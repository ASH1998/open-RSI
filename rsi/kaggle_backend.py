"""Build an explicit, private Kaggle upload containing only public generation inputs."""
import hashlib
import json
from pathlib import Path
import re

from .modal_workers import MODEL_ID, MODEL_REVISION


def prepare_kernel(request, destination, username, title='Open RSI MBPP Baseline V1'):
    allowed = {'model_id', 'revision', 'prompts', 'seed', 'max_new_tokens', 'manifest_hash'}
    if set(request) != allowed or request['model_id'] != MODEL_ID or request['revision'] != MODEL_REVISION:
        raise ValueError('Kaggle request must contain only the pinned model and allowed generation fields')
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', username):
        raise ValueError('Invalid Kaggle username')
    if not 1 <= len(request['prompts']) <= 64:
        raise ValueError('Kaggle batches contain 1 to 64 prompts')
    if request['seed'] != 42 or request['max_new_tokens'] != 512:
        raise ValueError('This baseline fixes seed 42 and 512 output tokens')
    for item in request['prompts']:
        if set(item) != {'id', 'prompt'} or not all(isinstance(v, str) and v for v in item.values()):
            raise ValueError('Only nonempty IDs and public prompts may be uploaded')
        if len(item['prompt']) > 30000:
            raise ValueError('Prompt is oversized')
    source = Path(__file__).with_name('kaggle_worker.py').read_text()
    marker = 'REQUEST = None  # Replaced with a JSON-only payload by kaggle_backend.prepare_kernel.'
    source = source.replace(marker, 'REQUEST = json.loads(' + repr(json.dumps(request)) + ')')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'worker.py').write_text(source)
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
    metadata = {'id': f'{username}/{slug}', 'title': title, 'code_file': 'worker.py',
                'language': 'python', 'kernel_type': 'script', 'is_private': True,
                'enable_gpu': True, 'enable_internet': True, 'machine_shape': 'NvidiaL4',
                'dataset_sources': [], 'competition_sources': [], 'kernel_sources': [], 'model_sources': []}
    (destination / 'kernel-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    audit = {'kernel': metadata['id'], 'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
             'request': request, 'session_timeout_seconds': 3600, 'private': True}
    (destination / 'upload-audit.json').write_text(json.dumps(audit, indent=2) + '\n')
    return audit
