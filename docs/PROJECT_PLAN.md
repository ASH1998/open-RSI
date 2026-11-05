# Project plan

Last updated: November 5, 2026. This document separates the longer-term research plan from the implemented MBPP study below.

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

The user authorized **$250 total Modal spending for the whole project** on November 4, 2026. An extension requires a separate decision. Provider authentication is verified. A November 4 billing snapshot reported $1.50054595 workspace metered usage, covered by credits; this is not a finalized project invoice. The initial controller reserves at most $5 per stage, with $25 held aside for overhead. Reservations persist after failures and are not released based on runtime estimates. See `config/budget.json` and `budget/ledger.json`. The earlier engineering timeline remains an estimate, not a delivery commitment.

1. **Setup:** project-local environment, credentials, immutable model revision, provider smoke tests, and one W&B run.
2. **Baseline:** independently checked task families, frozen splits, starting-model scores and failure inspection.
3. **First dataset:** a small audited collection of verified solutions/repairs with provenance; quantity follows useful yield.
4. **First update:** one adapter, equal-budget parent comparison, regression checks, cost report.
5. **Replication:** repeated runs/seeds and a few generations only if the first update is useful.
6. **Stronger recursion test:** compare the original and learned improvers on identical starting agents, history, permitted changes, and improvement budgets; evaluate resulting agents on fresh tasks.

## Open decisions

The MBPP v1 checkpoint, dataset, licenses, hardware and engineering thresholds are frozen. Future-study choices remain open: stronger evaluation/data, adapter continuation, finalized billing reconciliation, and whether Kaggle TPU work warrants a separate backend.

The first compatibility cycle has completed: training-family results rose from 4/16 to 6/16, while development results fell from 7/8 to 5/8. The parent was retained. See [measured experiment record](EXPERIMENTS.md) and [proposed next evaluation](NEXT_EVALUATION.md). No general improvement or sustained RSI has been demonstrated.

## Implemented MBPP v1 study

The frozen implementation is `studies/mbpp_v1/protocol.json`, committed before generation. It uses pinned MiniCPM5-2B, 128 audited MBPP training tasks and 48 development tasks on L40S, with native train/validation splits, duplicate exclusions and no final-test execution. A separate 32-task Kaggle baseline completed on Tesla T4. Main uses the controller in `rsi/study.py`; all stages reserve budget atomically, with a $100 study envelope inside the $250 project cap. Two training seeds (42, 43) use only unique verified parent training outputs, subject to the documented diversity gate.

The initial `rsilab` Python package provides immutable task/agent/provenance manifests, matching checks, paired score reports, checksummed artifact inventories and a retain-parent default. It is an offline foundation; provider integration still uses the checkout's legacy `rsi` controller. The user's v0.2 proposal is preserved in `docs/design/`, but its larger budget, different model and later recursion/RL mechanisms are proposals. At that historical milestone, packaging was local and no license had been chosen. The current library uses Apache-2.0; no PyPI release has been published.

The completed MBPP comparison scored parent 17/48 development versus adapters 16/48 and 15/48. Both seeds passed exact control matching but failed the predeclared development gain threshold; the original parent is retained. See `docs/MBPP_EXPERIMENT.md`. No automatic further experiment follows this result.

## Completed evaluator correction

The user authorized failure analysis and versioned evaluator repair before more training. V2 rechecked all 368 existing MBPP outcomes after 18 remote calibration checks and 176 reference passes. Four mapping-subclass false negatives were corrected. Current development scores are parent 18/48, seed 42 17/48, seed 43 16/48; the parent remains selected. Training-label eligibility is unchanged at 46 examples. No model generation or training followed. See `docs/MBPP_RESCORE_V2.md` and the compact tracked `studies/mbpp_rescore_v2/results.json`. The next research decision should address the documented logic failures and sparse tests in a newly frozen protocol; do not automatically launch further training from the corrected scores.

## Completed stronger diagnostics and durable execution

A new versioned controller uses `rsilab.execution` to persist failures before validation and drain already-started work. The separately frozen seven-task diagnostic added 43 assertions to 21 originals. All 64 reference cases passed, and all 23 saved-output checks completed. Parent task 558 and 576 solutions fail added cases while passing originals; no adapter promotion follows. The previous 368-outcome benchmark stays unchanged. Validation: 230 integrated tests, 15 isolated package execution tests, and remote artifact readback. Package version is locally 0.1.2. See `docs/MBPP_ROBUSTNESS.md`. No new model generation or training occurred. Current reservations are $155 plus $25 overhead, leaving $70 unallocated. The next research milestone is a prospective stronger-data protocol with untouched final evaluation; this post-hoc subset is not training data or held-out evidence.

## Completed verified-data SFT v1

The verified-data experiment was authorized for at most $20 across four $5 stages, within the existing $250 project cap. Its frozen protocol is `studies/verified_sft_v1/protocol.json`. Independent domain review and remote reference calibration produced 96 training and 32 development tasks with 1,568 cases. Sixteen earlier training tasks form a separate retention set. Twenty-three development tasks have prior exposure; this is a development comparison, not fresh held-out evidence. The native 500-task final split remains untouched.

Collection produced two independent attempts per training task, then one bounded repair for 32 tasks failing both attempts. The 47 unique verified targets passed the gate of at least 24 targets, three categories and no category above 60%. A fresh seed-42 QLoRA adapter received matched evaluation. Seed-43 replication required at least three net development successes gained and no individual retention success lost. No automatic promotion was permitted.

The reusable implementation is in `rsilab` 0.2.0: audited data freezing, immutable attempt ledger, repair prompts, target selection, matched comparison, durable collection, injected Modal backend, explicit workspace tracking and budget lifecycle. The specific cloud worker still uses this checkout and pinned GPU requirements. Validation before launch: 293 integrated tests; the installed wheel passed 56 isolated tests and five CLI help checks. The completed candidate scores 13/32 development versus parent 11/32, but 7/16 retention versus 8/16. It fails the frozen replication gate, so seed 43 was not launched and the parent remains selected. All 224 attempts and 47 verified targets are preserved, full training state is exported and hashes checked, and installed offline CLI replay matches exactly. The experiment reserved $15; cumulative reservations are $170 plus $25 overhead, leaving $55 unallocated. See `docs/VERIFIED_SFT_EXPERIMENT.md`. Proposed follow-up is a new retention/repair-data protocol; no automatic training follows.

## Successor-improvement probe and library 0.3.0

The next milestone directly tests teaching as a successor-improvement operator: original versus experimental learned teacher, identical fresh training tasks and generation budgets, identical starting student and fixed training steps. Teacher label yield is a separate endpoint from child performance. A single positive pair would remain preliminary development evidence; sustained RSI needs produced successors serving as improvers in later generations, matched controls, fresh evaluation blocks and replication. No outcome is guaranteed.

Manual review supports 24 never-generated native training tasks, from which the first 20 reference-eligible tasks will be selected in a frozen order. Both teachers get two attempts without repairs. Each must yield at least 16 unique targets spanning three categories, with no category over 60%. Otherwise stop after the paired feasibility probe. Conditional children start fresh from the same original base, each with 16 optimizer steps and the same seed. The learned teacher remains unpromoted. The existing 32 development/16 retention tasks are previously exposed. Final-test files are checksum-only in the new development path.

Main coordinates at most five $5 stages ($25 new reservations) within the unchanged $250 global cap and $25 overhead hold. The source/review/selection plan must be frozen before calibration; audited task and runtime manifests are frozen before teacher generation. No automatic retries or replication. The reusable successor audits, explicit split reader and portable Modal factory are included in 0.3.0. User selected Apache-2.0. Public quickstart and offline example are prepared; installed-wheel and remote validation remain to be recorded.

## Successor v1 outcome and current handoff

The calibration stage stopped at the category-diversity gate before any GPU call. All 24 original references passed and 261 approved additional cases were accepted, but nested task categories were all `text` and disagreed with the reviewed outer labels. There are no new model scores, teacher attempts or child checkpoints. Preserve the frozen failed study; do not retry it. The source remains Apache-2.0, the immutable 0.3.0 wheel passed 49 isolated tests, 342 unique integrated tests were verified, and public package CI passed. A reusable category preflight and explicit correction proposal are the offline follow-up. A new versioned protocol must establish any reference reuse before another paid launch. Reservations are $175 plus $25 overhead, leaving $50 unallocated. See [the experiment record](SUCCESSOR_EXPERIMENT.md).

## Authorized successor recovery v1

On November 5 the user authorized the corrected comparison. The new controller is `rsi.successor_recovery`; it preserves the failed study and reuses all 24 audited references through a separately versioned, tested library API. The same first 20 tasks, generation limits, 16-target/three-category gate, paired fresh students and acceptance thresholds remain. Main permits at most five new $5 stages ($25), with the prior failed $5 still counted globally. If the teacher gate fails, neither child trains. Current source preparation is for rsilab 0.4.0; exact new results and release validation will be recorded after execution. See `studies/successor_recovery_v1/README.md`.

Recovery baseline v1 failed at worker startup before any model outputs: image-build dependency caching populated the future volume mount. V2 changes only worker image-build order and preserves scientific controls. Five $4 stages use the remaining $20 of the same $25 recovery allocation; the failed $5 is retained and family reservations are checked across versions. The v2 plan is `a974ee728a7f9c220ea79d01393c1b57c82a4847567c09609e7ee5431932c7fa`. Library0.4.1 contains the corrected factory and regression tests; older factory/controllers/wheels remain preserved. See `studies/successor_recovery_v2/README.md`.

The v2 ENV layer also failed the mount check before model outputs. V3 removes image-level cache environment entirely and requires a CPU-only probe on the exact image/volume/source before GPU work. New allocation is $1 probe plus five $3 stages ($16); prior recovery failures retain $9, preserving the $25 family cap. Source plan `e04df37d5b23a30c4fb5f88821a5cd0ae6440fa070e893b49a65c7c7d7b80b26` is frozen. Tests:436 total with433 default passes and3 previously verified opt-in tokenizer checks. The CPU probe validates startup/source/package metadata, not CUDA or model loading. See `studies/successor_recovery_v3/README.md`.

## Completed successor recovery and current handoff

Original and learned teachers generated two matched attempts on the same 20 fresh training tasks. Unique verified yield is 10 versus 9, with zero text successes in either arm. Both fail the unchanged 16-target/three-category gate; no child training or promotion. Baseline exactly reproduces all 48 historical outputs and scores 11/32 development, 8/16 retention. This measures teacher-data feasibility, not successor performance or sustained RSI.

Library 0.4.2 includes reference-evidence reuse, preflight and a portable Modal factory with runtime-only cache setup and a CPU startup probe. Actual GPU inference and isolated verification completed; portable training/resume remain untested. Validation covers 436 unique integrated tests, 155 installed-wheel tests, hosted CI and exact installed offline report replay. Both startup failures remain preserved. All workers stopped; W&B report readbacks match. Recovery reservations total $19; cumulative jobs $194 plus $25 overhead, leaving $31. Billing remains non-final.

Next executable milestone is a new offline task-contract/boundary-coverage audit and preregistered diverse-data/repair design. Task 675 exposes a finite-test coverage gap; do not change the completed scores. Register these 20 tasks as exposed before selecting another fresh cohort. No automatic further training. See [completed report](SUCCESSOR_RECOVERY_EXPERIMENT.md).

## Task contract audit and next research step

All 20 exposed training tasks now have source-bound prompt reviews and private boundary checks. The public API derives and replays the task records, returns a generation-only projection and scores the new cases using their declared types. The 20 tasks join the previous 264 exposure records. Future fresh cohorts must exclude those 284 records, including variants with revised wording. See the [task diagnostic](../studies/task_contracts_v1/README.md).

The next research step is a separately preregistered comparison of independent sampling versus a bounded repair with verifier feedback on fresh, diverse training tasks. Specify the data source, split checks, text coverage, equal attempt/token budgets, reference calibration, and stop criteria before generation. Use the prior 20 only for diagnostics. Reserve compute only after the new protocol is frozen and passes its offline checks. Learning yield and actual successor performance remain separate outcomes.

## Authorized matched repair experiment

Main coordinates the experiment from this chat. The MBPP-only screen produced 19 fresh training tasks and two text tasks, below both entry thresholds. A prospective source amendment adds six independently reviewed native APPS training tasks and quarantines two overlaps. The selected study has 24 training tasks (seven text), nine held-back tasks (one text) and 16 historical retention tasks. Calibration passed all 234 cases for the selected 33 fresh tasks. Each teacher produces a shared greedy attempt and two matched second attempts. A child pair is conditional on both repair datasets passing all gates. Jobs are capped at $25 including both possible children, within the $250 project maximum. The selected parent is the original model. See [prospective study](../studies/repair_v1/README.md).

The matched repair study completed. Both teachers qualified for child training. Independent sampling yielded 17 unique targets each, versus 19 for original-teacher repair and 18 for learned-teacher repair. Both students passed the very same 4/9 fresh and 6/16 retention tasks, compared with the base's 3/9 and 8/16. The original parent remains selected. The next offline milestone is a retention-regression and label-quality diagnosis before proposing any replication. Project reservations are $219 for jobs and $25 overhead, leaving $6. [Experiment record](REPAIR_EXPERIMENT.md)
