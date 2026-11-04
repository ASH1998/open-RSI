# Reusing reference evidence after a category correction

`rsilab.reference_reuse.reuse_reference_audits` validates complete saved
reference executions and derives copies whose only changed field is
`task.category`. It performs no filesystem access, model inference, cloud
operations, or reference/candidate execution. Original inputs remain unchanged.

```python
from rsilab.reference_reuse import reuse_reference_audits

reuse = reuse_reference_audits(
    prepared=old_prepared,
    calibration_report=failed_calibration,
    correction=sealed_correction_proposal,
    expected_correction_sha256=pinned_correction_sha,
    expected_plan_sha256=pinned_old_plan_sha,
    expected_evaluator_source_hashes=pinned_evaluator_hashes,
    train_count=20,
    expected_category_counts={"collections": 9, "numeric": 8, "text": 3},
)
all_tasks = reuse["audited_pool"]       # All 24, in the original order.
selected = reuse["train"]              # First 20, independent copies.
assert reuse["preflight"]["first_n_category_counts"] == {
    "collections": 9, "numeric": 8, "text": 3,
}
```

The result contains a canonical `sha256`, source report/prepared/audit/plan and
correction identities, evaluator identities, all derived tasks, selected tasks,
category preflight, and one lineage record per task. Each lineage record binds
the original unaugmented task, original augmented task, derived task, original
audit, proposal, review, reference code, and correction row. `changed_fields`
is either `["category"]` or empty when the reviewed category already matched.
The existing task metadata keeps its original reference/review bindings; the
separate lineage records explain the subsequent category transformation.

## Required inputs and validation

`prepared` is the saved preparation dictionary containing ordered `items` and
`inventory_sha256`. Each item supplies `id`, `task`, `proposal`, `reference_code`,
`reference_sha256`, and `review`. Its complete canonical digest must match the
correction's source artifact and preserved preparation binding.

`calibration_report` retains the original failed status and body `ValueError`,
the original plan identity, and two complete `verify_records` execution streams:
`original_references` and `reference_probes`, each with its `_execution` summary.
Every row must be returned, persisted and validated, with exact index and task
order. Missing, duplicate, reordered, exceptional or detached rows fail. Any
GPU call or added generation/training/result field fails, including an empty
generation field. This version deliberately accepts only the documented
reference-only calibration report schema; new schemas need explicit support.

The function verifies reference code hashes using static extraction, rebuilds
the exact approved probe tasks, checks original/probe evaluator and source-test
identities, and recomputes typed scores and diagnostics. Probe `passed=False`
can be legitimate because probe expectations are non-authoritative placeholders;
the raw outputs and audit acceptance are what matter. Original references must
pass. Mutation evidence is reconstructed from the saved probe execution results,
not trusted merely because a saved audit includes it. Every original
`audit_reference_task` result must replay exactly, and every audit must remain
eligible. No audit is skipped or selected based on model outcomes.

`correction` is the independently reviewed, sealed proposal with its original
source artifact canonical digests, inventory/prepared/plan bindings, and ordered
task map. Every row specifies `task_id`, `original_serialized_category`,
`independently_reviewed_category`, `source_row_sha256`, `source_description`, and
a nonempty `reason`. The old category, row hash and description must match the
saved task. The new category must agree with the existing description-only
`coding_data.category` taxonomy. All rows, including fallback tasks, are checked.
The first-N derived category counts must exactly match the caller's declared
counts; no reordering, task replacement, case/test/prompt edits, or category
invention is permitted.

## Controller responsibilities and limits

Expected hashes must come from independently pinned evidence. Main must verify
the correction's source file hashes and canonical hashes, the old plan/prepared
seals, and the replay implementation/evaluator source identities against the
original frozen plan. The offline function validates dictionaries; it cannot
establish that their contents came from a real provider or that a reviewer was
independent. A self-consistent hash is integrity evidence, not authentication.
It also does not prove reference correctness or dataset semantic disjointness.

Persist the result under a new protocol/version. Preserve the original failed
report, audit pool, plan, prepared data and domain reviews; do not overwrite or
retroactively relabel them. The output neither retries the failed stage nor
authorizes another paid launch. The controller owns the new protocol, resource
limits, reservations, frozen generation controls, and all subsequent gates.

An optional `reuse_reference_categories(prepared=..., report=...,
correction=..., evaluator_source_hashes=..., first_n=20, min_categories=3)`
wrapper obtains the expected bindings from the correction. Its output names
the pools `tasks` and `selected_tasks`. Use it only after independently pinning
the proposal and its sources; the explicit-hash API above is preferred when
those expectations are available separately.

## Verification and handoff

The real saved successor-v1 calibration replays as 24 eligible audits with
261 accepted additional calls. Its first 20 derived tasks contain nine
collections, eight numeric, and three text categories, with 60 original and
213 additional cases. This was verified offline; no reference code ran again.

Synthetic tests cover nonmutation, hash lineage, controller wrapper behavior,
placeholder probe scores, pinned hashes, incomplete execution summaries,
detached/duplicate/reordered rows, result/evaluator identity mismatches, changed
outputs and audits, review-map changes including fallbacks, GPU evidence,
invalid thresholds, and malformed inputs. Run:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_reference_reuse.py' -v
```

Next executable milestone: main validates frozen source artifacts, integrates
the returned manifest into the corrected protocol, and independently reviews
that protocol before the authorized bounded generation stages. This module
does not certify controller integration or installed-package validation.
