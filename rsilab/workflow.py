"""Provider-neutral collection/verification primitives for verified SFT studies."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict
from .execution import execute_bounded,ExecutionAborted
from .core import digest


def check_verification(result):
    if result.get('infrastructure_error') or result.get('error_kind') in ('infrastructure','invalid_task'):
        raise ValueError('Verification infrastructure failure; collection incomplete')


def verify_records(items, *, execute, report, key, persist, validate=check_verification, workers=4):
    """Save every outcome before validation, including exceptions and abort evidence."""
    saved={};report[key]=[]
    def save(record):
        saved[record.item_id]=asdict(record)
        report[key]=[saved[x['id']] for x in items if x['id'] in saved]
        persist(report)
    try:
        summary=execute_bounded(items,identify=lambda x:x['id'],execute=execute,persist=save,
                               validate=lambda item,result:validate(result),max_workers=workers,max_in_flight=workers)
    except ExecutionAborted as error:
        report[key+'_execution']=error.summary.to_dict();persist(report);raise
    report[key+'_execution']=summary.to_dict();persist(report)
    return [r['result'] for r in report[key]]


class VerifiedCollector:
    """Generate text through an injected backend, verify remotely, retain every row.

    Backend controls compute and durable call IDs. Verifier controls isolation.
    Only public task prompts reach generation; tests/reference code stay trusted.
    """
    def __init__(self, *, backend, verify, extract_code, report, persist, batch_size=64):
        if type(batch_size) is not int or not 1<=batch_size<=64:raise ValueError('Invalid batch size')
        self.backend=backend;self.verify=verify;self.extract=extract_code
        self.report=report;self.persist=persist;self.batch_size=batch_size

    def collect(self,tasks,*,settings,key,prompts=None):
        if key in self.report:raise ValueError('Collection key already exists; no duplicate generation')
        if len({t['id'] for t in tasks})!=len(tasks):raise ValueError('Duplicate collection task IDs')
        if prompts is not None and set(prompts)!={t['id'] for t in tasks}:raise ValueError('Prompt identities differ')
        self.report[key]=[];self.report[key+'_batches']=[];self.persist(self.report)
        for offset in range(0,len(tasks),self.batch_size):
            batch=tasks[offset:offset+self.batch_size]
            request={**settings,'prompts':[{'id':t['id'],'prompt':prompts[t['id']] if prompts is not None else t['prompt']} for t in batch]}
            generated=self.backend.generate(request)
            self.report[key+'_batches'].append({'request_sha256':digest(request),'settings':deepcopy(settings),'generation':deepcopy(generated)})
            self.persist(self.report)
            outputs=generated.get('outputs',[])
            if generated.get('status')!='completed' or any(o.get('hit_time_limit') for o in outputs):
                raise ValueError('Generation incomplete; do not score partial batches')
            if [t['id'] for t in batch]!=[o.get('id') for o in outputs]:raise ValueError('Generation identity/order mismatch')
            items=[{'id':t['id'],'task':t,'generation':o} for t,o in zip(batch,outputs)]
            def verify(item):
                if item['generation'].get('hit_token_limit'):
                    return {'passed':False,'count':0,'total':len(item['task']['cases']),
                            'errors':['generation_token_limit'],'error_kind':'generation_limit','sandbox_id':None}
                return self.verify(item['generation']['text'],item['task'])
            values=verify_records(items,execute=verify,report=self.report,key=f'{key}_verification_{offset}',persist=self.persist)
            for item,result in zip(items,values):
                row={'task':deepcopy(item['task']),'generation':deepcopy(item['generation']),
                     'verification':result,'generation_settings':deepcopy(settings),
                     'generation_batch_index':offset//self.batch_size,
                     'generation_provenance':{k:deepcopy(generated[k]) for k in ('model_id','revision','gpu_name','packages','cuda_version','temperature','max_new_tokens','seed','enable_thinking') if k in generated}}
                if result['passed']:row['verified_code']=self.extract(item['generation']['text'])
                self.report[key].append(row)
            self.persist(self.report)
        return self.report[key]
