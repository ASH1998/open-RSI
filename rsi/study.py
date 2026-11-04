"""Frozen MBPP study orchestration; all paid stages use the project ledger."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
from pathlib import Path

from .config import ROOT, load_local_env, model_config
from .pilot import stage, persist, remote_call, load_report, write_json, scores

STUDY = ROOT / 'studies' / 'mbpp_v1'
DATA = ROOT / 'data' / 'mbpp'
SETTINGS = {'seed': 42, 'temperature': 0.0, 'max_new_tokens': 512}
BATCH_SIZE = 32


def digest(value):
    from rsilab import digest as framework_digest
    return framework_digest(value)


def category(prompt):
    # Classify the task description, excluding the common import-policy preamble.
    text = (prompt.split('\n\n')[1] if '\n\n' in prompt else prompt).lower()
    if any(w in text for w in ('string', 'word', 'character', 'substring', 'vowel', 'regex')):
        return 'text'
    if any(w in text for w in ('list', 'tuple', 'array', 'matrix', 'dictionary', 'heap', 'sort')):
        return 'collections'
    if any(w in text for w in ('number', 'integer', 'prime', 'factor', 'digit', 'sum', 'triangle',
                               'area', 'perimeter', 'slope', 'quadratic', 'discriminant', 'lcm',
                               'fibonacci', 'volume', 'arc length', 'wind chill')):
        return 'numeric'
    return 'other'


def read_manifest():
    manifest = json.loads((DATA / 'study-v1.json').read_text())
    expected = manifest.pop('sha256')
    if digest(manifest) != expected:
        raise ValueError('Frozen study manifest hash mismatch')
    manifest['sha256'] = expected
    return manifest


def guard_study_envelope():
    ledger = json.loads((ROOT / 'budget' / 'ledger.json').read_text())
    spent = sum(x['reserved_usd'] for x in ledger['reservations'] if x['stage'].startswith('mbpp-'))
    if spent + 5 > 100:
        raise ValueError('This study reached its $100 reservation envelope; inspect before further launches')


def audit():
    """Audit reference behavior before task selection; never use references as SFT labels."""
    import modal
    from .datasets import load_mbpp, build_mbpp_pools
    from .mbpp_verification import convert_mbpp_task, convert_mbpp_tests, UnsupportedTest
    from .verification import verify_candidate
    rows = load_mbpp()
    pool = build_mbpp_pools(rows)
    raw = {r['task_id']: r for split in ('train', 'validation') for r in rows[split]}
    compiled, excluded = [], []
    for split in ('train', 'dev'):
        for task in pool['pools'][split]:
            try:
                converted = convert_mbpp_task(task)
                converted['category'] = category(task['prompt'])
                compiled.append(converted)
            except UnsupportedTest as exc:
                excluded.append({'id': task['id'], 'reason': str(exc)})
    guard_study_envelope()
    app = modal.App('open-rsi-mbpp-reference-audit', include_source=False)
    with stage('mbpp-reference-audit') as (report, run):
        report.update(pool_sha256=pool['manifest_sha256'], conversion_exclusions=excluded, records=[])
        with app.run():
            report['modal_app_id'] = app.app_id
            preflight = convert_mbpp_tests(['assert solve((1, 2)) == (1, 2)',
                                            'assert set(solve((3, 2))) == {2, 3}'], 'solve')
            report['verifier_preflight'] = verify_candidate('def solve(value):\n    return value', preflight, app)
            persist(report)
            if not report['verifier_preflight']['passed']:
                raise RuntimeError('Typed verifier preflight failed; do not audit dataset')
            with ThreadPoolExecutor(max_workers=4) as executor:
                pending = {executor.submit(verify_candidate, raw[t['metadata']['source_id']]['code'], t, app): t
                           for t in compiled}
                for future in as_completed(pending):
                    task = pending[future]
                    result = future.result()
                    report['records'].append({'task': task, 'verification': result})
                    persist(report)
                    if result.get('infrastructure_error') or result.get('error_kind') == 'invalid_task':
                        raise RuntimeError('Reference audit infrastructure failure; do not freeze this audit')
                    print(json.dumps({'audit_completed': len(report['records']), 'total': len(compiled),
                                      'id': task['id'], 'passed': result['passed']}), flush=True)
        report['scores'] = scores(report['records'])
        run.log({f'{s}/reference_pass_rate': v['rate'] for s, v in report['scores'].items()})


def freeze(audit_id):
    from .datasets import load_mbpp, build_mbpp_pools
    audit = load_report(audit_id)
    if audit['stage'] != 'mbpp-reference-audit':
        raise ValueError('Expected completed reference audit')
    pool = build_mbpp_pools(load_mbpp())
    if audit['pool_sha256'] != pool['manifest_sha256']:
        raise ValueError('Dataset importer changed after reference audit')
    reviewed = json.loads((STUDY / 'manual-exclusions.json').read_text())
    excluded_ids = {item['id'] for item in reviewed['exclusions']}
    good = {r['task']['id']: r['task'] for r in audit['records']
            if r['verification']['passed'] and r['task']['id'] not in excluded_ids}
    for task in good.values():
        task['category'] = category(task['prompt'])
    tasks = []
    for split, count in (('train', 128), ('dev', 48)):
        selected = [good[t['id']] for t in pool['pools'][split] if t['id'] in good][:count]
        if len(selected) != count:
            raise ValueError(f'Only {len(selected)} audited {split} tasks; need {count}')
        tasks.extend(selected)
    plan = json.loads((STUDY / 'protocol.json').read_text())
    manifest = {'study': 'mbpp-v1', 'audit_run': audit_id, 'pool_sha256': pool['manifest_sha256'],
                'analysis_plan_sha256': digest(plan), 'protocol': plan, 'tasks': tasks,
                'manual_review': reviewed,
                'generation_settings': SETTINGS, 'retention_ids': [t['id'] for t in tasks if t['split']=='train'][:32]}
    manifest['sha256'] = digest(manifest)
    path = DATA / 'study-v1.json'
    if path.exists() and json.loads(path.read_text()) != manifest:
        raise ValueError('Refusing to replace frozen study manifest')
    write_json(path, manifest)
    public = {'sha256': manifest['sha256'], 'analysis_plan_sha256': manifest['analysis_plan_sha256'],
              'audit_run': audit_id, 'counts': dict(Counter(t['split'] for t in tasks)),
              'categories': {s: dict(Counter(t['category'] for t in tasks if t['split']==s)) for s in ('train','dev')},
              'task_ids': [t['id'] for t in tasks], 'retention_ids': manifest['retention_ids']}
    write_json(STUDY / 'frozen-manifest-summary.json', public)
    print(json.dumps(public, indent=2))


def verify_outputs(tasks, generated, app, report):
    from .verification import verify_candidate, extract_code
    if generated['status'] != 'completed' or any(o.get('hit_time_limit') for o in generated['outputs']):
        raise ValueError('Incomplete generation cannot be scored')
    if [t['id'] for t in tasks] != [o['id'] for o in generated['outputs']]:
        raise ValueError('Generation identity/order mismatch')
    results = {}
    report['records'] = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        pending = {executor.submit(verify_candidate, o['text'], t, app): (t, o)
                   for t, o in zip(tasks, generated['outputs']) if not o.get('hit_token_limit')}
        for task, output in zip(tasks, generated['outputs']):
            if output.get('hit_token_limit'):
                results[task['id']] = {'task':task, 'generation':output, 'verification':{
                    'passed':False, 'count':0, 'total':len(task['cases']), 'errors':['generation_token_limit'],
                    'error_kind':'generation_limit', 'sandbox_id':None}}
        for future in as_completed(pending):
            task, output = pending[future]
            result = future.result()
            row = {'task': task, 'generation': output, 'verification': result}
            if result['passed']:
                row['verified_code'] = extract_code(output['text'])
            results[task['id']] = row
            report['records'] = [results[t['id']] for t in tasks if t['id'] in results]
            persist(report)
            if result.get('infrastructure_error') or result.get('error_kind') == 'invalid_task':
                raise RuntimeError('Verifier infrastructure failure; comparison is incomplete')
            print(json.dumps({'verified': len(results), 'total': len(tasks), 'id': task['id'], 'passed': result['passed']}), flush=True)
    report['records'] = [results[t['id']] for t in tasks]
    persist(report)
    return report['records']


def generate_batch(batch, training_id=None):
    from .mbpp_workers import app, generate
    if type(batch) is not int or batch < 0:
        raise ValueError('Batch index must be a nonnegative integer')
    manifest = read_manifest()
    settings = manifest['generation_settings']
    tasks = manifest['tasks']
    training = None
    if training_id:
        training = load_report(training_id)
        if training.get('study_sha256') != manifest['sha256'] or training['stage'] != 'mbpp-train':
            raise ValueError('Training run belongs to another study')
        tasks = [t for t in tasks if t['split']=='dev' or t['id'] in manifest['retention_ids']]
    tasks = tasks[batch*BATCH_SIZE:(batch+1)*BATCH_SIZE]
    if not tasks:
        raise ValueError('No tasks in requested batch')
    guard_study_envelope()
    name = 'mbpp-evaluate' if training else 'mbpp-baseline'
    with stage(name) as (report, run):
        report.update(study_sha256=manifest['sha256'], batch=batch, training_run=training_id,
                      generation_settings=settings, task_hash=digest(tasks))
        request = {**model_config(), **settings, 'prompts': [{'id': t['id'], 'prompt': t['prompt']} for t in tasks]}
        if training:
            request['adapter_path'] = training['training']['adapter_path']
        with app.run():
            report['modal_app_id'] = app.app_id
            report['generation'] = remote_call(generate, request, report)
            if report['generation']['gpu_name'] != 'NVIDIA L40S':
                raise ValueError('Worker hardware differs from the preregistered L40S')
            report['records'] = verify_outputs(tasks, report['generation'], app, report)
        report['scores'] = scores(report['records'])
        run.log({f'{s}/pass_rate': row['rate'] for s, row in report['scores'].items()})


def baseline_reports():
    manifest = read_manifest()
    selected = []
    for batch in range(math.ceil(len(manifest['tasks'])/BATCH_SIZE)):
        matches = []
        for path in sorted((ROOT/'runs').glob('*/report.json')):
            r = json.loads(path.read_text())
            if (r.get('stage')=='mbpp-baseline' and r.get('status')=='completed'
                    and r.get('study_sha256')==manifest['sha256'] and r.get('batch')==batch):
                matches.append(r)
        if len(matches) != 1:
            raise ValueError(f'Expected exactly one completed baseline for batch {batch}; found {len(matches)}')
        selected.append(matches[0])
    return selected


def train(seed):
    from .mbpp_workers import app, train as worker
    from .modal_workers import _encode_example
    from transformers import AutoTokenizer
    manifest = read_manifest()
    parents = baseline_reports()
    rows = [r for p in parents for r in p['records'] if r['task']['split']=='train' and r['verification']['passed']]
    # Deduplicate targets without introducing external/reference labels.
    unique = {}
    for row in rows:
        unique.setdefault(digest(row['verified_code']), row)
    rows = list(unique.values())
    counts = Counter(r['task']['category'] for r in rows)
    if len(rows)<32 or len(counts)<3 or max(counts.values(), default=0)/max(1,len(rows))>0.6:
        raise ValueError('Diversity gate failed: need 32 unique verified targets across 3 descriptive categories, none above 60%')
    examples = [{'prompt':r['task']['prompt'], 'completion':r['verified_code'], 'verified':True} for r in rows]
    tokenizer = AutoTokenizer.from_pretrained(**{'pretrained_model_name_or_path': model_config()['model_id'],
                 'revision': model_config()['revision'], 'local_files_only':True, 'token':False})
    tokenized = [_encode_example(tokenizer, x, 2048) for x in examples]
    steps = math.ceil(2*len(examples)/4)
    guard_study_envelope()
    with stage('mbpp-train') as (report, run):
        report.update(study_sha256=manifest['sha256'], baseline_runs=[p['run_id'] for p in parents], seed=seed,
                      selected_ids=[r['task']['id'] for r in rows], dataset_hash=digest(examples), examples_count=len(examples),
                      categories=dict(Counter(r['task']['category'] for r in rows)),
                      supervised_tokens=sum(sum(x!=-100 for x in t['labels']) for t in tokenized))
        with app.run():
            report['modal_app_id'] = app.app_id
            report['training'] = remote_call(worker, {**model_config(), 'run_id':report['run_id'], 'examples':examples,
                         'seed':seed, 'max_steps':steps, 'gradient_accumulation':4, 'max_length':2048,
                         'learning_rate':2e-5}, report)
        if report['training']['status']!='completed':
            raise RuntimeError('Training did not complete')
        for point in report['training']['losses']:
            run.log({'train/optimizer_step':point['step'], 'train/loss':point['loss']})
        run.log({'train/examples':len(examples), 'train/steps':steps})


def kaggle_prepare():
    from .kaggle_backend import prepare_kernel
    from kaggle.api.kaggle_api_extended import KaggleApi
    manifest = read_manifest()
    tasks = [t for t in manifest['tasks'] if t['split']=='dev'][:32]
    api = KaggleApi(); api.authenticate()
    request = {**model_config(), 'seed':42, 'max_new_tokens':512,
               'manifest_hash':manifest['sha256'],
               'prompts':[{'id':t['id'],'prompt':t['prompt']} for t in tasks]}
    result = prepare_kernel(request, ROOT/'work/kaggle-mbpp-v1', api.get_config_value('username'))
    print(json.dumps({'kernel':result['kernel'], 'source_sha256':result['source_sha256']}))


def kaggle_import(path):
    import modal
    manifest = read_manifest()
    generated = json.loads(Path(path).read_text())
    audit = json.loads((ROOT/'work/kaggle-mbpp-v1/upload-audit.json').read_text())
    if generated['request'] != audit['request'] or generated['request']['manifest_hash'] != manifest['sha256']:
        raise ValueError('Kaggle output request does not match frozen upload')
    tasks = [t for t in manifest['tasks'] if t['split']=='dev'][:32]
    guard_study_envelope()
    app = modal.App('open-rsi-mbpp-kaggle-verification', include_source=False)
    with stage('mbpp-kaggle-verify') as (report, run):
        report.update(study_sha256=manifest['sha256'], kaggle_kernel=audit['kernel'],
                      uploaded_source_sha256=audit['source_sha256'], generation=generated,
                      interpretation='Separate Kaggle baseline; not a matched Modal arm')
        with app.run():
            report['modal_app_id'] = app.app_id
            report['records'] = verify_outputs(tasks, generated, app, report)
        report['scores'] = scores(report['records'])
        run.log({'dev/pass_rate':report['scores']['dev']['rate']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['audit','freeze','baseline','train','evaluate','kaggle-prepare','kaggle-import'])
    parser.add_argument('--audit-run')
    parser.add_argument('--batch',type=int,default=0)
    parser.add_argument('--training-run')
    parser.add_argument('--seed',type=int,choices=[42,43],default=42)
    parser.add_argument('--output-file')
    args = parser.parse_args()
    load_local_env()
    if args.command=='audit': audit()
    elif args.command=='freeze': freeze(args.audit_run)
    elif args.command=='baseline': generate_batch(args.batch)
    elif args.command=='train': train(args.seed)
    elif args.command=='kaggle-prepare': kaggle_prepare()
    elif args.command=='kaggle-import':
        if not args.output_file: parser.error('--output-file required')
        kaggle_import(args.output_file)
    else:
        if not args.training_run: parser.error('--training-run required')
        generate_batch(args.batch,args.training_run)


if __name__=='__main__': main()
