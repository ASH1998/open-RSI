# Verified SFT workflow primitives

`rsilab.learning` supplies provider-independent policy, immutable attempt
snapshots, repair-prompt construction, verified-target selection, and paired
comparison gates. It executes no candidate code, generation, training, or provider
call. Controllers continue to own budget reservations, durable storage, worker
invocations, independent verification, checkpoint exports, and rollback.

## Frozen policy and attempt collection

```python
from rsilab.learning import LearningPolicy, AttemptLedger

policy = LearningPolicy(retention_count=16)
ledger = AttemptLedger(train_tasks, excluded_tasks=dev_and_final_tasks, policy=policy)

initial = ledger.add(initial_record, source_run_id="greedy-run")
sample = ledger.add(sample_record, source_run_id="sample-run",
                    attempt_index=1, attempt_kind="sample")
# Only when both independent attempts failed, within the repair quota:
repair = ledger.add(repair_record, source_run_id="repair-run",
                    attempt_index=2, attempt_kind="repair",
                    parent_attempt_id=sample["attempt_id"])
```

`LearningPolicy` is a frozen dataclass with `to_dict()` and canonical JSON
`sha256`. Defaults require 24 unique targets, at least three categories, and at
most 60% from any category. The comparison uses 32 development tasks, defaults
to 32 retention tasks, and permits a preregistered positive retention count such
as 16. The promising threshold is at least three net development successes and
zero lost parent successes on retention. Thresholds cannot be weakened through
policy settings. Training seeds are 42 and conditional replication seed 43.

Each task receives two independent attempts, `initial` at index 0 and `sample`
at index 1. The second remains independent even after an initial success and has
no parent attempt ID. The controller's protocol binds the actual generation
settings: initial greedy generation and temperature-0.7 sampling with seed 31415
for this experiment. The ledger does not infer those settings from output text;
preserve worker provenance in the source run reports. At most one `repair` at
index 2 is allowed per task, for at most 32 tasks overall. Both earlier attempts
must be model failures; infrastructure failures do not authorize repairs. Repairs
link to the immediately preceding sample's content-derived attempt ID.

A raw record retains the existing controller shape:

```python
{
    "task": frozen_train_task,
    "generation": {"id": task_id, "text": raw_text, ...},
    "verification": verification_result,
    "verified_code": extracted_code,  # Required only for a selected success.
    # Other raw fields are preserved unchanged.
}
```

`add` returns a snapshot containing `attempt_id`, `source_run_id`, `attempt_index`,
`attempt_kind`, `parent_attempt_id`, `policy_sha256`, `task_sha256`, and the full
raw `record`. Failed attempts are retained, including infrastructure results.
The snapshots are deeply copied through `FrozenJSON`; mutating inputs or returned
dictionaries does not alter the ledger. `ledger.records` returns snapshot copies;
`ledger.to_dict()` includes the frozen training tasks, excluded-task digest,
policy, and every attempt. Persist those snapshots through the controller's
durable execution workflow. This in-memory ledger is not a disk journal.

Only exact tasks from the frozen training registry can be appended. Native
source metadata must also say `train` when present. Development/final/test tasks
cannot be relabeled through this API. The constructor rejects known overlap
against `excluded_tasks` by ID, whitespace-normalized public prompt, source row,
dataset/source ID, or supplied duplicate/cluster group. Supply the complete
excluded registry: the helper cannot discover unseen held-out tasks or perform
semantic near-duplicate detection. Category overlap alone is not a rejection and
does not imply family-held-out evaluation.

## Bounded repair prompts

```python
from rsilab.learning import build_repair_prompt

prompt = build_repair_prompt(task, previous_code, verification, policy=policy)
```

This requires a training task and a failed, non-infrastructure outcome. It uses
the public task prompt, up to 8,000 characters of previous code, and up to 1,200
characters of feedback. Feedback consists only of valid check counts, bounded
case indices with fixed categories (`wrong_output`, `execution_error`,
`invalid_result`), and fixed messages for token-limit/policy/execution failures.
Raw exception strings, stdout, returned values, expected values, reference code,
and authoritative tests are never copied from the verification/task evidence.

The final prompt is bounded to 16,000 characters by default. Oversized previous
code is explicitly marked as truncated. If the public task contract still makes
the prompt too long, the helper raises rather than silently truncating it. These
are character limits; the controller must additionally enforce tokenizer/input
token limits. The public prompt and previous code themselves remain caller-owned
inputs and are not a general secret-redaction boundary.

## Deterministic target selection

```python
from rsilab.learning import select_verified_targets

selection = select_verified_targets(ledger)
if not selection["eligible"]:
    # Persist the result and stop before training.
    ...
examples = [{"prompt": row["prompt"], "completion": row["completion"], "verified": True}
            for row in selection["selected"]]
```

Selection sorts task IDs and attempt indices, keeps the earliest verified
solution for each task, and deduplicates exact UTF-8 code bytes across tasks.
It does not search for a later alternative to evade deduplication. SFT inputs use
the original public task prompt; a failed attempt remains context/evidence, never
a completion label.

Selected code must occur in the raw generation, match the verifier's
`candidate_sha256` (SHA-256 of code bytes), and carry the task's
`source_tests_sha256`. Successful targets must share one evaluator version and
source-hash inventory. Complete generation flags, verification counts, and
consistent pass/fail flags are required; token-limit outputs cannot pass.

The result includes `selected`, `selected_count`, category counts/share,
`skipped`, `missing_task_ids`, `incomplete_task_ids`, `eligible`, `reasons`,
policy/ledger/evaluator lineage, and its own canonical digest in `sha256`.
Every task must have both independent attempts. Missing/incomplete/invalid
evidence, mixed target evaluators, too few labels/categories, or category
dominance block eligibility. Selected rows retain task/code/verification
digests, source run and attempt IDs, and repair-parent lineage.

This is an envelope and lineage audit, **not output rescoring**. Before calling
selection or comparison, the controller must independently recompute verifier
outcomes from saved outputs using the trusted evaluator. Digests detect changes;
they do not authenticate the producer or prove verifier correctness. Raw reports
and all attempts must remain available after selecting labels.

## Parent/candidate comparison contract

```python
from rsilab.learning import compare_learning_run

comparison = compare_learning_run(
    parent, candidate, tasks=ordered_dev_and_retention_tasks,
    retention_ids=frozen_retention_ids, policy=policy,
)
```

Each arm is a dictionary containing:

```python
{
    "run_id": "unique-run-id",
    "agent_id": "unique-agent-id",
    "adapter_sha256": None,  # Parent; candidate uses exported adapter byte SHA.
    "controls": {
        "generation": {
            "seed": 42, "temperature": 0.0, "max_new_tokens": 512,
            "max_input_tokens": 2048, "enable_thinking": False,
            "attempts_per_task": 1,
            # Additional matched settings, e.g. dtype/quantization, are allowed.
        },
        "evaluator": {"version": "version-id", "source_hashes": source_hashes},
        "model": {"model_id": "model-id", "revision": "immutable-40-hex-revision"},
        "hardware": "recorded accelerator identity",
        "packages": recorded_package_versions,
        "source_hashes": execution_source_hashes,
        "task_sha256": digest(ordered_dev_and_retention_tasks),
    },
    "records": [
        {"task": frozen_task, "generation": raw_generation,
         "verification": trusted_verification, "effective_seed": actual_task_seed},
    ],
}
```

The candidate also contains `training` with `seed`, `fresh_adapter: True`,
`parent_adapter_sha256: None`, `adapter_sha256` matching the arm, and
`selection_sha256`. The controller must verify the exported adapter bytes,
selection eligibility, fresh initialization, and training report provenance.
The helper checks these declarations without opening checkpoint files.

Task coverage/order and case evidence must be complete. Every untruncated
verification must match the arm's evaluator version/inventory. Per-task token
counts must stay within the recorded generation budget. Parent/candidate controls
and effective per-task seeds must match exactly. For a single 48-task batch,
record the actual 42-plus-index seed offsets in both arms; the helper does not
assume a 32-task rebatching scheme. Malformed/incomplete evidence raises;
otherwise differing controls return `matched: False` with no score comparison.

Matched reports contain per-task pairs, separate development/retention scores,
net development gain, and lost parent retention successes. Only a matched result
with at least three net gains on 32 development tasks and zero retention losses
is `promising`. Seed 42 can then set `replication_recommended: True` and
`next_training_seed: 43`. These fields recommend a separately budgeted action;
they never launch it.

Seed-43 comparison requires `initial_comparison=seed42_report`, with a matching
digest, policy, parent report, label selection, and promising seed-42 result.
Its fresh adapter must differ from the initial candidate. No further training
seed is recommended after replication. Every result retains the parent's agent
ID with `promoted: False`; a score gain is not sustained RSI or proof of
family-held-out generalization.

## Verification and handoff

Run the synthetic tests from the SSD project root:

```sh
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p test_learning.py -v
```

Tests cover immutable policy/records, independent attempts, repair lineage and
quota, raw failures, held-out leakage, feedback sanitization/bounds, code/test
binding, exact deduplication, diversity/coverage gates, matched inference
controls, retention losses, and conditional replication. They execute no
candidate, training, or provider code. Main owns controller integration and the
authorized experiment; packaging/CLI integration is deferred until that workflow
is verified. Frozen core/comparison/rescore sources remain unchanged.

Handoff verification: all 19 learning tests passed. Historical rescore and
robustness execution-source inventories still match their frozen protocols.
Only this module, its tests, and this document were added for the workflow task;
no dependency installation, paid job, or packaging change was performed.
