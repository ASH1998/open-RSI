# Project plan

Last updated: November 4, 2026. This is a proposed research protocol, not a record of completed experiments.

## Objective and scope

The user's long-term objective is a small model that improves through its own experience. The first research question is whether a 2B-class model can improve on unseen programming tasks through execution-verified self-training. A later question is whether the learned model makes better decisions about future training or produces better successor agents.

Start with a narrow domain: reference-checked function implementations, tensor-shape repairs, and small training-loop bugs. Autonomous repeated fine-tuning is an initial mechanism; sustained recursive improvement remains an empirical question.

## Model candidate

The current preference is OpenBMB. Use `openbmb/MiniCPM5-2B` as a provisional candidate, not an immutable choice. Its official card identifies a text-only causal model with standard `LlamaForCausalLM` architecture, Apache-2.0 licensing, 2,516,756,480 total parameters, and 1,981,982,720 non-embedding parameters. Thus “2B” describes its size class rather than exactly two billion total parameters. [Official model card](https://huggingface.co/openbmb/MiniCPM5-2B)

Before downloading large assets or training, resolve an immutable Hub revision, validate tokenizer/chat-template behavior, inspect the current loading/fine-tuning recipe, and run a small capability test. Pin compatible dependencies after a smoke test. Begin with short task contexts; advertised maximum context is not a pilot training target. Use a trainable checkpoint, not an inference-only GGUF/GPTQ export.

## Learning cycle

1. Freeze a parent model, task split, evaluator version, and inference budget.
2. Generate attempts and allow bounded repairs using actual execution feedback.
3. Independently verify results in isolated execution environments.
4. Store a complete experience ledger; select diverse verified solutions and repairs for training.
5. Train a candidate LoRA/QLoRA adapter with SFT and replay of earlier useful data.
6. Compare candidate and parent on development tasks and earlier-skill checks under matching budgets.
7. Promote only when predetermined acceptance criteria are met; otherwise retain the parent.
8. Repeat only after inspecting data quality, cost, and failure modes.

The first comparison should hold the harness fixed. A later control can give both models the same experience through retrieval to distinguish weight learning from memory access. Fresh-adapter training on cumulative data versus continued-adapter training with replay is an open design choice; do not silently mix them across generations.

Training inputs may include failed attempts and error feedback, but target outputs should be verified corrective actions. Keep development feedback available to the controller and reserve final evaluation for a frozen comparison; do not repeatedly tune against final-test results.

## Compute and storage architecture

| Component | Primary location | Secondary use |
| --- | --- | --- |
| Controller and generation scheduling | Modal Functions | Local development/debugging |
| Model inference and batch generation | Modal GPU Functions | Small Kaggle batches |
| Execution of generated programs | Modal Sandboxes | No requirement to run these in Kaggle |
| SFT/QLoRA training | Modal GPU Functions | Small Kaggle GPU trials that fit quota/runtime |
| Evaluation | Modal GPU/CPU jobs and isolated execution | Independent Kaggle benchmark runs |
| TPU experiments | No dependency in the initial pipeline | Optional Kaggle, using a separately validated stack |
| Metrics and lineage | W&B / CoreWeave Forge | Same project across both compute providers |
| Large persistent artifacts | Modal Volumes initially | Explicit exports for Kaggle and SSD backups |

Modal is the main provider by explicit user preference. Kaggle is opportunistic secondary capacity; jobs must be independently runnable and the main loop must remain functional without Kaggle. No dedicated server or CoreWeave GPU account is currently required.

GPU Sandboxes support GPUs with the `gvisor` runtime and can be preempted. Sandbox lifetimes are limited to 24 hours, so long work needs checkpoints and restarts. Use persistent volumes rather than relying on a worker's temporary disk. CPU/RAM Sandbox prices differ from regular Functions. [Modal resources](https://modal.com/docs/guide/sandbox-resources), [Sandbox lifecycle](https://modal.com/docs/guide/sandboxes), [Volumes](https://modal.com/docs/guide/volumes)

Kaggle documents P100 and dual-T4 GPU configurations, 12-hour CPU/GPU sessions, 9-hour TPU sessions, and 20 GB of saved working output. Its GPU guidance describes a weekly quota around 30 hours, sometimes higher; actual account quotas and accelerator availability must be checked at run time. Two GPUs do not automatically pool memory. CUDA-specific training settings cannot simply be reused on a TPU. [Notebook resources](https://www.kaggle.com/docs/notebooks), [GPU usage](https://www.kaggle.com/docs/efficient-gpu-usage)

Modal Volumes are not automatically mounted on Kaggle. Export versioned inputs and fetch results explicitly. Every remote job should consume a manifest and produce metrics, artifact checksums, a completion status, and resumable checkpoints when relevant. Transfers must be accounted for in the job budget.

## Tracking and measurement

Use the existing W&B project `ashu-na/rsi` with separate runs for generation, verification, training, and evaluation. Link inputs and outputs through Artifacts. W&B remains usable across cloud providers after its transition into CoreWeave Forge. [CoreWeave explanation](https://www.coreweave.com/companies/weights-and-biases), [W&B Artifacts](https://site.wandb.ai/artifacts/)

Record at least:

- Experiment ID, generation, parent/candidate IDs, exact base-model and tokenizer revisions.
- Code revision, dependency lock/image version, dataset and split hashes, verifier version.
- Training objective, adapter configuration, replay mixture, seeds, precision, sequence limits.
- Task success rate, per-family results, retained-skill results, invalid outputs, and execution failures.
- Generated tokens, attempt limits, GPU model/hours, wall time, estimated cost, and provider.
- Promotion decision, rationale, and artifact locations/checksums.

Keep learning curves separate from held-out capability scores. Hardware differences make direct wall-time comparisons misleading; use common hardware when making efficiency claims. Limit model-visible feedback to the intended development information.

Store full weights and bulky training state in persistent storage. W&B can track lightweight metadata and selected adapters; its published personal plan currently has a 5 GB storage allowance. Check the actual plan before uploading checkpoints. [W&B pricing](https://site.wandb.ai/pricing/)

## Pilot resources and milestones

Earlier discussion estimated a 24 GB GPU, roughly 32 GB host RAM, and 100 GB disk as a comfortable starting target for a small QLoRA pilot. These are planning targets, not measured requirements for MiniCPM5. Start with a short memory/throughput benchmark; select hardware based on total job cost.

The user authorized **$250 total Modal spending for the whole project** on November 4, 2026. An extension requires a separate decision. Provider authentication is verified; account credit balances have not been inspected. The initial controller reserves at most $5 per stage, with $25 held aside for overhead. Reservations persist after failures and are not released based on runtime estimates. See `config/budget.json` and `budget/ledger.json`. The earlier engineering timeline remains an estimate, not a delivery commitment.

1. **Setup:** project-local environment, credentials, immutable model revision, provider smoke tests, and one W&B run.
2. **Baseline:** independently checked task families, frozen splits, starting-model scores and failure inspection.
3. **First dataset:** a small audited collection of verified solutions/repairs with provenance; quantity follows useful yield.
4. **First update:** one adapter, equal-budget parent comparison, regression checks, cost report.
5. **Replication:** repeated runs/seeds and a few generations only if the first update is useful.
6. **Stronger recursion test:** compare the original and learned improvers on identical starting agents, history, permitted changes, and improvement budgets; evaluate resulting agents on fresh tasks.

## Open decisions

Exact checkpoint/revision; task sources and licenses; acceptance thresholds and required replication; adapter continuation strategy; GPU sizing; billing reconciliation; and whether Kaggle TPU work has enough value to justify a separate implementation.

The first compatibility cycle has completed: training-family results rose from 4/16 to 6/16, while development results fell from 7/8 to 5/8. The parent was retained. See [measured experiment record](EXPERIMENTS.md) and [proposed next evaluation](NEXT_EVALUATION.md). No general improvement or sustained RSI has been demonstrated.
