"""Frozen post-hoc stronger-case diagnostic; never generates or trains models."""
from __future__ import annotations
import argparse
import hashlib
import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from rsilab import digest
from .config import ROOT, load_local_env
from .pilot import stage, persist, write_json
from .rescore_study import load_plan as load_rescore_plan, reference_inputs, arm_lock
from .mbpp_verification_v2 import evaluator_source_hashes, verify_mbpp_candidate, score_mbpp_outputs

PLAN = ROOT / 'studies/mbpp_robustness_v1/protocol.json'
STAGE = 'robustness-v1-validate'


def source_hashes():
    names = ('rsi/robustness_study.py', 'rsi/mbpp_robustness.py', 'rsilab/execution.py',
             'rsi/pilot.py', 'rsi/budget.py', 'rsi/config.py', 'rsi/rescore_study.py',
             'rsi/study.py', 'rsi/datasets.py', 'rsilab/core.py', 'config/budget.json')
    return {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in names}


def inputs():
    from .mbpp_robustness import build_tasks
    previous, sources = load_rescore_plan()
    refs = reference_inputs()
    tasks = build_tasks([x['task'] for x in refs])
    by_original = {t['metadata']['original_task_id']:t for t in tasks}
    if len(by_original) != len(tasks) or not tasks:
        raise ValueError('Diagnostic tasks must have distinct original identities')
    old_summary = json.loads((ROOT/'artifacts/mbpp-rescore-v2/summary.json').read_text())
    if old_summary['rescore_protocol_sha256'] != previous['sha256']:
        raise ValueError('Wrong previous correction summary')
    corrected = {(r['arm'],r['task_id']):r for r in old_summary['records']}
    references = [{'id':'reference/'+r['task']['id'], 'original_task_id':r['task']['id'],
                   'task':by_original[r['task']['id']], 'code':r['code']}
                  for r in refs if r['task']['id'] in by_original]
    candidates=[]
    for arm,reports in sources.items():
        for report in reports:
            for row in report['records']:
                tid=row['task']['id']
                if tid not in by_original: continue
                baseline=corrected[(arm,tid)]
                if baseline['generation_sha256'] != digest(row['generation']):
                    raise ValueError('Corrected and original generation differ')
                candidates.append({'id':arm+'/'+tid, 'arm':arm, 'original_task_id':tid,
                    'source_run_id':report['run_id'], 'source_record_sha256':digest(row),
                    'task':by_original[tid], 'generation':deepcopy(row['generation']),
                    'previous_verification':deepcopy(baseline['verification'])})
    return tasks,references,candidates,previous,old_summary


def expected_plan():
    tasks,refs,candidates,previous,old_summary=inputs()
    return {'study':'mbpp-robustness-v1', 'classification':'Post-hoc selected-task diagnostic, not held-out evaluation or training data',
        'previous_protocol_sha256':previous['sha256'], 'previous_summary_sha256':digest(old_summary),
        'execution_source_hashes':source_hashes(), 'evaluator_source_hashes':evaluator_source_hashes(),
        'tasks_sha256':digest(tasks), 'references_sha256':digest(refs), 'candidates_sha256':digest(candidates),
        'task_ids':[t['id'] for t in tasks], 'reference_count':len(refs), 'candidate_count':len(candidates),
        'counts_by_arm':{arm:sum(c['arm']==arm for c in candidates) for arm in ('parent','seed-42','seed-43','kaggle')},
        'cases':{t['metadata']['original_task_id']:len(t['cases']) for t in tasks},
        'reference_gate':'Every pinned reference must pass all original and additional cases before saved candidate execution',
        'infrastructure':'Persist every returned result before validation; stop submissions on failure, cancel queued tasks, drain running tasks, retain missing IDs; no automatic retry',
        'budget':{'reservation_usd':5,'maximum_stages':1,'maximum_workers':4,'project_cap_usd':250},
        'no_generation':True,'no_training':True,'no_promotion':True,
        'interpretation':'Preserve previous 368-outcome scores. Report these selected-task diagnostics separately; task selection was informed by observed failures.'}


def freeze():
    plan=expected_plan();plan['sha256']=digest(plan)
    if PLAN.exists() and json.loads(PLAN.read_text())!=plan:
        raise ValueError('Refusing to change frozen diagnostic protocol')
    write_json(PLAN,plan)
    print(json.dumps({'protocol_sha256':plan['sha256'],'references':plan['reference_count'],'candidates':plan['candidate_count'],'cases':plan['cases']}))


def load_plan():
    plan=json.loads(PLAN.read_text())
    if digest({k:v for k,v in plan.items() if k!='sha256'})!=plan['sha256']:
        raise ValueError('Protocol hash mismatch')
    if expected_plan()!={k:v for k,v in plan.items() if k!='sha256'}:
        raise ValueError('Frozen source or inputs changed')
    return plan


def validate_result(result, *, reference=False):
    if result.get('infrastructure_error') or result.get('error_kind') in ('infrastructure','invalid_task'):
        raise ValueError('Infrastructure or task failure; diagnostic incomplete')
    if reference and result.get('passed') is not True:
        raise ValueError('Reference compatibility failure; candidates blocked')


def run_group(items, report, key, execute, *, reference=False):
    from rsilab.execution import execute_bounded, ExecutionAborted
    saved={}
    def save(record):
        saved[record.item_id]=asdict(record)
        report[key]=[saved[x['id']] for x in items if x['id'] in saved]
        persist(report)
    def validate(item,result):
        validate_result(result,reference=reference)
    try:
        summary=execute_bounded(items,identify=lambda x:x['id'],execute=execute,
            persist=save,validate=validate,max_workers=4,max_in_flight=4)
    except ExecutionAborted as exc:
        report[key+'_execution']=asdict(exc.summary)
        persist(report)
        raise
    report[key+'_execution']=asdict(summary)
    persist(report)


def run():
    with arm_lock('robustness-v1'):
        plan=load_plan()
        for p in (ROOT/'runs').glob('*/report.json'):
            prior=json.loads(p.read_text())
            if prior.get('stage')==STAGE:
                raise ValueError('Diagnostic attempt already exists; inspect evidence rather than launch duplicate work')
        tasks,refs,candidates,_,_=inputs()
        import modal
        with stage(STAGE) as (report,tracking):
            report.update(protocol_sha256=plan['sha256'],evaluator_source_hashes=plan['evaluator_source_hashes'],
                tasks=tasks,reference_inputs=refs,candidate_inputs=candidates,reference_audit_passed=False,
                no_training=True,no_generation=True,promoted=False)
            tracking.use_artifact(f'{tracking.entity}/{tracking.project}/mbpp-evaluator-v2-rescore:latest',type='evaluator-correction')
            app=modal.App('open-rsi-robustness-v1',include_source=False)
            with app.run():
                report['modal_app_id']=app.app_id;persist(report)
                run_group(refs,report,'references',lambda r:verify_mbpp_candidate(r['code'],r['task'],app),reference=True)
                report['reference_audit_passed']=True;persist(report)
                def verify(row):
                    if row['generation'].get('hit_token_limit'):
                        return {'passed':False,'count':0,'total':len(row['task']['cases']),
                                'preserved_token_limit':True,'reason':'Original truncated generation is never re-executed'}
                    return verify_mbpp_candidate(row['generation']['text'],row['task'],app)
                run_group(candidates,report,'candidates',verify)
            report['diagnostic_summary']=summarize(report,plan)
            for arm,score in report['diagnostic_summary']['arms'].items():
                tracking.log({f'{arm}/diagnostic_passed':score['passed'],f'{arm}/diagnostic_total':score['total']})
            tracking.summary['interpretation']='post_hoc_diagnostic_no_training'


def summarize(report,plan):
    if report.get('reference_audit_passed') is not True:
        raise ValueError('Reference gate not satisfied')
    tasks,refs,candidates,_,_=inputs()
    if report.get('reference_inputs')!=refs or report.get('candidate_inputs')!=candidates or report.get('tasks')!=tasks:
        raise ValueError('Saved inputs differ from frozen protocol')
    rows=[]
    for key,expected in (('references',refs),('candidates',candidates)):
        records=report.get(key,[])
        if [r['item_id'] for r in records]!=[r['id'] for r in expected]:
            raise ValueError('Incomplete or duplicated diagnostic output coverage')
        for record,item in zip(records,expected):
            if record.get('status')!='returned':raise ValueError('Incomplete execution record')
            result=record['result'];validate_result(result,reference=key=='references')
            if key=='candidates' and item['generation'].get('hit_token_limit'):
                if result.get('preserved_token_limit') is not True or result.get('passed') is not False:
                    raise ValueError('Truncation handling changed')
            else:
                if result.get('evaluator_source_hashes')!=plan['evaluator_source_hashes']:
                    raise ValueError('Wrong evaluator identity')
                if result.get('outputs') is not None:
                    from .verification import extract_code
                    code=item['code'] if key=='references' else item['generation']['text']
                    if result.get('candidate_sha256')!=hashlib.sha256(extract_code(code).encode()).hexdigest():
                        raise ValueError('Verification belongs to different code')
                    if result.get('source_tests_sha256')!=item['task']['source_tests_sha256']:
                        raise ValueError('Verification belongs to different assertions')
                recomputed=score_mbpp_outputs(result.get('outputs'),item['task']['cases'])
                if (result.get('passed'),result.get('count'))!=(recomputed['passed'],recomputed['count']):
                    raise ValueError('Saved verification contradicts authoritative scoring')
            if key=='candidates':
                boundary=item['task']['metadata']['robustness']['original_case_count']
                outputs=result.get('outputs')
                original_score=score_mbpp_outputs(outputs[:boundary] if isinstance(outputs,list) else None,item['task']['cases'][:boundary])
                added_score=score_mbpp_outputs(outputs[boundary:] if isinstance(outputs,list) else None,item['task']['cases'][boundary:])
                truncated=bool(item['generation'].get('hit_token_limit'))
                rows.append({'arm':item['arm'],'task_id':item['original_task_id'],
                    'previous_passed':item['previous_verification']['passed'],'passed':result['passed'],
                    'passed_cases':result['count'],'total_cases':result['total'],
                    'original_cases_rerun_passed':None if truncated else original_score['passed'],
                    'original_cases_rerun_count':None if truncated else original_score['count'],
                    'additional_cases_passed':None if truncated else added_score['passed'],
                    'additional_cases_count':None if truncated else added_score['count'],
                    'original_case_count':boundary,'additional_case_count':len(item['task']['cases'])-boundary,
                    'preserved_token_limit':truncated,
                    'source_run_id':item['source_run_id'],'generation_sha256':digest(item['generation'])})
    arms={arm:{'passed':sum(r['passed'] for r in rows if r['arm']==arm),
               'previous_passed':sum(r['previous_passed'] for r in rows if r['arm']==arm),
               'total':sum(r['arm']==arm for r in rows)} for arm in ('parent','seed-42','seed-43','kaggle')}
    return {'protocol_sha256':plan['sha256'],'reference_count':len(refs),'candidate_count':len(rows),
            'arms':arms,'rows':rows,'interpretation':plan['interpretation'],'training_performed':False,'promoted':False}


def aggregate():
    from .budget import Budget
    plan=load_plan()
    matches=[json.loads(p.read_text()) for p in (ROOT/'runs').glob('*/report.json')
             if json.loads(p.read_text()).get('stage')==STAGE]
    if len(matches)!=1 or matches[0].get('status')!='completed':
        raise ValueError('Need exactly one completed diagnostic stage')
    r=matches[0]
    if r.get('protocol_sha256')!=plan['sha256']:raise ValueError('Wrong diagnostic protocol')
    result=summarize(r,plan)
    result.update(run_id=r['run_id'],wandb_url=r['wandb_url'],report_sha256=digest(r),budget=Budget().summary())
    path=ROOT/'artifacts/mbpp-robustness-v1/summary.json'
    if path.exists() and json.loads(path.read_text())!=result:raise ValueError('Refusing to change saved diagnostic summary')
    write_json(path,result);print(json.dumps(result,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('freeze','run','report'))
    args=parser.parse_args();load_local_env()
    {'freeze':freeze,'run':run,'report':aggregate}[args.command]()

if __name__=='__main__':main()
