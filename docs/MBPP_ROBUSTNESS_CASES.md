# MBPP post-hoc diagnostic cases

Implemented November 4, 2026. This suite adds **43 manually specified assertions**
to the **21 original assertions** for seven previously inspected tasks: **64 cases
in seven diagnostic task copies**. No original dataset, v1/v2 evaluator, frozen
study, or official score is changed. These are post-hoc diagnostics selected after
failure inspection, not held-out evidence, training labels, or an RSI result.

## Source and interpretation

Source: Google Research's [MBPP dataset, pinned revision
4bb6404fdc6cacfda99d4ac4205087b89d32030c](https://huggingface.co/datasets/google-research-datasets/mbpp/tree/4bb6404fdc6cacfda99d4ac4205087b89d32030c),
full configuration, CC-BY-4.0. Task 928 is from train; the others are from validation.
The frozen `data/mbpp/study-v1.json` assertions were compared with locally saved
pinned Parquet rows and their reference text. Reference code was read, never run
locally. New assertions are authored additions; original assertions are preserved.

Expectations are literal equalities derived manually from the source contract,
not obtained from a model completion or by executing a reference. Unit tests check
numeric answers with independent standard-library/arithmetic calculations and
subarray answers with exhaustive bounded contiguous windows over static data.

| Source task | Extra / combined cases | Contract and additional coverage |
| --- | ---: | --- |
| 512 `count_element_freq` | 6 / 9 | Recursively count integer leaves of nested tuples. Empty tuples, nested empty tuples, singleton, deeper repeats, zero and negative leaves. Manual leaf tallies. |
| 520 `get_lcm` | 6 / 9 | Least positive common multiple of at least two positive integers. Ones, repeated values, divisibility chains, shared factors and coprime pairs. For `[12,18,30]`, maximum prime powers give `2²·3²·5 = 180`. |
| 557 `toggle_string` | 6 / 9 | Toggle upper/lower ASCII letters and preserve other characters. Empty, uppercase-only, lowercase-only, mixed case, punctuation, digits and spaces. |
| 558 `digit_distance_nums` | 6 / 9 | Sum decimal digits of the absolute difference. Equal values, reversed arguments, borrow chains and internal zeros. `1000−1=999`, so the answer is 27. |
| 568 `empty_list` | 4 / 7 | A list of the requested number of empty dictionaries; lengths 0, 1, 2 and 8. Equality contract only. |
| 576 `is_Sub_Array` | 10 / 13 | Ordered contiguous occurrence, with `n=len(A)`, `m=len(B)`, nonempty arrays/patterns. Wrong order, noncontiguous subsequence, final-start match, repeated-prefix restart, singleton match/mismatch and pattern longer than array. |
| 928 `change_date_format` | 5 / 8 | Reorder a valid, zero-padded `yyyy-mm-dd` date to `dd-mm-yyyy`, preserving digits. Leap day, year boundary, differing day/month and leading zeros. |

Task 576 deliberately distinguishes order from multiset membership. `[1,2]` does
not contain `[2,1]`; `[1,9,2]` does not contain contiguous `[1,2]`; `[8,9,1,2]`
does contain `[1,2]` at the final possible starting index. These are independent
counterexamples to the inspected parent's unordered/window logic. Remote results
must establish which saved outputs fail; no candidate was executed to construct
these expected answers.

## Explicit scope limits and omissions

- **512:** no lists inside tuples, unhashable leaves, or mixed-type key collisions.
- **520:** no empty/singleton arrays, zeros, negatives or very large integers. The
  source reference assumes two initial elements and divides by a positive gcd;
  extending those domains would require a separately agreed contract.
- **557:** Unicode case expansion/locale behavior is omitted; ASCII is sufficient
  to test the observed uppercase-handling defect.
- **558:** “digit distance” alone is underspecified. Here the pinned source
  reference and assertions establish digit-sum-of-absolute-difference semantics,
  rather than sum of positional digit differences. The test expectations use that
  declared dataset-specific meaning, with positive integer arguments only.
- **568:** negative/noninteger lengths and dictionary object identity/aliasing are
  omitted. Equality-only transport cannot establish that dictionaries are distinct
  objects; this suite makes no aliasing guarantee.
- **576:** an empty pattern and inconsistent `n`/`m` are omitted because neither
  source assertions nor wording settle their semantics. “Subarray” is interpreted
  as contiguous and ordered, consistent with the source reference and tests.
- **928:** invalid dates, surrounding text, non-padded components and alternative
  separators are omitted; regex permissiveness is not treated as a requirement.

No entire task needed omission once these bounded domains were chosen. A future
reference failure is a review gate: preserve the failure and inspect the source
contract before running candidates. Do not change expectations merely to match a
reference or candidate.

## API and provenance

```python
from rsi.mbpp_robustness import build_tasks

diagnostic_tasks = build_tasks(original_manifest["tasks"])
```

`build_tasks(original_tasks)` returns seven copies in deterministic numeric source
ID order. All seven selected originals must occur exactly once; unselected tasks
are ignored. It verifies the pinned dataset revision, source-row identities,
entry points, original assertion hashes and exact compiled cases. It uses only
the existing static assertion compiler; it neither executes code nor reads files.

Each ID ends in `-robustness-v1`. `metadata.original_task_id` joins the saved
generation. Original prompt, entry point, family, split and source metadata are
preserved as provenance; their split does not establish fresh generalization.
The original three assertions/cases remain an unchanged prefix. The combined
`test_list`, case indices, counts and `source_tests_sha256` describe the new suite
and remain compatible with the v2 verifier's exact typed case schema.

`metadata.robustness` records the full original task hash, original assertion hash,
original imported task hash, original/additional case counts, added assertion
hash, combined case hash and explicit diagnostic-only flags. The old imported
`metadata.task_sha256` is moved to `original_imported_task_sha256` so it cannot be
mistaken for the diagnostic task's hash. Hashes use canonical sorted compact JSON,
UTF-8, non-ASCII preserved and NaN prohibited; the assertion compiler's own
`source_tests_sha256` retains its established encoding convention.

## Verification and handoff

Local tests cover preservation, provenance, deterministic copies, rejection of
changed originals, schema/codec compatibility and independently checked literal
expectations. They execute neither saved candidates nor dataset references.

Verified locally: **9/9 new unit tests passed** with
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p 'test_mbpp_robustness.py' -v`.
The actual frozen manifest also constructed all seven tasks/64 cases successfully,
without input mutation, and every task passed the validator used by v2. Saved
full train/validation Parquet file SHA-256 values matched `raw/source.json`.

Next executable milestone belongs to the main controller: freeze this suite and
its source hash in a separate CPU diagnostic protocol; reserve its budget; verify
all seven source references remotely; then evaluate unchanged saved outputs using
the combined cases. Preserve raw per-case outcomes and report old-v2 versus
combined-suite results separately from the official 368-output scores. No remote
reference or candidate result is asserted by this implementation handoff.
