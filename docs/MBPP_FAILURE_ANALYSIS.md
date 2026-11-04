# MBPP v1 static failure analysis

November 4, 2026. This review reads saved generations, original verification envelopes, frozen source assertions, and verifier source. **No candidate/reference code was executed locally, and no corrected score is claimed.** Preserve the original reports and [original aggregation](../artifacts/mbpp/reports/summary.json); main chat coordinates a separately versioned rescore before further training.

## Findings requiring evaluator attention

The original `mbpp-typed-v1` codec uses exact `type(...)` membership for containers. It rejects standard-library mapping subclasses even when their native equality against the source's plain dictionary would succeed. The prompts permit `collections` and do not require exact built-in return types. This is a verifier coverage defect, not grounds to edit the saved candidate answers.

| Task / affected saved model | Static evidence | Interpretation |
| --- | --- | --- |
| **568: parent and Kaggle** | Returns a list of empty `collections.OrderedDict()` objects. Source assertions compare to lists of empty ordinary dictionaries. All three saved outputs are `ValueError`. | Strong false-negative evidence: nested empty OrderedDicts satisfy the source equality, but the codec rejects their type. One apparent gain shared by the adapters is therefore suspect. |
| **512: seeds 42 and 43** | Recursively counts elements with `collections.Counter`, using recursive results in `counter.update(...)`. Returns the Counter directly. Source assertions expect plain dictionaries with those frequencies; all three saved outputs are `ValueError`. | Strong false-negative evidence: the recursive counting logic matches these source inputs, but the codec rejects Counter. The parent's different implementation doubles existing counts when encountering an inner tuple and produces demonstrably wrong saved dictionaries. |

These are **four affected task/model outcomes**, requiring isolated confirmation. The original scores remain parent dev 17/48, seed 42 dev 16/48, seed 43 dev 15/48, and Kaggle 8/32 until rescore evidence exists. Do not infer a new aggregate by changing these flags manually.

The same codec failure can conceal an answer that is still wrong. Examples: task 890 returns a Counter instead of an index; 686 returns a Counter where source assertions require a **string**; 819 returns a Counter instead of the two-list run-length result; 561 returns a defaultdict keyed by whole pairs rather than the required endpoint mapping; seed adapters' 579 returns a one-sided Counter difference rather than a tuple of symmetric-difference elements. Parent 953 returns a Counter instead of a subset count. Supporting these runtime types should yield truthful mismatches, not automatic passes. Parent 709 returns `dict_keys` where a string is expected; parent/adapters 817 return a function where a list is expected. Those are incorrect return contracts, not demonstrated missing passes.

Recommended evaluator work for the owning chat:

- Support a bounded, explicit set of trusted standard-library container types where conversion preserves comparison against the permitted source literals, including nested containers. Do not serialize arbitrary objects or run candidate-defined equality/iteration methods in the controller.
- Preserve plain dict versus string, tuple versus list, ordering, and the source's equality semantics. Do not relax expectations to make rejected Counter/defaultdict results pass.
- Separate **candidate call**, **encoding**, and **parent comparison** failures in future envelopes. The original child catches both function and codec exceptions together, so `execution_error:ValueError` currently cannot identify the stage by itself.
- Test the two positive cases above and negative return-contract examples. Rescore all original saved arms under the same revised evaluator, with new version/code hashes and report paths, without regenerating or repairing answers.

General coverage risk: the parent currently applies source projections (`list`, `set`, etc.) only after encoding the return value. A source assertion may legally project an iterable that the codec cannot transport. This is a design limitation to test, **not another observed false-negative count in this review**.

## Shared regressions are candidate errors

Both adapters lost the same four development tasks and one retention task. Their saved outputs and small code excerpts explain these failures without invoking a codec/extraction defect.

| Task | Evidence in saved adapter code/output | Assessment |
| --- | --- | --- |
| **520**, array LCM | Both compute an LCM step, then multiply by the current number again: `result = result * num`. First case returns **63504** versus expected **252**; all three cases fail. | Logic regression. The extra multiplication corrupts the recurrence. |
| **558**, digit distance | Both return `max(len(s1), len(s2))`. Saved outputs are **1, 2, 3** versus **1, 6, 7**. | Logic regression: digit count replaces digit-wise distance. |
| **576**, contiguous subarray | Seed 42 never consults `B` and skips a full-length match when `m == n`; saved results include false for the identical-array case and true for a nonmatch. Seed 43 indexes `B[i]` for `i >= m`, producing `IndexError`, and also rejects the identical-array case. | Logic/indexing regressions, with mixed execution and wrong-output failures. |
| **557**, toggle case | Both substitute only `[a-z]` with uppercase. Saved outputs are entirely uppercase, whereas source assertions require existing uppercase characters to become lowercase too. | Logic regression: one-way uppercasing replaces `swapcase`. |
| **928**, date conversion; retention | Both use a replacement pattern containing literal regex escapes such as `\d{2}`, rather than captured date components. Every saved call records exception type `error`; source reference uses capture-group backreferences. | Candidate regex replacement error. No evidence of serialization failure. |

Task 576 also exposes a **weak-test limitation**: the passing parent compares Counters, losing order, and advances its window using the wrong index. By inspection it would accept a reversed full-length permutation such as `[1, 2]` versus `[2, 1]`, despite the contiguous ordered-subarray contract. The original source tests do not reveal this. Preserve its original pass; additional tests belong in a newly versioned prospective evaluation, not a silent rescore change.

## Gains and the Kaggle difference

- **568:** both adapter gains are entangled with the parent OrderedDict codec rejection above.
- **578:** both adapters replace concatenation with `chain.from_iterable(zip(...))`. The saved outputs interleave positions correctly for all three source tests. This is a substantive task-level improvement under those tests.
- **564:** seed 42 counts unordered unequal pairs using `i < j`; the parent and seed 43 count ordered equal-value pairs. For the all-equal and all-distinct source inputs, the saved parent/seed-43 values are 12 and 0 instead of 0 and 10. Seed 42's gain is supported by candidate logic and saved outputs.
- **512:** both adapters' recursion repairs the parent's frequency logic, but its Counter return is rejected. It is a potential missed gain, pending isolated rescore.
- **543, Kaggle only:** the saved function has one extra closing parenthesis in `return len(str(abs(total))))`. Static parsing independently reports invalid syntax. This is a real generated-code error, not evidence that fenced extraction dropped valid code. On the matched 32 dev tasks, the original arms share eight passes and 23 failures; Modal alone passes 543. Kaggle's T4/PyTorch environment remains separate from the L40S matched comparison.

## All-outcome inventory

The read-only [inventory script](../scripts/analyze_mbpp_failures.py) covers **368 original task/model records**. Categories below are mutually exclusive: a failed task with any saved child exception is placed in runtime/codec even if other cases also returned wrong values. “Wrong output only” means the saved values were compared and mismatched; it does not prove the source contract is complete or unambiguous.

| Original arm / split | Total | Pass | Wrong output only | Runtime or codec | Generation limit | Policy | Invalid syntax |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Parent train | 128 | 46 | 55 | 24 | 2 | 1 | 0 |
| Parent dev | 48 | 17 | 21 | 9 | 1 | 0 | 0 |
| Seed 42 retention | 32 | 12 | 13 | 7 | 0 | 0 | 0 |
| Seed 42 dev | 48 | 16 | 22 | 9 | 1 | 0 | 0 |
| Seed 43 retention | 32 | 12 | 13 | 7 | 0 | 0 | 0 |
| Seed 43 dev | 48 | 15 | 22 | 11 | 0 | 0 | 0 |
| Kaggle dev subset | 32 | 8 | 15 | 8 | 0 | 0 | 1 |

Common genuine runtime errors include wrong argument shapes (513 adds a string to integer tuple elements; 539 treats list arguments as scalars), invented APIs (`collections.zip` on 951 and `collections.abc.Counter` on 630), and missing imports (573 calls `math.prod` without importing math in all arms). Parent 862 also omits the `collections` import and returns words without their counts. Do not inject imports or repair these saved programs during the rescore. Parent 771 uses forbidden `eval`; retain the policy rejection.

The three original parent generation-limit failures are 689, 721, and 597; seed 42 has 547. Two parent outputs have incomplete fences; other capped outputs can parse, but remain failures under the frozen token-limit policy. There is no evidence here to justify salvaging only parseable capped answers. All non-limited parent/adapter generations parse statically; the non-limited Kaggle 543 error is described above.

Some tasks have underspecified descriptions or representation conventions: 686/709 require stringified mappings, while 512 expects a mapping; 579 requires a particular tuple order; 543 says “print” although its assertions require a return value. These are source/prompt-design caveats. They do not justify altering frozen source expectations after seeing outcomes. Future prompts can make such contracts explicit under a new prospective protocol.

## Evidence and reproduction

All 176 frozen `test_list`, `test_setup_code`, and `challenge_test_list` fields and their source-test hashes were compared with checksum-verified original train/validation Parquet rows. They match. The source assertions are independent of candidate answers; the observed defects concern transport/diagnostics and sparse contracts, not detected replacement of expected answers.

Evidence pointers below use zero-based `records` indices inside the raw JSON reports. Each record contains the exact prompt, source assertions, raw `generation.text`, limit flags, and original verification errors/outputs.

| Evidence group | Parent | Seed 42 | Seed 43 | Record indices |
| --- | --- | --- | --- | --- |
| 928 | [baseline batch 0](../runs/20261104T095148Z-mbpp-baseline-ddee4c/report.json) | [evaluation batch 0](../runs/20261104T100500Z-mbpp-evaluate-ac91e0/report.json) | [evaluation batch 0](../runs/20261104T100447Z-mbpp-evaluate-66cb3b/report.json) | 928: 21 |
| 543, 520, 568 | [baseline batch 4](../runs/20261104T095949Z-mbpp-baseline-7c3b8e/report.json) | [evaluation batch 1](../runs/20261104T100906Z-mbpp-evaluate-914680/report.json) | [evaluation batch 1](../runs/20261104T100820Z-mbpp-evaluate-daca3b/report.json) | 543: 1; 520: 4; 568: 19 |
| 578, 558, 576, 512, 564, 557 | [baseline batch 5](../runs/20261104T100054Z-mbpp-baseline-0cc65d/report.json) | [evaluation batch 2](../runs/20261104T101136Z-mbpp-evaluate-afcad5/report.json) | [evaluation batch 2](../runs/20261104T101211Z-mbpp-evaluate-136611/report.json) | 578: 0; 558: 5; 576: 6; 512: 7; 564: 12; 557: 15 |

[Kaggle raw report](../runs/20261104T095900Z-mbpp-kaggle-verify-21d047/report.json) uses the same first-dev-batch indices. Raw pinned references remain under ignored `data/mbpp/raw/`; no solution/test corpus is copied into this document or the inventory script.

```sh
.venv/bin/python scripts/analyze_mbpp_failures.py
.venv/bin/python scripts/analyze_mbpp_failures.py --task mbpp-full-568
.venv/bin/python scripts/analyze_mbpp_failures.py --details
```

The script only reads JSON, hashes text, and parses Python ASTs. It emits provenance pointers and classifications to stdout; it does not import provider/controller code, execute candidates, or write/rescore reports. It rejects duplicate original task/model records rather than silently choosing a run.

## Handoff

Changed only this new document and `scripts/analyze_mbpp_failures.py`. Verified the complete original outcome inventory, focused code/test comparisons, source-test hashes against pinned data, and the script's summary/task lookup. No source/verifier edits, credentials, paid calls, training, candidate execution, or commits. The two codec findings were reported to main chat during analysis.

Next executable milestone belongs to main/evaluator chats: fix and version the narrowly supported codec/diagnostics; rescore the unchanged saved parent, both adapters, and Kaggle answers in isolation; publish old/new paired outcomes and reasons together. Recheck label eligibility without silently retraining the already-frozen adapters. Keep the parent retained pending that audit. Static findings above are not replacement scores or proof of general correctness.
