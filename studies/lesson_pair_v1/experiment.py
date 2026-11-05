"""Preflight, run or replay the exploratory MBPP-only two-student experiment."""
import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys

from rsi import repair_study as repair
from rsi.budget import Budget
from rsi.mbpp_verification import convert_mbpp_task
from rsi.mbpp_verification_v2 import verify_mbpp_candidate
from rsi.verification import extract_code
from rsilab import digest
from rsilab.dataset_io import file_sha256
from rsilab.project import Workspace
from rsilab.providers.modal import ModalBackend
from rsilab.providers.portable_modal_v3 import create_modal_workers, validate_request
from rsilab.workflow import VerifiedCollector
from studies.lesson_selection_v1.audit import verified_reports
from studies.lesson_selection_v1.screen_validation import EXTRA

ROOT = repair.ROOT
HERE = Path("studies/lesson_pair_v1")
PLAN = HERE / "plan.json"
STUDY = "lesson-pair-v1"
ARMS = {"a": "723", "b": "811"}
AMOUNT = 3


def check(ok, message):
    if not ok:
        raise ValueError(message)


def diagnostic_task():
    pool = json.loads((ROOT / "data/mbpp/pools-full-seed42.json").read_text())
    task = next(t for t in pool["pools"]["dev"] if t["id"] == "mbpp-full-575")
    lead, _, signature = task["prompt"].split("\n\n")
    task["prompt"] = lead + "\n\nReturn the Nth integer in the inclusive interval [L,R] that is not a multiple of A, in ascending order. A is at least 2, L is positive, and the interval contains at least N such integers. N is one-based.\n\n" + signature
    task["challenge_test_list"] = list(task["challenge_test_list"]) + [
        f"assert {task['entry_point']}{args} == {expected}" for args, expected in EXTRA[575]]
    task["category"] = "numeric"
    return convert_mbpp_task(task)


def build():
    ws = Workspace(ROOT)
    history = repair.RepairStudy(ws)
    probe = history.load_probe()
    base = history.completed("baseline")
    history.evaluation_scores(base)
    prior_plan, paired, _ = verified_reports()
    replay = subprocess.run([sys.executable, "-B", "-m", "studies.lesson_selection_v1.dry_run"],
                            cwd=ROOT, text=True, check=True, capture_output=True, timeout=90)
    bundles = json.loads(replay.stdout)["bundles"]
    labels = {r["task_id"]: r for r in paired["teachers"]["learned"]["arms"]["repair"]["selected"]}
    tasks = [t for t in history.evaluation["tasks"] if t["id"].startswith("mbpp-")]
    check(len(tasks) == 8, "Historical MBPP development set changed")
    tasks = tasks + [diagnostic_task()] + history.retention
    examples, arm_details = {}, {}
    for arm, option in ARMS.items():
        slots = bundles[option]["slots"]
        rows = [labels[s["id"]] for s in slots]
        check([r["code_sha256"] for r in rows] == [s["code_sha256"] for s in slots], "Label changed")
        examples[arm] = [{k: r[k] for k in ("prompt", "completion", "verified")} for r in rows]
        accounting = repair.training_accounting(prior_plan, examples[arm])
        check(accounting["dataset_supervised_tokens"] == bundles[option]["supervised_tokens_per_pass"],
              "Tokenizer total differs")
        validate_request("train", {**prior_plan["model"], **repair.TRAIN, "examples": examples[arm],
                                   "run_id": "preflight"}, repair.worker_config(prior_plan))
        arm_details[arm] = {"bundle_sha256": bundles[option]["bundle_sha256"], "task_ids": [s["id"] for s in slots],
                            "examples_sha256": digest(examples[arm]), "tokens": accounting}
    check(len(tasks) == 25 and len({t["id"] for t in tasks}) == 25 and all(t["id"].startswith("mbpp-full-") for t in tasks),
          "Evaluation coverage differs")
    check(not {s["id"] for b in bundles.values() for s in b["slots"]} & {t["id"] for t in tasks}, "Lesson/evaluation overlap")
    # Match old prompt bytes/position on every reused item. No base score is assigned to 575.
    for i, task in enumerate(tasks):
        if i != 8:
            check(task == base["baseline"][i]["task"], "Historical baseline task or position differs")
    rates = ws.read_json("config/budget.json")["rates_per_second"]
    cost = (2 * (1800 + 600 + 15) * (rates["L40S"] + 2 * rates["cpu_core"] + 16 * rates["memory_gib"])
            + 25 * 30 * (.125 * rates["sandbox_cpu_core"] + .5 * rates["sandbox_memory_gib"]))
    check(cost < AMOUNT, "Bounded compute exceeds stage reservation")
    files = [HERE / "experiment.py", HERE / "README.md", Path("studies/lesson_selection_v1/dry_run.py"),
             Path("studies/lesson_selection_v1/screen_validation.py"), Path("studies/lesson_selection_v1/audit.py"),
             Path("studies/lesson_selection_v1/audit.json")]
    plan = {"study": STUDY, "status": "exploratory", "historical_plan": prior_plan["sha256"],
            "probe": [probe["run_id"], digest(probe)], "baseline": [base["run_id"], digest(base)],
            "paired_data_sha256": paired["sha256"], "model": prior_plan["model"], "training": repair.TRAIN,
            "generation": repair.GEN, "arms": arm_details, "arm_order": ["a", "b"], "reservation_per_arm": AMOUNT,
            "max_gpu_calls_per_arm": 2, "max_direct_compute_usd_per_arm": round(cost, 6),
            "evaluation_ids": [t["id"] for t in tasks], "evaluation_sha256": digest(tasks),
            "source_files": {str(p): file_sha256(ROOT / p) for p in files}, "promotion_allowed": False}
    plan["sha256"] = digest(plan)
    return plan, history, tasks, examples


class PairBudget(Budget):
    def __init__(self, root, stage):
        super().__init__(root)
        self.stage = stage

    def _read(self):
        policy, ledger = super()._read()
        existing = [r for r in ledger["reservations"] if r["stage"].startswith(STUDY + "-")]
        check(self.stage in {STUDY + "-a", STUDY + "-b"} and self.stage not in {r["stage"] for r in existing},
              "Unknown or previously attempted arm")
        if self.stage == STUDY + "-a":
            check(not existing, "Unexpected reservation before arm A")
        else:
            check(len(existing) == 1 and existing[0]["stage"] == STUDY + "-a" and existing[0]["status"] == "completed",
                  "Need completed arm A")
        remaining = policy["project_cap"] - policy["overhead_reserve"] - sum(r["reserved_usd"] for r in ledger["reservations"])
        check(remaining >= (6 if self.stage.endswith("-a") else 3), "Insufficient budget for complete pair")
        return policy, ledger


class PairWorkspace(Workspace):
    def reserve(self, name, requested_usd=AMOUNT):
        check(requested_usd == AMOUNT, "Wrong stage amount")
        self._budget()
        return PairBudget(self.root, name).reserve(name, requested_usd)


def export_checkpoint(ws, report):
    import modal
    result = report["training"]
    volume = modal.Volume.from_name("open-rsi-artifacts")
    root = Path("artifacts") / STUDY / report["run_id"]
    inventory = {}
    for label in ("adapter", "checkpoint"):
        path = PurePosixPath(result[label + "_path"])
        parent = PurePosixPath("/artifacts/adapters") / report["run_id"]
        check(path.is_relative_to(parent) and ".." not in path.parts, "Unexpected checkpoint path")
        relative = path.relative_to("/artifacts")
        for entry in volume.iterdir("/" + str(relative)):
            if int(entry.type) != 1:
                continue
            child = PurePosixPath(entry.path.lstrip("/")).relative_to(relative)
            check(len(child.parts) == 1 and child.name not in ("", ".", ".."), "Unsafe artifact name")
            name = f"{label}/{child.name}"
            target = ws.path(root / name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as out:
                for chunk in volume.read_file(entry.path):
                    out.write(chunk)
            inventory[name] = file_sha256(target)
    report["export"] = {"path": str(root), "files": inventory}
    ws.persist(report)


def check_training(ws, plan, report, arm, examples, packages):
    result = report["training"]
    request = {**plan["model"], **repair.TRAIN, "run_id": report["run_id"], "examples": examples}
    call = report["remote_calls"][0]
    check(call["operation"] == "train" and call["request_sha256"] == digest(request)
          and call["result"] == result and call["status"] == "completed" and call["call_id"], "Training evidence differs")
    check(all(result[k] == v for k, v in {**plan["model"], **repair.TRAIN}.items()) and
          result["status"] == "completed" and result["steps_completed"] == 16 and result["examples_count"] == 8
          and result["lora_rank"] == 8 and result["quantization"] == "nf4-double-bfloat16"
          and result["gpu_name"] == "NVIDIA L40S" and result["packages"] == packages
          and result["portable_worker"] == repair.worker_identity(plan)
          and result["supervised_tokens"] == plan["arms"][arm]["tokens"]["dataset_supervised_tokens"],
          "Runtime, training or token controls differ")


def check_export(ws, report, examples):
    record = report["export"]
    root = Path("artifacts") / STUDY / report["run_id"]
    check(record["path"] == str(root), "Export path differs")
    for name, expected in record["files"].items():
        check(file_sha256(ws.path(root / name)) == expected, "Exported file changed")
    complete = ws.read_json(root / "checkpoint/complete.json")
    check(complete["step"] == 16 and {"training_state.pt", "adapter_model.safetensors", "metadata.json", "adapter_config.json"} <= set(complete["sha256"]),
          "Checkpoint incomplete")
    for name, sha in complete["sha256"].items():
        check(record["files"]["checkpoint/" + name] == sha, "Checkpoint identity differs")
    metadata = ws.read_json(root / "checkpoint/metadata.json")
    check(metadata["examples"] == examples and metadata["fingerprint"] == report["training"]["dataset_sha256"] and
          report["training"]["adapter_sha256"] == record["files"]["adapter/adapter_model.safetensors"] ==
          complete["sha256"]["adapter_model.safetensors"], "Detached checkpoint/adapter")


def scores(ws, plan, history, tasks, examples, arm, report):
    check(report["plan_sha256"] == plan["sha256"] and report["stage"] == STUDY + "-" + arm, "Arm/plan mismatch")
    check_training(ws, plan, report, arm, examples[arm], history.packages)
    check_export(ws, report, examples[arm])
    settings = repair.settings(plan, "evaluation", report["training"]["adapter_path"], report["training"]["adapter_sha256"])
    records, _ = repair.verify_returned(report, plan, "evaluation", tasks, repair.prompt_list(tasks), settings,
                                        history.packages, history.manifests)
    return {row["task"]["id"]: row["verification"]["passed"] for row in records}


def completed(ws, arm):
    paths = list(ws.path("runs").glob(f"*-{STUDY}-{arm}-*/report.json"))
    check(len(paths) == 1, "Need exactly one completed run for arm " + arm)
    r = ws.load_report(paths[0].parent.name)
    check(r["evidence_sha256"] == repair.report_evidence_hash(r), "Report evidence changed")
    entries = [e for e in ws.read_json("budget/ledger.json")["reservations"] if e["stage"] == STUDY + "-" + arm]
    check(len(entries) == 1 and entries[0]["status"] == "completed" and entries[0]["reserved_usd"] == AMOUNT
          and entries[0]["id"] == r["budget_reservation"] and entries[0]["details"]["run_id"] == r["run_id"],
          "Ledger and run disagree")
    return r


def run(ws, plan, history, tasks, examples, arm):
    with ws.lock(STUDY):
        check(ws.read_json(PLAN) == plan and not list(ws.path("runs").glob(f"*-{STUDY}-{arm}-*/report.json")),
              "Plan changed or arm already attempted")
        if arm == "b":
            scores(ws, plan, history, tasks, examples, "a", completed(ws, "a"))
        with ws.stage(STUDY + "-" + arm, requested_usd=AMOUNT, source_hashes=plan["source_files"],
                      report_fields=("plan_sha256", "evidence_sha256", "usage", "metrics", "export"),
                      metric_keys=("tasks", "pass_count", "output_tokens", "input_tokens"),
                      upload_paths=(str(PLAN),), tracking_mode="online") as (report, tracking):
            report["plan_sha256"] = plan["sha256"]
            ws.persist(report)
            with repair.stage_deadline(5400):
                tracking.upload_json(str(PLAN), artifact_name=report["run_id"] + "-plan", artifact_type="study-input")
                workers = create_modal_workers(repair.worker_config(plan))
                check(workers.provenance == repair.worker_identity(plan), "Worker changed")
                with workers.app.run():
                    report["modal_app_id"] = workers.app.app_id
                    ws.persist(report)
                    backend = ModalBackend(generate_function=workers.generate, train_function=workers.train,
                                           report=report, persist=ws.persist, max_calls=2)
                    report["training"] = backend.train({**plan["model"], **repair.TRAIN, "run_id": report["run_id"],
                                                        "examples": examples[arm]})
                    ws.persist(report)
                    check_training(ws, plan, report, arm, examples[arm], history.packages)
                    export_checkpoint(ws, report)
                    check_export(ws, report, examples[arm])
                    def verify(code, task):
                        raw = verify_mbpp_candidate(code, task, workers.app)
                        return repair.score_result(history.manifests.get(task["id"]), task, raw)
                    engine = VerifiedCollector(backend=backend, verify=verify, extract_code=extract_code,
                                               report=report, persist=ws.persist)
                    cfg = repair.settings(plan, "evaluation", report["training"]["adapter_path"], report["training"]["adapter_sha256"])
                    engine.collect(tasks, settings=cfg, key="evaluation")
                    scores(ws, plan, history, tasks, examples, arm, report)
                repair.metrics(report, tracking, ws.read_json("config/budget.json")["rates_per_second"])
                report["evidence_sha256"] = repair.report_evidence_hash(report)
                ws.persist(report)
        print(completed(ws, arm)["run_id"])


def main():
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("action", choices=("freeze", "preflight", "arm-a", "arm-b", "report"))
    action = arg.parse_args().action
    ws = PairWorkspace(ROOT)
    plan, history, tasks, examples = build()
    if action == "freeze" and not ws.path(PLAN).exists():
        ws.write_json(PLAN, plan)
    check(ws.read_json(PLAN) == plan, "Preregistered plan or source no longer matches")
    if action in ("freeze", "preflight"):
        print(json.dumps({"sha256": plan["sha256"], "cost_bound_per_arm": plan["max_direct_compute_usd_per_arm"],
                          "evaluation_tasks": len(tasks), "arm_examples": [len(examples[a]) for a in ARMS]}))
    elif action.startswith("arm-"):
        run(ws, plan, history, tasks, examples, action[-1])
    else:
        arm_scores = {a: scores(ws, plan, history, tasks, examples, a, completed(ws, a)) for a in ARMS}
        baseline = history.completed("baseline")
        base = {row["task"]["id"]: row["verification"]["passed"] for row in baseline["baseline"] if row["task"]["id"].startswith("mbpp-")}
        output = {"plan_sha256": plan["sha256"], "runs": {a: completed(ws,a)["run_id"] for a in ARMS},
                  "arms": arm_scores, "base_reused": base, "promoted": False, "rsi_established": False}
        for group, subset in (("exposed_development", tasks[:8]), ("retention", tasks[9:])):
            ids = [t["id"] for t in subset]
            views = {k: {i: v[i] for i in ids} for k, v in {"base": base, **arm_scores}.items()}
            output[group] = {name: repair.compare_passes(views[x], views[y]) for name, x, y in
                             (("b_vs_a", "a", "b"), ("a_vs_base", "base", "a"), ("b_vs_base", "base", "b"))}
        output["unused_task_575"] = {a: arm_scores[a]["mbpp-full-575"] for a in ARMS}
        repair.save_once(ws, f"artifacts/{STUDY}/comparison.json", output)
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
