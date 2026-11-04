"""Offline, reference-derived MBPP augmentation with explicit evidence gates.

No file/network I/O, provider credentials, generation or source-code execution.
Remote reference work and independent semantic review belong to the controller.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Iterable, Mapping

from .core import digest
from rsi.datasets import DATASET_ID, REVISION, IMPORTER_VERSION, SEALED_DOMAIN, SOURCE_HASHES
from rsi.mbpp_verification import convert_mbpp_task, convert_mbpp_tests, encode_value, decode_value
from rsi.mbpp_verification_v2 import decode_value as decode_reference_value, score_mbpp_outputs

VERSION = "mbpp-verified-data-v1"
PINNED_POOL_SHA256 = "13907d86dc89f61a1bfb06d691415984b6efd0304d5b321b914d787d8873b49f"
CATEGORIES = ("collections", "text", "numeric", "other")
DIAGNOSTIC_IDS = frozenset(f"mbpp-full-{n}" for n in (512, 520, 557, 558, 568, 576, 928))
MANUAL_DUPLICATE_IDS = frozenset(f"mbpp-full-{n}" for n in (955, 541, 629, 554))
MAX_MUTATIONS = 12
MIN_ADDITIONAL_CASES = 3
AUDIT_CAPS = {"train": 192, "dev": 64}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _sealed(payload: dict) -> dict:
    return {**payload, "sha256": digest(payload)}


def _check_hash(record: Mapping, label: str) -> None:
    _require(record.get("sha256") == digest({k: v for k, v in record.items() if k != "sha256"}),
             f"{label} hash mismatch")


def category(prompt: str) -> str:
    """Versioned broad taxonomy; categories may overlap across native splits."""
    text = (prompt.split("\n\n")[1] if "\n\n" in prompt else prompt).lower()
    if any(w in text for w in ("string", "word", "character", "substring", "vowel", "regex")):
        return "text"
    if any(w in text for w in ("list", "tuple", "array", "matrix", "dictionary", "heap", "sort")):
        return "collections"
    if any(w in text for w in ("number", "integer", "prime", "factor", "digit", "sum", "triangle",
                              "area", "perimeter", "slope", "quadratic", "discriminant", "lcm",
                              "fibonacci", "volume", "arc length", "wind chill")):
        return "numeric"
    return "other"


def _balanced(tasks: list[dict], count: int, seed: int) -> tuple[list[dict], list[dict]]:
    buckets = {c: sorted((t for t in tasks if t["category"] == c),
                         key=lambda t: (t["metadata"]["coding_data"]["previously_generated"]
                                        if t["split"] == "dev" else False,
                                        digest([VERSION, seed, t["id"]]))) for c in CATEGORIES}
    ordered = []
    # Round robin reallocates exhausted small categories, rather than duplicating
    # rare tasks or silently moving tasks between dataset-native splits.
    phases = (False, True) if tasks and tasks[0]["split"] == "dev" else (None,)
    for exposure in phases:
        while any(b and (exposure is None or b[0]["metadata"]["coding_data"]["previously_generated"] == exposure)
                  for b in buckets.values()):
            for c in CATEGORIES:
                if buckets[c] and (exposure is None or buckets[c][0]["metadata"]["coding_data"]["previously_generated"] == exposure):
                    ordered.append(buckets[c].pop(0))
    _require(len(ordered) >= count, f"insufficient eligible tasks: need {count}, have {len(ordered)}")
    return ordered[:count], ordered[count:]


def select_mbpp_tasks(pool_manifest: Mapping, *, previous_tasks: Iterable[dict],
                      train_count: int = 96, dev_count: int = 32, seed: int = 43,
                      eligible_ids: Iterable[str] | None = None,
                      train_excluded_ids: Iterable[str] = (),
                      expected_pool_sha256: str = PINNED_POOL_SHA256) -> dict:
    """Select from pinned importer pools; expose reserves for a new frozen plan.

    ``previous_tasks`` must include every prior development task (pass all old
    manifest tasks). Prior training tasks may recur; development reuse is reported.
    ``eligible_ids`` is an optional preregistered reference/manual-review allowlist,
    never a filter based on model performance. Defaults use the complete pool.
    No final-test task or prompt is returned. Source test bytes are not read.
    """
    _require(type(seed) is int and 0 <= seed < 2**31, "invalid seed")
    _require(all(type(n) is int and n >= 4 for n in (train_count, dev_count)), "counts must be at least four")
    payload = {k: v for k, v in pool_manifest.items() if k != "manifest_sha256"}
    _require(digest(payload) == pool_manifest.get("manifest_sha256") == expected_pool_sha256,
             "pool is not the explicitly pinned importer result")
    _require(pool_manifest.get("dataset") == DATASET_ID and pool_manifest.get("revision") == REVISION
             and pool_manifest.get("config") == "full"
             and pool_manifest.get("importer_version") == IMPORTER_VERSION, "wrong dataset/importer")
    _require(pool_manifest.get("source_sha256") == SOURCE_HASHES
             and pool_manifest.get("source_counts", {}).get("test") == 500, "sealed source inventory mismatch")
    previous = list(previous_tasks)
    _require(previous and len({t["id"] for t in previous}) == len(previous), "missing/duplicate history")
    historical_eval = [t for t in previous if t["split"] != "train"]
    old_ids = {t["id"] for t in historical_eval}
    old_clusters = {t["family"] for t in historical_eval}
    old_rows = {t["metadata"]["source_row_sha256"] for t in historical_eval}
    allowed = None if eligible_ids is None else set(eligible_ids)
    retention_exclusions = set(train_excluded_ids)
    prior_ids = {t["id"] for t in previous}
    clusters = {c["id"]: c for c in pool_manifest["duplicate_clusters"]}
    excluded, selected, reserves, available = [], [], [], {}
    seen = set()
    for split, source_split, count in (("train", "train", train_count), ("dev", "validation", dev_count)):
        candidates = []
        for original in pool_manifest["pools"][split]:
            tid, meta = original["id"], original["metadata"]
            _require(tid not in seen, "duplicate pool task")
            seen.add(tid)
            _require(original["split"] == split and meta["source_split"] == source_split
                     and meta["revision"] == REVISION and meta["config"] == "full", "wrong native split")
            cluster = clusters[original["family"]]
            _require(cluster["source_splits"] == [source_split]
                     and meta["source_id"] == min(cluster["source_ids"]), "unscreened duplicate cluster")
            reason = None
            if tid in MANUAL_DUPLICATE_IDS:
                reason = "manual_cross_split_near_duplicate"
            elif split == "train" and (tid in old_ids or original["family"] in old_clusters
                                        or meta["source_row_sha256"] in old_rows):
                reason = "historical_evaluation_leakage"
            elif tid in DIAGNOSTIC_IDS:
                reason = "posthoc_diagnostic_task"
            elif split == "train" and tid in retention_exclusions:
                reason = "reserved_retention_task"
            elif SEALED_DOMAIN.search(original["prompt"]):
                reason = "sealed_pilot_domain"
            elif allowed is not None and tid not in allowed:
                reason = "outside_reference_review_allowlist"
            if reason:
                excluded.append({"id": tid, "split": split, "reason": reason})
                continue
            try:
                task = convert_mbpp_task(deepcopy(original))
            except ValueError as exc:
                excluded.append({"id": tid, "split": split, "reason": "unsupported_original_tests",
                                 "detail": str(exc)})
                continue
            task["category"] = category(task["prompt"])
            task["metadata"]["coding_data"] = {
                "previously_generated": tid in prior_ids,
                "previous_exposure": "development" if tid in old_ids else "training" if tid in prior_ids else "none_recorded",
                "held_out_claim": False,
            }
            if len(propose_mutations(task, seed=seed)["mutations"]) < MIN_ADDITIONAL_CASES:
                excluded.append({"id": tid, "split": split, "reason": "insufficient_input_mutations"})
                continue
            candidates.append(task)
        available[split] = dict(Counter(t["category"] for t in candidates))
        chosen, reserve = _balanced(candidates, count, seed)
        _require(set(t["category"] for t in chosen) == set(CATEGORIES), f"{split}: four categories unavailable")
        selected.extend(chosen)
        reserves.extend(reserve[:max(0, AUDIT_CAPS[split] - count)])
        _require(count <= AUDIT_CAPS[split], "requested count exceeds frozen audit cap")
    return _sealed({
        "version": VERSION, "stage": "proposed", "seed": seed,
        "pool_sha256": expected_pool_sha256, "previous_tasks_sha256": digest(previous),
        "historical_evaluation_ids": sorted(old_ids), "tasks": selected, "reserve_tasks": reserves,
        "retention_excluded_ids": sorted(retention_exclusions),
        "audit_caps": deepcopy(AUDIT_CAPS),
        "fallback_policy": "audit exact bounded selected+reserve pool; first eligible tasks in frozen per-split order; no candidate-based replacement",
        "requested_counts": {"train": train_count, "dev": dev_count},
        "available_by_category": available,
        "selected_by_category": {s: dict(Counter(t["category"] for t in selected if t["split"] == s))
                                 for s in ("train", "dev")},
        "reused_development_ids": sorted(t["id"] for t in selected if t["split"] == "dev" and t["id"] in old_ids),
        "exclusions": sorted(excluded, key=lambda x: x["id"]),
        "duplicate_screen": {"importer": IMPORTER_VERSION, "clusters_sha256": digest(pool_manifest["duplicate_clusters"]),
                             "manual_excluded_ids": sorted(MANUAL_DUPLICATE_IDS),
                             "limitation": "heuristic exact/near deduplication; not semantic family disjointness"},
        "sealed_final": {"dataset": DATASET_ID, "revision": REVISION, "config": "full", "split": "test",
                         "count": 500, "file_sha256": SOURCE_HASHES["full/test-00000-of-00001.parquet"],
                         "prompts_included": False, "execution_performed": False},
        "ready_for_generation": False, "ready_for_training": False,
        "interpretation": "native-split development study; category overlap and prior dev reuse disclosed",
    })


def _variants(value, path=()):
    """Bounded single-site structural mutations; semantic validity needs review."""
    if type(value) is int and 0 <= value <= 1000:
        for new in (value + 1, value - 1, 1, 2):
            if (0 if value == 0 else 1) <= new <= 1000 and new != value:
                yield new, ("nonnegative_integer", path)
    elif type(value) is str and 0 < len(value) <= 128 and value.isascii():
        lower = sorted(set(c for c in value if 'a' <= c <= 'z'))
        upper = sorted(set(c for c in value if 'A' <= c <= 'Z'))
        for shift in (1, 2, 3):
            translation = {ord(c): alphabet[(i + shift) % len(alphabet)]
                           for alphabet in (lower, upper) for i, c in enumerate(alphabet)}
            text = value.translate(translation)
            if text != value:
                yield text, ("observed_ascii_alphabet_substitution", path)
    elif type(value) in (list, tuple) and 0 < len(value) <= 32 and len(path) < 4:
        constructor = type(value)
        for permuted in (value[::-1], value[1:] + value[:1]):
            if permuted != value:
                yield constructor(permuted), ("sequence_permutation", path)
        for index, item in enumerate(value):
            for replacement, label in _variants(item, path + (index,)):
                changed = list(value)
                changed[index] = replacement
                yield constructor(changed), label


def propose_mutations(task: Mapping, *, seed: int = 43, max_mutations: int = 12) -> dict:
    """Emit only typed args/kwargs/projections, never candidate-derived expectations.

    At most 12 proposals; retain sequence lengths, container types, and string
    length/case/punctuation. Do not change floats, bools, negative ints, dicts or
    empty values. Change one argument/keyword at a time, never permute the call's
    argument tuple. Ref errors and review failures must be rejected downstream.
    """
    _require(type(seed) is int and 0 <= seed < 2**31, "invalid seed")
    _require(type(max_mutations) is int and max_mutations == MAX_MUTATIONS, "v1 fixes mutation limit at 12")
    checked = convert_mbpp_tests(task["test_list"], task["entry_point"],
                                test_setup_code=task.get("test_setup_code", ""),
                                test_imports=task.get("test_imports", []),
                                challenge_test_list=task.get("challenge_test_list", []))
    _require(all(task.get(k) == v for k, v in checked.items()), "original compiled cases changed")
    originals = {digest([c["args"], c["kwargs"]]) for c in task["cases"]}
    unique = {}
    for index, case in enumerate(task["cases"]):
        args, kwargs = decode_value(case["args"]), decode_value(case["kwargs"])
        has_container = any(type(v) in (list, tuple, dict, set, frozenset) for v in (*args, *kwargs.values()))
        # Multiple containers can encode coupled arrays (one extra element,
        # permutations, matching dimensions). Generic single-site mutation is
        # not a safe domain rule for them; exclude instead of guessing.
        if sum(type(v) in (list, tuple, dict, set, frozenset) for v in (*args, *kwargs.values())) > 1:
            continue
        for kind, values in (("arg", list(enumerate(args))), ("kwarg", sorted(kwargs.items()))):
            for key, value in values:
                # Scalars alongside containers commonly denote bounds, sizes or
                # indices. Preserve them instead of guessing their relationships.
                if has_container and type(value) is int:
                    continue
                for replacement, (method, path) in _variants(value):
                    if not _preserves_domain_shape(value, replacement):
                        continue
                    new_args, new_kwargs = list(args), deepcopy(kwargs)
                    if kind == "arg":
                        new_args[key] = replacement
                    else:
                        new_kwargs[key] = replacement
                    wire_args, wire_kwargs = encode_value(tuple(new_args)), encode_value(new_kwargs)
                    identity = digest([wire_args, wire_kwargs])
                    if identity in originals or identity in unique:
                        continue
                    unique[identity] = {"id": f"{task['id']}/mutation/{identity[:20]}",
                        "args": wire_args, "kwargs": wire_kwargs, "projections": deepcopy(case["projections"]),
                        "source_case_index": index, "method": method,
                        "site": [kind, key, *path]}
    ordered = sorted(unique.values(), key=lambda m: digest([VERSION, seed, m["id"]]))
    return _sealed({"version": VERSION, "task_id": task["id"], "task_sha256": digest(task),
                    "seed": seed, "max_mutations": max_mutations, "mutations": ordered[:max_mutations],
                    "expectations_present": False, "review_required": True})


def _preserves_domain_shape(before, after) -> bool:
    """Static necessary conditions, not proof of task-specific input validity."""
    if type(before) is not type(after):
        return False
    if type(before) in (list, tuple):
        if len(before) != len(after):
            return False
        if not all(_preserves_domain_shape(a, b) for a, b in zip(before, after)):
            return False
        if len(before) > 1 and all(type(x) is int for x in before):
            if list(before) == sorted(before) and list(after) != sorted(after):
                return False
            if list(before) == sorted(before, reverse=True) and list(after) != sorted(after, reverse=True):
                return False
    return True


def audit_pool(selection: Mapping) -> list[dict]:
    """Exact bounded prospective audit inventory, in final fallback order."""
    _check_hash(selection, "selection")
    tasks = selection["tasks"] + selection["reserve_tasks"]
    _require(len({t["id"] for t in tasks}) == len(tasks), "duplicate audit tasks")
    result = []
    for split in ("train", "dev"):
        group = [t for t in tasks if t["split"] == split]
        _require(len(group) <= AUDIT_CAPS[split], "audit pool exceeds frozen cap")
        result.extend(deepcopy(group))
    return result


def _literal_text(value) -> str:
    """Deterministic builtin literal syntax, including hash-randomized sets."""
    if type(value) is dict:
        return '{' + ', '.join(_literal_text(k) + ': ' + _literal_text(v) for k, v in value.items()) + '}'
    if type(value) in (set, frozenset):
        items = sorted(value, key=lambda x: digest(encode_value(x)))
        inside = '{' + ', '.join(_literal_text(x) for x in items) + '}' if items else 'set()'
        return f'frozenset({inside})' if type(value) is frozenset else inside
    if type(value) in (list, tuple):
        inside = ', '.join(_literal_text(x) for x in value)
        return '[' + inside + ']' if type(value) is list else '(' + inside + (',' if len(value) == 1 else '') + ')'
    return repr(value)


def build_probe_task(task: Mapping, proposal: Mapping, *, approved_mutation_ids: Iterable[str]) -> dict:
    """Build a reference-only v2-compatible probe task with NON-authoritative None expectations.

    Only remote reference outputs are meaningful here; its score is never used.
    metadata.probe_mutation_ids maps each output to the corresponding proposal.
    Controller must gate reference calibration before executing these probes.
    """
    _check_hash(proposal, "proposal")
    _require(proposal == propose_mutations(task, seed=proposal["seed"], max_mutations=proposal["max_mutations"]),
             "probe proposal changed")
    approved_list = list(approved_mutation_ids)
    approved = set(approved_list)
    _require(len(approved) == len(approved_list) and approved <= {m["id"] for m in proposal["mutations"]},
             "unknown/duplicate approved mutation")
    mutations = [m for m in proposal["mutations"] if m["id"] in approved]
    _require(len(mutations) >= MIN_ADDITIONAL_CASES, "fewer than three independently approved probes")
    assertions = []
    for m in mutations:
        args, kwargs = decode_value(m["args"]), decode_value(m["kwargs"])
        call = task["entry_point"] + '(' + ', '.join(
            [_literal_text(a) for a in args] + [f'{k}={_literal_text(v)}' for k, v in sorted(kwargs.items())]) + ')'
        for projection in m["projections"]:
            call = f'{projection}({call})'
        assertions.append(f'assert {call} == None')
    result = deepcopy(dict(task))
    result.update(convert_mbpp_tests(assertions, task["entry_point"]))
    result.update(id=task["id"] + '-reference-probes-v1', test_list=assertions, challenge_test_list=[])
    result["metadata"].pop("task_sha256", None)
    result["metadata"].update(reference_probe_only=True, expectations_authoritative=False,
                              proposal_sha256=proposal["sha256"], original_task_id=task["id"],
                              probe_mutation_ids=[m["id"] for m in mutations])
    return result


def audit_reference_task(task: Mapping, proposal: Mapping, *, reference_sha256: str,
                         original_result: Mapping, mutation_results: list[dict], review: Mapping) -> dict:
    """Validate saved remote reference results; do not run the reference.

    ``reference_sha256`` is SHA256 of the verifier-extracted reference code.
    ``review`` binds task/proposal/reference hashes, nonempty reviewer/notes, and
    approved=True. It attests independent reference/domain review, not model review.
    review.approved_mutation_ids is the independent domain-review allowlist.
    Provide results for exactly that subset; unapproved proposals never execute.
    Optional mutation_exclusion_reasons records per-ID review explanations.
    Each mutation result: {id, output:{ok,value|error}, reference_sha256,
    proposal_sha256, evaluator_source_hashes, sandbox_id}. All IDs must occur once;
    execution/encoding errors remain rejected evidence. Infrastructure errors abort.
    """
    _check_hash(proposal, "proposal")
    _require(proposal == propose_mutations(task, seed=proposal["seed"], max_mutations=proposal["max_mutations"]),
             "proposal does not match deterministic inputs")
    _require(type(reference_sha256) is str and len(reference_sha256) == 64
             and all(c in '0123456789abcdef' for c in reference_sha256), "invalid reference hash")
    _require(review.get("task_sha256") == digest(task)
             and review.get("proposal_sha256") == proposal["sha256"]
             and review.get("reference_sha256") == reference_sha256
             and isinstance(review.get("reviewer"), str) and review["reviewer"].strip()
             and isinstance(review.get("notes"), str) and review["notes"].strip(), "independent review missing/mismatched")
    _require(original_result.get("candidate_sha256") == reference_sha256
             and original_result.get("source_tests_sha256") == task["source_tests_sha256"]
             and original_result.get("verifier_version") == "mbpp-typed-v2"
             and original_result.get("sandbox_id")
             and original_result.get("evaluator_source_hashes")
             and not original_result.get("infrastructure_error"), "reference calibration identity failure")
    calibration = score_mbpp_outputs(original_result.get("outputs"), task["cases"])
    _require(all(original_result.get(k) == calibration[k] for k in ("passed", "count", "total")),
             "reference calibration score inconsistent")
    if not calibration["passed"] or review.get("approved") is not True:
        _require(not mutation_results, "probes ran despite failed calibration/review")
        reason = "original_reference_calibration_failed" if not calibration["passed"] else "independent_review_not_approved"
        return _sealed({"version": VERSION, "task_id": task["id"], "task_sha256": digest(task),
            "proposal": deepcopy(dict(proposal)), "reference_sha256": reference_sha256,
            "original_result": deepcopy(dict(original_result)), "mutation_results": [],
            "review": deepcopy(dict(review)), "accepted": [], "rejected": [{"id": m["id"], "reason": reason} for m in proposal["mutations"]],
            "eligible": False, "task": None,
            "interpretation": "reference-derived augmentation, not proof of reference correctness"})
    approved_ids = review.get("approved_mutation_ids")
    _require(type(approved_ids) is list and len(set(approved_ids)) == len(approved_ids)
             and set(approved_ids) <= {m["id"] for m in proposal["mutations"]}, "invalid/missing approved mutation IDs")
    excluded_ids = {m["id"] for m in proposal["mutations"]} - set(approved_ids)
    by_id = {r["id"]: r for r in mutation_results}
    _require(len(by_id) == len(mutation_results)
             and set(by_id) == set(approved_ids), "mutation result coverage mismatch")
    accepted, rejected, assertions = [], [], []
    constructors = {"set": set, "frozenset": frozenset, "list": list, "tuple": tuple, "sorted": sorted}
    for mutation in proposal["mutations"]:
        if mutation["id"] in excluded_ids:
            rejected.append({"id": mutation["id"], "reason": "input_domain_review_exclusion",
                             "review_reason": review.get("mutation_exclusion_reasons", {}).get(
                                 mutation["id"], "not independently approved")})
            continue
        result = by_id[mutation["id"]]
        _require(not result.get("infrastructure_error") and result.get("error_kind") not in ("infrastructure", "invalid_task")
                 and result.get("reference_sha256") == reference_sha256
                 and result.get("proposal_sha256") == proposal["sha256"]
                 and result.get("evaluator_source_hashes") == original_result["evaluator_source_hashes"]
                 and result.get("sandbox_id"), "mutation infrastructure/identity failure")
        output = result.get("output")
        if type(output) is not dict or output.get("ok") is not True or "value" not in output:
            rejected.append({"id": mutation["id"], "reason": "reference_call_or_encoding_error"})
            continue
        try:
            actual = decode_reference_value(output["value"])
            for projection in mutation["projections"]:
                actual = constructors[projection](actual)
            # No mapping subclass coercion: authoritative expectations must be
            # losslessly representable by the original v1 literal grammar.
            expected = encode_value(actual)
            original_case = task["cases"][mutation["source_case_index"]]
            if expected[0] != original_case["expected"][0]:
                raise ValueError("reference_expected_type_changed")
            args, kwargs = decode_value(mutation["args"]), decode_value(mutation["kwargs"])
            call = task["entry_point"] + '(' + ', '.join(
                [_literal_text(a) for a in args] + [f'{key}={_literal_text(value)}' for key, value in sorted(kwargs.items())]) + ')'
            for projection in mutation["projections"]:
                call = f'{projection}({call})'
            assertion = f'assert {call} == {_literal_text(decode_value(expected))}'
            # Static parse/type roundtrip, never eval/exec this assertion.
            case = convert_mbpp_tests([assertion], task["entry_point"])["cases"][0]
            _require(all(case[k] == mutation[k] for k in ("args", "kwargs", "projections"))
                     and case["expected"] == expected, "literal roundtrip changed call")
        except (ValueError, TypeError, OverflowError, RecursionError):
            rejected.append({"id": mutation["id"], "reason": "unsupported_or_type_changed_reference_value"})
            continue
        assertions.append(assertion)
        accepted.append({"id": mutation["id"], "expected": expected, "source_case_index": mutation["source_case_index"]})
    augmented = None
    if len(accepted) >= MIN_ADDITIONAL_CASES:
        augmented = deepcopy(dict(task))
        challenges = list(task.get("challenge_test_list", [])) + assertions
        augmented.update(convert_mbpp_tests(task["test_list"], task["entry_point"], challenge_test_list=challenges))
        augmented["challenge_test_list"] = challenges
        _require(augmented["cases"][:len(task["cases"])] == task["cases"], "original case prefix changed")
        augmented["metadata"].pop("task_sha256", None)
        augmented["metadata"]["verified_data"] = {"version": VERSION, "original_task_sha256": digest(task),
            "proposal_sha256": proposal["sha256"], "reference_sha256": reference_sha256,
            "review_sha256": digest(review), "original_case_count": len(task["cases"]),
            "additional_case_count": len(accepted), "reference_derived": True,
            "reference_correctness_proven": False}
    return _sealed({"version": VERSION, "task_id": task["id"], "task_sha256": digest(task),
        "proposal": deepcopy(dict(proposal)), "reference_sha256": reference_sha256,
        "original_result": deepcopy(dict(original_result)), "mutation_results": deepcopy(mutation_results),
        "review": deepcopy(dict(review)), "accepted": accepted, "rejected": rejected,
        "eligible": augmented is not None, "task": augmented,
        "interpretation": "reference-derived augmentation, not proof of reference correctness"})


def freeze_verified_dataset(selection: Mapping, audits: Iterable[Mapping]) -> dict:
    """Pure finalization gate; controller must persist this hash before generation.

    Revalidate complete remote audit evidence for the prospectively frozen bounded
    pool; take first eligible tasks in its per-split order. No candidate outcomes
    participate. Fail closed if counts/four-category coverage cannot be satisfied.
    """
    _check_hash(selection, "selection")
    _require(selection.get("stage") == "proposed" and selection.get("version") == VERSION, "wrong selection stage")
    records = list(audits)
    by_id = {a["task_id"]: a for a in records}
    pool = audit_pool(selection)
    _require(len(by_id) == len(records) == len(pool)
             and set(by_id) == {t["id"] for t in pool}, "audit coverage mismatch")
    tasks, audit_hashes, excluded = [], {}, []
    for original in pool:
        saved = by_id[original["id"]]
        _check_hash(saved, "audit")
        checked = audit_reference_task(original, saved["proposal"], reference_sha256=saved["reference_sha256"],
            original_result=saved["original_result"], mutation_results=saved["mutation_results"], review=saved["review"])
        _require(checked == saved, f"changed reference evidence: {original['id']}")
        if saved["eligible"]:
            if sum(t["split"] == original["split"] for t in tasks) < selection["requested_counts"][original["split"]]:
                tasks.append(deepcopy(saved["task"]))
        else:
            excluded.append({"id": original["id"], "accepted_additional_cases": len(saved["accepted"]),
                             "reasons": sorted({r['reason'] for r in saved['rejected']})})
        audit_hashes[original["id"]] = saved["sha256"]
    _require(dict(Counter(t["split"] for t in tasks)) == selection["requested_counts"], "final split counts changed")
    for split in ("train", "dev"):
        _require({t["category"] for t in tasks if t["split"] == split} == set(CATEGORIES), "final four-category gate failed")
    return _sealed({"version": VERSION, "stage": "frozen_reference_audited",
        "selection_sha256": selection["sha256"], "audit_sha256": audit_hashes,
        "audit_exclusions": excluded,
        "tasks": tasks, "split_counts": deepcopy(selection["requested_counts"]),
        "split_sha256": {s: digest([t for t in tasks if t["split"] == s]) for s in ("train", "dev")},
        "sealed_final": deepcopy(selection["sealed_final"]),
        "reused_development_ids": sorted(t["id"] for t in tasks if t["split"] == "dev"
                                         and t["metadata"]["coding_data"]["previous_exposure"] == "development"),
        "category_counts": {s: dict(Counter(t["category"] for t in tasks if t["split"] == s))
                            for s in ("train", "dev")},
        "ready_for_generation": True, "ready_for_training": False,
        "interpretation": "reference-derived tests; labels still require independently verified candidate outputs; no held-out family claim"})
