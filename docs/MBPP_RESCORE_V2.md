# MBPP evaluator v2 correction

November 4, 2026. The user authorized failure analysis, evaluator repair and rescoring all saved models before further training. This is a post-hoc measurement correction, not a new learning experiment. Original v1 evidence remains unchanged in `artifacts/mbpp/reports/` and the original run reports.

## Scope and review

The static [failure analysis](MBPP_FAILURE_ANALYSIS.md) inspected all 368 saved outcomes and compared all 176 task-test records with the pinned MBPP source. It identified mapping-subclass transport false negatives: task 568's nested OrderedDict results for parent/Kaggle and task 512's Counter results for both adapters. It also explained the four shared development regressions and retention loss as candidate logic errors. Static findings are hypotheses until isolated execution confirms them.

V2 supports exactly `collections.OrderedDict`, `collections.defaultdict` and `collections.Counter`, including nesting. It preserves source equality, mapping iteration order where projected, ordinary builtin distinctions and strict size/depth/resource bounds. Factories and arbitrary instance state are not serialized, and user-defined subclasses remain unsupported. Tests and scoring remain outside credential-free, network-blocked Modal sandboxes. Diagnostic fields now distinguish candidate calls, encoding, decoding and comparison failures. Existing dictionary-view/iterator transport limitations remain documented; no additional observed false-negative cases were established for those types.

The original `rsi/mbpp_verification.py` and `rsi/verification.py` files are byte-identical to v1. The corrected implementation lives in `rsi/mbpp_verification_v2.py`; the original compiler, frozen task cases and extraction/code policy are reused. No imports or repairs are injected into candidates. Truncated outputs retain their original failed verification records exactly and are not executed.

Protocol SHA256: `8cf70679601b44c9a41efb712dbdd44ed6a4a34c4ca0d0d98a19ab489ed70e30`. The [frozen protocol](../studies/mbpp_rescore_v2/protocol.json) records source report hashes, reference-input hashes, evaluator and child-source hashes, controller/report-helper hashes, all arm counts and the $20 reservation envelope. Commit `27c8f92` preceded paid execution. Both the original MBPP experiment and correction protocol were successfully pushed to GitHub after the earlier outage.

## Execution and integrity gates

The controller is `.venv/bin/python -m rsi.rescore_study`. It has `freeze`, `run --arm <parent|seed-42|seed-43|kaggle>`, and `report` commands. Do not rerun a completed arm: duplicate reports and concurrent controllers are rejected. The exact original outputs are the only candidate inputs; no model generation or training function is called.

The first $5 stage requires 18 hand-authored positive/negative remote calibration checks and all 176 frozen reference solutions to pass before it evaluates the 176 parent outputs. Each adapter's 80 outputs and the separate 32-output Kaggle baseline use one further $5 stage. Main coordinates at most two stages concurrently, with four CPU sandboxes per stage. Four token-limit failures are preserved, leaving 364 non-truncated outcomes for v2 verification or unchanged syntax/policy rejection. Infrastructure or invalid-task errors abort the stage and cannot count as model failures.

Aggregation independently recomputes scores from typed v2 outputs, then `rsilab.rescore.audit_rescores` validates the unchanged task/generation/provenance records, new evaluator identity, original source hashes and complete 13 logical-batch coverage. It reports all old/new outcomes and paired Modal parent/adapter scores; Kaggle stays separate. Original model checkpoints, training labels and source tests remain untouched. There is no automatic promotion or training.

## Framework validation

All **199 integrated tests** passed before execution, including the cached real tokenizer, v2 positive/negative/malformed-type tests, immutable lineage/tamper checks and launch guards. A second chat reviewed the controller/API integration and found no launch blocker.

`rsilab 0.1.1` was built from an explicit file allowlist, installed locally without dependencies, and checked with checkout imports excluded. Core, rescore and v2 imports plus all 11 rescore tests passed. The previous 0.1.0 wheel remains unchanged. New wheel: `work/rescore-framework-dist/rsilab-0.1.1-py3-none-any.whl`, SHA256 `3b72462b4b0a33101101831a9a2dec38ba335ca4bc97f6f44283719958af66ba`. No package was published to PyPI.

## Completed results

All 18 remote calibration checks and all 176 original reference solutions passed. All 368 saved outcomes are accounted for: four token-limit failures are preserved; the rest were reverified or received the unchanged syntax/policy rejection. One seed-43 attempt aborted after 77/80 saved rows at the infrastructure/invalid-task guard. A separately reserved recovery verified only the three absent outputs; no infrastructure failures remain unresolved in the final comparison. The original failed evidence remains intact. Trusted v2 scoring was recomputed from recorded outputs during aggregation, and all source/evaluator/lineage checks passed.

| Arm | Original evaluator | Corrected evaluator |
| --- | ---: | ---: |
| Parent | 17/48 (35.42%) | 18/48 (37.50%) |
| Adapter seed 42 | 16/48 (33.33%) | 17/48 (35.42%) |
| Adapter seed 43 | 15/48 (31.25%) | 16/48 (33.33%) |
| Kaggle separate baseline | 8/32 (25.00%) | 9/32 (28.12%) |

Only four outcomes changed, all false-to-true: parent and Kaggle task **568** (nested OrderedDict), and both adapters task **512** (Counter). No passing result became a failure. These are measurement corrections, not newly learned capabilities.

- Seed 42: development **3 wins / 4 losses**, net **-1** versus the corrected parent; retention **12/32** versus parent **13/32**, losing 1 previously passing task.
- Seed 43: development **2 wins / 4 losses**, net **-2** versus the corrected parent; retention **12/32** versus parent **13/32**, losing 1 previously passing task.

The four shared development regressions and the retention regex error remain. Correcting task 568 removes an apparent adapter gain; correcting task 512 restores a real task-level gain, leaving the overall net comparison unchanged. All **46** verified parent training labels remain eligible under v2; the existing adapters' labels and checkpoints were not modified.

**Decision: retain the original parent. No training or new generation was performed.** The original +4-net-development engineering threshold is still unmet for both seeds. Because evaluator changes followed inspection of saved failures, these corrected scores remain post-hoc development evidence. Sparse source tests and known transport coverage limits still constrain interpretation. In particular, the passing parent implementation on task 576 has a static counterexample not covered by the source tests; no extra tests were silently added to this rescore.

Consolidated [W&B correction report](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/gyzdo33g). The complete immutable JSON with all per-task changes is `artifacts/mbpp-rescore-v2/summary.json`; the compact tracked result is `studies/mbpp_rescore_v2/results.json`. Original v1 reports, original comparison artifacts, old wheel, source cases and generated code remain intact.

## Recovery and budget

The original four stages reserved $20. Seed 43 aborted after saving 77 of 80 outcomes; the controller raised before persisting the underlying infrastructure/invalid-task result. The precise cause is unknown. A separately frozen [recovery protocol](../studies/mbpp_rescore_v2/recovery.json) reserved another $5 and reverified only tasks 648, 582 and 557. Independent review confirmed all original 77 rows were unchanged. The failed reservation and original W&B report artifact v0 are preserved; the completed logical report links the recovery run. All five Modal apps are stopped with zero tasks.

This correction reserved **$25** in total. Project reservations are now **$150**, plus **$25** held for overhead, leaving **$75** unallocated within the unchanged **$250** cap. These are conservative reservations, not actual charges. The aggregate JSON retains its historical Kaggle-stage $145 budget snapshot; `artifacts/mbpp-rescore-v2/completion.json` records the current budget including recovery. The latest read-only billing snapshot reports workspace month-to-date metered usage of $1.31054595 and $0 billed after credits; it is provisional, may lag or be revised, and is not a project invoice. See `budget/reconciliation-mbpp-v2-2026-11-04.json`.

Before the next experiment, a new controller version should persist infrastructure results before raising and harvest already completed futures on abort. The frozen controller stays unchanged to preserve this study. A separate future protocol should strengthen test coverage before any further training.
