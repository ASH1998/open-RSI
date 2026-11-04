"""Workspace tests use SSD-local fixtures, synthetic secrets, and fake tracking."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rsilab.project import CACHE_PATHS, StageError, Workspace

ROOT = Path(__file__).resolve().parents[1]


class FakeArtifact:
    def __init__(self, name, *, type):
        self.name, self.type, self.files = name, type, []

    def add_file(self, path, *, name):
        self.files.append((name, json.loads(Path(path).read_text())))


class FakeRun:
    entity, project, url = "test-entity", "test-project", "https://tracking.invalid/run"

    def __init__(self):
        self.summary, self.logs, self.artifacts, self.finishes, self.lineage = {}, [], [], [], []

    def log(self, values): self.logs.append(values)
    def log_artifact(self, artifact): self.artifacts.append(artifact); return self
    def wait(self): return self
    def finish(self, *, exit_code): self.finishes.append(exit_code)
    def use_artifact(self, reference, *, type): self.lineage.append((reference, type)); return self


class FakeSDK:
    Artifact = FakeArtifact
    Settings = staticmethod(lambda **kwargs: kwargs)

    def __init__(self): self.run, self.calls = FakeRun(), []
    def init(self, **kwargs): self.calls.append(kwargs); return self.run


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "work").mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / "work", prefix="workspace-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)
        old_tempdir = tempfile.tempdir
        self.addCleanup(setattr, tempfile, "tempdir", old_tempdir)
        self.workspace = Workspace(self.root)
        self.workspace.write_json("config/budget.json", {"currency": "USD", "provider": "modal", "project_cap": 250,
            "overhead_reserve": 25, "max_stage_reservation": 5, "prefix_reservation_caps": {"study-": 10}})
        self.workspace.write_json("budget/ledger.json", {"reservations": []})
        (self.root / ".env").write_text("RSI_MODEL_ID=test/model\nRSI_MODEL_REVISION=" + "a"*40 +
            "\nWANDB_ENTITY=test-entity\nWANDB_PROJECT=test-project\nWANDB_MODE=offline\nWANDB_API_KEY=synthetic-secret-value\n")
        (self.root / "worker.py").write_text("# explicit source\n")
        self.sdk = FakeSDK()
        self.sdk_patch = patch("rsilab.project._wandb", return_value=self.sdk)
        self.sdk_patch.start(); self.addCleanup(self.sdk_patch.stop)

    def test_load_env_uses_only_explicit_root_and_configures_every_cache(self):
        self.workspace.load_env()
        self.assertEqual(os.environ["WANDB_API_KEY"], "synthetic-secret-value")
        self.assertEqual(os.environ["RSI_PROJECT_ROOT"], str(self.root))
        self.assertEqual(tempfile.gettempdir(), str(self.root / ".cache/tmp"))
        for key, relative in CACHE_PATHS.items():
            self.assertEqual(os.environ[key], str(self.root / relative))
            self.assertTrue((self.root / relative).is_dir())
        self.assertEqual(os.environ["WANDB_DISABLE_CODE"], "true")
        self.assertEqual(os.environ["WANDB_CONSOLE"], "off")

    def test_no_parent_dotenv_discovery_or_system_environment_changes(self):
        nested = self.root / "nested"
        nested.mkdir()
        Workspace(nested).load_env()
        self.assertNotIn("WANDB_API_KEY", os.environ)
        self.assertEqual(os.environ["PATH"], "/usr/bin:/bin")

    def test_missing_relative_and_symlink_roots_rejected(self):
        for root in ("relative", self.root / "missing"):
            with self.assertRaises(ValueError): Workspace(root)
        link = self.root / "alias"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError): Workspace(link)

    def test_mismatched_root_and_symlink_cache_rejected_before_env_apply(self):
        (self.root / ".env").write_text("RSI_PROJECT_ROOT=/not-this-workspace\n")
        with self.assertRaisesRegex(ValueError, "differs"): self.workspace.load_env()
        self.assertNotIn("RSI_PROJECT_ROOT", os.environ)
        (self.root / ".env").write_text("WANDB_API_KEY=synthetic\n")
        (self.root / ".cache").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlinks"): self.workspace.load_env()
        self.assertNotIn("WANDB_API_KEY", os.environ)

    def test_unsafe_run_id_paths_and_environment_keys_rejected(self):
        for run_id in ("../escape", "/absolute", ".", "bad/name", ""):
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                self.workspace.persist({"run_id": run_id})
        for path in ("../escape.json", "/outside.json"):
            with self.assertRaises(ValueError): self.workspace.write_json(path, {})
        (self.root / ".env").write_text("HOME=/somewhere\n")
        with self.assertRaisesRegex(ValueError, "Unsupported"): self.workspace.load_env()

    def test_atomic_persistence_preserves_previous_report_on_replace_failure(self):
        self.workspace.persist({"run_id": "safe", "status": "completed", "value": 1})
        with patch("rsilab.project.os.replace", side_effect=OSError("synthetic storage failure")):
            with self.assertRaises(OSError):
                self.workspace.persist({"run_id": "safe", "status": "completed", "value": 2})
        self.assertEqual(self.workspace.load_report("safe")["value"], 1)
        self.assertEqual(list((self.root / "runs/safe").glob(".rsilab-*.tmp")), [])

    def test_stage_success_tracks_allowlisted_json_and_reserves_explicit_root(self):
        self.workspace.write_json("data/selected.json", {"data": [1], "api_key": "do-not-upload"})
        with self.workspace.stage("study-collect", source_paths=["worker.py"], metric_keys=["data/count"],
                                  report_fields=["selected"], upload_paths=["data/selected.json"]) as (report, tracking):
            self.assertEqual(self.workspace.read_json("budget/ledger.json")["reservations"][0]["status"], "reserved")
            report.update(selected={"count": 1, "message": "value synthetic-secret-value", "password": "hidden"},
                          unlisted="never-upload", environment={"WANDB_API_KEY": "never-upload"})
            tracking.log({"data/count": 1})
            tracking.upload_json("data/selected.json", artifact_name="selected", artifact_type="verified-data").wait()
            tracking.use_artifact("test-entity/test-project/prior:latest", type="pilot-report")
        saved = self.workspace.load_report(report["run_id"])
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["provenance"]["source_hashes"]["worker.py"], hashlib.sha256((self.root / "worker.py").read_bytes()).hexdigest())
        self.assertIsNone(saved["provenance"]["git_commit"])  # Never substitute the parent checkout's commit.
        self.assertEqual(self.workspace.read_json("budget/ledger.json")["reservations"][0]["status"], "completed")
        artifact = self.sdk.run.artifacts[-1]
        self.assertEqual(artifact.type, "pilot-report")
        uploaded = artifact.files[0][1]
        self.assertNotIn("unlisted", uploaded)
        self.assertNotIn("environment", uploaded)
        self.assertNotIn("password", uploaded["selected"])
        self.assertIn("[REDACTED]", uploaded["selected"]["message"])
        self.assertNotIn("synthetic-secret-value", json.dumps([a.files for a in self.sdk.run.artifacts]))
        self.assertEqual(self.sdk.run.finishes, [0])
        self.assertEqual(self.sdk.calls[0]["settings"]["console"], "off")

    def test_safe_body_failure_survives_tracking_cleanup_failure(self):
        with patch.object(self.sdk.run, "log_artifact", side_effect=OSError("tracking-secret")):
            with self.assertRaises(StageError) as caught:
                with self.workspace.stage("study-fail") as (report, tracking):
                    raise RuntimeError("body-secret")
        report = caught.exception.report
        self.assertEqual(report["error_type"], "RuntimeError")
        self.assertEqual([row["phase"] for row in report["runtime_errors"]], ["body", "tracking_report"])
        self.assertEqual(self.workspace.load_report(report["run_id"], require_completed=False)["status"], "failed")
        self.assertEqual(self.sdk.run.finishes, [1])
        reservation = self.workspace.read_json("budget/ledger.json")["reservations"][0]
        self.assertEqual((reservation["status"], reservation["reserved_usd"]), ("failed", 5))
        self.assertNotIn("body-secret", json.dumps(report) + str(caught.exception))
        self.assertNotIn("tracking-secret", json.dumps(report))

    def test_tracking_initialization_failure_never_enters_body_and_finishes_budget(self):
        with patch.object(self.sdk, "init", side_effect=ConnectionError("credential-secret")):
            with self.assertRaises(StageError) as caught:
                with self.workspace.stage("study-init"):
                    self.fail("body entered")
        self.assertEqual(caught.exception.report["runtime_errors"][0]["phase"], "tracking_init")
        self.assertEqual(self.workspace.read_json("budget/ledger.json")["reservations"][0]["status"], "failed")

    def test_interrupt_finalizes_as_interrupted(self):
        with self.assertRaises(StageError):
            with self.workspace.stage("study-interrupt", tracking_mode="disabled"):
                raise KeyboardInterrupt("do-not-log")
        self.assertEqual(self.workspace.read_json("budget/ledger.json")["reservations"][0]["status"], "interrupted")

    def test_budget_and_source_validation_precede_tracking(self):
        for amount in (6, 0, True, float("nan")):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.workspace.reserve("study-bad", amount)
        with self.assertRaisesRegex(ValueError, "digest"):
            with self.workspace.stage("study-source", source_hashes={"worker.py": "0" * 64}): pass
        self.assertEqual(self.workspace.read_json("budget/ledger.json")["reservations"], [])
        self.assertEqual(self.sdk.calls, [])
        for index in range(2): self.workspace.reserve(f"study-{index}")
        from rsi.budget import BudgetExceeded
        with self.assertRaises(BudgetExceeded): self.workspace.reserve("study-over")

    def test_unlisted_uploads_metrics_and_credentials_are_rejected(self):
        with self.workspace.stage("study-allow", metric_keys=["loss"], tracking_mode="disabled") as (report, tracking):
            with self.assertRaises(ValueError): tracking.log({"other": 1})
            with self.assertRaises(ValueError): tracking.log({"loss": "secret"})
            with self.assertRaises(ValueError): tracking.upload_json("config/budget.json", artifact_name="x", artifact_type="x")
            with self.assertRaises(ValueError): tracking.use_artifact("other/project/run:latest", type="pilot-report")
        self.assertEqual(self.sdk.calls, [])

    def test_changed_environment_and_symlink_budget_fail_closed(self):
        self.workspace.load_env()
        os.environ["TMPDIR"] = "/outside"
        with self.assertRaisesRegex(ValueError, "environment changed"):
            with self.workspace.stage("study-env"): pass
        (self.root / "budget/ledger.json").unlink()
        (self.root / "budget/ledger.json").symlink_to(self.root / "config/budget.json")
        with self.assertRaisesRegex(ValueError, "symlinks"): self.workspace.reserve("study-link")

    def test_lock_is_explicit_workspace_local(self):
        with self.workspace.lock("study"):
            self.assertTrue((self.root / "work/locks/study.lock").is_file())
        with self.assertRaises(ValueError):
            with self.workspace.lock("../escape"): pass


if __name__ == "__main__": unittest.main()
