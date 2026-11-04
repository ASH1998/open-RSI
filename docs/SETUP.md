# Environment and provider setup

Last checked: November 4, 2026. Provider checks are implemented in `scripts/check_services.py`; see `VERIFICATION.md` for results. The variables below are a proposed contract for future launchers; SDK variables work only after loading them into the process environment.

## Local workspace

All local project files must remain under `/Volumes/DevSSDWD/openbmb/rsi`. This includes package installations, model caches, credentials, logs, and temporary work. Do not fall back to the old Documents/Codex directory.

When ready to configure the project, run from the SSD folder:

```sh
cd /Volumes/DevSSDWD/openbmb/rsi
cp -n .env.example .env
chmod 600 .env
mkdir -p .cache/huggingface .cache/pip .cache/uv .cache/torch .cache/tmp
mkdir -p .cache/wandb .config/wandb .config/kaggle work data models checkpoints runs artifacts
```

Edit `.env` locally. All secret values in the template are blank. Load it through an explicit dotenv loader in future Python entrypoints, before importing provider SDKs. CLI processes need the same variables exported; a `.env` file alone is not automatically consumed by every SDK. Do not print it or dump the entire process environment.

Use a local `.venv` for future dependencies and honor the cache paths before installation. Planned components are Python, PyTorch, Transformers, PEFT, TRL, bitsandbytes for a compatible CUDA QLoRA path, Modal, wandb, Kaggle CLI, huggingface_hub, and python-dotenv. Version locks are intentionally pending the model/GPU compatibility test. The service SDKs are installed in the SSD-local `.venv`; exact versions are recorded in `requirements-tools.lock`. Training packages are not installed.

`RSI_*` entries are project-defined settings that future code must implement; they are not provider SDK controls. `RSI_MODEL_REVISION` must be resolved to an immutable commit before recorded experiments. Do not log unresolved `main` as a reproducible revision.

## Credentials

| Service | Variables | When needed / where to obtain them |
| --- | --- | --- |
| Modal | `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` | Required for authenticated Modal jobs. Create a token in Modal account/workspace settings. Use environment authentication to avoid writing a home-directory profile. |
| W&B | `WANDB_API_KEY` | Required for online tracking. Obtain through W&B/CoreWeave Forge account settings. |
| W&B destination | `WANDB_ENTITY`, `WANDB_PROJECT` | Entity is your user/team namespace; entity is `ashu-na` and project is `rsi`. These are identifiers, not secrets. |
| Kaggle | `KAGGLE_API_TOKEN` | Optional, needed for secondary-provider API/CLI use. Generate at https://www.kaggle.com/settings/api. |
| Hugging Face | `HF_TOKEN` | Optional for public downloads; needed for gated/private assets or authenticated uploads. Create an appropriately scoped token at https://huggingface.co/settings/tokens. |

No separate OpenBMB key, OpenAI API key, CoreWeave compute key, AWS key, or paid teacher-model credential is needed for the present design. Add credentials only if a later integration actually requires them. GitHub authentication is handled by the Git credential manager or GitHub CLI; do not put a GitHub token in remote URLs or this template.

Modal documents the token pair above. Kaggle's current CLI documents `KAGGLE_API_TOKEN`; older clients may use legacy credentials, but the project should standardize on one supported client rather than mixing authentication methods. [Modal configuration](https://modal.com/docs/sdk/py/latest/config), [Kaggle authentication](https://github.com/Kaggle/kaggle-cli/blob/main/docs/README.md)

W&B environment variables are documented in the SDK source. Use the endpoint configured for your account; a branding/login migration alone does not justify changing the SDK API URL. `WANDB_MODE=offline` in the template permits local work without uploading. Switch to `online` for authenticated live tracking. Preserve offline logs for later synchronization. [SDK variables](https://github.com/wandb/wandb/blob/main/wandb/env.py)

`HF_HOME` places Hub cache/auth files under the SSD. Set it before importing the Hub client. [Hugging Face environment reference](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables)

## Remote configuration

Do not upload the local `.env` as code or mount the entire checkout into a worker without exclusions. Construct a per-job allowlist of required settings and secrets.

- **Modal:** use Modal Secrets for trusted workers that need `WANDB_API_KEY` or `HF_TOKEN`. Keep Modal control credentials in the controller. Mount the proposed `open-rsi-artifacts` Volume for persistent data/checkpoints. This name is a proposal; the Volume has not been created.
- **Generated-code Sandboxes:** provide only task inputs, bounded resources, and required runtime dependencies. Keep authoritative evaluators outside candidate-writable paths. Avoid giving these workers account tokens or unrelated project data.
- **Kaggle:** use Kaggle Secrets for W&B/Hugging Face access and enable internet only when the job needs it. The Kaggle API token generally belongs to the submitting client, not the training notebook. Save resumable outputs before session limits and export them explicitly.
- **Paths:** replace macOS SSD paths with worker-local paths, for example `/rsi` for a Modal mount and `/kaggle/working/rsi` on Kaggle. Never send the local path values blindly to Linux workers.

The controller must record durable job IDs/status and know how to resume after interruption. A model adapter plus a fixed base revision can reproduce inference, but resuming optimization also needs training-state files. Terminate unused workers; placeholder configuration does not enforce time or spending limits.

## Git and artifact backup

The remote is https://github.com/ASH1998/open-RSI.git. Commit source, notebooks with outputs cleared, dependency locks, configuration templates, and documentation. Keep `.env`, caches, datasets, model weights, adapters, checkpoints, and raw run logs ignored.

A source push is not a backup of ignored experiment outputs. Retain those in persistent cloud storage and copy selected results to this SSD with checksums. Set dataset/model visibility deliberately when exports are eventually implemented; do not publish artifacts as an incidental part of saving a run.

## Run the service checks

Use `.venv/bin/python scripts/check_services.py SERVICE`, with `SERVICE` equal to `modal`, `kaggle`, `huggingface`, or `wandb`. The W&B check explicitly uses online mode and creates a clearly labeled synthetic run; the others only read provider metadata. The script loads `.env`, keeps output on the SSD, and never prints raw provider exceptions or credentials. Each rerun of the W&B check creates a new run.

To reproduce the validated service environment, install `requirements-tools.lock` in a project-local virtual environment with the cache variables above. This lock describes the macOS/Python 3.13 service-check environment, not the future Linux GPU training environment.
