"""Provider-independent verified-SFT records and conservative experiment gates.

No model, candidate code, provider job, or training is executed here. Verifier
outcomes must come from the controller's independent authoritative scorer.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import math
import re
from typing import Iterable

from .core import FrozenJSON, canonical_json, digest


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _same(a, b):
    return canonical_json(a) == canonical_json(b)


def _code_sha(code):
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LearningPolicy:
    min_targets: int = 24
    min_categories: int = 3
    max_category_share: float = 0.60
    independent_attempts: int = 2
    max_repairs: int = 1
    max_repair_tasks: int = 32
    max_prompt_chars: int = 16000
    max_previous_code_chars: int = 8000
    max_feedback_chars: int = 1200
    dev_count: int = 32
    retention_count: int = 32
    min_dev_gain: int = 3
    initial_seed: int = 42
    replication_seed: int = 43

    def __post_init__(self):
        for name in ("min_targets", "min_categories", "independent_attempts", "max_repairs", "max_repair_tasks", "max_prompt_chars",
                     "max_previous_code_chars", "max_feedback_chars", "dev_count",
                     "retention_count", "min_dev_gain", "initial_seed", "replication_seed"):
            _require(type(getattr(self, name)) is int and getattr(self, name) >= 0, f"Invalid policy {name}")
        _require(self.min_targets >= 24 and self.min_categories >= 3, "Cannot weaken diversity gate")
        _require(type(self.max_category_share) in (int, float) and 0 < self.max_category_share <= 0.60,
                 "Category share must be at most 0.60")
        _require(self.independent_attempts == 2 and self.max_repairs <= 1 and self.max_repair_tasks <= 32,
                 "Require two independent attempts and at most one repair for at most 32 tasks")
        _require(self.max_prompt_chars >= 512 and self.max_previous_code_chars > 0
                 and self.max_feedback_chars >= 128, "Invalid repair prompt limits")
        _require(self.dev_count == 32 and self.retention_count > 0 and self.min_dev_gain >= 3,
                 "Require 32 development tasks, retention, and at least three net gains")
        _require((self.initial_seed, self.replication_seed) == (42, 43), "Training seeds must be 42 then 43")

    def to_dict(self):
        return asdict(self)

    @property
    def sha256(self):
        return digest(self.to_dict())


def _task(task):
    _require(isinstance(task, dict) and isinstance(task.get("id"), str) and task["id"].strip(), "Missing task ID")
    _require(isinstance(task.get("prompt"), str) and task["prompt"].strip(), "Missing public task prompt")
    _require(isinstance(task.get("category"), str) and task["category"].strip(), "Missing task category")
    _require(isinstance(task.get("cases"), list) and task["cases"], "Missing authoritative cases")
    _require(_sha(task.get("source_tests_sha256")), "Missing source tests digest")


def _leak_keys(task):
    keys = {("id", task["id"]), ("prompt", " ".join(task["prompt"].split()))}
    metadata = task.get("metadata", {})
    for key in ("source_row_sha256", "cluster_id", "duplicate_group"):
        value = metadata.get(key, task.get(key))
        if value is not None:
            keys.add((key, str(value)))
    if all(key in metadata for key in ("dataset", "source_id")):
        keys.add(("source_id", canonical_json([metadata["dataset"], metadata["source_id"]])))
    return keys


def _infrastructure(verification):
    return bool(verification.get("infrastructure_error")) or verification.get("error_kind") in {"infrastructure", "invalid_task"}


def _outcome(record, *, evaluator=None):
    task, generation, verification = record["task"], record["generation"], record["verification"]
    _require(generation.get("id") == task["id"] and isinstance(generation.get("text"), str), "Generation identity/text mismatch")
    _require(type(generation.get("hit_token_limit")) is bool and generation.get("hit_time_limit") is False,
             "Incomplete generation")
    _require(not _infrastructure(verification), "Infrastructure/task failure is not a model outcome")
    _require(type(verification.get("passed")) is bool and type(verification.get("count")) is int
             and type(verification.get("total")) is int and verification["total"] == len(task["cases"])
             and 0 <= verification["count"] <= verification["total"], "Invalid verification counts")
    _require(verification["passed"] == (verification["count"] == verification["total"]), "Contradictory verification outcome")
    _require(isinstance(verification.get("errors"), list)
             and all(isinstance(x, str) for x in verification["errors"])
             and (not verification["passed"] or not verification["errors"]), "Invalid verification errors")
    if generation["hit_token_limit"]:
        _require(not verification["passed"] and verification.get("error_kind") == "generation_limit"
                 and "generation_token_limit" in verification["errors"], "Truncation cannot pass")
    else:
        _require(isinstance(verification.get("verifier_version"), str) and verification["verifier_version"], "Missing evaluator version")
        if evaluator is not None:
            _require(verification["verifier_version"] == evaluator["version"]
                     and _same(verification.get("evaluator_source_hashes"), evaluator["source_hashes"]),
                     "Per-result evaluator identity mismatch")
    return verification["passed"]


class AttemptLedger:
    """Append-only snapshots of train-only attempts; persistence is caller-owned."""

    def __init__(self, train_tasks: Iterable[dict], *, excluded_tasks: Iterable[dict] = (),
                 policy: LearningPolicy = LearningPolicy()):
        self._policy = policy
        self._tasks = {}
        excluded = []
        excluded_keys = set()
        for task in excluded_tasks:
            _task(task)
            excluded.append(FrozenJSON(task))
            excluded_keys.update(_leak_keys(task))
        for task in train_tasks:
            _task(task)
            _require(task.get("split") == "train" and task.get("metadata", {}).get("source_split", "train") == "train",
                     "Only native training tasks may enter label collection")
            _require(task["id"] not in self._tasks and not (_leak_keys(task) & excluded_keys),
                     "Duplicate training ID or detected held-out overlap")
            self._tasks[task["id"]] = FrozenJSON(task)
        _require(bool(self._tasks), "Training pool is empty")
        self._excluded = tuple(excluded)
        self._attempts = []

    @property
    def policy(self):
        return self._policy

    @property
    def records(self):
        return tuple(record.to_dict() for record in self._attempts)

    @property
    def sha256(self):
        return digest(self.to_dict())

    def to_dict(self):
        return {"schema_version": 1, "policy": self.policy.to_dict(), "policy_sha256": self.policy.sha256,
                "train_tasks": [self._tasks[key].to_dict() for key in sorted(self._tasks)],
                "excluded_tasks_sha256": digest(sorted((task.to_dict() for task in self._excluded), key=lambda t: t["id"])),
                "attempts": list(self.records)}

    def add(self, record: dict, *, source_run_id: str, attempt_index: int = 0,
            attempt_kind: str = "initial", parent_attempt_id: str | None = None) -> dict:
        _require(isinstance(source_run_id, str) and source_run_id.strip(), "Missing source run ID")
        task = record.get("task", {})
        _require(task.get("id") in self._tasks and _same(task, self._tasks[task["id"]]), "Attempt task differs from frozen training pool")
        _require(isinstance(record.get("generation"), dict) and isinstance(record.get("verification"), dict), "Missing raw attempt evidence")
        _require(record["generation"].get("id") == task["id"] and isinstance(record["generation"].get("text"), str), "Missing raw generation")
        previous = [row for row in self.records if row["record"]["task"]["id"] == task["id"]]
        _require(type(attempt_index) is int and attempt_index == len(previous)
                 and attempt_index < self.policy.independent_attempts + self.policy.max_repairs,
                 "Attempt index/order/repair budget mismatch")
        expected_kind = ("initial", "sample", "repair")[attempt_index]
        _require(attempt_kind == expected_kind, "Attempt kind does not match sequence index")
        if attempt_kind == "repair":
            prior = previous[-1]
            _require(parent_attempt_id == prior["attempt_id"], "Repair must link the previous attempt")
            _require(all(row["record"]["verification"].get("passed") is False
                         and not _infrastructure(row["record"]["verification"]) for row in previous),
                     "Only tasks failing both independent attempts may be repaired")
            _require(sum(row["attempt_kind"] == "repair" for row in self.records) < self.policy.max_repair_tasks,
                     "Repair task quota exceeded")
        else:
            _require(parent_attempt_id is None, "Independent attempt cannot have a parent")
        payload = {"source_run_id": source_run_id, "attempt_index": attempt_index, "attempt_kind": attempt_kind,
                   "parent_attempt_id": parent_attempt_id, "policy_sha256": self.policy.sha256,
                   "task_sha256": digest(task), "record": record}
        payload["attempt_id"] = digest(payload)
        snapshot = FrozenJSON(payload)
        self._attempts.append(snapshot)
        return snapshot.to_dict()


def build_repair_prompt(task: dict, previous_code: str, verification: dict, *,
                        policy: LearningPolicy = LearningPolicy()) -> str:
    """Use public prompt + bounded code + fixed executable-feedback vocabulary."""
    _task(task)
    _require(task.get("split") == "train", "Repair labels are training-only")
    _require(isinstance(previous_code, str) and previous_code.strip(), "Missing previous code")
    _require(verification.get("passed") is False and not _infrastructure(verification), "Repair requires a model failure")
    feedback = []
    count, total = verification.get("count"), verification.get("total")
    if type(count) is int and type(total) is int and 0 <= count <= total == len(task["cases"]):
        feedback.append(f"Passed {count} of {total} executable checks.")
    allowed = {"execution_error", "invalid_result", "wrong_output"}
    for error in verification.get("errors", []):
        if not isinstance(error, str):
            continue
        match = re.fullmatch(r"case_([0-9]{1,6}):(execution_error|invalid_result|wrong_output)", error)
        if match and int(match[1]) < len(task["cases"]) and match[2] in allowed:
            feedback.append(f"Check {int(match[1])}: {match[2]}.")
        elif error == "generation_token_limit":
            feedback.append("The previous answer exceeded its generation-token budget.")
    kind = verification.get("error_kind")
    if kind in {"candidate_policy", "invalid_candidate", "candidate_execution"}:
        feedback.append({"candidate_policy": "The code violated execution policy.",
                         "invalid_candidate": "The code was not a valid candidate.",
                         "candidate_execution": "The candidate could not complete execution."}[kind])
    feedback_text = "\n".join(dict.fromkeys(feedback))[:policy.max_feedback_chars] or "The executable checks failed."
    code = previous_code[:policy.max_previous_code_chars]
    if len(code) < len(previous_code):
        code += "\n[previous code truncated]"
    prompt = (task["prompt"] + "\n\nRepair the previous implementation using the execution feedback. "
              "Return only a complete Python implementation.\nPrevious implementation:\n" + code
              + "\nExecution feedback:\n" + feedback_text)
    _require(len(prompt) <= policy.max_prompt_chars, "Repair prompt exceeds bound; do not truncate the task contract")
    return prompt


def select_verified_targets(ledger: AttemptLedger) -> dict:
    """Select earliest valid success per task, then deduplicate exact code bytes."""
    policy = ledger.policy
    reasons, selected, skipped = [], [], []
    evaluator = None
    seen_tasks, seen_code = set(), set()
    attempts = sorted(ledger.records, key=lambda row: (row["record"]["task"]["id"], row["attempt_index"], row["attempt_id"]))
    for attempt in attempts:
        row, attempt_id = attempt["record"], attempt["attempt_id"]
        task = row["task"]
        try:
            passed = _outcome(row)
        except (ValueError, KeyError, TypeError):
            reasons.append("incomplete_or_invalid_attempt_evidence")
            skipped.append({"attempt_id": attempt_id, "reason": "invalid_evidence"})
            continue
        if not passed:
            skipped.append({"attempt_id": attempt_id, "reason": "failed_attempt"})
            continue
        code = row.get("verified_code")
        _require(isinstance(code, str) and code.strip(), "Passing target lacks verified code")
        _require(code in row["generation"]["text"], "Verified code is absent from the raw generation")
        _require(row["verification"].get("candidate_sha256") == _code_sha(code)
                 and row["verification"].get("source_tests_sha256") == task["source_tests_sha256"],
                 "Verified code/test digest mismatch")
        sources = row["verification"].get("evaluator_source_hashes")
        _require(isinstance(sources, dict) and sources
                 and all(isinstance(key, str) and key and _sha(value) for key, value in sources.items()),
                 "Selected target lacks evaluator source inventory")
        identity = {"version": row["verification"]["verifier_version"], "source_hashes": sources}
        if evaluator is None:
            evaluator = identity
        elif not _same(identity, evaluator):
            reasons.append("mixed_target_evaluators")
        if task["id"] in seen_tasks:
            skipped.append({"attempt_id": attempt_id, "reason": "task_already_selected"})
            continue
        # The first verified solution determines this task's label; never seek an
        # alternate label just to evade the exact-code deduplication rule.
        seen_tasks.add(task["id"])
        code_sha = _code_sha(code)
        if code_sha in seen_code:
            skipped.append({"attempt_id": attempt_id, "reason": "duplicate_code"})
            continue
        seen_code.add(code_sha)
        selected.append({"task_id": task["id"], "category": task["category"], "prompt": task["prompt"],
                         "completion": code, "verified": True, "attempt_id": attempt_id,
                         "source_run_id": attempt["source_run_id"], "task_sha256": digest(task),
                         "code_sha256": code_sha, "verification_sha256": digest(row["verification"]),
                         "parent_attempt_id": attempt["parent_attempt_id"]})
    categories = dict(sorted(Counter(row["category"] for row in selected).items()))
    if len(selected) < policy.min_targets:
        reasons.append("too_few_targets")
    if len(categories) < policy.min_categories:
        reasons.append("too_few_categories")
    if selected and max(categories.values()) / len(selected) > policy.max_category_share:
        reasons.append("category_share_exceeded")
    missing = sorted(set(ledger._tasks) - {row["record"]["task"]["id"] for row in attempts})
    independent_counts = Counter(row["record"]["task"]["id"] for row in attempts if row["attempt_kind"] != "repair")
    incomplete = sorted(task_id for task_id in ledger._tasks if independent_counts[task_id] != policy.independent_attempts)
    if missing:
        reasons.append("missing_training_attempts")
    if incomplete:
        reasons.append("incomplete_independent_attempts")
    result = {"policy_sha256": policy.sha256, "ledger_sha256": ledger.sha256,
              "evaluator": evaluator,
              "selected": selected, "selected_count": len(selected), "categories": categories,
              "max_category_share": max(categories.values(), default=0) / len(selected) if selected else 0.0,
              "skipped": skipped, "missing_task_ids": missing, "incomplete_task_ids": incomplete, "eligible": not reasons,
              "reasons": sorted(set(reasons)), "promoted": False}
    result["sha256"] = digest(result)
    return result


def compare_learning_run(parent: dict, candidate: dict, *, tasks: Iterable[dict],
                         retention_ids: Iterable[str], policy: LearningPolicy = LearningPolicy(),
                         initial_comparison: dict | None = None) -> dict:
    """Compare complete paired evidence against explicit shared control identities.

    Each report supplies run_id, agent_id, adapter_sha256 (null for parent),
    controls, records; candidate additionally supplies training. Controls use
    generation, evaluator, model, hardware, packages, source_hashes, task_sha256.
    Records add effective_seed to the usual task/generation/verification shape.
    """
    tasks, retention = list(tasks), list(retention_ids)
    _require(len({task["id"] for task in tasks}) == len(tasks), "Duplicate comparison task IDs")
    for task in tasks:
        _task(task)
    _require(len(retention) == len(set(retention)) == policy.retention_count, "Retention identity/count mismatch")
    _require({task["id"] for task in tasks if task["split"] == "train"} == set(retention)
             and sum(task["split"] == "dev" for task in tasks) == policy.dev_count
             and len(tasks) == policy.dev_count + policy.retention_count, "Require frozen development and training-retention tasks only")
    development_keys = set().union(*(_leak_keys(task) for task in tasks if task["split"] == "dev"))
    _require(not any(_leak_keys(task) & development_keys for task in tasks if task["split"] == "train"),
             "Detected duplicate crosses development and retention")
    for key in ("run_id", "agent_id"):
        _require(all(isinstance(report.get(key), str) and report[key] for report in (parent, candidate))
                 and parent[key] != candidate[key], f"Distinct {key} identities required")
    _require(parent.get("adapter_sha256") is None and _sha(candidate.get("adapter_sha256")), "Parent/candidate adapter identity mismatch")
    reasons, outcomes = [], []
    for report in (parent, candidate):
        control = report["controls"]
        _require(set(control) == {"generation", "evaluator", "model", "hardware", "packages", "source_hashes", "task_sha256"},
                 "Incomplete comparison controls")
        _require(control["task_sha256"] == digest(tasks), "Frozen task/order digest mismatch")
        gen = control["generation"]
        _require(set(gen) >= {"seed", "temperature", "max_new_tokens", "max_input_tokens", "enable_thinking", "attempts_per_task"}
                 and type(gen["seed"]) is int and type(gen["enable_thinking"]) is bool
                 and 0 <= gen["seed"] < 2**31
                 and type(gen["temperature"]) in (int, float) and math.isfinite(gen["temperature"]) and gen["temperature"] >= 0
                 and type(gen["attempts_per_task"]) is int and gen["attempts_per_task"] == 1 and type(gen["max_new_tokens"]) is int
                 and gen["max_new_tokens"] > 0 and type(gen["max_input_tokens"]) is int and gen["max_input_tokens"] > 0,
                 "Invalid/missing inference controls")
        _require(isinstance(control["hardware"], str) and control["hardware"]
                 and isinstance(control["packages"], dict) and control["packages"]
                 and all(isinstance(k, str) and k and isinstance(v, str) and v for k, v in control["packages"].items()),
                 "Missing hardware/runtime controls")
        model, evaluator = control["model"], control["evaluator"]
        _require(isinstance(model.get("model_id"), str) and model["model_id"]
                 and isinstance(model.get("revision"), str) and re.fullmatch(r"[0-9a-f]{40}", model["revision"]), "Missing immutable base-model identity")
        _require(isinstance(evaluator.get("version"), str) and evaluator["version"], "Missing evaluator identity")
        for inventory in (control["source_hashes"], evaluator.get("source_hashes")):
            _require(isinstance(inventory, dict) and inventory
                     and all(isinstance(key, str) and key and _sha(value) for key, value in inventory.items()), "Missing source inventory")
        rows = report["records"]
        _require(_same([row["task"] for row in rows], tasks), "Comparison task coverage/order mismatch")
        arm = []
        for row in rows:
            _require(type(row.get("effective_seed")) is int and 0 <= row["effective_seed"] < 2**31, "Missing effective per-task seed")
            output = row["generation"]
            for field, bound in (("input_tokens", "max_input_tokens"), ("output_tokens", "max_new_tokens")):
                _require(type(output.get(field)) is int and 0 <= output[field] <= gen[bound], "Generation token budget mismatch")
            arm.append(_outcome(row, evaluator=evaluator))
        outcomes.append(arm)
    if not _same(parent["controls"], candidate["controls"]):
        reasons.append("unmatched_controls")
    if [row["effective_seed"] for row in parent["records"]] != [row["effective_seed"] for row in candidate["records"]]:
        reasons.append("unmatched_effective_seeds")
    training = candidate["training"]
    _require(training.get("fresh_adapter") is True and training.get("parent_adapter_sha256") is None
             and training.get("adapter_sha256") == candidate["adapter_sha256"]
             and _sha(training.get("selection_sha256")) and type(training.get("seed")) is int,
             "Fresh-adapter training lineage required")
    seed = training["seed"]
    _require(seed in (policy.initial_seed, policy.replication_seed), "Undeclared training seed")
    if seed == policy.replication_seed:
        _require(isinstance(initial_comparison, dict)
                 and initial_comparison.get("sha256") == digest({k: v for k, v in initial_comparison.items() if k != "sha256"})
                 and initial_comparison.get("policy_sha256") == policy.sha256
                 and initial_comparison.get("training_seed") == policy.initial_seed
                 and initial_comparison.get("promising") is True
                 and initial_comparison.get("matched") is True
                 and initial_comparison.get("replication_recommended") is True
                 and initial_comparison.get("parent_report_sha256") == digest(parent)
                 and initial_comparison.get("selection_sha256") == training["selection_sha256"]
                 and initial_comparison.get("candidate_adapter_sha256") != candidate["adapter_sha256"],
                 "Seed-43 replication requires matching promising seed-42 evidence")
    pairs = [{"task_id": task["id"], "role": "retention" if task["id"] in retention else "dev",
              "parent_passed": outcomes[0][index], "candidate_passed": outcomes[1][index]}
             for index, task in enumerate(tasks)]
    scores = {}
    if not reasons:
        for role in ("dev", "retention"):
            rows = [row for row in pairs if row["role"] == role]
            scores[role] = {"total": len(rows), "parent_passed": sum(row["parent_passed"] for row in rows),
                            "candidate_passed": sum(row["candidate_passed"] for row in rows),
                            "net_success_gain": sum(int(row["candidate_passed"]) - int(row["parent_passed"]) for row in rows),
                            "lost_parent_successes": sum(row["parent_passed"] and not row["candidate_passed"] for row in rows)}
    promising = not reasons and scores["dev"]["net_success_gain"] >= policy.min_dev_gain and scores["retention"]["lost_parent_successes"] == 0
    result = {"policy_sha256": policy.sha256, "parent_report_sha256": digest(parent), "candidate_report_sha256": digest(candidate),
              "candidate_adapter_sha256": candidate["adapter_sha256"],
              "training_seed": seed, "selection_sha256": training["selection_sha256"], "matched": not reasons,
              "reasons": reasons, "pairs": pairs if not reasons else [], "scores": scores, "promising": promising,
              "replication_recommended": promising and seed == policy.initial_seed,
              "next_training_seed": policy.replication_seed if promising and seed == policy.initial_seed else None,
              "promoted": False, "selected_agent_id": parent["agent_id"],
              "interpretation": "Descriptive development/retention gate only; retain parent, no RSI or held-out-family claim."}
    result["sha256"] = digest(result)
    return result
