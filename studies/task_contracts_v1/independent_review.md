# Independent task-contract review

This November 5, 2026 review concerns the 20 exposed training tasks in the completed successor probe. I checked the pinned `full/train` Parquet checksum, all 20 source-row digests, and equality of the stored reference text with the corresponding native training row. I inspected the prompts, typed historical cases and all 16 saved teacher responses for the four tasks below. The counterexamples and expected values here come from reading the source and reasoning about inputs. They are proposals for a separate diagnostic. No candidate or reference code ran in this inspection.

The native source is `google-research-datasets/mbpp`, revision `4bb6404fdc6cacfda99d4ac4205087b89d32030c`, config `full`, split `train`. The local evidence is `data/successor-v1/prepared.json` (references and domain reviews), `data/successor-recovery-v3/audited-dataset.json` (typed historical cases) and `artifacts/successor-recovery-v3/teacher-{original,learned}.json` (both attempts per teacher). The frozen protocol digest is `0cba1d12bb4f06c051566ac9e9d58923d1ad108475a34f6b04aa4cb3aa0060ba`.

## 675 · Adding within a range

For integer arguments with `m < n`, let `s = x + y`. The native reference uses `s in range(m, n)`, so it returns `20` when `m <= s < n` and the integer `s` otherwise. The word “between” leaves the upper endpoint unclear to a reader of the original prompt. The 13 historical cases had nine strictly interior sums and four sums above the interval. All four saved responses used `m <= s <= n` and passed all 13 cases. Their upper-inclusive condition differs from the reference at `s == n` whenever `n != 20`.

Holding the interval and first addend fixed gives these independently derived cases. The expected values are integers.

| Call | Expected | Position of the sum |
| --- | ---: | --- |
| `sum_nums(2, 2, 5, 9)` | 4 | One below the lower endpoint |
| `sum_nums(2, 3, 5, 9)` | 20 | Lower endpoint, included |
| `sum_nums(2, 6, 5, 9)` | 20 | One below the upper endpoint |
| `sum_nums(2, 7, 5, 9)` | 9 | Upper endpoint, excluded |
| `sum_nums(2, 8, 5, 9)` | 10 | One above the upper endpoint |

The fourth case distinguishes all four saved predicates by inspection. A case with `n == 20` would hide the error because both branches return `20`. Equal or reversed endpoints were explicitly excluded in the prior review. These five cases preserve its domain. Historical scores remain the recorded 13/13 for each attempt.

## 757 · Counting reverse-string pairs

The three native assertions require a **decimal string**. The reference counts position pairs `(i, j)` with `i <= j` and `words[j] == words[i][::-1]`. The reviewed historical domain used distinct, nonpalindromic strings. On that domain, `i == j` can never contribute. Specify unordered pairs counted once and preserve exact return type. Examples for this domain are `['ab', 'cd', 'ba', 'dc'] → '2'`, `['ba', 'ab'] → '1'`, and `['ab', 'ac'] → '0'`. An empty list yields `'0'` if the new review explicitly admits empty lists.

Two source behaviors need an explicit decision before expanding the domain. For `['aba']` the reference counts one self-pair and returns `'1'`; a distinct-position interpretation returns `'0'`. For `['ab', 'ba', 'ab']` the reference counts two position pairs, while a count of unique string pairs would be one. Keep these examples as ambiguity diagnostics unless the revised contract explicitly adopts their respective semantics. A nonempty list containing the empty string also raises the palindrome/self-pair question.

Both original responses return an integer count. On the reviewed domain their “seen earlier” rule counts each unordered reverse pair once; all 15 typed cases nevertheless failed for each response. Both learned responses also return integers. The first includes both orientations of a matched pair. The second counts occurrences of each current word when it looks up `counts[rev]`, including words with no partner. Clarifying output type and clarifying pair semantics address different defects.

## 885 · String isomorphism

Return a Python Boolean. Two strings are isomorphic when they have equal lengths and the same partition of positions by character equality. This requires a bijection: the same source character always maps to the same target, and different source characters cannot map to the same target. Repeated use of an established mapping is valid. The native reference collects each character's list of positions and compares the sorted lists.

| Arguments | Expected | Distinction |
| --- | --- | --- |
| `('abba', 'xyyx')` | `True` | Reuse of both mappings |
| `('aabb', 'xyxy')` | `False` | Equal character frequencies, different position partitions |
| `('aa', 'xy')` | `False` | One source character splits across targets |
| `('ab', 'xx')` | `False` | Distinct source characters collide |
| `('', '')` | `True` | Two empty position partitions |
| `('a', 'aa')` | `False` | Unequal lengths |

Explicitly admit emptiness and unequal lengths in a new contract if using those cases. Earlier perturbations preserved length. Use short literal strings, exact character equality and no normalization. The learned sampled response rejects a previously seen target even when reusing its established source mapping. The frozen suite already includes a repeated-character positive case (`paper`, `title`); the extra witnesses isolate the failure more directly. Historical case counts for original initial/sampled and learned initial/sampled were 0, 0, 0 and 5 of 12.

## 619 · Moving digits to the end

For a string, return the nondigit characters in their original order followed by the digit characters in their original order. The native reference classifies **individual characters** with `str.isdigit()`. On an explicitly ASCII domain, the digits are `0` through `9`. These independent cases separate order preservation, leading zeros, punctuation and identity inputs.

| Input | Expected string |
| --- | --- |
| `'0A-90z2'` | `'A-z0902'` |
| `'9a0b9'` | `'ab909'` |
| `'007'` | `'007'` |
| `'a-b'` | `'a-b'` |
| `''` | `''` |

If a future version accepts general Python strings, specify the digit predicate. For example, `'A²B7'` gives `'AB²7'` with `str.isdigit()` and `'A²B7'` with ASCII decimal matching. The earlier examples established ASCII semantics. Keep the Unicode witness diagnostic-only for an ASCII contract. The saved responses attempted substring removal, returned the input unchanged or removed digit runs. Each scored 0/12. Digit-only and digit-free cases can pass a trivial identity function, so pair them with interleavings.

## Validation boundaries and handoff

Use the pinned native training row as the source of reference code and the independently specified typed value as the expectation. Preserve exact primitive types, including the string on 757 and the Boolean on 885. A disagreement between an expectation and a trusted reference requires reviewing the contract or excluding the case. The reference output alone cannot resolve an ambiguous prompt. Candidate code, including previously passing 675 code, stays outside local execution and outside the oracle.

For the whole cohort, bound input sizes and reference execution time. The triplet reference (916) searches cubically. The nonempty-array references (661 and 863) index into their inputs, and 863 sorts its list in place, so use fresh argument values per case. Keep 844's index within `1..n`, 611's column within every tuple, and 613's inner lists nonempty. Keep 687's arguments in the approved positive domain and 745's enumerated interval short and positive. These restrictions come from inspecting the selected reference code and prior domain reviews.

## Integrated review

I applied and replayed `reviews.json` (`8934dd3d836911790e703a8f32a4a97140df9d48dfe7a51eaf32ee42ed65e300`) against the pinned 20 tasks. The manifest digest is `8a5bd6d42ae6335c9c5e27f0db696237a74c4923f66f0f84ad6d135e987a7e38`. All **273 inherited cases** remain exact ordered prefixes. The **73 additions** give **346 cases**. I independently computed all 346 expected results from decoded inputs with separate calculations, checking exact encoded values. For example, I enumerated valid position subsets on 661, used character-position equality on 885, and enumerated contiguous slices on 734. All 346 matched. Main separately reported 346/346 passes in its reference-only subprocess. Inspection of the runner confirms it accepts task IDs and input values, loads code from the checksum-verified native training rows, and checks each extracted reference hash before running it.

The integrated 675 suite has five additions covering below, at and above the lower and upper bounds, including `sum_nums(4, 5, 5, 9) → 9`. The five 757 additions remain inside the distinct nonpalindromic-word domain. The six 885 additions include a same-frequency, different-position pair. The five 619 additions retain the explicit ASCII domain and include repeated zeros. All 20 public prompts preserve their policy and signature, and the public projections contain only `id` and `prompt`. Manual review found no embedded hidden examples in these records. The review-order and tampered-manifest rejection checks both passed. For 687, passing output cases establishes GCD results only; the wording requests recursion, which the value checks do not measure.

The disclosure issue is resolved for the reported direct literal calls. On a synthetic copy of 675, the revised guard rejected both earlier reproducers, `sum_nums( 4 , 5 , 5 , 9 )` and `sum_nums(x=4, y=5, m=5, n=9)`. It also rejected reordered keywords and a mix of positional and keyword arguments, and accepted an unrelated call. It binds literal arguments to the declared parameters before comparison. Descriptions that disclose inputs or answers in natural language still need human review. The 20 actual descriptions passed that review.

I reran the public scorer on all 20 tasks with labeled control outputs from the independently checked expectations. Its counts were 273/273 inherited and 73/73 new. Single-output substitutions rejected integer `1` for Boolean `True` on 885, float `9.0` for integer `9` on 675, and a nested float `4.0` for integer `4` in a tuple inside a list on 613. Each produced one boundary failure at the substituted index. An inherited 885 case continued to accept integer `1` under its original equality semantics. On 757, integer `0` failed the new string-return case, and a shortened output list failed the batch. The focused task-contract unit suite also passed. The two reported API concerns are closed for these inputs and the manifest digest above.

The review concerns wording and coverage on already exposed training tasks. It adds no teacher attempts or scores. The historical v3 result and the proposed boundary diagnostic are separately identifiable.
