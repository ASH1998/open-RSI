"""One explicit, budgeted recovery of the v2 seed-43 infrastructure abort."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from rsi.config import load_local_env
from rsi.rescore_study import load_plan,original_reports,arm_lock,checked
from rsi.pilot import stage,persist,write_json,scores,load_report
from rsi.budget import Budget
from rsi.mbpp_verification_v2 import verify_mbpp_candidate
from rsilab import digest


def main():
    load_local_env()
    import modal,wandb,os
    protocol=json.loads((ROOT/'studies/mbpp_rescore_v2/recovery.json').read_text())
    plan,sources=load_plan()
    if protocol['rescore_protocol_sha256']!=plan['sha256']:
        raise ValueError('Recovery protocol mismatch')
    if protocol['controller_sha256']!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError('Recovery controller changed after authorization record')
    with arm_lock('seed-43'):
        path=ROOT/'runs'/protocol['failed_run_id']/'report.json'
        raw=path.read_bytes();old=json.loads(raw)
        if old.get('status')!='failed' or hashlib.sha256(raw).hexdigest()!=protocol['failed_report_file_sha256']:
            raise ValueError('Expected the preserved failed attempt; refusing duplicate recovery')
        for p in (ROOT/'runs').glob('*/report.json'):
            r=json.loads(p.read_text())
            if r.get('stage')=='mbpp-rescore-v2-recovery' and r.get('source_run_id')==old['run_id']:
                raise ValueError('Recovery already attempted; inspect saved evidence')
        saved={x['task']['id']:x for p in old['rescores'] for x in p['records']}
        missing=[x for p in sources['seed-43'] for x in p['records'] if x['task']['id'] not in saved]
        if [x['task']['id'] for x in missing]!=protocol['missing_task_ids'] or digest(missing)!=protocol['missing_records_sha256']:
            raise ValueError('Recovery changed saved generation inputs or task selection')
        with stage('mbpp-rescore-v2-recovery') as (recovery,run):
            recovery.update(source_run_id=old['run_id'],rescore_protocol_sha256=plan['sha256'],
                            recovery_protocol_sha256=digest(protocol),failed_report_file_sha256=protocol['failed_report_file_sha256'],
                            evaluator_source_hashes=plan['evaluator_source_hashes'],records=[])
            run.use_artifact(f"{run.entity}/{run.project}/{old['run_id']}:v0",type='pilot-report')
            app=modal.App('open-rsi-mbpp-v2-recovery',include_source=False)
            with app.run():
                recovery['modal_app_id']=app.app_id;persist(recovery)
                for row in missing:
                    result=verify_mbpp_candidate(row['generation']['text'],row['task'],app)
                    # Persist even failed infrastructure results before checking.
                    record={'task':row['task'],'generation':row['generation'],
                            'original_verification':row['verification'],'verification':result}
                    recovery['records'].append(record);persist(recovery)
                    checked(result)
                    print(json.dumps({'recovered':row['task']['id'],'passed':result['passed']}),flush=True)
        recovery=load_report(recovery['run_id'])
        merged={**saved,**{x['task']['id']:x for x in recovery['records']}}
        for source,part in zip(sources['seed-43'],old['rescores']):
            part['records']=[merged[x['task']['id']] for x in source['records']]
            part['status']='completed'
        old['initial_attempt_status']='failed'
        old['status']='completed'
        old['recovery']={'run_id':recovery['run_id'],'budget_reservation':recovery['budget_reservation'],
            'failed_report_file_sha256':protocol['failed_report_file_sha256'],
            'original_failed_artifact':old['run_id']+':v0','missing_task_ids':protocol['missing_task_ids'],
            'modal_app_id':recovery['modal_app_id'],'recovery_protocol_sha256':digest(protocol),
            'note':'Only absent records were reverified. The initial failed report and budget reservation are retained.'}
        rows=[x for p in old['rescores'] for x in p['records']]
        old['scores']=scores(rows);old['changed_task_ids']=[x['task']['id'] for x in rows if x['verification']['passed']!=x['original_verification']['passed']]
        old['budget']=Budget().summary();persist(old)
        w=wandb.init(entity=os.environ['WANDB_ENTITY'],project=os.environ['WANDB_PROJECT'],id=old['wandb_url'].rsplit('/',1)[-1],resume='must',mode='online',settings=wandb.Settings(disable_code=True,disable_git=True,x_disable_meta=True,x_disable_stats=True,console='off'))
        w.use_artifact(f"{w.entity}/{w.project}/{recovery['run_id']}:latest",type='pilot-report')
        a=wandb.Artifact(old['run_id'],type='pilot-report');a.add_file(str(path),name='report.json');w.log_artifact(a).wait()
        w.log({f'{k}/pass_rate':v['rate'] for k,v in old['scores'].items()});w.summary['status']='completed';w.summary['initial_attempt_status']='failed';w.summary['recovery_run']=recovery['run_id'];w.finish()
        print(json.dumps({'run_id':old['run_id'],'scores':old['scores'],'recovery_run':recovery['run_id']}))

if __name__=='__main__':main()
