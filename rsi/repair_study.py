"""Run or replay the independently frozen repair-v1 study on the project SSD."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import random
import signal
import subprocess

from rsi.budget import Budget
from rsi.datasets import SOURCE_HASHES
from rsi.mbpp_verification_v2 import evaluator_source_hashes, score_mbpp_outputs, verify_mbpp_candidate
from rsi.verification import extract_code
from rsilab import digest
from rsilab.dataset_io import file_sha256
from rsilab.learning import _leak_keys, _outcome
from rsilab.project import Workspace
from rsilab.providers.modal import ModalBackend
from rsilab.providers.portable_modal_v3 import (
    PortableModalConfig, create_modal_workers, resource_inventory, validate_request,
)
from rsilab.successor import inference_request_sha256
from rsilab.task_contracts import score_task_contract_outputs
from rsilab.workflow import VerifiedCollector, check_verification

ROOT = Path("/Volumes/DevSSDWD/openbmb/rsi")
STUDY = "repair-v1"
PREFIX = STUDY + "-"
PLAN = "studies/repair_v1/plan.json"
SELECTED = "data/repair-v1/selected"
COHORT = SELECTED + "/cohort.json"
PRIOR = "data/task-contracts-v1/prior-exposure.json"
HISTORY = "studies/successor_recovery_v3/plan.json"
PARENT_RUN = "20261104T143454Z-verified-sft-v1-train-evaluate-42-73116f4e"
ROLES = ("original", "learned")
RESERVATIONS = {"worker-probe": 1, "baseline": 4, "teacher-original": 5, "teacher-learned": 5,
                "child-original": 5, "child-learned": 5}
MAX_CALLS = {"worker-probe": 0, "baseline": 1, "teacher-original": 3, "teacher-learned": 3,
             "child-original": 2, "child-learned": 2}
GEN = {"seed": 42, "temperature": 0.0, "max_new_tokens": 512, "max_input_tokens": 2048}
SAMPLE = {**GEN, "seed": 31415, "temperature": 0.7}
TRAIN = {"seed": 42, "learning_rate": 2e-5, "gradient_accumulation": 4,
         "max_length": 2048, "max_steps": 16}
# Stage timeouts include provisioning and verification. Worker and sandbox
# timeouts also apply independently if the local process is lost.
WALL_SECONDS = {"worker-probe": 900, "baseline": 2700, "teacher-original": 5400,
                "teacher-learned": 5400, "child-original": 5400, "child-learned": 5400}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sources():
    """Source byte hashes for the main chat's plan freeze."""
    files = set()
    for directory in ("rsilab", "rsi"):
        files.update(p.relative_to(ROOT) for p in (ROOT / directory).rglob("*.py"))
    files.update(p.relative_to(ROOT) for p in (ROOT / "rsilab/resources").iterdir()
                 if p.suffix in {".txt", ".json"})
    files.update(map(Path, ("config/budget.json", "pyproject.toml")))
    return {str(p): file_sha256(ROOT / p) for p in sorted(files)}


def frozen_bindings():
    """Read-only inputs for assembling the preregistration (main owns its write)."""
    ws = Workspace(ROOT)
    old = ws.read_json(HISTORY)
    original = {"agent_id": "original-parent", **old["model"],
                "tokenizer_revision": old["model"]["revision"], "adapter_sha256": None,
                "parent_agent_sha256": None}
    learned = {**original, "agent_id": "experimental-verified-sft-42",
               "adapter_sha256": old["learned_adapter_sha256"], "parent_agent_sha256": digest(original)}
    prior_run = ws.load_report(PARENT_RUN)
    adapter_file = ws.path(prior_run["export"]["path"]) / "adapter/adapter_model.safetensors"
    require(prior_run["training"]["adapter_path"] == old["learned_adapter_path"]
            and file_sha256(adapter_file) == learned["adapter_sha256"], "Historical teacher bytes changed")
    compact = ws.read_json("studies/successor_recovery_v3/protocol.json")
    check_seal(compact, "Historical retention registry")
    retention = ws.read_json("data/successor-recovery-v3/audited-dataset.json")["retention"]
    require(digest(retention) == compact["registry_hashes"]["retention"], "Historical retention changed")
    for name, expected in SOURCE_HASHES.items():
        if name.startswith("full/") and name.endswith(".parquet"):
            require(file_sha256(ws.path(Path("data/mbpp/raw") / name)) == expected,
                    "Pinned source file differs: " + name)
    data_files = [ws.path(COHORT), *(ws.path(f"{SELECTED}/{role}-manifest.json") for role in ("train", "evaluation"))]
    return {"input_file_hashes": {str(p.relative_to(ROOT)): file_sha256(p) for p in data_files},
            "retention_sha256": digest(retention),
            "study": STUDY, "source_hashes": sources(), "cohort_sha256": digest(ws.read_json(COHORT)),
            "prior_exposure_sha256": digest(ws.read_json(PRIOR)), "model": old["model"],
            "teachers": {"original": original, "learned": learned},
            "learned_adapter_path": old["learned_adapter_path"], "reservations": RESERVATIONS,
            "max_gpu_calls": MAX_CALLS, "stage_wall_seconds": WALL_SECONDS,
            "generation": GEN, "sampling": SAMPLE, "training": TRAIN}


def validate_reservation(policy, ledger, stage, amount):
    require(stage.startswith(PREFIX) and RESERVATIONS.get(stage[len(PREFIX):]) == amount,
            "Stage or dollar amount differs from preregistration")
    rows = ledger["reservations"]
    require(not any(row["stage"] == stage for row in rows), "Stage already reserved or attempted")
    spent = sum(r["reserved_usd"] for r in rows if r["stage"].startswith("repair-"))
    require(spent + amount <= 25, "Repair family cap exceeded")
    remaining = policy["project_cap"] - policy["overhead_reserve"] - sum(r["reserved_usd"] for r in rows)
    require(remaining - amount >= 6, "Six dollars must remain unallocated")


class RepairWorkspace(Workspace):
    def reserve(self, name, requested_usd=5):
        # Budget.reserve reads the policy/ledger under its existing project-wide
        # exclusive lock. Check both study-specific rules inside that transaction.
        class GuardedBudget(Budget):
            def _read(self):
                policy, ledger = super()._read()
                validate_reservation(policy, ledger, name, requested_usd)
                return policy, ledger

        self._budget()  # Validate paths and upper bounds as in Workspace.reserve.
        return GuardedBudget(self.root).reserve(name, requested_usd)


@contextmanager
def stage_deadline(seconds):
    def expired(signum, frame):
        raise TimeoutError("Preregistered stage wall-time bound exceeded")
    prior = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, prior)


def settings(plan, kind, adapter_path=None, adapter_sha256=None):
    return {**plan["model"], **(SAMPLE if kind in {"repair", "sample"} else GEN),
            "adapter_path": adapter_path, "adapter_sha256": adapter_sha256}


def worker_config(plan):
    return PortableModalConfig(app_name="open-rsi-repair-v1", volume_name="open-rsi-artifacts",
                               model_id=plan["model"]["model_id"], model_revision=plan["model"]["revision"])


def worker_identity(plan):
    cfg = worker_config(plan)
    return {"worker": resource_inventory(), "config": cfg.to_dict(), "config_sha256": cfg.sha256}



def verify_probe_result(plan, result):
    identity = worker_identity(plan)
    cfg = identity["config"]
    require(result["status"] == "completed" and result["portable_worker"] == identity
            and result.get("mounted_volume_is_dir") is True and result.get("gpu_requested") is False
            and result["volume_mount"] == cfg["volume_mount"]
            and result["python_version"].startswith(cfg["python_version"] + "."), "Invalid CPU probe")
    installed = {k.lower().replace("_", "-"): v for k, v in result["packages"].items()}
    for pin in identity["worker"]["requirements"]:
        package, version = pin.split("==")
        require(installed.get(package.lower().replace("_", "-")) == version, "Worker package pin differs: " + package)


def prompt_list(tasks, prompts=None):
    return [{"id": t["id"], "prompt": prompts[t["id"]] if prompts is not None else t["prompt"]} for t in tasks]


def score_result(manifest, task, execution):
    """Keep native transport errors and raw V2 evidence; independently rescore typed outputs."""
    check_verification(execution)
    result = deepcopy(execution)
    if isinstance(result.get("outputs"), list):
        if manifest is not None:
            result["executor_score"] = {k: result.get(k) for k in ("passed", "count", "total", "errors", "case_diagnostics")}
            result.update(score_task_contract_outputs(manifest, task["id"], result["outputs"],
                                                      expected_sha256=manifest["sha256"]))
            if not result["passed"]:
                result["error_kind"] = "candidate_execution"
    return result


def verify_returned(report, plan, key, tasks, prompts, expected_settings, packages, manifests):
    """Bind every row to its actual provider call, request and isolated evidence."""
    rows = report[key]
    require(len(rows) == len(tasks) == len(prompts) and len(report[key + "_batches"]) == 1,
            "Require one complete ordered batch")
    batch = report[key + "_batches"][0]
    response = batch["generation"]
    request = {**expected_settings, "prompts": prompts}
    require(batch["settings"] == expected_settings and batch["request_sha256"] == digest(request),
            "Durable generation request differs")
    # Identical sample/repair requests are possible for an all-passing batch.
    # Bind by occurrence/order, never by unique payload hash alone.
    position = {"first": 0, "sample": 1, "repair": 2, "baseline": 0, "evaluation": 1}[key]
    calls = report["remote_calls"]
    require(len({c["call_id"] for c in calls}) == len(calls)
            and all(c["index"] == i and c["status"] == "completed" for i, c in enumerate(calls)),
            "Missing or reused physical provider call")
    call = calls[position]
    require(call["operation"] == "generate" and call["status"] == "completed" and call["call_id"]
            and call["request_sha256"] == digest(request) and call["result"] == response,
            "Durable provider result differs")
    require(response["status"] == "completed" and response["portable_worker"] == worker_identity(plan)
            and response["gpu_name"] == "NVIDIA L40S" and response["packages"] == packages,
            "Worker runtime differs from CPU probe")
    for field in ("seed", "temperature", "model_id", "revision", "max_new_tokens", "adapter_path", "adapter_sha256"):
        require(response.get(field) == expected_settings[field], "Returned inference setting differs: " + field)
    require(response.get("enable_thinking") is False and response["outputs"] == [row["generation"] for row in rows],
            "Raw generation outputs differ")
    verified = report[key + "_verification_0"]
    summary = report[key + "_verification_0_execution"]
    require(summary["succeeded"] and summary["records"] == verified and not summary["issues"],
            "Incomplete isolated execution summary")
    require(len(verified) == len(rows), "Incomplete verification evidence")
    records = []
    for i, (row, task, evidence) in enumerate(zip(rows, tasks, verified, strict=True)):
        manifest = manifests.get(task["id"])
        output, outcome = row["generation"], row["verification"]
        require(row["task"] == task and output["id"] == task["id"] == evidence["item_id"]
                and outcome == evidence["result"] and row["generation_settings"] == expected_settings,
                "Generation or verification row identity differs")
        require(output["hit_token_limit"] is (output["output_tokens"] == expected_settings["max_new_tokens"])
                and not output.get("hit_time_limit") and 0 < output["input_tokens"] <= expected_settings["max_input_tokens"]
                and 0 <= output["output_tokens"] <= expected_settings["max_new_tokens"],
                "Actual generation exceeds token or time limits")
        _outcome(row, evaluator={"version": "mbpp-typed-v2", "source_hashes": evaluator_source_hashes()})
        if output["hit_token_limit"]:
            require(outcome["passed"] is False and outcome["errors"] == ["generation_token_limit"],
                    "Truncated output received credit")
        else:
            require(outcome["verifier_version"] == "mbpp-typed-v2"
                    and outcome["evaluator_source_hashes"] == evaluator_source_hashes(), "Evaluator identity changed")
            if isinstance(outcome.get("outputs"), list):
                code = extract_code(output["text"])
                require(outcome["sandbox_id"] and outcome["candidate_sha256"] == hashlib.sha256(code.encode()).hexdigest()
                        and outcome["source_tests_sha256"] == task["source_tests_sha256"], "Detached sandbox result")
                actual = (score_task_contract_outputs(manifest, task["id"], outcome["outputs"])
                          if manifest else score_mbpp_outputs(outcome["outputs"], task["cases"]))
                require(all(outcome.get(k) == v for k, v in actual.items()), "Saved score differs from replay")
            else:
                require(outcome["passed"] is False and outcome["count"] == 0, "Success without isolated outputs")
        require((row.get("verified_code") == extract_code(output["text"])) if outcome["passed"]
                else "verified_code" not in row, "Verified training label differs")
        records.append({**row, "effective_seed": expected_settings["seed"] + i})
    generation = {k: expected_settings[k] for k in GEN}
    controls = {"generation": {**generation, "enable_thinking": False},
                "runtime": {"hardware": response["gpu_name"], "packages": packages,
                            "source_hashes": plan["source_hashes"], "precision": "nf4-double-quant-bfloat16-sdpa"},
                "evaluator": {"version": "mbpp-typed-v2", "source_hashes": evaluator_source_hashes()},
                "effective_seeds": [r["effective_seed"] for r in records]}
    return records, controls


def check_seal(value, label):
    require(value.get("sha256") == digest({k: v for k, v in value.items() if k != "sha256"}),
            label + " seal changed")


def save_once(ws, path, value):
    if ws.path(path).exists():
        require(ws.read_json(path) == value, "Existing evidence differs: " + path)
    else:
        ws.write_json(path, value)


def compare_passes(parent, candidate):
    require(list(parent) == list(candidate) and bool(parent), "Evaluation order or coverage differs")
    gains = [key for key in parent if candidate[key] and not parent[key]]
    losses = [key for key in parent if parent[key] and not candidate[key]]
    return {"parent_passes": sum(parent.values()), "candidate_passes": sum(candidate.values()),
            "total": len(parent), "gains": gains, "losses": losses, "net": len(gains) - len(losses)}


def validate_cohort(plan, cohort, training, evaluation):
    check_seal(cohort, "Selected cohort")
    require(cohort["study"] == STUDY and cohort["prior_exposure_sha256"] == plan["prior_exposure_sha256"],
            "Selected cohort exposure or study identity differs")
    checks = cohort["reference_checks"]
    expected_order = []
    for role, manifest in (("train", training), ("evaluation", evaluation)):
        check_seal(manifest, role + " task contract")
        require(manifest["sha256"] == plan["reviewed_manifest_sha256"][role]
                and cohort["manifests"][role]["sha256"] == manifest["sha256"]
                and cohort["manifests"][role]["path"] == f"{SELECTED}/{role}-manifest.json"
                and cohort[role] == manifest["tasks"], "Manifest differs from selected " + role + " cohort or seal")
        expected_order.extend((role, task, manifest) for task in manifest["tasks"])
    ids = {task["id"] for _, task, _ in expected_order}
    require(not ids & {"apps-train-4211", "mbpp-full-829", "mbpp-full-840"}
            and not {"mbpp-full-805", "apps-train-4189"} <= ids,
            "Selected task IDs violate the independent semantic quarantine")
    require(len(checks) == len(expected_order), "Reference calibration coverage differs")
    for row, (role, task, manifest) in zip(checks, expected_order, strict=True):
        ref_sha = row["reference_sha256"]
        require((row["id"], row["role"], row["task_sha256"]) == (task["id"], role, digest(task))
                and isinstance(ref_sha, str) and len(ref_sha) == 64 and all(c in "0123456789abcdef" for c in ref_sha),
                "Reference identity differs from selected task")
        score = score_task_contract_outputs(manifest, task["id"], row["outputs"],
                                           expected_sha256=plan["reviewed_manifest_sha256"][role])
        require(score["passed"] and score["boundary_total"] > 0, "Reference calibration failed: " + task["id"])


class RepairStudy:
    def __init__(self, ws):
        self.ws = ws
        self.plan = ws.read_json(PLAN)
        check_seal(self.plan, "Preregistration")
        for key, value in frozen_bindings().items():
            require(self.plan.get(key) == value, "Frozen binding differs: " + key)
        for name, sha in self.plan["design_files_sha256"].items():
            require(file_sha256(ws.path(name)) == sha, "Frozen design file changed: " + name)
        self.cohort = ws.read_json(COHORT)
        self.train = ws.read_json(f"{SELECTED}/train-manifest.json")
        self.evaluation = ws.read_json(f"{SELECTED}/evaluation-manifest.json")
        validate_cohort(self.plan, self.cohort, self.train, self.evaluation)
        self.retention = ws.read_json("data/successor-recovery-v3/audited-dataset.json")["retention"]
        self.manifests = {}
        prior = ws.read_json(PRIOR)
        require(len(prior) == 284 and len(self.retention) == 16, "Historical registry coverage changed")
        require(24 <= len(self.train["tasks"]) <= 32 and 8 <= len(self.evaluation["tasks"]) <= 48
                and sum(t["category"] == "text" for t in self.train["tasks"]) >= 6
                and {"text", "numeric", "collections"} <= {t["category"] for t in self.train["tasks"]},
                "Infeasible training or held-out evaluation size")
        excluded = set().union(*(_leak_keys(t) for t in prior + self.retention))
        for manifest in (self.train, self.evaluation):
            require(manifest["prompts"] == prompt_list(manifest["tasks"]), "Public projection differs")
            for task in manifest["tasks"]:
                keys = _leak_keys(task)
                require(task["split"] == "train" and task["metadata"]["source_split"] == "train"
                        and not keys & excluded, "Fresh task/split overlap: " + task["id"])
                excluded.update(keys)
                score_task_contract_outputs(manifest, task["id"], None, expected_sha256=manifest["sha256"])
                self.manifests[task["id"]] = manifest
        cfg = worker_config(self.plan)
        for tasks, kind in ((self.train["tasks"], "first"), (self.train["tasks"], "sample"),
                            (self.evaluation_tasks(), "baseline")):
            validate_request("generate", {**settings(self.plan, kind), "prompts": prompt_list(tasks)}, cfg)
        self.packages = None

    def evaluation_tasks(self):
        return self.evaluation["tasks"] + self.retention

    def reports(self, name):
        return [self.ws.load_report(p.parent.name, require_completed=False)
                for p in sorted(self.ws.path("runs").glob("*-" + PREFIX + name + "-*/report.json"))]

    def completed(self, name):
        rows = self.reports(name)
        require(len(rows) == 1 and rows[0]["status"] == "completed", "Need one completed stage: " + name)
        report = rows[0]
        entries = [r for r in self.ws.read_json("budget/ledger.json")["reservations"] if r["stage"] == PREFIX + name]
        require(len(entries) == 1 and entries[0]["status"] == "completed"
                and entries[0]["id"] == report["budget_reservation"] and entries[0]["reserved_usd"] == RESERVATIONS[name]
                and entries[0]["details"]["run_id"] == report["run_id"], "Stage ledger disagrees: " + name)
        require(report["stage"] == PREFIX + name and report["plan_sha256"] == self.plan["sha256"]
                and report["provenance"]["source_hashes"] == self.plan["source_hashes"], "Stage identity differs")
        require(report["evidence_sha256"] == report_evidence_hash(report), "Stage evidence changed: " + name)
        for run_id, sha in report["dependencies"].items():
            require(digest(self.ws.load_report(run_id)) == sha, "Saved parent report changed: " + run_id)
        return report

    def load_probe(self):
        report = self.completed("worker-probe")
        result = report["worker_probe"]
        require(len(report["remote_calls"]) == 1 and report["remote_calls"][0]["result"] == result
                and report["remote_calls"][0]["status"] == "completed" and report["remote_calls"][0]["call_id"]
                and report["remote_calls"][0]["request_sha256"] == digest(worker_identity(self.plan)),
                "CPU probe call evidence differs")
        verify_probe_result(self.plan, result)
        self.packages = result["packages"]
        return report

    def run_probe(self, report, workers):
        entry = {"index": 0, "operation": "probe", "request_sha256": digest(workers.provenance),
                 "status": "submitting"}
        report["remote_calls"] = [entry]
        self.ws.persist(report)
        call = None
        try:
            call = workers.probe.spawn()
            entry.update(call_id=call.object_id, status="running")
            self.ws.persist(report)
            result = call.get(timeout=300)
            verify_probe_result(self.plan, result)
            report["worker_probe"] = result
            entry.update(status="completed", result=result)
        except BaseException as error:
            entry.update(status="failed", error_type=type(error).__name__)
            if call is not None:
                try:
                    call.cancel(terminate_containers=True)
                except Exception as cancel_error:
                    entry["cancel_error_type"] = type(cancel_error).__name__
            raise
        finally:
            self.ws.persist(report)

    def collect(self, report, engine, key, tasks, cfg, prompts=None):
        public = prompt_list(tasks, prompts)
        report.setdefault("public_requests", {})[key] = public
        self.ws.persist(report)
        engine.collect(tasks, settings=cfg, key=key, prompts=prompts)
        return self.records(report, key, tasks, cfg, public)

    def records(self, report, key, tasks, cfg, public):
        require(report["public_requests"][key] == public, "Actual prompts differ from replay")
        return verify_returned(report, self.plan, key, tasks, public, cfg, self.packages, self.manifests)

    def teacher_collections(self, report, role, engine=None):
        from rsilab.paired_repair import second_prompts
        if engine is None:
            require(len(report["remote_calls"]) == 3, "Teacher requires three physical calls")
        teacher = self.plan["teachers"][role]
        adapter = self.plan["learned_adapter_path"] if role == "learned" else None
        tasks = self.train["tasks"]
        branches = {}
        collections = {}
        for key in ("first", "sample", "repair"):
            prompts = branches.get(key)
            cfg = settings(self.plan, key, adapter, teacher["adapter_sha256"])
            public = prompt_list(tasks, prompts)
            rows, controls = (self.collect(report, engine, key, tasks, cfg, prompts) if engine
                              else self.records(report, key, tasks, cfg, public))
            collections[key] = {"controls": controls, "records": rows, "prompts": public,
                                "request_sha256": inference_request_sha256(teacher, controls, public)}
            if key == "first":
                branches = second_prompts(self.train, rows)
        return {"run_id": report["run_id"], "teacher": teacher, "manifest_sha256": self.train["sha256"],
                "collections": collections}

    def paired_report(self):
        from rsilab.paired_repair import audit_paired_repair
        runs = {role: self.teacher_collections(self.completed("teacher-" + role), role) for role in ROLES}
        controls = runs["original"]["collections"]
        return audit_paired_repair(self.train, self.plan["teachers"],
                                   {"first": controls["first"]["controls"], "second": controls["sample"]["controls"]},
                                   runs["original"], runs["learned"])

    def evaluation_scores(self, report):
        key = "baseline" if report["stage"] == PREFIX + "baseline" else "evaluation"
        training = report.get("training", {})
        cfg = settings(self.plan, key, training.get("adapter_path"), training.get("adapter_sha256"))
        tasks = self.evaluation_tasks()
        rows, controls = self.records(report, key, tasks, cfg, prompt_list(tasks))
        count = len(self.evaluation["tasks"])
        return {k: {r["task"]["id"]: r["verification"]["passed"] for r in subset}
                for k, subset in (("fresh", rows[:count]), ("retention", rows[count:]))}, controls

    def prerequisites(self, name):
        parents = []
        prepared = None
        if name != "worker-probe":
            parents.append(self.load_probe())
        if name.startswith(("teacher-", "child-")):
            baseline = self.completed("baseline")
            self.evaluation_scores(baseline)
            parents.append(baseline)
        if name == "teacher-learned":
            original = self.completed("teacher-original")
            self.teacher_collections(original, "original")
            parents.append(original)
        if name.startswith("child-"):
            parents.extend(self.completed("teacher-" + r) for r in ROLES)
            if name == "child-learned":
                other = self.completed("child-original")
                self.check_export(other)
                self.evaluation_scores(other)
                parents.append(other)
            probe = self.paired_report()
            require(probe["child_gate"]["eligible"], "Paired verified-data gate failed")
            examples = probe["child_gate"]["examples"]
            require(all(len(examples[role]) == 16 for role in ROLES), "Equal-count child gate failed")
            # Prove *both* children can be tokenized before launching either.
            prepared = {r: (examples[r], training_accounting(self.plan, examples[r])) for r in ROLES}
        return parents, prepared

    def run(self, name):
        with self.ws.lock(STUDY):
            require(self.ws.read_json(PLAN) == self.plan, "Preregistration changed while awaiting stage lock")
            for path, sha in self.plan["input_file_hashes"].items():
                require(file_sha256(self.ws.path(path)) == sha, "Input changed while awaiting stage lock: " + path)
            require(not self.reports(name), "Stage already has a report")
            validate_reservation(self.ws.read_json("config/budget.json"), self.ws.read_json("budget/ledger.json"),
                                 PREFIX + name, RESERVATIONS[name])
            archived = subprocess.check_output(["git", "show", "HEAD:" + PLAN], cwd=ROOT)
            require(json.loads(archived) == self.plan, "Preregistration must be committed before launch")
            parents, prepared = self.prerequisites(name)
            with self.ws.stage(PREFIX + name, requested_usd=RESERVATIONS[name],
                               source_hashes=self.plan["source_hashes"], report_fields=(
                                   "plan_sha256", "dependencies", "evidence_sha256", "usage", "metrics",
                                   "examples_sha256", "export", "selected_example"),
                               metric_keys=("pass_count", "tasks", "input_tokens", "output_tokens"),
                               upload_paths=(PLAN,), tracking_mode="online") as (report, tracking):
                report.update(plan_sha256=self.plan["sha256"],
                              dependencies={r["run_id"]: digest(r) for r in parents})
                self.ws.persist(report)
                with stage_deadline(WALL_SECONDS[name]):
                    for run_id in list(report["dependencies"]) + ([PARENT_RUN] if name == "teacher-learned" else []):
                        tracking.use_artifact(f"{tracking.entity}/{tracking.project}/{run_id}:latest", type="pilot-report")
                    tracking.upload_json(PLAN, artifact_name=report["run_id"] + "-plan", artifact_type="study-input")
                    workers = create_modal_workers(worker_config(self.plan))
                    require(workers.provenance == worker_identity(self.plan), "Worker build differs")
                    report["portable_worker"] = workers.provenance
                    self.ws.persist(report)
                    with workers.app.run():
                        report["modal_app_id"] = workers.app.app_id
                        self.ws.persist(report)
                        if name == "worker-probe":
                            self.run_probe(report, workers)
                        else:
                            backend = ModalBackend(generate_function=workers.generate, train_function=workers.train,
                                                   report=report, persist=self.ws.persist, max_calls=MAX_CALLS[name])
                            def verify(code, task):
                                raw = verify_mbpp_candidate(code, task, workers.app)
                                return score_result(self.manifests.get(task["id"]), task, raw)
                            engine = VerifiedCollector(backend=backend, verify=verify, extract_code=extract_code,
                                                       report=report, persist=self.ws.persist)
                            if name == "baseline":
                                self.collect(report, engine, "baseline", self.evaluation_tasks(), settings(self.plan, "baseline"))
                                self.evaluation_scores(report)
                            elif name.startswith("teacher-"):
                                self.teacher_collections(report, name.split("-")[1], engine)
                            else:
                                self.child(report, engine, backend, *prepared[name.split("-")[1]])
                    metrics(report, tracking, self.ws.read_json("config/budget.json")["rates_per_second"])
                    report["evidence_sha256"] = report_evidence_hash(report)
                    self.ws.persist(report)
            return self.completed(name)["run_id"]

    def child(self, report, engine, backend, examples, accounting):
        report.update(examples_sha256=digest(examples), token_accounting=accounting)
        request = {**self.plan["model"], **TRAIN, "run_id": report["run_id"], "examples": examples}
        validate_request("train", request, worker_config(self.plan))
        result = backend.train(request)
        report["training"] = result
        self.ws.persist(report)
        self.check_training(report, examples, accounting)
        self.export_checkpoint(report)
        self.collect(report, engine, "evaluation", self.evaluation_tasks(),
                     settings(self.plan, "evaluation", result["adapter_path"], result["adapter_sha256"]))
        self.evaluation_scores(report)

    def check_training(self, report, examples, accounting):
        result = report["training"]
        request = {**self.plan["model"], **TRAIN, "run_id": report["run_id"], "examples": examples}
        call = report["remote_calls"][0]
        require(call["operation"] == "train" and call["request_sha256"] == digest(request)
                and call["result"] == result and call["status"] == "completed" and call["call_id"],
                "Child training call differs from verified labels or fresh initialization")
        require(result["status"] == "completed" and result["steps_completed"] == TRAIN["max_steps"]
                and result["examples_count"] == len(examples) == 16 and result["lora_rank"] == 8
                and result["supervised_tokens"] == accounting["dataset_supervised_tokens"]
                and result["quantization"] == "nf4-double-bfloat16", "Child training accounting differs")
        require(all(result[k] == v for k, v in {**self.plan["model"], **TRAIN}.items())
                and result["portable_worker"] == worker_identity(self.plan) and result["gpu_name"] == "NVIDIA L40S"
                and result["packages"] == self.packages, "Child training controls differ")
        require(report["examples_sha256"] == digest(examples) and report["token_accounting"] == accounting,
                "Saved training examples or token totals differ")

    def export_checkpoint(self, report):
        import modal
        volume = modal.Volume.from_name(worker_config(self.plan).volume_name)
        base = self.ws.path(Path("artifacts") / STUDY / report["run_id"])
        inventory = {}
        for label in ("adapter", "checkpoint"):
            worker_path = PurePosixPath(report["training"][label + "_path"])
            directory = PurePosixPath("/artifacts/adapters") / report["run_id"]
            require(worker_path.is_relative_to(directory) and ".." not in worker_path.parts, "Unsafe export path")
            remote = worker_path.relative_to("/artifacts")
            for entry in volume.iterdir("/" + str(remote)):
                if int(entry.type) != 1:
                    continue
                rel = PurePosixPath(entry.path.lstrip("/")).relative_to(remote)
                require(len(rel.parts) == 1 and rel.parts[0] != "..", "Unsafe remote file")
                target = self.ws.path(base / label / rel.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    for chunk in volume.read_file(entry.path):
                        stream.write(chunk)
                inventory[label + "/" + rel.name] = file_sha256(target)
        report["export"] = {"path": str(base.relative_to(self.ws.root)), "files": inventory}
        self.check_export(report)
        self.ws.persist(report)

    def check_export(self, report):
        exported, result = report["export"], report["training"]
        base = self.ws.path(exported["path"])
        require(base == self.ws.path(Path("artifacts") / STUDY / report["run_id"]), "Export run identity differs")
        for relative, sha in exported["files"].items():
            require(file_sha256(self.ws.path(base / relative)) == sha, "Exported training bytes changed")
        complete = self.ws.read_json(base / "checkpoint/complete.json")
        metadata = self.ws.read_json(base / "checkpoint/metadata.json")
        require(complete["step"] == TRAIN["max_steps"]
                and {"training_state.pt", "metadata.json", "adapter_config.json", "adapter_model.safetensors"}
                <= set(complete["sha256"]), "Incomplete training-state checkpoint")
        for file, sha in complete["sha256"].items():
            require(exported["files"]["checkpoint/" + file] == sha, "Checkpoint bytes differ from manifest")
        lora = self.ws.read_json(base / "adapter/adapter_config.json")
        require(lora["r"] == 8 and lora["lora_alpha"] == 16 and lora["lora_dropout"] == 0.0
                and lora["bias"] == "none"
                and set(lora["target_modules"]) == {"q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"},
                "Exported LoRA controls differ")
        require(exported["files"]["adapter/adapter_model.safetensors"] == result["adapter_sha256"]
                and complete["sha256"]["adapter_model.safetensors"] == result["adapter_sha256"]
                and digest(metadata["examples"]) == report["examples_sha256"]
                and metadata["fingerprint"] == result["dataset_sha256"], "Detached adapter or checkpoint data")
        for field in ("model_id", "revision", "seed", "learning_rate", "gradient_accumulation", "max_length"):
            require(metadata[field] == result[field], "Checkpoint training control differs: " + field)

    def report(self):
        stages = {name: self.reports(name) for name in RESERVATIONS}
        if any(len(stages[n]) != 1 or stages[n][0]["status"] != "completed"
               for n in ("worker-probe", "baseline", "teacher-original", "teacher-learned")):
            return {"study": STUDY, "plan_sha256": self.plan["sha256"], "status": "incomplete",
                    "stages": {k: [{"run_id": r["run_id"], "status": r["status"],
                                    "wall_seconds": r.get("wall_seconds"), "error_type": r.get("error_type")}
                                   for r in rows] for k, rows in stages.items()},
                    "selected_agent_id": "original-parent", "promoted": False, "sustained_rsi": False}
        self.load_probe()
        baseline = self.completed("baseline")
        base_scores, base_controls = self.evaluation_scores(baseline)
        teachers = [self.completed("teacher-" + role) for role in ROLES]
        paired = self.paired_report()
        save_once(self.ws, "artifacts/repair-v1/paired.json", paired)
        gate = paired["child_gate"]
        summary = {"study": STUDY, "plan_sha256": self.plan["sha256"], "paired_sha256": paired["sha256"],
                   "child_gate": {k: v for k, v in gate.items() if k != "examples"}, "baseline": base_scores,
                   "teachers": {}, "selected_agent_id": "original-parent", "promoted": False, "sustained_rsi": False}
        for role, report in zip(ROLES, teachers, strict=True):
            arm = paired["teachers"][role]
            summary["teachers"][role] = {"run_id": report["run_id"], "usage": report["usage"],
                                         "paired_unique": arm["paired_unique"], "paired_solved": arm["paired_solved"],
                                         "recoveries_by_category": arm["recoveries_by_category"],
                                         "yields": {k: v["unique_count"] for k, v in arm["arms"].items()},
                                         "category_yields": {k: v["categories"] for k, v in arm["arms"].items()}}
        for role, arm in paired["teachers"].items():
            by_source = {}
            for task in self.train["tasks"]:
                group = by_source.setdefault(task["metadata"]["dataset"], {"task_ids": [], "sample": 0, "repair": 0})
                group["task_ids"].append(task["id"])
                for branch in ("sample", "repair"):
                    if any(r["task_id"] == task["id"] for r in arm["arms"][branch]["selected"]):
                        group[branch] += 1
            summary["teachers"][role]["unique_yield_by_source"] = by_source
        summary["paired_teachers_unique"] = paired["paired_teachers_unique"]
        summary["fresh_ids_by_source"] = {}
        for task in self.evaluation["tasks"]:
            summary["fresh_ids_by_source"].setdefault(task["metadata"]["dataset"], []).append(task["id"])
        reports = {r: self.reports("child-" + r) for r in ROLES}
        if not gate["eligible"]:
            require(all(not rows for rows in reports.values()), "Unexpected child after gate failed")
            summary["status"] = "teacher_data_gate_failed"
        elif any(len(rows) != 1 or rows[0]["status"] != "completed" for rows in reports.values()):
            summary["status"] = "awaiting_paired_children"
            summary["child_status"] = {r: [row["status"] for row in rows] for r, rows in reports.items()}
            return summary
        else:
            scores = {}
            summary["children"] = {}
            for role in ROLES:
                report = self.completed("child-" + role)
                examples = gate["examples"][role]
                self.check_training(report, examples, training_accounting(self.plan, examples))
                self.check_export(report)
                scores[role], controls = self.evaluation_scores(report)
                require(controls == base_controls, "Child and starting evaluation controls differ")
                summary["children"][role] = {"run_id": report["run_id"], "usage": report["usage"],
                                             "token_accounting": report["token_accounting"], "scores": scores[role],
                                             "vs_start": {k: compare_passes(base_scores[k], scores[role][k])
                                                          for k in base_scores}}
            for role, other in (("learned", "original"), ("original", "learned")):
                comparison = {k: compare_passes(scores[other][k], scores[role][k]) for k in scores[role]}
                child = summary["children"][role]
                child["vs_other"] = comparison
                child["promising"] = all(c["fresh"]["net"] >= 3 and not c["retention"]["losses"]
                                         for c in (comparison, child["vs_start"]))
            summary["status"] = "paired_children_completed"
        run_reports = [self.completed("worker-probe"), baseline, *teachers]
        if gate["eligible"]:
            run_reports += [self.completed("child-" + r) for r in ROLES]
        summary["stages"] = {r["stage"]: {"run_id": r["run_id"], "wall_seconds": r["wall_seconds"],
                                          "usage": r["usage"], "report_sha256": digest(r)}
                             for r in run_reports}
        summary["budget"] = run_reports[-1]["budget"]
        save_once(self.ws, "artifacts/repair-v1/summary.json", summary)
        return summary


def report_evidence_hash(report):
    # Runtime finalization adds status, time, budget and W&B fields after the stage body.
    managed = {"evidence_sha256", "status", "wall_seconds", "budget", "wandb_url", "runtime_errors", "error_type"}
    return digest({k: v for k, v in report.items() if k not in managed})


def training_accounting(plan, examples):
    from transformers import AutoTokenizer
    from rsilab.resources.gpu_worker_v1 import _encode_example
    model = plan["model"]
    tokenizer = AutoTokenizer.from_pretrained(model["model_id"], revision=model["revision"], token=False,
                                              local_files_only=True, cache_dir=str(ROOT / ".cache/huggingface/hub"))
    rows = [_encode_example(tokenizer, example, TRAIN["max_length"]) for example in examples]
    random.Random(TRAIN["seed"]).shuffle(rows)
    consumed = [rows[i % len(rows)] for i in range(TRAIN["max_steps"] * TRAIN["gradient_accumulation"])]
    return {"processed_tokens": sum(len(r["input_ids"]) for r in consumed),
            "supervised_tokens": sum(sum(label != -100 for label in r["labels"]) for r in consumed),
            "dataset_supervised_tokens": sum(sum(label != -100 for label in r["labels"]) for r in rows)}


def metrics(report, tracking, rates):
    rows = [r for key in ("baseline", "first", "sample", "repair", "evaluation") for r in report.get(key, [])]
    usage = {field: sum(r["generation"][field] for r in rows) for field in ("input_tokens", "output_tokens")}
    gpu = sum(call["result"]["elapsed_seconds"] for call in report["remote_calls"] if call["operation"] != "probe")
    cpu = report.get("worker_probe", {}).get("elapsed_seconds", 0)
    sandbox = sum(r["verification"].get("duration_seconds", 0) for r in rows if r["verification"].get("sandbox_id"))
    estimate = (gpu * (rates["L40S"] + 2 * rates["cpu_core"] + 16 * rates["memory_gib"])
                + cpu * (2 * rates["cpu_core"] + 2 * rates["memory_gib"])
                + sandbox * (0.125 * rates["sandbox_cpu_core"] + 0.5 * rates["sandbox_memory_gib"]))
    report["usage"] = {**usage, "gpu_seconds": gpu, "sandbox_wall_seconds": sandbox, "cpu_probe_seconds": cpu,
                       "estimated_execution_cost_usd": estimate, "invoice_total_usd": None}
    report["metrics"] = {**usage, "pass_count": sum(r["verification"]["passed"] for r in rows), "tasks": len(rows)}
    if rows and "first" in report:
        row = rows[0]
        report["selected_example"] = {"task_id": row["task"]["id"], "prompt": row["task"]["prompt"],
                                      "completion": row["generation"]["text"], "passed": row["verification"]["passed"]}
    tracking.log(report["metrics"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("draft-plan", "preflight", "report", *RESERVATIONS))
    args = parser.parse_args(argv)
    require(Path.cwd().resolve() == ROOT, "Run from the canonical RSI SSD workspace")
    ws = RepairWorkspace(ROOT).load_env()
    if args.command == "draft-plan":
        value = frozen_bindings()
    else:
        study = RepairStudy(ws)
        if args.command == "preflight":
            value = {"plan_sha256": study.plan["sha256"], "train_count": len(study.train["tasks"]),
                     "evaluation_count": len(study.evaluation["tasks"]), "retention_count": len(study.retention)}
        elif args.command == "report":
            value = study.report()
        else:
            value = {"run_id": study.run(args.command)}
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()
