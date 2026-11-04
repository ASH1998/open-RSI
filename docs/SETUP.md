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

Use the SSD-local `.venv` and honor the cache paths before installation. The service SDKs and CPU tokenizer tools are pinned in `requirements-tools.txt` and `requirements-tools.lock`. Local PyTorch is not required. The separate Linux GPU image uses `requirements-gpu.txt` for PyTorch, Transformers, PEFT, Accelerate, and bitsandbytes. Model loading, generation, QLoRA training, adapter saving/loading, and matched evaluation passed integration; see `EXPERIMENTS.md` for outcomes and untested recovery limits.

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

- **Modal:** the pilot has created the `open-rsi-artifacts` Volume and mounts it at `/artifacts` for model cache and checkpoints. Public-model GPU workers receive no credentials; W&B logging runs in the controller. Use scoped Modal Secrets only if a future trusted worker needs private-model or tracking access. Keep Modal control credentials in the controller.
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

## MBPP framework and study

See `docs/FRAMEWORK.md` for the SSD-local wheel/install and offline manifest commands. MBPP preparation uses pinned `pyarrow==26.0.1` in the local tool environment. The frozen study launches through `.venv/bin/python -m rsi.study`; inspect `studies/mbpp_v1/protocol.json` and existing run reports before launching to avoid duplicate batches. Only the main chat starts paid stages.

Kaggle's private MBPP worker downloads the public pinned model without secrets. It sends prompts only, saves raw generations, and never executes generated programs. Results return to SSD and are verified in isolated Modal sandboxes. The actual accelerator/precision/package inventory is authoritative: the first submitted NvidiaL4 request ran on Tesla T4, and is reported separately from the L40S paired comparison.

## Rescoring saved MBPP outputs

Evaluator corrections are versioned separately from original studies. The v2 controller is `.venv/bin/python -m rsi.rescore_study`; inspect its frozen protocol and existing arm reports before execution. It uses CPU-only Modal sandboxes, no GPU model invocation. `report` is offline. The original v1 task/compiler/tests remain unchanged, and original scores are retained. See `docs/MBPP_RESCORE_V2.md` and `docs/RESCORING.md` for the data contract and local package 0.1.1.

## Stronger diagnostic controller

`.venv/bin/python -m rsi.robustness_study <freeze|run|report>` manages the separate frozen post-hoc diagnostic. The existing run is complete; do not launch it again. `report` recomputes scores offline from saved evidence. Future controllers should use the durable `rsilab.execution` API and a new protocol instead of changing frozen historical controllers. See `docs/MBPP_ROBUSTNESS.md` and `docs/EXECUTION.md`.

## Verified-data workflow

Local package version 0.2.0 adds `rsilab learning-select`, `rsilab learning-compare`, and `rsilab coding-data-freeze` for offline replay. `rsilab.project.Workspace(root)` explicitly loads that workspace's environment, configures local paths and manages allowlisted tracking plus persistent budget reservations. Nothing launches at import time. See `docs/PROJECT_RUNTIME.md` and `docs/LEARNING.md`.

The current cloud study adapter is `.venv/bin/python -m rsi.verified_study <prepare|collect|improve-data|train-evaluate|report>` from the SSD checkout. Only the main chat runs paid stages. Inspect saved reports and the ledger first: stages must not be duplicated, and failed reservations persist. All stage source identities are frozen; fixes require a new versioned protocol. The historical GPU worker needs the checkout's pinned `requirements-gpu.txt`; installation alone does not provide a standalone cloud launcher. The experiment is complete; do not rerun its paid stages. `report` is offline and reproducible. See `docs/VERIFIED_SFT_EXPERIMENT.md` for saved outputs and installed-library replay checks.

## Portable worker and successor probe

The new `rsilab.providers.portable_modal` factory uses packaged worker code and pinned requirements, without a checkout-relative requirements file. See `PORTABLE_MODAL.md` for explicit configuration, adapter byte-hash binding, bounds and optional dependencies. It launches nothing at import or construction. The new project adapter is `python -m rsi.successor_study --workspace /absolute/project/root COMMAND`; all local work in this project still uses the canonical SSD. Only main may run its paid commands after reviewing frozen plans and existing reports. The public library quickstart uses a caller-selected project directory.

Use `rsilab.dataset_io.read_development_splits` for explicit pinned train/validation reads. The legacy `load_mbpp()` eagerly decoded final rows before callers filtered splits; historical final-test evaluation was never run, but earlier 'never decoded' prose was incorrect. New development code must not call that legacy all-splits reader.

The successor-v1 calibration is now stopped at a data-category gate. Do not retry its paid commands. The raw run and original source remain frozen; a new protocol is needed after the category correction and preflight. See `SUCCESSOR_EXPERIMENT.md`. The immutable 0.3.0 wheel and installed tests passed, but no portable GPU function executed, so remote portable inference/training validation remains pending.

The user has now authorized a separate recovery study: `python -m rsi.successor_recovery COMMAND`. Its commands and bounds are in `studies/successor_recovery_v1/README.md`. This does not reopen the failed v1 stage. New reference-reuse and preflight APIs are packaged for 0.4.0; historical 0.3.0 wheel/source identities remain preserved. Only main launches paid recovery stages, with a new frozen plan and cumulative budget reservations.

Current executable recovery: `python -m rsi.successor_recovery_v2 COMMAND`, using `rsilab.providers.portable_modal_v2`. V1 remains a preserved failed startup; do not rerun it. The corrected factory sets runtime cache environment variables after dependency installation so image layers leave the volume mount empty. Five $4 reservations plus the preserved failed $5 fit the existing $25 recovery allocation.
