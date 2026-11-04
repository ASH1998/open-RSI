# Python sandbox verifier

Updated November 4, 2026. The original `python-json-v2` verifier has been used in
the main chat's pilot; measured outcomes are in `EXPERIMENTS.md`. The new
`mbpp-typed-v1` protocol is locally tested and **not yet remotely audited by this
chat**. Neither static conversion counts nor local tests measure model capability.

## MBPP integration contract

Implementation: `rsi/mbpp_verification.py`; tests: `tests/test_mbpp_verification.py`.
The dataset importer owns downloading, source revisions, splits, duplicate/family
quarantine, and task prompts. The verifier compiles tests and scores outputs.

```python
from rsi.mbpp_verification import convert_mbpp_task, UnsupportedTest
from rsi.verification import verify_candidate

# raw_task is the importer's verification_mode="python_assertions" manifest.
# Conversion is local AST/data processing, with no network or execution.
try:
    task = convert_mbpp_task(raw_task)
except UnsupportedTest as exc:
    exclusion_reason = str(exc)  # exclude the whole task and record its ID

# Only main/controller, after reservation and reference audit:
# result = verify_candidate(response, task, app)
```

`convert_mbpp_tests(test_list, entry_point=None, *, test_setup_code="",
test_imports=(), challenge_test_list=())` provides the lower-level API.
`convert_mbpp_record(record)` aliases task conversion for raw MBPP rows. All
supplied ordinary and challenge tests are mandatory; there is no flag that drops
unsupported challenge tests. Conversion returns `entry_point`, typed `cases`,
`verification_mode="mbpp_typed_v1"`, `mbpp_compiler_version="mbpp-typed-v1"`,
source test counts, and `source_tests_sha256`. Task conversion also preserves
the original manifest fields. Reference `code`, if present, is neither read nor
executed by conversion. `UnsupportedMBPPTest` aliases `UnsupportedTest`.

`verification.verify_candidate` dispatches this explicit compiled mode to
`verify_mbpp_candidate`. Raw `python_assertions` and unknown modes fail before a
sandbox launch. Existing tasks with no mode or `python_json` keep the original
candidate and scoring rules. Both protocols use the same sandbox lifecycle,
bounded stdout transport, sanitized provider errors, and fail-closed cleanup.

### Accepted test grammar and exclusions

The accepted form is one `assert fn(literal_args, name=literal_value) == expected`
per source string, or the reversed equality. Every test must call the same public
function. Names are preserved; there is no forced rename to `solve`.

Literal data supports finite numbers, strings, booleans, null, lists, tuples,
sets, and dictionaries with supported hashable keys. Unary numeric `+`/`-` and
zero/one-argument `set`, `frozenset`, `list`, `tuple`, `dict`, and `sorted`
constructors over literals are supported. These are fixed builtin constructors,
not arbitrary Python calls. Dataset setup is never executed or injected.

Results may be wrapped in nested unary `set`, `frozenset`, `list`, `tuple`, or
`sorted` calls. The compiler records those projections; the parent applies them
to decoded builtin values. Neither projection expressions nor expected values
are sent to the candidate. For example, `set(fn((1, 2))) == {1, 2}` sends a tuple
argument, receives a typed result, and compares sets in the parent.

Explicit exclusions include nonempty setup/import code (even import-only setup),
custom classes, type-valued arguments such as `int`, unknown names, attributes,
computed/reference-function expectations, arbitrary arithmetic, comprehensions,
`*args`/`**kwargs` unpacking, non-equality comparisons, chained comparisons,
truthiness assertions, assertion messages, multiple statements, multiple entry
points, and wrappers such as `int(fn(...))`. Unsupported tests invalidate the
entire record; no hidden case is silently omitted.

The primary [Hugging Face MBPP card](https://huggingface.co/datasets/google-research-datasets/mbpp/blob/4bb6404fdc6cacfda99d4ac4205087b89d32030c/README.md)
describes full rows with `test_list`, `test_setup_code`, and `challenge_test_list`,
and sanitized rows with `test_imports` and `test_list`. The
[upstream evaluation instructions](https://github.com/google-research/google-research/tree/master/mbpp)
define the original task-ID split. This restricted protocol is a **filtered MBPP
experiment**, not an unqualified reproduction of the official execution metric.
The controller must report every filtering stage and its denominator.

### Typed values and candidate policy

Typed JSON retains list/tuple distinctions, set membership, and non-string dict
keys. The wire form is `[tag, value]`, with nested entries for containers and
key/value pairs for dictionaries. The codec accepts exact builtin types only;
there is no pickle, import hook, custom-class reconstruction, or candidate-defined
comparison code in the parent. Duplicate keys/items in untrusted wire maps/sets
are rejected. Bytes, complex numbers, iterators, arrays, and custom container
subclasses are unsupported **return values**; candidates may use those internally
but must return one of the supported builtin values.

Parent comparison uses Python builtin `==` without float tolerance, matching the
accepted source operator: `(1, 2)` differs from `[1, 2]`, integer dictionary keys
remain integers, and `1 == True` is true. This is separate from `python-json-v2`,
which continues to reject bool/number equivalence and permits float tolerance.
The fixed parent builtin projections cannot be redefined by candidate code.
Order-sensitive conversion of sets/dictionaries reflects the reconstructed
builtin value; tasks depending on implementation-specific iteration order need
exclusion during remote reference audit. Use sorted/set comparisons when present
in the original tests; do not rewrite tests to make references pass.

MBPP candidates use the original AST policy with these additional modules:
`re`, `string`, `operator`, and `array`. Full import allowlist:

```text
array bisect collections functools heapq itertools math operator re statistics string
```

No `sys`, `os`, network, filesystem, process, or serialization modules are added.
The old JSON allowlist is unchanged. **Dataset prompts and metadata must advertise
the MBPP list before the manifest is frozen.** The design reference's larger
budget/local GPU proposal does not change the current $250 Modal authorization or
the prohibition on local candidate/reference-code execution.

### Bounds, evidence, and handoff

Original sandbox bounds below are reused unchanged: 0.125 CPU, 512 MiB memory,
30-second maximum lifetime, 8-second child wall limit, 5-second CPU limit,
256 MiB child address space, no secrets/mounts/network, and bounded output.
Typed values additionally have depth 8, 4,096 nodes, 4,096-bit integers, and
24,000-byte strings. Tests have a 24,000-byte/4,096-AST-node limit. Aggregate
compiled cases and launch payload are each limited to 128,000 bytes. Per-case
typed output is at most 8,192 bytes; aggregate output remains 65,536 bytes.
Only candidate source, entry point, and encoded positional/keyword arguments
enter the payload. Raw tests, expectations, projections, prompts, metadata, and
reference source remain in the controller. The untrusted child is not a scoring
authority even if it forges `ok` or `passed` fields.

Local verification command:

```sh
TMPDIR="$PWD/.cache/tmp" XDG_CACHE_HOME="$PWD/.cache" \
  .venv/bin/python -B -m unittest discover -s tests -p '*verification.py' -v
```

**65 tests passed** (35 MBPP and 30 original-verifier tests). Coverage includes
adversarial AST expressions, all-or-nothing challenge conversion, exact typed
round trips, equality semantics, unknown wire tags, output bounds, missing/forged
verdicts, no expected-value leakage, raw-mode rejection, unchanged original
import policy, rejected dropped challenge/case identities, maximum-depth transport,
and cleanup failure. Child source is parsed for Python 3.11 syntax;
it is never executed locally. Sandbox SDK calls are mocked.

A static inspection of the dataset chat's `pools-full-seed42.json` accepted
269/272 training and 65/68 development records. Reference AST policy checks
reduced those to 259 training and 64 development records, before execution.
These are provisional counts tied to that manifest snapshot; they are not a
correctness audit or guaranteed achievable experiment sizes. No final-test source
was opened by this verifier inspection. Detailed machine-readable evidence is in
the ignored SSD-local `work/mbpp-verifier/coverage.json`.

Main chat's next milestone is to freeze/import-align the compiled task list and
reserve a bounded remote audit. Audit selected source references against all
converted tests, typed tuple/set/dict transport, expected failure cases, and
resource/lifecycle behavior. Persist exclusions and reference failures before
scoring model outputs. Maintain matched task lists and inference limits for
parent/successor comparisons. This chat launched no remote job, read no `.env`,
spent no credits, and made no Git commit.

## Kaggle artifact audit — November 4, 2026

Read-only inspection of `artifacts/kaggle-mbpp-v1/open-rsi-result.json` confirmed
32 unique, ordered outputs for the first 32 frozen development tasks. Its request
matches `work/kaggle-mbpp-v1/upload-audit.json`, the embedded request in uploaded
`worker.py`, and the frozen task prompts/manifest hash. The uploaded source hash
matches its audit record, and the uploaded worker matches the current worker
template with that request substituted. All 32 progress-log records agree with
the output IDs and token counts. No result-envelope/schema mismatch was found.

| Evidence | Observed value |
| --- | --- |
| Result status | completed |
| Token/time-limit flags | 0/32 for each |
| Empty responses | 0/32 |
| Input tokens | 3,881 total; 112–136 per task |
| Output tokens | 2,321 total; 20–494 per task; cap 512 |
| Worker wall time | 284.88 seconds |
| Sum of per-task generation time | 194.46 seconds |
| Requested / recorded GPU | NvidiaL4 / Tesla T4 |
| Recorded compute dtype | torch.bfloat16 |
| Peak allocated GPU memory | 2,145,820,672 bytes |
| Packages | torch 2.11.0+cu130; transformers 5.22.1; accelerate 1.15.0; bitsandbytes 0.50.2; safetensors 0.8.0; tokenizers 0.23.3 |

The four packages explicitly installed by the worker match their pinned versions.
Torch and tokenizers are recorded runtime versions, not direct worker pins. The
worker chooses dtype with `torch.cuda.is_bf16_supported()`; the
[PyTorch 2.11 implementation](https://github.com/pytorch/pytorch/blob/v2.11.0/torch/cuda/__init__.py#L169-L188)
includes emulation in its default check. Therefore the reported dtype does not
establish native BF16 hardware support. The artifacts cannot establish why Kaggle
allocated a T4 instead of the requested L4. Preserve actual hardware/precision in
reporting; this remains the preregistered **separate Kaggle benchmark**, not a
matched L40S arm or a basis for cross-device speed claims.

Static extraction found one malformed response: `mbpp-full-543` contains an extra
closing parenthesis. The other 31 pass syntax and candidate-policy checks, which
does not establish correctness. Main chat's completed verification report
`runs/20261104T095900Z-mbpp-kaggle-verify-21d047/report.json` records **8/32 passed**,
23 candidate-execution/scoring failures, one syntax failure, and zero
infrastructure failures.

The frozen codec's exact-builtin restriction affects this result. Task
`mbpp-full-568` returns a list of empty `collections.OrderedDict` instances where
the expected values are lists of empty builtin dictionaries. By source inspection,
ordinary Python equality would accept those containers; the typed codec rejects
them with `ValueError`. Task `mbpp-full-561` likewise returns a `defaultdict`,
which is outside the return-value protocol, though its contents also differ from
the expected mapping. These are protocol limitations, not provider corruption.
Keep the recorded scores unchanged and disclose the restriction; any broader
codec would require a separately versioned, re-audited comparison. No candidate
completion was executed locally to make these observations.

Artifact SHA-256:
`799e052b8c96b3d4c92b4ad073087380308d9973a5d8e84c7fc722c37390822f`.
This inspection made no study-source changes or paid launches; only this evidence
note was added.

## Contract and authority

`verify_candidate(response, task, app, timeout=30)` accepts model response text
and a trusted task with `entry_point`, `cases` (each containing positional `args`
and `expected`), and optional `tolerance` (`rel_tol`, `abs_tol`). It requires
1–128 cases, finite JSON values, string object keys, and JSON nesting at most 32
levels. The timeout must be an integer from 10 through 30 seconds. Malformed
tasks, invalid tolerance, invalid code, policy violations, and oversized payloads
are rejected before attempting to create a sandbox.

The caller must reserve the stage through `rsi/budget.py` before invocation and
provide an active Modal app. This module does not reserve funds, create apps,
upload tracking records, or retry launches. Only the main project chat may launch
paid jobs. The total authorization remains $250, with initial reservations capped
at $5 and $25 held for overhead. A failed launch does not release its reservation.

One disposable sandbox handles one candidate and all its cases. Only extracted
code, entry point, and case arguments enter its payload. Expected answers, task
metadata, model prompts, reference implementations, and scoring remain in the
trusted controller. No generated code runs in that controller.

The subprocess calls the function sequentially with positional arguments and
JSON-normalizes its returned values. Results must contain an explicit `value`
and `ok: true` for each case. The parent ignores candidate-supplied verdicts and
computes success itself. Lists preserve order and length; object keys must match;
booleans never equal numbers. Integer expectations compare exactly (an equal
integral float is accepted). Floating expectations use the task's finite,
nonnegative tolerance, defaulting to relative `1e-6` and absolute `1e-8`. NaN and
infinity cannot pass. Missing `value` cannot pass an expected JSON null.

## Candidate policy

The response must be unfenced Python or one fenced `python`/`py` code block.
An optional prefix ending in `</think>` is discarded; an unfinished reasoning
section or ambiguous/multiple fences is rejected. Extraction is followed by
syntax and policy checks; syntactically valid prose alone is not a solution.

The entry point must be a top-level synchronous function with a public identifier.
Top-level statements are limited to function definitions, imports, assignments,
annotated assignments, and constant expressions such as docstrings. Function
decorators, including those on nested functions, are rejected. There is a
4,000-node AST limit.

The exact import allowlist is:

```text
math collections itertools functools bisect heapq statistics
```

Only these exact modules are allowed, including inside functions. Relative
imports, wildcard imports, private imported names, and other modules/submodules
are rejected. Attribute names starting with `_` and identifier references starting
with `__` are rejected. The following identifier references are also rejected:

```text
eval exec compile open input globals locals vars getattr setattr delattr
__import__ breakpoint help
```

Task prompts must describe this restricted policy rather than promise unrestricted
standard-library use. The current suite exposes the same set through
`rsi.tasks.TASK_IMPORTS`; the local compatibility test checks that agreement.
Print output is discarded; return a result. JSON serialization turns tuples into
arrays; other unsupported return types fail their case.

**AST checks are not a Python security boundary.** This is a deliberately small
task language, not a proof that Python introspection is impossible. Treat the
child, its harness, and everything emitted by the sandbox as untrusted. Candidate
code shares a Python interpreter with the child harness and can retain state
between cases. The outer sandbox provides host isolation; the trusted parent
provides scoring authority. Do not put authoritative expected outputs inside the
sandbox to strengthen tests.

## Resources and isolation

| Layer | Configured bound |
| --- | --- |
| Sandbox | Explicit `gvisor`, no GPU, 0.125 CPU request and hard cap |
| Sandbox memory | 512 MiB request and hard cap |
| Sandbox lifetime | 30 seconds maximum |
| Network and data | `block_network=True`, empty secrets/environment/volumes/network filesystems, OIDC identity token disabled, no exposed ports |
| Runtime image | Modal Debian slim, Python 3.11; no project checkout mounted |
| Candidate response | 24,000 UTF-8 bytes including reasoning/fences |
| Serialized input payload | 128,000 UTF-8 bytes |
| Child process | `python -I -S`; 5 CPU seconds, 256 MiB address space, 32 file descriptors, 16 processes via Linux rlimits |
| Child wall time | 8 seconds across startup and all cases |
| Child output files | 65,536 bytes each via `RLIMIT_FSIZE` |
| Per-case serialized result | 8,192 characters (ASCII-escaped JSON) |
| Aggregate child result | 65,536 UTF-8 bytes |
| Parent stdout retention | At most 65,537 bytes, including supervisor newline |

The supervisor captures child stdout/stderr in temporary files and discards normal
function prints through `/dev/null`. Parent stdout is read incrementally and
reading stops on oversize output; it does not use the SDK's unbounded `.read()`.
The byte limit bounds retained application output, not the size of one SDK
transport batch. Stderr is not fetched by the controller. Linux process limits
can depend on runtime privilege and are defense in depth, not substitutes for
sandbox isolation. At 0.125 CPU, the 8-second wall limit can expire well before
the 5-second CPU limit; measure task feasibility remotely before collecting data.

Termination is attempted in `finally` for every acquired sandbox handle, including
read/wait/scoring failures. A termination error forces `passed=False` and marks an
infrastructure failure even when all case values matched. Interrupted creation
before a handle is returned cannot be explicitly terminated here; provider
lifetime bounds and controller-side reconciliation remain necessary. SDK calls
can retry transport requests internally; this module adds no retry loop. The
sandbox lifetime is not a strict client RPC/provisioning deadline.

## Results and provenance

Every returned record contains `passed`, `count`, `total`, `errors`,
`verifier_version`, `sandbox_id`, and client `duration_seconds`. Once extraction
and policy validation succeed, it also contains `candidate_sha256`. Bounded
completed stdout is preserved in `stdout`, and parsed finite JSON is retained in
`outputs`. Oversized or interrupted streams are deliberately not retained in full.
These fields contain untrusted data and must never be treated as instructions.

`error_kind` separates `invalid_task`, `invalid_candidate`, `candidate_policy`,
`candidate_execution`, and `infrastructure`. Provider exception messages are not
returned; only exception class names are recorded. Infrastructure errors include
`infrastructure_error=True` and must not silently become model-quality failures
or verified training labels. `count` can preserve matching-case evidence even
when cleanup makes the overall verdict unsuccessful. Candidate timeout/process
error envelopes are diagnostic claims, not authoritative attestations.

The controller must durably save the original model response and returned record,
task/split hash, code revision, model revision, seeds, generation settings,
reservation ID, provider/job IDs, actual runtime image identity, timing, and
billing reconciliation. The Debian image declaration alone is not an immutable
image digest. Client duration includes provisioning/cleanup and is not a Modal
invoice. Upload only selected examples/metrics to W&B using an explicit allowlist.

## Original JSON verifier evidence (initial handoff)

Local command, run from the SSD workspace:

```sh
TMPDIR="$PWD/.cache/tmp" XDG_CACHE_HOME="$PWD/.cache" \
  .venv/bin/python -B -m unittest discover -s tests -p test_verification.py -v
```

Result on November 4, 2026: **28 tests passed**. Tests cover extraction and policy,
exact integer scoring and floating tolerance, malformed output/null handling,
preflight rejection without creation, parent-only expected answers, configured
isolation arguments, bounded streaming, sanitized provider failures, cleanup on
failure, and fail-closed termination. Task manifests and reference source strings
across all three splits/eight variants per family pass static policy checks.
Reference strings and the child/supervisor are parsed, never executed by these
tests. All sandbox creation is mocked.

Installed Modal **1.6.3** signatures accept `Sandbox.create` arguments,
`wait()`, and `terminate(wait=True)`; `StreamReader` supports synchronous iteration.
Installed source inspection confirms CPU/memory tuples encode requests and hard
limits. The official [Sandbox reference](https://modal.com/docs/sdk/py/latest/Sandbox)
documents those settings and the [stream reference](https://modal.com/docs/sdk/py/latest/io_streams)
documents chunk iteration. This validates the client interface, not server-side
acceptance or actual resource enforcement.

At the initial handoff, the next milestone was for the main chat to reserve a small
stage and run a remote smoke matrix with known correct and incorrect solutions, missing
outputs, syntax/policy failures, exceptions, infinite loops, memory/output growth,
and network/filesystem isolation probes. Confirm lifecycle termination, cold-start
behavior, gVisor rlimits, server acceptance of resource caps, image identity,
absence of injected credentials/mounts, and ledger reconciliation. Subsequent pilot
execution is recorded in `EXPERIMENTS.md`; the MBPP-specific remote audit remains
the next milestone for this change.

This expanded handoff changes only `rsi/verification.py`, `tests/test_verification.py`,
`rsi/mbpp_verification.py`, `tests/test_mbpp_verification.py`, and this document,
plus the ignored local coverage report. Main chat owns integration, the work log,
README/plan/setup updates, commits, and all paid launches. No credentials were read
and no credits were spent by this work.
