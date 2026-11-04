# Open RSI

A small-model research project investigating whether a model can learn from verified execution experience and eventually improve how it produces its successors.

**Status:** completed the matched successor teacher probe with `rsilab 0.4.2`. Original teacher: **10/20** unique verified targets; learned teacher: **9/20**. Both failed the data gate, so no children were trained and the original parent remains selected. No sustained RSI has been demonstrated. The Apache-2.0 library now includes reference-evidence reuse, category preflight and a remotely validated portable Modal inference path. See the [completed report](docs/SUCCESSOR_RECOVERY_EXPERIMENT.md), [failure analysis](docs/SUCCESSOR_RECOVERY_FAILURE_ANALYSIS.md) and [public quickstart](docs/QUICKSTART.md).

## Workspace and repository

- Canonical local workspace: `/Volumes/DevSSDWD/openbmb/rsi`
- GitHub repository: https://github.com/ASH1998/open-RSI
- Keep all project files, local dependencies, caches, downloads, checkpoints, and scratch work within this SSD directory. Remote workloads use their provider's storage; local copies belong here.
- Git backs up source and documentation. Large datasets, model weights, and secrets stay out of Git.

## Current direction

| Area | Decision |
| --- | --- |
| Model | Prefer an OpenBMB 2B-class text model. `openbmb/MiniCPM5-2B` is pinned to a verified trainable revision; see the experiment report. |
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

The environment template is consumed by `scripts/check_services.py` and `rsi/pilot.py`. Copy it to an ignored `.env` when configuring accounts; see the setup guide. The pilot commands provision bounded Modal jobs under the authorized $250 project budget.

Service check results and rerun instructions: [verification report](docs/VERIFICATION.md).

Pilot commands and budget behavior: [pilot guide](docs/PILOT.md). Parallel chat assignments: [work log](docs/WORK_LOG.md).

Measured results and W&B evidence: [experiment record](docs/EXPERIMENTS.md). Proposed next experiment: [evaluation redesign](docs/NEXT_EVALUATION.md).

Original study: [MBPP protocol](studies/mbpp_v1/README.md). Python framework: [installation and API](docs/FRAMEWORK.md). Dataset source/filtering: [MBPP preparation](docs/DATASETS.md).

Original study, training results and checkpoints: [MBPP experiment record](docs/MBPP_EXPERIMENT.md).

Historical evaluator correction and scores: [v2 rescore report](docs/MBPP_RESCORE_V2.md). Detailed causes: [failure analysis](docs/MBPP_FAILURE_ANALYSIS.md).

Earlier engineering milestone: [stronger diagnostics and durable execution](docs/MBPP_ROBUSTNESS.md).

Completed verified-data experiment: [verified-data SFT protocol](studies/verified_sft_v1/README.md). Reusable workflow: [learning API](docs/LEARNING.md), [dataset audit](docs/VERIFIED_DATA.md), and [project runtime](docs/PROJECT_RUNTIME.md).

Latest measured result and handoff: [successor recovery](docs/SUCCESSOR_RECOVERY_EXPERIMENT.md). Current reservations: $194 plus $25 overhead; $31 unallocated. Reservations are not invoices.

Completed successor probe: [recovery protocol](studies/successor_recovery_v3/README.md), [measurement contract](docs/SUCCESSOR_MEASUREMENT.md), and [portable Modal workers](docs/PORTABLE_MODAL.md).
