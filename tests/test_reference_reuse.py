"""Synthetic saved evidence only; never execute reference/candidate code."""
from copy import deepcopy
import hashlib
import unittest
from unittest.mock import patch

from rsilab.core import digest
from rsilab.coding_data import audit_reference_task, build_probe_task, propose_mutations
from rsilab.reference_reuse import reuse_reference_audits, reuse_reference_categories
from rsi.mbpp_verification import convert_mbpp_tests
from rsi.mbpp_verification_v2 import score_mbpp_outputs


def fixture():
    evaluator = {"synthetic-evaluator": "e" * 64}
    reference = "def solve(value):\n    return 5"
    refsha = hashlib.sha256(reference.encode()).hexdigest()
    items, audits, originals, probes, changes = [], [], [], [], []
    for index, (label, description) in enumerate([
        ("collections", "Find an item in a list."),
        ("text", "Count characters in a string."),
        ("numeric", "Calculate an integer result."),
        ("collections", "Find another item in a list."),
    ]):
        tid = f"synthetic-{index}"
        tests = ["assert solve(3) == 5", "assert solve(7) == 5"]
        task = {"id": tid, "family": tid, "split": "train", "category": "text",
                "prompt": "Common preamble mentions string.\n\n" + description,
                "entry_point": "solve", "test_list": tests, "challenge_test_list": [],
                "test_setup_code": "", "test_imports": [],
                "metadata": {"source_row_sha256": digest(tid)},
                **convert_mbpp_tests(tests, "solve")}
        proposal = propose_mutations(task)
        review = {"approved": True, "reviewer": "synthetic independent reviewer",
                  "notes": "Synthetic fixture; constant typed output supplied without code execution.",
                  "task_sha256": digest(task), "proposal_sha256": proposal["sha256"],
                  "reference_sha256": refsha,
                  "approved_mutation_ids": [m["id"] for m in proposal["mutations"]]}
        probe = build_probe_task(task, proposal, approved_mutation_ids=review["approved_mutation_ids"])

        def result(target):
            outputs = [{"ok": True, "value": ["int", 5]} for _ in target["cases"]]
            return {"candidate_sha256": refsha, "source_tests_sha256": target["source_tests_sha256"],
                    "verifier_version": "mbpp-typed-v2", "source_compiler_version": "mbpp-typed-v1",
                    "sandbox_id": f"synthetic-sandbox-{index}",
                    "evaluator_source_hashes": deepcopy(evaluator), "outputs": outputs,
                    **score_mbpp_outputs(outputs, target["cases"])}

        original, probed = result(task), result(probe)
        mutation_results = [{"id": mid, "output": output, "reference_sha256": refsha,
                             "proposal_sha256": proposal["sha256"],
                             "evaluator_source_hashes": evaluator, "sandbox_id": probed["sandbox_id"]}
                            for mid, output in zip(probe["metadata"]["probe_mutation_ids"], probed["outputs"])]
        audits.append(audit_reference_task(task, proposal, reference_sha256=refsha,
                      original_result=original, mutation_results=mutation_results, review=review))
        items.append({"id": tid, "task": task, "proposal": proposal, "reference_code": reference,
                      "reference_sha256": refsha, "review": review})
        originals.append(original); probes.append(probed)
        changes.append({"task_id": tid, "original_serialized_category": "text",
                        "independently_reviewed_category": label,
                        "source_row_sha256": task["metadata"]["source_row_sha256"],
                        "source_description": description, "reason": "Manual synthetic review."})
    prepared = {"items": items, "inventory_sha256": "a" * 64}
    ids = [item["id"] for item in items]
    report = {"run_id": "synthetic-calibration", "plan_sha256": "b" * 64,
              "status": "failed", "error_type": "ValueError", "remote_calls": [],
              "runtime_errors": [{"phase": "body", "error_type": "ValueError"}], "audits": audits}
    for key, results in [("original_references", originals), ("reference_probes", probes)]:
        records = [{"index": j, "item_id": tid, "status": "returned", "result": deepcopy(value),
                    "exception_type": None} for j, (tid, value) in enumerate(zip(ids, results))]
        report[key] = records
        report[key + "_execution"] = {"records": deepcopy(records), "issues": [],
            "submitted_ids": ids[:], "missing_ids": [], "unpersisted_ids": [],
            "validated_ids": ids[:], "succeeded": True}
    correction = {"schema_version": 1, "status": "future_protocol_input_only",
        "reviewer": "independent reviewer", "items": changes, "source_artifacts": {},
        "preserved_bindings": {"inventory_sha256": prepared["inventory_sha256"],
            "domain_review_inventory_sha256": prepared["inventory_sha256"], "plan_sha256": "b" * 64},
        "counts": {"first3_reviewed": {"collections": 1, "numeric": 1, "text": 1}}}
    bundle = dict(prepared=prepared, calibration_report=report, correction=correction,
        expected_correction_sha256="", expected_plan_sha256="b" * 64,
        expected_evaluator_source_hashes=evaluator, train_count=3,
        expected_category_counts={"collections": 1, "numeric": 1, "text": 1})
    reanchor(bundle)
    return bundle


def reanchor(bundle):
    """Bind mutations to their fixture digests to exercise deeper validators."""
    c = bundle["correction"]
    c["source_artifacts"] = {"prepared": {"canonical_json_sha256": digest(bundle["prepared"])},
        "failed_calibration": {"canonical_json_sha256": digest(bundle["calibration_report"])}}
    c["preserved_bindings"]["prepared_sha256"] = digest(bundle["prepared"])
    c["sha256"] = digest({k: v for k, v in c.items() if k != "sha256"})
    bundle["expected_correction_sha256"] = c["sha256"]


class ReferenceReuseTests(unittest.TestCase):
    def test_complete_replay_preserves_content_inputs_and_lineage(self):
        b = fixture(); before = deepcopy(b)
        with patch("rsi.verification._run_sandbox", side_effect=AssertionError("no execution")):
            result = reuse_reference_audits(**b)
        self.assertEqual(b, before)
        self.assertEqual(result["sha256"], digest({k: v for k, v in result.items() if k != "sha256"}))
        self.assertEqual(result["replayed_audit_count"], 4)
        self.assertEqual(len(result["audited_pool"]), 4)
        self.assertEqual(result["train"], result["audited_pool"][:3])
        self.assertEqual(result["preflight"]["first_n_category_counts"], b["expected_category_counts"])
        for new, old, line in zip(result["audited_pool"], b["calibration_report"]["audits"], result["lineage"]):
            self.assertEqual({k: v for k, v in new.items() if k != "category"},
                             {k: v for k, v in old["task"].items() if k != "category"})
            self.assertEqual(line["original_augmented_task_sha256"], digest(old["task"]))
            self.assertEqual(line["derived_task_sha256"], digest(new))
            self.assertEqual(line["audit_sha256"], old["sha256"])
        result["train"][0]["cases"].clear()
        self.assertTrue(result["audited_pool"][0]["cases"])
        self.assertEqual(b, before)

    def test_controller_api_and_placeholder_probe_failures_are_valid(self):
        b = fixture()
        self.assertFalse(b["calibration_report"]["reference_probes"][0]["result"]["passed"])
        x = reuse_reference_categories(prepared=b["prepared"], report=b["calibration_report"],
            correction=b["correction"], evaluator_source_hashes=b["expected_evaluator_source_hashes"],
            first_n=3, min_categories=3)
        self.assertEqual(len(x["tasks"]), 4)
        self.assertEqual(len(x["selected_tasks"]), 3)
        self.assertEqual(x["sha256"], digest({k: v for k, v in x.items() if k != "sha256"}))

    def test_pinned_hashes_and_evaluator(self):
        for field in ["expected_correction_sha256", "expected_plan_sha256"]:
            with self.subTest(field=field):
                b = fixture(); b[field] = "f" * 64
                with self.assertRaises(ValueError): reuse_reference_audits(**b)
        b = fixture(); b["expected_evaluator_source_hashes"]["synthetic-evaluator"] = "f" * 64
        with self.assertRaises(ValueError): reuse_reference_audits(**b)

    def test_changed_prepared_or_report_without_new_source_bindings(self):
        for key in ["prepared", "calibration_report"]:
            b = fixture(); b[key]["unexpected"] = True
            with self.assertRaises(ValueError): reuse_reference_audits(**b)

    def test_every_execution_completeness_field_is_enforced(self):
        for key in ["original_references", "reference_probes"]:
            for field, value in [("succeeded", False), ("succeeded", 1), ("issues", [{}]),
                                 ("missing_ids", ["synthetic-0"]), ("unpersisted_ids", ["synthetic-0"]),
                                 ("submitted_ids", []), ("validated_ids", [])]:
                with self.subTest(key=key, field=field, value=value):
                    b = fixture(); b["calibration_report"][key + "_execution"][field] = value; reanchor(b)
                    with self.assertRaises(ValueError): reuse_reference_audits(**b)

    def test_detached_duplicate_reordered_or_failed_execution_rows(self):
        for mode in ["detached", "missing", "duplicate", "reorder", "cancelled", "bool_index", "exception"]:
            with self.subTest(mode=mode):
                b = fixture(); r = b["calibration_report"]; rows = r["reference_probes"]
                if mode == "detached": rows[0]["result"]["sandbox_id"] = "different"
                elif mode == "missing": rows.pop()
                elif mode == "duplicate": rows[1] = deepcopy(rows[0])
                elif mode == "reorder": rows.reverse()
                elif mode == "cancelled": rows[0]["status"] = "cancelled"
                elif mode == "bool_index": rows[0]["index"] = False
                else: rows[0]["exception_type"] = "RuntimeError"
                if mode != "detached": r["reference_probes_execution"]["records"] = deepcopy(rows)
                reanchor(b)
                with self.assertRaises(ValueError): reuse_reference_audits(**b)

    def test_saved_result_identity_score_and_outputs_are_enforced(self):
        mutations = [("candidate_sha256", "f" * 64), ("source_tests_sha256", "f" * 64),
            ("verifier_version", "other"), ("source_compiler_version", "other"),
            ("sandbox_id", ""), ("evaluator_source_hashes", {}), ("outputs", []),
            ("count", 99), ("case_diagnostics", [{"tampered": True}]), ("infrastructure_error", True),
            ("error_kind", "invalid_task")]
        for key in ["original_references", "reference_probes"]:
            for field, value in mutations:
                with self.subTest(key=key, field=field):
                    b = fixture(); r = b["calibration_report"]; r[key][0]["result"][field] = value
                    r[key + "_execution"]["records"] = deepcopy(r[key]); reanchor(b)
                    with self.assertRaises(ValueError): reuse_reference_audits(**b)

    def test_audit_cannot_detach_mutations_or_change_task_data(self):
        for mode in ["output", "task", "eligible", "hash", "review", "original", "order"]:
            with self.subTest(mode=mode):
                b = fixture(); a = b["calibration_report"]["audits"][0]
                if mode == "output": a["mutation_results"][0]["output"]["value"] = ["int", 6]
                elif mode == "task": a["task"]["prompt"] += " Altered."
                elif mode == "eligible": a["eligible"] = False
                elif mode == "hash": a["sha256"] = "f" * 64
                elif mode == "review": a["review"]["notes"] += " Changed."
                elif mode == "original": a["original_result"]["sandbox_id"] = "different"
                else: b["calibration_report"]["audits"].reverse()
                reanchor(b)
                with self.assertRaises(ValueError): reuse_reference_audits(**b)

    def test_prepared_reference_proposal_review_and_case_identity(self):
        for mode in ["reference", "proposal", "review", "case", "prompt", "order"]:
            with self.subTest(mode=mode):
                b = fixture(); item = b["prepared"]["items"][0]
                if mode == "reference": item["reference_code"] += "\n# modified"
                elif mode == "proposal": item["proposal"]["mutations"].pop()
                elif mode == "review": item["review"]["approved_mutation_ids"].pop()
                elif mode == "case": item["task"]["cases"][0]["expected"] = ["int", 6]
                elif mode == "prompt": item["task"]["prompt"] += " changed"
                else: b["prepared"]["items"].reverse()
                reanchor(b)
                with self.assertRaises(ValueError): reuse_reference_audits(**b)

    def test_review_map_cannot_relabel_reorder_or_drop_reserves(self):
        for field, value in [("independently_reviewed_category", "numeric"),
            ("original_serialized_category", "numeric"), ("source_row_sha256", "f" * 64),
            ("source_description", "different"), ("reason", "")]:
            with self.subTest(field=field):
                b = fixture(); b["correction"]["items"][-1][field] = value; reanchor(b)
                with self.assertRaises(ValueError): reuse_reference_audits(**b)
        for mode in ["drop", "reorder", "duplicate"]:
            b = fixture(); rows = b["correction"]["items"]
            if mode == "drop": rows.pop()
            elif mode == "reorder": rows.reverse()
            else: rows[-1] = deepcopy(rows[0])
            reanchor(b)
            with self.assertRaises(ValueError): reuse_reference_audits(**b)

    def test_reject_any_gpu_or_generation_evidence_even_empty(self):
        for key, value in [("remote_calls", [{"status": "completed"}]), ("baseline", []),
            ("generation", {}), ("training", {}), ("dataset_sha256", "f" * 64),
            ("unknown_result", {})]:
            b = fixture(); b["calibration_report"][key] = value; reanchor(b)
            with self.assertRaises(ValueError): reuse_reference_audits(**b)

    def test_prefix_thresholds_and_malformed_inputs(self):
        for count in [True, 0, 5]:
            b = fixture(); b["train_count"] = count
            with self.assertRaises(ValueError): reuse_reference_audits(**b)
        b = fixture(); b["expected_category_counts"] = {"text": 3}
        with self.assertRaises(ValueError): reuse_reference_audits(**b)
        b = fixture(); b["correction"]["items"][0].pop("reason"); reanchor(b)
        with self.assertRaises(ValueError): reuse_reference_audits(**b)
        b = fixture(); b["prepared"] = []
        with self.assertRaises(ValueError): reuse_reference_audits(**b)


if __name__ == "__main__":
    unittest.main()
