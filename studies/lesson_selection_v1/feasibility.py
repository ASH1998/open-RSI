"""Read-only go/no-go check for the proposed MBPP-only matched lesson comparison."""
import json
import subprocess
import sys

from rsilab import digest
from studies.lesson_selection_v1.audit import ROOT, check, read, verified_reports


def run_module(name):
    completed = subprocess.run([sys.executable, "-B", "-m", "studies.lesson_selection_v1." + name],
                               cwd=ROOT, text=True, capture_output=True, timeout=90)
    if completed.returncode:
        raise RuntimeError(f"{name} failed: {completed.stderr[-1200:]}")
    return json.loads(completed.stdout)


def assess():
    bundles = run_module("dry_run")
    screen = run_module("screen_validation")
    remaining = [row["id"] for row in screen if row["disposition"] == "retain_for_bounded_development"]
    plan, _, _ = verified_reports()
    policy = read(ROOT / "config/budget.json")
    ledger = read(ROOT / "budget/ledger.json")
    reserved = sum(row["reserved_usd"] for row in ledger["reservations"])
    available = policy["project_cap"] - policy["overhead_reserve"] - reserved
    # Reuse historical reservation amounts as a planning scenario for one
    # baseline and one pair. No teacher generation is required for these bundles.
    phases = {stage: plan["reservations"][stage] for stage in
              ("worker-probe", "baseline", "child-original", "child-learned")}
    reservation = sum(phases.values())
    minimum_gain = 3
    reasons = []
    if len(remaining) < minimum_gain:
        reasons.append("fresh_task_ceiling_below_proposed_net_gain")
    if reservation > available:
        reasons.append("historical_stage_reservations_exceed_available_budget")
    check(bundles["exposure_inventory"]["total"] == 317, "Exposure record differs")
    return {
        "study": "lesson-selection-v1", "stage": "offline_feasibility",
        "bundle_checks": {option: {k: v for k, v in data.items() if k != "slots"}
                          for option, data in bundles["bundles"].items()},
        "exposure_inventory": bundles["exposure_inventory"], "validation_screen": screen,
        "remaining_development_ids": remaining, "max_possible_net_fresh_gain": len(remaining),
        "proposed_min_net_fresh_gain": minimum_gain, "budget_ledger_sha256": digest(ledger),
        "reserved_jobs_usd": reserved, "overhead_usd": policy["overhead_reserve"], "available_usd": available,
        "reservation_scenario_usd": phases, "reservation_scenario_total_usd": reservation,
        "shortfall_vs_scenario_usd": max(0, reservation - available),
        "reasons": reasons, "decision": "stop" if reasons else "requires_main_chat_review",
    }


if __name__ == "__main__":
    print(json.dumps(assess(), indent=2, sort_keys=True))
