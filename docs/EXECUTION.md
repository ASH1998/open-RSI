# Bounded execution and durable failure records

`rsilab.execution.execute_bounded` runs trusted execution callbacks with a bounded
thread pool and saves every harvested result before validating it. It starts no
provider job on its own and provides no isolation for generated code. A controller
can use it to schedule an independently authorized remote verifier; candidate
programs must still run in their designated sandboxes.

```python
execute_bounded(
    items,
    identify=lambda item: item["id"],
    execute=execute_item,
    persist=persist_record,
    validate=validate_result,
    max_workers=4,
    max_in_flight=None,  # Defaults to max_workers, including queued work.
    should_abort=None,  # Optional zero-argument bool callback.
)
```

Inputs are materialized and their unique, nonempty string identities are checked
before work starts. Input order assigns stable zero-based indices. The two limits
must be positive integers; a smaller `max_in_flight` also limits concurrency.
The helper never retries work or persistence automatically.

## Callbacks

`execute(item) -> result` runs in a worker thread. Return JSON-compatible evidence,
including ordinary model failures and structured infrastructure failures. The
helper preserves the payload without inspecting its meaning. Raised exceptions
become failure records with only a sanitized exception class name; no exception
message, traceback, or exception object is included in the record or summary.

`persist(record: ExecutionRecord) -> None` runs serially in the caller thread.
Use `record.to_dict()` to obtain its JSON-compatible envelope. The callback must
durably save the record before returning, for example by completing an atomic
file replacement or appending, flushing, and syncing a journal. The helper treats
a normal return as the persistence acknowledgement; it cannot verify the storage
backend's durability. A callback that fails after writing may already have saved
data, so use `(run_id, index, item_id)` to reconcile any later manual recovery.

`validate(item, result) -> None` runs in the caller thread only after persistence
acknowledges a returned result. Raise on infrastructure failure or invalid
evidence. Ordinary model test failures can remain valid results. Acceptance must
return `None`; returning `False` or another value is rejected as `TypeError`.
Worker exceptions, cancelled work, and records whose persistence failed never
reach validation. Callbacks must not mutate the input identity or result payload.

`should_abort() -> bool` runs in the caller thread before work begins, between
submissions, and while waiting. A true result or exception requests shutdown.
Waiting polls at most every 0.1 seconds, apart from callback execution time.

Result payloads and item IDs are caller-supplied evidence, not automatically
redacted. Keep credentials out of them. The safe exception handling applies to
raised errors; it cannot sanitize arbitrary data intentionally returned by a
callback. JSON compatibility of those payloads is also the caller's contract.

## Failure and shutdown

The first observed execution, persistence, validation, submission, or abort
failure stops submission. Queued futures are cancelled where possible. Every
already running or completed future is then harvested, with persistence attempted
once per record even when earlier persistence failed. Returned results are still
validated after successful persistence during this drain. Additional failures
are collected rather than replacing the first one.

Completion races can allow queued work to start before cancellation. Such work
is drained too. Running Python threads cannot be forcibly stopped safely, so
`execute` must enforce its own remote-operation timeout and cleanup. A hung
execution or storage callback can delay shutdown; this helper does not claim a
hard wall-time bound or terminate remote work. A `KeyboardInterrupt`/`SystemExit`
raised by a callback or the wait operation also triggers draining and ultimately
becomes `ExecutionAborted`, rather than being raised immediately. Process death
or interruption outside these guarded operations cannot guarantee harvesting.

Persistence callbacks run in observed completion order, with input index breaking
ties in a harvested batch. Waiting for input order would delay saving results
behind slow workers. The final record list, ID lists, and issue ordering are
deterministic by input index (issues then sort by phase); scheduling itself is not
deterministic.

## Records and summaries

`ExecutionRecord.to_dict()` returns:

```json
{
  "index": 0,
  "item_id": "task-0",
  "status": "returned",
  "result": {"passed": false, "infrastructure_error": false},
  "exception_type": null
}
```

Statuses are `returned`, `exception`, `cancelled`, and `not_started` (submission
failed). Non-returned records have a null result. Exception/submission failures
carry a safe exception type. Returned `null` is distinguishable by its status.

On success the helper returns `ExecutionSummary`. On failure it raises
`ExecutionAborted` only after draining; the same summary is available through
`error.summary`. `summary.to_dict()` contains:

- `records`: all harvested outcome envelopes, including outcomes whose storage
  callback failed. Never-submitted items have no outcome envelope.
- `issues`: objects with `phase`, `index`, `item_id`, and `exception_type`.
  Phases are `execute`, `persist`, `validate`, `submit`, or `abort`. Global aborts
  have null index/ID; an explicit boolean abort has no exception type.
- `submitted_ids`: successfully submitted items, including cancelled futures.
- `missing_ids`: cancelled, submission-failed, and never-submitted items. A
  harvested execution exception is recorded failure evidence, not a missing ID.
- `unpersisted_ids`: records whose persistence callback raised. They remain in
  `records` for fallback storage; no persistence retry was attempted.
- `validated_ids`: returned results accepted by validation after persistence.
- `succeeded`: true only when no issues, missing IDs, or unpersisted IDs exist.

An empty input succeeds unless an abort is requested. Invalid limits or identities
raise `ValueError` before execution. Iterator failures and executor-construction
failures also occur before any work is submitted.

A controller should save the aggregate summary, including on failure:

```python
from rsilab.execution import ExecutionAborted, execute_bounded

try:
    summary = execute_bounded(
        items, identify=lambda item: item["id"], execute=verify_remotely,
        persist=persist_record, validate=check_infrastructure, max_workers=4,
    )
except ExecutionAborted as error:
    save_fallback_report(error.summary.to_dict())
    raise
else:
    save_completed_report(summary.to_dict())
```

Both report writers are controller-owned durable operations. If fallback storage
also fails, the controller must surface that failure; the in-memory summary is
not a durable substitute.

## Verification and handoff

Run from the SSD project root:

```sh
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p test_execution.py -v
```

Tests use injected trusted functions, events/barriers, synthetic failures, and
SSD-local journals. They cover persistence-before-validation, complete draining,
queue cancellation, safe exception records, storage failures without retry,
interrupt/abort handling, ordinary model failures, and deterministic summaries.
No candidate code or provider service is executed. This helper is separate from
the frozen evaluator/controller/rescore sources. Integration into the new
robustness controller is the next milestone; packaging is not changed here.

Handoff verification: all 15 execution tests passed, and all execution-source
checksums in `studies/mbpp_rescore_v2/protocol.json` remained unchanged. No paid
calls, dependency installations, or edits outside these three new files were
performed for this work.

## Local package 0.1.2

The bounded execution helper is packaged and installed as `rsilab 0.1.2` in
the SSD-local `.venv`. Packaging changed only the two version declarations and
this appendix; helper, controller, case, and frozen evaluator source files were
not edited. There was no dependency download, paid job, or package publication.

- Wheel: `work/robustness-framework-dist/rsilab-0.1.2-py3-none-any.whl`
  (94,435 bytes).
- SHA-256: `7472b2512f8b3c8842fba81a4a03a36d91a9c205f0dc963d5c76cf0ba1823ce1`.
- Source staging: `work/robustness-framework-source/`, copied from an explicit
  allowlist. It includes the previous package modules plus `rsilab/execution.py`,
  `rsi/mbpp_robustness.py`, and `rsi/robustness_study.py`.
- Audit: `work/robustness-framework-dist/wheel-audit.json` records the exact
  source allowlist and hashes, archive inventory, prior-wheel checksums, and
  installed validation results.
- Test log: `work/robustness-framework-dist/installed-tests.log`.

All 15 execution tests passed under isolated Python against the installed wheel,
with network calls blocked and checkout package imports excluded. Validation
also checked version metadata, core/execution/rescore/v2/robustness imports,
every installed package file's checksum, and agreement with the frozen diagnostic
source inventory. No provider or ML-library modules were imported. The original
rescore source hashes remained unchanged.

Both prior wheels were preserved byte-for-byte:

| Version | Path | SHA-256 |
| --- | --- | --- |
| 0.1.0 | `work/framework-dist/rsilab-0.1.0-py3-none-any.whl` | `985a5a2a7b27874057a62ae862b1ebc306148cd373a26a30cd2c523538593551` |
| 0.1.1 | `work/rescore-framework-dist/rsilab-0.1.1-py3-none-any.whl` | `3b72462b4b0a33101101831a9a2dec38ba335ca4bc97f6f44283719958af66ba` |

These installed tests validate local orchestration behavior, not remote verifier
results. The main controller remains responsible for the authorized diagnostic
run and durable experiment reports.
