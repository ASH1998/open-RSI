"""Offline replay of successor-v1 category failure and proposed correction.

Run from the project root with ``python -m scripts.check_successor_categories``.
Requires local saved evidence. Does not alter evidence or start provider work.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from rsilab import digest
from rsilab.preflight import preflight_task_categories


def check(root):
    proposal = json.loads((root / 'studies/successor_v1/category-correction-proposal.json').read_text())
    if digest({k: v for k, v in proposal.items() if k != 'sha256'}) != proposal['sha256']:
        raise ValueError('Correction proposal hash differs')
    for binding in proposal['source_artifacts'].values():
        path = root / binding['path']
        if hashlib.sha256(path.read_bytes()).hexdigest() != binding['file_sha256']:
            raise ValueError('Original evidence differs: ' + binding['path'])
    report = json.loads((root / proposal['source_artifacts']['failed_calibration']['path']).read_text())
    original = [audit['task'] for audit in report['audits']]
    expected = {item['task_id']: item['independently_reviewed_category'] for item in proposal['items']}
    try:
        preflight_task_categories(original, first_n=20, min_categories=3,
                                  min_pool_count=24, expected_categories=expected)
    except ValueError as error:
        if 'disagrees with reviewed mapping' not in str(error):
            raise
        rejection = str(error)
    else:
        raise ValueError('Historical category failure was not reproduced')
    proposed = deepcopy(original)
    for task in proposed:
        task['category'] = expected[task['id']]
    strip = lambda tasks: [{k: v for k, v in task.items() if k != 'category'} for task in tasks]
    if strip(original) != strip(proposed):
        raise ValueError('Correction changes fields beyond category')
    summary = preflight_task_categories(proposed, first_n=20, min_categories=3,
                                       min_pool_count=24, expected_categories=expected)
    return {'status': 'offline_proposal_check_only', 'original_rejection': rejection,
            'proposal_sha256': proposal['sha256'], 'report_sha256': digest(report),
            'proposed_categories': summary,
            'non_category_fields_and_order_unchanged': True,
            'limitations': 'No transformed dataset or protocol created. Original task hashes are preserved only in original evidence. Future protocol must bind derived task hashes and evidence reuse explicitly.'}


if __name__ == '__main__':
    print(json.dumps(check(Path.cwd()), indent=2))
