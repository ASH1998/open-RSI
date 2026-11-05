"""Versioned execution adapter for the sealed lesson-pair protocol."""
import argparse
import json
from pathlib import Path

from rsi import repair_study as repair
from rsi.mbpp_verification_v2 import verify_mbpp_candidate
from rsi.verification import extract_code
from rsilab import digest
from rsilab.dataset_io import file_sha256
from rsilab.providers.modal import ModalBackend
from rsilab.providers.portable_modal_v3 import create_modal_workers
from rsilab.workflow import VerifiedCollector
from studies.lesson_pair_v1 import experiment as original

SCIENCE = '73cc79b2be12d046ced88ee3653ce431e30a00ab2bd6f6a31c8feecf5f74c02b'
DIRECTORY = Path('studies/lesson_pair_v2')
PLAN = DIRECTORY / 'plan.json'


def prepare(ws):
    scientific, history, tasks, examples = original.build()
    original.check(scientific == ws.read_json(original.PLAN) and scientific['sha256'] == SCIENCE,
                   'Original scientific plan differs')
    files = (DIRECTORY / 'experiment.py', DIRECTORY / 'README.md', original.PLAN,
             Path('studies/lesson_selection_v1/feasibility.json'))
    source_files = {**scientific['source_files'], **{str(f): file_sha256(ws.path(f)) for f in files}}
    plan = {**scientific, 'execution_revision': 2, 'scientific_plan_sha256': SCIENCE,
            'source_files': source_files,
            'source_hashes': {**history.plan['source_hashes'], **source_files}}
    del plan['sha256']
    plan['sha256'] = digest(plan)
    # Exercise the same scorer and evidence seals that run after training, using
    # a real archived return before reserving. No model output for either new arm.
    archive = history.completed('child-original')
    cfg = repair.settings(plan, 'evaluation', archive['training']['adapter_path'],
                          archive['training']['adapter_sha256'])
    old_tasks = history.evaluation_tasks()
    records, controls = repair.verify_returned(archive, plan, 'evaluation', old_tasks,
                                                repair.prompt_list(old_tasks), cfg, history.packages,
                                                history.manifests)
    original.check(len(records) == 25 and controls['runtime']['source_hashes'] == plan['source_hashes'],
                   'Historical scorer smoke check failed')
    return plan, history, tasks, examples


def run_arm(ws, plan, history, tasks, examples, arm):
    with ws.lock(original.STUDY):
        original.check(ws.read_json(PLAN) == plan and not list(ws.path('runs').glob(
            f'*-{original.STUDY}-{arm}-*/report.json')), 'Plan changed or arm already attempted')
        if arm == 'b':
            original.scores(ws, plan, history, tasks, examples, 'a', original.completed(ws, 'a'))
        with ws.stage(original.STUDY+'-'+arm, requested_usd=original.AMOUNT,
                      source_hashes=plan['source_files'],
                      report_fields=('plan_sha256','evidence_sha256','usage','metrics','export'),
                      metric_keys=('tasks','pass_count','output_tokens','input_tokens'),
                      upload_paths=(str(PLAN),), tracking_mode='online') as (report, tracking):
            report['plan_sha256'] = plan['sha256']
            ws.persist(report)
            with repair.stage_deadline(5400):
                tracking.upload_json(str(PLAN),artifact_name=report['run_id']+'-plan',artifact_type='study-input')
                workers = create_modal_workers(repair.worker_config(plan))
                original.check(workers.provenance == repair.worker_identity(plan), 'Worker changed')
                with workers.app.run():
                    report['modal_app_id'] = workers.app.app_id
                    ws.persist(report)
                    backend = ModalBackend(generate_function=workers.generate, train_function=workers.train,
                                           report=report,persist=ws.persist,max_calls=2)
                    report['training'] = backend.train({**plan['model'], **repair.TRAIN,
                        'run_id':report['run_id'], 'examples':examples[arm]})
                    ws.persist(report)
                    original.check_training(ws,plan,report,arm,examples[arm],history.packages)
                    original.export_checkpoint(ws,report)
                    original.check_export(ws,report,examples[arm])
                    def verify(code, task):
                        raw = verify_mbpp_candidate(code,task,workers.app)
                        return repair.score_result(history.manifests.get(task['id']),task,raw)
                    collector = VerifiedCollector(backend=backend,verify=verify,extract_code=extract_code,
                                                  report=report,persist=ws.persist)
                    cfg = repair.settings(plan,'evaluation',report['training']['adapter_path'],
                                          report['training']['adapter_sha256'])
                    collector.collect(tasks,settings=cfg,key='evaluation')
                    original.scores(ws,plan,history,tasks,examples,arm,report)
                repair.metrics(report,tracking,ws.read_json('config/budget.json')['rates_per_second'])
                report['evidence_sha256'] = repair.report_evidence_hash(report)
                ws.persist(report)
        return original.completed(ws,arm)['run_id']


def comparison(ws, plan, history, tasks, examples):
    records = {a:original.completed(ws,a) for a in original.ARMS}
    arms = {a:original.scores(ws,plan,history,tasks,examples,a,r) for a,r in records.items()}
    base = {r['task']['id']:r['verification']['passed'] for r in history.completed('baseline')['baseline']
            if r['task']['id'].startswith('mbpp-')}
    output = {'scientific_plan_sha256':SCIENCE,'plan_sha256':plan['sha256'],
              'runs':{a:r['run_id'] for a,r in records.items()},'arms':arms,'base_reused':base,
              'promoted':False,'rsi_established':False}
    for group, subset in (('exposed_development',tasks[:8]),('retention',tasks[9:])):
        ids = [t['id'] for t in subset]
        views = {k:{i:s[i] for i in ids} for k,s in {'base':base,**arms}.items()}
        output[group] = {name:repair.compare_passes(views[x],views[y]) for name,x,y in
                         (('b_vs_a','a','b'),('a_vs_base','base','a'),('b_vs_base','base','b'))}
    output['unused_task_575'] = {a:s['mbpp-full-575'] for a,s in arms.items()}
    repair.save_once(ws,f'artifacts/{original.STUDY}/comparison.json',output)
    return output


def main():
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument('action',choices=('freeze','preflight','arm-a','arm-b','report'))
    action = arg.parse_args().action
    original.check(Path.cwd().resolve() == original.ROOT, 'Run from the SSD')
    ws = original.PairWorkspace(original.ROOT)
    plan, history, tasks, examples = prepare(ws)
    if action == 'freeze' and not ws.path(PLAN).exists():
        ws.write_json(PLAN,plan)
    original.check(ws.read_json(PLAN)==plan,'Runtime addendum differs from the frozen plan')
    if action in ('freeze','preflight'):
        value = {'scientific_sha256':SCIENCE,'runtime_sha256':plan['sha256'],
                 'archived_scoring_replay':'passed','evaluation_tasks':len(tasks),
                 'maximum_direct_compute_per_arm':plan['max_direct_compute_usd_per_arm']}
    elif action.startswith('arm-'):
        value = {'run_id':run_arm(ws,plan,history,tasks,examples,action[-1])}
    else:
        value = comparison(ws,plan,history,tasks,examples)
    print(json.dumps(value,indent=2))


if __name__=='__main__':
    main()
