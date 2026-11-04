# rsilab framework foundation

`rsilab` 0.1.0 is an installable, dependency-free Python foundation for recording
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
The installed task adapter and console entrypoint passed; no Modal, Kaggle,
Torch, W&B, or dotenv module was imported by the core/offline pilot adapter.
The wheel content allowlist passed. Setuptools 84.2.1 and wheel 0.48.0 were added
only to the SSD-local build environment. No GPU, generated-code execution,
credentials, remote jobs, commits, or publication were used in this handoff.

Not implemented: new environments, provider-independent GPU execution, automatic
operators, authenticated/sealed ledgers, confidence intervals, promotion based
on evidence, Level 2 experiments, or a reusable distributed controller. These
remain proposals. Main owns orchestration and subsequent experiment decisions.
