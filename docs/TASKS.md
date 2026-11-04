# Pilot task suite

`rsi/tasks.py` defines `pilot-v2`, an original, deterministic, standard-library task suite for checking the first data-generation and training loop. It is a small engineering pilot, not a validated coding benchmark or evidence of recursive self-improvement. Version 2 narrows the advertised import/numeric contracts and makes discrete scoring exact; freeze fresh manifests rather than mixing version 1 and version 2 results.

## Splits and variants

| Split | Families | Main behaviors |
| --- | --- | --- |
| Training | `masked_mean`, `stable_softmax`, `gradient_clip`, `sequence_pad` | Missing-value reductions, numerical stability, vector norms, ragged batches |
| Development | `group_reduce`, `interval_union` | Grouped aggregation and ordered interval merging |
| Final test | `edit_distance`, `graph_reachability` | Dynamic programming and graph traversal |

Families are assigned to one split permanently. Changing a seed changes case sampling and semantic-variant selection; it does not create an independent held-out family. Do not move variants into another split to increase evaluation size. The development and final domains deliberately differ from training, so improvement on them is uncertain.

Training tasks alone may supply verified candidate solutions for SFT. Development results may guide model selection, promotion thresholds, and controller changes; development attempts and solutions must remain outside SFT data. Repeated development use makes those scores selection-dependent. Final-test prompts, including their public examples, are shown only during a frozen parent/candidate comparison with matched inference and repair budgets. Final results must not guide that comparison's tuning, selection, or training. If final results influence later changes, they are exploratory feedback and a fresh held-out evaluation is needed. These are caller responsibilities; `build_tasks` does not enforce access control or a training-data filter.

`build_tasks(split, count_per_family=4, seed=0)` returns JSON-serializable dictionaries. Supported counts are 1–8 per family, giving 16 training, 8 development, and 8 final tasks by default, or 32/16/16 at maximum. Configurations differ in actual requirements: reduction axis, empty-group value, temperature, probability versus log output, norm/limit, padding/cropping direction, aggregation method, merge-gap policy, edit costs, or graph/output semantics. They remain correlated within each family and are not independent statistical replications.

Each task has:

- `id`, `family`, `split`, and `entry_point` (`solve`).
- `prompt`: function contract and one visible input/output example.
- `cases`: hidden inputs and reference-computed expected outputs, including boundary cases and seeded random cases. Inputs differ from the public example, but variants can share hidden inputs.
- `examples`: the public example in structured form.
- `metadata`: suite version, semantic configuration, and seed.
- `tolerance`: recursive numeric comparison settings used by `verify_candidate`: `rel_tol=1e-6`, `abs_tol=1e-7` for means, softmax, gradient clipping, and grouped means; both zero for padding, grouped sum/max/count, intervals, edit distance, and graph outputs.

Only the prompt and entry-point contract go to the model. Hidden cases, their expected outputs, and reference implementations stay with the trusted controller; they are not training targets or feedback text. A model can see an execution failure summary if the frozen experimental protocol permits repairs. Never serialize the full task manifest into a generation prompt or mount this task/reference module into candidate execution environments.

Prompts allow Python built-ins and only `math`, `collections`, `itertools`, `functools`, `bisect`, `heapq`, and `statistics` imports, matching the verifier. They prohibit decorators, I/O, dynamic execution, and introspection. Numeric inputs to means, softmax, and clipping are finite and bounded in magnitude by 1,000,000; grouped reductions use integer inputs. This pilot does not claim correctness at arbitrary floating-point extremes.

## Verification

The builder computes expected values using repository-authored pure Python references. It never executes candidate code. `reference_solution(task)` emits trusted reference code only to validate the isolated evaluator and unit tests. Never add reference code to SFT data or substitute it when a model attempt fails.

Hidden inputs exclude the public example. Cases cover empty inputs, missing groups, zero vectors, extreme logits, negative values where appropriate, duplicates, overlapping/nested intervals, empty/Unicode strings, disconnected graphs, cycles, and self loops. The controller compares outputs recursively and rejects non-finite candidate values. Discrete tasks use exact numeric equality; the verifier treats `1` and `1.0` as equal but rejects bool-as-number. Strings, keys, list order, and shapes must match exactly. Tolerance applies only to floating expectations; integer expectations, including empty-group sentinels, always require exact equality. Tests are not exhaustive, and passing this suite is not a proof of arbitrary-input correctness.

Run the suite's local tests with:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_tasks.py' -v
```

The tests check reproducibility, strict JSON serialization, split disjointness, public/hidden input separation, all generated reference outputs, argument preservation, permitted imports, AST policy acceptance, controller scoring with each task's tolerance, and hand-computed semantic expectations. Weighted edit distance is additionally checked against an independent exhaustive recurrence. Local tests execute only repository-authored references; model-generated programs belong in Modal Sandboxes. These local checks do not verify remote execution, model capability, or training behavior.

## Review handoff — November 4, 2026

Changed only `rsi/tasks.py`, `tests/test_tasks.py`, and this document. Prompts now match the verifier's permitted imports, floating input domains are explicit, discrete tasks use zero tolerance, and malformed split requests consistently raise `ValueError`. The suite version is now `pilot-v2`. Tests additionally check AST policy compatibility, controller scoring, tolerance behavior, and mutation of the actual reference arguments.

Verified locally: all 16 task tests and the then-current 7 verifier tests passed. No candidate/model programs, network jobs, paid compute, commits, or pushes were run for this review. The verifier is maintained by a separate chat and was read only here.

Remaining limitations: hidden cases are generated by trusted references rather than a separately implemented oracle for every family; the small correlated family set supports pipeline checks only. Training/dev/test handling and prompt-only model exposure still require enforcement in the controller. No model benchmark or remote execution outcome is established by these tests.

Next executable milestone: have the main chat freeze and hash `pilot-v2` manifests with an explicit seed/count and verify the controller's split and prompt allowlists. Then run the budget-reserved isolated-verifier smoke test under main-chat coordination before baseline model collection. Record this assignment and integration status in the main chat's `docs/WORK_LOG.md`.
