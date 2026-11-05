# Repair v1 failure analysis

## Starting student

The original MiniCPM5-2B passed **3/9 fresh development tasks** and **8/16 historical retention tasks** in one greedy attempt each. Each success required every case to pass. The fresh set comprises eight held-back MBPP native-training rows and one held-back APPS native-training row. Its only text example is the APPS version-increment task. The retention answers and pass/fail decisions reproduced the earlier recovery baseline exactly on all 16 IDs. The 8/16 retention score measures prior skills on exposed tasks. [Repair baseline](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/lysnxeds)

| Group | Numeric | Collections | Text | Other | Tasks passed |
|---|---:|---:|---:|---:|---:|
| Fresh MBPP | 2/3 | 1/5 | — | — | 3/8 |
| Fresh APPS | — | — | 0/1 | — | 0/1 |
| Historical MBPP retention | 4/5 | 3/7 | 1/3 | 0/1 | 8/16 |

The fresh passes were MBPP 644 (reverse a prefix), 717 (sample standard deviation) and 950 (zodiac-year cycle). Each of the six fresh failures had a distinct cause visible in the saved answer or verifier outcome.

| Fresh task | Cases passed | What went wrong |
|---|---:|---|
| MBPP 626 · inscribed triangle | 4/6 | The answer computed the area of the semicircle. For radius 2, it returned 6 where the maximum inscribed triangle has area 4. |
| MBPP 679 · dictionary key by index | 0/6 | The answer looked up the integer index as a dictionary key. The supplied dictionaries have string keys, so all six calls raised execution errors. |
| MBPP 780 · pairwise coordinate sums | 2/6 | Each correct coordinate pair was enclosed in an additional one-element tuple. The empty and single-pair inputs still returned the correct empty list. |
| MBPP 915 · signed ordering | 3/6 | The answer sorted the negatives but kept the positives in input order. A boundary containing unsorted positives, zeros and negatives exposed the missing sort. |
| MBPP 938 · closest triple | 0/7 | The answer reached the 512-token output limit while writing comments about search strategies. The verifier recorded a generation-limit failure before executing any case. |
| APPS 4194 · dotted version increment | 5/9 | Incrementing a trailing 9 produced a final component of 10. The code inspected earlier components for 9 independently of whether a carry reached them. It failed two of five inherited examples and two of four new boundaries. |

For all five fresh failures that executed, at least one inherited case and at least one added boundary failed. The added boundaries therefore changed zero fresh task-level pass decisions for this baseline. With only one fresh APPS/text task, this split cannot distinguish a source effect from a text-category effect.

On retention, seven answers failed output comparisons and one was rejected by candidate policy. Output representation mattered on 686 (returned a Counter where the historical assertions require a formatted string), 861 (a set where the assertions require an ordered list) and 890 (a Counter of unmatched values where the task asks for an index). On 715, the answer’s digit pattern lost a minus sign. Task 771 attempted dynamic evaluation and was rejected before any test ran. Those historical prompts and test conventions were preserved.

## Evidence and method

The baseline data above come from `runs/20261105T163427Z-repair-v1-baseline-78a59c92/report.json`, completed evidence seal `2f5e6e537eeb65cb780d37524abee8851c1478d23a3bfdeb9273afa54fb8b0f9`. The comparison uses `runs/20261104T191836Z-successor-r3-baseline-df0f6744/report.json` for retention. The first nine baseline records match the ordered fresh evaluation manifest, followed by the 16 retention records. Findings use saved strict verifier results and static inspection of answer text. No candidate code was executed for this analysis.

## Original teacher

The original teacher solved 17/24 tasks greedily. Independent sampling recovered none of the seven misses. Repair recovered two, bringing the greedy-plus-repair total to **19/24**, versus **17/24** for greedy plus sampling. Paired task outcomes were 17 successes on both paths, two repair-only, zero sample-only and five failures on both. All 72 attempts are present. The second calls saw identical prompts and produced identical answer text on all 17 greedy successes, as specified. None of the 72 outputs hit the token limit. [Original teacher run](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/1vz9kizr)

| Attempt or path | MBPP | APPS | Collections | Numeric | Text | Total |
|---|---:|---:|---:|---:|---:|---:|
| Greedy | 15/19 | 2/5 | 9/11 | 4/6 | 4/7 | 17/24 |
| Sample, second answer alone | 11/19 | 2/5 | 8/11 | 1/6 | 4/7 | 13/24 |
| Repair, second answer alone | 12/19 | 3/5 | 9/11 | 1/6 | 5/7 | 15/24 |
| Greedy plus sample | 15/19 | 2/5 | 9/11 | 4/6 | 4/7 | 17/24 |
| Greedy plus repair | 16/19 | 3/5 | 10/11 | 4/6 | 5/7 | 19/24 |

Four greedy successes failed on both second attempts (MBPP 663, 664, 694 and 739). Each policy still retains its verified first answer. On the seven greedy misses, the following are cases passed by the first, independently sampled and repair answers respectively. The final column describes the recorded behavior by inspecting outputs and answer text.

| Task | Greedy | Sample | Repair | Finding |
|---|---:|---:|---:|---|
| MBPP 943 · merge sorted lists | 2/6 | 2/6 | **6/6** | Both earlier answers concatenated the lists in input order. Repair sorted the concatenation and preserved duplicates. |
| APPS 3038 · farthest repeated letter | 13/14 | 12/14 | **14/14** | The first answer chose by frequency and passed all ten native examples. On the private input `zaaabz`, it chose `a`; `z` spans the first and last positions. Repair calculated each letter's span and applied the stated tie rule. |
| MBPP 723 · equal positions | 1/6 | 1/6 | 1/6 | Repair repeated the first code, counting matching values regardless of position. |
| MBPP 830 · ceiling at decimal precision | 1/6 | 1/6 | 1/6 | The revised answer calculated a scale factor but never used it to round. |
| MBPP 910 · Gregorian date | 0/7 | 5/7 | 6/7 | Repair fixed the syntax error but accepted February 29, 1900. It allowed up to 29 days in every February. |
| APPS 3052 · trailing exclamation marks | 4/10 | 3/10 | 8/10 | Repair kept the trailing run when present. If there was no trailing run, it skipped removal of internal marks. |
| APPS 4256 · missing letters | 0/10 | 2/10 | 0/10 | Repair added the missing import, then compared uppercase candidate letters to a lowercase input set and inserted the same whole sequence at each new letter. |

For the original teacher the two recoveries demonstrate specific changes after a wrong-output verdict. The intervention also supplies the teacher's own previous answer and requests a revision. The experiment cannot attribute either recovery to the verdict alone. The source and category columns partition the same 24 tasks in two ways. All five APPS training tasks are text, and the two MBPP text tasks are decimal validation and maximum extraction.

Original teacher evidence seal: `d8e8fcac6a4d22cb48fe2a7ae919b24bcfc8c0bed0eaec07d12d5fb4eb6a5a8a`. The ordered tasks matched the sealed manifest on each of three completed calls. Typed outputs were rescored from the stored records when present. Pre-execution failures retained their reported policy, syntax or generation outcomes.

### Uncovered input in a verified target

MBPP 663 passed all seven frozen cases on the original greedy attempt. The prompt allows any positive integer divisor and nonnegative requested remainder. By inspection, the answer's special branch for divisor 1 returns the upper bound regardless of the requested remainder. For `(n, x, y) = (4, 1, 1)`, the contract requires `-1`: every integer has remainder zero modulo one. The answer would return `4`. This counterexample was derived statically after generation and was never run. The frozen result is still a pass. The verified-label pool therefore contains at least one response with a known out-of-test error.

## Learned teacher and paired comparison

The learned teacher also solved 17/24 tasks greedily. Independent sampling recovered none of its seven misses. Repair recovered one, for **18/24** on greedy plus repair versus **17/24** on greedy plus sampling. Paired outcomes were 17 successes on both paths, one repair-only, zero sample-only and six failures on both. All 72 attempts were present. Both second answers were byte-identical on all 17 greedy successes. No learned output hit the token limit. [Learned teacher run](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/q162odcf)

| Attempt or path | MBPP | APPS | Collections | Numeric | Text | Total |
|---|---:|---:|---:|---:|---:|---:|
| Greedy | 15/19 | 2/5 | 10/11 | 3/6 | 4/7 | 17/24 |
| Sample, second answer alone | 11/19 | 2/5 | 8/11 | 1/6 | 4/7 | 13/24 |
| Repair, second answer alone | 12/19 | 2/5 | 8/11 | 2/6 | 4/7 | 14/24 |
| Greedy plus sample | 15/19 | 2/5 | 10/11 | 3/6 | 4/7 | 17/24 |
| Greedy plus repair | 16/19 | 2/5 | 10/11 | 4/6 | 4/7 | 18/24 |

Four learned greedy successes failed on both second attempts (MBPP 662, 663, 696 and 739). On 662, the second answers returned an OrderedDict instead of a plain dictionary. They passed the inherited comparisons but failed all three strictly typed boundaries. The greedy answer was retained. The seven greedy misses account for every opportunity to recover a task on this teacher.

| Task | Greedy | Sample | Repair | Finding |
|---|---:|---:|---:|---|
| MBPP 664 · mean of the even integers | 0/6 | 0/6 | **6/6** | The first answer divided by one too many terms. Repair used the actual number of even integers from 2 through the endpoint. |
| MBPP 830 · ceiling at decimal precision | 2/6 | 1/6 | 2/6 | The repair reproduced the first answer's floor operation. |
| MBPP 910 · Gregorian date | 4/7 | 2/7 | 4/7 | The revised answer still required integers even though the prompt allows decimal strings. Its leap-year rule also accepted 1900 as a leap year. |
| MBPP 943 · merge sorted lists | 2/6 | 0/6 | 0/6 | The revised and independently sampled answers called nonexistent `collections.chain`, raising errors on every case. |
| APPS 3038 · farthest repeated letter | 13/14 | 7/14 | 13/14 | Like the original teacher, the learned greedy answer passed every native example by using frequency. Its repair kept the frequency rule and failed the same private case. |
| APPS 3052 · trailing exclamation marks | 3/10 | 3/10 | 5/10 | The revised answer returned the input string verbatim and continued to fail examples requiring internal marks to be removed. |
| APPS 4256 · missing letters | 2/10 | 3/10 | 2/10 | The revised answer still selected letters from those present in the string, without deriving the missing uppercase letters. |

Across teachers, both repair paths solved 17 of the same tasks. The original alone solved MBPP 943 and APPS 3038. The learned teacher alone solved MBPP 723, whose first answer correctly compared positions across the two lists. Both missed MBPP 830, MBPP 910, APPS 3052 and APPS 4256. The observed advantage of repair over independent sampling was two tasks for the original teacher and one for the learned teacher on this single cohort and seed schedule. Repair used more input tokens than sampling: 4,211 versus 3,458 for the original and 4,055 versus 3,458 for the learned teacher.

The frozen child-data gate passed with distinct selected datasets, each containing eight collections, four numeric and four text targets. No exact-code duplicate reduced either repair pool. The original selection included the repaired APPS 3038 answer and omitted repaired MBPP 943 under the fixed category quotas. The learned selection included repaired MBPP 664. Each selected dataset contains 15 first-attempt targets and one repaired target. Both include MBPP 663, and both selected answers share the divisor-one error described above. Thus the observed difference in child data includes different tasks and first-attempt code as well as one repair per arm. Teacher yield and eligibility alone do not measure successor quality.

The learned teacher evidence seal is `8fe38dc6ac6cf4dce871d26622699f24729e9c6607115a22c7d80eb2816a290d`. The controller replayed the probe, baseline, both completed teachers and the paired selection from the saved evidence. The resulting paired report seal is `cf3377cda9293317a803697f334b80d4de8d0d20f99ab2701a29364e9077fae3`.

## Original-teacher child

After 16 training steps, the original-teacher child passed **4/9 fresh tasks** and **6/16 retention tasks**. Against the common starting student, it gained two fresh tasks, lost one fresh task and lost two historical retention successes. The remaining six fresh tasks and 14 retention tasks kept the same pass/fail outcome. [Original child run](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/cz7rxlpl)

| Changed task | Baseline → child, cases passed | Difference in the recorded answer |
|---|---:|---|
| Fresh MBPP 780 | 2/6 → 6/6 | Returned each sum directly as a coordinate pair, eliminating the extra tuple layer. |
| Fresh MBPP 915 | 3/6 → 6/6 | Sorted the positives as well as the negatives and kept the zeros between them. |
| Fresh MBPP 950 | 7/7 → 0/7 | Rotated a deque of signs once for every input, producing the same answer for every year. |
| Retention MBPP 854 | 3/3 → 0/3 | Returned the result of in-place `heapq.heapify`, which is None. The baseline returned the modified list. |
| Retention MBPP 621 | 3/3 → 0/3 | Called string `replace` with a callback where a replacement string is required. The baseline used regex substitution. |

The fresh improvement was confined to two MBPP collections tasks. The APPS text result remained a failure (5/9 cases at baseline, 2/9 after training). The original child missed both baseline-relative criteria: its net fresh gain was one against the required three, and two baseline retention successes regressed. It processed 13,456 training tokens, including 4,416 supervised tokens, on 16 examples. The completed report evidence seal is `daca31da821cc2e0fcd30d39de9ee55b21cbd5d97982a351932a5536259ba1c2`.

The lost zodiac task also illustrates the distinction between a task pass and full correctness. Its baseline answer used the capitalized name `Sheep` where the contract explicitly requires lowercase `sheep` for 2003. That input was outside the seven frozen cases. The child regressed even on the frozen cases, so the pass-to-fail transition stands. The casing observation comes from static inspection only.

## Matched child outcome and final decision

**Both children passed exactly the same four fresh tasks and six retention tasks.** Relative to the starting student, each gained MBPP 780 and 915 and lost MBPP 950 on fresh evaluation (net +1). Each lost 854 and 621 on retention (net −2). Comparing the two children directly gives zero fresh gains, zero fresh losses and zero retention discordances. Neither met the required +3 fresh gain over both comparators or preserved all baseline retention successes. The final report keeps `original-parent` selected and records no promotion. This is a negative one-step successor comparison under the frozen controls. [Learned child run](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/nkb1k8hw)

All 50 child outcomes are represented below. Each paired entry is one task tested on both children. Numeric IDs refer to MBPP.

| Set | Baseline | Both children | Task IDs |
|---|---|---|---|
| Fresh | Pass | Pass | 644, 717 |
| Fresh | Fail | Pass | 780, 915 |
| Fresh | Pass | Fail | 950 |
| Fresh | Fail | Fail | 626, 679, 938, APPS 4194 |
| Retention | Pass | Pass | 711, 835, 873, 849, 665, 616 |
| Retention | Pass | Fail | 854, 621 |
| Retention | Fail | Fail | 742, 890, 771, 686, 715, 861, 898, 648 |

The children produced byte-identical answer text on 21/25 tasks. Their texts differed on 717, 938, 950 and 898. Only 938 had different case-pass counts: the original-teacher child passed 2/7 with an incorrect selection rule, while the learned-teacher child returned None and passed 0/7. On 950, the learned child attempted to call the nonexistent `collections.cycle`. It failed all seven cases, as did the original child's constant answer. Both children passed 4/8 fresh MBPP tasks and failed the sole fresh APPS/text task. These results cannot identify a broader text or cross-source effect.

The matched 16-step runs started from the same base and used equal category quotas, seed and optimizer settings. The learned-teacher child processed 12,148 tokens, including 3,124 supervised tokens. The original-teacher child processed 13,456 tokens, including 4,416 supervised tokens. Equal examples and steps therefore did not equalize realized training tokens. The learned child evidence seal is `52ca586429f12bbbab04ebd36038a39ed940c433b11dc9b7914ca7cf6404af94`.

The offline controller rechecked both completed child reports against their ledger entries and plan, rescored their evaluation records, and verified all 12 exported file hashes per run, including the adapter, step-16 checkpoint and training-state file. The original-child adapter SHA-256 is `d4880358b1d469b31a2f0e45fcd61e4dd3adb87d6865a7a1b501c79639982f25`; the learned-child adapter SHA-256 is `0ef633d32f711596dc334639e0af3ec6dd6ccc6d244754ffbdc262f31a327bff`. Hash verification establishes export integrity; this analysis did not exercise a checkpoint resume.

The six completed repair-v1 stages reserved $25 total ($1 probe, $4 baseline and four $5 stages). The ledger sums to $219 in cumulative job reservations, plus the separate $25 overhead hold, leaving $6 of the $250 cap. The final report records no invoice total. Both child datasets included the same known MBPP 663 coverage gap. Leave these results frozen; any revised case or future repeated generation needs a separate protocol.
