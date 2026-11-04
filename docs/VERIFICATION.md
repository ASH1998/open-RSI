# Service verification

Verified November 4, 2026, from `/Volumes/DevSSDWD/openbmb/rsi` using the project-local `.venv` (Python 3.13). Credentials remain in the ignored `.env`.

| Service | Result | Evidence and boundary |
| --- | --- | --- |
| W&B | Passed | Created a synthetic run in `ashu-na/rsi`, uploaded three metric steps, finished the run, and read the final metric back from the server. |
| Modal | Passed | Authenticated SDK client handshake. No app, Sandbox, or GPU worker was created. |
| Kaggle | Passed | Authenticated and successfully requested the account's own dataset listing. No notebook or accelerator was started. |
| Hugging Face | Passed | Updated token passed identity verification and authenticated metadata access for the pinned `openbmb/MiniCPM5-2B` revision. No model weights downloaded. |

W&B test: https://forge.coreweave.com/wandb/ashu-na/rsi/runs/y4x41q13

The run is named `service-check-synthetic`, tagged `smoke-test`, `synthetic`, and `no-training`, and records `training_performed=false`. Its synthetic values validate transport only; they are not accuracy or training results. Code, console capture, system metadata, and system statistics were disabled for this check.

## Corrections made

- Set local `.env` to `WANDB_ENTITY=ashu-na`, `WANDB_PROJECT=rsi`, and `WANDB_MODE=online`, matching the user's existing project.
- Updated the non-secret entity/project defaults in `.env.example`; its mode remains offline for a new unconfigured checkout.
- Restricted `.env` file permissions to the owner.
- Installed provider SDKs in `.venv` and package caches on the SSD. Added the missing `six` dependency needed by Kaggle's import path.
- Resolved the provisional model revision to `f97400052a43d642bbc6e9975e2397e3ae6a6b52` and pinned it in local `.env`.
- Initial public access passed without a token. The first token returned HTTP 401; the user replaced it, and the subsequent identity and authenticated model-metadata checks passed. Authenticated uploads remain untested.

## Repeating checks

Run from the project root:

```sh
.venv/bin/python scripts/check_services.py modal
.venv/bin/python scripts/check_services.py kaggle
.venv/bin/python scripts/check_services.py huggingface
.venv/bin/python scripts/check_services.py wandb
```

The final command creates a new online synthetic W&B run each time. Sanitized JSON results are saved to ignored `work/service-checks/`. The SDK versions are specified in `requirements-tools.txt`; the complete validated local environment is in `requirements-tools.lock`.

Modal, Kaggle, and Hugging Face authentication and W&B metric transport are working. GPU/TPU availability, quotas, billing balances, model loading, fine-tuning compatibility, and checkpoint storage have not been tested. No paid compute or training was started by these checks.
