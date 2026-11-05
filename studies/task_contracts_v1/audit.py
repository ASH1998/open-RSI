"""Rebuild this offline diagnostic from the sealed recovery and native training data."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from rsi.datasets import SOURCE_HASHES, REVISION, model_input
from rsi.mbpp_verification_v2 import evaluator_source_hashes
from rsilab import digest
from rsilab.dataset_io import file_sha256
from rsilab.project import Workspace
from rsilab.task_contracts import apply_task_contracts, replay_task_contracts, score_task_contract_outputs

ROOT = Path.cwd()
STUDY = Path('studies/task_contracts_v1')
PARENT_SHA = '0cba1d12bb4f06c051566ac9e9d58923d1ad108475a34f6b04aa4cb3aa0060ba'


def read(path):
    return json.loads((ROOT / path).read_text())


def source_registries():
    protocol = read('data/successor-recovery-v3/protocol.json')
    contents = {k: v for k, v in protocol.items() if k != 'sha256'}
    if protocol['sha256'] != PARENT_SHA or digest(contents) != PARENT_SHA:
        raise ValueError('Original protocol identity differs')
    registries = protocol['registries']
    audited = read('data/successor-recovery-v3/audited-dataset.json')
    if digest(audited['train']) != digest(registries['train']):
        raise ValueError('Source training records differ from the frozen protocol')
    return registries


def exposure_registry(registries):
    prior, attempted = registries['prior_exposure'], registries['train']
    rows = prior + attempted
    if len({row['id'] for row in rows}) != len(rows):
        raise ValueError('Duplicate exposure identity')
    evaluation_ids = {t['id'] for t in registries['dev'] + registries['retention']}
    if not evaluation_ids <= {t['id'] for t in prior}:
        raise ValueError('Evaluation exposure is missing')
    return {
        'source_protocol_sha256': PARENT_SHA,
        'previous_count': len(prior),
        'previous_sha256': digest(prior),
        'additional_ids': [t['id'] for t in attempted],
        'combined_count': len(rows),
        'combined_sha256': digest(rows),
        'full_registry_location': 'data/task-contracts-v1/prior-exposure.json',
    }, rows


def check_references(tasks):
    requests = [
        {'task_id': task['id'], 'inputs': [{k: c[k] for k in ('args', 'kwargs')} for c in task['cases']]}
        for task in tasks
    ]
    # Start a credential-free interpreter. The child loads the pinned reference itself.
    sub = subprocess.run([sys.executable,'-I','-B',str(ROOT/STUDY/'reference_check.py')],
                         input=json.dumps(requests,allow_nan=False), text=True, capture_output=True,
                         env={'TMPDIR':str(ROOT/'.cache/tmp')}, cwd=ROOT, timeout=45)
    if sub.returncode:
        raise RuntimeError('Pinned reference check failed: '+sub.stderr[-1200:])
    return json.loads(sub.stdout)


def build():
    registries = source_registries()
    sources = registries['train']
    reviews = read(STUDY/'reviews.json')
    manifest = apply_task_contracts(sources,reviews)
    replay_task_contracts(sources,reviews,manifest,expected_sha256=manifest['sha256'])
    reference_rows = check_references(manifest['tasks'])
    tasks = []
    checked = zip(sources, reviews, manifest['tasks'], manifest['prompts'], reference_rows, strict=True)
    for source, review, task, prompt, reference in checked:
        visible = model_input(task)
        if prompt != {'id':task['id'],'prompt':visible['prompt']} or visible['entry_point'] != source['entry_point']:
            raise ValueError('Generation projection differs from the reviewed contract')
        if reference['task_id'] != source['id']:
            raise ValueError('Reference outputs belong to a different task')
        inherited = len(source['cases'])
        score = score_task_contract_outputs(manifest, task['id'], reference['outputs'],
                                            expected_sha256=manifest['sha256'])
        if not score['passed'] or digest(task['cases'][:inherited]) != digest(source['cases']):
            raise ValueError(f'Inherited or new reference case failed on {task["id"]}: {score["errors"]}')
        added = task['cases'][inherited:]
        for boundary, case, output in zip(review['boundaries'],added,reference['outputs'][inherited:],strict=True):
            if case['expected'] != boundary['expected'] or output['value'] != boundary['expected']:
                raise ValueError(f'Typed reference mismatch on {source["id"]}/{boundary["name"]}')
        tasks.append({
            'id': task['id'],
            'category': source['category'],
            'original_cases': inherited,
            'new_cases': len(added),
            'reference_cases_passed': score['count'],
            'reference_sha256': reference['reference_sha256'],
            'derived_task_sha256': digest(task),
        })
    exposure, all_rows = exposure_registry(registries)
    code_paths = (STUDY / 'audit.py', STUDY / 'reference_check.py', Path('rsilab/task_contracts.py'))
    summary = {
        'study': 'task-contracts-v1',
        'scope': 'post-hoc training data diagnostic',
        'source_protocol_sha256': PARENT_SHA,
        'dataset_revision': REVISION,
        'train_parquet_sha256': SOURCE_HASHES['full/train-00000-of-00001.parquet'],
        'reviews_sha256': digest(reviews),
        'derived_manifest_sha256': manifest['sha256'],
        'reference_outputs_sha256': digest(reference_rows),
        'evaluator_source_hashes': evaluator_source_hashes(),
        'source_files_sha256': {str(path): file_sha256(ROOT / path) for path in code_paths},
        'tasks': tasks,
        'original_cases': sum(t['original_cases'] for t in tasks),
        'new_cases': sum(t['new_cases'] for t in tasks),
        'reference_cases_passed': sum(t['reference_cases_passed'] for t in tasks),
        'exposure': exposure,
        'model_attempts': 0,
        'modal_reservations_usd': 0,
    }
    return {
        Path('data/task-contracts-v1/manifest.json'): manifest,
        Path('data/task-contracts-v1/prior-exposure.json'): all_rows,
        Path('artifacts/task-contracts-v1/reference-outputs.json'): reference_rows,
        STUDY / 'results.json': summary,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze',action='store_true',help='Create missing evidence after all checks pass')
    args = parser.parse_args()
    outputs = build()
    for path, value in outputs.items():
        if (ROOT/path).exists():
            if digest(read(path)) != digest(value):
                raise ValueError('Saved evidence differs: '+str(path))
        elif not args.freeze:
            raise FileNotFoundError(path)
    if args.freeze:
        workspace = Workspace(ROOT)
        for path, value in outputs.items():
            if not (ROOT/path).exists():
                workspace.write_json(path,value)
    print(json.dumps({k:outputs[STUDY/'results.json'][k] for k in
                      ('derived_manifest_sha256','original_cases','new_cases','reference_cases_passed')}))


if __name__ == '__main__':
    main()
