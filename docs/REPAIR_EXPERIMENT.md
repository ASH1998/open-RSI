# Matched sampling, feedback repair and successor training

Completed November 5, 2026. A student trained on the learned teacher's solutions passed exactly the same fresh and retention tasks as a student trained on the original teacher's solutions. Both gained one fresh success overall and lost two previously retained successes relative to the starting model. The study's decision is to retain the original parent.

| Model | Fresh tasks | Historical retention |
| --- | ---: | ---: |
| Starting MiniCPM5-2B | 3/9 | 8/16 |
| Student of original teacher | 4/9 | 6/16 |
| Student of learned teacher | 4/9 | 6/16 |

Both students gained MBPP 780 and 915, lost MBPP 950 on fresh evaluation, and lost retention tasks 621 and 854. Both failed the single fresh APPS text task, 4194. The tie applies to all 25 task-level pass/fail decisions. The students' weights and individual outputs differ. With nine fresh tasks, a single seed and one generation, these observations provide no evidence of superior successor performance for the learned teacher. [Paired results](../studies/repair_v1/results.json)

## Teaching-data experiment

Each teacher received the same 24 tasks and three calls. The greedy attempt was shared between the independent-sampling and feedback-repair branches. Each branch received the same sampling seed and token limits. For greedy failures, the revision saw its own answer and a short failure category. Tests and expected values remained in the verifier.

| Teacher | Greedy passes | Greedy + independent sample, unique | Greedy + feedback repair, unique |
| --- | ---: | ---: | ---: |
| Original | 17/24 | 17/24 | 19/24 |
| Learned adapter | 17/24 | 17/24 | 18/24 |

The original teacher recovered MBPP 943 and APPS 3038 through repair. The learned teacher recovered MBPP 664. Neither independent sample added a solution beyond its greedy pass. All 144 attempts are preserved on the SSD. This compares two ways to produce labels and separately compares students trained on the repair labels. A student trained on independent-sampling labels would require a separate control.

The gate admitted 16 examples per teacher, with eight collections tasks, four numeric tasks and four text tasks in each set. Each fresh QLoRA student used seed 42, the same starting checkpoint and 16 optimizer steps. Realized supervised tokens were 4,416 for the original teacher's student and 3,124 for the learned teacher's. The frozen budget matched examples and optimization settings. Each training job exported a 12-file adapter and checkpoint inventory with optimizer, scheduler and RNG state. Both inventories were checked. A resume from those exports is a separate, untested operation. [Failure analysis](../studies/repair_v1/failure_analysis.md)

## Data and limits

The native MBPP screen yielded 19 training tasks and only two text tasks. Before any model generation, an independent review admitted six additional native APPS training tasks and quarantined two others for semantic overlap. Five supplemented training and one entered the held-back block by a deterministic hash rule. All 234 cases for the 33 selected tasks passed reference calibration. Among the 19 MBPP training tasks, repair yielded 16 solutions for each teacher. Among the five APPS training tasks, repair yielded three for the original teacher and two for the learned teacher. These convenience samples have prior-project exposure screening but may overlap model pretraining. [Source amendment](../studies/repair_v1/source-amendment.md)

A finite passing suite can admit an incorrect label. After generation, static review found that the original teacher's passing solution for task 663 would mishandle a positive requested remainder with divisor one. The frozen protocol selected that task. This finding is preserved separately from the official score. Reviewers also documented an uncovered case in a baseline answer on task 950. [Independent review](../studies/repair_v1/independent_review.md)

## Reproduction, tracking and cost

The preregistered code was pushed at `592bfb6`. The plan binds the exact model revision and adapter bytes, source files, exposure registry, calibrated inputs, evaluator, seeds and resource limits. The installed 0.6.0 library supports offline replay. The source suite passed 484 tests, the installed wheel passed 196 tests, and the hosted checks passed. [Frozen plan](../studies/repair_v1/plan.json) · [Library API](PAIRED_REPAIR.md) · [Hosted CI](https://github.com/ASH1998/open-RSI/actions/runs/42065673608)

All six stage reports were downloaded from W&B and checked against their explicitly allowed fields and full-local-report hashes. The comparison run links all six stage artifacts and publishes only score counts and scientific identities. Full attempts, checkpoints and detailed outputs live on the SSD and the checkpoints also persist on the Modal Volume. [Comparison run](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/rpeaca8b38) · [Stage links and hashes](../studies/repair_v1/run-links.json)

All six experiment apps stopped with zero tasks. The study reserved $25, bringing project job reservations to $219, with $25 held for overhead and $6 unallocated. The controller estimates approximately $0.69 in direct execution costs across these stages, before overhead. The workspace-wide, lagging November 5 snapshot showed $3.42141782 metered and $0 billed after credits. Final project invoice reconciliation remains open. [Reservation ledger](../studies/repair_v1/reconciliation.json)

The next offline milestone is to diagnose the two retention regressions and the label-coverage defects before designing a replication. A stronger successor test needs a larger fresh evaluation block and later generations. This study schedules no further paid runs.
