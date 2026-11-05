"""Synthetic evidence for the installed rsilab API. No provider or checkout fixtures."""
from copy import deepcopy
import hashlib
import unittest

from rsi.mbpp_verification import convert_mbpp_tests, encode_value
from rsilab import digest
from rsilab.paired_repair import audit_paired_repair, second_prompts
from rsilab.successor import inference_request_sha256
from rsilab.task_contracts import apply_task_contracts, score_task_contract_outputs


CATEGORIES = ("numeric", "collections", "text")


def fixture(n=3, categories=CATEGORIES):
    tasks, reviews = [], []
    for i in range(n):
        # Descending IDs make sorting by task ID observably wrong.
        tests = ["assert f(7) == True"]
        row = {"id": str(n - i), "entry_point": "f", "split": "train", "category": categories[i % len(categories)],
               "metadata": {"source_split": "train"}, "test_list": tests, "challenge_test_list": [],
               "prompt": "Write Python code.\n\nDetect a positive input.\n\nRequired signature:\ndef f(x):",
               **convert_mbpp_tests(tests, "f")}
        tasks.append(row)
        reviews.append({"task_id": row["id"], "source_sha256": digest(row),
                        "clarified_prompt": f"Task {row['id']}. Return whether x is positive.",
                        "review_note": "PRIVATE REVIEW", "boundaries": [
                            {"name": "negative", "call": "f(-4321)", "expected": encode_value(False)}]})
    manifest = apply_task_contracts(tasks, reviews)
    parent = {"agent_id": "parent", "model_id": "test/model", "revision": "f" * 40, "tokenizer_revision": "f" * 40,
              "parent_agent_sha256": None, "adapter_sha256": None}
    teachers = {"original": parent, "learned": {**parent, "agent_id": "experimental",
                                                "parent_agent_sha256": digest(parent), "adapter_sha256": "9" * 64}}
    controls = {}
    for phase, seed, temp in (("first", 42, 0.0), ("second", 31415, 0.7)):
        controls[phase] = {
            "generation": {"seed": seed, "temperature": temp, "max_new_tokens": 512,
                           "max_input_tokens": 2048, "enable_thinking": False},
            "effective_seeds": list(range(seed, seed + n)),
            "runtime": {"hardware": "fixture", "precision": "fixture", "packages": {"synthetic": "1"},
                        "source_hashes": {"rsilab/task_contracts.py": "d" * 64}},
            "evaluator": {"version": "mbpp-typed-v2", "source_hashes": {"executor": "e" * 64}},
        }
    return manifest, teachers, controls


def scored(manifest, task, control, i, pass_check, suffix):
    code = "def f(x):\n    return " + ("x > 0" if pass_check else "int(x > 0)") + f"  # {suffix}"
    outputs = [{"ok": True, "value": encode_value(v)} for v in ((True, False) if pass_check else (1, 0))]
    verification = {**score_task_contract_outputs(manifest, task["id"], outputs),
                    "verifier_version": "mbpp-typed-v2", "evaluator_source_hashes": control["evaluator"]["source_hashes"],
                    "source_tests_sha256": task["source_tests_sha256"], "outputs": outputs, "sandbox_id": "sb-fixture",
                    "candidate_sha256": hashlib.sha256(code.encode()).hexdigest()}
    generation = {"id": task["id"], "text": code, "hit_time_limit": False, "hit_token_limit": False,
                  "input_tokens": 48, "output_tokens": 14}
    row = {"task": task, "generation": generation, "verification": verification, "effective_seed": control["effective_seeds"][i]}
    if pass_check:
        row["verified_code"] = code
    return row


def runs(spec, passes=None, suffix=None):
    manifest, teachers, controls = spec
    passes = passes or (lambda role, branch, i: branch == "repair" or (i % 3 == 0 and branch == "first"))
    suffix = suffix or (lambda role, branch, i: f"{role}-{branch}-{i}")
    result = []
    for role, teacher in teachers.items():
        collections, prompts = {}, {}
        for branch in ("first", "sample", "repair"):
            control = controls["first" if branch == "first" else "second"]
            rows = [scored(manifest, task, control, i, passes(role, branch, i), suffix(role, branch, i))
                    for i, task in enumerate(manifest["tasks"])]
            public = manifest["prompts"] if branch == "first" else [
                {"id": t["id"], "prompt": prompts[branch][t["id"]]} for t in manifest["tasks"]]
            collections[branch] = {"controls": deepcopy(control), "records": rows, "prompts": public,
                                   "request_sha256": inference_request_sha256(teacher, control, public)}
            if branch == "first":
                prompts = second_prompts(manifest, rows)
        result.append({"run_id": role, "teacher": teacher, "manifest_sha256": manifest["sha256"], "collections": collections})
    return result


class PairedRepairTests(unittest.TestCase):
    def test_paired_discordances_and_raw_attempts(self):
        spec = fixture(4)
        data = runs(spec, lambda role, branch, i: (branch, i) in {("first", 0), ("sample", 1), ("repair", 2)})
        result = audit_paired_repair(*spec, *data)
        teacher = result["teachers"]["original"]
        self.assertEqual(teacher["paired_unique"], {"both": ["4"], "left_only": ["3"], "right_only": ["2"], "neither": ["1"]})
        self.assertEqual(teacher["recoveries_by_category"]["text"]["right_only"], ["2"])
        self.assertEqual(teacher["arms"]["sample"]["selected"][0]["source"], "first")
        self.assertEqual(teacher["tokens"]["first"]["output_tokens"], 56)
        self.assertEqual(teacher["run"]["collections"], data[0]["collections"])
        self.assertFalse(result["child_gate"]["eligible"])
        self.assertEqual(result["child_gate"]["examples"], {"original": [], "learned": []})
        saved = result["sha256"]
        data[0]["collections"]["first"]["records"].clear()
        self.assertEqual(saved, digest({k: v for k, v in result.items() if k != "sha256"}))

    def test_prompt_scope_and_teacher_local_first(self):
        spec = fixture()
        students = runs(spec)
        for run in students:
            cols = run["collections"]
            self.assertEqual(cols["first"]["prompts"], cols["sample"]["prompts"])
            self.assertEqual(cols["sample"]["prompts"][0], cols["repair"]["prompts"][0])
            prompt = cols["repair"]["prompts"][1]["prompt"]
            self.assertIn(cols["first"]["records"][1]["generation"]["text"], prompt)
            self.assertIn("Verifier feedback: wrong_output.", prompt)
            for hidden in ("PRIVATE REVIEW", "case_", "wrong_typed_output", "f(-4321)", "sb-fixture", "passed_count"):
                self.assertNotIn(hidden, prompt)
        students[1]["collections"]["repair"]["prompts"] = students[0]["collections"]["repair"]["prompts"]
        with self.assertRaisesRegex(ValueError, "prompts"):
            audit_paired_repair(*spec, *students)

    def test_typed_rescore_and_candidate_binding(self):
        spec = fixture(1)
        base = runs(spec)
        for target, new_value in (("count", 1), ("scorer_version", "old"), ("outputs", [{"ok": True}]),
                                  ("case_diagnostics", [{"error": "forged"}]), ("boundary_passed_count", 0),
                                  ("sandbox_id", None), ("candidate_sha256", "0" * 64),
                                  ("source_tests_sha256", "0" * 64)):
            data = deepcopy(base)
            data[1]["collections"]["first"]["records"][0]["verification"][target] = new_value
            with self.subTest(field=target), self.assertRaises(ValueError):
                audit_paired_repair(*spec, *data)
        bad = base[0]["collections"]["first"]["records"][0]
        bad["verified_code"] += "\n# substituted"
        with self.assertRaisesRegex(ValueError, "verified"):
            audit_paired_repair(*spec, *base)

    def test_incomplete_or_mismatched_run_controls(self):
        spec = fixture(2)
        base = runs(spec)
        for field, new_value in (("controls", spec[2]["first"]), ("records", []),
                                 ("request_sha256", "0" * 64), ("prompts", spec[0]["prompts"][::-1])):
            data = deepcopy(base)
            data[0]["collections"]["repair"][field] = new_value
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit_paired_repair(*spec, *data)
        for mutate in (lambda x: x["collections"]["sample"]["records"][0].update(effective_seed=123),
                       lambda x: x["collections"]["first"]["records"].reverse(),
                       lambda x: x["collections"]["first"]["records"][0]["generation"].update(input_tokens=2049),
                       lambda x: x["collections"]["repair"]["records"][0]["generation"].update(hit_time_limit=True),
                       lambda x: x["collections"]["first"]["records"][0]["verification"].update(infrastructure_error=True),
                       lambda x: x.update(run_id="learned"), lambda x: x.update(manifest_sha256="0" * 64),
                       lambda x: x.update(teacher=spec[1]["learned"])):
            data = deepcopy(base)
            mutate(data[0])
            with self.assertRaises(ValueError):
                audit_paired_repair(*spec, *data)

    def test_frozen_protocol_rejects_matched_but_wrong_settings(self):
        for field, value in (("temperature", 0.65), ("seed", 7), ("enable_thinking", True),
                             ("max_new_tokens", 513), ("max_input_tokens", 1000)):
            spec = fixture(1)
            spec[2]["second"]["generation"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "protocol"):
                audit_paired_repair(*spec, *runs(spec))

    def test_generation_limit_without_fabricated_outputs(self):
        spec = fixture(1)
        row = runs(spec)[0]["collections"]["first"]["records"][0]
        row.pop("verified_code")
        row["generation"].update(output_tokens=512, hit_token_limit=True)
        row["verification"] = {"passed": False, "count": 0, "total": 2, "errors": ["generation_token_limit"],
                               "error_kind": "generation_limit", "sandbox_id": None}
        prompts = second_prompts(spec[0], [row])
        self.assertIn("Verifier feedback: generation_limit.", prompts["repair"]["1"])
        row["verification"]["outputs"] = []
        with self.assertRaisesRegex(ValueError, "Truncation"):
            second_prompts(spec[0], [row])

    def test_reason_vocabulary_for_non_scored_failures(self):
        spec = fixture(1)
        base = runs(spec)[0]["collections"]["first"]["records"][0]
        for kind in ("invalid_candidate", "candidate_policy", "candidate_execution"):
            row = deepcopy(base)
            row.pop("verified_code")
            v = row["verification"]
            v.clear()
            v.update(verifier_version="mbpp-typed-v2", passed=False, count=0, total=2,
                     error_kind=kind, errors=[])
            if kind == "invalid_candidate":
                row["generation"]["text"] = "def broken("
                v["errors"] = ["invalid_candidate_or_payload:SyntaxError"]
            elif kind == "candidate_policy":
                row["generation"]["text"] = "import sys\ndef f(x): return x"
                v["errors"] = ["candidate_policy:unsupported_import"]
            else:
                v.update(errors=["candidate_timeout"], outputs={"error": "candidate_timeout"}, sandbox_id="sb-test",
                         candidate_sha256=base["verification"]["candidate_sha256"],
                         source_tests_sha256=base["verification"]["source_tests_sha256"])
            prompt = second_prompts(spec[0], [row])["repair"]["1"]
            self.assertNotIn("unsupported_import", prompt)
            self.assertNotIn("SyntaxError", prompt)
            self.assertNotIn("candidate_timeout", prompt)
            self.assertIn("Verifier feedback: " + ("execution_error" if kind == "candidate_execution" else kind), prompt)

    def test_duplicate_code_does_not_fall_back_to_later_pass(self):
        spec = fixture(3)
        data = runs(spec, lambda r, b, i: True, lambda r, b, i: "duplicate" if b == "first" else f"{r}-{b}-{i}")
        report = audit_paired_repair(*spec, *data)
        selection = report["teachers"]["original"]["arms"]["repair"]
        self.assertEqual(selection["solved_ids"], ["3", "2", "1"])
        self.assertEqual(selection["unique_count"], 1)
        self.assertEqual(selection["duplicate_code_ids"], ["2", "1"])

    def test_balanced_16_examples_in_frozen_order(self):
        spec = fixture(20)
        data = runs(spec)
        gate = audit_paired_repair(*spec, *data)["child_gate"]
        self.assertTrue(gate["eligible"], gate["reasons"])
        self.assertEqual(gate["category_counts"], {"numeric": 6, "collections": 5, "text": 5})
        for role in ("original", "learned"):
            self.assertEqual(gate["selected_ids"][role], [str(x) for x in range(20, 4, -1)])
            self.assertEqual(len(gate["examples"][role]), 16)
            self.assertTrue(all(set(ex) == {"prompt", "completion", "verified"} for ex in gate["examples"][role]))
        self.assertNotEqual(gate["examples"]["original"], gate["examples"]["learned"])

    def test_infeasible_common_quotas_stop_both(self):
        categories = ("numeric",) * 9 + ("text",) * 9 + ("collections",) * 8
        spec = fixture(26, categories)
        def passes(role, branch, i):
            if branch != "repair":
                return False
            return (i < 10 or i >= 18) if role == "original" else (i == 0 or i >= 9)
        gate = audit_paired_repair(*spec, *runs(spec, passes))["child_gate"]
        self.assertEqual(gate["reasons"], ["insufficient_common_category_capacity"])
        self.assertFalse(gate["eligible"])
        self.assertFalse(any(gate["examples"].values()))

    def test_gate_checks_raw_mix_and_identity_after_matching(self):
        spec = fixture(18, ("numeric", "numeric", "numeric", "numeric", "text", "collections"))
        gate = audit_paired_repair(*spec, *runs(spec))["child_gate"]
        self.assertIn("original_category_share_exceeded", gate["reasons"])
        spec = fixture(16)
        identical = runs(spec, suffix=lambda role, branch, i: f"{branch}-{i}")
        gate = audit_paired_repair(*spec, *identical)["child_gate"]
        self.assertEqual(gate["reasons"], ["identical_child_data"])
        self.assertFalse(any(gate["examples"].values()))

    def test_missing_text_never_replaced_with_fourth_category(self):
        spec = fixture(18, ("collections", "numeric", "other"))
        gate = audit_paired_repair(*spec, *runs(spec))["child_gate"]
        self.assertIn("original_missing_required_category", gate["reasons"])
        self.assertFalse(any(gate["examples"].values()))


if __name__ == "__main__":
    unittest.main()
