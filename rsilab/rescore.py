"""Offline lineage audit for post-hoc MBPP evaluator corrections.

This module does not import an evaluator implementation, execute candidate code,
or change historical reports. It checks recorded verification envelopes and
binds them to immutable original inputs and one declared evaluator/source map.
The controller must validate the new evaluator and its reference audit first.
"""
from __future__ import annotations

import math
import re
from typing import Sequence

from .core import canonical_json, digest

BATCH_SIZE = 32
SOURCE_STAGES = {"mbpp-baseline", "mbpp-evaluate", "mbpp-kaggle-verify"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _same(left, right):
    # Python equality treats True == 1 and 0 == 0.0; immutable JSON evidence does not.
    return canonical_json(left) == canonical_json(right)


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _hashes(value, label):
    _require(isinstance(value, dict) and value and all(isinstance(k, str) and k and _sha(v) for k, v in value.items()),
             f"Invalid {label} source digest map")


def _verification(value, total, label, *, version=None, truncated=False):
    _require(isinstance(value, dict) and type(value.get("passed")) is bool, f"{label}: missing boolean outcome")
    _require(not value.get("infrastructure_error") and value.get("error_kind") not in {"infrastructure", "invalid_task"},
             f"{label}: infrastructure/task failure")
    _require(type(value.get("count")) is int and type(value.get("total")) is int
             and value["total"] == total and 0 <= value["count"] <= total, f"{label}: invalid case counts")
    _require(value["passed"] == (value["count"] == total), f"{label}: contradictory outcome/count")
    _require(isinstance(value.get("errors"), list) and all(isinstance(x, str) for x in value["errors"]),
             f"{label}: invalid error evidence")
    if truncated:
        _require(value["passed"] is False and value["count"] == 0 and value.get("error_kind") == "generation_limit"
                 and "generation_token_limit" in value["errors"] and value.get("sandbox_id") is None,
                 f"{label}: token-limit failure must be preserved without execution")
    else:
        _require(isinstance(value.get("verifier_version"), str) and value["verifier_version"], f"{label}: missing evaluator version")
        if version is not None:
            _require(value["verifier_version"] == version, f"{label}: evaluator version mismatch")
    _require(not value["passed"] or not value["errors"], f"{label}: passing result carries errors")


def _stats(rows):
    return {"total": len(rows), "v1_passed": sum(r["v1_passed"] for r in rows),
            "v2_passed": sum(r["v2_passed"] for r in rows),
            "net_score_change": sum(int(r["v2_passed"]) - int(r["v1_passed"]) for r in rows),
            "changes": {key: sum(r["change"] == key for r in rows) for key in
                        ("fail_to_pass", "pass_to_fail", "unchanged_pass", "unchanged_fail")},
            "preserved_token_limit_failures": sum(r["token_limit_preserved"] for r in rows)}


def _summary(rows):
    return {**_stats(rows), "by_split": {split: _stats([r for r in rows if r["split"] == split])
                                        for split in sorted({r["split"] for r in rows})}}


def audit_rescores(study: dict, original_reports: Sequence[dict], logical_rescores: Sequence[dict], *,
                   training_reports: Sequence[dict], rescore_protocol_sha256: str) -> dict:
    """Audit all 368 saved outcomes under one new evaluator, without rescoring code.

    original_reports: 6 baseline + 3 evaluation per training seed + 1 Kaggle.
    logical_rescores: flatten completed grouped stage reports' `rescores` lists.
    source_report_sha256 must be rsilab.digest(original_report), not file bytes.
    The caller independently verifies the rescore plan digest and reference gate.
    Missing, duplicate, altered, incomplete, or inconsistent evidence raises.
    """
    _require(_sha(rescore_protocol_sha256), "Invalid expected rescore protocol digest")
    _require(study.get("sha256") == digest({k: v for k, v in study.items() if k != "sha256"}), "Frozen study hash mismatch")
    protocol = study["protocol"]
    _require(study["analysis_plan_sha256"] == digest(protocol), "Original protocol digest mismatch")
    _require(study["study"] == protocol["study"] == "mbpp-v1", "Unsupported study")
    _require(_same(protocol["sizes"], {"train_pool": 128, "development": 48, "training_retention": 32}), "Unexpected study sizes")
    tasks = study["tasks"]
    train = [task for task in tasks if task["split"] == "train"]
    dev = [task for task in tasks if task["split"] == "dev"]
    _require(len(train) == 128 and len(dev) == 48 and len(tasks) == len({t["id"] for t in tasks}) == 176
             and _same(tasks, train + dev), "Study task identity/order mismatch")
    retention = study["retention_ids"]
    _require(retention == [task["id"] for task in train[:32]], "Retention IDs/order mismatch")
    paired_tasks = [task for task in tasks if task["split"] == "dev" or task["id"] in retention]
    model = {"model_id": protocol["model_id"], "revision": protocol["model_revision"]}
    settings = {k: protocol["generation"][k] for k in ("seed", "temperature", "max_new_tokens")}
    _require(_same(study["generation_settings"], settings), "Frozen generation settings mismatch")
    _require(_same(protocol["training"]["seeds"], [42, 43]) and len(training_reports) == 2,
             "Require exactly the two predeclared training reports")
    training_by_id = {}
    for report in training_reports:
        _require(report.get("status") == "completed" and report.get("stage") == "mbpp-train"
                 and report.get("study_sha256") == study["sha256"], "Incomplete/wrong-study training report")
        _require(type(report.get("seed")) is int and report["seed"] in (42, 43), "Undeclared training seed")
        _require(isinstance(report.get("run_id"), str) and report["run_id"] and report["run_id"] not in training_by_id,
                 "Duplicate/invalid training run ID")
        _require(report["training"]["status"] == "completed" and _same(report["provenance"]["model"], model),
                 "Training model/status mismatch")
        training_by_id[report["run_id"]] = report
    _require({report["seed"] for report in training_reports} == {42, 43}, "Duplicate/missing training seed")
    originals, grouped = {}, {"parent": [], "seed-42": [], "seed-43": [], "kaggle": []}
    for report in original_reports:
        _require(report.get("stage") in SOURCE_STAGES and report.get("status") == "completed"
                 and report.get("study_sha256") == study["sha256"], "Original report incomplete or outside study")
        run_id = report.get("run_id")
        _require(isinstance(run_id, str) and run_id and run_id not in originals, "Duplicate/invalid source run ID")
        if report["stage"] == "mbpp-baseline":
            arm = "parent"
        elif report["stage"] == "mbpp-kaggle-verify":
            arm = "kaggle"
        else:
            _require(report.get("training_run") in training_by_id, "Candidate training identity missing")
            arm = f"seed-{training_by_id[report['training_run']]['seed']}"
        originals[run_id] = report
        grouped[arm].append(report)
    expected_by_arm = {"parent": tasks, "seed-42": paired_tasks, "seed-43": paired_tasks, "kaggle": dev[:32]}
    original_rows, controls, offsets = {}, [], {}
    for arm, reports in grouped.items():
        expected = expected_by_arm[arm]
        required_count = 1 if arm == "kaggle" else math.ceil(len(expected) / BATCH_SIZE)
        _require(len(reports) == required_count, f"{arm}: missing/extra original batches")
        if arm != "kaggle":
            _require(all(type(r.get("batch")) is int for r in reports)
                     and sorted(r["batch"] for r in reports) == list(range(required_count)), f"{arm}: duplicate/invalid batch indices")
            reports.sort(key=lambda r: r["batch"])
        for batch, report in enumerate(reports):
            part = expected if arm == "kaggle" else expected[batch*BATCH_SIZE:(batch+1)*BATCH_SIZE]
            records, generation = report["records"], report["generation"]
            _require(_same([row["task"] for row in records], part), f"{arm}: original task/order changed")
            _require(generation.get("status") == "completed" and _same([row["generation"] for row in records], generation["outputs"]),
                     f"{arm}: original generation coverage mismatch")
            _require([output["id"] for output in generation["outputs"]] == [task["id"] for task in part], f"{arm}: output IDs/order mismatch")
            _require(_same(report["provenance"]["model"], model), f"{arm}: original model provenance mismatch")
            _hashes(report["provenance"]["source_hashes"], "original")
            if arm == "kaggle":
                request = generation["request"]
                _require(request.get("manifest_hash") == study["sha256"]
                         and _same({k: request[k] for k in model}, model)
                         and request["seed"] == settings["seed"] and request["max_new_tokens"] == settings["max_new_tokens"]
                         and _same(request["prompts"], [{"id": task["id"], "prompt": task["prompt"]} for task in part]),
                         "Kaggle original request does not match frozen tasks/model")
            else:
                _require(report.get("task_hash") == digest(part) and _same(report["generation_settings"], settings),
                         f"{arm}: original task/settings hash mismatch")
                _require(_same({k: generation[k] for k in model}, model)
                         and _same({k: generation[k] for k in settings}, settings)
                         and generation["enable_thinking"] is protocol["generation"]["thinking"], f"{arm}: original actual model/settings mismatch")
                _require(generation["gpu_name"] == protocol["main_hardware"], f"{arm}: original hardware mismatch")
                control = {"source_hashes": report["provenance"]["source_hashes"], "hardware": generation["gpu_name"],
                           "packages": generation["packages"], "cuda_version": generation["cuda_version"]}
                _require(bool(control["packages"]) and bool(control["cuda_version"]), "Missing original runtime provenance")
                controls.append(control)
                if arm == "parent":
                    _require(generation.get("adapter_path") is None and report.get("training_run") is None, "Parent uses an adapter")
                else:
                    _require(generation["adapter_path"] == training_by_id[report["training_run"]]["training"]["adapter_path"],
                             "Saved candidate adapter differs from training report")
            for index, record in enumerate(records):
                task, output = record["task"], record["generation"]
                _require(isinstance(output.get("text"), str) and output.get("hit_time_limit") is False
                         and type(output.get("hit_token_limit")) is bool, "Original generation incomplete/invalid")
                _verification(record["verification"], len(task["cases"]), "original", truncated=output["hit_token_limit"])
                original_rows[(report["run_id"], task["id"])] = (arm, record)
                offsets[(arm, task["id"])] = settings["seed"] + index
    _require(all(_same(control, controls[0]) for control in controls), "Original Modal arms have unmatched source/runtime controls")
    for task in paired_tasks:
        _require(offsets[("parent", task["id"])] == offsets[("seed-42", task["id"])] == offsets[("seed-43", task["id"])],
                 "Original per-task seeds differ after rebatching")
    _require(len(originals) == len(logical_rescores) == 13, "Require all 13 original and logical rescore reports")
    by_source = {}
    for rescore in logical_rescores:
        source_id = rescore.get("source_run_id")
        _require(source_id in originals and source_id not in by_source, "Unknown/duplicate rescore source")
        by_source[source_id] = rescore
    _require(set(by_source) == set(originals), "Missing rescore source")
    rows, lineage, evaluator_identity = [], [], None
    for source_id, original in originals.items():
        rescore = by_source[source_id]
        _require(rescore.get("stage") == "mbpp-rescore-v2" and rescore.get("status") == "completed", "Incomplete/wrong rescore stage")
        _require(rescore.get("study_sha256") == study["sha256"] and rescore.get("source_report_sha256") == digest(original),
                 "Rescore source/study digest mismatch")
        _require(rescore.get("rescore_protocol_sha256") == rescore_protocol_sha256, "Rescore protocol digest mismatch")
        version, sources = rescore.get("evaluator_version"), rescore.get("evaluator_source_hashes")
        _require(isinstance(version, str) and version.strip(), "Missing new evaluator version")
        _hashes(sources, "evaluator")
        _require({"rsi/verification.py", "rsi/mbpp_verification.py"}.issubset(sources), "New evaluator source map is incomplete")
        identity = {"version": version, "source_hashes": sources}
        if evaluator_identity is None:
            evaluator_identity = identity
        _require(_same(identity, evaluator_identity), "New evaluator/source drift across arms")
        for key in ("generation", "source_provenance"):
            if key in rescore:
                _require(_same(rescore[key], original["provenance" if key == "source_provenance" else key]),
                         f"Rescore {key} changed original model/generation evidence")
        if "provenance" in rescore and "model" in rescore["provenance"]:
            _require(_same(rescore["provenance"]["model"], original["provenance"]["model"]), "Rescore model provenance changed")
        _require(len(rescore["records"]) == len(original["records"]), "Rescore record count mismatch")
        for old, new in zip(original["records"], rescore["records"]):
            _require(_same(new["task"], old["task"]) and _same(new["generation"], old["generation"]),
                     "Rescore changed saved task/generation/order")
            _require(_same(new["original_verification"], old["verification"]), "Original verification was not preserved")
            task, output, verification = old["task"], old["generation"], new["verification"]
            truncated = output["hit_token_limit"]
            _verification(verification, len(task["cases"]), "rescore", version=version, truncated=truncated)
            if truncated:
                _require(_same(verification, old["verification"]), "Token-limit verification must remain unchanged")
            else:
                _require(version != old["verification"]["verifier_version"], "Rescore still uses the original evaluator version")
                _require(_same(verification.get("evaluator_source_hashes"), sources),
                         "Verification evaluator source inventory differs from logical report")
            before, after = old["verification"]["passed"], verification["passed"]
            change = ("unchanged_pass" if before else "unchanged_fail") if before == after else ("fail_to_pass" if after else "pass_to_fail")
            arm = original_rows[(source_id, task["id"])][0]
            rows.append({"arm": arm, "task_id": task["id"], "split": task["split"],
                         "role": "retention" if task["id"] in retention else task["split"],
                         "source_run_id": source_id, "task_sha256": digest(task), "generation_sha256": digest(output),
                         "original_record_sha256": digest(old), "v1_passed": before, "v2_passed": after,
                         "change": change, "token_limit_preserved": truncated,
                         "original_verification": old["verification"], "verification": verification})
        lineage.append({"source_run_id": source_id, "source_report_sha256": digest(original),
                        "rescore_record_sha256": digest(rescore), "generation_sha256": digest(original["generation"]),
                        "original_provenance_sha256": digest(original["provenance"])})
    _require(len(rows) == 368, "Expected all 368 outcomes")
    indexed = {(row["arm"], row["task_id"]): row for row in rows}
    _require(len(indexed) == 368, "Duplicate arm/task outcomes")
    paired = {}
    for seed in (42, 43):
        pairs = []
        for task in paired_tasks:
            parent, candidate = indexed[("parent", task["id"])], indexed[(f"seed-{seed}", task["id"])]
            pairs.append({"task_id": task["id"], "split": "retention" if task["id"] in retention else "dev",
                          **{f"{version}_{arm}_passed": row[f"{version}_passed"] for version in ("v1", "v2")
                             for arm, row in (("parent", parent), ("candidate", candidate))}})
        scores = {}
        for version in ("v1", "v2"):
            scores[version] = {}
            for split in ("dev", "retention"):
                selected = [row for row in pairs if row["split"] == split]
                a, b = f"{version}_parent_passed", f"{version}_candidate_passed"
                scores[version][split] = {"total": len(selected), "parent_passed": sum(row[a] for row in selected),
                                          "candidate_passed": sum(row[b] for row in selected),
                                          "net_success_gain": sum(int(row[b]) - int(row[a]) for row in selected),
                                          "lost_parent_successes": sum(row[a] and not row[b] for row in selected)}
        paired[str(seed)] = {"training_run_id": next(r["run_id"] for r in training_reports if r["seed"] == seed),
                             "matched_saved_generation_controls": True, "same_new_evaluator": True,
                             "pairs": pairs, "scores": scores}
    return {"schema_version": 1, "study_sha256": study["sha256"],
            "original_protocol_sha256": study["analysis_plan_sha256"], "rescore_protocol_sha256": rescore_protocol_sha256,
            "evaluator": evaluator_identity, "evaluator_sha256": digest(evaluator_identity),
            "lineage": lineage, "training_report_sha256": {str(r["seed"]): digest(r) for r in training_reports},
            "records": rows, "total_records": len(rows), "changes": _stats(rows),
            "parent_full": _summary([row for row in rows if row["arm"] == "parent"]),
            "adapters": {str(seed): _summary([row for row in rows if row["arm"] == f"seed-{seed}"]) for seed in (42, 43)},
            "paired": paired,
            "kaggle": {**_summary([row for row in rows if row["arm"] == "kaggle"]),
                       "matched_modal_arm": False, "interpretation": "Separate saved Kaggle benchmark; not pooled with Modal."},
            "promoted": False, "training_performed": False, "generation_performed": False,
            "interpretation": "Post-hoc evaluator correction on saved outputs; no new learning or RSI claim.",
            "audit_boundary": "Lineage/envelope audit only. Controller owns evaluator correctness, frozen rescore plan, reference gate, and grouped-stage completion."}
