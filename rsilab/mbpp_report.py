"""Strict offline MBPP batch aggregation; never imports the study controller.

Call build_mbpp_comparison(study, baselines, evaluations, adapter_sha256=...) for
one trained adapter at a time. Supply the SHA256 of the exported adapter weights,
not the adapter path. Every baseline batch is required, even though only frozen
retention/dev rows enter the paired comparison. Task split `train` is preserved
in the framework manifests; `evaluation_splits.retention` labels its report role.
No code or provider job is executed. No promotion decision is made from gains.
"""
from __future__ import annotations

import json
import math
import re
from typing import Sequence

from .core import Agent, FrozenJSON, Manifest, Provenance, RunResult, Split, Task, canonical_json, digest
from .comparison import compare
from rsi.mbpp_verification import MBPP_VERIFIER_VERSION, _validate_task, score_mbpp_outputs
from rsi.verification import SANDBOX_TIMEOUT_SECONDS

BATCH_SIZE = 32  # Frozen mbpp-v1 controller contract, not a tunable report option.
REQUIRED_SOURCES = (
    "rsi/study.py", "rsi/modal_workers.py", "rsi/mbpp_workers.py",
    "rsi/verification.py", "rsi/mbpp_verification.py", "rsi/datasets.py",
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _study(study):
    payload = {key: value for key, value in study.items() if key != "sha256"}
    _require(study.get("sha256") == digest(payload), "Frozen study hash mismatch")
    protocol = study["protocol"]
    _require(study["analysis_plan_sha256"] == digest(protocol), "Protocol hash mismatch")
    _require(study["study"] == protocol["study"] == "mbpp-v1", "Unsupported study")
    tasks = study["tasks"]
    _require(bool(tasks) and len({task["id"] for task in tasks}) == len(tasks), "Duplicate/empty study tasks")
    _require(all(task["split"] in {"train", "dev"} for task in tasks), "Unexpected study split")
    train = [task for task in tasks if task["split"] == "train"]
    dev = [task for task in tasks if task["split"] == "dev"]
    _require(len(train) == protocol["sizes"]["train_pool"] and len(dev) == protocol["sizes"]["development"],
             "Study task counts differ from protocol")
    _require(tasks == train + dev, "Study must retain frozen train-then-dev order")
    retention = study["retention_ids"]
    _require(retention == [task["id"] for task in train][:protocol["sizes"]["training_retention"]]
             and len(retention) == protocol["sizes"]["training_retention"], "Invalid retention IDs/order")
    settings = study["generation_settings"]
    _require(settings == {key: protocol["generation"][key] for key in ("seed", "temperature", "max_new_tokens")},
             "Study generation settings differ from protocol")
    _require(protocol["generation"]["attempts_per_task"] == 1, "Only single-attempt MBPP supported")
    for task in tasks:
        _validate_task(task, SANDBOX_TIMEOUT_SECONDS)
    return [task for task in tasks if task["split"] == "dev" or task["id"] in retention]


def _collect(study, reports, stage, expected_tasks):
    _require(len(reports) == math.ceil(len(expected_tasks) / BATCH_SIZE), f"{stage}: missing/extra batches")
    batches = {}
    for report in reports:
        batch = report.get("batch")
        _require(type(batch) is int and batch not in batches, f"{stage}: invalid/duplicate batch")
        batches[batch] = report
    _require(set(batches) == set(range(len(reports))), f"{stage}: batch indices do not cover expected tasks")
    rows, controls, lineage, adapter_paths, training_ids = {}, [], [], set(), set()
    protocol = study["protocol"]
    for batch, report in sorted(batches.items()):
        _require(report.get("stage") == stage and report.get("status") == "completed", f"{stage}: incomplete/wrong stage")
        _require(isinstance(report.get("run_id"), str) and report["run_id"], f"{stage}: missing run ID")
        _require(report.get("study_sha256") == study["sha256"], f"{stage}: study hash mismatch")
        _require(report.get("generation_settings") == study["generation_settings"], f"{stage}: decoding settings mismatch")
        expected = expected_tasks[batch * BATCH_SIZE:(batch + 1) * BATCH_SIZE]
        _require(report.get("task_hash") == digest(expected), f"{stage}: batch task hash mismatch")
        records = report["records"]
        _require([row["task"] for row in records] == expected, f"{stage}: task content/order mismatch")
        generation = report["generation"]
        outputs = generation["outputs"]
        _require(generation.get("status") == "completed", f"{stage}: incomplete generation")
        _require([output["id"] for output in outputs] == [task["id"] for task in expected], f"{stage}: output order mismatch")
        _require(generation.get("gpu_name") == protocol["main_hardware"], f"{stage}: actual hardware differs from protocol")
        _require(generation.get("model_id") == protocol["model_id"] and generation.get("revision") == protocol["model_revision"],
                 f"{stage}: model identity mismatch")
        for key in ("seed", "temperature", "max_new_tokens"):
            _require(generation.get(key) == protocol["generation"][key], f"{stage}: actual {key} mismatch")
        _require(generation.get("enable_thinking") is protocol["generation"]["thinking"], f"{stage}: thinking mismatch")
        if "max_input_tokens" in generation:
            _require(generation["max_input_tokens"] == protocol["generation"]["max_input_tokens"], f"{stage}: input budget mismatch")
        sources = report["provenance"]["source_hashes"]
        _require(all(path in sources for path in REQUIRED_SOURCES) and all(_sha(value) for value in sources.values()),
                 f"{stage}: missing/invalid source hashes")
        _require(report["provenance"]["model"] == {"model_id": protocol["model_id"], "revision": protocol["model_revision"]},
                 f"{stage}: controller model identity mismatch")
        packages = generation.get("packages")
        _require(isinstance(packages, dict) and bool(packages) and all(isinstance(v, str) and v for v in packages.values()),
                 f"{stage}: missing/invalid package inventory")
        controls.append({"sources": sources, "hardware": generation["gpu_name"], "packages": packages,
                         "cuda_version": generation.get("cuda_version")})
        _require(controls[-1]["cuda_version"], f"{stage}: missing CUDA version")
        adapter = generation.get("adapter_path")
        if stage == "mbpp-baseline":
            _require(adapter is None and report.get("training_run") is None, "Baseline unexpectedly uses an adapter")
        else:
            _require(isinstance(adapter, str) and adapter and isinstance(report.get("training_run"), str)
                     and report["training_run"], "Candidate adapter/training identity missing")
            adapter_paths.add(adapter)
            training_ids.add(report["training_run"])
        for index, (record, output) in enumerate(zip(records, outputs)):
            _require(record["generation"] == output, f"{stage}: per-record generation mismatch")
            _require(output.get("hit_time_limit") is False and type(output.get("hit_token_limit")) is bool,
                     f"{stage}: incomplete/missing output limit flags")
            _require(type(output.get("output_tokens")) is int and 0 <= output["output_tokens"] <= protocol["generation"]["max_new_tokens"],
                     f"{stage}: invalid output token count")
            _require(type(output.get("input_tokens")) is int and 0 < output["input_tokens"] <= protocol["generation"]["max_input_tokens"],
                     f"{stage}: invalid input token count")
            verification = record["verification"]
            if output["hit_token_limit"]:
                # The controller rejects truncation before sandbox execution;
                # this explicit policy outcome legitimately has no verifier ID.
                _require(verification.get("passed") is False and verification.get("error_kind") == "generation_limit"
                         and "generation_token_limit" in verification.get("errors", []),
                         f"{stage}: truncated output must have a generation-limit failure record")
            else:
                _require(verification.get("verifier_version") == MBPP_VERIFIER_VERSION, f"{stage}: verifier version mismatch")
            _require(not verification.get("infrastructure_error") and verification.get("error_kind") not in {"infrastructure", "invalid_task"},
                     f"{stage}: infrastructure/task failure")
            scored = score_mbpp_outputs(verification.get("outputs"), record["task"]["cases"])
            value = int(scored["passed"] and not output["hit_token_limit"])
            _require(verification.get("passed") is bool(value), f"{stage}: recorded outcome differs from trusted protocol scoring")
            task_id = record["task"]["id"]
            rows[task_id] = {"record": record, "score": value, "source_run_id": report["run_id"],
                             "effective_seed": study["generation_settings"]["seed"] + index}
        lineage.append({"run_id": report["run_id"], "report_sha256": digest(report), "batch": batch,
                        "task_hash": report["task_hash"]})
    _require(len({row["run_id"] for row in lineage}) == len(lineage), f"{stage}: duplicate run IDs")
    _require(all(control == controls[0] for control in controls), f"{stage}: source/hardware/package/CUDA drift between batches")
    if stage == "mbpp-evaluate":
        _require(len(adapter_paths) == len(training_ids) == 1, "Evaluation mixes trained adapters")
    return rows, controls[0], lineage, next(iter(training_ids), None), next(iter(adapter_paths), None)


def build_mbpp_comparison(study: dict, baseline_reports: Sequence[dict], evaluation_reports: Sequence[dict], *,
                          adapter_sha256: str, training_report: dict | None = None) -> dict:
    """Build immutable framework manifests and re-scored paired data for one adapter.

    Malformed/incomplete evidence raises ValueError; valid reports with different
    parent/candidate controls produce compare().matched=False, never a promotion.
    The caller supplies the real adapter-weights digest after export verification.
    Optional training_report links the declared training seed and adapter path.
    """
    _require(_sha(adapter_sha256), "Supply the actual exported adapter SHA256")
    selected = _study(study)
    left, parent_control, baseline_lineage, _, _ = _collect(study, baseline_reports, "mbpp-baseline", study["tasks"])
    right, candidate_control, evaluation_lineage, training_id, adapter_path = _collect(study, evaluation_reports, "mbpp-evaluate", selected)
    _require(not ({r["run_id"] for r in baseline_lineage} & {r["run_id"] for r in evaluation_lineage}), "Run IDs overlap between arms")
    for task in selected:
        _require(left[task["id"]]["effective_seed"] == right[task["id"]]["effective_seed"], "Per-task sampling seeds do not match after rebatching")
    training_seed = None
    if training_report is not None:
        _require(training_report.get("run_id") == training_id and training_report.get("stage") == "mbpp-train"
                 and training_report.get("status") == "completed" and training_report.get("study_sha256") == study["sha256"],
                 "Training report lineage mismatch")
        _require(training_report["training"]["status"] == "completed" and training_report["training"]["adapter_path"] == adapter_path,
                 "Training adapter mismatch")
        training_seed = training_report["seed"]
        _require(type(training_seed) is int and training_seed in study["protocol"]["training"]["seeds"], "Undeclared training seed")
    tasks = tuple(Task(task["id"], task["family"], Split(task["split"]), task["prompt"], FrozenJSON(task)) for task in selected)
    seed = study["generation_settings"]["seed"]
    manifests, result_sets = [], []
    for label, rows, control, lineage, adapter in (
        ("parent", left, parent_control, baseline_lineage, None),
        ("candidate", right, candidate_control, evaluation_lineage, adapter_sha256),
    ):
        agent = Agent("mbpp-parent" if label == "parent" else training_id, study["protocol"]["model_id"],
                      study["protocol"]["model_revision"],
                      digest({path: control["sources"][path] for path in ("rsi/modal_workers.py", "rsi/mbpp_workers.py")}),
                      digest({"memory": None}), adapter)
        provenance = Provenance(digest(control["sources"]), digest(selected),
                                digest({path: control["sources"][path] for path in ("rsi/verification.py", "rsi/mbpp_verification.py")}),
                                study["analysis_plan_sha256"], FrozenJSON(control["packages"]), control["hardware"])
        manifest = Manifest(f"mbpp-{label}-{digest(lineage)[:16]}", agent, tasks, (seed,),
                            FrozenJSON({key: study["protocol"]["generation"][key] for key in
                                        ("max_new_tokens", "max_input_tokens", "attempts_per_task")}),
                            FrozenJSON({**study["generation_settings"], "thinking": study["protocol"]["generation"]["thinking"],
                                        "quantization": study["protocol"]["quantization"], "cuda_version": control["cuda_version"]}), provenance)
        results = []
        for task in selected:
            item = rows[task["id"]]
            output = item["record"]["generation"]
            results.append(RunResult(manifest.run_id, agent.id, task["id"], seed,
                                     "completed" if item["score"] else "failed", FrozenJSON(item), item["score"],
                                     output["input_tokens"] + output["output_tokens"], output["elapsed_seconds"]))
        manifests.append(manifest)
        result_sets.append(results)
    comparison = compare(manifests[0], manifests[1], result_sets[0], result_sets[1])
    summary = {}
    if comparison["matched"]:
        for split, role in (("dev", "dev"), ("train", "retention")):
            pairs = [pair for pair in comparison["pairs"] if pair["split"] == split]
            summary[role] = {"total": len(pairs), "parent_passed": sum(p["parent_score"] for p in pairs),
                             "candidate_passed": sum(p["candidate_score"] for p in pairs),
                             "net_success_gain": sum(p["gain"] for p in pairs),
                             "lost_parent_successes": sum(p["parent_score"] == 1 and p["candidate_score"] == 0 for p in pairs)}
    return json.loads(canonical_json({
        "schema_version": 1, "study_sha256": study["sha256"], "analysis_plan_sha256": study["analysis_plan_sha256"],
        "parent_manifest": manifests[0].to_dict(), "candidate_manifest": manifests[1].to_dict(),
        "parent_results": result_sets[0], "candidate_results": result_sets[1], "comparison": comparison,
        "evaluation_splits": summary, "baseline_lineage": baseline_lineage, "evaluation_lineage": evaluation_lineage,
        "training_run_id": training_id, "training_seed": training_seed,
        "training_report_sha256": digest(training_report) if training_report is not None else None,
        "adapter_path": adapter_path, "adapter_sha256": adapter_sha256, "promoted": False,
        "limitations": ["One adapter per report; both predeclared training seeds must be reviewed separately.",
                        "Retention is a preselected training subset, not a held-out split.",
                        "No confidence interval, population-level improvement, or RSI claim.",
                        "Adapter digest is caller-attested; verify exported bytes before invoking this helper."]}))
