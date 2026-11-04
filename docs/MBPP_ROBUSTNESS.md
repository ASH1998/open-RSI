# Stronger MBPP diagnostics and durable execution

Completed November 4, 2026. This milestone improves evaluation coverage and failure recording before further training. It does not train, generate new answers, promote an adapter, or replace the previous 368-outcome correction study.

## Completed implementation

`rsilab.execution.execute_bounded` persists each returned verification or sanitized exception envelope before validation. It bounds concurrent work, stops submissions on failure, cancels queued work, and harvests all already-running outcomes before raising `ExecutionAborted`. Deterministically ordered summaries identify missing and unpersisted records and retain results for controller-owned fallback storage. There is no automatic retry. Arbitrary stuck threads cannot be killed safely; trusted callbacks must enforce their own time limits, as the Modal verifier does. Storage failure is surfaced, not claimed to be recoverable if every durable store fails. See [API and tests](EXECUTION.md).

The new controller, `rsi/robustness_study.py`, uses this helper. It requires exact frozen source/input identities, rejects duplicate launches (including failed attempts), reserves budget before compute, verifies every source reference first, and recomputes saved scores from typed evidence. Original-case rerun, additional-case, and combined scores are recorded separately. Code and assertion hashes bind outputs to inputs. This supersedes the defective failure-recording pattern for future diagnostic work; the historical v2 controller remains unchanged for reproduction.

## Frozen coverage and remote validation

[Protocol](../studies/mbpp_robustness_v1/protocol.json) SHA256: `c19a8f43aa3e72e3733d8732cc179aa4f0b4343079ed66dee4caffb3afe32f7b`. Commit `574711c` preceded execution.

Seven tasks preserve **21 original assertions** and add **43 independently hand-calculated assertions**, for **64 reference cases**. Topics are nested tuple frequencies, positive-integer LCM, case toggling, digit distance, lists of empty mappings, ordered contiguous subarrays, and date conversion. Task identities and ambiguous-domain exclusions are documented in the [case specification](MBPP_ROBUSTNESS_CASES.md). For task 558, the pinned source contract means digit sum of the absolute numeric difference.

All seven pinned references passed all 64 cases remotely before candidate execution. All **23 available saved outputs** then completed under the same v2 verifier and resource bounds. Every original-case pass/fail outcome matched the archived v2 result. There were no infrastructure errors, missing records, retries, new generations, or training steps. The new Modal app is stopped with zero tasks.

## Selected-task results

These are post-hoc diagnostics on seven deliberately selected tasks (six development tasks plus retention task 928), not new held-out benchmark scores. Kaggle has saved outputs for only tasks 520 and 568 in this selection and is reported separately.

| Arm | Original cases on selected tasks | Original plus stronger cases |
| --- | ---: | ---: |
| Parent | 6/7 | 4/7 |
| Adapter seed 42 | 2/7 | 2/7 |
| Adapter seed 43 | 2/7 | 2/7 |
| Separate Kaggle subset | 2/2 | 2/2 |

The added cases reveal two previously undetected parent errors, on **558 (digit distance)** and **576 (ordered contiguous subarray detection)**. Both still pass their original three assertions. Parent 558 passes only 2/6 added cases; parent 576 passes only 4/10. The adapters' task-512 solutions pass all nine combined cases, confirming that the earlier Counter correction was valid. No passing adapter result was lost on this selected subset.

Independent read-only review reproduced every score and confirmed all original-case typed outputs exactly match the archived v2 evidence. Static inspection of parent task 558 shows it sums differences between corresponding digits and ignores unmatched trailing digits. For `(10, 1)` it returned `0`, whereas the specified digit sum of `abs(10 - 1)` is `9`; `(1000, 1)` returned `0` instead of `27`. These counterexamples were specified before the diagnostic run.

The original benchmark remains recorded as parent **18/48**, seed 42 **17/48**, seed 43 **16/48**. The diagnostic does not justify promotion or a generalization claim; the parent remains selected. It shows that sparse source tests can admit incorrect solutions and should not be treated as proof of broad correctness.

## Verification, package, and cost

All **230 integrated tests** passed, including the pinned cached tokenizer. An independent chat reviewed the controller before execution. Local `rsilab 0.1.2` was built from an explicit source allowlist, installed without dependency downloads, and passed all **15 execution tests** with checkout imports excluded. Wheel SHA256: `7472b2512f8b3c8842fba81a4a03a36d91a9c205f0dc963d5c76cf0ba1823ce1`. Earlier wheels and frozen study sources remain unchanged. No PyPI publication occurred.

The single CPU stage reserved **$5**. Cumulative project reservations are **$155**, with **$25** held for overhead and **$70** unallocated within the unchanged **$250** cap. Reservations are not actual invoices. The latest read-only workspace billing snapshot remains provisional; see `budget/reconciliation-robustness-2026-11-04.json`.

W&B [run and diagnostic artifact](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/6aygjyx7). Remote readback matched the original run report, diagnostic summary, and frozen protocol, and verified dependency on the earlier evaluator-correction artifact. Compact tracked results: `studies/mbpp_robustness_v1/results.json`. Full evidence stays on SSD in `runs/20261104T132855Z-robustness-v1-validate-2ef6ac/report.json` and `artifacts/mbpp-robustness-v1/`.

## Next research milestone

This engineering milestone is complete. Before another training experiment, freeze a prospective task-selection and stronger-verification policy for training data and development evaluation, with a fresh final evaluation kept untouched. Retain the current parent and checkpoints. These seven inspected tasks remain diagnostics and are not automatically added as labels or held-out evidence. The next experiment should test whether better verified data improves a fresh adapter under the same inference budget; its outcome remains unknown.
