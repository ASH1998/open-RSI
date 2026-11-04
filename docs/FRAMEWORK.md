# rsilab framework foundation

`rsilab` is an installable, dependency-free Python foundation for recording
and comparing verified agent experiments. It adapts the implemented `rsi` pilot
task generator and scorer. It does not launch compute, load credentials, train
models, or implement the reference document's proposed research programme.

The November 1 Mini-RSI Lab v0.2 document is a design reference, not an adoption
of its model, hardware, $500 budget, timeline, statistics, or measured claims.
This project retains its $250 total Modal cap, pinned MiniCPM5-2B model, and
main-chat ownership of launches. No legal license has been chosen and nothing
has been published to PyPI; a repository license remains a release prerequisite.

## Install and use offline

Python 3.11 or newer is required. From the SSD checkout, with the existing
project environment and SSD cache paths:

```sh
UV_CACHE_DIR="$PWD/.cache/uv" TMPDIR="$PWD/.cache/tmp" \
  uv pip install --python "$PWD/.venv/bin/python" --no-deps -e .
.venv/bin/rsilab --help
.venv/bin/rsilab validate work/manifest.json
.venv/bin/rsilab compare work/parent.json work/candidate.json work/parent-results.json work/candidate-results.json
.venv/bin/rsilab artifacts artifacts/export adapter/adapter_model.safetensors adapter/adapter_config.json
```

The equivalent module entrypoint is `python -m rsilab`. Commands print JSON to
stdout. Invalid inputs and unmatched comparisons return exit code 2. There is
no automatic upload, execution, promotion, or provider authentication. The
wheel includes only Python packages `rsilab` and `rsi`, plus the typing marker;
it does not bundle `.env`, tests, run outputs, model artifacts, or the checkout.
The packaged `rsi` code supports the offline task/scoring adapter; the existing
Modal pilot launcher still requires its checkout, configuration, GPU requirement
file, and separately installed service dependencies. Installing the core package
does not make that launcher a standalone cloud service.

## Stable initial interfaces

Public imports are available directly from `rsilab`:

| Interface | Implemented responsibility |
| --- | --- |
| `Agent` | Immutable identity: model ID and 40-character revision, harness/memory SHA256, optional adapter SHA256. |
| `Task` | ID, family, split, prompt, and immutable trusted payload. `agent_input()` excludes the trusted payload. |
| `RunResult` | Task/seed/run/agent identity, status, immutable evidence, optional trusted score, token count, elapsed time, optional cost. |
| `Provenance` | Trusted measurement-code, evaluation-data, evaluator and analysis-plan SHA256 values, installed packages, exact hardware label. Evolving harness/adapter identity belongs to `Agent`. |
| `Manifest` | Agent, tasks, seeds, declared budget/settings and provenance. Frozen data; stable `.sha256`, `.to_dict()`, `.from_dict()`. |
| `Environment` | Extension protocol `tasks(split)` and sandboxed `run(task, patch, seed)`. No new executor is implemented. |
| `Evaluator` | Extension protocol `score(task, result) -> Score`. The implemented `PilotEvaluator` reuses the trusted pilot scorer. |
| `Operator` | Extension protocol `propose(agent, ledger) -> Sequence[Agent]`. No SFT/DPO/memory/harness operator is claimed yet. |
| `PromotionGate` | Extension protocol `decide(parent, candidates) -> Decision`; a custom trusted gate must obtain its validated evidence. |
| `RetainParentGate` | Always retains the parent, including when descriptive scores increase. |
| `artifact_manifest(root, paths)` | Streams SHA256/size for an explicit relative file allowlist; rejects hidden/traversal paths and escaping symlinks. Returns `FrozenJSON`. |
| `digest(value)` | SHA256 of canonical finite JSON; accepts framework records. |
| `compare(...)` | Complete paired comparison of trusted result records under identical declared controls. |

`FrozenJSON` snapshots nested objects; `.to_dict()` returns a copy. Frozen
dataclasses alone would not prevent nested dictionary mutation, so record
payloads explicitly use this wrapper. Digests are identity checks, not signatures
or proof that a controller/evaluator was trustworthy. Hash artifacts only after
writers finish. The trusted controller must enforce access isolation, real
budgets, secret handling, and the integrity of scorer inputs.

Minimal manifest construction (replace hashes with actual artifacts; these
examples deliberately do not invent a completed run):

```python
from rsilab import Agent, FrozenJSON, Manifest, Provenance
from rsilab.pilot import pilot_tasks

# Obtain these digests from real, frozen source/data/analysis artifacts.
agent = Agent(agent_id, model_id, model_revision, harness_hash, memory_hash)
provenance = Provenance(code_hash, data_hash, evaluator_hash, analysis_plan_hash,
                        FrozenJSON(installed_packages), actual_gpu_name)
manifest = Manifest(run_id, agent, pilot_tasks("dev", count_per_family=4), (42,),
                    FrozenJSON({"max_new_tokens": 512, "attempts": 1}),
                    FrozenJSON({"temperature": 0.0, "enable_thinking": False}),
                    provenance)
manifest_json = manifest.to_dict()
manifest_hash = manifest.sha256
```

SHA256 fields require 64 lowercase hex characters; the model revision requires
40. Mutable Hub names such as `main` are rejected. Manifest validation rejects
duplicate task IDs, duplicate/invalid seeds, and a task family appearing in
multiple splits. It cannot detect semantic near-duplicates: dataset authors
must still enforce that separation. `test` remains the existing pilot label;
it does not imply a preregistered sealed evaluation. Generating a manifest does
not enforce sealing or constitute preregistration.

## Comparisons and existing pilot integration

`compare(parent_manifest, candidate_manifest, parent_results, candidate_results)`
requires exactly one result per task/seed, identical task manifests, seeds,
budgets, settings, and provenance (including exact hardware and package labels).
Distinct run/agent IDs are required. Missing, duplicate, incomplete, unscored,
or misidentified records suppress aggregate gains. Candidate execution failures
remain in the paired report when scored by the trusted evaluator; infrastructure
failures must be marked `incomplete`, not silently converted into low scores.
Results can use `higher_is_better=False` for loss objectives.

Matching refers to declared controls; measured token/time/cost fields remain in
the caller's raw records. This version does not enforce arbitrary budget-object
semantics or infer compliance from declarations. Reports show per-pair gains,
split means, wins/ties/losses, and a no-promotion decision. They do not compute
confidence intervals or establish any RSI level. A separate preregistered,
powered gate and sealed-access protocol are future work.

`rsilab.pilot.pilot_tasks` wraps existing `rsi.tasks.build_tasks` without changing
its suite. `PilotEvaluator` reuses `rsi.verification.score_outputs` and its task
validation, scoring raw outputs against trusted cases instead of accepting a
reported `passed` flag. It never executes candidate code. Existing isolated
execution remains `rsi.verification.verify_candidate`, which requires a budget
reservation in the main controller before use. The package introduces no second
budget ledger; use the project's existing `rsi.budget.Budget` with an explicit
checkout root when adapting it outside the source tree.

The additional `rsilab pilot-report PARENT_JSON CANDIDATE_JSON` command re-scores
existing pilot output records offline. It checks generation coverage, task
hashes, trusted evaluator/task source hashes, decoding settings, versions, and
the actual GPU label. Source differences outside those scorer controls remain
visible as `changed_sources`. This legacy report adapter is descriptive and
does not produce a complete framework manifest with invented missing hashes.

Replaying the first pilot reports exposed a previously overlooked hardware
label difference: baseline `20261104T070918Z-baseline-14df3d` reports **NVIDIA
A10G**, while evaluation `20261104T072356Z-evaluate-92cbe2` reports **NVIDIA A10**.
Both were requested using the Modal A10 selector, but this framework deliberately
does not silently normalize the observed labels. `pilot-report` therefore marks
that pair unmatched. This does not erase the recorded scores; it narrows what
can be claimed about a strict identical-hardware comparison. Main owns any
correction to the experiment record and future comparison policy.

## Aggregate completed MBPP study reports

For the completed two-seed study, the reusable offline driver discovers inputs
and writes all reports in one validated operation:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/report_mbpp.py --check-only
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/report_mbpp.py
```

Before either command, export each selected training run's weights to
`artifacts/mbpp/<training_run>/adapter/adapter_model.safetensors` and verify that
the export belongs to that run. The driver hashes the local bytes. It requires
six completed baseline batches, exactly one completed training run for each of
seeds 42 and 43, and three completed evaluation batches linked to each training
run. Missing exports, unfinished runs, ambiguous completed duplicates, changed
target selection, or incomplete batches are errors; no partial final report is
written. The driver also checks selected-data diversity and training settings,
source inventory, hardware, and package/CUDA inventory against the baseline.

The output directory `artifacts/mbpp/reports` contains `summary.json`,
`seed-42-comparison.json`, `seed-43-comparison.json`, parent/candidate manifests
for each seed, and a checksum `inventory.json`. Summary fields include baseline
split/category counts, baseline and per-seed truncation counts, unique verified
target yield/categories, paired dev/retention results, and failed-attempt
lineage. Exact reruns are idempotent; differing existing reports are preserved
and cause an error. `--check-only` validates and summarizes without writing.

The explicit prospective decision is `replication_worthy` only if **both**
training seeds gain at least **four net development successes**, each loses at
most **one previously passing retention task**, and both comparisons have
matched controls. Any unmet condition yields `not_replication_worthy`; unmatched
controls retain null scores rather than fabricated zeros. The original parent
remains selected and `promoted` is always false. This is an engineering flag,
not statistical significance, population-level generalization, or evidence of
RSI. The driver does not combine training seeds into an independent-data result.

Driver tests use synthetic report fixtures and the real strict scorer/helper;
they exercise threshold boundaries, incomplete/ambiguous inputs, training-label
lineage, unmatched controls, truncations, and atomic/idempotent publication.
No model or generated code is executed by the tests or driver.

Run the source CLI from the SSD checkout (`.venv/bin/python -m rsilab`), rather
than relying on an older installed wheel's console entrypoint. The adapter is
`rsilab.mbpp_report.build_mbpp_comparison`. It requires all **six** completed
baseline batches (0–5; 176 tasks) and **three** completed evaluation batches
(0–2; 80 tasks) for **one** training run. Run it separately for training seeds
42 and 43. The framework manifests retain the original `train` split; the
human-facing `evaluation_splits.retention` summary identifies the preselected
32-task retention subset, alongside 48 development tasks.

Direct CLI syntax, with explicit report paths and a verified weights digest:

```sh
.venv/bin/python -m rsilab mbpp-report data/mbpp/study-v1.json \
  --baseline PARENT_BATCH_0/report.json PARENT_BATCH_1/report.json PARENT_BATCH_2/report.json PARENT_BATCH_3/report.json PARENT_BATCH_4/report.json PARENT_BATCH_5/report.json \
  --candidate CANDIDATE_BATCH_0/report.json CANDIDATE_BATCH_1/report.json CANDIDATE_BATCH_2/report.json \
  --training-report runs/TRAINING_RUN_ID/report.json \
  --adapter-sha256 VERIFIED_ADAPTER_WEIGHTS_SHA256
```

Replace the uppercase placeholders with actual paths/values. The following
alternative discovers the correct completed reports, hashes the exported
`adapter_model.safetensors`, and saves the full result under `work/`. Replace
only the two invocation arguments; run from `/Volumes/DevSSDWD/openbmb/rsi`.
It performs no network access, credential loading, execution of generated code,
or provider calls. It refuses to overwrite an existing comparison file.

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - \
  "TRAINING_RUN_ID" "artifacts/EXPORTED_ADAPTER/adapter_model.safetensors" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
from rsilab.mbpp_report import build_mbpp_comparison

training_id, adapter_name = sys.argv[1:]
if Path(training_id).name != training_id:
    raise ValueError("Use a run ID, not a path")
root = Path.cwd().resolve()
adapter = Path(adapter_name).resolve()
if not adapter.is_relative_to(root) or adapter.name != "adapter_model.safetensors":
    raise ValueError("Use the exported adapter weights inside this SSD checkout")
study = json.loads(Path("data/mbpp/study-v1.json").read_text())
reports = [json.loads(path.read_text()) for path in sorted(Path("runs").glob("*/report.json"))]
completed = [row for row in reports if row.get("status") == "completed"
             and row.get("study_sha256") == study["sha256"]]
baselines = [row for row in completed if row.get("stage") == "mbpp-baseline"]
candidates = [row for row in completed if row.get("stage") == "mbpp-evaluate"
              and row.get("training_run") == training_id]
training = json.loads((Path("runs") / training_id / "report.json").read_text())
with adapter.open("rb") as stream:
    weights_hash = hashlib.file_digest(stream, "sha256").hexdigest()
result = build_mbpp_comparison(study, baselines, candidates,
                               adapter_sha256=weights_hash, training_report=training)
output = Path("work") / f"mbpp-comparison-{training_id}.json"
output.parent.mkdir(exist_ok=True)
with output.open("x") as stream:
    json.dump(result, stream, indent=2)
    stream.write("\n")
print(json.dumps({"path": str(output), "matched": result["comparison"]["matched"],
                  "reasons": result["comparison"]["reasons"],
                  "scores": result["evaluation_splits"], "promoted": False}, indent=2))
raise SystemExit(0 if result["comparison"]["matched"] else 2)
PY
```

Missing/extra batches, duplicate successful retries, wrong task order/hash,
mixed adapters, protocol changes, incomplete generation, invalid output flags,
or unverifiable recorded scores stop aggregation. Source/hardware/package/CUDA
drift within one arm also stops it. Differences between otherwise valid parent
and candidate controls produce `comparison.matched=false` and no score summary.
All recorded `rsi/*.py` source hashes participate, including files outside the
six required worker/evaluator modules: avoid changing that source inventory
between baseline and evaluation. Documentation-only edits do not affect it.

The exported weights hash is caller-attested: confirm the SSD export belongs to
the selected training run and matches its Volume/checkpoint inventory before
aggregation. The helper links the training report's run ID, study, seed and
adapter path but cannot prove a supplied digest belongs to remote bytes. Keep
raw reports and both failed and successful outcomes. No promotion or
replication-worthiness decision is automated by this single-adapter command;
the two-seed driver above implements only the predeclared replication flag.

## GPU and Kaggle backend handoff

Only installed Kaggle 2.2.5 source was inspected; importing `kaggle` was avoided
because its package initializer authenticates. No credentials, account quota,
network requests, or jobs were inspected through it. Its `cli.py` and
`api/kaggle_api_extended.py` implement:

- `kernels push -p DIR --accelerator NAME -t SECONDS`, which saves **and runs**
  by default; `--no-run` makes a remote quick-save without running cells.
- Private Python scripts via `kernel-metadata.json`, `code_file`,
  `kernel_type="script"`, `language="python"`, `is_private=true`, explicit
  `enable_internet`, and optional dataset/model sources.
- Accelerator selection through `--accelerator` (overrides boolean flags),
  or metadata `machine_shape`; the local help gives `NvidiaTeslaT4` as a T4 x2
  example and warns that retired P100 requests can run on replacements.
- Requested session timeout through `session_timeout_seconds`, plus status,
  output download, logs and quota commands. Capability in local code does not
  establish account access, availability, or actual hardware.

Recommended portable generation boundary for main's implementation: a pure
request/output contract with prompts `{id,prompt}`, pinned model/revision,
seed, decoding limits, quantization/precision, adapter reference plus checksum,
and explicit cache/output paths. Keep the existing CPU-tested chat-template
encoding (`return_dict=False`, `enable_thinking=False`) identical. Separate GPU
generation from Modal App/Volume lifecycle; directly importing the current
Modal `_generate` in Kaggle would still require Modal Volume operations. No
worker refactor or portable generation backend was made in this assignment.

For Kaggle, package only reviewed code, pinned requirements, input manifest,
and required adapter files; never the checkout or `.env`. Use
`/kaggle/working/rsi/{cache,outputs}` and write outputs incrementally with a final
completion marker and SHA256 inventory. Preserve failures, truncated outputs,
actual packages/GPU/CUDA/dtype, seed, input/output tokens, runtime and input
manifest hash. Download the output inventory and files back to SSD and verify
hashes before controller ingestion. Controller-side W&B logging avoids giving
the generation kernel tracking or provider control credentials. GPU execution
must reject unsupported precision instead of silently changing the experiment.

Kaggle should first be treated as optional training-data generation capacity.
Do not combine T4/Kaggle timing or precision results with A10/Modal comparisons
as matched evidence. TPU support is a separate unvalidated backend. Main owns
the private kernel package, submission, quota checks, execution and exports;
the framework CLI has no launch command.

## Validation and remaining scope

All 12 framework tests passed locally on November 4, 2026. They exercise immutable payloads and round trips, strict identities,
split separation, paired completeness/control mismatches, conservative gating,
artifact hashing and symlink containment, actual pilot scoring, and offline CLI
validation. `work/framework-dist/rsilab-0.1.0-py3-none-any.whl` was built from an
explicit source allowlist in `work/framework-source`, installed without runtime
dependencies into the SSD `.venv`, and imported using isolated Python (`-I`).
The latest wheel rebuild includes `rsilab.mbpp_report` and its CLI dispatch,
alongside the current allowlisted `rsi` Python sources. Installed core, pilot
adapter, MBPP report helper, and CLI checks passed under isolated Python with
socket connections blocked; no Modal, Kaggle, Torch, W&B, or dotenv module was
imported. Main reports 145 integrated tests passing. The wheel content and source
checksum allowlists passed; its SHA256 and inventory are recorded in
`work/framework-dist/wheel-audit.json`. Setuptools 84.2.1 and wheel 0.48.0 were added
only to the SSD-local build environment. No GPU, generated-code execution,
credentials, remote jobs, commits, or publication were used in this handoff.

Not implemented: new environments, provider-independent GPU execution, automatic
operators, authenticated/sealed ledgers, confidence intervals, promotion based
on evidence, Level 2 experiments, or a reusable distributed controller. These
remain proposals. Main owns orchestration and subsequent experiment decisions.

## Evaluator correction release

Local package 0.1.1 adds the versioned MBPP evaluator and offline rescore audit while preserving the original 0.1.0 wheel and v1 results. See [rescore API and package validation](RESCORING.md) and [correction experiment](MBPP_RESCORE_V2.md). No PyPI publication or automatic training/promotion is included.

## Durable execution release

Local version 0.1.2 adds bounded trusted-callback execution with persist-before-validation and complete draining after failures. Its installed execution tests and remote diagnostic integration passed. See [execution API](EXECUTION.md) and [completed diagnostic evidence](MBPP_ROBUSTNESS.md). No automatic retry, training loop, or release publication is implied.
