# What did the two teachers teach differently?

The offline audit traced all 32 selected repair-v1 labels to the examples embedded in the two child checkpoints. The original and learned teachers supplied **18 distinct tasks** between them. Fourteen task IDs were shared. Six shared answers were byte-identical and had identical Python syntax trees. The other eight shared tasks received different implementations. Both children ultimately made the same pass/fail decision on every evaluated task. [Historical comparison](../../docs/REPAIR_EXPERIMENT.md)

The scope of this retrospective is the two datasets actually consumed by the children. That includes the APPS examples from the completed mixed-source study. The proposed lesson-selection test and the two example lesson bundles below use MBPP only.

### How the training signal differed

Supervised tokens below count one pass through each checkpoint dataset with the frozen tokenizer, chat template and loss mask.

| Selected tasks | IDs | Original tokens | Learned tokens |
|---|---|---:|---:|
| Six shared tasks, identical code | MBPP 662, 696, 744, 759, 796, 805 | 171 | 171 |
| Eight shared tasks, different code | MBPP 663, 664, 688, 694, 739, 811, 832 and APPS 3041 | 563 | 532 |
| Two original-only tasks | MBPP 936 and APPS 3038 | 370 | — |
| Two learned-only tasks | MBPP 723 and APPS 3080 | — | 78 |
| Total | 16 per teacher | **1,104** | **781** |

**292 of the 323 extra supervised tokens** in the original dataset came from the four tasks unique to one teacher. APPS 3038 alone accounted for 299 tokens, including comments explaining how to track a letter's first and last positions. Each dataset contained one repair, APPS 3038 in the original dataset and MBPP 664 in the learned dataset. A comparison of these two children changes task choice, answer content and realized token count together.

For shared task 739 the original answer searches for the first triangular number meeting a threshold, while the learned answer computes the index directly. These are two substantively different examples of how to solve the same problem. On 688 the difference is simply an explicit float cast around a function that already returns a float. Counting every distinct answer as a distinct teaching strategy would overstate the variation. [Per-label review and code hashes](audit.json)

### Label correctness and retention

The audit includes 22 previously untested input calls across all 18 distinct tasks. Their expected outputs were specified separately and checked against the pinned MBPP reference worker or, for the three historical APPS task IDs, the study's trusted handwritten oracle. Candidate answers were inspected statically; none were executed locally. These checks establish the expected values for diagnostic inputs. Only the historical sandbox results measure actual candidate execution.

MBPP 663 has a concrete defect in **both** selected answers. For positive divisor one, each always returns the upper bound, regardless of the requested remainder. The checked cases include `(4, 1, 1) → -1`, `(0, 1, 2) → -1` and the valid control `(4, 1, 0) → 4`. The first two would return 4 and 0 respectively by inspection. Quarantine both implementations in any future lesson pool. Finite review of the other responses supplies no correctness guarantee. [Inputs and reasoning](review.py)

Both children lost the same two historical retention tasks. On MBPP 854 both returned the return value of an in-place heap operation. On 621 both attempted a string replacement with a callable, although the baseline used regex substitution. Among the 16 lessons per arm, none asks the student to heapify in place and then return the list, or to replace matched digit runs with values computed by a callback. Several teach list transformations or regex parsing more generally. This identifies two missing practice opportunities. Without a controlled substitution, the records cannot show that either omission caused a regression. Repeated use of 621 and 854 must stay diagnostic if future lesson design targets them. [Task-level evidence](../repair_v1/failure_analysis.md)

### Reproduce from the SSD

```sh
.venv/bin/python -B -m studies.lesson_selection_v1.audit
.venv/bin/python -B -m studies.lesson_selection_v1.dry_run
.venv/bin/python -B -m studies.lesson_selection_v1.screen_validation
```

The audit checks the frozen plan and paired selection, full child report hashes, exact checkpoint examples, candidate hashes, tokenizer totals, probe novelty and reference values. The second command constructs two MBPP-only lesson bundles from one donor in memory and verifies their input and supervised token budgets. The third command checked six native assertions and six additional cases, then quarantined MBPP 531 for two overlapping coin-change inputs with exposed task 918. MBPP 575 passed an additional bounded sweep of 3,522 calls. Only one fresh task remains in this inventory. The full data and budget check is available through `.venv/bin/python -B -m studies.lesson_selection_v1.feasibility`. [Feasibility result](feasibility.json). None of the commands trains a model or contacts a provider. The replay requires the pinned local tokenizer, MBPP training Parquet, repair reports and checkpoint metadata on the SSD. [Prospective test and feasibility decision](proposal.md)
