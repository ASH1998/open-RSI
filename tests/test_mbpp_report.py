"""Synthetic completed reports, scored by the real typed MBPP evaluator offline."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from rsilab import Manifest, digest
from rsilab.cli import main
from rsilab.mbpp_report import BATCH_SIZE, REQUIRED_SOURCES, build_mbpp_comparison
from rsi.mbpp_verification import MBPP_VERIFIER_VERSION, convert_mbpp_tests, encode_value


def fixture():
    protocol = {
        "study": "mbpp-v1", "sizes": {"train_pool": 64, "development": 3, "training_retention": 32},
        "model_id": "openbmb/MiniCPM5-2B", "model_revision": "a" * 40,
        "generation": {"seed": 42, "temperature": 0.0, "max_new_tokens": 512, "max_input_tokens": 2048,
                       "thinking": False, "attempts_per_task": 1},
        "main_hardware": "NVIDIA L40S", "quantization": "nf4-double-bfloat16", "training": {"seeds": [42, 43]},
    }
    tasks = [{**convert_mbpp_tests(["assert solve(1) == 1"], "solve"),
              "id": f"task-{index}", "family": f"cluster-{index}",
              "split": "train" if index < 64 else "dev", "prompt": f"Implement solve, task {index}"}
             for index in range(67)]
    study = {"study": "mbpp-v1", "protocol": protocol, "tasks": tasks, "analysis_plan_sha256": digest(protocol),
             "generation_settings": {"seed": 42, "temperature": 0.0, "max_new_tokens": 512},
             "retention_ids": [task["id"] for task in tasks[:32]]}
    study["sha256"] = digest(study)
    source = {path: digest(path) for path in REQUIRED_SOURCES}
    def reports(stage, chosen):
        result = []
        for batch in range((len(chosen) + BATCH_SIZE - 1) // BATCH_SIZE):
            selected = chosen[batch * BATCH_SIZE:(batch + 1) * BATCH_SIZE]
            outputs = [{"id": task["id"], "text": "def solve(x): return x", "input_tokens": 10,
                        "output_tokens": 10, "elapsed_seconds": 0.1, "hit_token_limit": False, "hit_time_limit": False}
                       for task in selected]
            rows = []
            for task, output in zip(selected, outputs):
                passed = not (stage == "mbpp-baseline" and task["id"] == "task-64")
                rows.append({"task": task, "generation": output, "verification": {
                    "verifier_version": MBPP_VERIFIER_VERSION, "passed": passed,
                    "outputs": [{"ok": True, "value": encode_value(1 if passed else 0)}],
                }})
            result.append({"run_id": f"{stage}-{batch}", "stage": stage, "batch": batch, "status": "completed",
                           "study_sha256": study["sha256"], "task_hash": digest(selected),
                           "generation_settings": copy.deepcopy(study["generation_settings"]), "records": rows,
                           "training_run": "training-42" if stage == "mbpp-evaluate" else None,
                           "provenance": {"source_hashes": copy.deepcopy(source), "model": {
                               "model_id": protocol["model_id"], "revision": protocol["model_revision"]}},
                           "generation": {"status": "completed", "outputs": outputs, "gpu_name": "NVIDIA L40S",
                               "packages": {"torch": "2.8.0", "transformers": "5.22.1"}, "cuda_version": "12.8",
                               "model_id": protocol["model_id"], "revision": protocol["model_revision"],
                               "seed": 42, "temperature": 0.0, "max_new_tokens": 512, "enable_thinking": False,
                               "adapter_path": "/artifacts/adapters/training-42/adapter" if stage == "mbpp-evaluate" else None}})
        return result
    selected = tasks[:32] + tasks[64:]
    return study, reports("mbpp-baseline", tasks), reports("mbpp-evaluate", selected)


class MBPPReportTests(unittest.TestCase):
    def build(self, study=None, parent=None, candidate=None, **kwargs):
        if study is None:
            study, parent, candidate = fixture()
        return build_mbpp_comparison(study, parent, candidate, adapter_sha256="f" * 64, **kwargs)

    def test_matched_report_builds_real_framework_manifests(self):
        report = self.build()
        self.assertTrue(report["comparison"]["matched"])
        self.assertFalse(report["promoted"])
        parent = Manifest.from_dict(report["parent_manifest"])
        candidate = Manifest.from_dict(report["candidate_manifest"])
        self.assertEqual(parent.sha256, report["comparison"]["parent_manifest_sha256"])
        self.assertEqual(candidate.sha256, report["comparison"]["candidate_manifest_sha256"])
        self.assertEqual(len(parent.tasks), 35)
        self.assertEqual([task.id for task in parent.tasks][-3:], ["task-64", "task-65", "task-66"])
        self.assertEqual(report["evaluation_splits"]["dev"]["net_success_gain"], 1)
        self.assertEqual(report["evaluation_splits"]["retention"]["total"], 32)
        self.assertEqual(len(report["baseline_lineage"]), 3)
        self.assertIsNone(report["training_seed"])

    def test_input_batch_file_order_is_irrelevant_but_task_order_is_fixed(self):
        study, parent, candidate = fixture()
        self.assertEqual(self.build(study, parent, candidate), self.build(study, parent[::-1], candidate[::-1]))
        candidate[0]["records"] = candidate[0]["records"][::-1]
        with self.assertRaisesRegex(ValueError, "order mismatch"):
            self.build(study, parent, candidate)

    def test_missing_duplicate_and_mixed_adapter_batches(self):
        study, parent, candidate = fixture()
        for altered in (candidate[:1], [candidate[0], candidate[0]]):
            with self.subTest(altered=altered), self.assertRaises(ValueError): self.build(study, parent, altered)
        candidate[1]["training_run"] = "training-43"
        with self.assertRaisesRegex(ValueError, "mixes trained adapters"): self.build(study, parent, candidate)

    def test_study_and_protocol_tampering(self):
        study, parent, candidate = fixture()
        study["retention_ids"][0] = "task-63"
        with self.assertRaisesRegex(ValueError, "study hash"): self.build(study, parent, candidate)
        study, parent, candidate = fixture()
        study["protocol"]["generation"]["temperature"] = 1.0
        study["sha256"] = digest({key: value for key, value in study.items() if key != "sha256"})
        with self.assertRaisesRegex(ValueError, "Protocol hash"): self.build(study, parent, candidate)

    def test_changed_evaluator_or_package_prevents_matching(self):
        for kind in ("source", "package", "cuda"):
            study, parent, candidate = fixture()
            for report in candidate:
                if kind == "source": report["provenance"]["source_hashes"]["rsi/mbpp_verification.py"] = "e" * 64
                elif kind == "package": report["generation"]["packages"]["torch"] = "different"
                else: report["generation"]["cuda_version"] = "different"
            result = self.build(study, parent, candidate)
            self.assertFalse(result["comparison"]["matched"])
            self.assertEqual(result["evaluation_splits"], {})
            self.assertFalse(result["promoted"])

    def test_hardware_and_within_arm_drift_rejected(self):
        study, parent, candidate = fixture()
        candidate[0]["generation"]["gpu_name"] = "NVIDIA A10G"
        with self.assertRaisesRegex(ValueError, "actual hardware"): self.build(study, parent, candidate)
        study, parent, candidate = fixture()
        candidate[0]["generation"]["packages"]["extra"] = "1"
        with self.assertRaisesRegex(ValueError, "drift between batches"): self.build(study, parent, candidate)

    def test_raw_outputs_are_rescored_not_trusting_passed(self):
        study, parent, candidate = fixture()
        candidate[0]["records"][0]["verification"]["outputs"] = [{"ok": True, "value": encode_value(999)}]
        with self.assertRaisesRegex(ValueError, "trusted protocol scoring"): self.build(study, parent, candidate)

    def test_truncated_success_rejected_and_scored_failure_preserved(self):
        study, parent, candidate = fixture()
        candidate[0]["generation"]["outputs"][0]["hit_token_limit"] = True
        with self.assertRaisesRegex(ValueError, "generation-limit failure"): self.build(study, parent, candidate)
        candidate[0]["records"][0]["verification"] = {
            "passed": False, "count": 0, "total": 1, "errors": ["generation_token_limit"],
            "error_kind": "generation_limit", "sandbox_id": None,
        }
        report = self.build(study, parent, candidate)
        self.assertEqual(report["evaluation_splits"]["retention"]["lost_parent_successes"], 1)
        self.assertEqual(report["candidate_results"][0]["status"], "failed")

    def test_infrastructure_time_limit_and_wrong_task_hash_rejected(self):
        for kind in ("infrastructure", "time", "hash"):
            study, parent, candidate = fixture()
            if kind == "infrastructure": candidate[0]["records"][0]["verification"]["infrastructure_error"] = True
            elif kind == "time": candidate[0]["generation"]["outputs"][0]["hit_time_limit"] = True
            else: candidate[0]["task_hash"] = "0" * 64
            with self.subTest(kind=kind), self.assertRaises(ValueError): self.build(study, parent, candidate)

    def test_training_report_seed_and_adapter_lineage(self):
        study, parent, candidate = fixture()
        training = {"run_id": "training-42", "stage": "mbpp-train", "status": "completed",
                    "study_sha256": study["sha256"], "seed": 42,
                    "training": {"status": "completed", "adapter_path": "/artifacts/adapters/training-42/adapter"}}
        result = self.build(study, parent, candidate, training_report=training)
        self.assertEqual(result["training_seed"], 42)
        self.assertEqual(result["training_report_sha256"], digest(training))
        training["seed"] = 7
        with self.assertRaisesRegex(ValueError, "Undeclared"): self.build(study, parent, candidate, training_report=training)

    def test_cli_dispatch_offline(self):
        study, parent, candidate = fixture()
        work = Path(__file__).resolve().parents[1] / "work"
        with tempfile.TemporaryDirectory(dir=work, prefix="mbpp-report-test-") as folder:
            root = Path(folder)
            def save(name, data):
                path = root / name
                path.write_text(json.dumps(data))
                return str(path)
            args = ["mbpp-report", save("study.json", study), "--baseline"]
            args += [save(f"p{i}.json", report) for i, report in enumerate(parent)]
            args += ["--candidate"] + [save(f"c{i}.json", report) for i, report in enumerate(candidate)]
            args += ["--adapter-sha256", "f" * 64]
            output = io.StringIO()
            with contextlib.redirect_stdout(output): self.assertEqual(main(args), 0)
            self.assertTrue(json.loads(output.getvalue())["matched"])


if __name__ == "__main__":
    unittest.main()
