# MBPP verifier v2: mapping-subclass transport

November 4, 2026. This is an evaluator correction for rescoring saved outputs,
not another model generation/training experiment. No v2 remote verification was
launched by the verifier chat. Main owns budget reservations, calibration,
reference audits, saved-candidate execution, and final reporting.

## Frozen input and integration interface

```python
from rsi.mbpp_verification_v2 import (
    MBPP_VERIFIER_VERSION, calibration_cases, evaluator_source_hashes,
    verify_mbpp_candidate,
)

inventory = evaluator_source_hashes()
fixtures = calibration_cases()
# After main reserves the stage and freezes the source inventory:
# result = verify_mbpp_candidate(saved_response, original_v1_task, app)
```

`MBPP_VERIFIER_VERSION` and `VERIFIER_VERSION` are `mbpp-typed-v2`.
`verify_mbpp_candidate(code, task, app, timeout=30)` accepts **the unchanged,
validated v1-compiled task** (`verification_mode="mbpp_typed_v1"`, compiler
version `mbpp-typed-v1`). It never rewrites task fields, expected values, test
counts, cases, projections, or task IDs. The result identifies v2 through
`verifier_version`; `source_compiler_version` remains `mbpp-typed-v1`.
The old `verification.verify_candidate` dispatcher remains untouched: callers
must import the new runner explicitly.

Results retain v1's scoring/provenance fields and add `evaluator_source_hashes`
and `case_diagnostics`. `evaluator_source_hashes()` returns SHA-256 values keyed
by `rsi/mbpp_verification_v2.py`, `rsi/mbpp_verification.py`,
`rsi/verification.py`, and `child_source`. The latter hashes the exact constructed
remote harness. The controller must separately hash itself and its other helpers,
freeze this inventory before launching, and reject source drift. Source-file
hashes assume immutable files during the run; they do not attest arbitrary
previously imported process state.

The v1 source files remain byte-identical:

| File | SHA-256 |
| --- | --- |
| `rsi/verification.py` | `b6cd4334adf34678f7f35f908a38a14329ca9a81b6b4d557eb4de270868b0db4` |
| `rsi/mbpp_verification.py` | `47efce04acdef807e54a49f1ecbd64942a31baa2ce9e7d7404fd62326e660bc4` |

## Systematic failure inspection

The read-only review covered **368 saved responses**: 176 parent, 80 per adapter,
and 32 separate Kaggle outputs. The v1 raw records contain 28 responses with at
least one per-case `ValueError` (82 such case errors). Source inspection finds
20 of those responses returning the newly supported mapping types: 14 `Counter`,
four `defaultdict`, and two `OrderedDict` responses. The remaining eight involve
returned functions, a dictionary view, invalid `namedtuple` construction, a math
domain error, or unpacking errors. This is a static diagnosis: v1 combined
candidate exceptions and serialization failures under the same error field, and
no candidate was executed locally to infer a new score.

The only saved dictionary-view transport failure found is parent task
`mbpp-full-709`, returning `Counter(...).keys()` against expected strings with
no wrapper projection. Ordinary Python equality would also reject that result.
Other saved `.keys()/.values()/.items()` failure sources encounter errors before
returning a view (such as an undefined module or indexing a values view).
No saved view-under-`set`/`list` false negative was identified.

## What the codec changes

The original finite builtin types and their wire representations are retained.
Three **exact** standard-library classes are added, recursively:

| Python type | Wire tag | Reconstruction/equality behavior |
| --- | --- | --- |
| `collections.OrderedDict` | `ordered_dict` | Preserve its current insertion order, including `move_to_end`; equality with builtin dicts ignores order, while two OrderedDicts retain order-sensitive equality. |
| `collections.defaultdict` | `default_dict` | Preserve entries and order; reconstruct with factory `None`. The factory is never serialized, invoked, or reconstructed. Equality and the permitted iterable projections do not need it. |
| `collections.Counter` | `counter` | Preserve exact key/value entries, including explicit zero and negative counts; reconstruct as Counter, not by counting encoded pairs. |

These rules follow the [Python 3.11 collections documentation](https://docs.python.org/3.11/library/collections.html).
In particular, `Counter(a=1, b=0) == Counter(a=1)` is true, but
`Counter(a=1, b=0) == {"a": 1}` is false. Flattening every mapping to a plain dict
or dropping zero entries would change Python semantics, so v2 does neither.
Expected values still decode through the original v1 codec and remain exact
literal builtins. Numeric comparison retains Python `==`, with no added tolerance.

The encoder checks exact type identity before traversal; arbitrary subclasses,
metaclass hooks, custom comparisons, and generic `Mapping`/`Iterable` conversion
are not accepted. It uses known mapping implementations rather than an instance's
overridden `items` method. The parent builds only its own trusted standard-library
objects from data. Candidate-defined classes, factories, methods, instance
attributes, or pickle payloads cannot be restored in the controller.

Dictionary views remain unsupported return values in this bounded correction.
Python keys/items views have set-like equality, whereas values views do not equal
lists; blindly turning every view into a list would accept invalid solutions.
See [Python dictionary views](https://docs.python.org/3.11/library/stdtypes.html#dictionary-view-objects).
Arbitrary subclasses, functions, generators, other iterators, arrays, bytes,
complex values, and non-finite numbers remain unsupported. Supporting those
later requires another scoped compatibility decision and audit; v2 does not claim
to execute the entire Python/MBPP language.

## Diagnostics and unchanged isolation

The child now separates raw failure records with `error_stage`:

- `candidate_call`: argument decoding or candidate invocation raised.
- `encode`: encoding the returned value or enforcing its per-case size failed.

The parent adds `case_diagnostics` entries with `case_index`, `error_stage`, and
an error class/reason, using `decode`, `projection_comparison`, or `output` as
appropriate. Wrong values are `projection_comparison` / `wrong_output`.
No exception message is included. Candidate-origin diagnostics are untrusted
claims; they cannot establish a pass or supersede parent comparison. Aggregate
process/timeout failures continue to use the existing shared transport errors.

All bounds and candidate policies are unchanged: the same import allowlist,
entry-point/AST checks, 0.125 CPU and 512 MiB sandbox caps, gVisor, network blocking,
empty secrets/environment/mounts, no identity token, 30-second maximum sandbox
lifetime, 8-second child wall limit, and Linux CPU/address-space/file limits.
Typed values retain depth 8, 4,096 nodes, 4,096-bit integers and 24,000-byte strings.
Per-case output is limited to 8,192 bytes, aggregate output to 65,536 bytes,
and launch payload to 128,000 bytes. Duplicate encoded mapping keys/set entries
are rejected. Termination still runs after success/failure and cleanup errors
force an unsuccessful infrastructure verdict.

Only candidate source, entry point, and encoded arguments enter the sandbox.
The exact expected values, test source, projections, reference code, metadata,
and parent scorer remain outside candidate-writable paths. Python AST checks and
the child interpreter are not security boundaries; the remote sandbox and
independent parent scoring remain the boundaries.

## Local evidence and remote calibration gate

Run from the SSD workspace:

```sh
TMPDIR="$PWD/.cache/tmp" XDG_CACHE_HOME="$PWD/.cache" \
  .venv/bin/python -B -m unittest discover -s tests -p 'test*verification*.py' -q
```

**103 tests pass: 38 v2 tests plus the 65 unchanged v1 verifier tests.** Synthetic
fixtures test nested mappings, numeric/non-string keys, OrderedDict ordering,
Counter zero/negative counts, factory omission, rejected custom subclasses and
metaclass hooks, original wire compatibility, depth/size limits, parent scoring,
phase diagnostics, payload secrecy, immutable task input, source inventories,
unchanged sandbox limits, and cleanup failure. The custom-subclass calibration
passes original AST policy and reaches the mocked transport; its actual remote
codec behavior is deliberately left to calibration. No saved candidate/reference
source or constructed child source is executed locally.

`calibration_cases()` returns 12 hand-authored checks: six expected successes
and six expected failures. Each record contains `id`, `code`, v1-format `task`,
`expected_passed`, `expected_count`, and, where relevant,
`expected_error_stage` (`candidate_call` or `encode`). The fixtures cover builtin
identity, nested OrderedDict, current OrderedDict iteration order, unused raising
default factory, Counter mappings, nested mixed mappings, wrong mapping values,
explicit Counter zero-key mismatch, tuple/list mismatch, custom subclass rejection,
callable-return rejection, and a genuine candidate exception.

Main should reserve the calibration/reference stage, run these plus its independent
controls, compare exact pass/count/stage expectations, and audit all 176 frozen
reference tasks. Any unexplained reference regression or calibration failure
blocks saved-candidate rescoring. After that gate, rerun the same saved model
responses under v2, retaining the original v1 records and token/time-limit rules.
Do not regenerate completions, alter frozen task identities, retrain adapters,
retroactively change the training-label selection, or promote a model from a
partially rescored comparison. Report v1 and v2 outcomes side by side, including
task-level changes and unchanged failures, once all arms finish.

This handoff adds only `rsi/mbpp_verification_v2.py`,
`tests/test_mbpp_verification_v2.py`, and this document. No paid job, local saved-code
execution, credential read, or Git commit was performed by this chat.
