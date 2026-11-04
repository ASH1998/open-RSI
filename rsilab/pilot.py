"""Offline adapters for the implemented rsi task generator and trusted scorer."""
from collections import defaultdict
import hashlib
import json

from rsi.tasks import build_tasks
from rsi.verification import VERIFIER_VERSION, score_outputs, _validate_task, SANDBOX_TIMEOUT_SECONDS

from .core import FrozenJSON, RunResult, Score, Split, Task


def pilot_tasks(split: Split | str, count_per_family: int = 4, seed: int = 42) -> tuple[Task, ...]:
    """Existing train/dev/test suite; does not invent promotion or sealed splits."""
    split = Split(split)
    if split not in (Split.TRAIN, Split.DEV, Split.TEST):
        raise ValueError("The pilot has no promotion/sealed split protocol")
    return tuple(Task(task["id"], task["family"], split, task["prompt"], FrozenJSON(task))
                 for task in build_tasks(split.value, count_per_family=count_per_family, seed=seed))


class PilotEvaluator:
    """Score bounded raw sandbox outputs; never trust a candidate's passed flag."""
    def score(self, task: Task, result: RunResult) -> Score:
        if result.task_id != task.id:
            raise ValueError("Result belongs to another task")
        if result.status == "incomplete":
            raise ValueError("Infrastructure/incomplete results cannot be scored as candidate failures")
        evidence = result.evidence.to_dict()
        if evidence.get("verifier_version") != VERIFIER_VERSION:
            raise ValueError("Unknown verifier version")
        trusted = task.trusted.to_dict()
        cases, tolerance = _validate_task(trusted, SANDBOX_TIMEOUT_SECONDS)
        details = score_outputs(evidence.get("outputs"), cases, **tolerance)
        return Score(float(details["passed"]), FrozenJSON(details))


def compare_pilot_reports(parent: dict, candidate: dict) -> dict:
    """Re-score existing reports offline; no imports of provider SDKs/controllers.

    This reports matched recorded controls, not a sealed/powered study. It
    retains source differences explicitly and never promotes an adapter.
    """
    reasons, indexed = [], []
    for label, report in (("parent", parent), ("candidate", candidate)):
        if report.get("status") != "completed" or report.get("generation", {}).get("status") != "completed":
            reasons.append(f"{label}: incomplete run/generation")
        records = report.get("records", [])
        if not records:
            reasons.append(f"{label}: missing records")
        tasks = [row["task"] for row in records]
        recorded_hash = hashlib.sha256(json.dumps(tasks, sort_keys=True).encode()).hexdigest()
        if recorded_hash != report.get("task_hash"):
            reasons.append(f"{label}: task hash mismatch")
        output_ids = [row["id"] for row in report.get("generation", {}).get("outputs", [])]
        if output_ids != [task["id"] for task in tasks]:
            reasons.append(f"{label}: generation coverage mismatch")
        if any(row.get("hit_time_limit") for row in report.get("generation", {}).get("outputs", [])):
            reasons.append(f"{label}: generation time limit")
        rows = {}
        for record in records:
            task, evidence = record["task"], record["verification"]
            if task["id"] in rows:
                reasons.append(f"{label}: duplicate task")
            if evidence.get("infrastructure_error") or evidence.get("error_kind") in {"infrastructure", "invalid_task"}:
                reasons.append(f"{label}: infrastructure/task failure")
            if evidence.get("verifier_version") != VERIFIER_VERSION:
                reasons.append(f"{label}: verifier version mismatch")
            cases, tolerance = _validate_task(task, SANDBOX_TIMEOUT_SECONDS)
            score = score_outputs(evidence.get("outputs"), cases, **tolerance)
            rows[task["id"]] = (task, int(score["passed"]))
        indexed.append(rows)
    for key in ("task_hash", "generation_settings"):
        if key not in parent or parent.get(key) != candidate.get(key):
            reasons.append(f"Mismatched {key}")
    for key in ("gpu_name", "packages", "model_id", "revision", "max_new_tokens", "temperature", "seed", "enable_thinking"):
        value = parent.get("generation", {}).get(key)
        if value is None or value != candidate.get("generation", {}).get(key):
            reasons.append(f"Mismatched generation {key}")
    sources = [report.get("provenance", {}).get("source_hashes", {}) for report in (parent, candidate)]
    for path in ("rsi/tasks.py", "rsi/verification.py"):
        if not sources[0].get(path) or sources[0].get(path) != sources[1].get(path):
            reasons.append(f"Mismatched trusted source {path}")
    left, right = indexed
    if set(left) != set(right):
        reasons.append("Task IDs differ")
    report = {"schema_version": 1, "matched": not reasons, "reasons": sorted(set(reasons)),
              "promoted": False, "selected_run_id": parent.get("run_id"), "pairs": [], "splits": {},
              "changed_sources": sorted(path for path in sources[0].keys() | sources[1].keys()
                                        if sources[0].get(path) != sources[1].get(path)),
              "decision": "Retain parent; descriptive pilot comparison is not a promotion protocol."}
    if reasons:
        return report
    groups = defaultdict(list)
    for task_id in sorted(left):
        task, a = left[task_id]
        _, b = right[task_id]
        pair = {"task_id": task_id, "split": task["split"], "parent_score": a, "candidate_score": b, "gain": b-a}
        report["pairs"].append(pair)
        groups[task["split"]].append(pair)
    for split, pairs in sorted(groups.items()):
        report["splits"][split] = {"total": len(pairs), "parent_passed": sum(x["parent_score"] for x in pairs),
                                    "candidate_passed": sum(x["candidate_score"] for x in pairs),
                                    "mean_gain": sum(x["gain"] for x in pairs) / len(pairs)}
    return report
