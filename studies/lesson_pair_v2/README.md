# Runtime correction for the MBPP lesson pair

The scientific plan is the original lesson-pair-v1 seal `73cc79b2be12d046ced88ee3653ce431e30a00ab2bd6f6a31c8feecf5f74c02b`. Neither arm had a reservation or model outputs when this correction was prepared. An offline replay of a real child evaluation showed that the first controller passed a plan with `source_files` to the shared verifier, which requires `source_hashes`. The exception occurs at the end of scoring, after GPU work. The runtime addendum binds that missing inventory and replays the real scoring path before any paid reservation.

The corrected executor uses the same eight verified MBPP examples per arm (seven shared and one alternative), native diagnostic, baseline positions, worker, seeds, token controls, evaluation cases, parent decision, stage IDs and $3 maximum per arm. The single shared ledger namespace enforces one attempt per arm across both executors. Only the main chat launches A followed by B. The comparison addresses a single lesson substitution. The eight development and 16 retention tasks are exposed; only native task 575 is unused and has no baseline score.

From the SSD root, run `.venv/bin/python -B -m studies.lesson_pair_v2.experiment preflight` or `report`. The runtime plan records the scientific seal, versioned code and historical worker source inventory.
