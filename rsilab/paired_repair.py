"""Replay a matched, two-attempt sampling/repair study from trusted JSON records."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json

from rsi.mbpp_verification_v2 import MBPP_ALLOWED_IMPORTS, MBPP_VERIFIER_VERSION
from rsi.verification import MAX_PAYLOAD_BYTES, CandidatePolicyError, extract_code, validate_code
from .core import digest
from .learning import _outcome, _task
from .successor import _agent, _inference, inference_request_sha256
from .task_contracts import VERSION as CONTRACT_VERSION, score_task_contract_outputs


ROLES = ("original", "learned")
BRANCHES = ("sample", "repair")
CHILD_COUNT = 16
REQUIRED_CATEGORIES = ("text", "numeric", "collections")


def _check(valid, message):
    if not valid:
        raise ValueError(message)


def _check_manifest(manifest):
    _check(manifest["version"] == CONTRACT_VERSION and manifest["sha256"] ==
           digest({k: v for k, v in manifest.items() if k != "sha256"}), "Invalid training manifest seal")
    tasks = manifest["tasks"]
    ids = [task["id"] for task in tasks]
    _check(ids and len(set(ids)) == len(ids), "Missing or duplicate training task")
    _check(manifest["prompts"] == [{"id": task["id"], "prompt": task["prompt"]} for task in tasks],
           "Invalid generation projection")
    _check([link["task_id"] for link in manifest["lineage"]] == ids, "Contract lineage order mismatch")
    for task, link in zip(tasks, manifest["lineage"]):
        _task(task)
        _check(task["split"] == task["metadata"]["source_split"] == "train", "Non-training task")
        _check(link["derived_sha256"] == digest(task), "Detached task contract")


def _records(manifest, rows):
    _check(isinstance(rows, list) and len(rows) == len(manifest["tasks"]), "Incomplete task coverage")
    for row, task in zip(rows, manifest["tasks"]):
        _check(digest(row["task"]) == digest(task), "Task order or content differs from manifest")


def _pre_execution_failure(task, generation, verification):
    """Replay the existing bounded extraction and policy checks without executing code."""
    try:
        code = extract_code(generation["text"])
        validate_code(code, task["entry_point"], allowed_imports=MBPP_ALLOWED_IMPORTS)
    except CandidatePolicyError as exc:
        kind, error = "candidate_policy", f"candidate_policy:{exc}"
    except (SyntaxError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        kind, error = "invalid_candidate", f"invalid_candidate_or_payload:{type(exc).__name__}"
    else:
        # Native V2 also checks the encoded supervisor payload size after parsing.
        payload = {"code": code, "entry_point": task["entry_point"],
                   "inputs": [{k: c[k] for k in ("args", "kwargs")} for c in task["cases"]]}
        _check(len(json.dumps(payload, allow_nan=False).encode()) > MAX_PAYLOAD_BYTES,
               "Pre-execution failure cannot be reproduced")
        kind, error = "invalid_candidate", "invalid_candidate_or_payload:ValueError"
    _check(verification["error_kind"] == kind and verification["errors"] == [error],
           "Pre-execution failure differs from replay")
    return kind


def _failure_kind(manifest, row, evaluator=None):
    """Return a fixed vocabulary label only after checking the actual outcome."""
    passed = _outcome(row, evaluator=evaluator)
    generation, verification, task = row["generation"], row["verification"], row["task"]
    kind, outputs = verification.get("error_kind"), verification.get("outputs")
    if not passed:
        _check(row.get("verified_code") is None, "Failed attempt carries a verified target")
    if generation["hit_token_limit"]:
        _check(outputs is None and verification["count"] == 0, "Truncation carries execution evidence")
        return "generation_limit"

    _check(verification["verifier_version"] == MBPP_VERIFIER_VERSION, "Unexpected executor version")
    if kind in ("candidate_policy", "invalid_candidate"):
        _check(not passed and verification["count"] == 0 and verification["errors"] and outputs is None
               and verification.get("sandbox_id") is None, "Invalid pre-execution failure")
        return _pre_execution_failure(task, generation, verification)

    code = extract_code(generation["text"])
    validate_code(code, task["entry_point"], allowed_imports=MBPP_ALLOWED_IMPORTS)
    _check(verification.get("candidate_sha256") == hashlib.sha256(code.encode()).hexdigest()
           and verification.get("source_tests_sha256") == task["source_tests_sha256"],
           "Detached candidate or test evidence")
    _check(isinstance(verification.get("sandbox_id"), str) and verification["sandbox_id"].strip(),
           "Missing isolated execution identity")
    if not isinstance(outputs, list):
        # The V2 supervisor can emit a process-level failure instead of per-case outputs.
        _check(kind == "candidate_execution" and not passed and verification["count"] == 0
               and verification["errors"], "Missing failed execution evidence")
        if outputs is None:
            _check(verification["errors"] in (["sandbox_process_failed"], ["invalid_output_json"],
                                              ["output_too_large"]), "Unknown sandbox failure")
        else:
            _check(isinstance(outputs, dict) and outputs.get("error") in
                   ("candidate_timeout", "candidate_process_failed")
                   and verification["errors"] == [outputs["error"]], "Invalid process failure envelope")
        return "execution_error"

    _check(len(outputs) == len(task["cases"]) and all(
        isinstance(item, dict) and (item.get("ok") is True and "value" in item or
        item.get("ok") is False and item.get("error_stage") in ("candidate_call", "encode")
        and isinstance(item.get("error"), str)) for item in outputs), "Incomplete per-case executor outputs")
    computed = score_task_contract_outputs(manifest, task["id"], outputs)
    _check(all(k in verification for k in computed) and
           digest({k: verification[k] for k in computed}) == digest(computed),
           "Saved typed scorer evidence differs from replay")
    if passed:
        _check(kind is None and row.get("verified_code") == code, "Unbound verified code or failure flag")
        return "passed"
    _check(kind in (None, "candidate_execution"), "Unknown executor outcome")
    errors = {error.partition(":")[2] for error in computed["errors"]}
    if "execution_error" in errors:
        return "execution_error"
    if "invalid_result" in errors:
        return "invalid_result"
    return "wrong_output"


def _prompts(manifest, rows, kinds):
    sample = {task["id"]: task["prompt"] for task in manifest["tasks"]}
    repair = dict(sample)
    for row, kind in zip(rows, kinds):
        if kind != "passed":
            key = row["task"]["id"]
            repair[key] += ("\n\nPrevious answer:\n" + row["generation"]["text"] +
                            "\n\nVerifier feedback: " + kind +
                            ".\nReturn a complete corrected Python implementation.")
    return {"sample": sample, "repair": repair}


def second_prompts(manifest: dict, first_records: list[dict]) -> dict:
    """Project public second requests; independently replay scored first attempts."""
    _check_manifest(manifest)
    _records(manifest, first_records)
    kinds = [_failure_kind(manifest, row) for row in first_records]
    return _prompts(manifest, first_records, kinds)


def _controls(controls, n):
    _check(set(controls) == {"first", "second"}, "Missing frozen branch controls")
    for name, seed, temp in (("first", 42, 0.0), ("second", 31415, 0.7)):
        control = controls[name]
        _inference(control, n)
        generation = control["generation"]
        _check((generation["seed"], generation["temperature"], generation["max_input_tokens"],
                generation["max_new_tokens"], generation["enable_thinking"]) ==
               (seed, temp, 2048, 512, False), "Controls differ from paired repair protocol")
        _check(control["effective_seeds"] == list(range(seed, seed + n)), "Unexpected effective task seeds")
        _check(control["evaluator"]["version"] == MBPP_VERIFIER_VERSION
               and "rsilab/task_contracts.py" in control["runtime"]["source_hashes"],
               "Missing executor or typed scorer identity")
    for field in ("runtime", "evaluator"):
        _check(controls["first"][field] == controls["second"][field], "First/second runtime or evaluator differs")


def _collection(manifest, teacher, coll, expected_controls, expected_prompts):
    _check(digest(coll["controls"]) == digest(expected_controls), "Actual controls differ from frozen controls")
    _check(coll["prompts"] == expected_prompts, "Actual prompts differ from public branch requests")
    _check(coll["request_sha256"] == inference_request_sha256(teacher, expected_controls, expected_prompts),
           "Detached normalized inference request")
    rows = coll["records"]
    _records(manifest, rows)
    kinds = []
    for row, seed in zip(rows, expected_controls["effective_seeds"]):
        _check(type(row["effective_seed"]) is int and row["effective_seed"] == seed, "Actual task seed mismatch")
        generation = row["generation"]
        for key, limit in (("input_tokens", "max_input_tokens"), ("output_tokens", "max_new_tokens")):
            _check(type(generation.get(key)) is int and 0 < generation[key] <= expected_controls["generation"][limit],
                   "Invalid actual token count")
        _check(generation["hit_token_limit"] is (generation["output_tokens"] ==
               expected_controls["generation"]["max_new_tokens"]), "Inconsistent generation-limit flag")
        kinds.append(_failure_kind(manifest, row, expected_controls["evaluator"]))
    return kinds


def _selection(tasks, first, second, branch, run_id):
    solved, selected, duplicates, seen = [], [], [], set()
    for task, greedy, retry in zip(tasks, first, second):
        if greedy["verification"]["passed"]:
            row, source = greedy, "first"
        elif retry["verification"]["passed"]:
            row, source = retry, branch
        else:
            continue
        solved.append(task["id"])
        code_hash = row["verification"]["candidate_sha256"]
        if code_hash in seen:
            duplicates.append(task["id"])
            continue
        seen.add(code_hash)
        selected.append({"task_id": task["id"], "category": task["category"], "prompt": task["prompt"],
                         "completion": row["verified_code"], "verified": True, "source": source,
                         "code_sha256": code_hash, "record_sha256": digest(row), "run_id": run_id})
    return {"solved_ids": solved, "selected": selected, "duplicate_code_ids": duplicates,
            "unique_count": len(selected), "categories": dict(Counter(row["category"] for row in selected))}


def _pair(ids, left, right):
    groups = {"both": [], "left_only": [], "right_only": [], "neither": []}
    a, b = set(left), set(right)
    labels = {(False, False): "neither", (True, False): "left_only",
              (False, True): "right_only", (True, True): "both"}
    for task_id in ids:
        groups[labels[task_id in a, task_id in b]].append(task_id)
    return groups


def _audit_run(manifest, teacher, controls, run):
    _check(isinstance(run["run_id"], str) and run["run_id"].strip(), "Missing run identity")
    _check(run["teacher"] == teacher and run["manifest_sha256"] == manifest["sha256"], "Run lineage mismatch")
    cols = run["collections"]
    _check(set(cols) == {"first", *BRANCHES}, "Each run requires three physical collections")
    first = cols["first"]
    kinds = _collection(manifest, teacher, first, controls["first"], manifest["prompts"])
    prompts = _prompts(manifest, first["records"], kinds)
    selections = {}
    for branch in BRANCHES:
        ordered = [{"id": key, "prompt": prompt} for key, prompt in prompts[branch].items()]
        _collection(manifest, teacher, cols[branch], controls["second"], ordered)
        selections[branch] = _selection(manifest["tasks"], first["records"], cols[branch]["records"], branch,
                                        run["run_id"])
    ids = [task["id"] for task in manifest["tasks"]]
    pair = _pair(ids, *(selections[b]["solved_ids"] for b in BRANCHES))
    unique_pair = _pair(ids, *([r["task_id"] for r in selections[b]["selected"]] for b in BRANCHES))
    paired_recoveries = {category: _pair([task["id"] for task, kind in zip(manifest["tasks"], kinds)
                                          if task["category"] == category and kind != "passed"],
                                         *(selections[b]["solved_ids"] for b in BRANCHES))
                         for category in dict.fromkeys(task["category"] for task in manifest["tasks"])}
    tokens = {name: {field: sum(r["generation"][field] for r in col["records"])
                     for field in ("input_tokens", "output_tokens")} for name, col in cols.items()}
    return {"run": deepcopy(run), "tokens": tokens, "first_outcomes": dict(zip(ids, kinds)),
            "arms": selections, "paired_solved": pair, "paired_unique": unique_pair,
            "recoveries_by_category": paired_recoveries,
            "repair_minus_sample_unique": selections["repair"]["unique_count"] - selections["sample"]["unique_count"]}


def _child_gate(results, tasks):
    repairs = {role: results[role]["arms"]["repair"] for role in ROLES}
    available = {category: min(repair["categories"].get(category, 0) for repair in repairs.values())
                 for category in dict.fromkeys(t["category"] for t in tasks)}
    # Preserve first appearance, visiting required categories before optional ones.
    order = sorted(available, key=lambda category: category not in REQUIRED_CATEGORIES)
    quotas = Counter()
    while quotas.total() < CHILD_COUNT:
        eligible = [cat for cat in order if quotas[cat] < min(available[cat], CHILD_COUNT * 60 // 100)]
        if not eligible:
            break
        quotas.update(eligible[:CHILD_COUNT - quotas.total()])
    reasons = []
    for role, repair in repairs.items():
        if repair["unique_count"] < CHILD_COUNT:
            reasons.append(role + "_too_few_unique_targets")
        if any(repair["categories"].get(cat, 0) == 0 for cat in REQUIRED_CATEGORIES):
            reasons.append(role + "_missing_required_category")
        if any(n * 100 > 60 * repair["unique_count"] for n in repair["categories"].values()):
            reasons.append(role + "_category_share_exceeded")
    if quotas.total() < CHILD_COUNT:
        reasons.append("insufficient_common_category_capacity")
    if any(not quotas[cat] for cat in REQUIRED_CATEGORIES):
        reasons.append("missing_common_required_category")
    rows, examples = {}, {}
    for role, repair in repairs.items():
        remaining = quotas.copy()
        rows[role] = []
        for row in repair["selected"]:
            if remaining[row["category"]] > 0:
                rows[role].append(row)
                remaining[row["category"]] -= 1
        examples[role] = [{k: row[k] for k in ("prompt", "completion", "verified")} for row in rows[role]]
    if not reasons and examples["original"] == examples["learned"]:
        reasons.append("identical_child_data")
    return {"eligible": not reasons, "reasons": reasons, "category_counts": dict(quotas),
            "selected_ids": {r: [row["task_id"] for row in rows[r]] for r in ROLES},
            "examples": examples if not reasons else {r: [] for r in ROLES}}


def audit_paired_repair(manifest: dict, teachers: dict, controls: dict,
                        original_run: dict, learned_run: dict) -> dict:
    """Audit both teachers and release paired child labels only when the fixed gate passes."""
    _check_manifest(manifest)
    _controls(controls, len(manifest["tasks"]))
    _check(set(teachers) == set(ROLES), "Missing teacher roles")
    for teacher in teachers.values():
        _agent(teacher)
    original, learned = (teachers[role] for role in ROLES)
    _check(original["agent_id"] != learned["agent_id"] and original["adapter_sha256"] is None
           and original["parent_agent_sha256"] is None and learned["adapter_sha256"] is not None
           and learned["parent_agent_sha256"] == digest(original)
           and all(original[k] == learned[k] for k in ("model_id", "revision", "tokenizer_revision")),
           "Invalid learned teacher lineage")
    _check(original_run["run_id"] != learned_run["run_id"], "Duplicate run identity")
    results = {role: _audit_run(manifest, teachers[role], controls, run) for role, run in
               zip(ROLES, (original_run, learned_run))}
    ids = [task["id"] for task in manifest["tasks"]]
    cross_teacher = {branch: _pair(ids, *([r["task_id"] for r in results[role]["arms"][branch]["selected"]]
                                          for role in ROLES)) for branch in BRANCHES}
    report = {"version": "paired-repair-v1", "manifest_sha256": manifest["sha256"],
              "controls": deepcopy(controls), "teachers": results, "paired_teachers_unique": cross_teacher,
              "child_gate": _child_gate(results, manifest["tasks"]), "promoted": False, "sustained_rsi": False}
    return {**report, "sha256": digest(report)}
