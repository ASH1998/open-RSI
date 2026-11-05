# Task contracts v1

This offline diagnostic revises the wording and private checks for the 20 native MBPP training tasks used in the completed successor probe. Each reviewed prompt preserves the original function declaration and execution instructions. Each task names its input domain, expected result and any ordering, indexing, type or endpoint conventions that affect grading. The reviews bind the original task hashes and preserve the order of all inherited tests.

The pinned training references passed **346/346 cases** across the cohort, including **73 new checks**. The two data and review chats also calculated expected values independently of executing the references.

On task 675, the interval includes its lower endpoint and excludes its upper endpoint. For the interval `[5, 9)`, a sum of eight returns 20 and a sum of nine returns nine. All four historical teacher responses include nine. The new check distinguishes those implementations by inspection. For the three text tasks, the reviews clarify the string return value for reverse-pair counting, character bijection for string isomorphism and stable ordering when moving digits. [Review notes](review_notes.md) and [independent review](independent_review.md).

From the project root, replay the diagnostic using the SSD environment and the pinned native training data.

```sh
.venv/bin/python -m studies.task_contracts_v1.audit
```

The replay derives tasks using the public library, runs checksum-bound reference implementations in a separate interpreter with an empty credential environment, checks all typed outputs, and compares the results with the saved records. The reference worker accepts task IDs and arguments only. The prior evaluation splits stay outside the worker. The reviewed manifest and full exposure registry live in `data/task-contracts-v1/`. Reference outputs live in `artifacts/task-contracts-v1/`. The [compact results](results.json) give their identities, case counts and the prior protocol hash. A new workspace with the source data and recovery evidence can create missing records with `--freeze`. Existing evidence must match on replay.

All 20 tasks have prior teacher exposure. The registry combines them with the 264 records accumulated before the recovery probe. Future cohort selection should load the 284 records and retain task identity across wording changes. This diagnostic measures reference agreement on reviewed cases. Improvement in model performance on the clarified prompts would require a separate experiment.

The original MBPP training data and derived wording are attributed to the MBPP authors, under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Dataset revision `4bb6404fdc6cacfda99d4ac4205087b89d32030c`. This study modifies task descriptions and adds independently specified cases. The reusable Python implementation uses the repository's Apache-2.0 license.
