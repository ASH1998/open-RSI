# Verified-data SFT v1: completed experiment

Completed November 4, 2026. The fresh adapter improved development from **11/32 to 13/32**, but retention fell from **8/16 to 7/16**. It fails both requirements for replication: at least three net development successes and zero individual retention losses. **Retain the original parent.** Seed 43 was not launched. No promotion or sustained RSI claim follows.

| Evaluation | Parent | Seed-42 adapter | Paired change |
| --- | --- | --- | --- |
| Development | 11/32 (34.375%) | 13/32 (40.625%) | 2 gains, 0 losses |
| Retention | 8/16 (50%) | 7/16 (43.75%) | 0 gains, 1 loss |

Development gains are tasks 524 and 577; retention loss is task 854. Independent saved-output review found: task 524 fixes double-counting in maximum-sum increasing subsequences (4/15 to 15/15 cases); task 577 fixes factorial last-digit behavior (9/11 to 11/11); task 854 incorrectly returns `heapq.heapify(...)`'s `None` instead of the mutated list (3/3 to 0/3). Original-only development scoring is 12/32 to 13/32, so the added tests materially affect this comparison. Candidate task 547 is truncated and correctly fails. These are new protocol scores, not a replacement for the historical 48-task scores (18/48, 17/48, 16/48).

## Data and test provenance

The pre-generation protocol is `studies/verified_sft_v1/protocol.json`, frozen in Git commit `f96b35a`. It pins MiniCPM5-2B revision `f97400052a43d642bbc6e9975e2397e3ae6a6b52`, MBPP revision `4bb6404fdc6cacfda99d4ac4205087b89d32030c`, evaluator v2, sources, policies and independent domain review.

All 154 reviewed reference solutions passed their original tests. All 1,441 approved probe calls matched reviewed mutation IDs. Unsupported/type-changing outputs excluded tasks 814, 957 and 931; a deterministic, reference-only fallback selected the final dataset before model generation.

| Split | Tasks | Original cases | Added cases | Total cases |
| --- | --- | --- | --- | --- |
| Training | 96 | 288 | 884 | 1,172 |
| Development | 32 | 96 | 300 | 396 |

Every selected task has at least three distinct accepted additions. Original tests are preserved. Reference code supplies expectations, never SFT targets. Domain review and calibration reduce test errors but do not prove reference correctness.

Training includes 41 previously used training tasks and 55 new ones. Development includes 23 previously exposed tasks and 9 unexposed tasks. Sixteen unchanged earlier training tasks form the separate retention set; none enters current training. Native splits and known duplicate clusters remain separated. Categories overlap across native splits, so this is not family-held-out evaluation. The native 500-task final split was not used for training, generation, scoring or selection. Correction recorded in the next phase: the legacy `load_mbpp()` function decoded all native splits before the preparation caller filtered to train/validation. Thus the earlier claim that no final-test prompts were decoded was incorrect. Final-test rows were not included in model requests or evaluations; new loaders must read permitted splits explicitly. Pretraining contamination has not been measured.

## Collection and training

| Attempt | Tasks attempted | Verified | New solved tasks |
| --- | --- | --- | --- |
| Initial greedy | 96 | 40 | 40 |
| Independent sample | 96 | 39 | 6 |
| One bounded repair | 32 | 1 | 1 |

All 224 raw attempts are preserved. Repairs target exactly the first 32 of 50 double failures in frozen training order. Sample settings are seed 31415 and temperature 0.7; repairs use seed 31416 and temperature 0. Each answer has at most 512 generated tokens. Feedback is bounded and excludes authoritative tests, expected values and reference code.

Target selection keeps the earliest verified answer per task, deduplicates exact code, and yields 47 unique targets: collections 14, numeric 13, other 3, text 17. The 24-target/three-category/60%-share gate passes. The sole repair success, task 974, removes a prohibited `sys` import while preserving the sampled function implementation. It demonstrates policy compliance, not algorithmic repair.

Initial failures comprise 44 wrong-output-only, 8 runtime-only, 2 mixed and 2 truncated answers. Truncated answers are not executed. Original-only scoring would pass 41/96; stronger tests reject task 768's confusion between numeric oddness and odd bit parity. Original tests remain necessary: tasks 764, 677 and 868 pass their added portion but fail originals. Independent review found no collection infrastructure failures.

A fresh seed-42 QLoRA adapter trained on the 47 targets, containing 2,743 supervised tokens per pass without truncation. It completed all 24 planned optimizer steps, with learning rate 2e-5, accumulation 4 and sequence limit 2048. Training took 61.12 seconds on L40S and peak allocated memory was 4,119,968,768 bytes. These are worker measurements, not total stage time or provider charges.

Parent and candidate evaluation use identical task order, effective per-task seeds, greedy generation, 512-token output limit, 2,048-token input limit, disabled thinking, model revision, L40S hardware, package inventory and evaluator sources. Actual candidate adapter identity matches the trained/exported adapter. The paired comparison passes all matching checks.

## Library integration and reproducibility

Reusable implementation is in `rsilab` 0.2.0:

- `coding_data`: reviewed probes, reference audit and deterministic data freezing.
- `learning`: immutable attempt ledger, bounded repair prompts, verified target selection and paired replication gates.
- `workflow` and `execution`: durable generation/verification records and preservation of failures.
- `providers.modal`: injected bounded generation/training calls with persisted call IDs and cancellation on failure.
- `project`: explicit workspace paths/environment, atomic reports, persistent budget reservations and allowlisted tracking.
- Offline CLI: `coding-data-freeze`, `learning-select`, and `learning-compare`.

`rsi.verified_study` connects these APIs for this experiment. The historical GPU worker still needs this checkout, its configuration and pinned requirements; the installed core does not provide a turnkey cloud service. Provider dependencies are optional and nothing launches at import time.

Validation: 293 integrated tests before launch; 56 isolated installed-package tests; five CLI help checks. Installed-package selection and comparison replay exactly match saved results with networking blocked and checkout imports excluded. Previous frozen studies and wheels remain unchanged. The local wheel is `work/verified-framework-dist/rsilab-0.2.0-py3-none-any.whl`; no PyPI publication or project license selection occurred.

To recompute the study report offline from this SSD checkout:

```sh
.venv/bin/python -m rsi.verified_study report
.venv/bin/python -I -B work/verified-framework-dist/replay_cli.py selection --workspace "$PWD"
.venv/bin/python -I -B work/verified-framework-dist/replay_cli.py comparison --seed 42 --workspace "$PWD"
```

Do not rerun completed paid stages. Raw data and scratch replay helpers are ignored; reusable CLI contracts are documented in `LEARNING.md`, `VERIFIED_DATA.md` and `PROJECT_RUNTIME.md`.

## Artifacts, budget and handoff

The adapter and full training-state checkpoint are persisted on Modal Volume `open-rsi-artifacts` and exported to SSD under `artifacts/verified-sft-v1/20261104T143454Z-verified-sft-v1-train-evaluate-42-73116f4e/`. Export hashes match the completion manifest. The checkpoint includes optimizer and RNG state; training uses a constant learning rate without a scheduler, and an interruption/resume trial was not run for this adapter. The original parent remains available unchanged.

All three W&B run reports were read back and matched their local reports plus the recorded local-report digest. The final summary artifact also matches its protocol, domain review and wheel audit; stage input lineage is preserved. All three Modal apps are stopped with zero tasks.

This experiment used three $5 reservations ($15), below its $20 envelope. Cumulative project reservations are **$170 plus $25 overhead, leaving $55 unallocated** under the $250 cap. The November 4 14:41 UTC billing snapshot reports workspace metered usage $2.22055157 and billed usage $0 after credits. That snapshot may lag, includes other activity and is not a project invoice; the app-filtered report returned no entries. No reservations were released. See `studies/verified_sft_v1/budget-reconciliation.json`.

The next executable research milestone is a separately frozen protocol addressing the weak repair yield and retention regression—potentially a replay mixture and more informative bounded training feedback—followed by another matched comparison. These are proposals, not authorized follow-on launches. Preserve this result, the parent, and the untouched final set.

W&B evidence: [verified-sft-v1-collect](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/gip7pzc8), [verified-sft-v1-improve-data](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/5ozagjsk), [verified-sft-v1-train-evaluate-42](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/cl4f2yfw). Compact tracked evidence: `studies/verified_sft_v1/results.json`.
