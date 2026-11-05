# MBPP single-lesson substitution

Both students completed 16 optimizer steps from the same base checkpoint, using seven shared examples and a different eighth example. Arm A received lesson 723 on counting matching list positions. Arm B received lesson 811 on comparing ordered lists of tuples. The examples all came from the same learned teacher. A supplied 1,944 supervised tokens across training and B supplied 1,920.

| Model | Previously exposed development | Previously exposed retention | Previously unused task 575 |
| --- | ---: | ---: | ---: |
| Starting model, historical aligned scores | 3/8 | 8/16 | Unmeasured |
| Arm A, lesson 723 | 3/8 | 6/16 | Failed, 0/6 cases |
| Arm B, lesson 811 | 4/8 | 6/16 | Failed, 0/6 cases |

B gained task 780 against A and lost no development or retention tasks against A. On task 780 the requested function combines pairs of tuples. A's saved comprehension referenced two undefined variables when a pair existed and passed two of six cases. B indexed both tuples and passed all six. The net difference between A and B is one success on eight exposed development tasks. Relative to the starting model, A gained 915 and lost 950. B gained 780 and 915 and lost 950. Both lost retention successes 621 and 854. The original parent stays selected. [Paired outcomes and verified stage metrics](../studies/lesson_pair_v2/results.json)

The direction favors B in this one-seed exploratory comparison. The single unused validation task provides no evidence of a fresh gain, and neither student has a base score to compare against on that task. A change in which lesson was supplied can affect a student. Testing learned selection or recursive self-improvement requires a different experiment.

Main preserved the original scientific plan, reproduced a missing verifier source-hash field on an archived result before any reservation, and froze a separate execution addendum. The corrected preflight exercised the actual scorer on 25 saved outcomes. Both students trained and evaluated once with identical settings and task positions. The final comparison verified both training requests, all 50 evaluation outcomes and 12 exported adapter/checkpoint files per arm. Checkpoint resume was not exercised. Comparison digest `23936ed088c4299c1dfd52dfbae2ead7925501713324c69886d272c6752386b8`. [Scientific protocol](../studies/lesson_pair_v1/README.md) · [Runtime correction](../studies/lesson_pair_v2/README.md)

Both W&B stage artifacts matched the allowlisted SSD payloads and full-local-report hashes after download. Full run outputs and exported training states are retained on the SSD. Both Modal apps stopped with zero tasks. [Arm A run](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/0y8mgaab) · [Arm B run](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/8y352kja)

The two $3 reservations used the final $6 of the planning ledger. Cumulative job reservations total $225, overhead is $25 and unallocated funds are $0. The controller estimated about $0.23 of direct execution for the two arms combined. The lagging workspace snapshot showed $3.86141994 month-to-date metered and $0 billed; final project invoicing remains open. No further paid stage is scheduled.
