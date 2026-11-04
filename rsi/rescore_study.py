"""Re-evaluate immutable MBPP outputs; this module never invokes a model."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import fcntl
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .config import ROOT, load_local_env
from .pilot import stage, persist, write_json, scores
from .study import read_manifest, baseline_reports
from rsilab import digest

PLAN_PATH = ROOT / 'studies/mbpp_rescore_v2/protocol.json'
ARMS = ('parent', 'seed-42', 'seed-43', 'kaggle')
SOURCE_PATHS = ('rsi/mbpp_verification_v2.py', 'rsi/mbpp_verification.py',
                'rsi/verification.py', 'rsi/rescore_study.py', 'rsilab/rescore.py')


def source_hashes():
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCE_PATHS}


def original_reports():
    study = read_manifest()
    previous = json.loads((ROOT / 'artifacts/mbpp/reports/summary.json').read_text())
    if previous['study_sha256'] != study['sha256']:
        raise ValueError('Previous comparison belongs to another frozen study')
    all_reports = [json.loads(p.read_text()) for p in (ROOT/'runs').glob('*/report.json')]
    all_reports = [r for r in all_reports if r.get('study_sha256') == study['sha256']
                   and r.get('status') == 'completed']
    result = {'parent': baseline_reports()}
    for seed in (42, 43):
        training_id = previous['seeds'][str(seed)]['training_run_id']
        found = sorted([r for r in all_reports if r.get('stage') == 'mbpp-evaluate'
                        and r.get('training_run') == training_id], key=lambda r:r['batch'])
        if len(found) != 3 or [r['batch'] for r in found] != [0,1,2]:
            raise ValueError('Missing or duplicate original evaluation batch')
        result[f'seed-{seed}'] = found
    result['kaggle'] = [r for r in all_reports if r.get('stage') == 'mbpp-kaggle-verify']
    if len(result['kaggle']) != 1:
        raise ValueError('Need exactly one original Kaggle benchmark')
    expected = {'parent':176, 'seed-42':80, 'seed-43':80, 'kaggle':32}
    for arm, reports in result.items():
        rows = [x for r in reports for x in r['records']]
        if len(rows) != expected[arm] or len({x['task']['id'] for x in rows}) != len(rows):
            raise ValueError(f'Original task coverage mismatch: {arm}')
        for r in reports:
            if [x['generation'] for x in r['records']] != r['generation']['outputs']:
                raise ValueError('Original output identity mismatch')
            if any(x['generation'].get('hit_time_limit') for x in r['records']):
                raise ValueError('Incomplete original output')
    return result


def reference_inputs():
    from .datasets import load_mbpp
    raw = {r['task_id']:r for split,rows in load_mbpp().items()
           if split in ('train','validation') for r in rows}
    return [{'task':t, 'code':raw[t['metadata']['source_id']]['code']}
            for t in read_manifest()['tasks']]


def freeze():
    from .mbpp_verification_v2 import MBPP_VERIFIER_VERSION, evaluator_source_hashes
    sources = original_reports()
    plan = {
        'study': 'mbpp-rescore-v2', 'parent_study_sha256':read_manifest()['sha256'],
        'classification':'Post-hoc evaluator correction, not new generation or prospective training evidence',
        'evaluator_version':MBPP_VERIFIER_VERSION, 'evaluator_source_hashes':evaluator_source_hashes(),
        'execution_source_hashes':source_hashes(),
        'source_reports': {arm:[{'run_id':r['run_id'], 'sha256':digest(r)} for r in reports]
                           for arm,reports in sources.items()},
        'counts': {'parent':176,'seed-42':80,'seed-43':80,'kaggle':32},
        'reference_inputs_sha256':digest(reference_inputs()),
        'preserved':'Original tasks, authoritative cases, prompts, generation text, token limits, model checkpoints and v1 outcomes',
        'execution':'Re-execute every non-truncated output independently in credential-free network-blocked Modal CPU sandboxes; never execute candidates locally',
        'reference_gate':'Hand-authored positive/negative calibration then all 176 original reference solutions must pass before saved candidate execution',
        'infrastructure':'Abort incomplete stages on transport, invalid-task or termination failures. Never count them as model errors.',
        'maximum_sandboxes_per_stage':4, 'maximum_parallel_stages':2,
        'stage_reservation_usd':5, 'total_planned_reservations_usd':20,
        'no_training':True, 'no_promotion':True,
        'comparison':'Report old/new outcomes and changes for every arm. Pair Modal parent/adapters on unchanged 48 dev and 32 retention tasks. Report Kaggle separately.',
    }
    plan['sha256'] = digest(plan)
    if PLAN_PATH.exists() and json.loads(PLAN_PATH.read_text()) != plan:
        raise ValueError('Refusing to replace frozen rescore protocol')
    write_json(PLAN_PATH, plan)
    print(json.dumps({'protocol':str(PLAN_PATH),'sha256':plan['sha256'],'counts':plan['counts']}))


def load_plan():
    plan = json.loads(PLAN_PATH.read_text())
    if digest({k:v for k,v in plan.items() if k!='sha256'}) != plan['sha256']:
        raise ValueError('Rescore protocol hash mismatch')
    if plan['execution_source_hashes'] != source_hashes():
        raise ValueError('Evaluator/controller/reporting source changed after freeze')
    from .mbpp_verification_v2 import evaluator_source_hashes
    if plan['evaluator_source_hashes'] != evaluator_source_hashes():
        raise ValueError('Evaluator payload changed after freeze')
    sources = original_reports()
    actual = {arm:[{'run_id':r['run_id'],'sha256':digest(r)} for r in reports]
              for arm,reports in sources.items()}
    if actual != plan['source_reports']:
        raise ValueError('Original saved evidence changed after freeze')
    return plan, sources


def calibration():
    from .mbpp_verification import convert_mbpp_tests
    from .mbpp_verification_v2 import calibration_cases
    cases = [
        ('ordered_dict_positive', 'from collections import OrderedDict\ndef solve():\n return OrderedDict([(2,3),(1,4)])', 'assert solve() == {1:4,2:3}', True),
        ('ordered_dict_negative', 'from collections import OrderedDict\ndef solve():\n return OrderedDict([(2,3),(1,5)])', 'assert solve() == {1:4,2:3}', False),
        ('nested_mapping_positive', 'from collections import OrderedDict, defaultdict, Counter\ndef solve():\n return [OrderedDict(a=1), defaultdict(int,b=2), Counter(c=3)]', "assert solve() == [{'a':1},{'b':2},{'c':3}]", True),
        ('counter_zero_negative', 'from collections import Counter\ndef solve():\n return Counter(a=0)', 'assert solve() == {}', False),
        ('tuple_list_negative', 'def solve():\n return (1,2)', 'assert solve() == [1,2]', False),
        ('set_projection_positive', 'def solve():\n return [2,1,2]', 'assert set(solve()) == {1,2}', True),
    ]
    return calibration_cases() + [{'id':name,'code':code,'task':convert_mbpp_tests([test], 'solve'),'expected_passed':passed}
            for name,code,test,passed in cases]


def checked(result):
    if result.get('infrastructure_error') or result.get('error_kind') in ('infrastructure','invalid_task'):
        raise RuntimeError('Verifier infrastructure/task failure; this rescore is incomplete')
    return result


def audit(app, report, plan):
    from .mbpp_verification_v2 import verify_mbpp_candidate
    report['calibration'] = []
    for item in calibration():
        result = checked(verify_mbpp_candidate(item['code'], item['task'], app))
        report['calibration'].append({**item,'verification':result})
        persist(report)
        if result['passed'] is not item['expected_passed'] or ('expected_count' in item and result['count'] != item['expected_count']):
            raise RuntimeError('Evaluator calibration failed')
        if item.get('expected_error_stage') and (not result.get('outputs') or not all(x.get('error_stage')==item['expected_error_stage'] for x in result['outputs'])):
            raise RuntimeError('Evaluator calibration diagnostic mismatch')
    refs = reference_inputs()
    if digest(refs) != plan['reference_inputs_sha256']:
        raise ValueError('Reference code or frozen cases changed')
    report['reference_audit'] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(verify_mbpp_candidate, item['code'], item['task'], app):item for item in refs}
        for future in as_completed(futures):
            item=futures[future];result=checked(future.result())
            report['reference_audit'].append({'task_id':item['task']['id'],
                 'reference_sha256':hashlib.sha256(item['code'].encode()).hexdigest(),'verification':result})
            persist(report)
            if not result['passed']:
                raise RuntimeError('Reference compatibility failed; do not rescore candidates')
            print(json.dumps({'reference_verified':len(report['reference_audit']),'total':len(refs)}),flush=True)
    report['reference_audit_passed'] = True
    persist(report)


def completed_stage(arm, plan):
    matches=[]
    for p in (ROOT/'runs').glob('*/report.json'):
        r=json.loads(p.read_text())
        if r.get('stage')=='mbpp-rescore-v2' and r.get('arm')==arm and r.get('rescore_protocol_sha256')==plan['sha256']:
            matches.append(r)
    if len(matches)!=1 or matches[0].get('status')!='completed':
        raise ValueError(f'Need exactly one completed rescore stage for {arm}')
    return matches[0]


@contextmanager
def arm_lock(arm):
    path=ROOT/'work'/f'rescore-{arm}.lock'
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a') as handle:
        try:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('Rescore arm already has an active controller') from exc
        try:yield
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def run_arm(arm):
    if arm not in ARMS:raise ValueError('Unknown rescore arm')
    with arm_lock(arm):
        _run_arm(arm)


def _run_arm(arm):
    import modal
    from .mbpp_verification_v2 import verify_mbpp_candidate
    plan,sources=load_plan()
    # Refuse accidental repeated launches, including unfinished attempts.
    for p in (ROOT/'runs').glob('*/report.json'):
        r=json.loads(p.read_text())
        if r.get('stage')=='mbpp-rescore-v2' and r.get('arm')==arm and r.get('rescore_protocol_sha256')==plan['sha256']:
            raise ValueError('Rescore stage already exists; inspect/recover it instead of duplicating')
    parent=None
    if arm!='parent':
        parent=completed_stage('parent',plan)
        if parent.get('reference_audit_passed') is not True:
            raise ValueError('Reference gate has not passed')
    with stage('mbpp-rescore-v2') as (report,run):
        report.update(arm=arm,study_sha256=plan['parent_study_sha256'],rescore_protocol_sha256=plan['sha256'],
                      evaluator_version=plan['evaluator_version'],evaluator_source_hashes=plan['evaluator_source_hashes'],
                      reference_audit_run=parent['run_id'] if parent else None,rescores=[])
        for source in sources[arm]:
            run.use_artifact(f"{run.entity}/{run.project}/{source['run_id']}:latest",type='pilot-report')
        app=modal.App('open-rsi-mbpp-rescore-v2',include_source=False)
        with app.run():
            report['modal_app_id']=app.app_id;persist(report)
            if arm=='parent':audit(app,report,plan)
            pending_records={}
            for source in sources[arm]:
                part={'stage':'mbpp-rescore-v2','status':'running','source_run_id':source['run_id'],
                      'source_report_sha256':digest(source),'study_sha256':plan['parent_study_sha256'],
                      'evaluator_version':plan['evaluator_version'],'evaluator_source_hashes':plan['evaluator_source_hashes'],
                      'rescore_protocol_sha256':plan['sha256'],'records':[]}
                report['rescores'].append(part)
                pending_records[source['run_id']]={}
            def save_record(part,old,result):
                pending_records[part['source_run_id']][old['task']['id']]={
                    'task':deepcopy(old['task']),'generation':deepcopy(old['generation']),
                    'original_verification':deepcopy(old['verification']),'verification':result}
                source=next(s for s in sources[arm] if s['run_id']==part['source_run_id'])
                part['records']=[pending_records[source['run_id']][r['task']['id']] for r in source['records']
                                 if r['task']['id'] in pending_records[source['run_id']]]
                persist(report)
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures={}
                for source,part in zip(sources[arm],report['rescores']):
                    for row in source['records']:
                        if row['generation'].get('hit_token_limit'):
                            save_record(part,row,deepcopy(row['verification']))
                        else:
                            futures[pool.submit(verify_mbpp_candidate,row['generation']['text'],row['task'],app)]=(part,row)
                for future in as_completed(futures):
                    part,row=futures[future];result=checked(future.result());save_record(part,row,result)
                    n=sum(len(x['records']) for x in report['rescores'])
                    print(json.dumps({'arm':arm,'rescored':n,'total':plan['counts'][arm],
                                      'task':row['task']['id'],'passed':result['passed']}),flush=True)
            for part in report['rescores']:part['status']='completed'
            persist(report)
        rows=[x for p in report['rescores'] for x in p['records']]
        if len(rows)!=plan['counts'][arm]:raise ValueError('Incomplete rescore stage')
        report['scores']=scores(rows)
        report['changed_task_ids']=[r['task']['id'] for r in rows if r['verification']['passed']!=r['original_verification']['passed']]
        run.log({f'{split}/pass_rate':v['rate'] for split,v in report['scores'].items()})
        run.summary['arm']=arm
        run.summary['changed_outcomes']=len(report['changed_task_ids'])


def aggregate():
    from rsilab.rescore import audit_rescores
    from .mbpp_verification_v2 import score_mbpp_outputs
    plan,sources=load_plan()
    stages=[completed_stage(arm,plan) for arm in ARMS]
    if stages[0].get('reference_audit_passed') is not True:
        raise ValueError('Reference gate missing')
    for result in stages[1:]:
        if result.get('reference_audit_run')!=stages[0]['run_id']:
            raise ValueError('Reference audit lineage differs between arms')
    parts=[p for result in stages for p in result['rescores']]
    # Recompute authoritative scores from bounded typed evidence, not supplied flags.
    for part in parts:
        for row in part['records']:
            verification=row['verification']
            if row['generation']['hit_token_limit']:
                continue
            value=score_mbpp_outputs(verification.get('outputs'),row['task']['cases'])
            if verification['passed'] is not value['passed'] or verification['count']!=value['count']:
                raise ValueError('Saved rescore flags contradict trusted v2 scoring')
    originals=[r for arm in ARMS for r in sources[arm]]
    training_ids={r['training_run'] for arm in ('seed-42','seed-43') for r in sources[arm]}
    training=[json.loads((ROOT/'runs'/rid/'report.json').read_text()) for rid in sorted(training_ids)]
    result=audit_rescores(read_manifest(),originals,parts,training_reports=training,
                          rescore_protocol_sha256=plan['sha256'])
    result['grouped_stage_runs']=[{'run_id':r['run_id'],'arm':r['arm'],'sha256':digest(r),'wandb_url':r['wandb_url']} for r in stages]
    result['reference_audit']={'run_id':stages[0]['run_id'],'passed':True,
                               'count':len(stages[0]['reference_audit']),
                               'calibration_count':len(stages[0]['calibration'])}
    result['trusted_outputs_rescored']=True
    result['budget']=stages[-1]['budget']
    path=ROOT/'artifacts/mbpp-rescore-v2/summary.json'
    if path.exists() and json.loads(path.read_text())!=result:
        raise ValueError('Refusing to overwrite different aggregate results')
    write_json(path,result)
    print(json.dumps({'path':str(path),'total':result['total_records'],'changes':result['changes'],
                      'paired':{seed:r['scores'] for seed,r in result['paired'].items()},
                      'kaggle':result['kaggle']},indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['freeze','run','report'])
    parser.add_argument('--arm',choices=ARMS)
    args=parser.parse_args();load_local_env()
    if args.command=='freeze':freeze()
    elif args.command=='report':aggregate()
    else:
        if not args.arm:parser.error('--arm is required')
        run_arm(args.arm)

if __name__=='__main__':main()
