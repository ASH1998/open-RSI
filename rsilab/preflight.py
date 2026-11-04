"""Offline checks of explicit task categories and a declared ordered prefix.

This module neither infers categories nor selects/relabels tasks. Review and
reference eligibility are caller responsibilities; no provider work occurs.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from .core import digest


def _label(value, name):
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{name} must be nonempty text without surrounding whitespace")
    return value


def preflight_task_categories(tasks, *, first_n: int, min_categories: int,
                              min_pool_count: int | None = None,
                              expected_categories: Mapping[str, str] | None = None) -> dict:
    """Validate an ordered pool and its first N tasks; return counts and hashes.

    Tasks must be a sequence of mappings with explicit string ``id`` and
    ``category`` fields. Other fields are ignored. When supplied, the reviewed
    ID-to-category mapping must cover exactly the pool and agree with every
    record, including reserves outside the prefix. The caller establishes the
    mapping's independent review; this check cannot establish its truth.

    Counts are positive integers (not booleans), with min_categories <= first_n
    <= min_pool_count. The pool minimum defaults to first_n. Failures raise
    ValueError; inputs are never changed. Digests bind ordered IDs/categories,
    review mapping and thresholds, not prompts, tests or reference eligibility.
    """
    if min_pool_count is None:
        min_pool_count = first_n
    for name, value in (("first_n", first_n), ("min_categories", min_categories),
                        ("min_pool_count", min_pool_count)):
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    if not min_categories <= first_n <= min_pool_count:
        raise ValueError("Require min_categories <= first_n <= min_pool_count")
    if not isinstance(tasks, Sequence) or isinstance(tasks, (str, bytes, bytearray)):
        raise ValueError("Tasks must be an ordered sequence of task mappings")

    rows, seen = [], set()
    for task in tasks:
        if not isinstance(task, Mapping):
            raise ValueError("Each task must be a mapping with explicit id and category")
        task_id = _label(task.get("id"), "Task id")
        category = _label(task.get("category"), "Task category")
        if task_id in seen:
            raise ValueError(f"Duplicate task id: {task_id}")
        seen.add(task_id)
        rows.append({"id": task_id, "category": category})

    reviewed = None
    if expected_categories is not None:
        if not isinstance(expected_categories, Mapping):
            raise ValueError("Expected categories must be a reviewed ID-to-category mapping")
        reviewed = {_label(key, "Reviewed task id"): _label(value, "Reviewed category")
                    for key, value in expected_categories.items()}
        if set(reviewed) != seen:
            raise ValueError("Reviewed category mapping must cover exactly the task pool")
        for row in rows:
            if row["category"] != reviewed[row["id"]]:
                raise ValueError(f"Task category disagrees with reviewed mapping: {row['id']}")

    if len(rows) < min_pool_count:
        raise ValueError(f"Insufficient task pool: need {min_pool_count}, have {len(rows)}")
    pool_counts = dict(sorted(Counter(row["category"] for row in rows).items()))
    prefix_counts = dict(sorted(Counter(row["category"] for row in rows[:first_n]).items()))
    if len(prefix_counts) < min_categories:
        raise ValueError(f"First {first_n} tasks have {len(prefix_counts)} categories; need {min_categories}")
    summary = {
        "schema_version": 1,
        "pool_count": len(rows), "first_n": first_n,
        "min_pool_count": min_pool_count, "min_categories": min_categories,
        "pool_category_counts": pool_counts, "first_n_category_counts": prefix_counts,
        "ordered_categories_sha256": digest(rows),
        "reviewed_categories_sha256": None if reviewed is None else digest(reviewed),
    }
    return {**summary, "sha256": digest(summary)}
