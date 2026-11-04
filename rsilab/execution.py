"""Bounded orchestration of trusted callbacks; this is not a code sandbox."""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
import re
from typing import Any, Callable, Iterable


def _exception_type(error: BaseException) -> str:
    name = type(error).__name__
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,79}", name) else "Exception"


@dataclass(frozen=True)
class ExecutionRecord:
    index: int
    item_id: str
    status: str  # returned, exception, cancelled, or not_started
    result: Any = None
    exception_type: str | None = None

    def to_dict(self) -> dict:
        return {"index": self.index, "item_id": self.item_id, "status": self.status,
                "result": self.result, "exception_type": self.exception_type}


@dataclass(frozen=True)
class ExecutionIssue:
    phase: str  # execute, persist, validate, submit, or abort
    index: int | None
    item_id: str | None
    exception_type: str | None = None

    def to_dict(self) -> dict:
        return {"phase": self.phase, "index": self.index, "item_id": self.item_id,
                "exception_type": self.exception_type}


@dataclass(frozen=True)
class ExecutionSummary:
    records: tuple[ExecutionRecord, ...]
    issues: tuple[ExecutionIssue, ...]
    submitted_ids: tuple[str, ...]
    missing_ids: tuple[str, ...]
    unpersisted_ids: tuple[str, ...]
    validated_ids: tuple[str, ...]

    @property
    def succeeded(self) -> bool:
        return not (self.issues or self.missing_ids or self.unpersisted_ids)

    def to_dict(self) -> dict:
        return {"records": [record.to_dict() for record in self.records],
                "issues": [issue.to_dict() for issue in self.issues],
                "submitted_ids": list(self.submitted_ids), "missing_ids": list(self.missing_ids),
                "unpersisted_ids": list(self.unpersisted_ids), "validated_ids": list(self.validated_ids),
                "succeeded": self.succeeded}


class ExecutionAborted(RuntimeError):
    """All submitted work was harvested; inspect summary for recovery evidence."""

    def __init__(self, summary: ExecutionSummary):
        self.summary = summary
        super().__init__(f"Execution stopped: {len(summary.issues)} issue(s), "
                         f"{len(summary.missing_ids)} missing, "
                         f"{len(summary.unpersisted_ids)} unpersisted")


def execute_bounded(
    items: Iterable[Any], *, identify: Callable[[Any], str],
    execute: Callable[[Any], Any], persist: Callable[[ExecutionRecord], None],
    validate: Callable[[Any, Any], None], max_workers: int = 4,
    max_in_flight: int | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> ExecutionSummary:
    """Persist and validate bounded results, draining all work after a failure.

    execute(item) runs in a worker thread. Other callbacks run serially in the
    caller. persist(record) must durably save evidence before returning; validate
    (item, result) must raise on invalid/infrastructure results and return None
    on acceptance. False is rejected, not silently interpreted as acceptance.

    No automatic retries occur, including on persistence failure. Result payloads
    are passed through unchanged; the caller owns their serialization/redaction.
    Exceptions contribute only a sanitized type name, never their message.
    """
    capacity = max_workers if max_in_flight is None else max_in_flight
    if type(max_workers) is not int or max_workers < 1:
        raise ValueError("max_workers must be a positive integer")
    if type(capacity) is not int or capacity < 1:
        raise ValueError("max_in_flight must be a positive integer")
    values = tuple(items)
    ids = []
    for item in values:
        try:
            item_id = identify(item)
        except BaseException as error:
            raise ValueError(f"identify failed: {_exception_type(error)}") from None
        if type(item_id) is not str or not item_id.strip() or item_id in ids:
            raise ValueError("Item identities must be unique nonempty strings")
        ids.append(item_id)
    records, issues, submitted, persisted, validated = {}, [], set(), set(), set()
    pending = {}
    stopped = False
    next_index = 0

    def fail(phase, index=None, error=None):
        nonlocal stopped
        stopped = True
        issues.append(ExecutionIssue(phase, index, ids[index] if index is not None else None,
                                     _exception_type(error) if error is not None else None))
        for future in pending:
            future.cancel()

    def check_abort():
        if stopped or should_abort is None:
            return
        try:
            requested = should_abort()
            if type(requested) is not bool:
                raise TypeError("should_abort must return bool")
        except BaseException as error:
            fail("abort", error=error)
        else:
            if requested:
                fail("abort")

    def save(record):
        records[record.index] = record
        try:
            persist(record)
        except BaseException as error:
            fail("persist", record.index, error)
            return False
        persisted.add(record.index)
        return True

    def harvest(future, index):
        if future.cancelled():
            save(ExecutionRecord(index, ids[index], "cancelled"))
            return
        try:
            result = future.result()
        except BaseException as error:
            # Stop/cancel immediately, but persist before considering more work.
            fail("execute", index, error)
            save(ExecutionRecord(index, ids[index], "exception", exception_type=_exception_type(error)))
            return
        record = ExecutionRecord(index, ids[index], "returned", result=result)
        if not save(record):
            return
        try:
            if validate(values[index], result) is not None:
                raise TypeError("validate must return None or raise")
        except BaseException as error:
            fail("validate", index, error)
        else:
            validated.add(index)

    # Running threads cannot be killed safely. Drain even after KeyboardInterrupt
    # or SystemExit in callbacks/wait; emit a summary exception only afterwards.
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="rsilab") as pool:
        while True:
            check_abort()
            while not stopped and next_index < len(values) and len(pending) < capacity:
                # Observe already completed failures before filling another slot.
                if any(future.done() for future in pending):
                    break
                index = next_index
                next_index += 1
                try:
                    future = pool.submit(execute, values[index])
                except BaseException as error:
                    fail("submit", index, error)
                    save(ExecutionRecord(index, ids[index], "not_started", exception_type=_exception_type(error)))
                    break
                submitted.add(index)
                pending[future] = index
                check_abort()
            if not pending:
                break
            # Inspect done() explicitly: cancelled queued futures may not yet be
            # notified by an executor worker, but still require durable records.
            done = {future for future in pending if future.done()}
            if not done:
                try:
                    done, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                except BaseException as error:
                    fail("abort", error=error)
                    continue
            for future in sorted(done, key=pending.__getitem__):
                index = pending.pop(future)
                harvest(future, index)
            if stopped:
                for future in pending:
                    future.cancel()
    ordered = tuple(records[index] for index in sorted(records))
    summary = ExecutionSummary(
        records=ordered,
        issues=tuple(sorted(issues, key=lambda issue: (-1 if issue.index is None else issue.index, issue.phase))),
        submitted_ids=tuple(ids[index] for index in sorted(submitted)),
        missing_ids=tuple(item_id for index, item_id in enumerate(ids)
                          if index not in records or records[index].status in {"cancelled", "not_started"}),
        unpersisted_ids=tuple(ids[index] for index in sorted(set(records) - persisted)),
        validated_ids=tuple(ids[index] for index in sorted(validated)),
    )
    if not summary.succeeded:
        raise ExecutionAborted(summary) from None
    return summary
