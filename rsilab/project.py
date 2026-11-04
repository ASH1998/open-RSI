"""Explicit local workspace runtime; importing this module reads no credentials."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid


CACHE_PATHS = {
    "HF_HOME": ".cache/huggingface", "HF_HUB_CACHE": ".cache/huggingface/hub",
    "HUGGINGFACE_HUB_CACHE": ".cache/huggingface/hub", "TRANSFORMERS_CACHE": ".cache/huggingface/transformers",
    "XDG_CACHE_HOME": ".cache", "PIP_CACHE_DIR": ".cache/pip", "UV_CACHE_DIR": ".cache/uv",
    "TORCH_HOME": ".cache/torch", "TMPDIR": ".cache/tmp",
    "WANDB_DIR": "runs", "WANDB_CACHE_DIR": ".cache/wandb", "WANDB_CONFIG_DIR": ".config/wandb",
    "WANDB_DATA_DIR": "work/wandb", "WANDB_ARTIFACT_DIR": "artifacts", "KAGGLE_CONFIG_DIR": ".config/kaggle",
}
BASE_REPORT_FIELDS = frozenset({
    "run_id", "stage", "budget_reservation", "provenance", "started_at", "status",
    "wall_seconds", "budget", "error_type", "runtime_errors", "wandb_url", "modal_app_id",
})
SECRET_KEYS = frozenset({"api_key", "password", "secret", "credentials", "credential", "access_token",
                         "refresh_token", "token_secret", "authorization", "environment", "environ", "env"})
SECRET_ENV_KEYS = frozenset({"MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "WANDB_API_KEY", "KAGGLE_API_TOKEN",
                             "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "OPENAI_API_KEY", "AWS_ACCESS_KEY_ID",
                             "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"})


def _safe_type(error):
    name = type(error).__name__
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,79}", name) else "Exception"


def _identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", value):
        raise ValueError(f"Unsafe {label}")
    return value


def _wandb():
    import wandb
    return wandb


class StageError(RuntimeError):
    """Safe failure summary after attempting report, budget, and tracking cleanup."""

    def __init__(self, report):
        self.report = report
        super().__init__(f"Stage {report['run_id']} failed; inspect its local runtime_errors")


class Workspace:
    def __init__(self, root):
        supplied = Path(root).expanduser()
        if not supplied.is_absolute() or supplied.is_symlink() or not supplied.is_dir():
            raise ValueError("Workspace must be an explicit existing absolute directory")
        self.root = supplied.resolve(strict=True)
        self._configured = False

    def path(self, value) -> Path:
        """Resolve a path under this root; reject traversal and symlink components."""
        requested = Path(value)
        if ".." in requested.parts:
            raise ValueError("Workspace path traversal is forbidden")
        path = requested if requested.is_absolute() else self.root / requested
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            raise ValueError("Path is outside the explicit workspace") from None
        cursor = self.root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("Workspace-managed paths cannot contain symlinks")
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("Workspace path escapes its root")
        return path

    def load_env(self):
        """Load only root/.env, then force managed caches/config paths under root."""
        from dotenv import dotenv_values
        env_file = self.path(".env")
        values = dotenv_values(env_file, interpolate=False) if env_file.exists() else {}
        configured = values.get("RSI_PROJECT_ROOT", os.environ.get("RSI_PROJECT_ROOT"))
        if configured and Path(configured).expanduser().resolve() != self.root:
            raise ValueError("RSI_PROJECT_ROOT differs from the explicit workspace")
        paths = {key: self.path(relative) for key, relative in CACHE_PATHS.items()}
        for key in values:
            if key not in CACHE_PATHS and not key.startswith(("RSI_", "MODAL_", "WANDB_", "KAGGLE_", "HF_")):
                raise ValueError("Unsupported project environment key")
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True)
        for key, value in values.items():
            if value is not None and key not in CACHE_PATHS:
                os.environ[key] = value
        os.environ["RSI_PROJECT_ROOT"] = str(self.root)
        for key, path in paths.items():
            os.environ[key] = str(path)
        tempfile.tempdir = str(paths["TMPDIR"])
        os.environ.update(WANDB_CONSOLE="off", WANDB_DISABLE_CODE="true", WANDB_DISABLE_GIT="true")
        self._configured = True
        return self

    def read_json(self, path):
        return json.loads(self.path(path).read_text())

    def write_json(self, path, value):
        target = self.path(path)
        payload = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        self.path(target)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                             prefix=".rsilab-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            self.path(target)
            os.replace(temporary, target)
            descriptor = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return target

    def persist(self, report):
        run_id = _identifier(report.get("run_id"), "run ID")
        return self.write_json(Path("runs") / run_id / "report.json", report)

    def load_report(self, run_id, *, require_completed=True):
        _identifier(run_id, "run ID")
        report = self.read_json(Path("runs") / run_id / "report.json")
        if report.get("run_id") != run_id or (require_completed and report.get("status") != "completed"):
            raise ValueError("Run identity/status mismatch")
        return report

    @contextmanager
    def lock(self, name):
        _identifier(name, "lock name")
        path = self.path(Path("work/locks") / f"{name}.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _budget(self):
        from rsi.budget import Budget
        for path in ("config/budget.json", "budget/ledger.json", "budget/ledger.tmp", ".cache/budget.lock"):
            self.path(path)
        policy = self.read_json("config/budget.json")
        if (policy.get("currency") != "USD" or policy.get("provider") != "modal"
                or not 0 < policy.get("project_cap", 0) <= 250
                or not policy.get("overhead_reserve", 0) >= 25
                or not 0 < policy.get("max_stage_reservation", 0) <= 5):
            raise ValueError("Budget policy exceeds the authorized project bounds")
        return Budget(self.root)

    def reserve(self, name, requested_usd=5):
        _identifier(name, "stage name")
        if type(requested_usd) not in (int, float) or not math.isfinite(requested_usd) or not 0 < requested_usd <= 5:
            raise ValueError("Stage reservation must be positive and at most USD 5")
        return self._budget().reserve(name, requested_usd)

    def provenance(self, *, source_paths=(), source_hashes=None):
        from rsi.config import model_config
        sources = {}
        for name in tuple(source_paths) + tuple((source_hashes or {}).keys()):
            path = self.path(name)
            if path.name.startswith(".") or not path.is_file():
                raise ValueError("Source inventory requires explicit ordinary files")
            relative = str(path.relative_to(self.root))
            sources[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            if source_hashes is not None and name in source_hashes and source_hashes[name] != sources[relative]:
                raise ValueError("Explicit source digest differs from workspace file")
        commit = None
        try:
            top = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=self.root, text=True, stderr=subprocess.DEVNULL).strip()
            if Path(top).resolve() == self.root:
                commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.root, text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            pass
        return {"git_commit": commit, "source_hashes": sources, "model": model_config()}

    @contextmanager
    def stage(self, name, *, requested_usd=5, source_paths=(), source_hashes=None,
              report_fields=(), metric_keys=(), upload_paths=(), tracking_mode=None):
        """Yield (report, tracking); reserve before work, preserve all reservations."""
        if not self._configured:
            self.load_env()
        if (os.environ.get("RSI_PROJECT_ROOT") != str(self.root)
                or any(os.environ.get(key) != str(self.path(relative)) for key, relative in CACHE_PATHS.items())):
            raise ValueError("Workspace environment changed; configure this workspace before its stage")
        _identifier(name, "stage name")
        if len(name) > 100:
            raise ValueError("Stage name is too long")
        provenance = self.provenance(source_paths=source_paths, source_hashes=source_hashes)
        mode = tracking_mode or os.environ.get("WANDB_MODE", "offline")
        if mode not in {"online", "offline", "disabled"}:
            raise ValueError("Invalid tracking mode")
        tracking = TrackingRun(self, metric_keys=metric_keys, upload_paths=upload_paths, report_fields=report_fields)
        reservation = self.reserve(name, requested_usd)
        budget = self._budget()
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + name + "-" + uuid.uuid4().hex[:8]
        report = {"run_id": run_id, "stage": name, "budget_reservation": reservation,
                  "provenance": provenance, "started_at": datetime.now(timezone.utc).isoformat(), "status": "running"}
        started, errors = time.monotonic(), []

        def capture(phase, error):
            errors.append({"phase": phase, "error_type": _safe_type(error)})
            report.update(status="failed", error_type=errors[0]["error_type"], runtime_errors=list(errors))

        def attempt(phase, operation):
            try:
                return operation()
            except BaseException as error:
                capture(phase, error)
                return None

        interrupted = False
        phase = "initial_persist"
        try:
            self.persist(report)
            phase = "tracking_init"
            tracking.start(report, mode=mode, requested_usd=requested_usd)
            if tracking.url:
                report["wandb_url"] = tracking.url
            phase = "body"
            yield report, tracking
            report["status"] = "completed"
        except BaseException as error:
            interrupted = isinstance(error, (KeyboardInterrupt, SystemExit))
            capture(phase, error)
        finally:
            report["wall_seconds"] = time.monotonic() - started
            snapshot = attempt("budget_summary", budget.summary)
            if snapshot is not None:
                report["budget"] = snapshot
            attempt("terminal_persist", lambda: self.persist(report))
            if tracking.started:
                attempt("tracking_report", lambda: tracking.publish_report(report))
                attempt("tracking_finish", lambda: tracking.finish(report))
            status = "interrupted" if interrupted else ("failed" if errors else "completed")
            attempt("budget_finish", lambda: budget.finish(reservation, status, {
                "run_id": run_id, "wall_seconds": report["wall_seconds"],
                "error_type": report.get("error_type"), "app_id": report.get("modal_app_id")}))
            attempt("final_persist", lambda: self.persist(report))
        if errors:
            raise StageError(report) from None


class TrackingRun:
    """Small W&B facade: numeric metrics and explicitly selected JSON evidence."""

    def __init__(self, workspace, *, metric_keys, upload_paths, report_fields):
        self.workspace = workspace
        self.metric_keys = frozenset(metric_keys)
        self.report_fields = BASE_REPORT_FIELDS | frozenset(report_fields)
        if any(not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_./-]{0,119}", key) for key in self.metric_keys):
            raise ValueError("Invalid metric allowlist")
        if any(not isinstance(key, str) or not key or key.lower() in SECRET_KEYS for key in self.report_fields):
            raise ValueError("Invalid report field allowlist")
        self.upload_paths = frozenset(workspace.path(path) for path in upload_paths)
        if any(path.suffix != ".json" or any(part.startswith(".") for part in path.relative_to(workspace.root).parts)
               for path in self.upload_paths):
            raise ValueError("Tracking upload allowlist accepts ordinary JSON files only")
        self.run = self.sdk = None
        self.run_id = None
        self.started = False

    @property
    def entity(self):
        return self.run.entity if self.run else os.environ.get("WANDB_ENTITY")

    @property
    def project(self):
        return self.run.project if self.run else os.environ.get("WANDB_PROJECT")

    @property
    def url(self):
        return self.run.url if self.run else None

    def _clean(self, value):
        secrets = sorted({os.environ[key] for key in SECRET_ENV_KEYS if os.environ.get(key)}, key=len, reverse=True)

        def clean(item):
            if isinstance(item, dict):
                return {key: clean(value) for key, value in item.items()
                        if key.lower() not in SECRET_KEYS and key.upper() not in SECRET_ENV_KEYS
                        and not any(fragment in key.lower() for fragment in ("api_key", "password", "token_secret"))
                        and not key.lower().endswith(("_token", "_secret"))}
            if isinstance(item, (list, tuple)):
                return [clean(value) for value in item]
            if isinstance(item, str):
                for secret in secrets:
                    item = item.replace(secret, "[REDACTED]")
            return item
        return clean(value)

    def start(self, report, *, mode, requested_usd):
        self.run_id = report["run_id"]
        if mode == "disabled":
            self.started = True
            return
        entity, project = os.environ.get("WANDB_ENTITY"), os.environ.get("WANDB_PROJECT")
        if not entity or not project:
            raise ValueError("Explicit W&B entity/project required")
        self.sdk = _wandb()
        self.run = self.sdk.init(entity=entity, project=project, mode=mode, name=self.run_id,
            dir=str(self.workspace.path("runs")), job_type=report["stage"],
            tags=["verified-learning", "not-rsi-evidence"],
            config=self._clean({"model": report["provenance"]["model"], "stage": report["stage"],
                               "budget_reservation_usd": requested_usd, "git_commit": report["provenance"]["git_commit"]}),
            settings=self.sdk.Settings(disable_code=True, disable_git=True, x_disable_meta=True,
                                       x_disable_stats=True, console="off", init_timeout=45))
        self.started = True

    def log(self, metrics):
        if not isinstance(metrics, dict) or not set(metrics).issubset(self.metric_keys):
            raise ValueError("Metric is outside the explicit allowlist")
        if any(type(value) not in (int, float, bool) or not math.isfinite(value) for value in metrics.values()):
            raise ValueError("Tracking metrics must be finite numeric values")
        if self.run:
            self.run.log(metrics)

    def use_artifact(self, reference, *, type):
        if not isinstance(reference, str) or not reference.startswith(f"{self.entity}/{self.project}/"):
            raise ValueError("Artifact lineage must use the configured entity/project")
        if self.run:
            return self.run.use_artifact(reference, type=type)

    def _upload(self, value, *, artifact_name, artifact_type, name):
        _identifier(artifact_name, "artifact name")
        _identifier(artifact_type, "artifact type")
        _identifier(name, "artifact file name")
        if not name.endswith(".json"):
            raise ValueError("Artifact evidence must be JSON")
        if not self.run:
            return None
        path = self.workspace.write_json(Path("work/tracking") / self.run_id / artifact_name / name, self._clean(value))
        artifact = self.sdk.Artifact(artifact_name, type=artifact_type)
        artifact.add_file(str(path), name=name)
        return self.run.log_artifact(artifact)

    def upload_json(self, path, *, artifact_name, artifact_type, name="data.json"):
        path = self.workspace.path(path)
        if path not in self.upload_paths:
            raise ValueError("Artifact path is outside the explicit upload allowlist")
        return self._upload(self.workspace.read_json(path), artifact_name=artifact_name, artifact_type=artifact_type, name=name)

    def publish_report(self, report):
        from .core import digest
        if self.run:
            self.run.summary["status"] = report["status"]
            self.run.summary["wall_seconds"] = report["wall_seconds"]
        value = {key: report[key] for key in self.report_fields if key in report}
        value["local_report_sha256"] = digest(report)
        return self._upload(value,
                            artifact_name=self.run_id, artifact_type="pilot-report", name="report.json")

    def finish(self, report):
        if self.run:
            self.run.finish(exit_code=0 if report.get("status") == "completed" else 1)
