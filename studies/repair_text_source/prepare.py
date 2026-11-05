"""Rebuild the eight APPS train contracts offline; --fetch retrieves only missing raw rows."""
import argparse
import hashlib
import inspect
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

from rsi.datasets import ALLOWED_IMPORTS, SEALED_DOMAIN, SOURCE_HASHES
from rsi.mbpp_verification import convert_mbpp_tests, decode_value, encode_value
from rsilab import digest
from rsilab.dataset_io import file_sha256, read_development_splits
from rsilab.learning import _leak_keys
from rsilab.task_contracts import apply_task_contracts, replay_task_contracts, score_task_contract_outputs
from studies.repair_text_source.oracles import ORACLES
from studies.repair_text_source.reviews import REVIEWS

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "studies/repair_text_source"
OUT = ROOT / "data/repair-text-source"
HISTORY_SHA = "05ae698aa0cc4a68d8c8e86eec35af3282e329f659e731bc515bf134fe3ac199"
POLICY = ("Implement the following Python function. Return concise, self-contained Python code only; "
          "no explanation or long comments. Include required imports. Only these modules are permitted: "
          + ", ".join(ALLOWED_IMPORTS) + ". Do not read stdin, print, access files, "
          "or use dynamic execution, introspection, or decorators.")


def row_bytes(spec, pin, fetch):
    path = OUT / f"train-{pin['id']}.jsonl"
    start, end = pin["start"], pin["end"]
    size = end - start + 1
    if path.exists():
        raw = path.read_bytes()
    elif fetch:
        url = f"https://huggingface.co/datasets/codeparrot/apps/resolve/{spec['revision']}/train.jsonl?offset={start}"
        request = Request(url, headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"})
        with urlopen(request, timeout=40) as stream:
            if (stream.status != 206 or stream.headers["Content-Range"] != f"bytes {start}-{end}/{spec['file_size']}"
                    or not stream.geturl().startswith("https://")):
                raise ValueError("Refusing unbounded or redirected non-HTTPS response")
            raw = stream.read(size + 1)
    else:
        raise FileNotFoundError(path)
    if (len(raw) != size or hashlib.sha256(raw).hexdigest() != pin["row_bytes_sha256"]
            or raw.count(b"\n") != 1 or not raw.endswith(b"\n")):
        raise ValueError(f"Invalid raw train row {pin['id']}")
    if not path.exists():
        with path.open("xb") as out:
            out.write(raw)
    return json.loads(raw)


def contract(spec, pin, row):
    number = pin["id"]
    if row["id"] != number or row["url"] != pin["url"] or row["difficulty"] != "introductory":
        raise ValueError("APPS source identity mismatch")
    io = json.loads(row["input_output"])
    entry = io["fn_name"]
    signature = row["starter_code"].strip()
    if not re.fullmatch(r"def " + re.escape(entry) + r"\([a-z]+(?:, [a-z]+)*\):", signature):
        raise ValueError("Unexpected APPS starter declaration")
    tests = []
    for args, result in zip(io["inputs"], io["outputs"], strict=True):
        if not isinstance(args, list) or any(type(arg) != str for arg in args) or len(result) != 1:
            raise ValueError("Unexpected native call or output envelope")
        tests.append(f"assert {entry}({', '.join(map(repr, args))}) == {result[0]!r}")
    family = "apps-kata-" + row["url"].rsplit("/", 1)[1]
    source = {
        "id": f"apps-train-{number}", "split": "train", "category": "text", "family": family,
        "prompt": f"{POLICY}\n\n{row['question'].strip()}\n\nRequired signature:\n{signature}",
        "test_list": tests, "challenge_test_list": [], "test_setup_code": "", "test_imports": [],
        "metadata": {"dataset": spec["dataset"], "revision": spec["revision"], "source_split": "train",
                     "source_id": number, "source_row_sha256": digest(row),
                     "raw_row_bytes_sha256": pin["row_bytes_sha256"], "source_url": pin["url"],
                     "cluster_id": family, "license": "MIT (APPS card); BSD-2-Clause (Codewars kata data)",
                     "attribution": f"{pin['created_at'][:4]} {pin['author']}",
                     "allowed_imports": list(ALLOWED_IMPORTS), "difficulty": row["difficulty"]},
        **convert_mbpp_tests(tests, entry),
    }
    prompt, notes, boundaries = REVIEWS[number]
    review = {
        "task_id": source["id"], "source_sha256": digest(source), "clarified_prompt": prompt,
        "review_note": notes,
        "boundaries": [{"name": name, "call": f"{entry}({', '.join(map(repr, args))})",
                        "expected": encode_value(expected)} for name, args, expected in boundaries],
    }
    return source, review


def screen(sources, manifest):
    prior = json.loads((ROOT / "data/task-contracts-v1/prior-exposure.json").read_bytes())
    if len(prior) != 284 or digest(prior) != HISTORY_SHA:
        raise ValueError("Exposure registry mismatch")
    splits = read_development_splits(ROOT / "data/mbpp/raw", source_hashes=SOURCE_HASHES,
                                    expected_counts={"train": 374, "validation": 90})
    descriptions = {row["text"].strip().casefold() for rows in splits.values() for row in rows}
    used = set().union(*(_leak_keys(task) for task in prior))
    for task, source in zip(manifest["tasks"], sources, strict=True):
        keys = _leak_keys(task) | _leak_keys(source)
        if used & keys:
            raise ValueError("Duplicate APPS or prior exposure identity")
        for prompt in (task["prompt"], source["prompt"]):
            text = prompt.split("\n\n", 1)[1].rsplit("\n\nRequired signature:", 1)[0].strip()
            if text.casefold() in descriptions or SEALED_DOMAIN.search(text):
                raise ValueError("Matched MBPP description or sealed domain")
        used.update(keys)
    return {"history_count": len(prior), "history_sha256": HISTORY_SHA,
            "mbpp_full_counts": {k: len(v) for k, v in splits.items()},
            "mbpp_files_sha256": {k: v for k, v in SOURCE_HASHES.items()
                                  if k.startswith(("full/train-", "full/validation-"))},
            "manual_semantic_review_sha256": file_sha256(STUDY / "overlap.md")}


def calibrate(manifest):
    records, scores = [], []
    for task in manifest["tasks"]:
        oracle = ORACLES[task["metadata"]["source_id"]]
        function_sha = hashlib.sha256(inspect.getsource(oracle).encode()).hexdigest()
        outputs = []
        for case in task["cases"]:
            args, kwargs = decode_value(case["args"]), decode_value(case["kwargs"])
            actual = encode_value(oracle(*args, **kwargs))
            if actual != case["expected"]:
                raise ValueError(f"Typed oracle mismatch in {task['id']} at case {case['source_test_index']}")
            outputs.append({"ok": True, "value": actual})
        score = score_task_contract_outputs(manifest, task["id"], outputs, expected_sha256=manifest["sha256"])
        if not score["passed"]:
            raise ValueError(f"Evaluator rejected oracle {task['id']}")
        records.append({"id": task["id"], "reference_sha256": function_sha, "outputs": outputs})
        scores.append({"id": task["id"], "source_id": task["metadata"]["source_id"],
                       "source_row_sha256": task["metadata"]["source_row_sha256"],
                       "derived_task_sha256": digest(task), "reference_name": oracle.__name__,
                       "reference_sha256": function_sha, "source_pass": score["source_passed_count"],
                       "boundary_pass": score["boundary_passed_count"]})
    return records, scores


def build(fetch):
    spec = json.loads((STUDY / "slice.json").read_bytes())
    if ([r["id"] for r in spec["rows"]] != list(REVIEWS) or spec["native_split"] != "train"
            or spec["path"] != "train.jsonl" or spec["dataset"] != "codeparrot/apps"):
        raise ValueError("Unexpected APPS inventory")
    sources, reviews = [], []
    for pin in spec["rows"]:
        row = row_bytes(spec, pin, fetch)
        source, review = contract(spec, pin, row)
        sources.append(source)
        reviews.append(review)
    manifest = apply_task_contracts(sources, reviews)
    replay_task_contracts(sources, reviews, manifest, expected_sha256=manifest["sha256"])
    outputs, scores = calibrate(manifest)
    artifacts = {"train-sources.json": sources, "train-reviews.json": reviews,
                 "train-manifest.json": manifest, "reference-outputs.json": outputs}
    receipt = {"kind": "APPS train contingency, independent handwritten oracle", "selection": scores,
               "rows": len(scores), "original_pass": sum(r["source_pass"] for r in scores),
               "boundary_pass": sum(r["boundary_pass"] for r in scores), "screen": screen(sources, manifest),
               "artifacts_sha256": {k: digest(v) for k, v in artifacts.items()},
               "manifest_sha256": manifest["sha256"],
               "files_sha256": {str(f.relative_to(ROOT)): file_sha256(f) for f in
                                [STUDY / name for name in ("prepare.py", "slice.json", "reviews.py", "oracles.py")]
                                + [ROOT / name for name in ("rsi/mbpp_verification.py", "rsi/mbpp_verification_v2.py",
                                                           "rsi/verification.py", "rsilab/task_contracts.py")]}}
    return {**artifacts, "validation.json": receipt}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="fetch only missing selected train rows by byte range")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    artifacts = build(args.fetch)
    for name, obj in artifacts.items():
        path = OUT / name
        if path.exists() and digest(json.loads(path.read_bytes())) != digest(obj):
            raise ValueError(f"Existing artifact differs from rebuilt result: {path}")
    for name, obj in artifacts.items():
        path = OUT / name
        if not path.exists():
            with path.open("x", encoding="utf-8") as stream:
                json.dump(obj, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
                stream.write("\n")
    print(json.dumps({k: artifacts["validation.json"][k] for k in
                      ("rows", "original_pass", "boundary_pass", "manifest_sha256")}))


if __name__ == "__main__":
    main()
