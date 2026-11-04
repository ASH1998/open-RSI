# Open RSI

A small-model research project investigating whether a model can learn from verified execution experience and eventually improve how it produces its successors.

**Status:** provider credential checks and a synthetic W&B run have passed; a reusable service-check script is available. No model has been downloaded, no training pipeline exists, and no paid jobs have been launched. Updated November 4, 2026.

## Workspace and repository

- Canonical local workspace: `/Volumes/DevSSDWD/openbmb/rsi`
- GitHub repository: https://github.com/ASH1998/open-RSI
- Keep all project files, local dependencies, caches, downloads, checkpoints, and scratch work within this SSD directory. Remote workloads use their provider's storage; local copies belong here.
- Git backs up source and documentation. Large datasets, model weights, and secrets stay out of Git.

## Current direction

| Area | Decision |
| --- | --- |
| Model | Prefer an OpenBMB 2B-class text model. `openbmb/MiniCPM5-2B` is the provisional checkpoint, pending a capability and compatibility check. |
| Primary compute | Modal for inference, training, evaluation, orchestration, and isolated code execution. |
| Secondary compute | Kaggle for optional small GPU/TPU experiments. The core loop must work without it. |
| Tracking | W&B, now part of CoreWeave Forge, across both providers. CoreWeave compute is not required. |
| Initial learning method | Execution-verified SFT using LoRA/QLoRA. Add DPO or online RL only when the evidence supports it. |
| First domain | Small, mechanically checkable programming and ML-code repair tasks. |
| First milestone | One reproducible learning cycle with a fair comparison against the original model. |

The user's phrase “OpenAI BMB” is interpreted here as **OpenBMB**, a separate organization. This project does not currently require an OpenAI API key.

## Read next

1. [Project plan](docs/PROJECT_PLAN.md): research objective, experiment design, compute split, milestones, and open decisions.
2. [Environment setup](docs/SETUP.md): credentials, SSD-local paths, remote storage, and provider notes.
3. [Environment template](.env.example): blank credential fields and proposed configuration.
4. [Agent instructions](AGENTS.md): rules and handoff expectations for future agents.

The environment template is consumed by `scripts/check_services.py`; the training/controller launcher is not implemented. Copy it to an ignored `.env` when configuring accounts; see the setup guide. Nothing in this repository currently provisions infrastructure or spends credits.

Service check results and rerun instructions: [verification report](docs/VERIFICATION.md).
