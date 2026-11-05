"""Replay the post-hoc lesson audit. Only pinned native references execute."""
import argparse
import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from rsi.mbpp_verification import encode_value
from rsilab import digest
from rsilab.dataset_io import file_sha256
from rsilab.resources.gpu_worker_v1 import _encode_example
from studies.lesson_selection_v1.review import NOTES, PROBES
from studies.repair_text_source.oracles import ORACLES

ROOT = Path(__file__).resolve().parents[2]
REPAIR = ROOT / "artifacts/repair-v1"
STUDY = Path(__file__).resolve().parent
ROLES = ("original", "learned")


def read(path):
    return json.loads(path.read_text())


def check(condition, message):
    if not condition:
        raise ValueError(message)


def verified_reports():
    results = read(ROOT / "studies/repair_v1/results.json")
    plan = read(ROOT / "studies/repair_v1/plan.json")
    paired = read(REPAIR / "paired.json")
    for record, sha in ((plan, results["plan_sha256"]), (paired, results["paired_sha256"])):
        check(record["sha256"] == sha == digest({k: v for k, v in record.items() if k != "sha256"}),
              "Frozen plan or paired evidence changed")
    reports = {}
    for role in ROLES:
        stage = results["stages"]["repair-v1-child-" + role]
        report = read(ROOT / "runs" / stage["run_id"] / "report.json")
        check(digest(report) == stage["report_sha256"], "Child report changed")
        reports[role] = report
    return plan, paired, reports


def selected_labels(role, paired, report, tokenizer):
    gate = paired["child_gate"]
    metadata_path = ROOT / report["export"]["path"] / "checkpoint/metadata.json"
    check(file_sha256(metadata_path) == report["export"]["files"]["checkpoint/metadata.json"],
          "Checkpoint metadata changed")
    examples = read(metadata_path)["examples"]
    check(examples == gate["examples"][role] and digest(examples) == report["examples_sha256"],
          "Selected examples differ from actual training data")
    pool = {r["task_id"]: r for r in paired["teachers"][role]["arms"]["repair"]["selected"]}
    labels = {}
    for task_id, example in zip(gate["selected_ids"][role], examples, strict=True):
        row = pool[task_id]
        check(example == {k: row[k] for k in ("prompt", "completion", "verified")}, "Label identity changed")
        code = row["completion"]
        code_sha = hashlib.sha256(code.encode()).hexdigest()
        check(code_sha == row["code_sha256"], "Selected code hash differs")
        encoded = _encode_example(tokenizer, example, report["training"]["max_length"])
        labels[task_id] = {
            "code_sha256": code_sha,
            "ast_sha256": digest(ast.dump(ast.parse(code), include_attributes=False)),
            "attempt": row["source"],
            "supervised_tokens": sum(x != -100 for x in encoded["labels"]),
        }
    check(sum(x["supervised_tokens"] for x in labels.values()) == report["token_accounting"]["dataset_supervised_tokens"],
          "Supervised token accounting differs")
    return labels


def calibrated_cases(selected):
    native = read(ROOT / "data/repair-v1/cohort.json")
    tasks = {t["metadata"]["source_id"]: t for role in ("train", "evaluation") for t in native[role]}
    check(set(PROBES) == set(NOTES) == {int(t.split("-")[-1]) for t in selected}, "Review coverage differs")
    requests = []
    for number, task in sorted(tasks.items()):
        inputs = [{"args": encode_value(tuple(args)), "kwargs": encode_value({})}
                  for args, _ in PROBES.get(number, [])]
        requests.append({"source_id": number, "entry_point": task["entry_point"], "inputs": inputs,
                         "source_row_sha256": task["metadata"]["source_row_sha256"]})
    worker = ROOT / "studies/repair_v1/data/reference.py"
    completed = subprocess.run([sys.executable, "-I", "-B", str(worker)], text=True,
                               input=json.dumps(requests), capture_output=True, cwd=ROOT, timeout=60,
                               env={"TMPDIR": str(ROOT / ".cache/tmp")}, check=True)
    native_outputs = {r["source_id"]: r["outputs"] for r in json.loads(completed.stdout)}
    manifest = read(ROOT / "data/repair-v1/selected/train-manifest.json")
    check(manifest["sha256"] == digest({k: v for k, v in manifest.items() if k != "sha256"}),
          "Training manifest is not sealed")
    by_id = {t["id"]: t for t in manifest["tasks"]}
    cases = {}
    for task_id in sorted(selected):
        number = int(task_id.split("-")[-1])
        probes = PROBES[number]
        if task_id.startswith("mbpp-"):
            outputs = native_outputs[number]
        else:
            outputs = [{"ok": True, "value": encode_value(ORACLES[number](*args))} for args, _ in probes]
        cases[task_id] = []
        for (args, expected), output in zip(probes, outputs, strict=True):
            encoded_args = encode_value(tuple(args))
            check(all(c["args"] != encoded_args or c["kwargs"] != encode_value({})
                      for c in by_id[task_id]["cases"]), "Diagnostic input repeats a frozen case: " + task_id)
            check(output == {"ok": True, "value": encode_value(expected)}, "Reference disagrees: " + task_id)
            cases[task_id].append({"args": encoded_args, "expected": output["value"]})
    return cases, manifest["sha256"]


def build():
    # Use the historical tokenizer offline. Never read credentials or initialize providers.
    os.environ.update(HF_HUB_OFFLINE="1", HF_HOME=str(ROOT / ".cache/huggingface"),
                      HF_HUB_DISABLE_TELEMETRY="1", XDG_CACHE_HOME=str(ROOT / ".cache"),
                      TMPDIR=str(ROOT / ".cache/tmp"))
    from transformers import AutoTokenizer

    plan, paired, reports = verified_reports()
    tokenizer = AutoTokenizer.from_pretrained(plan["model"]["model_id"], revision=plan["model"]["revision"],
                                              local_files_only=True, token=False,
                                              cache_dir=str(ROOT / ".cache/huggingface/hub"))
    arms = {role: selected_labels(role, paired, reports[role], tokenizer) for role in ROLES}
    all_ids = set(arms["original"]) | set(arms["learned"])
    cases, manifest_sha = calibrated_cases(all_ids)
    check(manifest_sha == paired["manifest_sha256"], "Review manifest differs from the teacher experiment")
    rows = []
    for task_id in sorted(all_ids):
        number = int(task_id.split("-")[-1])
        versions = {role: labels[task_id] for role, labels in arms.items() if task_id in labels}
        if len(versions) == 1:
            comparison = next(iter(versions)) + "_only"
        elif versions["original"]["ast_sha256"] == versions["learned"]["ast_sha256"]:
            comparison = "same_ast"
        else:
            comparison = "different_ast"
        rows.append({"id": task_id, "arms": versions, "comparison": comparison, "static_review": NOTES[number],
                     "reference_checked_inputs": cases[task_id]})
    return {"study": "lesson-selection-v1-offline-audit", "parent_plan_sha256": plan["sha256"],
            "paired_sha256": paired["sha256"], "comparison_counts": dict(Counter(r["comparison"] for r in rows)),
            "checkpoint_examples_sha256": {r: reports[r]["examples_sha256"] for r in ROLES},
            "token_accounting": {r: reports[r]["token_accounting"] for r in ROLES},
            "diagnostic_input_count": sum(map(len, cases.values())),
            "labels_reviewed": sum(map(len, arms.values())), "lessons": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", action="store_true", help="create the initial audit if missing")
    args = parser.parse_args()
    result = build()
    path = STUDY / "audit.json"
    if path.exists():
        check(read(path) == result, "Audit differs from saved result")
    elif args.freeze:
        with path.open("x") as out:
            out.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    else:
        raise FileNotFoundError(path)
    print(json.dumps({k: result[k] for k in ("labels_reviewed", "diagnostic_input_count", "comparison_counts")}))


if __name__ == "__main__":
    main()
