"""Compose reviewed native training sources before any teacher generation."""
import argparse
import json
from pathlib import Path

from rsi.repair_study import SELECTED, STUDY, validate_cohort
from rsilab import digest
from rsilab.learning import _leak_keys
from rsilab.project import Workspace
from rsilab.task_contracts import apply_task_contracts
from studies.repair_v1.data import prepare as native_prepare

ROOT = Path.cwd()
NATIVE = Path('data/repair-v1')
SUPPLEMENT = Path('data/repair-text-source')
OUTPUT = Path(SELECTED)


def read(path):
    return json.loads((ROOT / path).read_text())


def sealed(record):
    return {**record, 'sha256': digest(record)}


def compose():
    prior = read('data/task-contracts-v1/prior-exposure.json')
    native = read(NATIVE / 'cohort.json')
    native_train = read(NATIVE / 'train-manifest.json')
    evaluation = read(NATIVE / 'evaluation-manifest.json')
    original_tasks = read(NATIVE / 'native-train-sources.json')
    original_reviews = read(NATIVE / 'native-train-reviews.json')
    if digest(apply_task_contracts(original_tasks, original_reviews)) != digest(native_train):
        raise ValueError('Native training manifest failed replay')
    validation = read(SUPPLEMENT / 'validation.json')
    for name, checksum in validation['artifacts_sha256'].items():
        if digest(read(SUPPLEMENT / name)) != checksum:
            raise ValueError('Supplement artifact differs from calibration: '+name)
    # Review caught an observable type requirement missing from native task 830.
    row = next(r for r in original_reviews if r['task_id'] == 'mbpp-full-830')
    row['clarified_prompt'] += ' For zero decimal places return an int. For positive decimal places return a float.'
    row['review_note'] += ' Combined review adds the pinned reference return types; case inputs and expectations are identical.'
    supp_tasks = read(SUPPLEMENT / 'train-sources.json')
    supp_reviews = read(SUPPLEMENT / 'train-reviews.json')
    if any(t['category'] != 'text' or t['metadata']['source_split'] != 'train' for t in supp_tasks):
        raise ValueError('The supplement must contain reviewed native training text tasks')
    quarantine = {'apps-train-4189', 'apps-train-4211'}
    candidates = [(t, r) for t, r in zip(supp_tasks, supp_reviews, strict=True) if t['id'] not in quarantine]
    supp_tasks = [t for t, _ in candidates]
    supp_reviews = [r for _, r in candidates]
    if len(supp_tasks) < 6:
        raise ValueError('Need at least six reviewed supplemental tasks for both roles')
    pairs = list(zip(supp_tasks, supp_reviews, strict=True))
    ranked = sorted(supp_tasks, key=lambda t: digest(['repair-v1-heldback', t['id']]))
    hold_ids = {t['id'] for t in ranked[:min(2, len(supp_tasks) - 5)]}
    train_supp = [(t, r) for t, r in pairs if t['id'] not in hold_ids]
    held_supp = [(t, r) for t, r in pairs if t['id'] in hold_ids]
    training = apply_task_contracts(original_tasks + [t for t, _ in train_supp],
                                    original_reviews + [r for _, r in train_supp])
    if not 24 <= len(training['tasks']) <= 32 or sum(t['category']=='text' for t in training['tasks']) < 6:
        raise ValueError('Insufficient fresh training tasks or text coverage')
    if len(evaluation['tasks']) < 8 or digest(evaluation['tasks']) != digest(native['evaluation']):
        raise ValueError('Insufficient or detached held-back evaluation')
    inventory, _, _ = native_prepare.inventory()
    eval_sources = [inventory[t['metadata']['source_id']] for t in evaluation['tasks']]
    eval_reviews = [native_prepare.review(t) for t in eval_sources]
    if digest(apply_task_contracts(eval_sources, eval_reviews)) != digest(evaluation):
        raise ValueError('Native evaluation manifest failed replay')
    evaluation = apply_task_contracts(eval_sources + [t for t, _ in held_supp],
                                      eval_reviews + [r for _, r in held_supp])
    keys = set().union(*(_leak_keys(t) for t in prior))
    for task in training['tasks'] + evaluation['tasks']:
        new_keys = _leak_keys(task)
        if new_keys & keys:
            raise ValueError('Cohort identity overlap: '+task['id'])
        keys.update(new_keys)
    native_checks = read(NATIVE / 'reference-outputs.json')
    native_evidence = read('studies/repair_v1/data/selection.json')
    if native['sha256'] != native_evidence['cohort_sha256'] or digest(native_checks) != native_evidence['reference_outputs_sha256']:
        raise ValueError('Native reference checks changed')
    checks = {f"mbpp-full-{r['source_id']}": r for r in native_checks}
    for row in read(SUPPLEMENT / 'reference-outputs.json'):
        if row['id'] in checks:
            raise ValueError('Conflicting reference identity')
        checks[row['id']] = row
    roles = {'train': training, 'evaluation': evaluation}
    references = []
    for role, manifest in roles.items():
        for task in manifest['tasks']:
            raw = checks[task['id']]
            references.append({'role':role,'id':task['id'],'task_sha256':digest(task),
                               'reference_sha256':raw['reference_sha256'],'outputs':raw['outputs']})
    links = {role: {'path': str(OUTPUT / f'{role}-manifest.json'), 'sha256': m['sha256']}
             for role,m in roles.items()}
    cohort = sealed({
        'study': STUDY, 'prior_exposure_sha256': digest(prior), 'manifests': links,
        'train':training['tasks'], 'evaluation':evaluation['tasks'], 'reference_checks':references,
        'native_evidence_sha256':digest(native_evidence), 'supplement_validation_sha256':digest(validation),
        'native_cohort_sha256':native['sha256'], 'supplement_sources_sha256':digest(supp_tasks),
        'supplement_reviews_sha256':digest(supp_reviews), 'supplement_slice_sha256':digest(read('studies/repair_text_source/slice.json')),
        'order':'native MBPP first, then APPS in reviewed order within each role',
        'apps_held_back_ids':sorted(hold_ids), 'quarantined_apps_ids':sorted(quarantine),
        'native_type_clarification':'mbpp-full-830',
    })
    plan_fields = {'prior_exposure_sha256':digest(prior),
                   'reviewed_manifest_sha256':{k:v['sha256'] for k,v in roles.items()}}
    validate_cohort(plan_fields,cohort,training,evaluation)
    return {OUTPUT / 'cohort.json':cohort,
            **{OUTPUT / f'{role}-manifest.json':m for role,m in roles.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze',action='store_true')
    args = parser.parse_args()
    results = compose()
    ws = Workspace(ROOT)
    for path, value in results.items():
        if (ROOT / path).exists() and digest(read(path)) != digest(value):
            raise ValueError('Existing cohort differs: '+str(path))
        if not (ROOT / path).exists() and not args.freeze:
            raise FileNotFoundError(path)
    for path,value in results.items():
        if not (ROOT / path).exists():
            ws.write_json(path,value)
    cohort = results[OUTPUT / 'cohort.json']
    print(json.dumps({'sha256':cohort['sha256'],'train':len(cohort['train']),'evaluation':len(cohort['evaluation']),
                      'reference_checks':len(cohort['reference_checks'])}))


if __name__ == '__main__':
    main()
