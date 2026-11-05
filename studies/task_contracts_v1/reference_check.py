"""Run the twenty pinned MBPP *references* for this offline diagnostic only.

Incoming requests carry task IDs and typed inputs. The pinned train Parquet is
the sole code source. This program is not a runner for generated programs.
"""
import hashlib
import json
import resource
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# This script runs under Python -I. Import the audited checkout explicitly.
sys.path.insert(0, str(ROOT))
from rsi.datasets import SOURCE_HASHES
from rsi.mbpp_verification_v2 import decode_value, encode_value
from rsi.verification import extract_code, validate_code
from rsilab import digest
from rsilab.dataset_io import read_development_splits

TRAIN_SEAL = '764949f038295e2ab0e8e0abdef6f70b9c141e2432f74038d82184be14e847c7'


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    original = json.loads((ROOT/'data/successor-recovery-v3/audited-dataset.json').read_text())['train']
    if digest(original) != TRAIN_SEAL:
        raise ValueError('Historical training cohort has changed')
    requests = json.load(sys.stdin)
    if len(requests) != len(original):
        raise ValueError('Expected the complete reviewed training cohort')
    rows = read_development_splits(ROOT/'data/mbpp/raw', source_hashes=SOURCE_HASHES,
                                   expected_counts={'train':374}, splits=('train',))
    pinned = {row['task_id']: row for row in rows['train']}
    results = []
    for task, request in zip(original, requests, strict=True):
        if set(request) != {'task_id','inputs'} or request['task_id'] != task['id']:
            raise ValueError('Reference request differs from the pinned cohort')
        row = pinned[task['metadata']['source_id']]
        if digest(row) != task['metadata']['source_row_sha256']:
            raise ValueError('Reference row identity changed')
        reference = extract_code(row['code'])
        sha = hashlib.sha256(reference.encode()).hexdigest()
        if sha != task['metadata']['verified_data']['reference_sha256']:
            raise ValueError('Reference implementation changed')
        validate_code(reference, task['entry_point'], allowed_imports=frozenset({'math'}))
        namespace = {}
        exec(compile(reference, '<pinned MBPP training reference>', 'exec'), namespace)
        function = namespace[task['entry_point']]
        outputs = []
        for case in request['inputs']:
            if set(case) != {'args', 'kwargs'}:
                raise ValueError('Pass only arguments to the reference')
            value = function(*decode_value(case['args']), **decode_value(case['kwargs']))
            outputs.append({'ok':True, 'value':encode_value(value)})
        results.append({'task_id':task['id'], 'reference_sha256':sha, 'outputs':outputs})
    json.dump(results, sys.stdout, allow_nan=False)


if __name__ == '__main__':
    main()
