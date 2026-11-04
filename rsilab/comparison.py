"""Strictly paired descriptive comparisons; no significance or RSI-level claims."""
from __future__ import annotations
from collections import defaultdict
from typing import Sequence

from .core import Manifest, RetainParentGate, RunResult, digest


def compare(parent: Manifest, candidate: Manifest, parent_results: Sequence[RunResult],
            candidate_results: Sequence[RunResult], *, higher_is_better: bool = True) -> dict:
    """Refuse aggregate gains unless complete task/seed pairs and controls match.

    Inputs must be trusted evaluator records. Hashes detect identity changes;
    they do not authenticate who produced a result or enforce compute budgets.
    """
    reasons = []
    if type(higher_is_better) is not bool:
        raise ValueError("higher_is_better must be boolean")
    if parent.run_id == candidate.run_id or parent.agent.id == candidate.agent.id:
        reasons.append("Parent and candidate require distinct run and agent IDs")
    for name in ("tasks", "seeds", "budget", "settings", "provenance"):
        if digest(getattr(parent, name)) != digest(getattr(candidate, name)):
            reasons.append(f"Mismatched {name}")
    expected = {(task.id, seed) for task in parent.tasks for seed in parent.seeds}

    def index(manifest, results, label):
        indexed = {}
        for row in results:
            key = (row.task_id, row.seed)
            if key in indexed:
                reasons.append(f"{label}: duplicate task/seed result")
            indexed[key] = row
            if row.run_id != manifest.run_id or row.agent_id != manifest.agent.id:
                reasons.append(f"{label}: result identity mismatch")
            if row.status == "incomplete" or row.score is None:
                reasons.append(f"{label}: incomplete or unscored result")
        if set(indexed) != expected:
            reasons.append(f"{label}: missing or unexpected task/seed pairs")
        return indexed

    left = index(parent, parent_results, "parent")
    right = index(candidate, candidate_results, "candidate")
    decision = RetainParentGate().decide(parent.agent, [candidate.agent])
    report = {
        "schema_version": 1, "parent_manifest_sha256": parent.sha256,
        "candidate_manifest_sha256": candidate.sha256, "matched": not reasons,
        "reasons": sorted(set(reasons)), "pairs": [], "splits": {},
        "promoted": decision.promoted, "selected_agent_id": decision.selected_agent_id,
        "decision": decision.reason, "higher_is_better": higher_is_better,
        "interpretation": "Descriptive paired scores only; no confidence interval or RSI-level claim.",
    }
    if reasons:
        return report
    groups = defaultdict(list)
    split_of = {task.id: task.split.value for task in parent.tasks}
    for task_id, seed in sorted(expected):
        a, b = left[task_id, seed], right[task_id, seed]
        delta = (b.score - a.score) * (1 if higher_is_better else -1)
        pair = {"task_id": task_id, "seed": seed, "split": split_of[task_id],
                "parent_score": a.score, "candidate_score": b.score, "gain": delta,
                "parent_status": a.status, "candidate_status": b.status}
        report["pairs"].append(pair)
        groups[split_of[task_id]].append(pair)
    for split, pairs in sorted(groups.items()):
        report["splits"][split] = {
            "pairs": len(pairs), "mean_gain": sum(x["gain"] for x in pairs) / len(pairs),
            "wins": sum(x["gain"] > 0 for x in pairs), "losses": sum(x["gain"] < 0 for x in pairs),
            "ties": sum(x["gain"] == 0 for x in pairs),
        }
    return report
