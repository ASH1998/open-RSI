"""Category preflight regressions; no provider or dataset access."""
from copy import deepcopy
import unittest

from rsilab.core import digest
from rsilab.preflight import preflight_task_categories


def pool(count=24):
    categories = ("collections", "text", "numeric")
    return [{"id": f"task-{i:02}", "category": categories[i % 3],
             "prompt": "This prompt must never determine the category."} for i in range(count)]


def check(tasks, **overrides):
    return preflight_task_categories(tasks, **{"first_n": 20, "min_categories": 3,
                                               "min_pool_count": 24, **overrides})


class CategoryPreflightTests(unittest.TestCase):
    def test_success_counts_and_digest_are_deterministic(self):
        tasks = pool(); reviewed = {row["id"]: row["category"] for row in tasks}
        value = check(tasks, expected_categories=reviewed)
        self.assertEqual(value["pool_count"], 24)
        self.assertEqual(value["pool_category_counts"], {"collections": 8, "numeric": 8, "text": 8})
        self.assertEqual(value["first_n_category_counts"], {"collections": 7, "numeric": 6, "text": 7})
        self.assertEqual(value["sha256"], digest({k: v for k, v in value.items() if k != "sha256"}))
        self.assertEqual(check(tasks, expected_categories=dict(reversed(list(reviewed.items())))), value)
        self.assertEqual(check(tuple(tasks), expected_categories=reviewed), value)

    def test_record_categories_disagree_with_independently_reviewed_mapping(self):
        tasks = pool(); reviewed = {row["id"]: row["category"] for row in tasks}
        for row in tasks: row["category"] = "text"
        before = deepcopy(tasks)
        with self.assertRaisesRegex(ValueError, "disagrees with reviewed mapping"):
            check(tasks, expected_categories=reviewed)
        self.assertEqual(tasks, before)

    def test_whole_pool_diversity_does_not_rescue_first_twenty(self):
        tasks = pool()
        for row in tasks[:20]: row["category"] = "text"
        self.assertEqual(len({row["category"] for row in tasks}), 3)
        reviewed = {row["id"]: row["category"] for row in tasks}
        with self.assertRaisesRegex(ValueError, "First 20 tasks have 1 categories"):
            check(tasks, expected_categories=reviewed)

    def test_no_review_mapping_still_enforces_explicit_categories_and_coverage(self):
        self.assertIsNone(check(pool())["reviewed_categories_sha256"])
        tasks = pool()
        for row in tasks: row["category"] = "text"
        with self.assertRaisesRegex(ValueError, "First 20"):
            check(tasks)

    def test_review_checks_reserves_too(self):
        tasks = pool(); reviewed = {row["id"]: row["category"] for row in tasks}
        tasks[-1]["category"] = "other"
        with self.assertRaisesRegex(ValueError, "disagrees.*task-23"):
            check(tasks, expected_categories=reviewed)

    def test_duplicate_ids_rejected_including_reserves(self):
        tasks = pool(); tasks[-1]["id"] = tasks[0]["id"]
        with self.assertRaisesRegex(ValueError, "Duplicate task id"):
            check(tasks)

    def test_insufficient_pool_and_default_minimum(self):
        with self.assertRaisesRegex(ValueError, "Insufficient task pool"):
            check(pool(23))
        self.assertEqual(check(pool(20), min_pool_count=None)["min_pool_count"], 20)
        with self.assertRaisesRegex(ValueError, "Insufficient task pool"):
            check(pool(19), min_pool_count=None)
        with self.assertRaisesRegex(ValueError, "Insufficient task pool"):
            check([])

    def test_invalid_counts_fail_without_coercion(self):
        for field in ("first_n", "min_categories", "min_pool_count"):
            for value in (True, False, 0, -1, 3.0, "3", float("nan")):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    check(pool(), **{field: value})
        for options in ({"first_n": None}, {"min_categories": None},
                        {"min_categories": 21}, {"min_pool_count": 19}):
            with self.subTest(options=options), self.assertRaises(ValueError): check(pool(), **options)

    def test_missing_or_invalid_record_fields_are_not_inferred(self):
        for field in ("id", "category"):
            for value in (None, "", " ", " text", "text ", 1, True, []):
                tasks = pool(); tasks[0][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError): check(tasks)
        tasks = pool(); reviewed = {row["id"]: row["category"] for row in tasks}
        del tasks[0]["category"]
        with self.assertRaisesRegex(ValueError, "Task category"):
            check(tasks, expected_categories=reviewed)

    def test_review_mapping_requires_exact_valid_coverage(self):
        tasks = pool(); reviewed = {row["id"]: row["category"] for row in tasks}
        cases = [[], {}, {k: v for k, v in reviewed.items() if k != tasks[-1]["id"]},
                 {**reviewed, "extra": "text"}, {**reviewed, tasks[0]["id"]: ""},
                 {**reviewed, 1: "text"}]
        for value in cases:
            with self.subTest(mapping=value), self.assertRaises(ValueError):
                check(tasks, expected_categories=value)

    def test_unordered_or_malformed_pools_rejected(self):
        for tasks in (None, {}, "tasks", b"tasks", set(), iter(pool()), [None]):
            with self.subTest(tasks=tasks), self.assertRaises(ValueError): check(tasks)

    def test_hash_binds_order_categories_review_and_thresholds_not_prompt_content(self):
        tasks = pool(); before = deepcopy(tasks); original = check(tasks)
        self.assertEqual(tasks, before)
        tasks[0]["prompt"] = "string list number: no automatic inference"
        self.assertEqual(check(tasks), original)
        tasks[0], tasks[1] = tasks[1], tasks[0]
        self.assertNotEqual(check(tasks)["sha256"], original["sha256"])
        tasks = pool(); tasks[-1]["category"] = "another-explicit-category"
        self.assertNotEqual(check(tasks)["ordered_categories_sha256"], original["ordered_categories_sha256"])
        self.assertNotEqual(check(pool(), min_pool_count=23)["sha256"], original["sha256"])
        self.assertNotEqual(check(pool(), expected_categories={r["id"]: r["category"] for r in pool()})["sha256"], original["sha256"])


if __name__ == "__main__": unittest.main()
