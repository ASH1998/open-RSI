# Python sandbox verifier

Updated November 4, 2026. Implementation: `rsi/verification.py`; evaluator version
`python-json-v2`. Local validation is complete for the checks below. **No remote
sandbox has been launched by this verifier work, and remote enforcement has not
been demonstrated.** This is not evidence of model performance or RSI.

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

## Verified evidence and next milestone

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

The next executable milestone belongs to the main chat: reserve a small stage
and run a remote smoke matrix with known correct and incorrect solutions, missing
outputs, syntax/policy failures, exceptions, infinite loops, memory/output growth,
and network/filesystem isolation probes. Confirm lifecycle termination, cold-start
behavior, gVisor rlimits, server acceptance of resource caps, image identity,
absence of injected credentials/mounts, and ledger reconciliation. Do not collect
training labels or report baseline scores until that boundary is validated.

This handoff changes only `rsi/verification.py`, `tests/test_verification.py`, and
this document. Main chat owns integration, the work log, README/plan/setup updates,
commits, and all paid launches. No credentials were read and no credits were spent
by this work.
