"""Offline report-driver fixtures; no model inference or candidate code execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.report_mbpp import build_reports, write_reports
from rsilab import digest
from rsilab.mbpp_report import REQUIRED_SOURCES
from rsi.mbpp_verification import MBPP_VERIFIER_VERSION, convert_mbpp_tests, encode_value

ROOT = Path(__file__).resolve().parents[1]


def fixture(root, gains=(4, 4), retention_losses=(0, 0)):
    protocol = json.loads((ROOT / "studies/mbpp_v1/protocol.json").read_text())
    tasks = []
    for index in range(176):
        tasks.append({**convert_mbpp_tests(["assert solve(1) == 1"], "solve"),
                      "id": f"task-{index}", "family": f"cluster-{index}",
                      "split": "train" if index < 128 else "dev",
                      "prompt": f"Implement solve, task {index}",
                      "category": ("collections", "text", "numeric", "collections")[index % 4]})
    study = {"study": "mbpp-v1", "protocol": protocol, "analysis_plan_sha256": digest(protocol),
             "tasks": tasks, "generation_settings": {"seed": 42, "temperature": 0.0, "max_new_tokens": 512},
             "retention_ids": [task["id"] for task in tasks[:32]]}
    study["sha256"] = digest(study)
    def save(relative, value):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    save("data/mbpp/study-v1.json", study)
    sources = {path: digest(path) for path in REQUIRED_SOURCES}
    provenance = {"source_hashes": sources, "model": {"model_id": protocol["model_id"], "revision": protocol["model_revision"]}}
    packages = {"torch": "2.8.0", "transformers": "5.22.1"}
    def generate(stage, chosen, seed=None, gain=0, losses=0):
        result = []
        for batch in range((len(chosen) + 31) // 32):
            part = chosen[batch*32:(batch+1)*32]
            outputs, records = [], []
            for task in part:
                index = int(task["id"].split("-")[1])
                code = f"def solve(x):\n    return x  # task {index}"
                output = {"id": task["id"], "text": code, "input_tokens": 10, "output_tokens": 10,
                          "elapsed_seconds": 0.1, "hit_token_limit": False, "hit_time_limit": False}
                passed = (index < 64 if index < 128 else index < 148 + gain)
                if seed is not None and index < losses:
                    passed = False
                verification = {"passed": passed, "verifier_version": MBPP_VERIFIER_VERSION,
                                "outputs": [{"ok": True, "value": encode_value(1 if passed else 0)}]}
                record = {"task": task, "generation": output, "verification": verification}
                if passed:
                    record["verified_code"] = code
                outputs.append(output)
                records.append(record)
            run_id = f"{stage}-{seed}-{batch}"
            report = {"run_id": run_id, "stage": stage, "batch": batch, "status": "completed",
                      "study_sha256": study["sha256"], "task_hash": digest(part), "generation_settings": study["generation_settings"],
                      "training_run": f"training-{seed}" if seed else None, "provenance": copy.deepcopy(provenance), "records": records,
                      "generation": {"status": "completed", "outputs": outputs, "gpu_name": "NVIDIA L40S", "packages": packages,
                                     "cuda_version": "12.8", "model_id": protocol["model_id"], "revision": protocol["model_revision"],
                                     "seed": 42, "temperature": 0.0, "max_new_tokens": 512, "enable_thinking": False,
                                     "adapter_path": f"/artifacts/adapters/training-{seed}/adapter" if seed else None}}
            save(f"runs/{run_id}/report.json", report)
            result.append(report)
        return result
    baseline = generate("mbpp-baseline", tasks)
    selected = [row for report in baseline for row in report["records"]
                if row["task"]["split"] == "train" and row["verification"]["passed"]]
    examples = [{"prompt": row["task"]["prompt"], "completion": row["verified_code"], "verified": True} for row in selected]
    from collections import Counter
    for seed, gain, losses in zip((42, 43), gains, retention_losses):
        run_id = f"training-{seed}"
        training = {"run_id": run_id, "stage": "mbpp-train", "status": "completed", "seed": seed,
                    "study_sha256": study["sha256"], "baseline_runs": [r["run_id"] for r in baseline],
                    "selected_ids": [r["task"]["id"] for r in selected], "dataset_hash": digest(examples),
                    "examples_count": 64, "categories": dict(Counter(r["task"]["category"] for r in selected)),
                    "provenance": copy.deepcopy(provenance),
                    "training": {"status": "completed", "adapter_path": f"/artifacts/adapters/{run_id}/adapter", "seed": seed,
                                 "steps_completed": 32, "max_steps": 32, "examples_count": 64, "learning_rate": 2e-5,
                                 "gradient_accumulation": 4, "max_length": 2048, "lora_rank": 8, "gpu_name": "NVIDIA L40S",
                                 "model_id": protocol["model_id"], "revision": protocol["model_revision"],
                                 "quantization": protocol["quantization"], "packages": packages, "cuda_version": "12.8"}}
        save(f"runs/{run_id}/report.json", training)
        adapter = root / f"artifacts/mbpp/{run_id}/adapter/adapter_model.safetensors"
        adapter.parent.mkdir(parents=True)
        adapter.write_bytes(f"synthetic test artifact seed {seed}".encode())
        generate("mbpp-evaluate", tasks[:32] + tasks[128:], seed, gain, losses)
    return study


class ReportDriverTests(unittest.TestCase):
    def setUp(self):
        work = ROOT / "work"
        work.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="report-driver-test-", dir=work)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_two_seed_thresholds_and_manifests_without_promotion(self):
        fixture(self.root, retention_losses=(1, 1))
        reports = build_reports(self.root)
        summary = reports["summary.json"]
        self.assertTrue(summary["replication_worthy"])
        self.assertFalse(summary["promoted"])
        self.assertEqual(summary["selected_yield"]["unique_targets"], 64)
        self.assertEqual(summary["baseline"]["by_split"]["train"]["total"], 128)
        self.assertEqual(summary["baseline"]["by_split_category"]["dev"]["text"]["total"], 12)
        self.assertEqual(len(reports), 7)
        self.assertEqual(summary["seeds"]["43"]["lost_parent_retention_successes"], 1)

    def test_one_seed_shortfall_or_retention_regression_fails_decision(self):
        fixture(self.root, gains=(4, 3), retention_losses=(0, 2))
        summary = build_reports(self.root)["summary.json"]
        self.assertFalse(summary["replication_worthy"])
        self.assertTrue(summary["seeds"]["42"]["threshold_met"])
        self.assertFalse(summary["seeds"]["43"]["threshold_met"])

    def test_missing_evaluation_or_adapter_refuses_without_output(self):
        fixture(self.root)
        path = self.root / "runs/mbpp-evaluate-43-2/report.json"
        original = path.read_bytes()
        path.unlink()
        with self.assertRaisesRegex(ValueError, "missing/extra batches"): build_reports(self.root)
        self.assertFalse((self.root / "artifacts/mbpp/reports").exists())
        path.write_bytes(original)
        (self.root / "artifacts/mbpp/training-43/adapter/adapter_model.safetensors").unlink()
        with self.assertRaisesRegex(ValueError, "Missing SSD adapter"): build_reports(self.root)

    def test_ambiguous_training_and_tampered_selection_refused(self):
        fixture(self.root)
        path = self.root / "runs/training-42/report.json"
        training = json.loads(path.read_text())
        training["selected_ids"][0] = "task-128"
        path.write_text(json.dumps(training))
        with self.assertRaisesRegex(ValueError, "target lineage"): build_reports(self.root)
        training["selected_ids"][0] = "task-0"
        path.write_text(json.dumps(training))
        training["run_id"] = "duplicate-training-42"
        other = self.root / "runs/duplicate-training-42/report.json"
        other.parent.mkdir()
        other.write_text(json.dumps(training))
        with self.assertRaisesRegex(ValueError, "exactly two"): build_reports(self.root)

    def test_complete_mismatched_controls_never_get_positive_decision(self):
        fixture(self.root)
        for path in (self.root / "runs").glob("mbpp-evaluate-43-*/report.json"):
            report = json.loads(path.read_text())
            report["generation"]["packages"]["torch"] = "different"
            path.write_text(json.dumps(report))
        summary = build_reports(self.root)["summary.json"]
        self.assertFalse(summary["replication_worthy"])
        self.assertFalse(summary["seeds"]["43"]["matched_controls"])
        self.assertIsNone(summary["seeds"]["43"]["net_development_gain"])

    def test_atomic_report_publication_idempotent_and_no_overwrite(self):
        fixture(self.root)
        reports = build_reports(self.root)
        destination = write_reports(self.root, reports)
        self.assertEqual(write_reports(self.root, reports), destination)
        self.assertEqual(len(list(destination.iterdir())), 8)
        original = (destination / "summary.json").read_bytes()
        reports["summary.json"]["promoted"] = True
        with self.assertRaisesRegex(ValueError, "Existing reports differ"): write_reports(self.root, reports)
        self.assertEqual((destination / "summary.json").read_bytes(), original)


    def test_truncation_counts_preserve_failures(self):
        fixture(self.root)
        for relative, index in (("runs/mbpp-baseline-None-3/report.json", 4),
                                ("runs/mbpp-evaluate-42-0/report.json", 0)):
            path = self.root / relative
            report = json.loads(path.read_text())
            report["generation"]["outputs"][index]["hit_token_limit"] = True
            report["records"][index]["generation"]["hit_token_limit"] = True
            report["records"][index]["verification"] = {
                "passed": False, "error_kind": "generation_limit", "errors": ["generation_token_limit"]}
            path.write_text(json.dumps(report))
        summary = build_reports(self.root)["summary.json"]
        self.assertEqual(summary["baseline"]["truncated_total"], 1)
        self.assertEqual(summary["seeds"]["42"]["evaluation_counts"]["truncated_total"], 1)
        self.assertEqual(summary["seeds"]["42"]["lost_parent_retention_successes"], 1)


if __name__ == "__main__":
    unittest.main()
