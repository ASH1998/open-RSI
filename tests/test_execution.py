"""Bounded execution tests use trusted callbacks only, with no provider calls."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from rsilab.execution import ExecutionAborted, execute_bounded

ROOT = Path(__file__).resolve().parents[1]


class ExecutionTests(unittest.TestCase):
    def run_items(self, items, **kwargs):
        options = dict(identify=str, execute=lambda item: {"value": item},
                       persist=lambda record: None, validate=lambda item, result: None)
        options.update(kwargs)
        return execute_bounded(items, **options)

    def test_durable_records_precede_validation_and_round_trip(self):
        (ROOT / "work").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "work", prefix="execution-test-") as directory:
            path = Path(directory) / "records.jsonl"
            caller = threading.get_ident()
            def persist(record):
                self.assertEqual(threading.get_ident(), caller)
                with path.open("a") as stream:
                    stream.write(json.dumps(record.to_dict()) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            def validate(item, result):
                self.assertEqual(threading.get_ident(), caller)
                saved = [json.loads(line) for line in path.read_text().splitlines()]
                self.assertIn(str(item), [record["item_id"] for record in saved])
            summary = self.run_items(range(8), persist=persist, validate=validate, max_workers=2)
            self.assertTrue(summary.succeeded)
            self.assertEqual([record.index for record in summary.records], list(range(8)))
            self.assertEqual(summary.validated_ids, tuple(map(str, range(8))))
            self.assertEqual(json.loads(json.dumps(summary.to_dict()))["missing_ids"], [])

    def test_failure_drains_other_running_result_and_never_submits_remainder(self):
        other_started, release = threading.Event(), threading.Event()
        saved = []
        def execute(item):
            if item == 0:
                self.assertTrue(other_started.wait(2))
                raise ConnectionError("secret-provider-token")
            other_started.set()
            self.assertTrue(release.wait(2))
            return {"ok": True}
        def persist(record):
            saved.append(record)
            if record.status == "exception":
                release.set()
        with self.assertRaises(ExecutionAborted) as caught:
            self.run_items(range(5), execute=execute, persist=persist, max_workers=2)
        summary = caught.exception.summary
        self.assertEqual([record.item_id for record in saved], ["0", "1"])
        self.assertEqual(summary.submitted_ids, ("0", "1"))
        self.assertEqual(summary.missing_ids, ("2", "3", "4"))
        self.assertEqual(summary.records[0].exception_type, "ConnectionError")
        self.assertNotIn("secret-provider-token", json.dumps(summary.to_dict()) + str(caught.exception))

    def test_infrastructure_return_is_saved_before_validation_stops_work(self):
        saved, validated = [], []
        def validate(item, result):
            self.assertEqual(saved[-1].result, result)
            validated.append(item)
            if result["infrastructure_error"]:
                raise RuntimeError("raw-secret-in-validation-error")
        with self.assertRaises(ExecutionAborted) as caught:
            self.run_items(range(3), max_workers=1,
                           execute=lambda item: {"infrastructure_error": True},
                           persist=saved.append, validate=validate)
        summary = caught.exception.summary
        self.assertEqual(len(saved), 1)
        self.assertEqual(validated, [0])
        self.assertEqual(summary.issues[0].phase, "validate")
        self.assertEqual(summary.missing_ids, ("1", "2"))
        self.assertNotIn("raw-secret", json.dumps(summary.to_dict()))

    def test_persistence_failure_retains_record_and_drains_other_running_error(self):
        other_started, release = threading.Event(), threading.Event()
        attempts, validated = [], []
        def execute(item):
            if item == 0:
                self.assertTrue(other_started.wait(2))
                return {"evidence": "first result"}
            other_started.set()
            self.assertTrue(release.wait(2))
            raise OSError("secret-worker-error")
        def persist(record):
            attempts.append(record.item_id)
            if record.item_id == "0":
                release.set()
                raise OSError("secret-storage-error")
        with self.assertRaises(ExecutionAborted) as caught:
            self.run_items(range(4), execute=execute, persist=persist, max_workers=2,
                           validate=lambda item, result: validated.append(item))
        summary = caught.exception.summary
        self.assertEqual(attempts, ["0", "1"])
        self.assertEqual(validated, [])
        self.assertEqual(summary.unpersisted_ids, ("0",))
        self.assertEqual(summary.records[0].result, {"evidence": "first result"})
        self.assertEqual(summary.records[1].exception_type, "OSError")
        self.assertEqual(summary.missing_ids, ("2", "3"))
        self.assertNotIn("secret-", json.dumps(summary.to_dict()))

    def test_explicit_abort_cancels_queue_but_harvests_running_worker(self):
        started, release = threading.Event(), threading.Event()
        polls, called, saved = [], [], []
        def execute(item):
            called.append(item)
            started.set()
            self.assertTrue(release.wait(2))
            return item
        def abort():
            polls.append(True)
            if len(polls) == 2:
                self.assertTrue(started.wait(2))
            return len(polls) >= 5  # initial poll plus four submissions
        def persist(record):
            saved.append(record)
            if record.status == "cancelled":
                release.set()
        with self.assertRaises(ExecutionAborted) as caught:
            self.run_items(range(7), execute=execute, persist=persist, should_abort=abort,
                           max_workers=1, max_in_flight=4)
        summary = caught.exception.summary
        self.assertEqual(called, [0])
        self.assertEqual(summary.submitted_ids, ("0", "1", "2", "3"))
        self.assertEqual([record.status for record in summary.records],
                         ["returned", "cancelled", "cancelled", "cancelled"])
        self.assertEqual(summary.missing_ids, tuple(map(str, range(1, 7))))
        self.assertEqual(len(saved), 4)

    def test_abort_before_submission_records_all_missing(self):
        with self.assertRaises(ExecutionAborted) as caught:
            self.run_items(["a", "b"], should_abort=lambda: True)
        self.assertEqual(caught.exception.summary.submitted_ids, ())
        self.assertEqual(caught.exception.summary.missing_ids, ("a", "b"))

    def test_wait_interrupt_drains_then_raises_summary(self):
        release = threading.Event()
        def execute(item):
            self.assertTrue(release.wait(2))
            return item
        def interrupt(*args, **kwargs):
            release.set()
            raise KeyboardInterrupt("secret-interrupt")
        with patch("rsilab.execution.wait", side_effect=interrupt):
            with self.assertRaises(ExecutionAborted) as caught:
                self.run_items([0, 1], execute=execute, max_workers=1)
        summary = caught.exception.summary
        self.assertEqual(summary.records[0].status, "returned")
        self.assertEqual(summary.issues[0].exception_type, "KeyboardInterrupt")
        self.assertEqual(summary.missing_ids, ("1",))

    def test_worker_base_exception_is_safe_and_never_validated(self):
        class UnsafeError(BaseException):
            def __str__(self):
                raise AssertionError("Exception text must never be inspected")
        def execute(item):
            raise UnsafeError()
        saved = []
        with self.assertRaises(ExecutionAborted) as caught:
            self.run_items([0], execute=execute, persist=saved.append,
                           validate=lambda *args: self.fail("exception was validated"))
        self.assertEqual(saved[0].exception_type, "UnsafeError")
        self.assertEqual(caught.exception.summary.issues[0].phase, "execute")

    def test_false_validation_return_is_rejected(self):
        with self.assertRaises(ExecutionAborted) as caught:
            self.run_items([0], validate=lambda *args: False)
        self.assertEqual(caught.exception.summary.issues[0].exception_type, "TypeError")

    def test_model_failure_is_valid_evidence_and_does_not_abort(self):
        def validate(item, result):
            if result["infrastructure_error"]:
                raise RuntimeError()
        summary = self.run_items(range(3), validate=validate,
                                 execute=lambda item: {"passed": False, "infrastructure_error": False})
        self.assertTrue(summary.succeeded)
        self.assertEqual(len(summary.records), 3)

    def test_every_persistence_failure_is_retained_without_retry(self):
        barrier = threading.Barrier(2)
        attempts = []
        def execute(item):
            barrier.wait(timeout=2)
            return {"item": item}
        def persist(record):
            attempts.append(record.item_id)
            raise OSError("storage-secret")
        with self.assertRaises(ExecutionAborted) as caught:
            self.run_items(range(4), execute=execute, persist=persist, max_workers=2)
        summary = caught.exception.summary
        self.assertEqual(sorted(attempts), ["0", "1"])
        self.assertEqual(summary.unpersisted_ids, ("0", "1"))
        self.assertEqual([record.result for record in summary.records], [{"item": 0}, {"item": 1}])
        self.assertEqual(summary.missing_ids, ("2", "3"))

    def test_abort_callback_exception_is_safe(self):
        def abort():
            raise RuntimeError("abort-secret")
        with self.assertRaises(ExecutionAborted) as caught:
            self.run_items([0], should_abort=abort)
        summary = caught.exception.summary
        self.assertEqual(summary.issues[0].phase, "abort")
        self.assertEqual(summary.issues[0].exception_type, "RuntimeError")
        self.assertNotIn("abort-secret", json.dumps(summary.to_dict()))

    def test_invalid_limits_and_duplicate_ids_do_no_work(self):
        called = []
        for options in ({"max_workers": 0}, {"max_workers": True}, {"max_in_flight": 0}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_items([0], execute=called.append, **options)
        with self.assertRaises(ValueError):
            self.run_items([0, 0], execute=called.append)
        self.assertEqual(called, [])

    def test_empty_input_succeeds(self):
        summary = self.run_items([])
        self.assertTrue(summary.succeeded)
        self.assertEqual(summary.records, ())

    def test_completion_order_does_not_change_summary_identity(self):
        second, release = threading.Event(), threading.Event()
        saved = []
        def execute(item):
            if item == "first":
                self.assertTrue(release.wait(2))
            else:
                second.set()
            return item
        def persist(record):
            saved.append(record.item_id)
            if record.item_id == "second":
                self.assertTrue(second.is_set())
                release.set()
        summary = self.run_items(["first", "second"], execute=execute, persist=persist, max_workers=2)
        self.assertEqual(saved, ["second", "first"])
        self.assertEqual([record.item_id for record in summary.records], ["first", "second"])


if __name__ == "__main__":
    unittest.main()
