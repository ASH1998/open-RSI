# Explicit category preflight

Status: additive, unreleased follow-up. The immutable tested 0.3.0 wheel does not
contain this module; its version and existing source files are unchanged.

`rsilab.preflight.preflight_task_categories` checks an ordered task pool before
reference calibration or other paid work. It uses record-level categories and
can compare them with an independently reviewed mapping. It never infers a
category from prompts, copies a reviewed label onto a task, or changes ordering.

```python
from rsilab.preflight import preflight_task_categories

# ordered_tasks is the exact pool intended for the next step.
# reviewed_categories is a separately reviewed {task_id: category} mapping.
summary = preflight_task_categories(
    ordered_tasks,
    first_n=20,
    min_pool_count=24,
    min_categories=3,
    expected_categories=reviewed_categories,
)
```

Tasks must be an ordered sequence (for example, a list or tuple) of mappings with
explicit `id` and `category` strings. IDs must be unique throughout the pool,
including reserves. Strings must be nonempty and have no surrounding whitespace;
the helper does not normalize them. Category names are caller-defined.

Counts must be positive integers, excluding booleans, with
`min_categories <= first_n <= min_pool_count`. The optional `min_pool_count`
defaults to `first_n`. The pool must meet that minimum, and its **first N tasks**
must contain at least `min_categories` distinct labels. Diversity only among
later reserve tasks cannot satisfy the prefix check.

If provided, `expected_categories` must cover exactly the pool IDs and match
every task's explicit category, including reserves. An absent record category
still fails even when a reviewed label exists. Without a mapping, the helper
checks explicit labels and coverage but cannot detect consistently incorrect
labels. Independent review and mapping provenance remain the caller's duties.

Failures raise `ValueError`. Success returns a compact dictionary containing
pool size, thresholds, sorted whole-pool and prefix category counts, a hash of
ordered ID/category pairs, an optional reviewed-mapping hash, and a `sha256` over
the other summary fields. Identical inputs produce identical results; mapping
insertion order does not matter. The digests do **not** bind ignored task fields
such as prompts, tests, or reference solutions. Freeze those separately.

Run this check on the proposed ordered pool before spending, then again on the
actual ordered eligible pool after reference calibration if eligibility changes.
A pre-calibration success cannot guarantee that the remaining eligible prefix
will meet the gate. This helper does not establish reference correctness,
train/evaluation separation, category-share limits, or a budget reservation.

The regression tests model a 24-task pool whose record categories all say `text`
while a separately reviewed mapping spans three categories. They also distinguish
whole-pool diversity from first-20 diversity, check reserves and duplicate IDs,
and verify deterministic hashes and non-mutation:

```sh
env -i PATH=/usr/bin:/bin .venv/bin/python -B -m unittest discover -s tests -p test_preflight.py -v
```

This addition does not modify a frozen controller, relabel historical records,
retry an experiment, or launch cloud work. Main owns release packaging and any
future controller integration under a newly reviewed protocol.
