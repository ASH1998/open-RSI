# Open RSI

A small-model research project investigating whether a model can learn from verified execution experience and eventually improve how it produces its successors.

**Status:** evaluator v2 rescored all 368 saved MBPP outcomes and corrected four codec false negatives. Development scores are parent **18/48**, adapter seed 42 **17/48**, and seed 43 **16/48**; the original parent is retained. The separate Kaggle baseline is **9/32**. No new generation or training was performed. The local `rsilab 0.1.1` framework and 199 integrated tests are verified. No sustained self-improvement has been demonstrated. Updated November 4, 2026.

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

The environment template is consumed by `scripts/check_services.py` and `rsi/pilot.py`. Copy it to an ignored `.env` when configuring accounts; see the setup guide. The pilot commands provision bounded Modal jobs under the authorized $250 project budget.

Service check results and rerun instructions: [verification report](docs/VERIFICATION.md).

Pilot commands and budget behavior: [pilot guide](docs/PILOT.md). Parallel chat assignments: [work log](docs/WORK_LOG.md).

Measured results and W&B evidence: [experiment record](docs/EXPERIMENTS.md). Proposed next experiment: [evaluation redesign](docs/NEXT_EVALUATION.md).

Current study: [MBPP protocol](studies/mbpp_v1/README.md). Python framework: [installation and API](docs/FRAMEWORK.md). Dataset source/filtering: [MBPP preparation](docs/DATASETS.md).

Original study, training results and checkpoints: [MBPP experiment record](docs/MBPP_EXPERIMENT.md).

Evaluator correction and current scores: [v2 rescore report](docs/MBPP_RESCORE_V2.md). Detailed causes: [failure analysis](docs/MBPP_FAILURE_ANALYSIS.md).
