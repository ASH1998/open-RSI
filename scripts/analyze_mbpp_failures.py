"""Read-only inventory of saved MBPP outcomes; never execute candidate code.

This script uses only the standard library. It does not import the controller,
load credentials, call providers, rescore outputs, or modify original reports.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def classify(record):
    result = record["verification"]
    if result["passed"]:
        return "passed"
    kind = result.get("error_kind")
    if kind == "generation_limit":
        return "generation_limit"
    if kind in ("candidate_policy", "invalid_candidate"):
        return kind
    if any(output.get("ok") is not True for output in result.get("outputs", [])):
        return "runtime_or_codec_error"
    if result["errors"] and all(e.endswith(":wrong_output") for e in result["errors"]):
        return "wrong_output_only"
    return "other_failure"


def syntax_status(text):
    """Parse text only. This is diagnostic, not a replacement extraction policy."""
    source = text.strip()
    if "</think>" in source:
        source = source.rsplit("</think>", 1)[1].strip()
    if "```" in source:
        blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", source, re.DOTALL)
        if len(blocks) != 1 or source.count("```") != 2:
            return {"status": "ambiguous_or_incomplete_fence"}
        source = blocks[0].strip()
    try:
        ast.parse(source)
        return {"status": "parseable"}
    except SyntaxError as exc:
        return {"status": "syntax_error", "line": exc.lineno, "reason": exc.msg}


def inventory(root=ROOT):
    root = Path(root)
    reports = [(path, json.loads(path.read_text()))
               for path in sorted((root / "runs").glob("*mbpp*/report.json"))]
    train_seeds = {r["run_id"]: r["seed"] for _, r in reports if r["stage"] == "mbpp-train"}
    models = defaultdict(list)
    details = []
    for path, report in reports:
        stage = report["stage"]
        if stage == "mbpp-baseline":
            model = "parent"
        elif stage == "mbpp-evaluate":
            model = f"seed{train_seeds[report['training_run']]}"
        elif stage == "mbpp-kaggle-verify":
            model = "kaggle"
        else:
            continue
        if report["status"] != "completed":
            raise ValueError(f"Incomplete original report: {report['run_id']}")
        for index, record in enumerate(report["records"]):
            models[model].append(record)
            task = record["task"]
            verification = record["verification"]
            text = record["generation"]["text"]
            details.append({
                "model": model, "task_id": task["id"], "split": task["split"],
                "report": str(path.relative_to(root)), "record_index": index,
                "original_passed": verification["passed"], "category": classify(record),
                "errors": verification["errors"],
                "exception_types": sorted({o["error"] for o in verification.get("outputs", [])
                                           if o.get("ok") is False and "error" in o}),
                "generation_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "candidate_sha256": verification.get("candidate_sha256"),
                "source_tests_sha256": task.get("source_tests_sha256"),
                "syntax": syntax_status(text),
            })
    for model, records in models.items():
        ids = [x["task"]["id"] for x in records]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate original records for {model}; choose a study explicitly")
    summary = {}
    for model in sorted(models):
        rows = [x for x in details if x["model"] == model]
        summary[model] = {
            "records": len(rows), "outcomes": dict(sorted(Counter(x["category"] for x in rows).items())),
            "by_split": {s: dict(sorted(Counter(x["category"] for x in rows if x["split"] == s).items()))
                         for s in sorted({x["split"] for x in rows})},
            "syntax": dict(sorted(Counter(x["syntax"]["status"] for x in rows).items())),
        }
    return {"analysis": "static_original_report_inventory", "scores_recomputed": False,
            "candidate_execution": False, "summary": summary, "records": details}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--details", action="store_true", help="Include every outcome and evidence pointer")
    parser.add_argument("--task", help="Include evidence pointers for one task ID, e.g. mbpp-full-568")
    args = parser.parse_args()
    result = inventory()
    if args.task:
        result["records"] = [r for r in result["records"] if r["task_id"] == args.task]
    elif not args.details:
        result.pop("records")
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
