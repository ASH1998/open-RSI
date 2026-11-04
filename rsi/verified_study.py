"""Project adapter for the reusable rsilab verified-data learning workflow.

All paid launches use the global project ledger and an immutable four-stage cap.
Use --help; no computation starts at import time.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path,PurePosixPath

from rsilab import digest
from rsilab.workflow import VerifiedCollector,verify_records,check_verification
from rsilab.providers.modal import ModalBackend
from rsilab.learning import LearningPolicy,AttemptLedger,build_repair_prompt,select_verified_targets,compare_learning_run
from .config import ROOT,model_config
from .pilot import write_json
import fcntl
from .mbpp_verification_v2 import verify_mbpp_candidate,score_mbpp_outputs,evaluator_source_hashes
from .verification import extract_code,validate_code
from .mbpp_verification import MBPP_ALLOWED_IMPORTS

DIRECTORY=ROOT/'studies/verified_sft_v1'
DATA=ROOT/'data/verified-sft-v1'
ARTIFACTS=ROOT/'artifacts/verified-sft-v1'
PREFIX='verified-sft-v1-'


def configure_workspace(root):
    global ROOT,DIRECTORY,DATA,ARTIFACTS
    ROOT=Path(root).resolve()
    if not ROOT.is_dir():raise ValueError('Project workspace is unavailable')
    DIRECTORY=ROOT/'studies/verified_sft_v1';DATA=ROOT/'data/verified-sft-v1';ARTIFACTS=ROOT/'artifacts/verified-sft-v1'


def workspace():
    from rsilab.project import Workspace
    return Workspace(ROOT)


def load_local_env():workspace().load_env()
def persist(report):workspace().persist(report)
def stage(name):
    fields={'protocol_sha256','study','policy','source_hashes','prepared_sha256','audited_dataset_sha256',
            'original_reference_audit','original_reference_audit_execution','mutation_reference_audit',
            'mutation_reference_audit_execution','reference_audits','remote_calls','scores','initial_run',
            'attempt_ledger_sha256','selection','seed','selection_sha256','examples_count','supervised_tokens',
            'training','export','comparison'}
    for key in ('initial_attempts','parent_evaluation','sample_attempts','repair_attempts','candidate_evaluation'):
        fields.update((key,key+'_batches'))
        for offset in (0,64):fields.update((f'{key}_verification_{offset}',f'{key}_verification_{offset}_execution'))
    metrics=('parent/train/pass_rate','parent/dev/pass_rate','data/targets','data/eligible',
             'train/optimizer_step','train/loss','dev/net_gain','replication/promising')
    return workspace().stage(name,source_paths=tuple(source_hashes()),report_fields=fields,
            metric_keys=metrics,upload_paths=(DATA/'audited-dataset.json',),tracking_mode='online')


@contextmanager
def arm_lock(name):
    path=ROOT/'work'/f'{name}.lock';path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Experiment controller already active') from None
        try:yield
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def policy():return json.loads((ROOT/'config/verified_sft_v1.json').read_text())
def learning_policy():return LearningPolicy(retention_count=policy()['retention_count'])
def source_hashes():
    paths=('rsi/verified_study.py','rsi/verified_workers.py','rsi/modal_workers.py','rsi/pilot.py','rsi/budget.py',
           'rsi/config.py','rsi/datasets.py','rsilab/coding_data.py','rsilab/learning.py','rsilab/workflow.py',
           'rsilab/execution.py','rsilab/providers/modal.py','rsilab/project.py','rsilab/learning_commands.py','rsilab/core.py','config/verified_sft_v1.json','requirements-gpu.txt')
    return {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}


def save_immutable(path,value):
    if path.exists() and json.loads(path.read_text())!=value:raise ValueError('Refusing to overwrite frozen evidence: '+path.name)
    write_json(path,value)


def prepare():
    from .datasets import load_mbpp
    from rsilab.coding_data import select_mbpp_tasks,propose_mutations
    old=json.loads((ROOT/'data/mbpp/study-v1.json').read_text())
    if digest({k:v for k,v in old.items() if k!='sha256'})!=old['sha256']:raise ValueError('Historical manifest changed')
    retention=[deepcopy(t) for tid in old['retention_ids'][:policy()['retention_count']] for t in old['tasks'] if t['id']==tid]
    review_file=json.loads((DIRECTORY/'domain-review.json').read_text())
    reviews={r['task_id']:r for r in review_file['reviews'] if r['approved']}
    pool=json.loads((ROOT/'data/mbpp/pools-full-seed42.json').read_text())
    selection=select_mbpp_tasks(pool,previous_tasks=old['tasks'],eligible_ids=reviews,train_excluded_ids=[t['id'] for t in retention],train_count=policy()['train_count'],dev_count=policy()['dev_count'])
    candidates=audit_tasks(selection)
    raw={r['task_id']:r for split,rows in load_mbpp(ROOT/'data/mbpp').items() if split in ('train','validation') for r in rows}
    items=[]
    for t in candidates:
        proposal=propose_mutations(t);code=raw[t['metadata']['source_id']]['code'];review=reviews[t['id']]
        validate_code(extract_code(code),t['entry_point'],allowed_imports=MBPP_ALLOWED_IMPORTS)
        identity={'task_sha256':digest(t),'proposal_sha256':proposal['sha256'],'reference_sha256':hashlib.sha256(extract_code(code).encode()).hexdigest()}
        if any(review.get(k)!=v for k,v in identity.items()):raise ValueError('Independent domain review identity differs: '+t['id'])
        items.append({'id':t['id'],'task':t,'proposal':proposal,'reference_code':code,'review':review,**identity})
    prepared={'selection':selection,'reference_items':items,'retention_tasks':retention,'review_file_sha256':digest(review_file)}
    prepared['sha256']=digest(prepared);save_immutable(DATA/'prepared.json',prepared)
    plan={'study':'verified-sft-v1','prepared_sha256':prepared['sha256'],'source_hashes':source_hashes(),
          'evaluator_source_hashes':evaluator_source_hashes(),'policy':policy(),'learning_policy':learning_policy().to_dict(),
          'model':model_config(),'reference_pool_count':len(items),'retention_ids':[t['id'] for t in retention],
          'final_evaluation':selection['sealed_final'],'interpretation':'Prospective native-split self-training study; previously exposed dev tasks disclosed; reference-derived extra tests; final split untouched'}
    plan['sha256']=digest(plan);save_immutable(DIRECTORY/'protocol.json',plan)
    print(json.dumps({'protocol_sha256':plan['sha256'],'reference_pool':len(items),'requested_counts':selection['requested_counts']}))


def audit_tasks(selection):
    from rsilab.coding_data import audit_pool
    return audit_pool(selection)


def load_plan():
    p=json.loads((DIRECTORY/'protocol.json').read_text());d=json.loads((DATA/'prepared.json').read_text())
    for value in (p,d):
        if digest({k:v for k,v in value.items() if k!='sha256'})!=value['sha256']:raise ValueError('Frozen manifest hash mismatch')
    if p['prepared_sha256']!=d['sha256'] or p['source_hashes']!=source_hashes() or p['evaluator_source_hashes']!=evaluator_source_hashes():raise ValueError('Frozen study identity changed')
    if p['policy']!=policy() or p['model']!=model_config():raise ValueError('Frozen policy/model changed')
    return p,d


def reports(name):
    return [json.loads(p.read_text()) for p in (ROOT/'runs').glob('*/report.json') if json.loads(p.read_text()).get('stage')==PREFIX+name]

def completed(name):
    matches=reports(name)
    if len(matches)!=1 or matches[0].get('status')!='completed':raise ValueError('Need exactly one completed '+name)
    plan,_=load_plan()
    if matches[0].get('protocol_sha256')!=plan['sha256']:raise ValueError('Wrong prior protocol')
    return matches[0]


@contextmanager
def bounded_stage(name):
    with arm_lock('verified-sft-v1'):
        plan,_=load_plan();cfg=plan['policy']
        if name not in cfg['stages'] or reports(name):raise ValueError('Unknown or already attempted stage; no automatic retries')
        ledger=json.loads((ROOT/'budget/ledger.json').read_text())
        spent=sum(r['reserved_usd'] for r in ledger['reservations'] if r['stage'].startswith(PREFIX))
        if spent+cfg['per_stage_usd']>cfg['reservation_cap_usd']:raise ValueError('Verified-data $20 reservation envelope exhausted')
        with stage(PREFIX+name) as (report,tracking):
            report.update(protocol_sha256=plan['sha256'],study='verified-sft-v1',policy=cfg,source_hashes=plan['source_hashes'])
            yield report,tracking


def collector(report,app):
    from .verified_workers import generate,train
    backend=ModalBackend(generate_function=generate,train_function=train,report=report,persist=persist,max_calls=policy()['max_gpu_calls_per_stage'])
    engine=VerifiedCollector(backend=backend,verify=lambda code,task:verify_mbpp_candidate(code,task,app),extract_code=extract_code,report=report,persist=persist)
    return backend,engine


def reference_audit(prepared,report,app):
    from rsilab.coding_data import audit_reference_task,build_probe_task
    items=prepared['reference_items']
    originals=verify_records(items,execute=lambda item:verify_mbpp_candidate(item['reference_code'],item['task'],app),
                            report=report,key='original_reference_audit',persist=persist)
    original_by_id={item['id']:result for item,result in zip(items,originals)}
    probes=[]
    for item in items:
        if original_by_id[item['id']]['passed']:
            probe=build_probe_task(item['task'],item['proposal'],approved_mutation_ids=item['review']['approved_mutation_ids'])
            probes.append({'id':item['id'],'task':probe,'code':item['reference_code']})
    probe_results=verify_records(probes,execute=lambda item:verify_mbpp_candidate(item['code'],item['task'],app),
                               report=report,key='mutation_reference_audit',persist=persist)
    probe_by_id={item['id']:(item['task'],result) for item,result in zip(probes,probe_results)}
    audits=[]
    for item in items:
        evidence=[]
        if item['id'] in probe_by_id:
            probe,raw=probe_by_id[item['id']]
            ids=probe['metadata']['probe_mutation_ids'];outputs=raw.get('outputs',[])
            if len(outputs)!=len(ids):raise ValueError('Incomplete reference probe outputs')
            evidence=[{'id':mid,'output':output,'reference_sha256':raw.get('candidate_sha256'),
                       'proposal_sha256':item['proposal']['sha256'],'evaluator_source_hashes':raw['evaluator_source_hashes'],
                       'sandbox_id':raw['sandbox_id']} for mid,output in zip(ids,outputs)]
        audit=audit_reference_task(item['task'],item['proposal'],reference_sha256=item['reference_sha256'],
                  original_result=original_by_id[item['id']],mutation_results=evidence,review=item['review'])
        audits.append(audit)
    report['reference_audits']=audits;persist(report)
    return audits


def dataset():
    value=json.loads((DATA/'audited-dataset.json').read_text())
    if digest({k:v for k,v in value.items() if k!='sha256'})!=value['sha256']:raise ValueError('Audited data changed')
    return value


def collect():
    from rsilab.coding_data import freeze_verified_dataset
    from .verified_workers import app
    plan,prepared=load_plan()
    with bounded_stage('collect') as (report,tracking):
        report['prepared_sha256']=prepared['sha256'];persist(report)
        with app.run():
            report['modal_app_id']=app.app_id;persist(report)
            audited=reference_audit(prepared,report,app)
            frozen=finalize_data(prepared['selection'],audited)
            save_immutable(DATA/'audited-dataset.json',frozen)
            report['audited_dataset_sha256']=frozen['sha256'];persist(report)
            tracking.upload_json(DATA/'audited-dataset.json',artifact_name='verified-sft-v1-audited-data',artifact_type='verified-data',name='dataset.json').wait()
            _,engine=collector(report,app)
            train_tasks=[t for t in frozen['tasks'] if t['split']=='train']
            eval_tasks=[t for t in frozen['tasks'] if t['split']=='dev']+prepared['retention_tasks']
            engine.collect(train_tasks,settings={**model_config(),**policy()['generation']},key='initial_attempts')
            engine.collect(eval_tasks,settings={**model_config(),**policy()['generation']},key='parent_evaluation')
        report['scores']=score_records(report['parent_evaluation'])
        tracking.log({f'parent/{k}/pass_rate':v['passed']/v['total'] for k,v in report['scores'].items()})


def finalize_data(selection,results):
    from rsilab.coding_data import freeze_verified_dataset
    # Adapter for the library's prospective reference-only replacement gate.
    return freeze_verified_dataset(selection,results)


def trusted_rows(rows):
    for row in rows:
        v=row['verification'];check_verification(v)
        if row['generation'].get('hit_token_limit'):
            if v.get('passed') is not False:raise ValueError('Truncated answer passed')
            continue
        if v.get('verifier_version')!='mbpp-typed-v2' or v.get('evaluator_source_hashes')!=evaluator_source_hashes():raise ValueError('Evaluator identity mismatch')
        computed=score_mbpp_outputs(v.get('outputs'),row['task']['cases'])
        if any(v.get(k)!=computed[k] for k in ('passed','count','total')):raise ValueError('Untrusted saved scoring')
        if v.get('outputs') is not None:
            if v.get('candidate_sha256')!=hashlib.sha256(extract_code(row['generation']['text']).encode()).hexdigest():raise ValueError('Code identity mismatch')
            if v.get('source_tests_sha256')!=row['task']['source_tests_sha256']:raise ValueError('Test identity mismatch')
    return rows


def attempt_ledger(initial,improvement=None):
    data=dataset();_,prepared=load_plan()
    tasks=[t for t in data['tasks'] if t['split']=='train'];excluded=[t for t in data['tasks'] if t['split']=='dev']+prepared['retention_tasks']
    ledger=AttemptLedger(tasks,excluded_tasks=excluded,policy=learning_policy());latest={}
    for row in trusted_rows(initial['initial_attempts']):
        a=ledger.add(row,source_run_id=initial['run_id'],attempt_index=0,attempt_kind='initial');latest[row['task']['id']]=a
    if improvement:
        for row in trusted_rows(improvement['sample_attempts']):
            a=ledger.add(row,source_run_id=improvement['run_id'],attempt_index=1,attempt_kind='sample');latest[row['task']['id']]=a
        for row in trusted_rows(improvement.get('repair_attempts',[])):
            tid=row['task']['id'];a=ledger.add(row,source_run_id=improvement['run_id'],attempt_index=2,attempt_kind='repair',parent_attempt_id=latest[tid]['attempt_id']);latest[tid]=a
    return ledger


def improve_data():
    from .verified_workers import app
    first=completed('collect');data=dataset();tasks=[t for t in data['tasks'] if t['split']=='train']
    with bounded_stage('improve-data') as (report,tracking):
        tracking.use_artifact(f'{tracking.entity}/{tracking.project}/{first["run_id"]}:latest',type='pilot-report')
        report['initial_run']=first['run_id'];report['audited_dataset_sha256']=data['sha256'];persist(report)
        with app.run():
            report['modal_app_id']=app.app_id;persist(report);_,engine=collector(report,app)
            engine.collect(tasks,settings={**model_config(),**policy()['sample_generation']},key='sample_attempts')
            initial={r['task']['id']:r for r in first['initial_attempts']};sample={r['task']['id']:r for r in report['sample_attempts']}
            repair=[t for t in tasks if not initial[t['id']]['verification']['passed'] and not sample[t['id']]['verification']['passed']][:policy()['max_repaired_tasks']]
            prompts={t['id']:build_repair_prompt(t,sample[t['id']]['generation']['text'],sample[t['id']]['verification'],policy=learning_policy()) for t in repair}
            engine.collect(repair,settings={**model_config(),**policy()['repair_generation']},key='repair_attempts',prompts=prompts)
        ledger=attempt_ledger(first,report);selection=select_verified_targets(ledger)
        report['attempt_ledger_sha256']=ledger.sha256;report['selection']=selection
        save_immutable(DATA/'attempt-ledger.json',ledger.to_dict());save_immutable(DATA/'selection.json',selection)
        persist(report);tracking.log({'data/targets':selection['selected_count'],'data/eligible':int(selection['eligible'])})
        # Gate failure is a complete collection result, not a provider failure.


def score_records(rows):
    trusted_rows(rows)
    return {split:{'passed':sum(r['verification']['passed'] for r in rows if r['task']['split']==split),'total':sum(r['task']['split']==split for r in rows)} for split in ('train','dev')}


def export_training(report):
    import modal
    volume=modal.Volume.from_name('open-rsi-artifacts');base=ARTIFACTS/report['run_id'];inventory={}
    for key,label in (('adapter_path','adapter'),('checkpoint_path','checkpoint')):
        remote='/adapters/'+report['training'][key].split('/adapters/',1)[1]
        for entry in volume.iterdir(remote):
            if int(entry.type)!=1:continue
            rel=PurePosixPath(entry.path).relative_to(PurePosixPath(remote.lstrip('/')))
            if '..' in rel.parts:raise ValueError('Unsafe checkpoint path')
            target=base/label/str(rel);target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('wb') as output:
                for chunk in volume.read_file(entry.path):output.write(chunk)
            inventory[str(target.relative_to(base))]=hashlib.sha256(target.read_bytes()).hexdigest()
    saved=json.loads((base/'checkpoint/complete.json').read_text())
    for name,sha in saved['sha256'].items():
        if inventory.get('checkpoint/'+name)!=sha:raise ValueError('Checkpoint export hash mismatch')
    write_json(base/'export-sha256.json',inventory)
    report['export']={'path':str(base.relative_to(ROOT)),'files':inventory,'checkpoint_verified':True,'adapter_sha256':inventory['adapter/adapter_model.safetensors']};persist(report)


def comparison_envelope(report,key,tasks,*,candidate=False):
    rows=deepcopy(trusted_rows(report[key]));batches=report[key+'_batches']
    if len(batches)!=1:raise ValueError('Matched evaluation must be a single batch')
    generated=batches[0]['generation'];plan,_=load_plan()
    if generated['gpu_name']!='NVIDIA L40S':raise ValueError('Unexpected evaluation hardware')
    expected_adapter=report['training']['adapter_path'] if candidate else None
    if generated.get('adapter_path')!=expected_adapter:raise ValueError('Actual adapter identity differs')
    for key in ('seed','temperature','max_new_tokens'):
        if generated.get(key)!=policy()['generation'][key]:raise ValueError('Actual generation controls differ')
    if generated.get('enable_thinking') is not False or any(generated.get(k)!=v for k,v in model_config().items()):
        raise ValueError('Actual model or thinking mode differs')
    for index,row in enumerate(rows):row['effective_seed']=policy()['generation']['seed']+index
    controls={'generation':{**policy()['generation'],'enable_thinking':False,'attempts_per_task':1},
              'evaluator':{'version':'mbpp-typed-v2','source_hashes':plan['evaluator_source_hashes']},
              'model':plan['model'],'hardware':generated['gpu_name'],'packages':generated['packages'],
              'source_hashes':plan['source_hashes'],'task_sha256':digest(tasks)}
    result={'run_id':report['run_id'],'agent_id':report['run_id'] if candidate else 'original-parent',
            'adapter_sha256':report['export']['adapter_sha256'] if candidate else None,'controls':controls,'records':rows}
    if candidate:result['training']={'fresh_adapter':True,'parent_adapter_sha256':None,'adapter_sha256':result['adapter_sha256'],
          'selection_sha256':report['selection_sha256'],'seed':report['seed']}
    return result


def train_evaluate(seed):
    from .verified_workers import app
    first=completed('collect');improved=completed('improve-data');data=dataset();_,prepared=load_plan()
    selection=select_verified_targets(attempt_ledger(first,improved))
    if selection!=improved['selection'] or not selection['eligible']:raise ValueError('Verified-data diversity gate not satisfied')
    initial=None
    if seed==43:
        initial=completed('train-evaluate-42')['comparison']
        if not initial['promising']:raise ValueError('Replication gate not satisfied')
    examples=[{k:r[k] for k in ('prompt','completion','verified')} for r in selection['selected']]
    from transformers import AutoTokenizer
    from .modal_workers import _encode_example
    tokenizer=AutoTokenizer.from_pretrained(model_config()['model_id'],revision=model_config()['revision'],local_files_only=True,token=False,cache_dir=str(ROOT/'.cache/huggingface/hub'))
    tokenized=[_encode_example(tokenizer,e,policy()['training']['max_length']) for e in examples]
    steps=min(policy()['training']['max_steps'],math.ceil(policy()['training']['epochs']*len(examples)/policy()['training']['gradient_accumulation']))
    tasks=[t for t in data['tasks'] if t['split']=='dev']+prepared['retention_tasks']
    with bounded_stage(f'train-evaluate-{seed}') as (report,tracking):
        report.update(seed=seed,selection_sha256=selection['sha256'],audited_dataset_sha256=data['sha256'],examples_count=len(examples),
                      supervised_tokens=sum(sum(v!=-100 for v in row['labels']) for row in tokenized))
        tracking.use_artifact(f'{tracking.entity}/{tracking.project}/{improved["run_id"]}:latest',type='pilot-report')
        with app.run():
            report['modal_app_id']=app.app_id;persist(report);backend,engine=collector(report,app)
            report['training']=backend.train({**model_config(),'run_id':report['run_id'],'examples':examples,'seed':seed,
                 **{k:v for k,v in policy()['training'].items() if k not in ('epochs','max_steps')},'max_steps':steps})
            persist(report)
            if report['training']['status']!='completed':raise ValueError('Training incomplete')
            if report['training']['gpu_name']!='NVIDIA L40S' or report['training']['steps_completed']!=steps or report['training']['examples_count']!=len(examples):raise ValueError('Training hardware or completion controls differ')
            engine.collect(tasks,settings={**model_config(),**policy()['generation'],'adapter_path':report['training']['adapter_path']},key='candidate_evaluation')
        export_training(report)
        parent=comparison_envelope(first,'parent_evaluation',tasks)
        candidate=comparison_envelope(report,'candidate_evaluation',tasks,candidate=True)
        report['comparison']=compare_learning_run(parent,candidate,tasks=tasks,retention_ids=[t['id'] for t in prepared['retention_tasks']],policy=learning_policy(),initial_comparison=initial)
        report['scores']=score_records(report['candidate_evaluation'])
        persist(report)
        for point in report['training']['losses']:tracking.log({'train/optimizer_step':point['step'],'train/loss':point['loss']})
        tracking.log({'dev/net_gain':report['comparison']['scores']['dev']['net_success_gain'],'replication/promising':int(report['comparison']['promising'])})



def report_results():
    from rsi.budget import Budget
    plan,prepared=load_plan();first=completed('collect');improved=completed('improve-data');data=dataset()
    selection=select_verified_targets(attempt_ledger(first,improved))
    if selection!=improved['selection']:raise ValueError('Training selection changed')
    tasks=[t for t in data['tasks'] if t['split']=='dev']+prepared['retention_tasks']
    parent=comparison_envelope(first,'parent_evaluation',tasks)
    comparisons={};run_ids=[first['run_id'],improved['run_id']]
    for seed in (42,43):
        if not reports(f'train-evaluate-{seed}'):continue
        trained=completed(f'train-evaluate-{seed}')
        candidate=comparison_envelope(trained,'candidate_evaluation',tasks,candidate=True)
        comparison=compare_learning_run(parent,candidate,tasks=tasks,retention_ids=plan['retention_ids'],
            policy=learning_policy(),initial_comparison=comparisons.get('42'))
        if comparison!=trained['comparison']:raise ValueError('Comparison changed after trusted recomputation')
        comparisons[str(seed)]=comparison;run_ids.append(trained['run_id'])
    result={'study':'verified-sft-v1','protocol_sha256':plan['sha256'],'dataset_sha256':data['sha256'],
        'training_selection_sha256':selection['sha256'],'targets':selection['selected_count'],'categories':selection['categories'],
        'selection_eligible':selection['eligible'],'selection_reasons':selection['reasons'],
        'attempt_counts':{'initial':len(first['initial_attempts']),'sample':len(improved['sample_attempts']),'repair':len(improved['repair_attempts'])},
        'verified_attempt_counts':{name:sum(r['verification']['passed'] for r in rows) for name,rows in
            [('initial',first['initial_attempts']),('sample',improved['sample_attempts']),('repair',improved['repair_attempts'])]},
        'split_counts':data['split_counts'],'augmented_case_count':sum(len(t['cases']) for t in data['tasks']),
        'reused_development_ids':data['reused_development_ids'],'parent_scores':score_records(first['parent_evaluation']),
        'comparisons':comparisons,'run_ids':run_ids,'sealed_final':data['sealed_final'],'promoted':False,
        'decision':'retain_original_parent','budget':json.loads((ROOT/'runs'/run_ids[-1]/'report.json').read_text())['budget'],
        'interpretation':plan['interpretation'],'stopping_reason':'data_gate_failed' if not selection['eligible'] else
            'replication_completed' if '43' in comparisons else 'replication_gate_not_met' if comparisons and not comparisons['42']['promising'] else 'work_remaining'}
    if result['stopping_reason']=='work_remaining':raise ValueError('Required experiment work remains')
    save_immutable(ARTIFACTS/'summary.json',result)
    for name,value in [('parent-comparison.json',parent),('evaluation-tasks.json',tasks),('retention-ids.json',plan['retention_ids']),('learning-policy.json',learning_policy().to_dict())]:
        save_immutable(ARTIFACTS/name,value)
    for seed in comparisons:
        r=completed(f'train-evaluate-{seed}')
        save_immutable(ARTIFACTS/f'candidate-{seed}-comparison.json',comparison_envelope(r,'candidate_evaluation',tasks,candidate=True))
    print(json.dumps(result,indent=2))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare','collect','improve-data','train-evaluate','report'))
    parser.add_argument('--seed',type=int,choices=(42,43),default=42)
    parser.add_argument('--workspace',type=Path,default=ROOT)
    args=parser.parse_args(argv);configure_workspace(args.workspace);load_local_env()
    if args.command=='prepare':prepare()
    elif args.command=='collect':collect()
    elif args.command=='improve-data':improve_data()
    elif args.command=='report':report_results()
    else:train_evaluate(args.seed)

if __name__=='__main__':main()
