# MBPP-only single-lesson experiment

This exploratory comparison trains two fresh copies of MiniCPM5-2B. In the eighth position of an otherwise identical eight-lesson bundle, arm A uses MBPP 723 and arm B uses MBPP 811. The same learned teacher supplied all examples. Neither arm trains or tests a learned lesson selector. The original parent stays selected regardless of the result.

Both students use seed 42, the existing rank-8 QLoRA worker and 16 optimizer steps. Each arm's single evaluation call processes individual prompts greedily. The first eight are the exposed repair-v1 MBPP development block. Position nine is native-validation task 575 instead of the historical APPS prompt. Positions 10–25 are the same 16 historical MBPP retention tasks. The order preserves the historical base's per-position seeds for the eight development and 16 retention comparisons. Task 575 has no historical baseline, so report only the two students' outcomes on that task. Its bounded reference calibration and the already exposed status of the other tasks are recorded in the [feasibility result](../lesson_selection_v1/feasibility.json).

The primary descriptive outcome is each student's task-level gains and losses against the other on the eight exposed development tasks. Report retention discordances separately and disclose all outcomes, including ties and failures. A favorable direction is more development successes with no retention losses relative to the other arm; a single switch and a single seed cannot establish a better improver. There is no promotion, recursion, automatic retry or further generation.

## Launch envelope

Reuse the saved CPU probe on the same portable worker configuration, image construction and package inventory. Check returned runtime identity, hardware and packages on both new GPU calls. Reuse the prior verified base outputs for the 24 common prompts; exclude the APPS task from labels, evaluation, counts and scores.

Each arm may reserve $3 through the project ledger. The limit is two L40S function calls and at most 25 isolated candidate evaluations per arm. Counting 1,800 execution, 600 startup and 15 scaledown seconds per function with two CPU cores and 16 GiB RAM gives about $2.92 direct compute per arm including the bounded sandbox executions. The separate existing overhead hold covers workspace overhead and transfers. Stage reservations are planning bounds, not invoices. Use the project-wide cap and reject duplicate reservations, retries and partial continuation. [Modal resource prices](https://modal.com/pricing)

Only the main project chat coordinates paid launches. Run preflight before either stage. The learner-quality gate on the separate confirmatory proposal still fails; this study collects an exploratory substitution outcome only.
