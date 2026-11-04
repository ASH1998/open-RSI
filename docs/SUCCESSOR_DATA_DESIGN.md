# Successor experiment: data review and feasibility

Status: manual data review completed on November 4, 2026. Main selected a
20-task design from the 24-task audit pool before paid work. This document does
not itself freeze a study, launch work, or report successor results.
Owned artifacts are this document and `work/successor-design-data.json`.

## Decision supported by the review

The current generic-proposal pool supports **24 tasks for remote reference
audit**, with **261 explicitly approved additional calls**. The requested
32- or 40-task cohort is not available from these reviewed proposals.
The 24 tasks span collections (13), numeric (8), and text (3). There is no
fourth category; none should be invented or forced into the cohort.

These are input/domain approvals, not remotely verified expectations.
Every selected task still needs a passing original-reference calibration and
at least three accepted additional calls under the unchanged typed evaluator.
Reference success is evidence for these tests, not proof of oracle correctness.
No reference or model-generated code was executed in this review.

The inventory contains exact mutation IDs, per-exclusion reasons, task/proposal/
extracted-reference SHA bindings, and `audit_reference_task`-compatible
`successor_review` records for all 52 inspected tasks. Its current canonical
SHA is `958d94195798fe876fdbc9bf8c67d06dc7560c15aa7c4f24cd3f0f10baf40424`.
It also contains 264 public historical exposure records from 19 saved generating
reports: 240 MBPP tasks and 24 synthetic pilot tasks. These omit test cases,
completions, and reference code. Source report hashes and per-task generating
run IDs remain recorded separately.

Main's decision is to audit all 24 and select the first 20 eligible tasks,
requiring at least three categories. Four tasks serve as reference-only
fallbacks. Stop before model generation if those conditions fail. The explicit
order is category round-robin (collections, text, numeric, other), preserving
the earlier deterministic seed20261104 rank within each category:

```text
613 757 661 916 885 863 929 619 641 844 789 610
681 816 687 633 675 611 745 734 805 915 744 780
```

All IDs above have prefix `mbpp-full-`. If all pass remote audit, the first 20
contain nine collections, eight numeric, and three text tasks. Main owns the
protocol freeze. Fallbacks must be selected from reference-only evidence before
any model outcomes; they cannot fill holes after seeing teacher failures.

## Freshness and exclusions

The earlier 46 MBPP labels and verified-SFT run's 47 labels overlap on 16 IDs,
giving 77 distinct previously trained MBPP tasks, plus four synthetic masked-mean
labels. A label-disjoint pool alone would retain previously attempted failures
and could select for difficulty. The current requirement instead excludes every
task with recorded model generation, whether successful or not, along with old
and current development, all 32 historical retention tasks, diagnostics, and
known duplicate identities/clusters/rows.

Before the new manual review, 87 native-train candidates remained never
generated, 73 had a saved original-reference pass, and 52 had at least three
generic proposals. The earlier estimate of 59 potentially admissible tasks
included 21 with too few generic proposals and preceded the additional semantic
review; it must not be treated as the launchable cohort. Of the 52 inspected,
24 pass manual review and 28 are excluded. The 21 low-proposal tasks were not
newly approved and need separate task-specific case authoring and review.

All 52 prompts, original assertions, reference sources, and proposed inputs were
inspected without execution. The review retained the 13 earlier semantic
exclusions and task 931's strict output-type exclusion. Further exclusions are:

| IDs | Reason |
| --- | --- |
| 615, 886 | Mean computation overlaps the trained masked-mean subproblems; 886 also duplicates MBPP label 959. |
| 690 | Adjacent products duplicate trained task 726 with a different container type. |
| 760 | All-elements-identical is a container/output variant of trained task 741; conservatively treated as a near duplicate. |
| 831 | Equal-pair counting is a predicate/complement variant of development task 564; conservatively excluded. |
| 940 | Same heap-sort contract and function signature as trained task 635; sorting also overlaps development task 516. |
| 664 | All five generic proposals violate the even-endpoint domain. |
| 702 | Binary search misses the final endpoint; an approved-shaped proposal has a statically demonstrable wrong removal count. |
| 775 | Reference constrains even indices as well as the odd indices specified by the prompt. |
| 847 | Prompt says singleton tuple; source assertions and reference copy a plain list. Earlier stronger-test acceptance does not resolve this mismatch. |
| 889 | Reference sorts descending instead of reversing. Monotone source examples conceal the difference. |
| 891 | Decimal digit counting uses true division until floating-point underflow. |
| 908 | Fixed-point comparison uses object identity instead of numeric equality. |
| 969 | Reference joins only adjacent equal keys although the prompt does not impose that restriction. |

The semantic screen compared all previous label prompts and protected evaluation
prompts; suspected duplicate references were inspected directly. It is a
conservative screen, not a proof of semantic disjointness. Broad categories and
algorithm families still overlap. Do not claim family-held-out generalization.

Partial input approvals enforce valid integer bounds for 675, 681, 745, 789,
and 844. For 916, only the seven proposals retaining a matching triplet and
the original tuple expectation type are approved. For 757, approval is bounded
to unique nonpalindromic words, avoiding its self-pair ambiguity. Complete
mutation allowlists and reasons are in the inventory.

## Proposed comparison and gates

Use the pinned original MiniCPM5 model and the saved verified-SFT seed42 adapter
as two experimental teachers. The adapter SHA is
`6c5d5f5df6701757a2e34cdfa229921fa03f27610b745c18b7ce8c222d55c772`.
It improved development from 11/32 to 13/32 but reduced retention from 8/16
to 7/16. It failed the historical promotion gate and remains unpromoted.

Both teachers receive the same newly frozen tasks, prompt construction, two
independent attempts, effective seeds, and inference ceilings. The current main
controller proposal uses greedy plus sampled generation, with no repairs or
model-visible verifier feedback. Preserve all attempts, outputs, verification
failures, time, tokens, and costs. Verify targets independently and select the
earliest verified completion per task with exact-code deduplication.

The proposed new `SuccessorPolicy` minimum of 16 targets per teacher is a
distinct pilot policy. It does not weaken or reinterpret historical
`LearningPolicy`'s minimum of 24. With the selected 20-task design, 16 targets
require at least 80% task coverage in each arm. A feasibility-only outcome is
acceptable. The prior 47/96 result is context, not a forecast for this fresh
cohort. Three selected categories and maximum 60% category share must still
hold; selection may not silently discard valid labels to force these gates.
Both arms must pass before either child trains. Identical resulting training
sequences provide no meaningful teaching contrast and should stop the pair.

Both children start from the identical original base checkpoint with fresh
adapters, using the same seed, fixed 16 optimizer steps under the proposed pilot,
optimizer, schedule, precision, runtime, and token ceilings. Neither child
continues the learned teacher's adapter. Record actual token counts and label
mix: equal steps do not imply equal supervised tokens. Using all independently
verified targets measures the full teaching intervention, including coverage;
it does not isolate label quality on identical successful tasks.

Compare the two children and the original starting model under matched
evaluation controls. Teacher yield alone is not successor-improvement evidence.
The current 32 development and 16 retention tasks are previously exposed and
support only descriptive development comparisons. No additional unseen 32-task
development cohort is established here. One seed and one teaching hop cannot
establish sustained recursive improvement or general research capability.

The next executable milestone is main-chat review of the exact mutation
allowlists and the 24-to-20 selection rule, followed by protocol/source freeze
and remote calibration. Do not add weaker tasks, reuse attempted tasks, override
semantic exclusions, or lower thresholds to fill the count.

## Final split and budget

The sealed native final split contains 500 tasks, file SHA
`566fd53060ffba5766dace1d1e2f4c38906781526de222b0dfbdbc325b696c77`.
Historical `load_mbpp()` decoded all source splits before `prepare` filtered
them. Therefore the earlier claim that final prompts had never been decoded is
incorrect. Final tasks were not sent to models, trained on, or scored. This
review read train and validation files only; the new controller must use
split-specific loading and hash-only access to final bytes, never `load_mbpp()`.

The proposed five stages are calibration plus starting evaluation, original
teacher, learned teacher, original-teacher child, and learned-teacher child.
Each has a maximum $5 reservation, for at most $25 new reservations. The
recorded planning snapshot is $170 reserved for jobs, $25 overhead held, and
$55 unallocated from the $250 authorization. A full new $25 envelope would
leave $30 unallocated. Reservations are not invoices or guarantees the jobs
fit; reconcile provider billing and enforce resource limits. Only main reserves
and launches. No paid work was launched by this review.

## Library handoff and verification

Existing `rsilab.coding_data` proposal, probe, and audit primitives provide
explicit mutation subsets and exact evidence binding. Keep their source and
historical behavior unchanged. The new study requires its own policy and
successor comparator: the old learning comparator models an adapter-free parent
versus an adapted candidate, not two independently trained children. Do not
misrepresent a trained child as an adapter-free parent to reuse that API.

The public API should accept caller-supplied task registries, teacher/student
identities, runtime/evaluator controls, and evidence artifacts without hardcoded
checkout paths. Provider execution remains separate from offline evidence
validation. It must reject missing exposure registries, mismatched prompt/source/
cluster identities, unverified labels, wrong teacher lineage, unequal controls,
and incomplete checkpoint inventories. Persist optimizer/scheduler/RNG state,
not just adapters. Main and the measurement/library chat own implementation;
this review does not certify their changing source or test results.

Verification in this chat covers saved report hashes, exposure reconstruction,
manual review bindings, deterministic proposal reproduction, exact subset/probe
construction, and static inventory consistency. No claim of new model quality,
successful reference probes, trained successors, or promotion is made.
