# Explicit workspace runtime

`rsilab.project.Workspace(root)` provides root-relative environment setup,
atomic JSON persistence, locks, budget reservations, and tracked stage lifecycle.
It never derives the project directory from an installed package's location.
Importing the module reads no `.env`, initializes no tracking service, and starts
no compute. Construct it with an existing absolute directory; a missing SSD is
an error, not a reason to create a replacement checkout.

```python
from rsilab.project import Workspace

workspace = Workspace("/Volumes/DevSSDWD/openbmb/rsi").load_env()
workspace.persist(report)  # runs/<safe-run-id>/report.json
saved = workspace.load_report(report["run_id"])
```

## Environment and paths

`load_env()` reads only the explicit root's `.env`, without searching parent
directories or interpolating variables from the surrounding environment.
`RSI_PROJECT_ROOT`, if configured, must resolve to this root. Project/provider
keys beginning `RSI_`, `MODAL_`, `WANDB_`, `KAGGLE_`, or `HF_` are accepted, along
with the managed cache keys. System keys such as `HOME` and `PATH` are rejected.
No credential is written to a home-directory configuration file.

The method creates and forces all managed cache/config locations under the root:
Hugging Face/model caches, XDG, pip, uv, Torch, temporary files, W&B runs/cache/
configuration/data/artifacts, and Kaggle configuration. It also resets Python's
cached temporary-directory choice to the project temp directory. W&B console,
automatic code, and Git capture are disabled. The map is exported as
`CACHE_PATHS`; no complete environment dump is recorded or uploaded.

Environment variables and Python's temporary-directory setting are process-wide.
Use separate processes for concurrent workspaces. A stage refuses to proceed if
its configured root/cache environment has changed. `load_env()` can be called
explicitly again after restoring the intended configuration. Runtime dotenv
loading uses the existing `python-dotenv` tool dependency; no dependency is
installed automatically.

`path(value)` accepts a relative path or an absolute path inside the root. It
rejects traversal, paths outside the root, and symlink components. The root must
already exist and cannot itself be a symlink. These checks assume a trusted local
workspace; they are not a defense against an adversary racing filesystem changes.

`read_json(path)` and `write_json(path, value)` use these checks. Writes serialize
finite JSON before replacing anything, create a unique temporary file beside the
destination, flush/sync it, atomically replace the destination, and sync the
directory. A failed replacement leaves the previous file intact and removes its
temporary file. `persist(report)` additionally validates the run ID and always
writes `runs/<id>/report.json`. `load_report(id, require_completed=True)` checks
both stored identity and completion status.

`lock(name)` is a blocking, process-level advisory lock under `work/locks/`.
Controllers that need fail-fast admission may retain their own explicitly rooted
nonblocking lock. Neither lock authorizes paid work.

## Budgeted tracked stages

```python
with workspace.stage(
    "verified-sft-v1-collect",
    requested_usd=5,
    source_paths=("rsilab/workflow.py", "rsi/verified_study.py"),
    report_fields=("protocol_sha256", "records", "scores"),
    metric_keys=("dev/pass_rate",),
    upload_paths=("data/audited-dataset.json",),
    tracking_mode="online",
) as (report, tracking):
    # Controller owns authorized provider execution and resource cleanup.
    report["protocol_sha256"] = frozen_protocol_sha256
    workspace.persist(report)
    tracking.log({"dev/pass_rate": 0.5})
```

`stage` yields `(report, tracking)` using the established report shape. It adds
run/stage IDs, reservation ID, start time, model and source provenance, status,
wall time, budget summary, and W&B URL when available. Run IDs and stage names are
restricted to safe identifiers.

Reservations use `rsi.budget.Budget(root)` with the explicit root, never its
captured default. Existing policy and ledger files are required; the runtime
does not initialize or enlarge them. It rejects stage requests above USD 5 and
policies above the authorized USD 250 project cap, below USD 25 overhead, or above
USD 5 per stage. The existing budget implementation atomically enforces total and
configured prefix caps. Controllers must separately enforce their preregistered
experiment scope, no-retry rules, and the current USD 20 experiment envelope.

The reservation is recorded before the body or tracking initialization. Success,
failure, and interruption retain the reservation; none is treated as a refund or
invoice total. `reserve(name, requested_usd=5)` also exposes this operation without
starting tracking or compute. Reservations are not automatic permission to launch
an otherwise unauthorized job.

Provenance uses `rsi.config.model_config()` only for its pure environment-based
model identity check. Git commands run in the explicit root. If that directory
is not the repository top level, its parent repository's commit is not silently
substituted; `git_commit` is null. Source files are hashed only from explicit
`source_paths`. Alternatively pass `source_hashes={relative_path: expected_sha}`
to verify supplied digests against the workspace bytes. No source files are
automatically uploaded.

On errors, the runtime attempts report persistence, tracking finalization, and
budget finalization even if an earlier cleanup step fails. Reports retain only
safe exception type names and phases in `runtime_errors`. It then raises
`StageError`, whose `.report` carries available evidence, without rendering raw
provider exception messages. `KeyboardInterrupt`/`SystemExit` in the guarded
lifecycle become safe stage failures with the budget marked `interrupted`.
Provider calls and remote cancellation remain the controller/backend's job.
Process death or storage failure can still prevent final evidence from reaching
disk; inspect the carried report and ledger before any manual recovery.

## Tracking allowlists

The tracking object is a restricted facade, not the unrestricted W&B run API.
Its supported surface is `log`, `upload_json`, `use_artifact`, and the
`entity`/`project`/`url` properties. W&B is imported lazily when a stage starts
tracking. Mode defaults to configured `WANDB_MODE`, or `offline`; the main
controller requests `online` explicitly. `disabled` supports local-only execution
without importing the SDK. Explicit entity/project are required in tracked modes.

- `log(metrics)` accepts only declared `metric_keys` with finite numeric values.
- Stage reports upload as `pilot-report`, preserving existing artifact lineage.
  The uploaded JSON contains standard lifecycle/provenance fields plus only the
  explicitly named `report_fields`, and `local_report_sha256` for the source
  snapshot. Full raw reports remain under `runs/` locally.
- `upload_json(path, artifact_name=..., artifact_type=..., name="data.json")`
  accepts only predeclared ordinary JSON files under the workspace. It writes a
  sanitized copy under `work/tracking/<run-id>/` and uploads that one file. There
  is no unrestricted directory or code upload. In online mode its SDK result can
  be awaited with `.wait()` as in the existing controller.
- `use_artifact(reference, type=...)` requires a reference under the configured
  entity/project, for example `entity/project/parent-run:latest`.

Upload copies drop known credential/environment fields recursively and redact
configured provider credential values from strings. Console/code/Git/metadata/
system-stat collection is disabled through the established W&B settings. These
measures do not make arbitrary caller data safe: keep unknown credentials out of
reports, metric names, IDs, and allowed files. Local report persistence preserves
caller evidence rather than acting as a general secret scrubber.

A tracking upload is a snapshot taken before final cleanup. If subsequent
tracking or budget cleanup fails, the final local report is authoritative and
may be marked failed even if an earlier uploaded snapshot looked completed.
Failed stages cannot be treated as completed based solely on a remote artifact.

## Installed-package boundary and verification

An installed `Workspace` can manage an explicitly selected project root without
monkeypatching frozen `rsi.config.ROOT` or historical controller modules. Generic
provider adapters accept injected functions and remain reusable. This does **not**
make the historical GPU worker a standalone installed cloud deployment: its
image still depends on requirements-file adjacency in the project checkout.
Keep that limitation separate from the runtime's explicit-root support.

Verification uses fake W&B objects and temporary workspaces under the SSD's
`work/` directory. All 14 runtime tests passed; together with the new workflow and
study-controller tests, 24 tests passed. Covered behavior includes cache/env
containment, no parent dotenv discovery, symlink/path rejection, atomic writes,
budget/prefix caps, source provenance, allowlisted/redacted uploads, lifecycle
failure draining, and interruption. No real credentials were loaded by those
tests and no provider or tracking request was made.

```sh
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p test_project.py -v
```

Only `rsilab/project.py`, `tests/test_project.py`, and this document are owned by
this runtime task. Historical frozen modules remain unchanged. Main owns final
controller checks, protocol freeze, any authorized launches, and later packaging.
