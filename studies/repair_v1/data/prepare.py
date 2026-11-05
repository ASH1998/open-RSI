"""Replay the frozen MBPP-only selection, boundary cases, and reference calibration."""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

from rsi.datasets import DATASET_ID, REVISION, SOURCE_HASHES, model_input
from rsi.mbpp_verification import convert_mbpp_task, encode_value
from rsilab import digest
from rsilab.coding_data import DIAGNOSTIC_IDS, MANUAL_DUPLICATE_IDS, PINNED_POOL_SHA256
from rsilab.dataset_io import file_sha256
from rsilab.learning import _leak_keys
from rsilab.task_contracts import apply_task_contracts, replay_task_contracts, score_task_contract_outputs
from studies.repair_v1.data.reviews import CONTRACTS, QUARANTINE, VALIDATION_REVIEW

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path("studies/repair_v1/data")
OUT = Path("data/repair-v1")
HISTORY = Path("data/task-contracts-v1/prior-exposure.json")
EXPOSURE_SHA = "05ae698aa0cc4a68d8c8e86eec35af3282e329f659e731bc515bf134fe3ac199"
DOMAIN_SHA = "fa63e01a700c143e54181a2dbde872508458c10b69c439d0f31e29fd7af53a00"
# The two roles stay stable on replay and are separate from the native split field.
HOLDOUT = {626, 644, 679, 717, 780, 915, 938, 950}
ROLES = ("train", "evaluation")


def read(path):
    return json.loads((ROOT / path).read_text())


def identities(task):
    return _leak_keys(task) | {("family", task["family"])}


def inventory():
    pool = read("data/mbpp/pools-full-seed42.json")
    prior = read(HISTORY)
    if (digest({k: v for k, v in pool.items() if k != "manifest_sha256"}) != PINNED_POOL_SHA256
            or pool["manifest_sha256"] != PINNED_POOL_SHA256 or pool["source_sha256"] != SOURCE_HASHES
            or pool["revision"] != REVISION or pool["config"] != "full"):
        raise ValueError("Importer pool seal differs from the pinned source")
    if (digest(prior) != EXPOSURE_SHA or len(prior) != 284 or len({r["id"] for r in prior}) != 284):
        raise ValueError("Expected all 284 pinned exposure records")
    excluded_review = read("studies/successor_v1/domain-review.json")
    if digest(excluded_review) != DOMAIN_SHA:
        raise ValueError("Historical domain review changed")
    history_keys = set().union(*(identities(t) for t in prior))
    clusters = {c["id"]: c for c in pool["duplicate_clusters"]}
    counts = {}
    selected = {}
    dispositions = []
    excluded_refs = {r["task_id"]: r["notes"] for r in excluded_review["excluded_reviews"]}
    # Prior v1 excluded 664 because all generic mutations violated its even-input
    # domain. Its source tests are consistent; this study supplies only even inputs.
    excepted = {"mbpp-full-664"}
    for split, source_split in (("train", "train"), ("dev", "validation")):
        counts[split] = Counter()
        for task in pool["pools"][split]:
            meta = task["metadata"]
            cluster = clusters[task["family"]]
            if (cluster["source_splits"] != [source_split] or meta["source_id"] != min(cluster["source_ids"])
                    or meta["source_split"] != source_split or meta["revision"] != REVISION):
                raise ValueError("Invalid native partition or duplicate representative")
            if identities(task) & history_keys:
                continue
            counts[split]["unexposed"] += 1
            if task["id"] in MANUAL_DUPLICATE_IDS | DIAGNOSTIC_IDS:
                continue
            try:
                compiled = convert_mbpp_task(task)
            except ValueError:
                continue
            counts[split]["after_conversion_and_exclusions"] += 1
            number = meta["source_id"]
            if number not in CONTRACTS:
                reason = (VALIDATION_REVIEW.get(number) if split == "dev" else QUARANTINE.get(number))
                reason = reason or excluded_refs.get(task["id"])
                if not reason:
                    raise ValueError(f"Missing disposition for {task['id']}")
                dispositions.append({"id": task["id"], "native_split": source_split, "reason": reason})
                continue
            if split != "train" or number in selected:
                raise ValueError("Duplicate or wrong-source selection")
            if task["id"] in set(excluded_refs) - excepted:
                raise ValueError("Known failed domain or duplicate")
            compiled["category"] = CONTRACTS[number][0]
            if number in {644, 832}:
                # Original references use a parameter named input; reading that
                # name violates the candidate policy. Only positional calls exist.
                # Preserve the raw import record identity and exact required edit.
                if any(c["kwargs"] != ["dict", []] for c in compiled["cases"]):
                    raise ValueError("Cannot rename a parameter used by a native keyword call")
                original_prompt = compiled["prompt"]
                prefix, declaration = original_prompt.rsplit("\n", 1)
                if not declaration.startswith("def " + compiled["entry_point"] + "(input"):
                    raise ValueError("Unexpected source signature")
                new_declaration = declaration.replace("(input", "(values", 1)
                adaptation = {"native_compiled_sha256": digest(compiled), "original_signature": declaration,
                              "adapted_signature": new_declaration}
                compiled["prompt"] = prefix + "\n" + new_declaration
                compiled["metadata"]["repair_v1_signature"] = adaptation
            selected[number] = compiled
    if set(selected) != set(CONTRACTS) or not HOLDOUT < set(selected):
        raise ValueError("Missing or misplaced reviewed selection")
    occupied = history_keys.copy()
    for task in selected.values():
        keys = identities(task)
        if occupied & keys:
            raise ValueError("Detected duplicate across the cohort or history")
        occupied.update(keys)
    return selected, counts, sorted(dispositions, key=lambda r: r["id"])


def review(source):
    number = source["metadata"]["source_id"]
    category, prompt, cases = CONTRACTS[number]
    boundaries = [{"name": name, "call": source["entry_point"] + "(" + ", ".join(map(repr, args)) + ")",
                   "expected": encode_value(expected)} for name, args, expected in cases]
    return {"task_id": source["id"], "source_sha256": digest(source), "clarified_prompt": prompt,
            "review_note": f"{category}; independent hand-specified boundaries: " + ", ".join(b["name"] for b in boundaries),
            "boundaries": boundaries}


def build():
    sources, screen_counts, dispositions = inventory()
    contracts = {}
    original_train, train_reviews = [], []
    requests = []
    for role in ROLES:
        ids = sorted(HOLDOUT if role == "evaluation" else set(sources) - HOLDOUT)
        originals = [sources[n] for n in ids]
        reviews = [review(t) for t in originals]
        if role == "train":
            original_train, train_reviews = originals, reviews
        manifest = apply_task_contracts(originals, reviews)
        replay_task_contracts(originals, reviews, manifest, expected_sha256=manifest["sha256"])
        contracts[role] = manifest
        for task, projection in zip(manifest["tasks"], manifest["prompts"], strict=True):
            if projection != {"id": task["id"], "prompt": model_input(task)["prompt"]}:
                raise ValueError("Generation projection differs")
            meta = task["metadata"]
            requests.append({"source_id": meta["source_id"], "source_row_sha256": meta["source_row_sha256"],
                             "entry_point": task["entry_point"],
                             "inputs": [{k: c[k] for k in ("args", "kwargs")} for c in task["cases"]]})
    raw = subprocess.run([sys.executable, "-I", "-B", str(ROOT / STUDY / "reference.py")],
                         input=json.dumps(sorted(requests, key=lambda r: r["source_id"])),
                         text=True, capture_output=True, timeout=50, cwd=ROOT,
                         env={"TMPDIR": str(ROOT / ".cache/tmp"), "HOME": str(ROOT / "work/repair-v1-data")})
    if raw.returncode:
        raise ValueError("Pinned-reference worker failed: " + raw.stderr[-1500:])
    records = json.loads(raw.stdout)
    by_id = {r["source_id"]: r for r in records}
    checked = []
    reference_checks = []
    for role, manifest in contracts.items():
        for task in manifest["tasks"]:
            n = task["metadata"]["source_id"]
            reference = by_id[n]
            score = score_task_contract_outputs(manifest, task["id"], reference["outputs"],
                                                expected_sha256=manifest["sha256"])
            if not score["passed"]:
                raise ValueError(f"Reference disagreement {n}: {score['errors']}")
            if any(c["projections"] or digest(out["value"]) != digest(c["expected"])
                   for out, c in zip(reference["outputs"], task["cases"], strict=True)):
                raise ValueError(f"Inherited or boundary case differs in typed value for {n}")
            reference_checks.append({"id": task["id"], "role": role, "task_sha256": digest(task),
                                     "reference_sha256": reference["reference_sha256"], "outputs": reference["outputs"]})
            checked.append({"id": task["id"], "role": role, "category": task["category"],
                            "task_sha256": digest(task), "reference_sha256": reference["reference_sha256"],
                            "source_cases": score["source_total"], "boundaries": score["boundary_total"]})
    links = {role: {"path": str(OUT / f"{role}-manifest.json"), "sha256": contracts[role]["sha256"]}
             for role in ROLES}
    cohort = {role: contracts[role]["tasks"] for role in ROLES}
    cohort.update(manifests=links, reference_checks=reference_checks, dataset=DATASET_ID, revision=REVISION, source_split="train",
                  prior_exposure_sha256=EXPOSURE_SHA, study="repair-v1")
    shortfalls = {name: max(0, target - count) for name, target, count in (
        ("train_tasks", 24, len(cohort["train"])),
        ("train_text", 6, sum(t["category"] == "text" for t in cohort["train"])),
        ("evaluation_tasks", 8, len(cohort["evaluation"])),
    )}
    cohort["native_only_eligible"] = not any(shortfalls.values())
    cohort["shortfalls"] = shortfalls
    cohort["sha256"] = digest(cohort)
    counts = {role: dict(Counter(t["category"] for t in cohort[role])) for role in ROLES}
    evidence = {
        "study": "repair-v1", "data_revision": REVISION, "dataset": DATASET_ID, "configuration": "full",
        "source_split": "train", "train_parquet_sha256": SOURCE_HASHES["full/train-00000-of-00001.parquet"],
        "pool_sha256": PINNED_POOL_SHA256, "prior_exposure_path": str(HISTORY), "prior_exposure_count": 284,
        "prior_exposure_sha256": EXPOSURE_SHA, "domain_review_sha256": DOMAIN_SHA,
        "native_only_eligible": cohort["native_only_eligible"], "shortfalls": shortfalls,
        "screen_counts": screen_counts, "screened_not_selected": dispositions, "counts": counts, "manifests": links, "cohort_sha256": cohort["sha256"],
        "reference_outputs_sha256": digest(records), "passed_cases": sum(t["source_cases"] + t["boundaries"] for t in checked),
        "new_boundaries": sum(t["boundaries"] for t in checked), "selected": checked,
        "train_sources_sha256": digest(original_train), "train_reviews_sha256": digest(train_reviews),
        "manual_duplicate_ids": sorted(MANUAL_DUPLICATE_IDS), "diagnostic_ids": sorted(DIAGNOSTIC_IDS),
        "source_files": {str(p): file_sha256(ROOT / p) for p in
                         [STUDY / "prepare.py", STUDY / "reference.py", STUDY / "reviews.py",
                          Path("rsilab/task_contracts.py"), Path("rsi/mbpp_verification.py"),
                          Path("rsi/mbpp_verification_v2.py")]},
    }
    outputs = {STUDY / "selection.json": evidence, OUT / "reference-outputs.json": records, OUT / "cohort.json": cohort}
    outputs[OUT / "native-train-sources.json"] = original_train
    outputs[OUT / "native-train-reviews.json"] = train_reviews
    for role in ROLES:
        outputs[Path(links[role]["path"])] = contracts[role]
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", action="store_true", help="write any missing evidence after verifying all existing outputs")
    args = parser.parse_args()
    outputs = build()
    for path, value in outputs.items():
        if (ROOT / path).exists():
            if digest(read(path)) != digest(value):
                raise ValueError(f"Existing sealed evidence differs: {path}")
        elif not args.freeze:
            raise FileNotFoundError(path)
    for path, value in outputs.items():
        target = ROOT / path
        if args.freeze and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x") as out:
                json.dump(value, out, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
                out.write("\n")
    evidence = outputs[STUDY / "selection.json"]
    print(json.dumps({k: evidence[k] for k in ("counts", "passed_cases", "new_boundaries", "cohort_sha256")}))


if __name__ == "__main__":
    main()
