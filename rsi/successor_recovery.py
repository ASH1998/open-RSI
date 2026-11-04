"""Versioned successor recovery using immutable saved reference evidence."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
from pathlib import Path, PurePosixPath
import random

from rsilab import digest
from rsilab.project import Workspace
from rsilab.workflow import VerifiedCollector, verify_records
from rsilab.providers.modal import ModalBackend
from rsilab.providers.portable_modal import PortableModalConfig, create_modal_workers, resource_inventory, validate_request
from rsilab.successor import SuccessorPolicy, freeze_successor_protocol, audit_improver_probe, compare_successors, inference_request_sha256
from rsi.mbpp_verification_v2 import verify_mbpp_candidate, evaluator_source_hashes
from rsi.verification import extract_code
from rsi.verified_study import trusted_rows

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'successor-r1-'


def ws(): return Workspace(ROOT)
def read(path): return json.loads((ROOT / path).read_text())
def config(): return read('config/successor_recovery_v1.json')
def save(path, value):
    path = ROOT / path
    if path.exists() and json.loads(path.read_text()) != value:
        raise ValueError('Refusing to overwrite frozen evidence: '+str(path))
    ws().write_json(path, value)

def sources():
    paths = [Path('rsi/successor_recovery.py'),Path('rsi/verified_study.py'),Path('config/successor_recovery_v1.json'),Path('config/budget.json'),Path('pyproject.toml')]
    paths += [p.relative_to(ROOT) for p in sorted((ROOT/'rsilab').rglob('*.py'))]
    paths += [Path('rsi')/name for name in ('budget.py','config.py','pilot.py','datasets.py','verification.py','mbpp_verification.py','mbpp_verification_v2.py')]
    paths += [p.relative_to(ROOT) for pattern in ('*.txt','*.json') for p in sorted((ROOT/'rsilab/resources').glob(pattern))]
    return {str(p):hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}

def plan():
    value=read('studies/successor_recovery_v1/plan.json')
    if digest({k:v for k,v in value.items() if k!='sha256'})!=value['sha256'] or value['source_hashes']!=sources() or value['config']!=config():
        raise ValueError('Frozen experiment identity changed')
    prepared=read('data/successor-recovery-v1/prepared.json')
    if digest(prepared)!=value['prepared_sha256']:raise ValueError('Prepared data changed')
    return value,prepared

def protocol():
    p=read('data/successor-recovery-v1/protocol.json');compact=read('studies/successor_recovery_v1/protocol.json')
    if digest({k:v for k,v in compact.items() if k!='sha256'})!=compact['sha256'] or compact['full_protocol_sha256']!=p['sha256'] or compact['plan_sha256']!=plan()[0]['sha256']:
        raise ValueError('Protocol summary identity changed')
    checked=freeze_successor_protocol({k:v for k,v in p.items() if k!='sha256'},policy=policy())
    if checked!=p:raise ValueError('Full protocol identity changed')
    data=read('data/successor-recovery-v1/audited-dataset.json')
    if digest(data)!=completed('baseline')['dataset_sha256']:raise ValueError('Audited dataset changed')
    if any(p['registries'][k]!=data[k] for k in ('train','dev','retention')):raise ValueError('Protocol task registry differs')
    return p
def policy():return SuccessorPolicy(**plan()[0]['policy'])
def reports(name):
    return [r for p in (ROOT/'runs').glob('*/report.json') if (r:=json.loads(p.read_text())).get('stage')==PREFIX+name]

def completed(name):
    rows=reports(name)
    if len(rows)!=1 or rows[0]['status']!='completed':raise ValueError('Need exactly one completed stage: '+name)
    if rows[0].get('plan_sha256')!=plan()[0]['sha256']:raise ValueError('Stage plan differs')
    return rows[0]

@contextmanager
def stage(name):
    frozen,_=plan();cfg=config()
    lock=ROOT/'work/successor-recovery-v1.lock';lock.parent.mkdir(exist_ok=True)
    with lock.open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if name not in cfg['stages'] or reports(name):raise ValueError('Unknown or already attempted stage')
        spent=sum(x['reserved_usd'] for x in read('budget/ledger.json')['reservations'] if x['stage'].startswith(PREFIX))
        if spent+cfg['per_stage_usd']>cfg['reservation_cap_usd']:raise ValueError('Study reservation cap exceeded')
        fields={'plan_sha256','protocol_sha256','portable_worker','remote_calls','reuse_sha256','audits','dataset_sha256','training','export','token_accounting','examples_sha256'}
        for key in ('original_references','reference_probes','baseline','initial','sample','evaluation'):
            fields.update((key,key+'_execution',key+'_batches',key+'_verification_0',key+'_verification_0_execution'))
        uploads=['studies/successor_recovery_v1/plan.json','data/successor-recovery-v1/prepared.json','data/successor-recovery-v1/audited-dataset.json']
        if name!='baseline':uploads.append('data/successor-recovery-v1/protocol.json')
        if name.startswith('child-'):uploads.append('artifacts/successor-recovery-v1/probe.json')
        with ws().stage(PREFIX+name,source_paths=tuple(frozen['source_hashes']),report_fields=fields,metric_keys=(),upload_paths=uploads,tracking_mode='online') as pair:
            report,tracking=pair;report['plan_sha256']=frozen['sha256'];ws().persist(report)
            dependencies=['20261104T183006Z-successor-v1-calibrate-a33b28fc'] if name=='baseline' else [completed('baseline')['run_id']]
            if name=='teacher-learned':dependencies.append('20261104T143454Z-verified-sft-v1-train-evaluate-42-73116f4e')
            if name.startswith('child-'):dependencies.extend(completed('teacher-'+role)['run_id'] for role in ('original','learned'))
            for run_id in dependencies:tracking.use_artifact('ashu-na/rsi/'+run_id+':latest',type='pilot-report')
            for index,path in enumerate(uploads):tracking.upload_json(path,artifact_name=report['run_id']+'-input-'+str(index),artifact_type='study-input',name='data.json')
            yield pair

def worker_config():
    model=plan()[0]['model']
    return PortableModalConfig(app_name='open-rsi-successor-recovery-v1',volume_name='open-rsi-artifacts',model_id=model['model_id'],model_revision=model['revision'],gpu='L40S')

def workers():return create_modal_workers(worker_config())

def collector(report, workers):
    backend=ModalBackend(generate_function=workers.generate,train_function=workers.train,report=report,persist=ws().persist,max_calls=config()['max_gpu_calls_per_stage'])
    engine=VerifiedCollector(backend=backend,verify=lambda code,task:verify_mbpp_candidate(code,task,workers.app),extract_code=extract_code,report=report,persist=ws().persist)
    report['portable_worker']=workers.provenance;ws().persist(report)
    return backend,engine

def generate_settings(kind='generation',adapter=None,adapter_sha256=None):
    return {**plan()[0]['model'],**config()[kind],'adapter_path':adapter,'adapter_sha256':adapter_sha256}

def runtime(generated):
    cfg=worker_config();expected={'worker':resource_inventory(),'config':cfg.to_dict(),'config_sha256':cfg.sha256}
    if generated.get('portable_worker')!=expected:raise ValueError('Actual portable worker identity differs')
    if generated['gpu_name']!='NVIDIA L40S':raise ValueError('Unexpected GPU')
    return {'hardware':generated['gpu_name'],'packages':generated['packages'],'source_hashes':plan()[0]['source_hashes'],'precision':'nf4-double-quant-bfloat16-sdpa'}

def infer_controls(generated, settings, count):
    for key in ('model_id','revision','seed','temperature','max_new_tokens','adapter_path','adapter_sha256'):
        if generated.get(key)!=settings.get(key):raise ValueError('Actual generation differs: '+key)
    if generated['enable_thinking'] is not False:raise ValueError('Thinking mode differs')
    return {'generation':{k:settings[k] for k in ('seed','temperature','max_input_tokens','max_new_tokens')}|{'enable_thinking':False},
            'runtime':runtime(generated),'evaluator':{'version':'mbpp-typed-v2','source_hashes':evaluator_source_hashes()},
            'effective_seeds':[settings['seed']+i for i in range(count)]}

def collect_envelope(report,key,agent,attempt=None):
    rows=deepcopy(trusted_rows(report[key]));batches=report[key+'_batches']
    if len(batches)!=1:raise ValueError('Require one bounded ordered inference batch')
    batch=batches[0]
    if [r['generation'] for r in rows]!=batch['generation'].get('outputs'):raise ValueError('Raw generation rows differ from worker outputs')
    calls=[c for c in report['remote_calls'] if c['operation']=='generate' and c['request_sha256']==batch['request_sha256']]
    if len(calls)!=1 or calls[0]['status']!='completed' or calls[0]['result']!=batch['generation']:raise ValueError('Durable provider call evidence differs')
    controls=infer_controls(batch['generation'],batch['settings'],len(rows))
    if batch['generation'].get('adapter_sha256')!=agent['adapter_sha256']:raise ValueError('Agent adapter identity differs from worker')
    for i,row in enumerate(rows):row['effective_seed']=controls['effective_seeds'][i]
    request={**batch['settings'],'prompts':[{'id':r['task']['id'],'prompt':r['task']['prompt']} for r in rows]}
    if digest(request)!=batch['request_sha256']:raise ValueError('Worker request hash differs')
    value={'status':'completed','agent':agent,'controls':controls,'records':rows,'request_sha256':inference_request_sha256(agent,controls,[r['task'] for r in rows])}
    if attempt is not None:value['attempt_index']=attempt
    return value

def stage_fields(report, rows):
    # Planning estimate from measured worker/sandbox execution; cold builds and
    # persistent storage remain covered by the separate project overhead hold.
    rates=read('config/budget.json')['rates_per_second']
    gpu=sum(c.get('result',{}).get('elapsed_seconds',0) for c in report.get('remote_calls',[]))
    sandbox=sum(r['verification'].get('duration_seconds',0) for r in rows)
    sandbox+=sum(entry.get('result',{}).get('duration_seconds',0) for key in ('original_references','reference_probes') for entry in report.get(key,[]))
    estimate=gpu*(rates['L40S']+2*rates['cpu_core']+16*rates['memory_gib'])+sandbox*(rates['sandbox_cpu_core']+rates['sandbox_memory_gib'])
    path=ROOT/'runs'/report['run_id']/'report.json'
    return {'run_id':report['run_id'],'reservation':{'id':report['budget_reservation'],'amount_usd':5},
            'usage':{'wall_seconds':report['wall_seconds'],'estimated_cost_usd':estimate,
                     'input_tokens':sum(r['generation']['input_tokens'] for r in rows),'output_tokens':sum(r['generation']['output_tokens'] for r in rows)},
            'artifact_inventory':{'report.json':hashlib.sha256(path.read_bytes()).hexdigest()},'artifacts_verified':True,'outputs_rescored':True}


def teacher(role):
    frozen,_=plan();p=protocol();completed('baseline')
    adapter=frozen['learned_adapter_path'] if role=='learned' else None
    with stage('teacher-'+role) as (report,tracking):
        report['protocol_sha256']=p['sha256'];w=workers()
        with w.app.run():
            report['modal_app_id']=w.app.app_id;_,engine=collector(report,w)
            for key,kind in (('initial','generation'),('sample','sampling')):
                engine.collect(p['registries']['train'],settings=generate_settings(kind,adapter,frozen['learned_adapter_sha256'] if role=='learned' else None),key=key)
                envelope=collect_envelope(report,key,p['teachers'][role],0 if key=='initial' else 1)
                if envelope['controls']!=p['controls']['teacher'][envelope['attempt_index']]:raise ValueError('Teacher controls differ from frozen protocol')
    report=completed('teacher-'+role)
    collections=[collect_envelope(report,key,p['teachers'][role],i) for i,key in enumerate(('initial','sample'))]
    rows=[row for c in collections for row in c['records']]
    evidence={'protocol_sha256':p['sha256'],'teacher':p['teachers'][role],'collections':collections,**stage_fields(report,rows)}
    save('artifacts/successor-recovery-v1/teacher-'+role+'.json',evidence)
    if all(reports('teacher-'+r) and reports('teacher-'+r)[0]['status']=='completed' for r in ('original','learned')):
        probe=audit_improver_probe(p,read('artifacts/successor-recovery-v1/teacher-original.json'),read('artifacts/successor-recovery-v1/teacher-learned.json'),policy=policy())
        save('artifacts/successor-recovery-v1/probe.json',probe)
        print(json.dumps({'eligible':probe['eligible'],'reasons':probe['reasons'],'yields':{r:a['yield'] for r,a in probe['arms'].items()}}))


def prepare():
    """Reuse reference execution only after checking its historical identity."""
    from rsilab.dataset_io import file_sha256
    from rsilab.reference_reuse import reuse_reference_audits
    from rsilab.preflight import preflight_task_categories
    from rsilab.learning import _leak_keys
    correction=read('studies/successor_v1/category-correction-proposal.json')
    if digest({k:v for k,v in correction.items() if k!='sha256'})!=correction['sha256']:
        raise ValueError('Category correction seal differs')
    for binding in correction['source_artifacts'].values():
        path=ws().path(binding['path'])
        if file_sha256(path)!=binding['file_sha256'] or digest(json.loads(path.read_text()))!=binding['canonical_json_sha256']:
            raise ValueError('Historical source evidence changed: '+binding['path'])
    old_plan=read('studies/successor_v1/plan.json');old_prepared=read('data/successor-v1/prepared.json')
    failed=read(correction['source_artifacts']['failed_calibration']['path'])
    if digest({k:v for k,v in old_plan.items() if k!='sha256'})!=old_plan['sha256'] or digest(old_prepared)!=old_plan['prepared_sha256'] or failed['plan_sha256']!=old_plan['sha256']:
        raise ValueError('Historical plan or prepared identity differs')
    import subprocess
    commit=failed['provenance']['git_commit']
    if len(commit)!=40 or any(c not in '0123456789abcdef' for c in commit):raise ValueError('Invalid historical commit')
    for name,sha in old_plan['source_hashes'].items():
        archived=subprocess.check_output(['git','show',commit+':'+name],cwd=ROOT)
        if hashlib.sha256(archived).hexdigest()!=sha:raise ValueError('Historical archived source differs')
    # General package version may evolve. Replay-critical modules must remain identical.
    for name in ('rsilab/coding_data.py','rsi/verification.py','rsi/mbpp_verification.py','rsi/mbpp_verification_v2.py'):
        if file_sha256(ROOT/name)!=old_plan['source_hashes'][name]:
            raise ValueError('Reference replay implementation changed')
    reuse=reuse_reference_audits(prepared=old_prepared,calibration_report=failed,correction=correction,
        expected_correction_sha256=correction['sha256'],expected_plan_sha256=old_plan['sha256'],
        expected_evaluator_source_hashes=evaluator_source_hashes(),train_count=20,
        expected_category_counts={'collections':9,'numeric':8,'text':3})
    cfg=config();pol=SuccessorPolicy(train_count=cfg['train_count'],min_targets=cfg['min_targets'],min_categories=cfg['min_categories'],max_category_share=cfg['max_category_share'])
    reviewed={item['task_id']:item['independently_reviewed_category'] for item in correction['items']}
    preflight_task_categories(reuse['audited_pool'],first_n=pol.train_count,min_categories=pol.min_categories,min_pool_count=cfg['reference_pool_cap'],expected_categories=reviewed)
    prior=old_prepared['prior_exposure_tasks'];dev=old_prepared['dev'];retention=old_prepared['retention']
    excluded=set().union(*(_leak_keys(t) for t in prior+dev+retention))
    if any(_leak_keys(t)&excluded for t in reuse['audited_pool']):raise ValueError('Recovered training data overlaps prior exposure')
    sealed=old_prepared['sealed_final']
    if file_sha256(ROOT/'data/mbpp/raw/full/test-00000-of-00001.parquet')!=sealed['file_sha256']:
        raise ValueError('Final-test checksum differs')
    previous=read('runs/20261104T143454Z-verified-sft-v1-train-evaluate-42-73116f4e/report.json')
    if file_sha256(ROOT/previous['export']['path']/'adapter/adapter_model.safetensors')!=old_plan['learned_adapter_sha256']:
        raise ValueError('Experimental adapter changed')
    prepared={'reuse':reuse,'train':reuse['train'],'dev':dev,'retention':retention,
              'prior_exposure_tasks':prior,'sealed_final':sealed,'correction_sha256':correction['sha256']}
    value={'study':'successor-recovery-v1','config':cfg,'policy':pol.to_dict(),'prepared_sha256':digest(prepared),
           'source_hashes':sources(),'model':old_plan['model'],'learned_adapter_path':old_plan['learned_adapter_path'],
           'learned_adapter_sha256':old_plan['learned_adapter_sha256'],'historical_plan_sha256':old_plan['sha256'],
           'historical_report_sha256':digest(failed),'historical_source_commit':failed['provenance']['git_commit'],
           'reuse_sha256':reuse['sha256'],'previous_failed_reservation_retained':True,
           'interpretation':'Category-only recovery with exact reference evidence replay; new $25 envelope, previous $5 remains in global ledger; no automatic retry or promotion'}
    save('data/successor-recovery-v1/prepared.json',prepared)
    save('studies/successor_recovery_v1/plan.json',{**value,'sha256':digest(value)})
    dataset={k:prepared[k] for k in ('train','dev','retention')}
    dataset.update(reuse_sha256=reuse['sha256'],plan_sha256=digest(value))
    save('data/successor-recovery-v1/audited-dataset.json',dataset)
    compact={k:v for k,v in reuse.items() if k not in ('audited_pool','train','sha256')}
    compact['full_reuse_sha256']=reuse['sha256']
    save('studies/successor_recovery_v1/reuse.json',{**compact,'sha256':digest(compact)})
    print(json.dumps({'plan_sha256':digest(value),'reuse_sha256':reuse['sha256'],'train_count':len(dataset['train'])}))


def baseline():
    frozen,prepared=plan();dataset=read('data/successor-recovery-v1/audited-dataset.json')
    if any(dataset[k]!=prepared[k] for k in ('train','dev','retention')) or dataset['reuse_sha256']!=prepared['reuse']['sha256']:
        raise ValueError('Derived dataset differs before reservation')
    static_preflight(frozen,prepared,dataset)
    with stage('baseline') as (report,tracking):
        report['dataset_sha256']=digest(dataset);report['reuse_sha256']=prepared['reuse']['sha256'];w=workers()
        with w.app.run():
            report['modal_app_id']=w.app.app_id;_,engine=collector(report,w)
            engine.collect(dataset['dev']+dataset['retention'],settings=generate_settings(),key='baseline')
            # Validate returned controls and protocol compatibility before marking stage completed.
            original=original_agent(frozen)
            envelope=collect_envelope(report,'baseline',original)
            freeze_successor_protocol(protocol_spec(frozen,prepared,dataset,envelope['controls']),policy=policy())
    freeze_protocol()


def original_agent(frozen):
    model=frozen['model']
    return {'agent_id':'original-parent','model_id':model['model_id'],'revision':model['revision'],
            'tokenizer_revision':model['revision'],'adapter_sha256':None,'parent_agent_sha256':None}


def protocol_spec(frozen,prepared,data,base_controls):
    model=frozen['model']
    original={'agent_id':'original-parent','model_id':model['model_id'],'revision':model['revision'],'tokenizer_revision':model['revision'],'adapter_sha256':None,'parent_agent_sha256':None}
    learned={**original,'agent_id':'experimental-verified-sft-42','adapter_sha256':frozen['learned_adapter_sha256'],'parent_agent_sha256':digest(original)}
    run=base_controls['runtime']
    def controls(kind,count):
        gen={**config()[kind],'enable_thinking':False}
        return {'generation':gen,'runtime':run,'evaluator':base_controls['evaluator'],'effective_seeds':[gen['seed']+i for i in range(count)]}
    training={'steps':config()['training']['max_steps'],'gradient_accumulation':4,'micro_batch_size':1,'max_length':2048,'learning_rate':2e-5,
              'optimizer':'AdamW','scheduler':'none','adapter_config':{'rank':8,'alpha':16,'dropout':0.0,'bias':'none','target_modules':['q_proj','k_proj','v_proj','o_proj','gate_proj','up_proj','down_proj']},'runtime':run}
    spec={'schema_version':1,'policy':policy().to_dict(),'teachers':{'original':original,'learned':learned},'starting_student':original,
          'selection':'all_unique_earliest_verified','teacher_context_sha256':digest([]),'exclusion_registry_complete':True,'prior_exposure_registry_complete':True,
          'registries':{**{k:data[k] for k in ('train','dev','retention')},'sealed_final':[prepared['sealed_final']],'prior_exposure':prepared['prior_exposure_tasks']},
          'controls':{'teacher':[controls('generation',len(data['train'])),controls('sampling',len(data['train']))],'student_evaluation':base_controls,'student_training':training}}
    return spec


def static_preflight(frozen,prepared,data):
    from rsilab.preflight import preflight_task_categories
    preflight_task_categories(data['train'],first_n=policy().train_count,min_categories=policy().min_categories)
    controls={'generation':{**config()['generation'],'enable_thinking':False},
              'runtime':{'hardware':'pending-baseline','packages':{'pending':'pending'},'source_hashes':frozen['source_hashes'],'precision':'nf4-double-quant-bfloat16-sdpa'},
              'evaluator':{'version':'mbpp-typed-v2','source_hashes':evaluator_source_hashes()},
              'effective_seeds':[config()['generation']['seed']+i for i in range(len(data['dev']+data['retention']))]}
    freeze_successor_protocol(protocol_spec(frozen,prepared,data,controls),policy=policy())
    cfg=worker_config()
    for tasks,kind in ((data['train'],'generation'),(data['train'],'sampling'),(data['dev']+data['retention'],'generation')):
        validate_request('generate',{**generate_settings(kind),'prompts':[{'id':t['id'],'prompt':t['prompt']} for t in tasks]},cfg)


def freeze_protocol():
    frozen,prepared=plan();report=completed('baseline');data=read('data/successor-recovery-v1/audited-dataset.json')
    if report['dataset_sha256']!=digest(data):raise ValueError('Dataset identity differs')
    base=collect_envelope(report,'baseline',original_agent(frozen))
    p=freeze_successor_protocol(protocol_spec(frozen,prepared,data,base['controls']),policy=policy())
    save('data/successor-recovery-v1/protocol.json',p)
    summary={'full_protocol_sha256':p['sha256'],'plan_sha256':frozen['sha256'],'policy':p['policy'],'teachers':p['teachers'],'starting_student':p['starting_student'],'controls':p['controls'],'registry_hashes':{k:digest(v) for k,v in p['registries'].items()},'registry_ids':{k:[t['id'] for t in p['registries'][k]] for k in ('train','dev','retention')},'sealed_final':p['registries']['sealed_final'],'full_protocol_location':'data/successor-recovery-v1/protocol.json'}
    save('studies/successor_recovery_v1/protocol.json',{**summary,'sha256':digest(summary)})
    starting={'protocol_sha256':p['sha256'],'evaluation':base,**stage_fields(report,base['records'])}
    save('artifacts/successor-recovery-v1/starting-student.json',starting)
    print(json.dumps({'protocol_sha256':p['sha256'],'train_count':len(data['train']),'baseline_passes':sum(r['verification']['passed'] for r in base['records'])}))


def export_training(report):
    import modal
    volume=modal.Volume.from_name('open-rsi-artifacts');base=ROOT/'artifacts/successor-recovery-v1'/report['run_id'];inventory={}
    for key,label in (('adapter_path','adapter'),('checkpoint_path','checkpoint')):
        remote='/adapters/'+report['training'][key].split('/adapters/',1)[1]
        for entry in volume.iterdir(remote):
            if int(entry.type)!=1:continue
            rel=PurePosixPath(entry.path).relative_to(PurePosixPath(remote.lstrip('/')))
            if '..' in rel.parts:raise ValueError('Unsafe checkpoint path')
            target=base/label/str(rel);target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('wb') as stream:
                for chunk in volume.read_file(entry.path):stream.write(chunk)
            inventory[str(target.relative_to(base))]=hashlib.sha256(target.read_bytes()).hexdigest()
    manifest=json.loads((base/'checkpoint/complete.json').read_text())
    metadata=json.loads((base/'checkpoint/metadata.json').read_text())
    if digest(metadata['examples'])!=report['examples_sha256']:raise ValueError('Exported checkpoint training data differs')
    for key in ('seed','learning_rate','gradient_accumulation','max_length'):
        if metadata[key]!=config()['training'][key]:raise ValueError('Exported checkpoint controls differ')
    for name,sha in manifest['sha256'].items():
        if inventory.get('checkpoint/'+name)!=sha:raise ValueError('Checkpoint checksum mismatch')
    if manifest['step']!=config()['training']['max_steps']:raise ValueError('Checkpoint step differs')
    if inventory['adapter/adapter_model.safetensors']!=report['training']['adapter_sha256']:raise ValueError('Trained adapter bytes differ from export')
    report['export']={'path':str(base.relative_to(ROOT)),'files':inventory,'checkpoint_verified':True,'adapter_sha256':inventory['adapter/adapter_model.safetensors']};ws().persist(report)


def train_child(role):
    p=protocol();probe=read('artifacts/successor-recovery-v1/probe.json')
    check=audit_improver_probe(p,read('artifacts/successor-recovery-v1/teacher-original.json'),read('artifacts/successor-recovery-v1/teacher-learned.json'),policy=policy())
    if probe!=check or not probe['eligible']:raise ValueError('Paired teacher feasibility gate failed')
    selected=probe['arms'][role]['selection'];examples=[{k:r[k] for k in ('prompt','completion','verified')} for r in selected['selected']]
    from transformers import AutoTokenizer
    from rsilab.resources.gpu_worker_v1 import _encode_example
    model=plan()[0]['model'];tokenizer=AutoTokenizer.from_pretrained(model['model_id'],revision=model['revision'],token=False,local_files_only=True,cache_dir=str(ROOT/'.cache/huggingface/hub'))
    encoded=[_encode_example(tokenizer,x,2048) for x in examples];random.Random(42).shuffle(encoded)
    consumed=[encoded[i%len(encoded)] for i in range(16*4)]
    accounting={'processed_tokens':sum(len(r['input_ids']) for r in consumed),'supervised_tokens':sum(sum(v!=-100 for v in r['labels']) for r in consumed),'dataset_supervised_tokens':sum(sum(v!=-100 for v in r['labels']) for r in encoded)}
    with stage('child-'+role) as (report,tracking):
        report['protocol_sha256']=p['sha256'];report['token_accounting']=accounting;report['examples_sha256']=digest(examples);w=workers()
        with w.app.run():
            report['modal_app_id']=w.app.app_id;backend,engine=collector(report,w)
            request={**model,**config()['training'],'run_id':report['run_id'],'examples':examples}
            report['training']=backend.train(request);ws().persist(report)
            t=report['training']
            if t['status']!='completed' or t['steps_completed']!=16 or t['examples_count']!=len(examples) or t['supervised_tokens']!=accounting['dataset_supervised_tokens']:raise ValueError('Training completion/accounting differs')
            for key in ('seed','learning_rate','gradient_accumulation','max_length','max_steps'):
                if t[key]!=config()['training'][key]:raise ValueError('Actual training controls differ')
            if t['lora_rank']!=8:raise ValueError('Actual LoRA rank differs')
            if runtime(t)!=p['controls']['student_training']['runtime']:raise ValueError('Training runtime differs')
            engine.collect(p['registries']['dev']+p['registries']['retention'],settings=generate_settings(adapter=t['adapter_path'],adapter_sha256=t['adapter_sha256']),key='evaluation')
        export_training(report)
    child_envelope(role)


def child_envelope(role):
    p=protocol();probe=read('artifacts/successor-recovery-v1/probe.json');report=completed('child-'+role);export=report['export'];files=export['files']
    for relative,sha in files.items():
        if hashlib.sha256((ROOT/export['path']/relative).read_bytes()).hexdigest()!=sha:raise ValueError('Export changed')
    student=p['starting_student'];agent={**student,'agent_id':report['run_id'],'adapter_sha256':export['adapter_sha256'],'parent_agent_sha256':digest(student)}
    evaluation=collect_envelope(report,'evaluation',agent)
    selected=probe['arms'][role]['selection'];t=report['training']
    controls={**p['controls']['student_training'],'runtime':runtime(t)}
    checkpoint={'complete':True,'step':t['steps_completed'],'adapter_sha256':agent['adapter_sha256'],'training_state_sha256':files['checkpoint/training_state.pt'],
                'metadata_sha256':files['checkpoint/metadata.json'],'manifest_sha256':files['checkpoint/complete.json'],'optimizer_state':True,'rng_state':True,'scheduler_state':'not_used'}
    evidence={'protocol_sha256':p['sha256'],'teacher':p['teachers'][role],'starting_student':student,'agent':agent,'evaluation':evaluation,
              **stage_fields(report,evaluation['records']),
              'training':{'status':t['status'],'initialization':'fresh','resume_checkpoint_sha256':None,'selection_sha256':selected['sha256'],
                          'examples_sha256':probe['arms'][role]['examples_sha256'],'examples_count':t['examples_count'],'seed':t['seed'],'controls':controls,
                          'steps_completed':t['steps_completed'],**report['token_accounting'],'checkpoint':checkpoint}}
    evidence['artifact_inventory'].update(files);save('artifacts/successor-recovery-v1/child-'+role+'.json',evidence)


def report_results():
    p=protocol();probe=read('artifacts/successor-recovery-v1/probe.json')
    replay=audit_improver_probe(p,read('artifacts/successor-recovery-v1/teacher-original.json'),read('artifacts/successor-recovery-v1/teacher-learned.json'),policy=policy())
    if replay!=probe:raise ValueError('Probe replay differs')
    result={'study':'successor-recovery-v1','plan_sha256':plan()[0]['sha256'],'protocol_sha256':p['sha256'],'probe_sha256':probe['sha256'],
            'yields':{role:arm['yield'] for role,arm in probe['arms'].items()},'probe_eligible':probe['eligible'],'probe_reasons':probe['reasons'],
            'promoted':False,'selected_agent_id':'original-parent','sustained_rsi':False}
    if probe['eligible']:
        comparison=compare_successors(p,probe,read('artifacts/successor-recovery-v1/starting-student.json'),read('artifacts/successor-recovery-v1/child-original.json'),read('artifacts/successor-recovery-v1/child-learned.json'),policy=policy())
        result['comparison']=comparison;result['stopping_reason']='paired_children_completed'
    else:result['stopping_reason']='teacher_data_gate_failed'
    last=completed('child-learned' if probe['eligible'] else 'teacher-learned')
    result['budget']=last['budget'];save('artifacts/successor-recovery-v1/summary.json',result);print(json.dumps(result,indent=2))


def main(argv=None):
    global ROOT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare','baseline','freeze-protocol','teacher-original','teacher-learned','child-original','child-learned','report'))
    parser.add_argument('--workspace',type=Path,default=Path.cwd())
    args=parser.parse_args(argv);ROOT=args.workspace.resolve();ws().load_env()
    if args.command=='prepare':prepare()
    elif args.command=='baseline':baseline()
    elif args.command=='freeze-protocol':freeze_protocol()
    elif args.command.startswith('teacher-'):teacher(args.command.split('-',1)[1])
    elif args.command.startswith('child-'):train_child(args.command.split('-',1)[1])
    else:report_results()

if __name__=='__main__':main()
