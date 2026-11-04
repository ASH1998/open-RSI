# Measuring successor-improvement ability

Updated November 4, 2026. The offline API and synthetic tests are implemented;
the experiment remains prospective. This chat owns only this document,
`rsilab/successor.py`, and `tests/test_successor.py`. No paid jobs, candidate-code
execution or frozen-source changes were performed here.

## Controlled question and claim scope

Compare original teacher T0 with experimental learned teacher T1 acting on the
same starting student S. Generate D0 and D1 from identical ordered training
tasks, public prompts, two independent attempts, effective seeds, inference
limits, runtime and verifier. No repairs or verifier feedback enter the second
attempt. Train C0 = Train(S, D0) and C1 = Train(S, D1), matching optimizer steps,
gradient accumulation, micro-batch size, sequence ceiling, seed, optimizer,
scheduler, adapter settings, hardware and packages. Evaluate S, C0 and C1 on the
same ordered dev/retention tasks under independent student inference controls.

Keep these measurements separate:

1. Teacher solve rate and verified-label yield, with category mix, unique solved
   tasks, selection exclusions, raw failures, tokens, time and cost.
2. Each child's gain over S and C1's gain over C0, including paired outcomes and
   individual retention losses. With shared S, the difference in gains equals
   the difference in child scores. This tests one-step successor ability.
3. Sustained recursion, which this experiment cannot establish. It needs later
   generations where a produced successor acts as an improver against its
   predecessor on another identical starting-student intervention, with positive
   successor gains repeated across generations and seeds.

Proposed T0 and S are the original MiniCPM5 parent. T1 is the rejected
verified-SFT seed42 adapter, byte SHA-256
`6c5d5f5df6701757a2e34cdfa229921fa03f27610b745c18b7ce8c222d55c772`.
Its retention gate failed; it remains an experimental teacher, never a promoted
parent. Both children start fresh from S, not T1. The intervention measures
verified-example teaching through a fixed trainer, not general research ability
or autonomous optimizer design.

## Prospective pilot, selection and gates

Independent domain review supports 24 fresh candidates. Main selected a
20-task probe with four reference-only fallbacks, two attempts per teacher and
at least 16 selected targets per teacher. Freeze the final 20 tasks after
reference calibration and before teacher generation. This is a small development
pilot that may stop at teacher feasibility. Counts are explicit configurable
fields of a new prospective policy; historical `LearningPolicy` and earlier
thresholds remain unchanged.

Before training either child, require complete evidence for both attempts on
every task, at least 16 unique verified targets in each arm, three categories,
and at most 60% from any category. The second attempt remains independent even
after a first success. Infrastructure/missing evidence blocks the audit. Do not
require better adapted-teacher yield: equal yield can still produce a better
child. Identical final example sequences stop an uninformative contrast.

Keep all unique eligible targets. Selection sorts task IDs, takes the earliest
verified attempt per task, and deduplicates exact UTF-8 code bytes. It never
seeks a later alternative to evade duplicate-code exclusions. Different data
counts and task mixtures are part of the teaching intervention and are reported.
Use fixed 16 optimizer steps and accumulation four, not per-arm epochs. Record
dataset supervised tokens and actual processed/supervised training tokens.
Equal steps and token ceilings do not imply equal actual token exposure. Avoid
post-hoc downsampling to equalize an observed result.

For 32 dev/16 retention tasks, the proposed gate requires C1 to gain at least
three net dev successes over C0 **and** three over S, with zero individual
retention successes lost from either S or C0. C0's own regressions are reported;
the gain-over-S gate prevents calling merely less harmful teaching useful.
Complete matching controls, lineage, evidence and budgets are required.

Every result retains S with `promoted=False` and `sustained_rsi=False`. A passing
pair recommends separately authorized replication. It does not launch seed43,
promote a child, or establish statistical significance. Small data and one
training seed limit stability/power; report paired counts. Replicating a seed
is not another recursive generation.

## Five-stage reservation envelope

| Stage | Maximum reservation | Condition |
| --- | ---: | --- |
| Reference calibration and matched S baseline | $5 | New protocol/worker bounds frozen |
| T0 teacher, two attempts | $5 | Audited dataset frozen |
| T1 teacher, same tasks/attempts/settings | $5 | Finish paired probe |
| T0 child and evaluation | $5 | Both datasets eligible |
| T1 child and evaluation | $5 | Same decision; finish paired evidence |

This is at most $25 of the reported $55 unallocated, leaving $30 unallocated
and the separate $25 overhead hold unchanged. Reservations are not invoice
totals or price estimates. Only main reserves through `rsi/budget.py` and
launches after establishing worker cost bounds. Failed reservations persist.
No retries, replication or later generations are included. The helper audits
supplied reservations; it does not reserve money, inspect the cumulative ledger,
terminate workers or reconcile provider billing.

## Exact API

```python
from rsilab.successor import (
    SuccessorPolicy, freeze_successor_protocol, inference_request_sha256,
    audit_improver_probe, compare_successors,
)
policy = SuccessorPolicy(train_count=20, min_targets=16)
protocol = freeze_successor_protocol(spec, policy=policy)
probe = audit_improver_probe(protocol, original_probe, learned_probe, policy=policy)
# Only if probe['eligible']:
comparison = compare_successors(protocol, probe, baseline,
                                original_child, learned_child, policy=policy)
```

The executable schema is in `tests/test_successor.py`: `protocol_fixture`,
`probe_fixture`, `child_fixture`, and `comparison_fixture`. These use synthetic
data and execute no candidate code. There are no project-controller, provider,
environment, torch or checkpoint-loading imports in this API.

`SuccessorPolicy` defaults (override training count with the reviewed count):

```python
train_count=40; dev_count=32; retention_count=16
min_targets=16; min_categories=3; max_category_share=0.60
min_teacher_advantage=3; min_starting_gain=3; training_seed=42
max_stage_reservation_usd=5.0; max_total_reservation_usd=25.0
```

Policy is immutable and canonically hashed. Changing counts or thresholds
requires a new protocol. All agent manifests have exactly these fields:

```python
{"agent_id": "stable-id", "model_id": "org/model", "revision": "40-hex",
 "tokenizer_revision": "40-hex", "adapter_sha256": None,
 "parent_agent_sha256": None}
```

For an adapter, supply its exported byte SHA and `digest(parent_manifest)`.
T1 must name T0 as its parent. Both children name S and have distinct new
adapter/agent identities. Teacher/student roles stay separate even when T0=S.

Protocol fields:

```python
{"schema_version": 1, "policy": policy.to_dict(),
 "teachers": {"original": T0, "learned": T1}, "starting_student": S,
 "selection": "all_unique_earliest_verified", "teacher_context_sha256": digest([]),
 "exclusion_registry_complete": True, "prior_exposure_registry_complete": True,
 "registries": {"train": [...], "dev": [...], "retention": [...],
                "sealed_final": [...], "prior_exposure": [...]},
 "controls": {"teacher": [initial_controls, sample_controls],
              "student_evaluation": eval_controls, "student_training": train_controls}}
```

Active tasks retain the learning-record shape: `id`, public `prompt`, `category`,
`split`, authoritative `cases`, `source_tests_sha256`, and `metadata` with native
`dataset`, `source_id`, `source_split`. Dev uses `split='dev'` and source-native
`validation`/`dev`; training/retention use native `train`. Preserve source-row and
duplicate-cluster identities. Prior exposure needs public identity records, not
reference code or cases.

Sealed final can use metadata-only source descriptors; **do not read final
prompts or decode final Parquet** to satisfy the API:

```python
{"dataset": "google-research-datasets/mbpp", "revision": "40-hex",
 "source_split": "test", "count": 500, "file_sha256": "64-hex"}
```

Known explicit final identity records (`id`, `prompt`, optional metadata) are
accepted if already available, but never required. All active tasks must be
source-native train or validation/dev. Known overlap checks use ID, normalized
prompt, native source ID, source-row hash and provided duplicate-group/cluster
IDs. Fresh training must also avoid recorded prior exposure. Exposed dev IDs
are disclosed. Source descriptors cannot reveal unknown semantic duplicates
with sealed content; registry completeness and duplicate discovery remain
controller duties.

Inference controls are normalized **actual worker controls**, bound to raw
provider requests/results by the controller:

```python
{"generation": {"seed": 42, "temperature": 0.0, "max_input_tokens": 2048,
                "max_new_tokens": 512, "enable_thinking": False},
 "runtime": {"hardware": "NVIDIA L40S", "precision": "nf4-bfloat16",
             "packages": {...}, "source_hashes": {"worker.py": "64-hex"}},
 "evaluator": {"version": "mbpp-typed-v2", "source_hashes": {...}},
 "effective_seeds": [...]}  # Exact ordered task seeds, including rebatching.
```

Training controls are exactly `steps`, `gradient_accumulation`,
`micro_batch_size`, `max_length`, `learning_rate`, `optimizer`, `scheduler`
(`"none"` if unused), `adapter_config` (complete actual configuration), and
`runtime` as above. Student evaluation does not inherit teacher sampling.

A collection has `status='completed'`, `agent`, `controls`, full `records`, and
`request_sha256=inference_request_sha256(agent, controls, ordered_tasks)`.
This binds a normalized public-only request, not the provider's raw request;
preserve both digests in controller reports. Rows contain full `task`, raw
`generation`, trusted `verification`, `effective_seed`, and `verified_code` for
successes. Existing generation flags, counts, typed outputs, evaluator inventory
and code/test hashes are audited. Records cover every ordered task, including
failures/truncations.

All five stage envelopes share:

```python
{"run_id": "unique-stage", "protocol_sha256": protocol["sha256"],
 "reservation": {"id": "unique-ledger-reservation", "amount_usd": 5.0},
 "usage": {"input_tokens": 123, "output_tokens": 456,
           "wall_seconds": 1.2, "estimated_cost_usd": 0.1},
 "artifact_inventory": {"report.json": "64-hex", ...},
 "artifacts_verified": True, "outputs_rescored": True}
```

Token totals equal the envelope's raw generation/evaluation rows. Training
tokens are separate below. Time/cost cover the whole stage, including calibration
for baseline or training for children. The two `True` flags assert actual
controller checks; they are not substitutes for those checks.

Probe envelope adds `teacher`, `collections=[first, second]`; each collection
adds `attempt_index` 0/1. No repairs. The audit reconstructs selection and keeps
raw evidence under `probe['arms'][role]['evidence']`, alongside `selection`,
`examples_sha256`, yields and matching/eligibility reasons. Training examples
are selected rows projected to `prompt`, `completion`, `verified`, in returned
order. This is a new selector/policy, not a weakened historical learning gate.

Baseline adds `evaluation`, containing S's collection. Each child adds
`teacher`, `starting_student`, new `agent`, `evaluation`, and `training`:

```python
{"status": "completed", "initialization": "fresh", "resume_checkpoint_sha256": None,
 "seed": policy.training_seed,
 "selection_sha256": probe["arms"][role]["selection"]["sha256"],
 "examples_sha256": probe["arms"][role]["examples_sha256"], "examples_count": 16,
 "controls": actual_training_controls, "steps_completed": 16,
 "dataset_supervised_tokens": 1000,  # Once over selected dataset.
 "processed_tokens": 6000, "supervised_tokens": 3000,  # Actual optimizer work.
 "checkpoint": {"complete": True, "step": 16, "adapter_sha256": "64-hex",
                "training_state_sha256": "64-hex", "metadata_sha256": "64-hex",
                "manifest_sha256": "64-hex", "optimizer_state": True, "rng_state": True,
                "scheduler_state": "not_used"}}  # Or "included" when scheduler used.
```

All four checkpoint hashes must occur in the verified artifact inventory.
The controller hashes real exported bytes and checks manifest/state provenance;
the helper never opens/unpickles checkpoints. Saved state does not prove resume
was tested. Derive token accounting from actual training/tokenization, not from
ceilings presented as measurements.

## Audit limits, verification and handoff

Malformed/incomplete/tampered evidence fails closed. Complete but mismatched
comparisons have `matched=False`, empty comparative scores/pairs and no gate.
Per-arm descriptive probe yields may still be reported, but unmatched probes
cannot authorize children. Comparison replays the full probe rather than
trusting its `eligible` flag or selected totals.

Matched results report yields separately from child scores, actual data/token
exposure, input digests, the gate and
`replication_requires_new_protocol_and_budget=True`. This version audits one
complete pair. It does not accept an opaque prior-success flag as replication
or recursion evidence; those need a future explicit multi-pair contract.

Controllers must independently recompute typed outcomes, bind actual controls,
verify bytes, persist reports and enforce global budget/isolation. Hashes detect
changes; they do not authenticate malicious producers, prove reference semantic
correctness, discover unknown duplicates or prove absence of hidden history.

Synthetic tests cover replay, yield-vs-successor distinction, configurable
counts, immutable snapshots, teacher/student/adapter substitution, freshness,
source-native splits, metadata-only final exclusion, raw failure completeness,
controls/seeds, checkpoint completeness, retention gates and malformed resource
accounting. Run from the SSD workspace:

```sh
.venv/bin/python -B -m unittest discover -s tests -p test_successor.py -v
```

Handoff validation: 21 successor tests and 19 existing learning tests passed;
the 20-task/16-target policy is covered. All 17 source hashes in the completed
verified-SFT protocol still match. No real successor experiment or checkpoint
resume was run by this chat. The main controller/portable worker are under
concurrent integration; the review handoff identifies prelaunch compatibility
and evidence-binding checks separately from these offline API results.

Main owns protocol/controller, actual worker mappings, packaging/CLI, work-log
and paid launches. Next milestone: freeze the reviewed task count and complete
controller envelope integration/offline replay before any reservation.
