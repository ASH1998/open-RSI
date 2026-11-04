# Successor recovery v3: failure analysis

Status: final, November 5, 2026 (Asia/Kolkata). Baseline and both teacher arms
completed. The original teacher yielded 10 unique verified targets and the
learned teacher nine; both failed the unchanged target-count and category gates.
No child training ran, so successor-improvement ability was not measured. This
document is observational: no data, thresholds, source, or frozen evidence was
changed, and no candidate/reference code or cloud job was executed here.

## Baseline agrees exactly with the historical parent

The completed recovered baseline is
`runs/20261104T191836Z-successor-r3-baseline-df0f6744/report.json`, canonical
JSON SHA `fab428a15f9d27f2f560763f36849ecc470dd23add1f4de3c810561417616ae7`.
The historical comparison is the `parent_evaluation` in
`runs/20261104T140745Z-verified-sft-v1-collect-298ecd59/report.json`, canonical
SHA `ff52accbe60b22a651065e4d29acc54317638bdfb2ea5562d10eb813eec22516`.

| Registry | Historical parent | Recovered parent | Recovered case passes |
| --- | ---: | ---: | ---: |
| Development | 11/32 | 11/32 | 178/396 |
| Retention | 8/16 | 8/16 | 26/48 |

Matching by task ID gives equality of all 48 full task records, all 48 generated
completion strings, all 48 saved typed-output lists, and all 48 task-level
outcomes. The recovery therefore reproduces the historical failures as well as
the successes, rather than merely matching aggregate scores. Both batches
generated 2,817 output tokens. The recovery verification execution summary
records all 48 IDs validated, no issues, and successful completion; its single
generation call is completed. No completion reached its token or time limit.

The pinned MiniCPM5 revision, greedy seed 42, temperature zero, disabled thinking,
512-token output ceiling, and 2,048-token input ceiling agree. Both use L40S,
CUDA 12.8, and the same six pinned ML packages: torch 2.8.0, transformers 5.22.1,
peft 0.21.2, accelerate 1.15.0, bitsandbytes 0.50.2, safetensors 0.8.0.
The new settings dictionary explicitly adds null adapter path/hash fields that
were absent from the older settings dictionary; those dictionaries are not
literally identical. Both are base-model runs without an adapter.

This supports consistency of this portable baseline inference execution. It
does not validate future training or establish a fresh held-out result: the
development and retention tasks have prior project exposure.

## Baseline failure categories

The following task-level classes are mutually exclusive for this saved batch.
`candidate_execution` is a broad recorded error kind that includes ordinary
wrong answers; it should not be interpreted as a runtime exception by itself.

| Observed failure | Development tasks | Retention tasks | Total |
| --- | ---: | ---: | ---: |
| Wrong returned value, type, representation, or ordering | 17 | 7 | 24 |
| Candidate-call `TypeError` | 4 | 0 | 4 |
| Prohibited `eval` rejected before execution | 0 | 1 | 1 |
| Total failed tasks | 21 | 8 | 29 |

There is no saved evidence of infrastructure failure, incomplete generation,
or truncation accounting for these 29 failures. The source assertions define
some conventions that are not explicit in the short natural-language prompt;
an assertion mismatch should not automatically be described as a general
algorithmic incapability.

### Algorithm and operation mismatches

- **524, increasing-subsequence sum:** generated code includes `arr[i]` when
  choosing the predecessor and then adds it again. The first saved result is
  211 against expected 106; only 4/15 cases pass.
- **515, divisible subset:** generated code constructs residues but returns
  `True` unconditionally for nonzero modulus. The mixed cases reveal the
  missing subset decision; 10/15 pass, so partial case accuracy hides the defect.
- **586, rotation:** `a[:n] + a[n:]` reconstructs the input and ignores `k`;
  0/15 cases pass. **648** reverses the entire list instead of swapping adjacent
  positions; 0/3 retention cases pass.
- **545 and 547, bit operations:** the former does not toggle the leading and
  trailing bits; the latter sums XOR integer values rather than their bit
  counts. They pass 0/11 and 1/6 cases respectively.
- **535, 519, 742 and 581, geometry:** saved expressions use the wrong formula
  or interpretation. For example, 535 returns circumference `2*pi*r` where
  the test expects disk area; its first value is about 62.83 versus 314.15.
- **577, factorial digit:** this is the only development failure whose three
  original assertions all pass while added cases fail. The shortcut returns
  `n % 10` below ten: saved added results include 5 where 0 is expected and 3
  where 6 is expected. The full result is 9/11, correctly a failed task.
- **564, unequal pairs:** the completion counts ordered equal pairs using
  `count*(count-1)`, rather than unequal unordered pairs. Its first example
  coincidentally passes, but the original all-equal and all-distinct cases fail.

These descriptions come from static inspection of saved completions and saved
typed outputs, not newly running the code.

### Runtime errors and policy rejection

All four execution-error tasks report `TypeError` at `candidate_call`:

| Task | Static cause visible in the saved completion |
| --- | --- |
| 552 | Passes an integer difference to `collections.Counter`, which expects an iterable or mapping. It also returns booleans where assertions use descriptive strings. |
| 513 | Computes integer-plus-string `x + K` instead of alternating original items and the inserted string. |
| 553 | Calls `float()` on a tuple instead of constructing the required decimal representation. |
| 571 | Calls `sum()` on the integer `arr[i] + arr[j]`; the early return also fails to accumulate disjoint pairs. |

Retention task **771** attempts `eval` for balanced-bracket checking. The
evaluator rejects it as `candidate_policy:forbidden_name` before a sandbox
output is produced. This is a policy failure, not evidence of a sandbox crash.

### Output conventions and interpretation

- **537:** returns Python `None` for no repeated word; assertions require the
  literal string `'None'`. Repeated-word examples pass; 6/9 cases pass overall.
- **523:** returns a boolean and assumes length four; assertions expect a list
  of validation messages including a minimum-length-eight convention.
- **546:** uses zero-based `rfind`; the original assertion expects one-based
  position 10 for the last `l` in `hello world`, versus returned 9.
- **686:** returns a `Counter`; the frozen retention assertion expects a string
  representation of counts. The typed evaluator successfully preserves the
  Counter output, so this is a contract mismatch, not unsupported serialization.
- **890:** returns a Counter difference instead of the extra element's index.
- **861:** returns a set of anagrams instead of the required ordered list.
- **715:** the regular expression `\d+` discards minus signs; the first saved
  result contains positive 5 where the assertion expects negative 5.
- **530:** returns a count of negatives instead of the expected rounded ratio.
- **544:** concatenates tuple representations instead of flattening their
  elements with spaces. **898** takes the first N elements instead of extracting
  elements meeting the consecutive-repeat criterion.

These distinctions matter when interpreting scores, but they do not authorize
changing this experiment's prompts, expected outputs, or gates after observing
the baseline.

## Original teacher: completed, fails feasibility

Source: `runs/20261104T192332Z-successor-r3-teacher-original-b2467f06/report.json`,
canonical SHA `6f955ff2f08fee4702a938c29b97c3d06d853e666a4fb31cd69609aa7e277803`.
The corresponding envelope is
`artifacts/successor-recovery-v3/teacher-original.json`.

| Measure | Original teacher |
| --- | ---: |
| Greedy verified tasks | 9/20 |
| Sampled verified tasks | 7/20 |
| Tasks verified in both attempts | 6 |
| Unique verified tasks across both | 10/20 |
| Sampled-only new task | 745 |
| Selected category counts | Numeric 6; collections 4; text 0 |
| Largest category share | 60% |

The ten task IDs are **633, 661, 675, 681, 687, 734, 745, 789, 816, 929**
(all with prefix `mbpp-full-`). Earliest passing completion per task gives ten
distinct code hashes, so exact-code deduplication does not reduce this count.
There are 16 passing attempts, but six repeat already verified task IDs; they
do not provide sixteen independent targets. The sampled pass adds only 745;
661, 633, and 734 pass greedily but fail in the sampled attempt.

Both 20-row verification execution summaries succeeded. No attempt reached a
token/time limit or recorded an infrastructure failure. Generation used 1,666
greedy plus 1,437 sampled output tokens, totaling 3,103. Among the 24 failed
attempts, 18 are wrong-output failures, five are candidate-call exceptions, and
one is invalid Python syntax. The sampled pass is an independent generation,
not a feedback repair.

Concrete failure patterns from the saved outputs:

- **757, reverse pairs:** both attempts compute an integer count (first output
  2), while the frozen assertions require a string (`'2'`). Both score 0/15.
  This explains one text-task failure without implying the pair-counting
  algorithm itself failed on these inputs.
- **885, isomorphic strings:** greedy emits a second `else` at the same level,
  causing `SyntaxError` before execution. Sampling tries to call a defaultdict
  instance as a function, producing `TypeError` on all cases. **619**, the third
  text task, returns effectively unchanged text instead of moving digits to the
  end. No text target is verified.
- **916:** both completions return a boolean for triplet existence, while the
  task assertions require the actual matching tuple. **613** chooses one
  maximal record/key instead of returning each key with its value-list maximum.
- **610:** both use zero-based deletion where the source examples use a
  one-based position; coincidental duplicates allow 6/15 cases to pass.
- **844:** both treat integer `n` as an iterable, producing `TypeError`.
  **611** greedily returns an entire tuple instead of a column maximum; the
  sampled version calls nonexistent `collections.abc.itervalues`, producing
  `AttributeError`.
- **863:** greedy only examines the current number and its immediate predecessor,
  not a complete consecutive run; sampled code references undefined `chain`.
  **641** uses an incorrect nonagonal-number formula in both attempts.
- **745:** greedy skips zero digits and therefore incorrectly includes numbers
  such as 10 and 20. The sampled completion verifies all 13 cases and supplies
  the sole additional task.
- **661, 633, 734 sampled regressions:** the first initializes the three-element
  DP state with all three values; the second counts both orders of every XOR
  pair (first output 94 versus 47); the third uses combinations instead of
  contiguous subarrays (first output 23 versus 20). The earlier verified greedy
  targets remain selected for these tasks.

The original arm fails **both** `min_targets=16` and `min_categories=3`.
Its 60% maximum category share meets the inclusive cap; that is not a separate
failure. Since both teachers must pass, the original arm alone was sufficient
to block paired child training; the learned arm subsequently also failed.
No data or threshold adjustment is proposed here.

## Completed paired teacher comparison

Learned source:
`runs/20261104T192821Z-successor-r3-teacher-learned-c9ee6e5a/report.json`, canonical
SHA `6997bf3011beb7726ff3f5a66d5b0b45cbf8b7f9685ed238a5780088ad72559d`.
Its envelope is `artifacts/successor-recovery-v3/teacher-learned.json`.
The paired `artifacts/successor-recovery-v3/probe.json` seal is
`8bc807da036a09a298aff52ff0ddc1a21140a5dec5bd5820940d79745d437d53`.
The full offline `audit_improver_probe` replay exactly reproduces that artifact.

Both attempt indices have identical ordered task records, generation/runtime/
evaluator controls, and effective seeds between arms. Both envelopes record
verified artifacts and rescored outputs. The learned report's two generation
calls and verification execution summaries completed; no truncation or
infrastructure failure is recorded. This is a matched paired feasibility probe,
not an incomplete-arm comparison.

| Measure | Original | Learned |
| --- | ---: | ---: |
| Greedy verified tasks | 9/20 | 9/20 |
| Sampled verified tasks | 7/20 | 6/20 |
| Passing attempts / all attempts | 16/40 | 15/40 |
| Unique selected targets | 10/20 | 9/20 |
| Sampled-only additional tasks | 1 (745) | 0 |
| Collections / numeric / text targets | 4 / 6 / 0 | 4 / 5 / 0 |
| Largest category share | 60% | 55.6% |
| Input tokens across two attempts | 4,962 | 4,962 |
| Output tokens across two attempts | 3,103 | 2,382 |

Output ceilings and attempts were matched; realized output tokens differ.
Lower token use does not establish better data quality or successor ability.
Main owns billing reconciliation; token counts here are not provider invoices.

### Paired wins, losses, and overlap

All task numbers below use the `mbpp-full-` prefix. Relative to the original
teacher on the same task and attempt:

| Comparison | Learned-only successes | Original-only successes |
| --- | --- | --- |
| Greedy attempt | 610, 745 | 633, 789 |
| Sampled attempt | 734 | 745, 789 |
| Either attempt / unique targets | 610 | 633, 789 |

The eight common unique successes are **661, 675, 681, 687, 734, 745, 816,
929**. Nine tasks fail in both arms across both attempts: **613, 757, 916,
885, 863, 619, 641, 844, 611**. Thus there are eight common successes, one
learned-only success, two original-only successes, and nine common failures
among the 20 tasks. This small fixed cohort shows a one-target lower learned
yield; it does not establish a population-level deterioration.

- **610, learned-only:** the learned greedy completion uses the required
  one-based deletion convention and verifies all 15 cases. Both original
  attempts and the learned sampled attempt use zero-based deletion and pass
  only 6/15. This is a greedy win, not a new sampled recovery.
- **633, original-only:** learned code has the appropriate unordered-pair XOR
  expression but calls `itertools.combinations` without importing `itertools`.
  Both learned attempts fail with `NameError`. The original greedy target
  verifies all 15 cases; its sampled version instead double-counts pairs.
- **789, original-only:** both learned attempts replace perimeter `s*l` with
  `s*2*sin(pi/l)`, giving approximately 1.25 instead of 80 on the first source
  case. They pass 2/14 cases; the original teacher passes both attempts.
- **745:** learned greedy already verifies the task, while original requires
  sampling. Learned sampling returns a generator, producing saved `ValueError`
  at the **encoding** stage. This is an unsupported returned value, not evidence
  that the generator body executed successfully. It contributes no new target.

### Differences between selected labels

Selection keeps the earliest passing completion per task and exact-code
deduplicates across tasks. Each arm skips six later passing attempts because
their task was already selected; neither loses a target to duplicate-code
filtering. The selected example hashes differ:

- Original: `7df869ad93657e577cf96ae8ccc44f500cac398dc35523c09ced27a71582a42d`.
- Learned: `04dfb0fbde40dcf1bc1c534521d4b0a4d010b24c28ef7d87f0ada57f1f163900`.

Among the eight shared tasks, **675, 816, and 929** have identical selected
code hashes. **661, 681, 687, 734, and 745** have different selected code:
661 uses a defaultdict DP rather than a list; 681 changes trial-divisor
enumeration; 687 adds `abs` around the recursive remainder; 734 keeps the same
nested contiguous-product loop with different imports/guards; 745 uses a more
compact digit predicate with a redundant membership condition. These are
observed code differences, not evidence that one label trains a better student.
For 745, the original selected target comes from sampling and the learned
target from greedy generation. All other shared selected targets are greedy.

Both selected implementations of **675** use `m <= x+y <= n`, whereas the
saved reference checks `x+y in range(m,n)`, which excludes the upper endpoint.
Static inspection of all 13 frozen case inputs shows **none has `x+y == n`**.
Consequently, both targets verify despite a distinguishable upper-bound
behavior outside those cases. This is a concrete test-coverage limitation,
not a reason to rewrite results or add tests during this completed comparison.
Verified here means passing the frozen finite tests, not proven correct over
the complete intended domain.

### Learned failures and shared patterns

The learned arm has 25 failed attempts: 20 wrong-output failures, four
candidate-call exceptions, and one output-encoding failure (745 sampled).
There is no syntax/policy rejection. Its greedy failures contain nine wrong
outputs and two call exceptions; sampled failures contain eleven wrong outputs,
two call exceptions, and the encoding failure.

All three text tasks still fail in both attempts:

- **757:** learned greedy double-counts reverse pairs (first output integer 4
  versus required string `'2'`); sampling returns integer 5 on that case.
  The original attempts returned the numerically correct integer 2 but still
  failed the required string representation. Thus the learned failures involve
  more than representation alone.
- **885:** learned greedy returns an empty defaultdict instead of a boolean.
  Sampling rejects every repeated destination character even when a consistent
  mapping permits that repetition, passing 5/12 cases but not the task. This
  changes the original syntax/runtime failures into wrong answers without
  producing a verified label.
- **619:** learned greedy returns the input unchanged and sampling removes
  digits without appending them. Both score 0/12, as do both original attempts.

Other shared failures persist through different incorrect constructions:
613 selects a maximal key rather than key-wise maxima; 916 returns booleans
and the learned greedy version merely detects duplicates; 863 counts local
neighbors/repetitions rather than the complete consecutive run; 641 uses
incorrect numeric formulas; 844 iterates over scalar `n`; 611 returns a tuple
instead of its column maximum. Repeated output-contract mismatches and missing
operations dominate this cohort, alongside ordinary coding errors.

## Final interpretation and handoff

The frozen gate remains at least 16 unique verified targets per teacher,
at least three categories, no category above 60%, and different training data.
The paired audit records `matched=True`, `eligible=False`, with four reasons:
`original_too_few_targets`, `original_too_few_categories`,
`learned_too_few_targets`, and `learned_too_few_categories`. Both category-share
caps pass, and the selected datasets differ; those are not the stopping causes.

No child training or child evaluation ran. The saved audit records
`successor_improvement_measured=False`, `promoted=False`,
`selected_agent_id='original-parent'`, and `sustained_rsi=False`. The empirical
result is a failed data-production feasibility gate, with learned yield 9/20
versus original 10/20 under the matched two-attempt budget. It does not measure
which teacher would produce a better successor if trained, and it does not
demonstrate sustained RSI.

This analysis is complete and stable for main's final commit. It used saved
outputs, static completion inspection, hash comparisons, and pure offline
audit replay only. No candidate/reference code, cloud jobs, source edits,
data edits, or threshold changes were performed. Main owns final billing,
backups, and the experiment report. Any further experiment needs a separately
specified prospective protocol rather than an alteration of this result.
