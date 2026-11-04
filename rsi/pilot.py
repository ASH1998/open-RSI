"""Budgeted first-pilot controller. Run with: python -m rsi.pilot --help."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from .budget import Budget
from .config import ROOT, load_local_env, model_config


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def provenance():
    source = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted((ROOT / 'rsi').glob('*.py'))}
    return {'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'source_hashes': source, 'model': model_config()}


@contextmanager
def stage(name):
    budget = Budget()
    reservation = budget.reserve(name, 5.0)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + name + '-' + uuid.uuid4().hex[:6]
    report_path = ROOT / 'runs' / run_id / 'report.json'
    report = {'run_id': run_id, 'stage': name, 'budget_reservation': reservation,
              'provenance': provenance(), 'started_at': datetime.now(timezone.utc).isoformat()}
    write_json(report_path, report)
    started = time.monotonic()
    run = None
    try:
        import wandb
        run = wandb.init(
            entity=os.environ['WANDB_ENTITY'], project=os.environ['WANDB_PROJECT'],
            mode='online', name=run_id, job_type=name,
            tags=['pilot', 'real-model', 'not-rsi-evidence'],
            config={'model': model_config(), 'stage': name, 'budget_reservation_usd': 5.0,
                    'git_commit': report['provenance']['git_commit']},
            settings=wandb.Settings(disable_code=True, disable_git=True, x_disable_meta=True,
                                    x_disable_stats=True, console='off', init_timeout=45),
        )
        report['wandb_url'] = run.url
        yield report, run
        report['status'] = 'completed'
        budget.finish(reservation, 'completed', {'run_id': run_id, 'app_id': report.get('modal_app_id'),
                      'wall_seconds': round(time.monotonic() - started, 2)})
    except BaseException as error:
        report['status'] = 'failed'
        report['error_type'] = type(error).__name__
        budget.finish(reservation, 'interrupted' if isinstance(error, KeyboardInterrupt) else 'failed',
                      {'run_id': run_id, 'error_type': type(error).__name__, 'app_id': report.get('modal_app_id')})
        raise
    finally:
        report['wall_seconds'] = time.monotonic() - started
        report['budget'] = budget.summary()
        write_json(report_path, report)
        if run:
            run.summary['status'] = report.get('status', 'failed')
            run.summary['wall_seconds'] = report['wall_seconds']
            # Explicit file upload: never auto-upload code, .env, or run directory.
            artifact = wandb.Artifact(run_id, type='pilot-report')
            artifact.add_file(str(report_path), name='report.json')
            run.log_artifact(artifact)
            run.finish(exit_code=0 if report.get('status') == 'completed' else 1)
        print(json.dumps({'run_id': run_id, 'status': report.get('status'),
                          'report': str(report_path), 'wandb_url': report.get('wandb_url'),
                          'budget': report['budget']}), flush=True)


def persist(report):
    write_json(ROOT / 'runs' / report['run_id'] / 'report.json', report)


def remote_call(function, request, report, seconds=2400):
    call = function.spawn(request)
    report['modal_call_id'] = call.object_id
    persist(report)
    try:
        return call.get(timeout=seconds)
    except BaseException:
        call.cancel(terminate_containers=True)
        raise


def load_report(value):
    path = (ROOT / 'runs' / value / 'report.json').resolve()
    if not path.is_relative_to(ROOT / 'runs'):
        raise ValueError('Run ID must refer to this project runs directory')
    report = json.loads(path.read_text())
    if report.get('status') != 'completed':
        raise ValueError('Source run did not complete')
    return report


def score_generation(tasks, generation, app, report):
    from .verification import verify_candidate, extract_code
    if generation.get('status') != 'completed' or any(x.get('hit_time_limit') for x in generation['outputs']):
        raise ValueError('Generation did not finish within its time budget; comparison is incomplete')
    outputs = generation['outputs']
    if [x['id'] for x in tasks] != [x['id'] for x in outputs]:
        raise ValueError('Model output task IDs/order do not match')
    records = []
    report['records'] = records
    for task, output in zip(tasks, outputs):
        result = verify_candidate(output['text'], task, app)
        record = {'task': task, 'generation': output, 'verification': result}
        if result['passed']:
            record['verified_code'] = extract_code(output['text'])
        records.append(record)
        persist(report)
        print(json.dumps({'task': task['id'], 'passed': result['passed'],
                          'errors': result['errors'][:2]}), flush=True)
        if result.get('infrastructure_error') or result.get('error_kind') == 'invalid_task':
            raise RuntimeError('Verifier infrastructure/task failure; comparison is incomplete')
    return records


def scores(records):
    result = {}
    for split in sorted({x['task']['split'] for x in records}):
        rows = [x for x in records if x['task']['split'] == split]
        passed = sum(x['verification']['passed'] for x in rows)
        result[split] = {'passed': passed, 'total': len(rows), 'rate': passed / len(rows)}
    return result


def smoke():
    from .modal_workers import app, smoke as worker
    from .verification import verify_candidate
    with stage('smoke') as (report, run):
        with app.run():
            report['modal_app_id'] = app.app_id
            report['generation'] = remote_call(worker, model_config(), report)
            task = {'id': 'addition-smoke', 'entry_point': 'add',
                    'cases': [{'args': [2, 3], 'expected': 5}, {'args': [-7, 2], 'expected': -5}]}
            report['verification'] = verify_candidate(report['generation']['outputs'][0]['text'], task, app)
            if not report['verification']['passed']:
                raise RuntimeError('Generated smoke solution failed isolated verification')
        run.log({'smoke/verified': 1, 'gpu/peak_memory_bytes': report['generation']['peak_gpu_memory_bytes']})


def baseline(count):
    from .modal_workers import app, generate
    from .tasks import build_tasks, SUITE_VERSION
    tasks = build_tasks('train', count_per_family=count, seed=42) + build_tasks('dev', count_per_family=count, seed=42)
    with stage('baseline') as (report, run):
        report.update(suite_version=SUITE_VERSION, task_hash=digest(tasks), count_per_family=count,
                      generation_settings={'seed': 42, 'temperature': 0.0, 'max_new_tokens': 512})
        with app.run():
            report['modal_app_id'] = app.app_id
            generated = remote_call(generate, {**model_config(), **report['generation_settings'],
                                    'prompts': [{'id': t['id'], 'prompt': t['prompt']} for t in tasks]}, report)
            report['generation'] = generated
            report['records'] = score_generation(tasks, generated, app, report)
        report['scores'] = scores(report['records'])
        run.log({f'{split}/pass_rate': row['rate'] for split, row in report['scores'].items()})


def train(parent_id, max_steps):
    from .modal_workers import app, train as worker
    parent = load_report(parent_id)
    if parent['stage'] != 'baseline':
        raise ValueError('Training requires a baseline report')
    examples = [{'prompt': r['task']['prompt'], 'completion': r['verified_code'], 'verified': True}
                for r in parent['records'] if r['task']['split'] == 'train' and r['verification']['passed']]
    if len(examples) < 4:
        raise ValueError('Fewer than four verified training examples; investigate data yield first')
    with stage('train') as (report, run):
        report.update(parent_run=parent_id, examples_count=len(examples), dataset_hash=digest(examples))
        with app.run():
            report['modal_app_id'] = app.app_id
            report['training'] = remote_call(worker, {**model_config(), 'examples': examples,
                          'run_id': report['run_id'], 'max_steps': max_steps,
                          'seed': 42, 'max_length': 2048, 'gradient_accumulation': 4}, report)
        if report['training']['status'] != 'completed':
            raise RuntimeError('Training stopped before completing the requested steps')
        for point in report['training']['losses']:
            run.log({'train/optimizer_step': point['step'], 'train/loss': point['loss']})
        run.log({'train/examples': len(examples), 'train/steps': report['training']['steps_completed']})


def evaluate(training_id):
    from .modal_workers import app, generate
    training = load_report(training_id)
    if training['stage'] != 'train':
        raise ValueError('Evaluation requires a training report')
    parent = load_report(training['parent_run'])
    tasks = [r['task'] for r in parent['records']]
    with stage('evaluate') as (report, run):
        report.update(parent_run=training['parent_run'], training_run=training_id,
                      task_hash=digest(tasks), parent_scores=parent['scores'],
                      generation_settings=parent['generation_settings'])
        with app.run():
            report['modal_app_id'] = app.app_id
            generated = remote_call(generate, {**model_config(), **parent['generation_settings'],
                       'adapter_path': training['training']['adapter_path'],
                       'prompts': [{'id': t['id'], 'prompt': t['prompt']} for t in tasks]}, report)
            report['generation'] = generated
            report['records'] = score_generation(tasks, generated, app, report)
        report['scores'] = scores(report['records'])
        report['promoted'] = False
        report['decision'] = 'Pilot comparison only; no automatic promotion without replication and a frozen acceptance protocol.'
        run.log({f'{split}/pass_rate': row['rate'] for split, row in report['scores'].items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['budget', 'smoke', 'baseline', 'train', 'evaluate'])
    parser.add_argument('--count-per-family', type=int, choices=range(1, 9), default=4)
    parser.add_argument('--parent-run')
    parser.add_argument('--training-run')
    parser.add_argument('--max-steps', type=int, choices=range(1, 41), default=20)
    args = parser.parse_args()
    load_local_env()
    if args.stage == 'budget':
        print(json.dumps(Budget().summary(), indent=2))
    elif args.stage == 'smoke':
        smoke()
    elif args.stage == 'baseline':
        baseline(args.count_per_family)
    elif args.stage == 'train':
        if not args.parent_run:
            parser.error('--parent-run is required for training')
        train(args.parent_run, args.max_steps)
    else:
        if not args.training_run:
            parser.error('--training-run is required for evaluation')
        evaluate(args.training_run)


if __name__ == '__main__':
    main()
