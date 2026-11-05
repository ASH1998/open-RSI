"""Public contract tests using synthetic training data and the production scorer."""
from copy import deepcopy
from collections import OrderedDict
import unittest

from rsi.mbpp_verification import convert_mbpp_tests, encode_value
from rsi.mbpp_verification_v2 import encode_value as encode_output, score_mbpp_outputs
from rsilab import digest
from rsilab.task_contracts import apply_task_contracts, replay_task_contracts, score_task_contract_outputs


def fixture(identifier="window"):
    tests = ["assert inside(4, 3, 5) == True"]
    challenges = ["assert inside(2, 3, 5) == False"]
    source = {
        "id": identifier, "family": "windows", "category": "numeric", "split": "train",
        "metadata": {"source_split": "train", "audit": {"review_sha256": digest("synthetic")}},
        "prompt": "Return Python code only.\n\nCheck a window.\n\nRequired signature:\ndef inside(x, lo, hi):",
        "test_list": tests, "challenge_test_list": challenges,
        **convert_mbpp_tests(tests, "inside", challenge_test_list=challenges),
    }
    review = {"task_id": identifier, "source_sha256": digest(source),
              "clarified_prompt": "Return whether lo <= x < hi.",
              "review_note": "Independent review of the upper endpoint.",
              "boundaries": [{"name": "upper", "call": "inside(5, 3, 5)", "expected": encode_value(False)}]}
    return source, review


class TaskContractTests(unittest.TestCase):
    def test_evaluator_compatibility_and_generation_visibility(self):
        source, review = fixture()
        bundle = apply_task_contracts([source], [review])
        task = bundle["tasks"][0]
        self.assertEqual(task["cases"][:-1], source["cases"])
        self.assertEqual(task["challenge_test_list"][:-1], source["challenge_test_list"])
        self.assertEqual(task["source_test_count"], 1)
        self.assertEqual(task["challenge_test_count"], 2)
        self.assertNotEqual(task["source_tests_sha256"], source["source_tests_sha256"])
        self.assertEqual(task["metadata"], source["metadata"])
        self.assertEqual(bundle["prompts"], [{"id": source["id"], "prompt": task["prompt"]}])
        for hidden in (review["review_note"], review["boundaries"][0]["call"], source["test_list"][0]):
            self.assertNotIn(hidden, task["prompt"])
        outputs = [{"ok": True, "value": c["expected"]} for c in task["cases"]]
        self.assertTrue(score_mbpp_outputs(outputs, task["cases"])["passed"])
        outputs[-1]["value"] = encode_value(True)
        self.assertEqual(score_mbpp_outputs(outputs, task["cases"])["count"], 2)
        self.assertEqual(bundle["lineage"][0]["boundaries"], [
            {"name": "upper", "case_index": 2, "case_sha256": digest(task["cases"][2])}])

    def test_inputs_and_replayed_outputs_are_independent(self):
        source, review = fixture()
        before = deepcopy([source, review])
        manifest = apply_task_contracts([source], [review])
        replayed = replay_task_contracts([source], [review], manifest, expected_sha256=manifest["sha256"])
        self.assertEqual(manifest, replayed)
        replayed["tasks"][0]["metadata"]["audit"].clear()
        replayed["tasks"][0]["test_list"].clear()
        self.assertTrue(manifest["tasks"][0]["metadata"]["audit"])
        self.assertEqual([source, review], before)

    def test_wrong_source_digest_and_wrong_order(self):
        a, ra = fixture("a")
        b, rb = fixture("b")
        for tasks, reviews in (([a, b], [rb, ra]), ([a], []), ([a, a], [ra, ra]), ([], [])):
            with self.assertRaises(ValueError): apply_task_contracts(tasks, reviews)
        a["metadata"]["audit"]["late_edit"] = True
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            apply_task_contracts([a], [ra])

    def test_native_training_split_only(self):
        for field in ("split", "source_split"):
            source, review = fixture()
            (source if field == "split" else source["metadata"])[field] = "test"
            review["source_sha256"] = digest(source)
            with self.assertRaisesRegex(ValueError, "native training"):
                apply_task_contracts([source], [review])

    def test_detached_cases_hash_or_counts_fail_even_after_reanchoring(self):
        for key, value in (("source_tests_sha256", digest("changed")), ("source_test_count", True),
                           ("cases", []), ("challenge_test_list", [])):
            source, review = fixture()
            source[key] = value
            review["source_sha256"] = digest(source)
            with self.subTest(key=key), self.assertRaises(ValueError): apply_task_contracts([source], [review])

    def test_reject_malformed_and_mismatched_calls(self):
        for call in ("different(5,3,5)", "inside(5,3)", "inside(1,2,3,4)", "inside(1,2,hi=3,lo=1)",
                     "inside(x=5,lo=3,bad=5)", "inside(*[5,3,5])", "inside(**{})",
                     "inside(__import__('os'),3,5)", "sorted(inside(5,3,5))", "inside(5,3,5) or True",
                     "inside(5,3,5); other()", "inside(5,3,5) == True", "inside("):
            source, review = fixture()
            review["boundaries"][0]["call"] = call
            with self.subTest(call=call), self.assertRaises(ValueError): apply_task_contracts([source], [review])

    def test_duplicate_call_across_keyword_spelling_and_conflicting_outcome(self):
        for expected, reason in ((True, "Duplicate call"), (False, "Conflicting expectations")):
            source, review = fixture()
            review["boundaries"][0].update(call="inside(hi=5, x=4, lo=3)", expected=encode_value(expected))
            with self.assertRaisesRegex(ValueError, reason): apply_task_contracts([source], [review])
        source, review = fixture()
        review["boundaries"].append({**review["boundaries"][0], "name": "other upper",
                                     "call": "inside(5, hi=5, lo=3)"})
        with self.assertRaisesRegex(ValueError, "Duplicate call"): apply_task_contracts([source], [review])

    def test_duplicate_name_and_bad_typed_values(self):
        source, review = fixture()
        review["boundaries"] *= 2
        with self.assertRaisesRegex(ValueError, "duplicate boundary name"):
            apply_task_contracts([source], [review])
        for expected in (False, ["bool", 1], ["unknown", []], ["set", [["int", 1], ["int", 1]]],
                         ["dict", [[["list", []], ["bool", False]]]]):
            source, review = fixture()
            review["boundaries"][0]["expected"] = expected
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                apply_task_contracts([source], [review])

    def test_repeated_inherited_inputs_and_distinct_projections_preserved(self):
        source, review = fixture()
        direct = "assert inside(4, 3, 5) == [4, 3, 5]"
        projected = "assert sorted(inside(4, 3, 5)) == [3, 4, 5]"
        tests, challenges = [direct], [projected, direct]
        source.update(convert_mbpp_tests(tests, "inside", challenge_test_list=challenges),
                      test_list=tests, challenge_test_list=challenges)
        review["source_sha256"] = digest(source)
        result = apply_task_contracts([source], [review])
        self.assertEqual(result["tasks"][0]["cases"][:3], source["cases"])
        self.assertEqual(result["tasks"][0]["challenge_test_list"][:2], challenges)
        review["boundaries"][0]["call"] = "inside(x=4, lo=3, hi=5)"
        for expected, error in (([4, 3, 5], "Duplicate call"), ([], "Conflicting expectations")):
            review["boundaries"][0]["expected"] = encode_value(expected)
            with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, error):
                apply_task_contracts([source], [review])

    def test_review_cannot_change_policy_signature_or_disclose_review_call(self):
        source, review = fixture()
        for text in (source["prompt"].replace("Python", "Java"), source["prompt"].replace("hi):", "hi, z):"),
                     "Required signature: def changed(x):", "Try inside(5, 3, 5) as your example."):
            review["clarified_prompt"] = text
            with self.subTest(text=text), self.assertRaises(ValueError): apply_task_contracts([source], [review])

    def test_equivalent_literal_calls_in_prose_cannot_disclose_boundaries(self):
        source, review = fixture()
        for text in ("At the edge, inside( 5 , 3 , 5 ) returns False.",
                     "Consider `inside(hi=5, x=5, lo=3)` here.",
                     "The candidate's example inside(5,\n lo=3, hi=5) is hidden."):
            review["clarified_prompt"] = text
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "Hidden boundary call"):
                apply_task_contracts([source], [review])

    def test_clarity_only_and_full_prompt(self):
        source, review = fixture()
        review.update(clarified_prompt=source["prompt"].replace("Check a window.", "Check lo <= x < hi."),
                      boundaries=[])
        result = apply_task_contracts([source], [review])
        self.assertEqual(result["tasks"][0], {**source, "prompt": review["clarified_prompt"]})
        self.assertEqual(result["lineage"][0]["boundaries"], [])

    def test_review_and_boundary_fields_are_explicit(self):
        for change in ({"extra": 1}, {"review_note": ""}, {"boundaries": None},
                       {"boundaries": [{"name": "missing", "call": "inside(5,3,5)"}]}):
            source, review = fixture()
            with self.subTest(change=change), self.assertRaises(ValueError):
                apply_task_contracts([source], [{**review, **change}])

    def test_replay_rejects_resealed_evidence_and_mismatched_external_pin(self):
        source, review = fixture()
        record = apply_task_contracts([source], [review])
        with self.assertRaisesRegex(ValueError, "external pin"):
            replay_task_contracts([source], [review], record, expected_sha256="0" * 64)
        for field in ("tasks", "prompts", "lineage"):
            changed = deepcopy(record)
            changed[field] = []
            changed["sha256"] = digest({k: v for k, v in changed.items() if k != "sha256"})
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "differs from replay"):
                replay_task_contracts([source], [review], changed)


class ContractScoringTests(unittest.TestCase):
    def score(self, expected, actual):
        source, review = fixture()
        review["boundaries"][0]["expected"] = encode_value(expected)
        bundle = apply_task_contracts([source], [review])
        # Both inherited bool cases pass with int values under historical equality.
        outputs = [{"ok": True, "value": encode_output(v)} for v in (1, 0, actual)]
        return score_task_contract_outputs(bundle, source["id"], outputs, expected_sha256=bundle["sha256"])

    def test_integer_one_passes_inherited_true_but_fails_reviewed_true(self):
        score = self.score(True, 1)
        self.assertEqual((score["source_passed_count"], score["boundary_passed_count"]), (2, 0))
        self.assertEqual((score["count"], score["total"], score["passed"]), (2, 3, False))
        self.assertEqual(score["errors"], ["case_2:wrong_typed_output"])
        self.assertEqual(score["case_diagnostics"][0]["error_stage"], "boundary_comparison")
        self.assertTrue(self.score(True, True)["passed"])
        self.assertFalse(self.score(1, True)["passed"])
        self.assertFalse(self.score(1.0, 1)["passed"])

    def test_nested_types_and_container_type_are_part_of_the_contract(self):
        self.assertFalse(self.score((1,), [1])["passed"])
        self.assertFalse(self.score((True,), (1,))["passed"])
        self.assertTrue(self.score((True,), (True,))["passed"])
        self.assertFalse(self.score({False}, {0})["passed"])

    def test_plain_mapping_order_is_irrelevant_but_key_value_and_mapping_tags_matter(self):
        desired = {"first": [True], "second": (2,)}
        self.assertTrue(self.score(desired, {"second": (2,), "first": [True]})["passed"])
        self.assertFalse(self.score(desired, {"second": (2,), "first": [1]})["passed"])
        self.assertFalse(self.score({True: "x"}, {1: "x"})["passed"])
        self.assertFalse(self.score(desired, OrderedDict(desired))["passed"])

    def test_invalid_output_count_execution_encoding_and_pinned_manifest(self):
        source, review = fixture()
        bundle = apply_task_contracts([source], [review])
        score = score_task_contract_outputs(bundle, source["id"], [])
        self.assertEqual(score["errors"], ["invalid_output_count"])
        self.assertEqual((score["source_passed_count"], score["boundary_passed_count"]), (0, 0))
        for bad, reason in (({"ok": False, "error_stage": "candidate_call", "error": "TypeError"}, "execution_error"),
                            ({"ok": True, "value": ["unknown", "x"]}, "invalid_result")):
            outputs = [{"ok": True, "value": c["expected"]} for c in bundle["tasks"][0]["cases"]]
            outputs[-1] = bad
            self.assertEqual(score_task_contract_outputs(bundle, source["id"], outputs)["errors"], ["case_2:" + reason])
        with self.assertRaisesRegex(ValueError, "external pin"):
            score_task_contract_outputs(bundle, source["id"], [], expected_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "detached task"):
            score_task_contract_outputs(bundle, "unknown", [])
        bundle["lineage"][0]["source_case_count"] = 3
        with self.assertRaisesRegex(ValueError, "manifest seal"):
            score_task_contract_outputs(bundle, source["id"], [])
        bundle["sha256"] = digest({k: v for k, v in bundle.items() if k != "sha256"})
        with self.assertRaisesRegex(ValueError, "partition"):
            score_task_contract_outputs(bundle, source["id"], [])


if __name__ == "__main__":
    unittest.main()
