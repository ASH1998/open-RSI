"""Executable envelope examples and adversarial audits; no candidate execution."""
import copy
from dataclasses import FrozenInstanceError, replace
import hashlib
import unittest

from rsilab import digest
from rsilab.successor import (SuccessorPolicy, audit_improver_probe, compare_successors,
                             freeze_successor_protocol, inference_request_sha256)


def task(index, role):
    return {"id": f"{role}-{index:03}", "prompt": f"Implement {role} problem {index}.",
            "split": "dev" if role == "dev" else "train",
            "category": ("numeric", "text", "collections")[index % 3],
            "cases": [{"private_expected": index}], "source_tests_sha256": digest([role, index]),
            "metadata": {"dataset": "fixture", "source_id": f"{role}-{index}",
                         "source_split": "validation" if role == "dev" else "train"}}


def agent(name, parent=None):
    return {"agent_id": name, "model_id": "test/model", "revision": "a" * 40,
            "tokenizer_revision": "b" * 40, "adapter_sha256": digest(name) if parent else None,
            "parent_agent_sha256": digest(parent) if parent else None}


def inference_controls(count, seed=42, temperature=0.0):
    return {"generation": {"seed": seed, "temperature": temperature, "max_input_tokens": 2048,
                           "max_new_tokens": 512, "enable_thinking": False},
            "runtime": {"hardware": "test-GPU", "precision": "nf4-bfloat16",
                        "packages": {"torch": "test"}, "source_hashes": {"worker.py": digest("worker")}},
            "evaluator": {"version": "test-v2", "source_hashes": {"verifier.py": digest("verifier")}},
            "effective_seeds": [seed + index for index in range(count)]}


def protocol_fixture(policy=SuccessorPolicy()):
    original = agent("original")
    spec = {"schema_version": 1, "policy": policy.to_dict(),
            "teachers": {"original": original, "learned": agent("experimental-teacher", original)},
            "starting_student": original, "selection": "all_unique_earliest_verified",
            "teacher_context_sha256": digest([]), "exclusion_registry_complete": True,
            "prior_exposure_registry_complete": True,
            "registries": {"train": [task(i, "train") for i in range(policy.train_count)],
                           "dev": [task(i, "dev") for i in range(policy.dev_count)],
                           "retention": [task(i, "retention") for i in range(policy.retention_count)],
                           "sealed_final": [{"dataset": "fixture", "revision": "c" * 40,
                                             "source_split": "test", "count": 500,
                                             "file_sha256": digest("sealed-file")}],
                           "prior_exposure": []},
            "controls": {"teacher": [inference_controls(policy.train_count),
                                      inference_controls(policy.train_count, 31415, .7)],
                         "student_evaluation": inference_controls(policy.dev_count + policy.retention_count),
                         "student_training": {"steps": 16, "gradient_accumulation": 4, "micro_batch_size": 1,
                             "max_length": 2048, "learning_rate": 2e-5, "optimizer": "AdamW", "scheduler": "none",
                             "adapter_config": {"rank": 8, "alpha": 16},
                             "runtime": inference_controls(1)["runtime"]}}}
    return freeze_successor_protocol(spec, policy=policy)


def collection_fixture(who, controls, tasks, successes):
    rows = []
    for index, item in enumerate(tasks):
        code = f"def solve():\n    return {who['agent_id'] + item['id']!r}"
        passed = index in successes
        rows.append({"task": copy.deepcopy(item), "effective_seed": controls["effective_seeds"][index],
                     "generation": {"id": item["id"], "text": code, "input_tokens": 30, "output_tokens": 20,
                                    "hit_token_limit": False, "hit_time_limit": False},
                     "verification": {"passed": passed, "count": int(passed), "total": 1,
                         "errors": [] if passed else ["case_0:wrong_output"],
                         "outputs": [{"ok": True, "value": ["int", index if passed else -1]}],
                         "verifier_version": controls["evaluator"]["version"],
                         "evaluator_source_hashes": copy.deepcopy(controls["evaluator"]["source_hashes"]),
                         "candidate_sha256": hashlib.sha256(code.encode()).hexdigest(),
                         "source_tests_sha256": item["source_tests_sha256"]},
                     **({"verified_code": code} if passed else {})})
    return {"status": "completed", "agent": copy.deepcopy(who), "controls": copy.deepcopy(controls),
            "request_sha256": inference_request_sha256(who, controls, tasks), "records": rows}


def stage_fields(name, protocol, rows):
    return {"run_id": name, "protocol_sha256": protocol["sha256"],
            "reservation": {"id": "reservation-" + name, "amount_usd": 5.0},
            "usage": {"input_tokens": sum(r["generation"]["input_tokens"] for r in rows),
                      "output_tokens": sum(r["generation"]["output_tokens"] for r in rows),
                      "wall_seconds": 10.0, "estimated_cost_usd": .1},
            "artifact_inventory": {"report.json": digest(name)},
            "artifacts_verified": True, "outputs_rescored": True}


def probe_fixture(protocol, role, count=20):
    who = protocol["teachers"][role]
    collections = [{**collection_fixture(who, controls, protocol["registries"]["train"], range(count)),
                    "attempt_index": index} for index, controls in enumerate(protocol["controls"]["teacher"])]
    return {**stage_fields(role + "-probe", protocol, [r for c in collections for r in c["records"]]),
            "teacher": copy.deepcopy(who), "collections": collections}


def child_fixture(protocol, probe, role, dev_successes):
    student = protocol["starting_student"]
    who = agent(role + "-child", student)
    selection = probe["arms"][role]["selection"]
    tasks = protocol["registries"]["dev"] + protocol["registries"]["retention"]
    evaluation = collection_fixture(who, protocol["controls"]["student_evaluation"], tasks,
                                    set(range(dev_successes)) | set(range(32, 40)))
    checkpoint = {"complete": True, "step": 16, "adapter_sha256": who["adapter_sha256"],
                  "training_state_sha256": digest(role + "-state"), "metadata_sha256": digest(role + "-meta"),
                  "manifest_sha256": digest(role + "-manifest"), "optimizer_state": True,
                  "rng_state": True, "scheduler_state": "not_used"}
    return {**stage_fields(role + "-training", protocol, evaluation["records"]),
            "teacher": copy.deepcopy(protocol["teachers"][role]), "starting_student": copy.deepcopy(student),
            "agent": who, "evaluation": evaluation,
            "training": {"status": "completed", "initialization": "fresh", "resume_checkpoint_sha256": None,
                         "selection_sha256": selection["sha256"], "examples_sha256": probe["arms"][role]["examples_sha256"],
                         "examples_count": selection["selected_count"], "seed": protocol["policy"]["training_seed"],
                         "controls": copy.deepcopy(protocol["controls"]["student_training"]), "steps_completed": 16,
                         "processed_tokens": 16000, "supervised_tokens": 8000, "dataset_supervised_tokens": 200,
                         "checkpoint": checkpoint},
            "artifact_inventory": {key: value for key, value in checkpoint.items() if key.endswith("_sha256")}}


def comparison_fixture():
    protocol = protocol_fixture()
    original, learned = probe_fixture(protocol, "original"), probe_fixture(protocol, "learned")
    probe = audit_improver_probe(protocol, original, learned)
    tasks = protocol["registries"]["dev"] + protocol["registries"]["retention"]
    evaluation = collection_fixture(protocol["starting_student"], protocol["controls"]["student_evaluation"],
                                    tasks, set(range(10)) | set(range(32, 40)))
    starting = {**stage_fields("baseline", protocol, evaluation["records"]), "evaluation": evaluation}
    return protocol, probe, starting, child_fixture(protocol, probe, "original", 11), child_fixture(protocol, probe, "learned", 14)


def resign(value):
    value["sha256"] = digest({k: v for k, v in value.items() if k != "sha256"})
    return value


class SuccessorTests(unittest.TestCase):
    def test_policy_is_immutable_and_counts_are_configurable(self):
        policy = SuccessorPolicy(train_count=40, min_targets=16)
        self.assertEqual(policy.sha256, digest(policy.to_dict()))
        with self.assertRaises(FrozenInstanceError): policy.min_targets = 1
        for kwargs in ({"min_targets": True}, {"min_targets": 41}, {"training_seed": True},
                       {"max_category_share": float("nan")}, {"max_stage_reservation_usd": 6},
                       {"max_total_reservation_usd": 26}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): SuccessorPolicy(**kwargs)
        other = replace(policy, train_count=52, min_targets=24)
        self.assertEqual(len(protocol_fixture(other)["registries"]["train"]), 52)
        small = replace(policy, train_count=20, min_targets=16)
        protocol = protocol_fixture(small)
        probe = audit_improver_probe(protocol, probe_fixture(protocol, "original", 16),
                                     probe_fixture(protocol, "learned", 16), policy=small)
        self.assertTrue(probe["eligible"])

    def test_equal_yield_can_measure_better_successor_and_never_promotes(self):
        fixture = comparison_fixture()
        result = compare_successors(*fixture)
        self.assertTrue(result["promising"])
        self.assertEqual(result["scores"]["dev"]["teacher_advantage"], 3)
        self.assertEqual(result["scores"]["dev"]["learned_gain_over_starting"], 4)
        self.assertEqual(result["probe_yields"]["original"], result["probe_yields"]["learned"])
        self.assertFalse(result["promoted"])
        self.assertFalse(result["sustained_rsi"])
        self.assertEqual(result["selected_agent_id"], "original")
        self.assertEqual(result["resources"]["reserved_usd"], 25)
        self.assertTrue(result["replication_requires_new_protocol_and_budget"])
        self.assertEqual(result, compare_successors(*fixture))

    def test_yield_alone_is_not_successor_improvement(self):
        p = protocol_fixture()
        probe = audit_improver_probe(p, probe_fixture(p, "original", 16), probe_fixture(p, "learned", 24))
        self.assertTrue(probe["eligible"])
        self.assertFalse(probe["successor_improvement_measured"])
        _, _, baseline, _, _ = comparison_fixture()
        original = child_fixture(p, probe, "original", 11)
        learned = child_fixture(p, probe, "learned", 11)
        result = compare_successors(p, probe, baseline, original, learned)
        self.assertFalse(result["promising"])
        self.assertEqual(result["student_exposure"]["original"]["examples_count"], 16)
        self.assertEqual(result["student_exposure"]["learned"]["examples_count"], 24)

    def test_probe_reconstructs_selection_and_preserves_failure_rows(self):
        p = protocol_fixture()
        a, b = probe_fixture(p, "original"), probe_fixture(p, "learned")
        result = audit_improver_probe(p, a, b)
        selection = result["arms"]["original"]["selection"]
        self.assertEqual(selection["selected_count"], 20)
        self.assertEqual(len(selection["skipped"]), 60)
        self.assertEqual(sum(x["reason"] == "failed_attempt" for x in selection["skipped"]), 40)
        a["collections"][0]["records"][0]["generation"]["text"] = "mutated"
        self.assertNotEqual(result["arms"]["original"]["evidence"], a)
        for count in (0, 15):
            result = audit_improver_probe(p, probe_fixture(p, "original", count), b)
            self.assertFalse(result["eligible"])

    def test_missing_attempt_failure_or_infrastructure_is_not_model_evidence(self):
        for mutation in (lambda a: a["collections"].pop(),
                         lambda a: a["collections"][1]["records"].pop(),
                         lambda a: a["collections"][1]["records"][-1]["verification"].update(infrastructure_error=True)):
            p = protocol_fixture(); a = probe_fixture(p, "original"); mutation(a)
            with self.assertRaises(ValueError): audit_improver_probe(p, a, probe_fixture(p, "learned"))

    def test_raw_outputs_and_code_test_binding_required(self):
        for mutation in (lambda v: v.pop("outputs"), lambda v: v.update(outputs=[]),
                         lambda v: v.update(source_tests_sha256=digest("other-tests")),
                         lambda v: v.update(candidate_sha256="invalid")):
            p = protocol_fixture(); a = probe_fixture(p, "original")
            mutation(a["collections"][0]["records"][-1]["verification"])
            with self.assertRaises(ValueError): audit_improver_probe(p, a, probe_fixture(p, "learned"))

    def test_metadata_only_final_descriptor_and_native_source_identity(self):
        p = protocol_fixture()
        self.assertNotIn("prompt", p["registries"]["sealed_final"][0])
        for mutation in (lambda p: p["registries"]["sealed_final"][0].update(source_split="train"),
                         lambda p: p["registries"]["sealed_final"][0].update(count=True),
                         lambda p: p["registries"]["train"][0]["metadata"].pop("source_split"),
                         lambda p: p["registries"]["train"][0]["metadata"].update(source_id=True),
                         lambda p: p["registries"]["train"][0]["metadata"].update(coding_data={"previously_generated": True})):
            p = protocol_fixture(); p.pop("sha256"); mutation(p)
            with self.assertRaises(ValueError): freeze_successor_protocol(p)

    def test_student_gain_required_even_if_original_teacher_hurts(self):
        f = comparison_fixture()
        original = child_fixture(f[0], f[1], "original", 6)
        learned = child_fixture(f[0], f[1], "learned", 10)
        result = compare_successors(*f[:3], original, learned)
        self.assertEqual(result["scores"]["dev"]["teacher_advantage"], 4)
        self.assertFalse(result["promising"])

    def test_child_relative_retention_loss_blocks_even_without_starting_loss(self):
        f = comparison_fixture()
        row = f[-2]["evaluation"]["records"][40]
        row["verification"].update(passed=True, count=1, errors=[])
        result = compare_successors(*f)
        self.assertEqual(result["scores"]["retention"]["learned_lost_starting_successes"], 0)
        self.assertEqual(result["scores"]["retention"]["learned_lost_original_successes"], 1)
        self.assertFalse(result["promising"])

    def test_teacher_control_mismatch_blocks_probe_without_changing_yield_gate(self):
        p = protocol_fixture(); a = probe_fixture(p, "original")
        collection = a["collections"][0]
        collection["controls"]["runtime"]["hardware"] = "other-GPU"
        collection["request_sha256"] = inference_request_sha256(collection["agent"], collection["controls"], p["registries"]["train"])
        result = audit_improver_probe(p, a, probe_fixture(p, "learned"))
        self.assertFalse(result["matched"]); self.assertFalse(result["eligible"])

    def test_identical_training_examples_stop_uninformative_contrast(self):
        p = protocol_fixture(); a = probe_fixture(p, "original"); b = probe_fixture(p, "learned")
        for ca, cb in zip(a["collections"], b["collections"]):
            cb["records"] = copy.deepcopy(ca["records"])
        result = audit_improver_probe(p, a, b)
        self.assertFalse(result["eligible"])
        self.assertIn("identical_training_examples", result["reasons"])

    def test_failed_truncation_kept_as_model_failure(self):
        p = protocol_fixture(); a = probe_fixture(p, "original")
        row = a["collections"][0]["records"][-1]
        row["generation"]["hit_token_limit"] = True
        row["verification"] = {"passed": False, "count": 0, "total": 1,
                               "errors": ["generation_token_limit"], "error_kind": "generation_limit"}
        result = audit_improver_probe(p, a, probe_fixture(p, "learned"))
        self.assertTrue(result["eligible"])
        self.assertFalse(result["arms"]["original"]["evidence"]["collections"][0]["records"][-1]["verification"]["passed"])

    def test_category_concentration_and_duplicate_code_do_not_supply_diversity(self):
        p = protocol_fixture(); p.pop("sha256")
        for item in p["registries"]["train"]: item["category"] = "one-category"
        p = freeze_successor_protocol(p)
        result = audit_improver_probe(p, probe_fixture(p, "original"), probe_fixture(p, "learned"))
        self.assertFalse(result["eligible"])
        self.assertIn("original_too_few_categories", result["reasons"])
        p = protocol_fixture(); a = probe_fixture(p, "original")
        first = a["collections"][0]["records"][0]
        for collection in a["collections"]:
            for row in collection["records"][:20]:
                row["generation"]["text"] = first["generation"]["text"]
                row["verified_code"] = first["verified_code"]
                row["verification"]["candidate_sha256"] = first["verification"]["candidate_sha256"]
        result = audit_improver_probe(p, a, probe_fixture(p, "learned"))
        self.assertEqual(result["arms"]["original"]["selection"]["selected_count"], 1)
        self.assertFalse(result["eligible"])

    def test_known_identity_overlap_and_source_split_spoofing_rejected(self):
        for registry in ("dev", "retention", "sealed_final", "prior_exposure"):
            p = protocol_fixture(); p.pop("sha256")
            if registry in ("sealed_final", "prior_exposure"):
                p["registries"][registry].append(copy.deepcopy(p["registries"]["train"][0]))
            else:
                p["registries"][registry][0]["prompt"] = p["registries"]["train"][0]["prompt"]
            with self.subTest(registry=registry), self.assertRaises(ValueError): freeze_successor_protocol(p)
        for field in ("source_row_sha256", "duplicate_group", "cluster_id"):
            p = protocol_fixture(); p.pop("sha256")
            for role in ("train", "dev"): p["registries"][role][0]["metadata"][field] = "same"
            with self.subTest(field=field), self.assertRaises(ValueError): freeze_successor_protocol(p)
        p = protocol_fixture(); p.pop("sha256")
        p["registries"]["train"][0]["metadata"]["source_split"] = "test"
        with self.assertRaises(ValueError): freeze_successor_protocol(p)

    def test_teacher_student_and_adapter_lineage_substitution_rejected(self):
        for mutation in (lambda c, p: c.update(starting_student=p["teachers"]["learned"]),
                         lambda c, p: c.update(teacher=p["teachers"]["original"]),
                         lambda c, p: c["agent"].update(parent_agent_sha256=digest(p["teachers"]["learned"])),
                         lambda c, p: c["training"].update(resume_checkpoint_sha256=digest("resume")),
                         lambda c, p: c["training"].update(selection_sha256=digest("wrong")),
                         lambda c, p: c["training"].update(seed=43)):
            fixture = comparison_fixture(); mutation(fixture[-1], fixture[0])
            with self.assertRaises(ValueError): compare_successors(*fixture)

    def test_changed_training_controls_are_unmatched_not_a_score(self):
        f = comparison_fixture(); f[-1]["training"]["controls"]["gradient_accumulation"] = 8
        result = compare_successors(*f)
        self.assertFalse(result["matched"]); self.assertFalse(result["promising"])
        self.assertEqual(result["scores"], {}); self.assertEqual(result["pairs"], [])

    def test_independent_student_controls_and_effective_seeds(self):
        f = comparison_fixture(); evaluation = f[-1]["evaluation"]
        evaluation["controls"]["generation"]["temperature"] = .7
        tasks = [r["task"] for r in evaluation["records"]]
        evaluation["request_sha256"] = inference_request_sha256(evaluation["agent"], evaluation["controls"], tasks)
        self.assertFalse(compare_successors(*f)["matched"])
        f = comparison_fixture(); f[-1]["evaluation"]["records"][0]["effective_seed"] += 1
        with self.assertRaises(ValueError): compare_successors(*f)

    def test_retention_loss_blocks_despite_dev_gain(self):
        f = comparison_fixture(); row = f[-1]["evaluation"]["records"][32]
        row["verification"].update(passed=False, count=0, errors=["case_0:wrong_output"])
        result = compare_successors(*f)
        self.assertEqual(result["scores"]["dev"]["teacher_advantage"], 3)
        self.assertFalse(result["promising"])
        self.assertEqual(result["scores"]["retention"]["learned_lost_starting_successes"], 1)

    def test_incomplete_checkpoint_or_step_count_rejected(self):
        for field, value in (("complete", False), ("optimizer_state", False), ("rng_state", False),
                             ("scheduler_state", "included"), ("training_state_sha256", digest("absent")), ("step", 15)):
            f = comparison_fixture(); f[-1]["training"]["checkpoint"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): compare_successors(*f)
        f = comparison_fixture(); f[-1]["training"]["steps_completed"] = 15
        with self.assertRaises(ValueError): compare_successors(*f)

    def test_tampered_protocol_probe_and_selection_are_rejected(self):
        f = comparison_fixture(); f[0]["policy"]["min_targets"] = 1
        with self.assertRaises(ValueError): compare_successors(*f)
        f = comparison_fixture(); f[1]["arms"]["learned"]["selection"]["selected_count"] = 100
        resign(f[1])
        with self.assertRaises(ValueError): compare_successors(*f)
        f = comparison_fixture(); f[1]["eligible"] = False; resign(f[1])
        with self.assertRaises(ValueError): compare_successors(*f)

    def test_nonfinite_boolean_and_inconsistent_resource_evidence_rejected(self):
        for field, value in (("estimated_cost_usd", True), ("estimated_cost_usd", float("nan")),
                             ("estimated_cost_usd", 6), ("input_tokens", True), ("output_tokens", 0),
                             ("wall_seconds", -1)):
            f = comparison_fixture(); f[-1]["usage"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError): compare_successors(*f)
        f = comparison_fixture(); f[-1]["reservation"]["id"] = f[-2]["reservation"]["id"]
        with self.assertRaises(ValueError): compare_successors(*f)


if __name__ == "__main__":
    unittest.main()
