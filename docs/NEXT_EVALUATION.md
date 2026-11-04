# Proposed next evaluation

Historical proposal after the synthetic pilot. The later user-authorized MBPP v1 study adopted its own frozen protocol; see [MBPP experiment record](MBPP_EXPERIMENT.md). Gates suggested below do not override that protocol.

November 4, 2026. **The next experiment remains proposed; the completed compatibility run does not establish a generalization gain or authorize another launch.** Exactly one 20-step QLoRA adapter on four verified training outputs completed its matched comparison. Training-family scores increased while development scores regressed; the parent was retained. This document does not change that run, its frozen prompts, or its acceptance criteria retrospectively.

## Baseline evidence and immediate decision

The completed [baseline report](../runs/20261104T070918Z-baseline-14df3d/report.json) records **4/16 training successes** and **7/8 development successes**, using `pilot-v2`, seed 42, greedy decoding, and a 512-token output cap. All four training successes are `masked_mean`; `stable_softmax`, `gradient_clip`, and `sequence_pad` each score 0/4. Development scores are `group_reduce` 3/4 and `interval_union` 4/4. These are baseline measurements, not post-training gains.

Main chat additionally reports three truncated outputs, missing `import math` in several math-using solutions, and wrong sequence-task outputs. Inspect these categories separately before interpreting low training yield as uniformly poor reasoning. Keep them as failures under the frozen current protocol; do not patch candidate imports, increase the cap selectively, or replace model answers with references. A proposed future prompt/cap change requires a new version and matched parent baseline.

The completed [matched evaluation report](../runs/20261104T072356Z-evaluate-92cbe2/report.json) records **training 4/16 → 6/16** and **development 7/8 → 5/8**. The paired changes were two `sequence_pad` wins with no training losses, and two `group_reduce` losses with no development wins. Task hash, packages, and decoding settings match. A later strict framework check found A10G versus A10 observed hardware; the original resource request was A10 for both, but exact hardware equivalence was not established. This establishes an executed compatibility comparison and a development regression on this small suite, not improved generalization or recursive improvement. Four same-family labels repeated for 20 steps add no independent evidence or training-family coverage.

**Current decision: retain the parent; no promotion, further jobs, or final-test audit.** The four same-family labels miss the proposed diversity gate below, the parent's 7/8 development score is near-ceiling, and the adapter regressed. The proposed next work remains a harder, broader development manifest and a separately frozen collection protocol capable of testing training-family yield. Do not extend the completed run or use final families to fill either gap. Any future experiment still needs the gates and budget checks below.

## Question and interpretation

Next ask whether execution-verified self-training produces a repeatable development improvement under a fixed inference budget, without losing previously solved tasks. A successful update demonstrates a limited self-training effect. It does not establish that the model has become better at producing successors, let alone sustained recursive improvement.

Report task successes, paired wins/losses, and results by family. Hidden cases are checks within a task, not additional independent observations; semantic variants and new sampling seeds remain correlated. Two development families cannot support a broad coding-capability claim. Training-task gains primarily measure fitting/retention. Loss reduction alone is not a capability result.

## Gate after the current comparison

These thresholds are prospective engineering decisions for further work, not significance tests or retroactive promotion rules.

| Observation | Proposed action |
| --- | --- |
| Missing provenance, split leakage, unresolved execution/infrastructure failures, or unequal inference settings | Stop interpretation and paid expansion; repair and invalidate affected comparisons. Do not count infrastructure failures as model errors or silently omit them. |
| Parent solves 7–8 of 8 development tasks | Treat as near-ceiling. Do not add epochs or repeatedly resample these families to manufacture a gain. Build and freeze a separate harder development suite before another learning claim. |
| Parent solves 0–1 of 8 development tasks | Inspect failure categories locally. Fix protocol/format problems first; if failures reflect capability, design a more learnable training curriculum without using development answers as labels. |
| Parent solves 2–6 of 8 | There is pilot headroom, but the current suite is still too narrow for promotion. Proceed to the bounded replication design below only after integrity and budget checks. |

Preserve all current outputs, including failures. Do not borrow `edit_distance` or `graph_reachability` tasks, reference solutions, or near-duplicate variants for curriculum design, training, or development.

## Bounded replication design

Create a separately versioned development manifest of 24 tasks: six variants in each of four families. Retain the two existing development families with newly reviewed harder task requirements, and add two independently reviewed families with different core algorithms; exclude graph traversal, edit-distance/dynamic-programming variants, and near-duplicates of training tasks. Simply increasing hidden-case counts or changing seeds does not address prompt-level saturation. Review requirements, boundary cases, and independent oracle checks before model evaluation. These additions are proposed work, not implemented tasks; preserve the current frozen prompts.

Use that development baseline for difficulty calibration. Proceed only if the parent solves 6–18 of 24 and at least three families have both successes and failures. Otherwise stop this experiment and record a new proposal; never change an evaluated manifest in place. Calibration makes this development data, not an untouched test set.

Collect at most 32 train-family attempts with a fixed generation budget. Require at least eight distinct, verified training examples spanning at least three training families. Deduplicate solutions; retain raw unsuccessful attempts separately. No reference substitution or development labels. Freeze the dataset and train two fresh adapters from the same parent, each for 20 steps with identical settings except predeclared training seeds. This tests training-seed sensitivity, not independent dataset replication. No hyperparameter sweep or extra generations in this experiment.

Evaluate parent and both adapters on identical development and 16 fixed training-family retention tasks. Retention tasks are diagnostic, not held-out evidence. Use one greedy attempt, no repair feedback, the same 512-token output cap, tokenizer/template, precision, and hardware class. Truncated or invalid model outputs count as failures. Record actual tokens/time as well as equal caps. Any later budget change requires rerunning all compared arms under a new protocol.

**Go to one final audit only if both adapters independently achieve:** at least three net additional development successes out of 24; no decline in any development family's task count; no more than one lost parent success on the 16 retention tasks; and no unresolved integrity or infrastructure issue. Otherwise retain the parent and stop this experiment. These deliberately simple gates justify a follow-up audit, not a statistical claim. Report each seed separately rather than treating seed/task combinations as independent samples.

## Freeze before any final-test use

Before the replication starts, save a protocol artifact containing manifest hashes, model/tokenizer/code/evaluator revisions, dataset selection rules, seeds, training settings, inference caps, metrics, exclusions/retry policy, thresholds above, and the budget envelope. Reserve the final families throughout development. Select one adapter by development family-macro score, breaking ties by lower predeclared training seed; record its immutable checkpoint before opening final results.

For the final audit, freeze 16 tasks: eight variants each of `edit_distance` and `graph_reachability`, at a seed recorded in the protocol. Compare the selected adapter and original parent once under the same inference settings. Only prompts/public examples reach the models; hidden outputs remain with the controller. No final feedback, repairs, training, candidate selection, or threshold changes.

Proposed final gate: at least two net additional successes out of 16, with no decline in either family's success count, and the development/retention gates still satisfied. Failure or insufficient headroom means no promotion. Even passage supports only a provisional pilot checkpoint for further research, with the original parent retained for rollback. Report all paired outcomes; do not attach a population-level confidence claim to two correlated families. Subsequent decisions informed by these final results consume their holdout status and require fresh independent final families for another confirmatory comparison.

## Budget and later recursion test

Main chat alone reconciles provider billing and outstanding reservations before launch. The existing **$250 total project cap**, **$25 overhead holdback**, and **at most $5 per-stage reservation through `rsi/budget.py`** remain binding. Do not infer the remaining balance from this proposal or release failed reservations based on runtime estimates.

Propose a maximum **$50 incremental envelope**, including collection, both training runs, all paired evaluations, and any retries; use less if available headroom is smaller. Before launching, main chat must map the complete design to bounded stages and show it fits both this envelope and the cumulative ledger/billing headroom while preserving overhead. If it does not fit, stop before spending or freeze a reduced protocol; do not split jobs merely to evade a stage cap. Unused allowance is not a spending target. Storage and result export must also fit the project cap.

A later, separately budgeted recursion experiment would give the original and learned **improvers** identical starting student checkpoints, experience, permitted improvement actions, and compute/token budgets. Each would produce a successor using only training data; independent fresh tasks would score those successors. Freeze the improvement interface and compare successor quality across multiple matched starting conditions. Better task-solving by an improver is not this result; sustained recursion would additionally require evidence across successive improvement rounds. Neither experiment is authorized or claimed by this document.

## Handoff

Only this document was added/updated. Proposal consistency was checked against local task, pilot, project-plan, and budget-policy documents; baseline status/settings and aggregate/family scores, and completed evaluation status/settings/scores/non-promotion, were read from the supplied local reports. Failure-category details, paired changes, matching packages/hardware/task hash, and the decision to retain the parent and stop jobs are attributed to main chat. No credentials, private accounts, jobs, or billing were accessed or initiated here. Future diverse-data yield, runtime/cost feasibility, new-family implementation, and remaining budget are unresolved. Main chat is finalizing the experiment record, work log, budget, and Git. Any later experiment requires a costed, frozen redesign addressing diversity and ceiling gates before launch or final-test use.
