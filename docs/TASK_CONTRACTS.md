# Reviewing task wording and hidden boundary cases

Use `rsilab.task_contracts` to derive training tasks from an ordered, audited MBPP cohort and an independent review. Supply the same ordered sources and reviews to replay a saved manifest. The API uses the existing MBPP compiler and returns ordinary JSON-compatible dictionaries. All three operations run offline.

## Apply a review

```python
from rsilab.task_contracts import apply_task_contracts

manifest = apply_task_contracts(original_tasks, reviews)
public_batch = manifest["prompts"]
evaluator_tasks = manifest["tasks"]
```

Supply one review per source task, in the same order, with these five fields.

| Field | Meaning |
| --- | --- |
| `task_id` | The exact, unique source task ID. |
| `source_sha256` | `rsilab.digest(original_task)`, including its metadata, prompt and complete case inventory. |
| `clarified_prompt` | A replacement description, or a full prompt retaining the original policy paragraph and exact required signature. |
| `review_note` | A nonempty, private explanation of the review. Keep the review artifact for replay. |
| `boundaries` | An ordered list of objects with exactly `name`, `call`, and `expected`. An empty list supports wording-only changes. |

Each boundary has a unique name within its task. Write `call` as a direct call to the entry point using the MBPP compiler's bounded literal argument grammar. Write `expected` as a canonical tagged value, for example `["bool", false]` for a boolean in JSON or `["int", 0]` for an integer. Construct tagged values in Python with `rsi.mbpp_verification.encode_value`. The reviewer supplies expected values independently of model or candidate output.

Source records must have native training split metadata and the existing audited prompt format, including a fixed positional-or-keyword function signature. The library recompiles the original regular and challenge assertions and checks their complete compiled fields against the source. It then appends reviewed direct-call cases as challenges. Original case order, projection rules, indices and expectations are preserved, including inherited repetitions or multiple projections of the same input.

A new boundary must bind valid arguments and introduce a new input. Positional and equivalent keyword spellings identify the same call. The library rejects repeated names, duplicate or conflicting added inputs, malformed typed values, changed signatures and evaluator limit violations. Record failures raise `ValueError` with the task's review index.

Use only `manifest["prompts"]` for generation. Each row has exactly `id` and `prompt`. Reviewed notes, cases, expected outputs and lineage belong in the trusted environment. The prompt check extracts parseable literal calls to the entry point from prose, binds their arguments and rejects any matching a new hidden boundary. It catches whitespace and positional/keyword variations. Reviewers must also inspect clarified prompts for paraphrased examples, indirect calls, computed expressions or other wording that reveals hidden answers.

## Manifest and lineage

| Key | Contents |
| --- | --- |
| `version` | `mbpp-task-contracts-v1` |
| `source_sha256` | Digest of the ordered input task list |
| `reviews_sha256` | Digest of the ordered review list, including private notes and boundary expectations |
| `tasks` | Independent, evaluator-ready copies with clarified prompts and all compiled cases |
| `prompts` | Generation rows in source order |
| `lineage` | Per-task source, review, derived-task and test hashes, source case count, and each boundary's name, index and case digest |
| `sha256` | Digest of the preceding manifest fields |

Inherited `metadata.verified_data` describes the **source** audit and its historical reference-derived cases. For a newly reviewed boundary, use its lineage entry and separate calibration evidence. Applying a human review establishes the derivation. Reference calibration separately runs a pinned reference in an approved executor and compares its outputs to the hand-authored expectations.

```python
from rsilab.task_contracts import replay_task_contracts

verified = replay_task_contracts(
    original_tasks, reviews, saved_manifest,
    expected_sha256=independently_recorded_manifest_sha256,
)
```

Replay rebuilds the whole manifest and returns a fresh copy only when its contents match. The optional external pin binds the result to the specific previously recorded artifact. Retain that pin independently alongside the source and review files. A digest identifies content. Source authenticity and review independence depend on how the caller obtained those inputs.

## Score saved or isolated outputs

```python
from rsilab.task_contracts import score_task_contract_outputs

score = score_task_contract_outputs(
    verified, task_id, outputs,
    expected_sha256=independently_recorded_manifest_sha256,
)
```

Pass all outputs in the task's compiled case order, using the existing V2 executor transport. A success is `{"ok": True, "value": encoded_value}`. Obtain actual outputs from the isolated reference or candidate run. The score function takes data only and checks the manifest seal, selected task identity and boundary indices.

Inherited cases keep V2 scoring, including their original projections and Python equality. New boundaries additionally require recursive type-tag agreement. For example, integer `1` can pass an inherited `True` expectation under historical equality, while the reviewed boolean boundary requires `["bool", true]`. Lists and tuples retain distinct tags at every depth. Plain mappings match regardless of insertion order, with types checked in both keys and values. Sets compare typed members without regard to order. Registered mapping subclasses carry their own tags in V2 transport.

The result includes `scorer_version` (`task-contract-output-score-v1`), `manifest_sha256`, `task_id`, `passed`, `count`, `total`, `errors`, `case_diagnostics`, `source_passed_count`, `source_total`, `boundary_passed_count`, and `boundary_total`. A type mismatch that historical equality accepted is reported as `wrong_typed_output` at its case index. An incomplete output list returns `invalid_output_count` with zero passes.

The standalone example uses synthetic records and saved outputs and prints only the generation row, counts and manifest identity. From an environment with the module installed, run `python -I examples/task_contracts.py`. [Example](../examples/task_contracts.py)
