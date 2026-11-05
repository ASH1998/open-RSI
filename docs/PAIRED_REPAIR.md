# Matched sampling and repair

## Runner interface

The pure functions in `rsilab.paired_repair` take JSON-compatible dictionaries. The caller passes the trusted, frozen **training** manifest produced by `apply_task_contracts`, with its original `tasks`, `prompts`, `lineage` and `sha256`. A flat list of derived tasks alone cannot replay the boundary scorer.

```python
from rsilab.paired_repair import second_prompts, audit_paired_repair

prompts = second_prompts(manifest, first_records)
# prompts["sample"] and prompts["repair"] are {task_id: public_prompt} mappings.
# Give each to VerifiedCollector.collect(..., prompts=...) in frozen task order.
report = audit_paired_repair(manifest, teachers, controls, original_run, learned_run)
if report["child_gate"]["eligible"]:
    examples = report["child_gate"]["examples"]  # {original: [...], learned: [...]}
```

* `teachers` maps `original` and `learned` to the existing successor agent identities. The learned adapter must bind to the original teacher. `controls` maps `first` and `second` to the existing normalized inference-control shape (generation, effective_seeds, runtime, evaluator). Set evaluator.version to `mbpp-typed-v2` and evaluator.source_hashes to the actual V2 executor inventory. Pin the typed scorer's source in runtime.source_hashes with key `rsilab/task_contracts.py`. First temperature is zero. Second temperature is positive. Both branches share one second control set.
* Each run has `run_id`, `teacher` (the full agent), `manifest_sha256`, and `collections` keyed by `first`, `sample`, `repair`. Each collection has `controls` (normalized actual worker evidence), `prompts` (ordered list of exactly {id, prompt} sent to the worker), `records` (all VerifiedCollector rows plus `effective_seed`), and `request_sha256` (the normalized `inference_request_sha256(teacher, controls, prompts)`). The controller separately binds this projection to the actual durable provider request/response. No inferred worker settings.
* Generate three complete ordered batches per teacher. The first is physically shared by both strategies. Both second batches cover every task at the same per-task seed, temperature and token limits. For first successes both second requests are independent samples of the unchanged public prompt. For first failures only the repair branch sees its teacher's own first answer and one fixed failure-kind label. The first verified answer always wins.
* Each verification retains V2 executor identity/evidence. For rows with actual isolated outputs, merge `score_task_contract_outputs(manifest, id, outputs)` into the top-level verification dictionary **before** the collector decides whether to attach verified_code. Keep original executor evidence in the run report. The audit independently recomputes every field of the typed score from those outputs. For generation limits, candidate policy, invalid candidate or unsuccessful sandbox execution, retain the native failure envelope instead of inventing outputs.
* The output keeps both run ledgers, per-teacher paired sample/repair task IDs and unique selected yields. Only repair-arm targets can enter child data. Both complete repair selections must supply at least 16 unique targets, represent text, numeric and collections, and have no category above 60%. From common category capacities choose exactly 16 with the same counts per category, text, numeric and collections, and at most nine examples of any one category. Allocate one per nonexhausted category per round in order of first appearance in the frozen cohort, visiting required categories before optional ones. Take the earliest selected rows in each category and emit them in the original task order. If no matched subset meets all criteria, withhold both children. Identical child prompt/completion sequences block both children. Training examples have fields `prompt`, `completion`, `verified`. On a gate failure both example lists are empty. The report measures teacher yield only.

## Reading the report

Each `report["teachers"][role]` carries a deep copy of the complete run, three physical token totals, and the verdict of each first attempt. Count the greedy batch once when accounting for actual tokens and cost. The caller records wall time, reservation, actual worker call IDs and estimated cost alongside the stage report. These quantities can differ even when generation limits match.

The `arms` entry contains `sample` and `repair` selections. Each stores solved task IDs, earliest verified task/code pairs, exact-code duplicate exclusions and category counts. A later pass on a task cannot replace its earliest pass to evade deduplication. Every training example uses the original public task prompt as input and the verified implementation as its completion. The repair prompt and failed attempts remain in the evidence.

The `paired_solved` table compares solved task IDs before code deduplication. The `paired_unique` table compares task IDs with selected targets after deduplication. The tables name four groups, `both`, `left_only` (sampling), `right_only` (repair) and `neither`. Each list follows the frozen cohort order. `repair_minus_sample_unique` gives the signed count difference. `recoveries_by_category` uses the same groups restricted to first-attempt failures. The top-level `paired_teachers_unique` tables compare original (left) and learned (right) selections on each strategy. Retain the denominators and raw disagreements.

The comparison combines access to prior code, a failure category and a revision instruction. The runner must independently bind the normalized controls and raw outputs to actual worker requests/responses, reconstruct trusted manifests from pinned sources, enforce splits and reservations and preserve partial evidence on infrastructure failures. The API audits completed evidence and raises on a mismatch. It leaves the original parent selected. Child evaluation and any subsequent-generation experiments require separate evidence.

## Verification and handoff

```sh
.venv/bin/python -B -m unittest discover -s tests -p test_paired_repair.py -v
```

The 12 synthetic tests passed both from source and from a scratch wheel installed on the SSD. The installed test run used isolated Python, checked package origins and blocked socket connections and DNS resolution. The example also ran from the isolated installation. In its single-task fixture, typed replay rejects an integer returned where the reviewed boundary requires a boolean. Only the original teacher's repair supplies a target, and both child datasets are withheld. Run `python -I examples/paired_repair.py` with this module installed to reproduce the fixture.

The runner interface and tests are ready for integration. The scratch wheel was built from the concurrent project source during development. Main owns the frozen release, full-suite validation, launches and experiment results.
