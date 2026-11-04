"""Aggregate the frozen two-seed MBPP study offline; never launch or promote.

Run from the checkout: .venv/bin/python scripts/report_mbpp.py [--check-only]
All inputs must already be complete, and both adapter weights must be exported.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
# Prefer this checkout over an older wheel installed in the project environment.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rsilab import canonical_json, digest
from rsilab.cli import _load
from rsilab.mbpp_report import build_mbpp_comparison, _collect, _study
from rsi.verification import extract_code

DECISION_TEXT = (
    "No automatic promotion. Only mark replication-worthy if both seeds gain at least 4 net development successes, "
    "neither loses more than 1 parent retention success, and no unresolved integrity mismatch exists. "
    "These are prospective pilot engineering gates, not proof of population-level generalization or RSI."
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def counts(records):
    by_split, by_category = defaultdict(list), defaultdict(list)
    for row in records:
        split = row["task"]["split"]
        by_split[split].append(row)
        by_category[(split, row["task"]["category"])].append(row)

    def summarize(rows):
        return {"total": len(rows), "passed": sum(row["verification"]["passed"] for row in rows),
                "truncated": sum(row["generation"]["hit_token_limit"] for row in rows)}

    return {"by_split": {split: summarize(rows) for split, rows in sorted(by_split.items())},
            "by_split_category": {split: {category: summarize(rows)
                for (s, category), rows in sorted(by_category.items()) if s == split}
                for split in sorted(by_split)},
            "truncated_total": sum(row["generation"]["hit_token_limit"] for row in records)}


def build_reports(root: Path = ROOT) -> dict[str, dict]:
    """Read and validate everything before returning any publishable payload."""
    root = Path(root).resolve()
    study = _load(root / "data/mbpp/study-v1.json")
    _study(study)
    protocol = study["protocol"]
    require(protocol["training"]["seeds"] == [42, 43] and protocol["training"]["fresh_adapters"] == 2,
            "Expected the two predeclared training seeds, 42 and 43")
    require(protocol["decision"] == DECISION_TEXT, "Decision protocol changed; do not reinterpret thresholds")
    require(protocol["sizes"] == {"train_pool": 128, "development": 48, "training_retention": 32},
            "Expected the frozen 128/48/32 study sizes")
    reports = []
    for path in sorted((root / "runs").glob("*/report.json")):
        report = _load(path)
        if report.get("study_sha256") != study["sha256"]:
            continue
        require(report.get("run_id") == path.parent.name, "Report run ID does not match its directory")
        if report.get("stage") in {"mbpp-baseline", "mbpp-train", "mbpp-evaluate"}:
            reports.append(report)
    # Failed attempts remain visible as lineage, but are never substituted for a
    # missing completed batch. Active relevant runs make this a premature report.
    active = [r["run_id"] for r in reports if r.get("status") not in {"completed", "failed", "interrupted"}]
    require(not active, f"Study has unfinished reports: {active}")
    complete = [r for r in reports if r.get("status") == "completed"]
    baseline = sorted((r for r in complete if r["stage"] == "mbpp-baseline"), key=lambda r: r["batch"])
    _collect(study, baseline, "mbpp-baseline", study["tasks"])
    records = [row for report in baseline for row in report["records"]]
    passing = [row for row in records if row["task"]["split"] == "train" and row["verification"]["passed"]]
    unique = {}
    for row in passing:
        code = row["verified_code"]
        require(code == extract_code(row["generation"]["text"]), "Verified target differs from generated code")
        unique.setdefault(digest(code), row)
    selected = list(unique.values())
    selected_ids = [row["task"]["id"] for row in selected]
    categories = dict(Counter(row["task"]["category"] for row in selected))
    gate = protocol["training_gate"]
    require(len(selected) >= gate["minimum_unique_targets"] and len(categories) >= gate["minimum_descriptive_categories"]
            and max(categories.values(), default=0) / max(1, len(selected)) <= gate["maximum_category_fraction"],
            "Frozen verified-data diversity gate did not pass")
    examples = [{"prompt": row["task"]["prompt"], "completion": row["verified_code"], "verified": True} for row in selected]
    trainings = [r for r in complete if r["stage"] == "mbpp-train"]
    require(len(trainings) == 2, f"Expected exactly two completed training runs; found {len(trainings)}")
    require(all(type(r.get("seed")) is int for r in trainings) and {r["seed"] for r in trainings} == {42, 43},
            "Missing, duplicate, or undeclared completed training seed")
    evaluations = [r for r in complete if r["stage"] == "mbpp-evaluate"]
    require(all(r.get("training_run") in {t["run_id"] for t in trainings} for r in evaluations),
            "Evaluation references an unselected training run")
    payloads, per_seed = {}, {}
    for training in sorted(trainings, key=lambda r: r["seed"]):
        seed, run_id = training["seed"], training["run_id"]
        require(training["baseline_runs"] == [r["run_id"] for r in baseline], "Training used different baseline runs")
        require(training["selected_ids"] == selected_ids and training["dataset_hash"] == digest(examples),
                "Training target lineage differs from the frozen verified selection")
        require(training["examples_count"] == len(selected) and training["categories"] == categories,
                "Training selected-yield metadata mismatch")
        state = training["training"]
        expected_steps = math.ceil(2 * len(selected) / protocol["training"]["gradient_accumulation"])
        require(state["steps_completed"] == state["max_steps"] == expected_steps
                and expected_steps <= protocol["training"]["maximum_steps"], "Training step target mismatch")
        require(state["seed"] == seed and state["examples_count"] == len(selected), "Training worker identity mismatch")
        for key in ("learning_rate", "gradient_accumulation", "max_length", "lora_rank"):
            require(state[key] == protocol["training"][key], f"Training {key} differs from protocol")
        require(state["model_id"] == protocol["model_id"] and state["revision"] == protocol["model_revision"]
                and state["quantization"] == protocol["quantization"], "Training model/quantization mismatch")
        require(state["gpu_name"] == protocol["main_hardware"], "Training hardware differs from protocol")
        require(training["provenance"]["source_hashes"] == baseline[0]["provenance"]["source_hashes"],
                "Training source inventory differs from the frozen baseline")
        require(state["packages"] == baseline[0]["generation"]["packages"]
                and state["cuda_version"] == baseline[0]["generation"]["cuda_version"],
                "Training package/CUDA inventory differs from baseline")
        adapter = (root / "artifacts/mbpp" / run_id / "adapter/adapter_model.safetensors").resolve()
        require(adapter.is_relative_to(root) and adapter.is_file(), f"Missing SSD adapter export for {run_id}")
        require(adapter.stat().st_size > 0, f"Empty adapter export for {run_id}")
        with adapter.open("rb") as stream:
            adapter_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        candidate = [r for r in evaluations if r["training_run"] == run_id]
        result = build_mbpp_comparison(study, baseline, candidate, adapter_sha256=adapter_hash, training_report=training)
        matched = result["comparison"]["matched"]
        split_scores = result["evaluation_splits"]
        dev_gain = split_scores["dev"]["net_success_gain"] if matched else None
        retention_loss = split_scores["retention"]["lost_parent_successes"] if matched else None
        threshold_met = matched and dev_gain >= 4 and retention_loss <= 1
        per_seed[str(seed)] = {"training_run_id": run_id, "matched_controls": matched,
                              "integrity_reasons": result["comparison"]["reasons"], "scores": split_scores,
                              "net_development_gain": dev_gain, "lost_parent_retention_successes": retention_loss,
                              "threshold_met": threshold_met, "adapter_sha256": adapter_hash,
                              "evaluation_counts": counts([row for report in candidate for row in report["records"]])}
        payloads[f"seed-{seed}-comparison.json"] = result
        payloads[f"seed-{seed}-parent-manifest.json"] = result["parent_manifest"]
        payloads[f"seed-{seed}-candidate-manifest.json"] = result["candidate_manifest"]
    replication_worthy = all(row["threshold_met"] for row in per_seed.values())
    payloads["summary.json"] = {
        "schema_version": 1, "study_sha256": study["sha256"], "analysis_plan_sha256": study["analysis_plan_sha256"],
        "baseline": counts(records), "selected_yield": {
            "verified_train_successes": len(passing), "unique_targets": len(selected), "train_tasks": 128,
            "unique_target_fraction": len(selected) / 128, "duplicates_removed": len(passing) - len(selected),
            "categories": categories, "diversity_gate_passed": True, "dataset_sha256": digest(examples)},
        "seeds": per_seed, "replication_worthy": replication_worthy, "promoted": False,
        "decision": "replication_worthy" if replication_worthy else "not_replication_worthy",
        "decision_rule": {"seeds": [42, 43], "minimum_net_development_gain_each": 4,
                          "maximum_lost_parent_retention_successes_each": 1, "matched_controls_required": True},
        "decision_protocol": protocol["decision"], "selected_agent": "original_parent",
        "failed_or_interrupted_attempts": [{"run_id": r["run_id"], "stage": r["stage"], "status": r["status"],
                                            "report_sha256": digest(r)} for r in reports if r["status"] != "completed"],
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limitations": ["Two seeds share one generated training dataset.",
                        "Retention is training data, not held-out evaluation.",
                        "Replication-worthy is a prospective engineering flag, not promotion or an RSI claim.",
                        "Exported adapter digests are measured locally; main must verify their remote lineage."]}
    return payloads


def write_reports(root: Path, payloads: dict[str, dict]) -> Path:
    """Publish only after full validation; identical reruns are idempotent."""
    root = Path(root).resolve()
    target = root / "artifacts/mbpp/reports"
    require(target.resolve().is_relative_to(root), "Report destination escapes the checkout")
    encoded = {name: (canonical_json(value) + "\n").encode() for name, value in payloads.items()}
    inventory = {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name, data in encoded.items()}
    encoded["inventory.json"] = (canonical_json({"files": inventory}) + "\n").encode()
    if target.exists():
        require(target.is_dir() and {p.name for p in target.iterdir()} == set(encoded)
                and all((target / name).read_bytes() == data for name, data in encoded.items()),
                "Existing reports differ; preserve them and resolve the discrepancy before rewriting")
        return target
    (root / "work").mkdir(exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mbpp-report-", dir=root / "work") as temporary:
        staged = Path(temporary) / "reports"
        staged.mkdir()
        for name, data in encoded.items():
            (staged / name).write_bytes(data)
        staged.rename(target)
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="Validate complete inputs without writing reports")
    args = parser.parse_args(argv)
    try:
        payloads = build_reports(ROOT)
        summary = payloads["summary.json"]
        path = None if args.check_only else str(write_reports(ROOT, payloads))
        print(json.dumps({"path": path, "replication_worthy": summary["replication_worthy"], "promoted": False,
                          "seeds": summary["seeds"]}, indent=2))
        return 0 if all(seed["matched_controls"] for seed in summary["seeds"].values()) else 2
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(f"report_mbpp: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
