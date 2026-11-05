"""Offline controller regressions. GPU, sandbox, budget and tracking calls are faked."""
from copy import deepcopy
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from rsi import repair_study as repair
from rsi.mbpp_verification_v2 import score_mbpp_outputs
from rsilab import digest
from rsilab.paired_repair import audit_paired_repair
from rsilab.project import Workspace
from rsilab.providers.modal import ModalBackend
from rsilab.task_contracts import apply_task_contracts
from rsilab.workflow import VerifiedCollector
from test_task_contracts import fixture


class FakeFunction:
    def __init__(self, plan, teacher, all_pass=False):
        self.plan = plan
        self.teacher = teacher
        self.all_pass = all_pass
        self.requests = []

    def spawn(self, request):
        self.requests.append(deepcopy(request))
        success = self.all_pass or len(self.requests) == 3
        text = ("def inside(x,lo,hi): return lo <= x < hi" if success
                else "def inside(x,lo,hi): return int(lo <= x < hi)")
        outputs = [{"id": p["id"], "text": text, "hit_token_limit": False, "hit_time_limit": False,
                    "input_tokens": len(p["prompt"]), "output_tokens": 23} for p in request["prompts"]]
        response = {k: v for k, v in request.items() if k not in ("prompts", "max_input_tokens")}
        response.update(status="completed", portable_worker=repair.worker_identity(self.plan), gpu_name="NVIDIA L40S",
                        packages={"fixture": "1"}, enable_thinking=False, outputs=outputs)
        call = MagicMock()
        call.object_id = "fixture-" + str(len(self.requests))
        call.get.return_value = response
        return call


def synthetic_run(role, all_pass=False):
    source, review = fixture()
    manifest = apply_task_contracts([source], [review])
    original = {"agent_id": "base", "model_id": "example/model", "revision": "a" * 40,
                "tokenizer_revision": "a" * 40, "adapter_sha256": None, "parent_agent_sha256": None}
    learned = {**original, "agent_id": "learned", "adapter_sha256": "b" * 64, "parent_agent_sha256": digest(original)}
    plan = {"source_hashes": {"rsilab/task_contracts.py": "e" * 64},
            "model": {"model_id": "example/model", "revision": "a" * 40}, "teachers": {"original": original, "learned": learned},
            "learned_adapter_path": "/artifacts/adapters/test"}
    study = repair.RepairStudy.__new__(repair.RepairStudy)
    study.plan, study.train = plan, manifest
    study.packages, study.ws = {"fixture": "1"}, MagicMock()
    study.manifests = {source["id"]: manifest}
    report = {"run_id": "fixture-" + role}
    function = FakeFunction(plan, plan["teachers"][role], all_pass)
    backend = ModalBackend(generate_function=function, train_function=None, report=report,
                           persist=study.ws.persist, max_calls=3)

    def verify(text, task):
        outputs = [{"ok": True, "value": c["expected"]} for c in task["cases"]]
        if "int(" in text:
            for output in outputs:
                output["value"] = ["int", int(output["value"][1])]
        result = {**score_mbpp_outputs(outputs, task["cases"]), "outputs": outputs,
                  "verifier_version": "mbpp-typed-v2", "evaluator_source_hashes": repair.evaluator_source_hashes(),
                  "candidate_sha256": hashlib.sha256(text.encode()).hexdigest(),
                  "source_tests_sha256": task["source_tests_sha256"], "sandbox_id": "sandbox-fixture"}
        return repair.score_result(manifest, task, result)

    engine = VerifiedCollector(backend=backend, verify=verify, extract_code=repair.extract_code,
                               report=report, persist=study.ws.persist)
    run = study.teacher_collections(report, role, engine)
    return study, run, report, function.requests


class TeacherTests(unittest.TestCase):
    def test_real_collection_replay_and_paired_library_with_test_doubles(self):
        study, original, report, requests = synthetic_run("original")
        _, learned, _, _ = synthetic_run("learned")
        self.assertEqual(original, study.teacher_collections(report, "original"))
        self.assertEqual(len(requests), 3)
        for request in requests:
            repair.validate_request("generate", request, repair.worker_config(study.plan))
        self.assertEqual(requests[0]["prompts"], requests[1]["prompts"])
        self.assertNotEqual(requests[1]["prompts"], requests[2]["prompts"])
        self.assertIn("Verifier feedback: wrong_output.", requests[2]["prompts"][0]["prompt"])
        self.assertNotIn("inside(5, 3, 5)", requests[2]["prompts"][0]["prompt"])
        row = report["first"][0]
        self.assertTrue(row["verification"]["executor_score"]["passed"])
        self.assertFalse(row["verification"]["passed"])
        self.assertNotIn("verified_code", row)
        controls = original["collections"]
        paired = audit_paired_repair(study.train, study.plan["teachers"],
                                     {"first": controls["first"]["controls"], "second": controls["sample"]["controls"]},
                                     original, learned)
        self.assertEqual(paired["teachers"]["original"]["paired_unique"]["right_only"], ["window"])
        self.assertFalse(paired["child_gate"]["eligible"])

    def test_all_pass_still_physical_second_and_third_call(self):
        study, original, report, requests = synthetic_run("original", all_pass=True)
        self.assertEqual(requests[1], requests[2])
        self.assertNotEqual(report["remote_calls"][1]["call_id"], report["remote_calls"][2]["call_id"])
        self.assertEqual(original, study.teacher_collections(report, "original"))
        report["remote_calls"][2]["call_id"] = report["remote_calls"][1]["call_id"]
        with self.assertRaisesRegex(ValueError, "physical provider call"):
            study.teacher_collections(report, "original")

    def test_tampered_call_or_repair_prompt_rejected(self):
        study, _, report, _ = synthetic_run("original")
        report["public_requests"]["repair"][0]["prompt"] += " private content"
        with self.assertRaisesRegex(ValueError, "prompts differ"):
            study.teacher_collections(report, "original")
        report["remote_calls"][0]["request_sha256"] = digest("invented")
        with self.assertRaisesRegex(ValueError, "provider result"):
            study.teacher_collections(report, "original")

    def test_isolation_error_blocks_further_outcomes(self):
        with self.assertRaisesRegex(ValueError, "infrastructure"):
            repair.score_result(None, {}, {"infrastructure_error": True})


class BudgetAndGateTests(unittest.TestCase):
    def test_orphaned_failed_reserved_stage_is_never_retried(self):
        policy = {"project_cap": 250, "overhead_reserve": 25}
        ledger = {"reservations": [{"stage": repair.PREFIX + "baseline", "reserved_usd": 4, "status": "failed"}]}
        with self.assertRaisesRegex(ValueError, "already reserved"):
            repair.validate_reservation(policy, ledger, repair.PREFIX + "baseline", 4)

    def test_family_and_global_headroom(self):
        policy = {"project_cap": 250, "overhead_reserve": 25}
        for stage, usd, reason in (("repair-v0-older", 23, "family cap"), ("external", 215, "unallocated")):
            with self.subTest(stage=stage), self.assertRaisesRegex(ValueError, reason):
                repair.validate_reservation(policy, {"reservations": [{"stage": stage, "reserved_usd": usd}]},
                                            repair.PREFIX + "child-original", 5)
        self.assertEqual(sum(repair.RESERVATIONS.values()), 25)
        ledger = {"reservations": [{"stage": "external", "reserved_usd": 194}]}
        for name, amount in repair.RESERVATIONS.items():
            repair.validate_reservation(policy, ledger, repair.PREFIX + name, amount)
            ledger["reservations"].append({"stage": repair.PREFIX + name, "reserved_usd": amount})
        self.assertEqual(250 - 25 - sum(r["reserved_usd"] for r in ledger["reservations"]), 6)

    def test_failed_gate_blocks_child_before_any_compute(self):
        study = repair.RepairStudy.__new__(repair.RepairStudy)
        with patch.object(study, "completed"), patch.object(study, "load_probe"), patch.object(study, "evaluation_scores"), \
                patch.object(study, "paired_report", return_value={"child_gate": {"eligible": False}}), \
                self.assertRaisesRegex(ValueError, "gate failed"):
            study.prerequisites("child-original")

    def test_baseline_requires_cpu_probe(self):
        study = repair.RepairStudy.__new__(repair.RepairStudy)
        with patch.object(study, "load_probe", side_effect=ValueError("missing probe")), self.assertRaisesRegex(ValueError, "missing probe"):
            study.prerequisites("baseline")

    def test_report_preserves_discordant_tasks(self):
        result = repair.compare_passes({"a": True, "b": False, "c": False}, {"a": False, "b": True, "c": True})
        self.assertEqual(result["net"], 1)
        self.assertEqual(result["gains"], ["b", "c"])
        self.assertEqual(result["losses"], ["a"])

    def test_save_once_prevents_destructive_replay(self):
        with tempfile.TemporaryDirectory(dir=repair.ROOT / "work") as tmp:
            ws = Workspace(Path(tmp))
            repair.save_once(ws, "result.json", {"value": 1})
            with self.assertRaisesRegex(ValueError, "Existing evidence"):
                repair.save_once(ws, "result.json", {"value": 2})
            self.assertEqual(ws.read_json("result.json"), {"value": 1})


class FrozenInputsTests(unittest.TestCase):
    def setUp(self):
        train, evaluation = (apply_task_contracts([source], [review]) for source, review in
                             (fixture("first-task"), fixture("held-out")))
        self.manifests = train, evaluation
        self.plan = {"prior_exposure_sha256": digest("prior"), "reviewed_manifest_sha256": {}}
        self.cohort = {"study": repair.STUDY, "prior_exposure_sha256": digest("prior"),
                       "manifests": {}, "reference_checks": []}
        for role, manifest in zip(("train", "evaluation"), self.manifests):
            self.plan["reviewed_manifest_sha256"][role] = manifest["sha256"]
            self.cohort[role] = deepcopy(manifest["tasks"])
            self.cohort["manifests"][role] = {"path": f"{repair.SELECTED}/{role}-manifest.json", "sha256": manifest["sha256"]}
            task = manifest["tasks"][0]
            self.cohort["reference_checks"].append({"role": role, "id": task["id"], "task_sha256": digest(task),
                                                    "reference_sha256": digest("synthetic trusted reference"),
                                                    "outputs": [{"ok": True, "value": c["expected"]} for c in task["cases"]]})

    def validate(self):
        body = {k: v for k, v in self.cohort.items() if k != "sha256"}
        repair.validate_cohort(self.plan, {**body, "sha256": digest(body)}, *self.manifests)

    def test_complete_reference_evidence(self):
        self.validate()

    def test_self_sealed_but_unreviewed_manifest_fails(self):
        train = self.manifests[0]
        train["tasks"][0]["prompt"] += "Rewritten after freeze."
        train["sha256"] = digest({k: v for k, v in train.items() if k != "sha256"})
        with self.assertRaisesRegex(ValueError, "selected train"):
            self.validate()

    def test_cohort_task_projection_differs(self):
        self.cohort["evaluation"][0]["prompt"] += "mismatch"
        with self.assertRaisesRegex(ValueError, "selected evaluation"):
            self.validate()

    def test_calibration_wrong_type_rejected(self):
        self.cohort["reference_checks"][0]["outputs"][-1]["value"] = ["int", 0]
        with self.assertRaisesRegex(ValueError, "calibration failed"):
            self.validate()

    def test_missing_reference_record_rejected(self):
        self.cohort["reference_checks"].pop()
        with self.assertRaisesRegex(ValueError, "coverage differs"):
            self.validate()

    def test_concurrent_duplicate_reservations_in_scratch_ledger(self):
        with tempfile.TemporaryDirectory(dir=repair.ROOT / "work") as tmp:
            ws = repair.RepairWorkspace(Path(tmp))
            ws.write_json("config/budget.json", {"project_cap": 250, "overhead_reserve": 25,
                                                 "max_stage_reservation": 5, "currency": "USD", "provider": "modal"})
            ws.write_json("budget/ledger.json", {"reservations": []})
            with ThreadPoolExecutor(max_workers=2) as pool:
                calls = [pool.submit(ws.reserve, "repair-v1-baseline", 4) for _ in range(2)]
            self.assertEqual(sum(call.exception() is None for call in calls), 1)
            self.assertEqual(len(ws.read_json("budget/ledger.json")["reservations"]), 1)


class ChildEvidenceTests(unittest.TestCase):
    def test_fresh_training_bound_to_exact_verified_examples(self):
        study, _, _, _ = synthetic_run("original")
        examples = [{"prompt": "fixture-" + str(i), "completion": "return 1", "verified": True} for i in range(16)]
        result = {**study.plan["model"], **repair.TRAIN, "status": "completed", "steps_completed": 16,
                  "examples_count": 16, "lora_rank": 8, "supervised_tokens": 16, "quantization": "nf4-double-bfloat16",
                  "portable_worker": repair.worker_identity(study.plan), "gpu_name": "NVIDIA L40S",
                  "packages": study.packages}
        request = {**study.plan["model"], **repair.TRAIN, "run_id": "synthetic-child", "examples": examples}
        account = {"dataset_supervised_tokens": 16}
        report = {"run_id": "synthetic-child", "training": result, "examples_sha256": digest(examples),
                  "token_accounting": account,
                  "remote_calls": [{"operation": "train", "status": "completed", "call_id": "synthetic-call",
                                    "request_sha256": digest(request), "result": result}]}
        study.check_training(report, examples, account)
        report["remote_calls"][0]["request_sha256"] = digest({**request, "resume_checkpoint": "/artifacts/other"})
        with self.assertRaisesRegex(ValueError, "fresh initialization"):
            study.check_training(report, examples, account)

    def test_probe_requires_actual_pinned_package_versions(self):
        plan = {"model": {"model_id": "test/model", "revision": "a" * 40}}
        identity = repair.worker_identity(plan)
        result = {"status": "completed", "gpu_requested": False, "portable_worker": identity,
                  "mounted_volume_is_dir": True, "volume_mount": "/artifacts", "python_version": "3.12.0",
                  "packages": dict(pin.split("==") for pin in identity["worker"]["requirements"])}
        repair.verify_probe_result(plan, result)
        result["packages"]["torch"] = "unexpected"
        with self.assertRaisesRegex(ValueError, "pin differs"):
            repair.verify_probe_result(plan, result)


if __name__ == "__main__":
    unittest.main()
