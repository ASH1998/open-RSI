"""Load local configuration without passing local secrets to remote workers."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_local_env():
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=True)
    configured = os.environ.get('RSI_PROJECT_ROOT')
    if configured and Path(configured).resolve() != ROOT:
        raise RuntimeError('RSI_PROJECT_ROOT does not match this checkout')
    for key, relative in {
        'HF_HOME': '.cache/huggingface', 'TMPDIR': '.cache/tmp',
        'XDG_CACHE_HOME': '.cache', 'WANDB_DIR': 'runs',
        'WANDB_CACHE_DIR': '.cache/wandb', 'WANDB_CONFIG_DIR': '.config/wandb',
        'WANDB_DATA_DIR': 'work/wandb', 'WANDB_ARTIFACT_DIR': 'artifacts',
    }.items():
        path = ROOT / relative
        path.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(path)
    os.environ['WANDB_CONSOLE'] = 'off'
    os.environ['WANDB_DISABLE_CODE'] = 'true'
    os.environ['WANDB_DISABLE_GIT'] = 'true'


def model_config():
    import re
    model_id = os.environ.get('RSI_MODEL_ID', 'openbmb/MiniCPM5-2B')
    revision = os.environ.get('RSI_MODEL_REVISION', '')
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('RSI_MODEL_REVISION must be an immutable 40-character commit')
    return {'model_id': model_id, 'revision': revision}
