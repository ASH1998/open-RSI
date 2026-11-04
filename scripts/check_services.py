"""Check configured services without allocating compute or printing credentials.

W&B creates one explicitly synthetic run; all other checks are read-only.
Run with .venv/bin/python scripts/check_services.py SERVICE.
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def configure():
    from dotenv import dotenv_values

    values = dotenv_values(ROOT / '.env')
    for key, value in values.items():
        if value is not None:
            os.environ[key] = value
    # Enforce SSD-local output even if a copied .env has stale paths.
    paths = {
        'HF_HOME': '.cache/huggingface', 'XDG_CACHE_HOME': '.cache',
        'TMPDIR': '.cache/tmp', 'WANDB_DIR': 'runs',
        'WANDB_CACHE_DIR': '.cache/wandb', 'WANDB_CONFIG_DIR': '.config/wandb',
        'WANDB_DATA_DIR': 'work/wandb', 'WANDB_ARTIFACT_DIR': 'artifacts',
        'KAGGLE_CONFIG_DIR': '.config/kaggle',
    }
    for key, relative in paths.items():
        path = ROOT / relative
        path.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(path)
    os.environ['WANDB_CONSOLE'] = 'off'
    os.environ['WANDB_DISABLE_CODE'] = 'true'
    os.environ['WANDB_DISABLE_GIT'] = 'true'


def required(*keys):
    missing = [key for key in keys if not os.environ.get(key)]
    if missing:
        raise ValueError('Missing required configuration: ' + ', '.join(missing))


def check_modal():
    required('MODAL_TOKEN_ID', 'MODAL_TOKEN_SECRET')
    import modal

    # Client handshake validates credentials without creating an app/worker.
    modal.Client.from_env()
    return {'status': 'passed', 'check': 'authenticated client handshake',
            'compute_allocated': False}


def check_kaggle():
    required('KAGGLE_API_TOKEN')
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()
    api.dataset_list(mine=True, page=1)
    return {'status': 'passed', 'check': 'authenticated personal dataset listing',
            'compute_allocated': False}


def check_huggingface():
    from huggingface_hub import HfApi

    token = os.environ.get('HF_TOKEN') or False
    api = HfApi(token=token)
    if token:
        api.whoami()
    model = os.environ.get('RSI_MODEL_ID', 'openbmb/MiniCPM5-2B')
    info = api.model_info(model, revision=os.environ.get('RSI_MODEL_REVISION') or None)
    return {'status': 'passed', 'check': 'model metadata access (no weights downloaded)',
            'authenticated': bool(token), 'model_id': model, 'resolved_revision': info.sha}


def check_wandb():
    required('WANDB_API_KEY', 'WANDB_ENTITY', 'WANDB_PROJECT')
    import wandb

    entity = os.environ['WANDB_ENTITY']
    project = os.environ['WANDB_PROJECT']
    api = wandb.Api(timeout=30)
    if api.project(project, entity=entity) is None:
        raise ValueError('Configured W&B project does not exist or is inaccessible')
    run = wandb.init(
        entity=entity, project=project, mode='online',
        name='service-check-synthetic', job_type='smoke-test',
        tags=['smoke-test', 'synthetic', 'no-training'],
        config={'purpose': 'credential-and-metric-upload-check',
                'synthetic': True, 'training_performed': False},
        settings=wandb.Settings(disable_code=True, disable_git=True,
                                x_disable_meta=True, x_disable_stats=True,
                                console='off', init_timeout=45),
    )
    path = f'{entity}/{project}/{run.id}'
    try:
        for step in range(3):
            run.log({'smoke/step': step, 'smoke/value': step + 1})
        run.summary['smoke_test_passed'] = True
        run.summary['training_performed'] = False
        url = run.url
    finally:
        run.finish()
    # Read back the server-side record rather than trusting local log creation.
    uploaded = wandb.Api(timeout=30).run(path)
    if uploaded.summary.get('smoke/value') != 3:
        raise RuntimeError('Server-side metric readback did not match')
    return {'status': 'passed', 'check': 'online run, metric upload, server readback',
            'url': url, 'run_id': run.id, 'state': uploaded.state,
            'training_performed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('service', choices=['modal', 'kaggle', 'huggingface', 'wandb'])
    args = parser.parse_args()
    configure()
    try:
        result = globals()['check_' + args.service]()
    except Exception as exc:
        # Provider exceptions can contain request headers or sensitive values.
        # Emit only the exception class and HTTP status, never its raw text.
        response = getattr(exc, 'response', None)
        result = {'status': 'failed', 'error_type': type(exc).__name__,
                  'http_status': getattr(response, 'status_code', None)}
    result['service'] = args.service
    destination = ROOT / 'work' / 'service-checks'
    destination.mkdir(parents=True, exist_ok=True)
    (destination / f'{args.service}.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
