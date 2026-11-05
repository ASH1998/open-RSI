"""Seal this study's source, cohort, resource bounds and predeclared comparisons."""
import json
from pathlib import Path

from rsi import repair_study
from rsilab import digest
from rsilab.dataset_io import file_sha256

ROOT = Path.cwd()
STUDY = Path('studies/repair_v1')


def assemble():
    bindings = repair_study.frozen_bindings()
    manifests = {}
    for split in ('train', 'evaluation'):
        source = ROOT / 'data/repair-v1/selected' / f'{split}-manifest.json'
        manifest = json.loads(source.read_text())
        content = {k: v for k, v in manifest.items() if k != 'sha256'}
        if digest(content) != manifest['sha256']:
            raise ValueError(f'{split} manifest seal is invalid')
        manifests[split] = manifest
    training = manifests['train']['tasks']
    evaluation = manifests['evaluation']['tasks']
    if not 24 <= len(training) <= 32 or len(evaluation) < 8:
        raise ValueError('Insufficient reviewed fresh tasks for the preregistered comparison')
    if sum(task['category'] == 'text' for task in training) < 6:
        raise ValueError('At least six fresh text training tasks are required')
    prior = json.loads((ROOT / repair_study.PRIOR).read_text())
    if len(prior) != 284 or digest(prior) != json.loads((ROOT/'studies/task_contracts_v1/results.json').read_text())['exposure']['combined_sha256']:
        raise ValueError('Exposure registry differs from the verified 284-task union')
    ids = [task['id'] for task in training + evaluation + prior]
    if len(set(ids)) != len(ids):
        raise ValueError('Repeated identity across train, held-back evaluation or prior exposure')
    policy = {
        'task_order': 'frozen manifest order for both teachers and all three batches',
        'min_train_tasks': 24, 'max_train_tasks': 32, 'min_text_train': 6, 'min_fresh_evaluation': 8,
        'gate': {'minimum_unique_targets': 16, 'required_categories': ['text','numeric','collections'],
                 'max_category_share': 0.60, 'child_targets_per_arm': 16, 'matched_category_counts': True},
        'passed_first_attempt_second_prompt': 'original prompt in both branches',
        'failed_first_attempt_second_prompt': 'original for sample; own prior code and fixed failure category for repair',
        'primary_endpoint': 'within-teacher paired unique verified yields, greedy+repair minus greedy+sample',
        'child_dataset': 'earliest independent verified greedy or repair output, exact-code/task deduplication',
        'child_evaluation': 'paired starting base and two fresh children on never-generated evaluation and 16 prior retention tasks',
        'child_signal': 'at least three net gains against both base and other child, with no individual retention loss against either',
        'promotion': 'retain original parent', 'automatic_retries': False, 'project_unallocated_floor_usd': 6,
        'budget_family_ceiling_usd': 25, 'invoice_total_usd': None,
    }
    files = [STUDY/'README.md', STUDY/'freeze.py', STUDY/'select_cohort.py', STUDY/'source-amendment.md',
             *sorted((ROOT/'studies/repair_text_source').glob('*.py')),
             ROOT/'studies/repair_text_source/slice.json', ROOT/'studies/repair_text_source/overlap.md',
             STUDY/'data/selection.json', *sorted((ROOT/STUDY/'data').rglob('*.py'))]
    plan = {
        **bindings, 'scientific_policy': policy,
        'reviewed_manifest_sha256': {split: manifest['sha256'] for split,manifest in manifests.items()},
        'design_files_sha256': {str(Path(f).relative_to(ROOT) if Path(f).is_absolute() else f):file_sha256(ROOT/f) for f in files},
    }
    return {**plan, 'sha256':digest(plan)}


def main():
    path = ROOT / repair_study.PLAN
    plan = assemble()
    if path.exists():
        if digest(json.loads(path.read_text())) != digest(plan):
            raise ValueError('Refusing to replace an existing frozen plan')
    else:
        with path.open('x',encoding='utf-8') as stream:
            json.dump(plan, stream, indent=2, allow_nan=False)
            stream.write('\n')
    print(plan['sha256'])


if __name__ == '__main__':
    main()
