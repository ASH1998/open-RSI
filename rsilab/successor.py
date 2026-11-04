"""Offline audits of two teachers producing children of one starting student.

No candidate code, model, checkpoint, provider, or environment is executed or
loaded. Controllers must independently rescore outputs and verify artifact
bytes. These checks establish consistency of supplied evidence, not its origin.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from collections import Counter
import hashlib
import math
import re

from .core import FrozenJSON, digest
from .learning import _leak_keys, _outcome, _task


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _sha(value, length=64):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d}" % length, value) is not None


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _number(value, minimum=0):
    return type(value) in (int, float) and math.isfinite(value) and value >= minimum


def _snapshot(value):
    return FrozenJSON(value).to_dict()


def _seal(value):
    return {**value, "sha256": digest(value)}


def _check_seal(value, label):
    _require(value.get("sha256") == digest({k: v for k, v in value.items() if k != "sha256"}),
             f"{label} digest mismatch")


@dataclass(frozen=True)
class SuccessorPolicy:
    train_count: int = 40
    dev_count: int = 32
    retention_count: int = 16
    min_targets: int = 16
    min_categories: int = 3
    max_category_share: float = 0.60
    min_teacher_advantage: int = 3
    min_starting_gain: int = 3
    training_seed: int = 42
    max_stage_reservation_usd: float = 5.0
    max_total_reservation_usd: float = 25.0

    def __post_init__(self):
        for field in ("train_count", "dev_count", "retention_count", "min_targets",
                      "min_categories", "min_teacher_advantage", "min_starting_gain"):
            _require(_integer(getattr(self, field), 1), f"Invalid policy {field}")
        _require(self.train_count >= self.min_targets and self.min_targets >= self.min_categories,
                 "Target/category counts exceed the task budget")
        _require(_number(self.max_category_share) and 0 < self.max_category_share <= .60,
                 "Category share must be at most 0.60")
        _require(_integer(self.training_seed) and self.training_seed < 2**31, "Invalid training seed")
        _require(_number(self.max_stage_reservation_usd) and 0 < self.max_stage_reservation_usd <= 5
                 and _number(self.max_total_reservation_usd)
                 and self.max_stage_reservation_usd <= self.max_total_reservation_usd <= 25,
                 "Invalid bounded reservation policy")

    def to_dict(self):
        return asdict(self)

    @property
    def sha256(self):
        return digest(self.to_dict())

def _inventory(value):
    _require(isinstance(value, dict) and value
             and all(_text(k) and _sha(v) for k, v in value.items()), "Missing SHA-256 inventory")


def _agent(agent):
    _require(set(agent) == {"agent_id", "model_id", "revision", "tokenizer_revision",
                            "adapter_sha256", "parent_agent_sha256"}, "Incomplete agent identity")
    _require(_text(agent["agent_id"]) and _text(agent["model_id"])
             and _sha(agent["revision"], 40) and _sha(agent["tokenizer_revision"], 40),
             "Missing immutable model/tokenizer identity")
    for key in ("adapter_sha256", "parent_agent_sha256"):
        _require(agent[key] is None or _sha(agent[key]), "Invalid adapter/parent identity")
    _require(agent["adapter_sha256"] is None or agent["parent_agent_sha256"] is not None,
             "Adapter requires parent lineage")


def _base(agent):
    return {k: agent[k] for k in ("model_id", "revision", "tokenizer_revision")}


def _runtime(runtime):
    _require(set(runtime) == {"hardware", "packages", "source_hashes", "precision"},
             "Incomplete runtime controls")
    _require(_text(runtime["hardware"]) and _text(runtime["precision"])
             and isinstance(runtime["packages"], dict) and runtime["packages"]
             and all(_text(k) and _text(v) for k, v in runtime["packages"].items()),
             "Invalid hardware/packages/precision")
    _inventory(runtime["source_hashes"])


def _inference(controls, count):
    _require(set(controls) == {"generation", "runtime", "evaluator", "effective_seeds"},
             "Incomplete inference controls")
    gen = controls["generation"]
    _require(set(gen) == {"seed", "temperature", "max_input_tokens", "max_new_tokens", "enable_thinking"},
             "Incomplete generation controls")
    _require(_integer(gen["seed"]) and gen["seed"] < 2**31 and _number(gen["temperature"])
             and _integer(gen["max_input_tokens"], 1) and _integer(gen["max_new_tokens"], 1)
             and type(gen["enable_thinking"]) is bool, "Invalid generation controls")
    seeds = controls["effective_seeds"]
    _require(isinstance(seeds, list) and len(seeds) == count
             and all(_integer(seed) and seed < 2**31 for seed in seeds), "Invalid effective seeds")
    _runtime(controls["runtime"])
    evaluator = controls["evaluator"]
    _require(set(evaluator) == {"version", "source_hashes"} and _text(evaluator["version"]),
             "Incomplete evaluator identity")
    _inventory(evaluator["source_hashes"])


def _training_controls(controls):
    _require(set(controls) == {"steps", "gradient_accumulation", "micro_batch_size", "max_length",
                              "learning_rate", "optimizer", "scheduler", "adapter_config", "runtime"},
             "Incomplete student training controls")
    for key in ("steps", "gradient_accumulation", "micro_batch_size", "max_length"):
        _require(_integer(controls[key], 1), f"Invalid training {key}")
    _require(_number(controls["learning_rate"]) and controls["learning_rate"] > 0
             and _text(controls["optimizer"]) and _text(controls["scheduler"])
             and isinstance(controls["adapter_config"], dict) and controls["adapter_config"],
             "Missing training algorithm controls")
    _runtime(controls["runtime"])


def _identity(item):
    _require(isinstance(item, dict) and _text(item.get("id")) and _text(item.get("prompt")),
             "Registry needs task ID and public prompt")
    _require(isinstance(item.get("metadata", {}), dict), "Invalid task metadata")
    keys = _leak_keys(item)
    metadata = item.get("metadata", {})
    if "dataset" in metadata and "source_id" in metadata:
        # Native integer IDs and their JSON string representation are the same
        # source identity, even when separate importers use different types.
        keys.add(("native-source-id", str(metadata["dataset"]), str(metadata["source_id"])))
    return keys


def _registry(items, *, unique=True):
    _require(isinstance(items, list), "Registry must be a list")
    keys = set()
    for item in items:
        identity = _identity(item)
        _require(not unique or not (keys & identity), "Duplicate within active registry")
        keys.update(identity)
    return keys


def _validate_protocol(protocol, policy):
    _require(protocol.get("schema_version") == 1 and type(protocol["schema_version"]) is int
             and protocol.get("policy") == policy.to_dict(), "Protocol policy/schema mismatch")
    _require(protocol.get("selection") == "all_unique_earliest_verified"
             and protocol.get("teacher_context_sha256") == digest([]), "Require fixed selection and empty teacher history")
    _require(protocol.get("exclusion_registry_complete") is True
             and protocol.get("prior_exposure_registry_complete") is True,
             "Complete final/exposure registries must be declared")
    teachers = protocol["teachers"]
    _require(set(teachers) == {"original", "learned"}, "Require two teacher arms")
    for agent in (*teachers.values(), protocol["starting_student"]):
        _agent(agent)
    original, learned = teachers["original"], teachers["learned"]
    _require(original["agent_id"] != learned["agent_id"] and _base(original) == _base(learned)
             and learned["parent_agent_sha256"] == digest(original)
             and _sha(learned["adapter_sha256"])
             and learned["adapter_sha256"] != original["adapter_sha256"], "Invalid learned-teacher lineage")
    registries = protocol["registries"]
    _require(set(registries) == {"train", "dev", "retention", "sealed_final", "prior_exposure"},
             "Incomplete task registries")
    _require(bool(registries["sealed_final"]), "Sealed-final registry is required")
    # Final source descriptors do not require reading final prompts or rows.
    # Explicit public identity registries may additionally be supplied when
    # already available. Neither form is sent to a model by this module.
    _require(isinstance(registries["sealed_final"], list), "Invalid sealed-final registry")
    sealed = set()
    for entry in registries["sealed_final"]:
        if "id" in entry:
            sealed.update(_identity(entry))
        else:
            _require(set(entry) == {"dataset", "revision", "source_split", "count", "file_sha256"}
                     and _text(entry["dataset"]) and _sha(entry["revision"], 40)
                     and entry["source_split"] in ("test", "final", "sealed")
                     and _integer(entry["count"], 1) and _sha(entry["file_sha256"]),
                     "Invalid metadata-only sealed source descriptor")
    prior = _registry(registries["prior_exposure"], unique=False)
    active = set()
    for role, count in (("train", policy.train_count), ("dev", policy.dev_count),
                        ("retention", policy.retention_count)):
        items = registries[role]
        keys = _registry(items)
        _require(len(items) == count, f"{role} registry count mismatch")
        _require(not keys & (sealed | active), "Detected cross-split or sealed-final overlap")
        if role == "train":
            _require(not keys & prior, "Training tasks must be strictly fresh")
        for task in items:
            _task(task)
            _require(task.get("split") == ("dev" if role == "dev" else "train"), "Invalid active task split")
            metadata = task.get("metadata", {})
            source_id = metadata.get("source_id")
            _require(_text(metadata.get("dataset")) and (_text(source_id) or _integer(source_id)),
                     "Active tasks need native source identities")
            native = metadata.get("source_split")
            _require(native in (("dev", "validation") if role == "dev" else ("train",)),
                     "Native source split mismatch")
            if role == "train":
                _require(metadata.get("coding_data", {}).get("previously_generated") is not True,
                         "Training task declares prior generation")
        active.update(keys)
    controls = protocol["controls"]
    _require(set(controls) == {"teacher", "student_evaluation", "student_training"}
             and isinstance(controls["teacher"], list) and len(controls["teacher"]) == 2,
             "Require independent teacher and student controls")
    for item in controls["teacher"]:
        _inference(item, policy.train_count)
    _require(controls["teacher"][0]["runtime"] == controls["teacher"][1]["runtime"]
             and controls["teacher"][0]["evaluator"] == controls["teacher"][1]["evaluator"],
             "Teacher attempts must use the same runtime/evaluator")
    _inference(controls["student_evaluation"], policy.dev_count + policy.retention_count)
    _training_controls(controls["student_training"])


def freeze_successor_protocol(spec: dict, *, policy: SuccessorPolicy = SuccessorPolicy()) -> dict:
    """Validate and hash a new protocol; refuses to silently re-sign a frozen one."""
    spec = _snapshot(spec)
    _require("sha256" not in spec, "Protocol is already frozen")
    _validate_protocol(spec, policy)
    return _seal(spec)


def _protocol(value, policy):
    value = _snapshot(value)
    _check_seal(value, "Protocol")
    _validate_protocol(value, policy)
    return value


def inference_request_sha256(agent, controls, tasks):
    """Digest the normalized public-only request, including explicit task seeds.

    This is distinct from a provider's raw request digest. Preserve both in the
    controller report; the controller maps actual worker settings into controls.
    """
    _require(len(tasks) == len(controls["effective_seeds"]), "Request seed coverage mismatch")
    return digest({"agent": agent, "controls": controls, "prompts": [
        {"id": task["id"], "prompt": task["prompt"], "effective_seed": seed}
        for task, seed in zip(tasks, controls["effective_seeds"])]})


def _collection(collection, agent, tasks, expected_controls):
    _require(collection.get("status") == "completed", "Incomplete inference collection")
    _require(collection.get("agent") == agent, "Inference agent identity mismatch")
    controls = collection["controls"]
    _inference(controls, len(tasks))
    _require(collection.get("request_sha256") == inference_request_sha256(agent, controls, tasks),
             "Public inference request digest mismatch")
    rows = collection["records"]
    _require(isinstance(rows, list) and [row["task"] for row in rows] == tasks,
             "Raw record task coverage/order mismatch")
    passed = []
    for row, seed in zip(rows, controls["effective_seeds"]):
        _require(type(row.get("effective_seed")) is int and row["effective_seed"] == seed,
                 "Per-record effective seed mismatch")
        for key, bound in (("input_tokens", "max_input_tokens"), ("output_tokens", "max_new_tokens")):
            _require(_integer(row["generation"].get(key))
                     and row["generation"][key] <= controls["generation"][bound], "Inference token budget exceeded")
        passed.append(_outcome(row, evaluator=controls["evaluator"]))
        verification = row["verification"]
        if not row["generation"]["hit_token_limit"] and verification.get("error_kind") not in ("candidate_policy", "invalid_candidate"):
            _require("outputs" in verification, "Missing raw verification outputs")
            outputs = verification["outputs"]
            _require((isinstance(outputs, list) and len(outputs) == len(row["task"]["cases"])
                      and all(isinstance(output, dict) for output in outputs))
                     or (outputs is None and verification.get("error_kind") == "candidate_execution"
                         and verification["passed"] is False and bool(verification["errors"])),
                     "Incomplete raw verification outputs")
            _require(verification.get("source_tests_sha256") == row["task"]["source_tests_sha256"]
                     and _sha(verification.get("candidate_sha256")), "Missing code/test evidence binding")
    return passed, controls == expected_controls


def _stage(stage, rows, policy):
    _require(_text(stage.get("run_id")), "Missing durable run identity")
    reservation = stage["reservation"]
    _require(_text(reservation.get("id")) and _number(reservation.get("amount_usd"))
             and 0 < reservation["amount_usd"] <= policy.max_stage_reservation_usd,
             "Invalid stage reservation")
    usage = stage["usage"]
    for key in ("wall_seconds", "estimated_cost_usd"):
        _require(_number(usage.get(key)), f"Invalid usage {key}")
    _require(usage["estimated_cost_usd"] <= reservation["amount_usd"], "Stage cost exceeds reservation")
    for key in ("input_tokens", "output_tokens"):
        _require(_integer(usage.get(key)) and usage[key] == sum(row["generation"][key] for row in rows),
                 "Usage token totals disagree with raw evidence")
    _inventory(stage.get("artifact_inventory"))
    _require(stage.get("artifacts_verified") is True and stage.get("outputs_rescored") is True,
             "Controller must verify artifacts and independently rescore outputs")


def _budget(stages, policy):
    _require(len({stage["run_id"] for stage in stages}) == len(stages), "Duplicate stage run identity")
    _require(len({stage["reservation"]["id"] for stage in stages}) == len(stages),
             "Distinct stages require distinct reservations")
    reserved = sum(stage["reservation"]["amount_usd"] for stage in stages)
    _require(reserved <= policy.max_total_reservation_usd, "Study reservation envelope exceeded")
    return {"reserved_usd": reserved,
            "estimated_cost_usd": sum(stage["usage"]["estimated_cost_usd"] for stage in stages),
            "billing_reconciled": False}


def _select(attempts, policy):
    """A new policy/selection contract; does not weaken historical LearningPolicy."""
    selected, skipped, seen_tasks, seen_code = [], [], set(), set()
    for attempt in sorted(attempts, key=lambda a: (a["record"]["task"]["id"], a["attempt_index"])):
        row, attempt_id = attempt["record"], attempt["attempt_id"]
        task = row["task"]
        if not row["verification"]["passed"]:
            skipped.append({"attempt_id": attempt_id, "reason": "failed_attempt"})
            continue
        code = row.get("verified_code")
        _require(_text(code) and code in row["generation"]["text"], "Passing target lacks generated verified code")
        code_sha = hashlib.sha256(code.encode()).hexdigest()
        _require(row["verification"].get("candidate_sha256") == code_sha
                 and row["verification"].get("source_tests_sha256") == task["source_tests_sha256"],
                 "Verified code/test digest mismatch")
        if task["id"] in seen_tasks:
            skipped.append({"attempt_id": attempt_id, "reason": "task_already_selected"})
            continue
        seen_tasks.add(task["id"])
        if code_sha in seen_code:
            skipped.append({"attempt_id": attempt_id, "reason": "duplicate_code"})
            continue
        seen_code.add(code_sha)
        selected.append({"task_id": task["id"], "category": task["category"], "prompt": task["prompt"],
                         "completion": code, "verified": True, "attempt_id": attempt_id,
                         "source_run_id": attempt["source_run_id"], "task_sha256": digest(task),
                         "code_sha256": code_sha, "verification_sha256": digest(row["verification"])})
    categories = dict(sorted(Counter(row["category"] for row in selected).items()))
    reasons = []
    if len(selected) < policy.min_targets:
        reasons.append("too_few_targets")
    if len(categories) < policy.min_categories:
        reasons.append("too_few_categories")
    if selected and max(categories.values()) / len(selected) > policy.max_category_share:
        reasons.append("category_share_exceeded")
    return _seal({"policy_sha256": policy.sha256, "attempts_sha256": digest(attempts),
                  "selected": selected, "selected_count": len(selected), "categories": categories,
                  "skipped": skipped, "eligible": not reasons, "reasons": reasons})


def audit_improver_probe(protocol: dict, original: dict, learned: dict, *,
                         policy: SuccessorPolicy = SuccessorPolicy()) -> dict:
    """Rebuild two complete two-attempt/no-repair ledgers and their selections."""
    protocol = _protocol(protocol, policy)
    registries = protocol["registries"]
    arms, reasons = {}, []
    for role, evidence in (("original", original), ("learned", learned)):
        evidence = _snapshot(evidence)
        _require(evidence.get("protocol_sha256") == protocol["sha256"], "Probe protocol mismatch")
        _require(evidence.get("teacher") == protocol["teachers"][role], "Probe teacher identity mismatch")
        collections = evidence["collections"]
        _require(isinstance(collections, list) and len(collections) == 2, "Require two complete attempts and no repairs")
        attempts, outcomes, all_rows = [], [], []
        for index, collection in enumerate(collections):
            _require(type(collection.get("attempt_index")) is int and collection["attempt_index"] == index,
                     "Independent attempt order mismatch")
            passed, matched = _collection(collection, evidence["teacher"], registries["train"],
                                           protocol["controls"]["teacher"][index])
            if not matched:
                reasons.append(role + "_unmatched_teacher_controls")
            outcomes.append(passed)
            for row in collection["records"]:
                attempt = {"record": row, "source_run_id": evidence["run_id"], "attempt_index": index}
                attempts.append({**attempt, "attempt_id": digest(attempt)})
                all_rows.append(row)
        _stage(evidence, all_rows, policy)
        selection = _select(attempts, policy)
        if not selection["eligible"]:
            reasons.extend(role + "_" + reason for reason in selection["reasons"])
        examples = [{key: row[key] for key in ("prompt", "completion", "verified")}
                    for row in selection["selected"]]
        arms[role] = {"evidence": evidence, "selection": selection, "examples_sha256": digest(examples),
                      "yield": {"attempt_successes": [sum(values) for values in outcomes],
                                "unique_solved_tasks": sum(a or b for a, b in zip(*outcomes)),
                                "selected_targets": selection["selected_count"],
                                "categories": selection["categories"]}}
    resources = _budget([arm["evidence"] for arm in arms.values()], policy)
    matched = not any("unmatched" in reason for reason in reasons)
    if arms["original"]["examples_sha256"] == arms["learned"]["examples_sha256"]:
        reasons.append("identical_training_examples")
    return _seal({"schema_version": 1, "protocol_sha256": protocol["sha256"], "policy_sha256": policy.sha256,
                  "arms": arms, "matched": matched, "eligible": not reasons,
                  "reasons": sorted(set(reasons)), "resources": resources,
                  "successor_improvement_measured": False, "promoted": False,
                  "selected_agent_id": protocol["starting_student"]["agent_id"], "sustained_rsi": False})


def _child(child, role, protocol, probe, policy):
    _require(child.get("protocol_sha256") == protocol["sha256"], "Child protocol mismatch")
    _require(child.get("teacher") == protocol["teachers"][role], "Child teacher lineage mismatch")
    student = protocol["starting_student"]
    _require(child.get("starting_student") == student, "Children must start from the identical student")
    agent = child["agent"]
    _agent(agent)
    _require(_base(agent) == _base(student) and agent["parent_agent_sha256"] == digest(student)
             and _sha(agent["adapter_sha256"])
             and agent["adapter_sha256"] not in {student["adapter_sha256"], *(a["adapter_sha256"] for a in protocol["teachers"].values())},
             "Invalid fresh child adapter lineage")
    _require(agent["agent_id"] not in {student["agent_id"], *(a["agent_id"] for a in protocol["teachers"].values())},
             "Child agent identity must be distinct")
    training = child["training"]
    _require(training.get("status") == "completed" and training.get("initialization") == "fresh"
             and "resume_checkpoint_sha256" in training and training["resume_checkpoint_sha256"] is None,
             "Require completed fresh training with no resume")
    selection = probe["arms"][role]["selection"]
    _require(training.get("selection_sha256") == selection["sha256"]
             and training.get("examples_sha256") == probe["arms"][role]["examples_sha256"]
             and type(training.get("examples_count")) is int and training["examples_count"] == selection["selected_count"],
             "Child training data lineage mismatch")
    _require(type(training.get("seed")) is int and training["seed"] == policy.training_seed, "Child training seed mismatch")
    controls = training["controls"]
    _training_controls(controls)
    _require(type(training.get("steps_completed")) is int and training["steps_completed"] == controls["steps"],
             "Incomplete student optimizer steps")
    max_tokens = controls["steps"] * controls["gradient_accumulation"] * controls["micro_batch_size"] * controls["max_length"]
    _require(_integer(training.get("processed_tokens"), 1) and training["processed_tokens"] <= max_tokens
             and _integer(training.get("supervised_tokens"), 1)
             and training["supervised_tokens"] <= training["processed_tokens"]
             and _integer(training.get("dataset_supervised_tokens"), 1)
             and training["dataset_supervised_tokens"] <= training["examples_count"] * controls["max_length"],
             "Invalid student token accounting")
    checkpoint = training["checkpoint"]
    _require(checkpoint.get("complete") is True and type(checkpoint.get("step")) is int
             and checkpoint["step"] == training["steps_completed"]
             and checkpoint.get("adapter_sha256") == agent["adapter_sha256"]
             and checkpoint.get("optimizer_state") is True and checkpoint.get("rng_state") is True
             and checkpoint.get("scheduler_state") == ("not_used" if controls["scheduler"] == "none" else "included"),
             "Incomplete resumable checkpoint evidence")
    _inventory(child["artifact_inventory"])
    for key in ("adapter_sha256", "training_state_sha256", "metadata_sha256", "manifest_sha256"):
        _require(_sha(checkpoint.get(key)) and checkpoint[key] in child["artifact_inventory"].values(),
                 "Checkpoint file absent from verified artifact inventory")
    tasks = protocol["registries"]["dev"] + protocol["registries"]["retention"]
    outcomes, matched = _collection(child["evaluation"], agent, tasks, protocol["controls"]["student_evaluation"])
    _stage(child, child["evaluation"]["records"], policy)
    return outcomes, matched and controls == protocol["controls"]["student_training"]


def compare_successors(protocol: dict, probe: dict, starting: dict, original_child: dict,
                       learned_child: dict, *, policy: SuccessorPolicy = SuccessorPolicy()) -> dict:
    """Audit one paired child experiment, separating yield from successor gains.

    Always retain the starting student. A positive gate recommends separately
    authorized replication, never a paid launch, promotion, or recursion claim.
    """
    protocol = _protocol(protocol, policy)
    probe, starting, original_child, learned_child = map(_snapshot, (probe, starting, original_child, learned_child))
    _check_seal(probe, "Probe")
    replay = audit_improver_probe(protocol, probe["arms"]["original"]["evidence"],
                                 probe["arms"]["learned"]["evidence"], policy=policy)
    _require(probe == replay and probe["eligible"], "Require replayable eligible paired probe")
    _require(starting.get("protocol_sha256") == protocol["sha256"], "Starting evaluation protocol mismatch")
    tasks = protocol["registries"]["dev"] + protocol["registries"]["retention"]
    baseline, matched = _collection(starting["evaluation"], protocol["starting_student"], tasks,
                                     protocol["controls"]["student_evaluation"])
    _stage(starting, starting["evaluation"]["records"], policy)
    reasons = [] if matched else ["unmatched_starting_evaluation"]
    original, original_matched = _child(original_child, "original", protocol, probe, policy)
    learned, learned_matched = _child(learned_child, "learned", protocol, probe, policy)
    if not original_matched:
        reasons.append("unmatched_original_child_controls")
    if not learned_matched:
        reasons.append("unmatched_learned_child_controls")
    _require(original_child["agent"]["agent_id"] != learned_child["agent"]["agent_id"]
             and original_child["agent"]["adapter_sha256"] != learned_child["agent"]["adapter_sha256"],
             "Distinct child identities and adapters required")
    resources = _budget([starting, *(probe["arms"][role]["evidence"] for role in ("original", "learned")),
                         original_child, learned_child], policy)
    pairs, scores = [], {}
    if not reasons:
        pairs = [{"task_id": task["id"], "role": "dev" if i < policy.dev_count else "retention",
                  "starting_passed": baseline[i], "original_child_passed": original[i], "learned_child_passed": learned[i]}
                 for i, task in enumerate(tasks)]
        for role in ("dev", "retention"):
            rows = [row for row in pairs if row["role"] == role]
            scores[role] = {"total": len(rows), **{
                name: sum(row[name + "_passed"] for row in rows)
                for name in ("starting", "original_child", "learned_child")},
                "original_gain_over_starting": sum(int(r["original_child_passed"]) - int(r["starting_passed"]) for r in rows),
                "learned_gain_over_starting": sum(int(r["learned_child_passed"]) - int(r["starting_passed"]) for r in rows),
                "teacher_advantage": sum(int(r["learned_child_passed"]) - int(r["original_child_passed"]) for r in rows),
                "original_lost_starting_successes": sum(r["starting_passed"] and not r["original_child_passed"] for r in rows),
                "learned_lost_starting_successes": sum(r["starting_passed"] and not r["learned_child_passed"] for r in rows),
                "learned_lost_original_successes": sum(r["original_child_passed"] and not r["learned_child_passed"] for r in rows)}
    promising = (not reasons and scores["dev"]["teacher_advantage"] >= policy.min_teacher_advantage
                 and scores["dev"]["learned_gain_over_starting"] >= policy.min_starting_gain
                 and scores["retention"]["learned_lost_starting_successes"] == 0
                 and scores["retention"]["learned_lost_original_successes"] == 0)
    prior = _registry(protocol["registries"]["prior_exposure"], unique=False)
    return _seal({"schema_version": 1, "protocol_sha256": protocol["sha256"], "policy_sha256": policy.sha256,
                  "probe_sha256": probe["sha256"], "starting_evaluation_sha256": digest(starting),
                  "child_evidence_sha256": {"original": digest(original_child), "learned": digest(learned_child)},
                  "training_seed": policy.training_seed, "matched": not reasons, "reasons": reasons,
                  "pairs": pairs, "scores": scores, "promising": promising,
                  "probe_yields": {role: probe["arms"][role]["yield"] for role in ("original", "learned")},
                  "student_exposure": {role: {key: child["training"][key] for key in
                      ("examples_count", "steps_completed", "processed_tokens", "supervised_tokens", "dataset_supervised_tokens")}
                      for role, child in (("original", original_child), ("learned", learned_child))},
                  "previously_exposed_dev_ids": [t["id"] for t in protocol["registries"]["dev"] if _identity(t) & prior],
                  "resources": resources, "replication_recommended": promising,
                  "replication_requires_new_protocol_and_budget": True,
                  "promoted": False, "selected_agent_id": protocol["starting_student"]["agent_id"],
                  "sustained_rsi": False,
                  "interpretation": "One paired development experiment of verified-example teaching; no promotion, sealed-final, or sustained-RSI claim."})
