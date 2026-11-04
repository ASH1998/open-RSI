# MBPP v1: verified self-training experiment

November 4, 2026. This is a filtered-subset engineering experiment, not the standard MBPP leaderboard or a demonstration of recursive self-improvement. The protocol was committed locally as `cb2babe3149808956cd160f62421a31fb2f1a57f` before generation. Both matched evaluations completed; the original parent is retained.

## Data and fixed comparison

Source: [Google Research MBPP](https://huggingface.co/datasets/google-research-datasets/mbpp/blob/4bb6404fdc6cacfda99d4ac4205087b89d32030c/README.md), full configuration, revision `4bb6404fdc6cacfda99d4ac4205087b89d32030c`, CC BY 4.0. Attribution: Google Research and Austin et al., *Program Synthesis with Large Language Models* (2021). Filtering, prompt construction and typed-test conversion are project modifications. See [dataset preparation](DATASETS.md) for exclusions and license details.

The importer preserved source train/validation splits, quarantined detected cross-split duplicate clusters, deduplicated within splits, and excluded unsupported tasks. Reference code was independently checked in isolated Modal sandboxes before subset selection. Of 334 convertible tasks, 258 train and 64 development references passed; 11 failed the code policy and one failed execution. Manual review then removed two additional cross-split near-duplicate pairs. The frozen subset contains **128 training and 48 development tasks**, with the first 32 training tasks designated for retention checks. No test/prompt-split tasks were executed, evaluated or used as labels; those splits were read statically for duplicate screening.

Frozen manifest SHA256: `cde70ffcd2bc5e243587a0c32f4f084457ac446a67c00adbd3522303ec3029ca`. The tracked [protocol](../studies/mbpp_v1/protocol.json) and [manifest summary](../studies/mbpp_v1/frozen-manifest-summary.json) preserve settings and task IDs. Full inputs, outputs and source checksums remain on the SSD and in explicit W&B report artifacts.

Model: `openbmb/MiniCPM5-2B`, revision `f97400052a43d642bbc6e9975e2397e3ae6a6b52`. All main comparison arms use actual NVIDIA L40S hardware, the same NF4 double-quantized bfloat16 model stack, greedy generation, one attempt per task, 512 new tokens, 2,048 input-token limit, thinking disabled and seed 42. Invalid or truncated outputs count as failures. Infrastructure failures make a batch incomplete rather than a model failure.

## Parent baseline and training yield

| Split | Passed | Rate |
| --- | ---: | ---: |
| Training pool | 46/128 | 35.94% |
| Development | 17/48 | 35.42% |
| Training-retention subset | 13/32 | 40.63% |

There were three token-limited parent outputs and no recorded time-limit or infrastructure failures. The 46 passing training completions were all unique: collections 25, text 11, numeric 9, other 1. The largest category accounts for 54.35%, passing the predeclared minimum of 32 unique targets across at least three descriptive categories, none exceeding 60%. These broad heuristic categories are not independent algorithm families.

Only these parent-generated verified training solutions became labels. Reference answers and development outputs were excluded. Both fresh rank-8 QLoRA adapters used exactly those 46 examples (2,725 supervised tokens before repetition), learning rate 0.00002, accumulation 4, sequence limit 2,048 and **23 optimizer steps**: two passes through the 46 examples. Seeds 42 and 43 vary initialization and example order. This is one generated dataset with two training seeds, not two independent dataset replications.

| Seed | Training run | Initial / final logged batch loss |
| --- | --- | --- |
| 42 | [W&B](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/lu2qadgf) — `20261104T100258Z-mbpp-train-8445eb` | 0.5121 / 0.0199 |
| 43 | [W&B](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/5idh5xdx) — `20261104T100258Z-mbpp-train-ff538c` | 0.5718 / 0.0358 |

The loss points cover different minibatches and are not held-out capability scores. Both runs completed all requested steps and persisted adapters plus optimizer/RNG state. SSD exports under `artifacts/mbpp/<training-run>/` passed all checkpoint payload checksums. Training-resume equivalence is still untested. The adapter SHA256 values are `60949b960ba2c0241624000dcd9962c23fafc37416979cd57bc9cf2666eea286` (42) and `9e812ba9c821a47f9a82372adc5aabfec4f68a338744ddef7920eec12a0573c8` (43).

## Separate Kaggle baseline

The private [Kaggle kernel](https://www.kaggle.com/code/ashutoshmishra1998/open-rsi-mbpp-baseline-v1) completed 32 frozen development prompts. It requested NvidiaL4 but actually ran on **Tesla T4**, recording bfloat16 and PyTorch 2.11.0+cu130; the Modal arm used L40S, PyTorch 2.8.0 and CUDA 12.8. Prompts, pinned model revision and task IDs match. Hardware/package differences prevent a controlled provider or speed comparison.

Kaggle passed **8/32 (25%)**, versus Modal's **9/32 (28.13%)** on those same tasks: eight shared passes, 23 shared failures and one Modal-only pass. Kaggle's output for `mbpp-full-543` had a syntax error. Kaggle produced 2,321 output tokens with no token/time-limit hits. Generated code was never executed in Kaggle; the same trusted Modal verifier scored the downloaded outputs. [W&B verification evidence](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/wxbuhutu).

## Integrity and interpretation limits

- Public MBPP may occur in model pretraining; split separation does not establish absence of contamination.
- Native train/validation splits share algorithm categories. Deduplication and manual review reduce detected overlap but cannot prove semantic independence or family-held-out generalization.
- Source tests are sparse. Passing them does not establish correctness for all inputs.
- The frozen typed codec supports builtin containers and rejects subclasses. For example, empty `OrderedDict` results on `mbpp-full-568` are rejected even though ordinary Python equality would accept them against empty dictionaries. Scores preserve this restriction consistently; changing it requires a new evaluator version and re-evaluation of all arms.
- Retention uses training tasks, including tasks eligible for labels. It measures retention on this pool, not unseen-task generalization.
- Two seeds and one dataset cannot establish sustained improvement or improved successor-building ability.
- A controller interruption during parent batch 0 was recovered from the original completed Modal call. Verification resumed under the existing reservation and W&B run; no GPU output was regenerated.

## Framework and reproduction

The installable `rsilab` package provides immutable tasks/agents/manifests, canonical hashes, exact matched-control checks, paired outcomes and retain-parent decisions. Provider orchestration remains in the checkout's `rsi` modules; more of the user's v0.2 architecture remains future work. See [framework guide](FRAMEWORK.md).

After complete artifacts are present, `.venv/bin/python scripts/report_mbpp.py` validates both seeds and produces comparison/manifests plus checksummed JSON under `artifacts/mbpp/reports`. It refuses missing, ambiguous, mismatched or unfinished evidence. The integrated suite passed **145 tests**, including the cached real model tokenizer. Generated programs were checked in isolated, credential-free, network-blocked Modal sandboxes, never by local execution.

## Matched results and decision

| Measure | Original parent | Adapter seed 42 | Adapter seed 43 |
| --- | ---: | ---: | ---: |
| Development tasks | 17/48 (35.42%) | 16/48 (33.33%) | 15/48 (31.25%) |
| Development wins / losses versus parent | — | 3 / 4 | 2 / 4 |
| Training-retention tasks | 13/32 (40.63%) | 12/32 (37.50%) | 12/32 (37.50%) |
| Retention wins / losses versus parent | — | 0 / 1 | 0 / 1 |
| Candidate token-limited outputs across 80 evaluated tasks | — | 1 | 0 |

The strict framework comparison accepted both arms as matched: all frozen tasks, effective per-task seeds, source inventory, model revision, decoding settings, actual L40S hardware, CUDA and package inventories agree. Saved typed outputs were rescored independently during aggregation. There are no unresolved integrity mismatches.

**Decision: retain the original parent; neither adapter is promoted or marked replication-worthy.** Both seeds miss the prospectively required gain of at least four net development successes. They each lose one parent retention success, within that separate tolerance, but the development gate fails. Lower training loss did not translate into development improvement. The observed regressions are small and this study does not establish a population-level degradation or improvement claim.

The complete machine-readable summary, both comparisons, parent/candidate manifests and inventory hashes are in `artifacts/mbpp/reports/`. Raw failures and successes remain in each original run report. Both adapters and their resumable states remain available for inspection or rollback.

## Budget, completion and next milestone

This MBPP study reserved **$80** across 16 stages: one reference audit, six parent baseline batches, one Kaggle verification, two training seeds and six adapter evaluation batches. Recovering baseline batch 0 reused its original reservation and model output. Including the earlier pilot, the ledger conservatively reserves **$125** for jobs and **$25** for overhead, leaving **$100** unallocated under the unchanged **$250** project cap.

A read-only provider billing snapshot at **2026-11-04 10:14:56 UTC (15:44:56 IST)** reported **$1.50054595 workspace month-to-date metered usage**, with **$0 billed after credits**. This is a lagging workspace observation, not a finalized project invoice. The app-filtered billing report had no rows, so per-app reconciliation remains unavailable; it does not imply zero usage. No reservation was refunded. The filtered observation is tracked in `budget/reconciliation-2026-11-04.json`; raw readback stays in SSD artifacts. Persistent storage and later meter updates must be included in future reconciliation.

All project Modal apps were confirmed stopped with zero tasks. The private Kaggle run completed. No final-test evaluation, additional model generation, hyperparameter sweep, automatic promotion or release publication followed.

Next executable milestone: inspect the preserved paired failures offline, add verifier compatibility cases for container subclasses under a new evaluator version, and design a new frozen protocol before spending on another training run. A future alternative could test repair trajectories or more diverse verified labels; neither is authorized as an automatic loop by these results. The Python framework remains an initial installable foundation for that work, not a completed Level-2 RSI system.
