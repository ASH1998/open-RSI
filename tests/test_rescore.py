"""Synthetic immutable source/rescore records; no candidate code is executed."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from rsilab import digest
from rsilab.rescore import audit_rescores
from test_report_mbpp_driver import fixture as write_original_fixture

ROOT = Path(__file__).resolve().parents[1]
RESCORE_PROTOCOL = digest({"study": "mbpp-v1", "correction": "synthetic v2 audit fixture"})
EVALUATOR_SOURCES = {"rsi/verification.py": digest("unchanged runner"),
                     "rsi/mbpp_verification.py": digest("unchanged v1 evaluator"),
                     "rsi/mbpp_verification_v2.py": digest("new evaluator"),
                     "child_source": digest("new evaluator child source")}


def fixture(root):
    study = write_original_fixture(root)
    reports = [json.loads(path.read_text()) for path in sorted((root / "runs").glob("*/report.json"))]
    trainings = [r for r in reports if r["stage"] == "mbpp-train"]
    originals = [r for r in reports if r["stage"] != "mbpp-train"]
    for report in originals:
        for row in report["records"]:
            v = row["verification"]
            v.update(count=len(row["task"]["cases"]) if v["passed"] else 0,
                     total=len(row["task"]["cases"]), errors=[] if v["passed"] else ["case_0:wrong_output"])
    baseline = sorted((r for r in originals if r["stage"] == "mbpp-baseline"), key=lambda r: r["batch"])
    # One pre-existing generation-limit failure must never be sent for re-execution.
    source = baseline[3]
    source["generation"]["outputs"][4]["hit_token_limit"] = True
    source["records"][4]["generation"]["hit_token_limit"] = True
    source["records"][4]["verification"] = {"passed": False, "count": 0, "total": 1,
        "errors": ["generation_token_limit"], "error_kind": "generation_limit", "sandbox_id": None}
    kaggle_rows = copy.deepcopy(baseline[4]["records"])
    kaggle = {"run_id": "kaggle-source", "stage": "mbpp-kaggle-verify", "status": "completed",
              "study_sha256": study["sha256"], "provenance": copy.deepcopy(baseline[0]["provenance"]),
              "records": kaggle_rows, "generation": {"status": "completed", "provider": "kaggle",
                  "outputs": [copy.deepcopy(r["generation"]) for r in kaggle_rows], "gpu_name": "NVIDIA L4",
                  "dtype": "torch.bfloat16", "packages": {"torch": "kaggle-version"},
                  "request": {"model_id": study["protocol"]["model_id"], "revision": study["protocol"]["model_revision"],
                              "seed": 42, "max_new_tokens": 512, "manifest_hash": study["sha256"],
                              "prompts": [{"id": r["task"]["id"], "prompt": r["task"]["prompt"]} for r in kaggle_rows]}}}
    originals.append(kaggle)
    rescored = []
    for original in originals:
        rows = []
        for row in original["records"]:
            verification = copy.deepcopy(row["verification"])
            if not row["generation"]["hit_token_limit"]:
                verification["verifier_version"] = "mbpp-typed-v2"
                verification["evaluator_source_hashes"] = copy.deepcopy(EVALUATOR_SOURCES)
                if ((original["stage"] == "mbpp-baseline" and row["task"]["id"] == "task-148")
                        or (original.get("training_run") == "training-42" and row["task"]["id"] == "task-152")):
                    verification.update(passed=True, count=verification["total"], errors=[])
            rows.append({"task": copy.deepcopy(row["task"]), "generation": copy.deepcopy(row["generation"]),
                         "original_verification": copy.deepcopy(row["verification"]), "verification": verification})
        rescored.append({"stage": "mbpp-rescore-v2", "status": "completed", "source_run_id": original["run_id"],
                         "source_report_sha256": digest(original), "study_sha256": study["sha256"],
                         "evaluator_version": "mbpp-typed-v2", "rescore_protocol_sha256": RESCORE_PROTOCOL,
                         "evaluator_source_hashes": copy.deepcopy(EVALUATOR_SOURCES), "records": rows})
    return study, originals, rescored, trainings


class RescoreAuditTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "work").mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="rescore-audit-", dir=ROOT / "work")
        self.addCleanup(temporary.cleanup)
        self.data = fixture(Path(temporary.name))

    def audit(self):
        study, originals, rescored, trainings = self.data
        return audit_rescores(study, originals, rescored, training_reports=trainings,
                              rescore_protocol_sha256=RESCORE_PROTOCOL)

    def test_all_368_rows_full_parent_paired_arms_and_separate_kaggle(self):
        result = self.audit()
        self.assertEqual(result["total_records"], 368)
        self.assertEqual(result["parent_full"]["total"], 176)
        self.assertEqual(result["adapters"]["42"]["total"], 80)
        self.assertEqual(result["kaggle"]["total"], 32)
        self.assertFalse(result["kaggle"]["matched_modal_arm"])
        self.assertEqual(result["changes"]["changes"]["fail_to_pass"], 2)
        self.assertEqual(result["paired"]["42"]["scores"]["v1"]["dev"]["net_success_gain"], 4)
        self.assertEqual(result["paired"]["43"]["scores"]["v2"]["dev"]["net_success_gain"], 3)
        self.assertEqual(result["paired"]["42"]["scores"]["v2"]["retention"]["total"], 32)
        self.assertFalse(result["promoted"])
        self.assertFalse(result["training_performed"])
        self.assertEqual(result["changes"]["preserved_token_limit_failures"], 1)

    def test_input_reports_and_rescores_remain_immutable(self):
        before = digest(self.data)
        self.audit()
        self.assertEqual(digest(self.data), before)

    def test_altered_generation_text_or_task_order_rejected(self):
        self.data[2][0]["records"][0]["generation"]["text"] += "\n# changed"
        with self.assertRaisesRegex(ValueError, "saved task/generation/order"): self.audit()
        self.data[2][0]["records"][0]["generation"]["text"] = self.data[1][0]["records"][0]["generation"]["text"]
        self.data[2][0]["records"].reverse()
        with self.assertRaisesRegex(ValueError, "saved task/generation/order"): self.audit()

    def test_source_digest_and_original_verification_preserved(self):
        self.data[2][0]["source_report_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source/study digest"): self.audit()
        self.data[2][0]["source_report_sha256"] = digest(self.data[1][0])
        self.data[2][0]["records"][0]["original_verification"]["count"] = 999
        with self.assertRaisesRegex(ValueError, "Original verification"): self.audit()

    def test_same_evaluator_and_plan_required_on_every_arm(self):
        self.data[2][-1]["evaluator_source_hashes"]["rsi/verification.py"] = "1" * 64
        with self.assertRaisesRegex(ValueError, "source drift"): self.audit()
        self.data[2][-1]["evaluator_source_hashes"] = copy.deepcopy(self.data[2][0]["evaluator_source_hashes"])
        self.data[2][-1]["rescore_protocol_sha256"] = "1" * 64
        with self.assertRaisesRegex(ValueError, "protocol digest"): self.audit()

    def test_infrastructure_incomplete_missing_and_duplicate_records_rejected(self):
        row = self.data[2][0]["records"][0]
        row["verification"]["infrastructure_error"] = True
        with self.assertRaisesRegex(ValueError, "infrastructure/task"): self.audit()
        del row["verification"]["infrastructure_error"]
        self.data[2][0]["status"] = "running"
        with self.assertRaisesRegex(ValueError, "Incomplete/wrong"): self.audit()
        self.data[2][0]["status"] = "completed"
        self.data[2][-1] = self.data[2][0]
        with self.assertRaisesRegex(ValueError, "duplicate rescore source"): self.audit()
        self.data[2].pop()
        with self.assertRaisesRegex(ValueError, "all 13"): self.audit()

    def test_per_verification_evaluator_inventory_must_match_outer_report(self):
        verification = self.data[2][0]["records"][0]["verification"]
        verification["evaluator_source_hashes"]["child_source"] = "1" * 64
        with self.assertRaisesRegex(ValueError, "inventory differs"): self.audit()
        del verification["evaluator_source_hashes"]
        with self.assertRaisesRegex(ValueError, "inventory differs"): self.audit()

    def test_token_limit_cannot_be_promoted_or_reexecuted(self):
        row = next(row for report in self.data[2] for row in report["records"] if row["generation"]["hit_token_limit"])
        row["verification"]["sandbox_id"] = "new-sandbox"
        with self.assertRaisesRegex(ValueError, "without execution"): self.audit()
        row["verification"]["sandbox_id"] = None
        row["verification"]["passed"] = True
        row["verification"]["count"] = row["verification"]["total"]
        with self.assertRaisesRegex(ValueError, "token-limit failure"): self.audit()

    def test_original_model_and_runtime_provenance_cannot_drift(self):
        report = next(r for r in self.data[1] if r["stage"] == "mbpp-evaluate")
        report["generation"]["packages"]["torch"] = "different"
        with self.assertRaisesRegex(ValueError, "unmatched source/runtime"): self.audit()

    def test_boolean_numeric_coercion_does_not_hide_generation_change(self):
        row = self.data[2][0]["records"][0]
        row["generation"]["hit_time_limit"] = 0
        with self.assertRaisesRegex(ValueError, "saved task/generation/order"): self.audit()

    def test_group_flattening_requires_no_logical_rescore_run_id(self):
        groups = [{"status": "completed", "rescores": self.data[2][:6]},
                  {"status": "completed", "rescores": self.data[2][6:]}]
        self.data = (self.data[0], self.data[1], [item for group in groups for item in group["rescores"]], self.data[3])
        self.assertTrue(all("run_id" not in row for row in self.data[2]))
        self.assertEqual(self.audit()["total_records"], 368)


if __name__ == "__main__":
    unittest.main()
