# Feedback repair versus independent sampling

This study tests whether verifier feedback improves the yield of training examples from the original MiniCPM5-2B teacher and its experimental learned adapter. The main chat coordinates all launches. This prospective design was written before model generation. The machine-readable plan must bind a reviewed cohort, source inventory and runtime controls before a job starts.

## Intervention and outcomes

On the same ordered fresh training tasks, each teacher produces one greedy answer with seed 42. That answer is shared by its two comparison branches. Each branch receives one additional attempt at temperature 0.7 with seed 31415 and the same per-position seed schedule. The sampling branch sees the original prompt. For failed first attempts, the repair branch sees the prompt, its own prior answer and only an allowlisted failure category. For passed first attempts, both second calls receive the original prompt and the same seed. Both branches generate for every task, including first-pass successes. All calls use the same 512 output-token and 2,048 input-token ceilings. Persist realized token counts and any truncations. Hidden tests, expected values, reference code and raw exceptions stay outside the repair prompt.

The primary feasibility outcome is the difference in unique verified tasks between greedy-plus-repair and greedy-plus-sampling within each teacher. Also compare the teachers on the same task IDs and report category yields, overlap, gains, losses and actual costs. Count each task once even if both attempts pass. Treat infrastructure errors as incomplete evidence. Record every attempt, including failures.

The repair branch is the only source for child labels. Both teachers need at least 16 unique verified task/code targets, coverage of text, numeric and collections, and a maximum category share of 60%. Use the earliest passing answer per task. If both pass, select exactly 16 per teacher under the same category quotas in frozen order, with distinct resulting datasets. A failed gate stops both child jobs. Preserve the prior parent in all cases.

## Students and evaluation

If eligible, initialize both children separately from the same original model. Match seed, LoRA configuration, optimizer settings, update count, evaluator and inference budgets. Each child is evaluated on the same fresh evaluation block and 16 previously exposed retention tasks. Compare both to a fresh starting-model baseline. A promising child needs at least three net new successes relative to both the starting baseline and the other child, with no individual retention success lost against either comparator. Report paired task outcomes, denominators and realized training tokens. One positive pair is preliminary successor evidence. Replication and another generation would be separate experiments.

## Data and project budget

The native-only MBPP screen failed the training and text minima. Apply the [prospective source amendment](source-amendment.md) to combine reviewed MBPP and APPS native-training records, excluding the 284 exposure records and exact or near duplicates. The requested training block is 24–32 audited tasks, with at least six text tasks, and the fresh evaluation block needs at least eight independent tasks. Neither the original pilot's sealed domains nor MBPP's native final test may be used. Publish the source split and limitations. No train or evaluation prompts may be added based on model outcomes.

| Stage | Maximum reservation |
| --- | ---: |
| CPU probe | $1 |
| Fresh base evaluation | $4 |
| Original teacher | $5 |
| Learned teacher | $5 |
| Original-teacher child, if eligible | $5 |
| Learned-teacher child, if eligible | $5 |
| **Maximum total** | **$25** |

At design time, $194 of the $250 project cap was reserved for jobs, with $25 held for overhead and $31 available. A complete six-stage run would leave $6 available. This table gives planning reservations. Every attempted stage must reserve before launching, retain its reservation on failure, and terminate within its specified resource bounds. Preflight or data failure stops dependent jobs. At recorded L40S, CPU and memory rates, three 30-minute function execution windows at 2 cores and 16 GiB total about $3.26. Cold starts, isolated verifiers, storage and actual provider billing require separate accounting. [Modal prices](https://modal.com/pricing)
