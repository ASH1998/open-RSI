# Reference-audited coding data

Implemented November 4, 2026 in `rsilab.coding_data`. This is offline preparation
for a prospective better-data experiment. No new model/reference execution,
training labels, or measured learning result is produced by these functions.
All local work remains on the project SSD; only the main controller starts paid
stages under the separately authorized four-stage/$20 experiment envelope.

## Source, splits, and feasibility

The default pool is the immutable full MBPP importer result
`13907d86dc89f61a1bfb06d691415984b6efd0304d5b321b914d787d8873b49f`,
dataset `google-research-datasets/mbpp`, revision
`4bb6404fdc6cacfda99d4ac4205087b89d32030c`. Attribution: Google Research and
Austin et al., *Program Synthesis with Large Language Models* (2021), CC-BY-4.0.
Original reference code, assertions, raw source bytes, and previous studies remain
immutable. Filtering and additional assertions are explicitly recorded changes.

The existing importer screened all four native splits using exact normalized
text, canonical reference AST, and conservative near-text duplicate components.
This module consumes that pinned result; it does not rescan or expose sealed test
prompts. It checks single-source-split cluster membership and retained lowest IDs,
preserves the importer exclusions, reapplies the sealed pilot-domain prompt rule,
and excludes the four manually identified near duplicates 955/541 and 629/554.
These heuristics do not prove semantic deduplication or family disjointness.

Training uses only native train; development uses only native validation. Prior
development/nontraining IDs, row hashes and duplicate-cluster IDs cannot enter
training. Pass **all historical task manifests**, deduplicated by ID, as
`previous_tasks`; incomplete history cannot establish absence of prior exposure.
The seven post-hoc diagnostic tasks 512/520/557/558/568/576/928 are excluded from
both new splits. Main's retention IDs must be passed through `train_excluded_ids`:
742, 890, 711, 835, 771, 686, 854, 621, 873, 715, 849, 861, 898, 665, 616, 648,
with the `mbpp-full-` prefix. Their original v2 tests remain unchanged elsewhere.

`sealed_final` records native test **500 rows** and file SHA-256
`566fd53060ffba5766dace1d1e2f4c38906781526de222b0dfbdbc325b696c77`.
It contains no test prompts or reference code. The package does not open or execute
that split. The source prompt split is likewise never sampled.

The versioned taxonomy is collections, text, numeric, other, using the original
study's description-keyword precedence. These are broad categories, not independent
algorithm families. Selection round-robins categories, reallocating exhausted
buckets, with seed-hashed order inside each. Development tasks with no recorded
generation precede previously exposed tasks. Native-split category overlap and
past development exposure must be reported; this is not a new held-out benchmark.

Observed **pre-review feasibility**, using the earlier passing-reference allowlist,
the 16 retention exclusions, and the implemented static mutation guards:

| Split | Eligible before audit cap | Bounded audit pool | Provisional selected categories |
| --- | ---: | ---: | --- |
| Train | 202 | 192 | 96: collections 28, text 28, numeric 28, other 12 |
| Development | 47 | 47 | 32: collections 8, text 9, numeric 13, other 2 |

Only **13/47** development tasks have no recorded earlier generation; the proposed
32 therefore reuse 19 development tasks. These counts are **not semantic approval
or a prediction of reference-pass yield**. Independent task/probe review may
reduce them before the paid plan is frozen. In particular, only two development
tasks fall in the broad “other” category, so the four-category gate is fragile.
If reviewed capacity cannot support 96/32, change the target prospectively before
freezing; do not weaken review or lower the three-case gate after seeing results.

## Stable API

All return values are JSON-compatible dictionaries; no function reads/writes
files, loads credentials, launches jobs, or executes source code.

```python
from rsilab.coding_data import (
    select_mbpp_tasks, audit_pool, propose_mutations, build_probe_task,
    audit_reference_task, freeze_verified_dataset,
)

selection = select_mbpp_tasks(
    importer_pool,
    previous_tasks=previous_manifest["tasks"],
    train_count=96, dev_count=32, seed=43,
    eligible_ids=independently_reviewed_task_ids,
    train_excluded_ids=retention_ids,
)
inventory = audit_pool(selection)
proposal = propose_mutations(inventory[0], seed=43)  # max_mutations fixed at 12
probe_task = build_probe_task(
    inventory[0], proposal,
    approved_mutation_ids=review["approved_mutation_ids"],
)
```

`eligible_ids` is an optional **prospectively frozen** allowlist from independent
reference/domain review, never model scores. The default pin cannot be replaced
silently; `expected_pool_sha256` is an explicit override for separately reviewed
importer results or synthetic tests, not a request to download a different source.

The selection contains initial `tasks`, bounded `reserve_tasks`, requested counts,
exclusions, exposure tags, duplicate provenance, sealed-final inventory and its
canonical `sha256`. `audit_pool(selection)` returns each split's initial tasks
followed by reserves, at most **192 train / 64 dev**. That complete order is the
prospective fallback policy. Preserve it and its hash before any paid audit.

The controller must also freeze the complete independent review file, including
approved mutation IDs and review notes, in its protocol. The library checks the
review's task/proposal/reference identities; the controller must enforce that this
is the same review file frozen before execution. No approval is manufactured from
a successful reference output or from a candidate answer.

## Input-only proposals and domain review

`propose_mutations(task, seed=43, max_mutations=12)` validates original compiled
cases against their source assertions, then emits at most 12 distinct typed calls
with no expectations. Each proposal has an ID, typed args/kwargs, unchanged source
projections, source-case index, mutation method/site, and canonical hash.
Original calls and duplicate proposed calls are removed regardless of projections.
The seed, 12-call cap, ordering and mutation policy must be frozen before audit.

Static necessary guards:

- Integer sites are bounded to 0..1000. Positive inputs stay positive; bools,
  floats and negative integers are untouched.
- Nonempty ASCII strings of at most 128 characters substitute only within their
  own observed lowercase/uppercase alphabets. Length, case positions, digits and
  punctuation remain unchanged; empty strings are untouched.
- Nonempty lists/tuples of length at most 32 permit bounded element changes or
  permutations, with nesting depth capped at four. Container types, nested shape,
  lengths and existing monotone integer-sequence order are preserved.
- Integer parameters alongside containers stay fixed because they may be lengths,
  indices or bounds. Tasks with multiple container arguments produce no generic
  proposals because those containers may encode coupled constraints.
- Dictionaries, sets, unsupported scalar domains, and calls with fewer than three
  distinct proposals are not generically augmented.

These rules do **not** establish semantic input validity. Examples include indices
embedded in data, required uniqueness, specialized string languages, mathematical
constraints, or relational scalar arguments. An independent reviewer must inspect
the pinned reference/specification and each proposed call. The review explicitly
lists approved IDs; unapproved calls must never reach a remote probe. It is valid
to exclude a task entirely. Reference exceptions alone cannot detect all invalid
domains because a reference may return a plausible value on invalid input.

`build_probe_task` requires `approved_mutation_ids`; it rejects unknown/duplicate
IDs, retains proposal order, and maps outputs through
`metadata.probe_mutation_ids`. It builds a v2-compatible **reference-only** task
whose `None` expectations are explicitly non-authoritative placeholders. Ignore
its aggregate score. Never score a model against this probe task or use it as a
dataset task; only its remote reference outputs may enter the audit below.

## Calibration and evidence contract

Before probes, run the pinned reference on **all unchanged original cases** in a
credential-free remote sandbox and require calibration success. The controller
must enforce this chronological gate. Never execute dataset reference/candidate
code locally. A returned original calibration failure is an ineligible audit
record; no probes may accompany it. Infrastructure/identity failures block dataset
finalization and must be preserved separately by the durable executor.

```python
review = {
    "approved": True,
    "task_sha256": digest(original_task),
    "proposal_sha256": proposal["sha256"],
    "reference_sha256": extracted_reference_code_sha256,
    "reviewer": "actual independent reviewer identity",
    "notes": "actual specification/reference/domain review findings",
    "approved_mutation_ids": approved_ids,
    "mutation_exclusion_reasons": {excluded_id: "actual domain concern"},
}
```

`reference_sha256` is SHA-256 of the verifier-extracted reference source string,
matching its `candidate_sha256`; preserve raw source/hash separately in the
controller. `original_result` is the full v2 calibration verification result.
For each **approved** mutation, supply exactly one record:

```python
{
    "id": mutation_id,
    "output": {"ok": True, "value": typed_remote_output},
    "reference_sha256": extracted_reference_code_sha256,
    "proposal_sha256": proposal["sha256"],
    "evaluator_source_hashes": original_result["evaluator_source_hashes"],
    "sandbox_id": actual_probe_sandbox_id,
}
```

For a candidate-call or encoding exception, preserve the original output envelope
(`ok=False`, error and error-stage) instead. Do not fabricate successful outputs or
drop failed rows. Missing/duplicate/extra results, wrong hashes, infrastructure
errors and mismatched evaluator identities fail closed.

```python
audited = audit_reference_task(
    original_task, proposal,
    reference_sha256=extracted_reference_code_sha256,
    original_result=original_result,
    mutation_results=all_approved_probe_results,
    review=review,
)
```

The audit recomputes calibration from saved typed outputs, validates identity and
coverage, applies unchanged source projections to successful probe outputs, and
accepts only values losslessly representable by the v1 literal/expectation codec.
Extended Counter/OrderedDict/defaultdict values are **not coerced** to plain dicts.
A source projection such as `list` may explicitly yield an encodable value.
Expected root type must match that source case's original expectation type.
Unsupported/type-changing values and reference errors remain recorded rejections.
At least **three distinct valid additional calls** are required for eligibility.

Successful expectations become deterministic literal equality assertions appended
to `challenge_test_list`. Original regular and challenge assertions, projections,
and typed cases remain an unchanged prefix. The compiler recomputes case indices,
counts and combined test hash. Task IDs remain the source IDs within this new
dataset; dataset hashes and `metadata.verified_data` distinguish the augmentation.
No reference code is returned as a training completion.

## Finalization and checks

```python
frozen = freeze_verified_dataset(selection, audits_for_exact_audit_pool)
```

Finalization revalidates complete evidence for every task in the frozen bounded
pool, including failed references/reviews and rejected probes. It takes the first
eligible 96 train / 32 dev tasks in the frozen per-split order. No candidate scores
participate. Insufficient eligible counts or loss of a category fails the gate;
no silent shrinking, weakened minimum, or unplanned replacement occurs.

Persist the returned final manifest/hash **before any model generation**. It
records final tasks, split hashes/counts, category counts, selected prior-dev reuse,
all audit hashes/exclusions, and sealed-final identity. `ready_for_generation=True`
means the reference-evidence gates passed; it is not proof the controller persisted
the manifest. `ready_for_training` remains false: SFT labels require separately
verified candidate outputs on this frozen combined suite.

Reference-derived augmentation is stronger coverage, **not proof of reference
correctness**. Tests derived from an independently reviewed reference can still
share its bugs. Public MBPP pretraining contamination remains unresolved; native
split separation and heuristic duplicate exclusions do not eliminate it.

Local validation: 15 synthetic unit tests cover pins/leakage, deterministic bounded
selection, exposure/retention, domain guards, subset-only probes, calibration and
identity failures, distinct-input thresholds, codec/projection constraints,
original-case preservation, full-pool finalization and prospective fallback.
No real candidate/reference source executes in those tests. Local actual-pool
inspection established the pre-review counts above, not semantic approval or
remote reference success. Next milestone: finish independent review, freeze its
inventory/subsets and the bounded audit plan, then main runs the reserved remote
reference stage and freezes the resulting final dataset before generation.
