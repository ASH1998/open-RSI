"""Offline, category-only derivation from complete saved reference evidence.

No filesystem, provider, model or reference-code execution. Callers establish
the provenance of pinned input hashes and retain the immutable source files.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib

from .core import digest
from .coding_data import audit_reference_task, build_probe_task, category
from .preflight import preflight_task_categories
from rsi.mbpp_verification_v2 import score_mbpp_outputs
from rsi.verification import extract_code

VERSION = "category-only-reference-reuse-v1"

# Fail closed on added generation/training/result fields, even empty ones.
_REPORT_FIELDS = frozenset({
    "run_id", "stage", "budget_reservation", "provenance", "started_at", "status",
    "wandb_url", "plan_sha256", "modal_app_id", "remote_calls", "portable_worker",
    "original_references", "original_references_execution", "reference_probes",
    "reference_probes_execution", "audits", "error_type", "runtime_errors",
    "wall_seconds", "budget",
})


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(value):
    return (type(value) is str and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def _same(left, right):
    # JSON identity distinguishes True from 1 and 1.0 from 1.
    return digest(left) == digest(right)


def _execution(report, key, ids):
    records, summary = report[key], report[key + "_execution"]
    _require(type(records) is list and type(summary) is dict,
             "Missing saved execution envelope")
    _require(set(summary) == {"records", "issues", "submitted_ids", "missing_ids",
                             "unpersisted_ids", "validated_ids", "succeeded"},
             "Unexpected execution summary fields")
    _require(summary["succeeded"] is True
             and all(summary[k] == [] for k in ("issues", "missing_ids", "unpersisted_ids"))
             and summary["submitted_ids"] == ids and summary["validated_ids"] == ids,
             "Reference execution incomplete or not durably validated")
    _require(_same(summary["records"], records) and len(records) == len(ids),
             "Saved execution records disagree or are incomplete")
    results = []
    for index, (record, task_id) in enumerate(zip(records, ids)):
        _require(type(record) is dict and set(record) == {
            "index", "item_id", "status", "result", "exception_type"},
            "Unexpected execution record fields")
        _require(type(record["index"]) is int and record["index"] == index
                 and record["item_id"] == task_id and record["status"] == "returned"
                 and record["exception_type"] is None and type(record["result"]) is dict,
                 "Reference execution identity/order/status mismatch")
        results.append(record["result"])
    return results


def _result(result, task, reference_sha, evaluator):
    _require(not result.get("infrastructure_error")
             and result.get("error_kind") not in {"infrastructure", "invalid_task",
                                                  "invalid_candidate", "candidate_policy"},
             "Reference execution infrastructure or task failure")
    _require(result.get("candidate_sha256") == reference_sha
             and result.get("source_tests_sha256") == task["source_tests_sha256"]
             and result.get("verifier_version") == "mbpp-typed-v2"
             and result.get("source_compiler_version") == "mbpp-typed-v1"
             and _same(result.get("evaluator_source_hashes"), evaluator)
             and type(result.get("sandbox_id")) is str and bool(result["sandbox_id"].strip()),
             "Reference/result/evaluator identity mismatch")
    _require(type(result.get("outputs")) is list
             and len(result["outputs"]) == len(task["cases"]),
             "Incomplete reference outputs")
    scored = score_mbpp_outputs(result["outputs"], task["cases"])
    _require(all(k in result and _same(result[k], v) for k, v in scored.items()),
             "Saved reference scoring differs from typed-output replay")


def reuse_reference_audits(*, prepared: dict, calibration_report: dict,
                          correction: dict, expected_correction_sha256: str,
                          expected_plan_sha256: str,
                          expected_evaluator_source_hashes: dict,
                          train_count: int, expected_category_counts: dict) -> dict:
    """Replay an entire saved audit pool and derive category-only task copies.

    ``prepared`` has ordered ``items`` (id, task, proposal, reference_code,
    reference_sha256, review) and ``inventory_sha256``. The calibration report
    contains complete ``verify_records`` envelopes for original_references and
    reference_probes, saved audits, and no GPU calls/results. ``correction`` is
    a sealed independently reviewed mapping with source-artifact canonical
    digests and preserved inventory/prepared/plan bindings. Caller-supplied
    expected hashes must come from trusted frozen evidence, not this function.

    All original audits must replay exactly and remain eligible. Only category
    changes in copies of their augmented tasks; metadata stays byte-equivalent
    as JSON, retaining old review/audit bindings. Separate lineage explains the
    transformation. The ordered prefix must match expected_category_counts.
    Inputs are never mutated. Malformed/inconsistent evidence raises ValueError.
    A sealed manifest is an integrity record, not authentication or a launch.
    """
    try:
        return _reuse(prepared, calibration_report, correction,
                      expected_correction_sha256, expected_plan_sha256,
                      expected_evaluator_source_hashes, train_count, expected_category_counts)
    except (KeyError, TypeError, IndexError, AttributeError, SyntaxError) as exc:
        raise ValueError("Malformed reference reuse evidence") from exc


def reuse_reference_categories(*, prepared: dict, report: dict, correction: dict,
                               evaluator_source_hashes: dict, first_n: int = 20,
                               min_categories: int = 3) -> dict:
    """Controller convenience API; caller independently pins correction sources.

    Unlike reuse_reference_audits, expected identities come from ``correction``.
    Before calling, authenticate/pin that proposal and verify its source file
    hashes, old plan seal and replay implementation hashes. The returned sealed
    dict uses ``tasks`` for the complete pool and ``selected_tasks`` for its
    declared prefix. No input is written, and no new execution occurs.
    """
    try:
        _require(type(first_n) is int and type(min_categories) is int
                 and 1 <= min_categories <= first_n, "Invalid category prefix requirements")
        counts = {}
        for row in correction["items"][:first_n]:
            label = row["independently_reviewed_category"]
            counts[label] = counts.get(label, 0) + 1
        _require(len(counts) >= min_categories, "Reviewed prefix lacks required categories")
        declared = correction.get("counts", {}).get(f"first{first_n}_reviewed")
        _require(declared is None or _same(declared, counts),
                 "Correction prefix summary differs from explicit review map")
        manifest = reuse_reference_audits(prepared=prepared, calibration_report=report,
            correction=correction, expected_correction_sha256=correction["sha256"],
            expected_plan_sha256=correction["preserved_bindings"]["plan_sha256"],
            expected_evaluator_source_hashes=evaluator_source_hashes,
            train_count=first_n, expected_category_counts=counts)
        manifest.pop("sha256")
        manifest["tasks"] = manifest.pop("audited_pool")
        manifest["selected_tasks"] = manifest.pop("train")
        manifest["requested_min_categories"] = min_categories
        return {**manifest, "sha256": digest(manifest)}
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError("Malformed category correction evidence") from exc


def _reuse(prepared, report, correction, correction_sha, plan_sha, evaluator,
           train_count, expected_counts):
    _require(all(type(x) is dict for x in (prepared, report, correction, evaluator, expected_counts)),
             "Reference reuse requires dictionary inputs")
    _require(_sha(correction_sha) and _sha(plan_sha), "Invalid pinned identity")
    _require(correction.get("sha256") == correction_sha
             == digest({k: v for k, v in correction.items() if k != "sha256"}),
             "Correction seal or expected identity mismatch")
    _require(correction.get("schema_version") == 1
             and correction.get("status") == "future_protocol_input_only"
             and type(correction.get("reviewer")) is str and correction["reviewer"].strip(),
             "Missing independent category review")
    _require(evaluator and all(type(k) is str and k and _sha(v) for k, v in evaluator.items()),
             "Invalid expected evaluator identities")
    _require(type(train_count) is int and train_count > 0 and expected_counts
             and all(type(k) is str and k and type(v) is int and v > 0
                     for k, v in expected_counts.items())
             and sum(expected_counts.values()) == train_count,
             "Invalid selected count/category expectations")
    sources, bindings = correction["source_artifacts"], correction["preserved_bindings"]
    _require(sources["prepared"]["canonical_json_sha256"] == digest(prepared)
             == bindings["prepared_sha256"]
             and sources["failed_calibration"]["canonical_json_sha256"] == digest(report),
             "Prepared data or calibration differs from reviewed source evidence")
    _require(_sha(prepared["inventory_sha256"])
             and bindings["inventory_sha256"] == prepared["inventory_sha256"]
             == bindings["domain_review_inventory_sha256"]
             and bindings["plan_sha256"] == plan_sha == report["plan_sha256"],
             "Frozen inventory/review/plan bindings disagree")
    _require(set(report) <= _REPORT_FIELDS and report.get("remote_calls") == [],
             "Unexpected report fields or GPU/model call evidence present")
    _require(report.get("status") == "failed" and report.get("error_type") == "ValueError"
             and report.get("runtime_errors") == [{"phase": "body", "error_type": "ValueError"}]
             and type(report.get("run_id")) is str and report["run_id"].strip(),
             "Expected preserved failed calibration report")
    items, changes, audits = prepared["items"], correction["items"], report["audits"]
    _require(all(type(x) is list for x in (items, changes, audits))
             and len(items) == len(changes) == len(audits) and len(items) >= train_count,
             "Audit/correction pool coverage mismatch")
    ids = [x["id"] for x in items]
    _require(all(type(x) is str and x for x in ids) and len(set(ids)) == len(ids)
             and [x["task_id"] for x in changes] == ids
             and [x["task_id"] for x in audits] == ids,
             "Duplicate/missing/reordered audit or correction tasks")
    originals = _execution(report, "original_references", ids)
    probes = _execution(report, "reference_probes", ids)
    pool, lineage, reviewed = [], [], {}
    for item, change, audit, original, probe_result in zip(items, changes, audits, originals, probes):
        task, proposal, review = item["task"], item["proposal"], item["review"]
        tid = item["id"]
        _require(task["id"] == tid and review.get("approved") is True,
                 "Task identity differs or reference review not approved")
        refsha = hashlib.sha256(extract_code(item["reference_code"]).encode()).hexdigest()
        _require(refsha == item["reference_sha256"] == review["reference_sha256"],
                 "Reference code identity differs")
        probe = build_probe_task(task, proposal, approved_mutation_ids=review["approved_mutation_ids"])
        _result(original, task, refsha, evaluator)
        _result(probe_result, probe, refsha, evaluator)
        _require(original["passed"] is True, "Original reference calibration failed")
        mutations = [{"id": mid, "output": output, "reference_sha256": refsha,
                      "proposal_sha256": proposal["sha256"],
                      "evaluator_source_hashes": probe_result["evaluator_source_hashes"],
                      "sandbox_id": probe_result["sandbox_id"]}
                     for mid, output in zip(probe["metadata"]["probe_mutation_ids"], probe_result["outputs"])]
        replay = audit_reference_task(task, proposal, reference_sha256=refsha,
                                      original_result=original, mutation_results=mutations, review=review)
        _require(_same(replay, audit) and audit["eligible"] is True,
                 "Saved audit differs from execution replay or is ineligible")
        description = task["prompt"].split("\n\n")[1] if "\n\n" in task["prompt"] else task["prompt"]
        new_category = change["independently_reviewed_category"]
        _require(change["original_serialized_category"] == task["category"] == audit["task"]["category"]
                 and change["source_row_sha256"] == task["metadata"]["source_row_sha256"]
                 and _sha(change["source_row_sha256"])
                 and change["source_description"] == description
                 and new_category == category(task["prompt"])
                 and type(change.get("reason")) is str and change["reason"].strip(),
                 "Category correction differs from reviewed description/source/old value")
        derived = deepcopy(audit["task"])
        derived["category"] = new_category
        _require(_same({k: v for k, v in derived.items() if k != "category"},
                       {k: v for k, v in audit["task"].items() if k != "category"}),
                 "Category-only derivation changed task content")
        reviewed[tid] = new_category
        pool.append(derived)
        lineage.append({"task_id": tid, "original_task_sha256": digest(task),
                        "original_augmented_task_sha256": digest(audit["task"]),
                        "derived_task_sha256": digest(derived), "audit_sha256": audit["sha256"],
                        "proposal_sha256": proposal["sha256"], "review_sha256": digest(review),
                        "reference_sha256": refsha, "correction_row_sha256": digest(change),
                        "original_category": task["category"], "derived_category": new_category,
                        "changed_fields": [] if task["category"] == new_category else ["category"]})
    preflight = preflight_task_categories(pool, first_n=train_count,
        min_categories=len(expected_counts), min_pool_count=len(pool), expected_categories=reviewed)
    _require(preflight["first_n_category_counts"] == expected_counts,
             "Selected prefix category counts differ from preregistration")
    result = {"schema_version": 1, "version": VERSION, "status": "derived_offline",
              "source_run_id": report["run_id"], "source_plan_sha256": plan_sha,
              "source_prepared_sha256": digest(prepared), "source_report_sha256": digest(report),
              "source_audits_sha256": digest(audits), "correction_sha256": correction_sha,
              "evaluator_source_hashes": deepcopy(evaluator), "replayed_audit_count": len(audits),
              "accepted_additional_calls": sum(len(a["accepted"]) for a in audits),
              "audited_pool": pool, "train": deepcopy(pool[:train_count]), "lineage": lineage,
              "preflight": preflight, "expected_category_counts": deepcopy(expected_counts),
              "transformation": "Only augmented task.category changes; old evidence bindings remain unchanged.",
              "interpretation": "Saved evidence consistency, not proof of origin/reference correctness; no execution or launch."}
    return {**result, "sha256": digest(result)}
