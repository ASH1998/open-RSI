"""Build two matched MBPP-only lesson bundles in memory. No jobs, scores or new labels."""
import json
import os

from rsilab import digest
from rsilab.dataset_io import file_sha256
from rsilab.resources.gpu_worker_v1 import _encode_example
from studies.lesson_selection_v1.audit import ROOT, STUDY, check, read, verified_reports


def exposure_inventory(plan):
    prior = read(ROOT / "data/task-contracts-v1/prior-exposure.json")
    cohort_path = "data/repair-v1/selected/cohort.json"
    check(file_sha256(ROOT / cohort_path) == plan["input_file_hashes"][cohort_path], "Selected cohort changed")
    cohort = read(ROOT / cohort_path)
    check(digest(prior) == plan["prior_exposure_sha256"], "Prior registry changed")
    rows = prior + cohort["train"] + cohort["evaluation"]
    check(len({row["id"] for row in rows}) == len(rows), "Overlapping exposure IDs")
    return {"total": len(rows), "mbpp": sum(r["id"].startswith("mbpp-") for r in rows),
            "ordered_rows_sha256": digest(rows)}


def main():
    os.environ.update(HF_HUB_OFFLINE="1", HF_HOME=str(ROOT / ".cache/huggingface"),
                      XDG_CACHE_HOME=str(ROOT / ".cache"), TMPDIR=str(ROOT / ".cache/tmp"),
                      HF_HUB_DISABLE_TELEMETRY="1")
    from transformers import AutoTokenizer

    audit = read(STUDY / "audit.json")
    reviewed = {row["id"]: row for row in audit["lessons"]}
    plan, paired, _ = verified_reports()
    check(audit["paired_sha256"] == paired["sha256"], "Audit belongs to a different experiment")
    tokenizer = AutoTokenizer.from_pretrained(plan["model"]["model_id"], revision=plan["model"]["revision"],
                                              token=False, local_files_only=True,
                                              cache_dir=str(ROOT / ".cache/huggingface/hub"))
    # One common pool; using one donor's verified answers for both arms removes
    # teacher identity from the substitution. Both choices are collection tasks.
    donor = "learned"
    labels = {row["task_id"]: row for row in paired["teachers"][donor]["arms"]["repair"]["selected"]}
    anchors = (662, 664, 688, 744, 759, 796, 832)
    result = {}
    for option in (723, 811):
        slots = []
        processed = supervised = 0
        for number in (*anchors, option):
            task_id = f"mbpp-full-{number}"
            selected = labels[task_id]
            audit_row = reviewed[task_id]["arms"][donor]
            check(number != 663 and audit_row["code_sha256"] == selected["code_sha256"], "Excluded or detached lesson")
            encoded = _encode_example(tokenizer, selected, plan["training"]["max_length"])
            processed += len(encoded["input_ids"])
            supervised += sum(x != -100 for x in encoded["labels"])
            slots.append({"id": task_id, "category": selected["category"], "code_sha256": selected["code_sha256"]})
        result[str(option)] = {"slots": slots, "bundle_sha256": digest(slots),
                               "processed_tokens_per_pass": processed, "supervised_tokens_per_pass": supervised}
    a, b = result.values()
    check(a["slots"][:-1] == b["slots"][:-1] and a["slots"][-1]["category"] == b["slots"][-1]["category"],
          "More than one lesson or category changed")
    for k in ("processed_tokens_per_pass", "supervised_tokens_per_pass"):
        check(max(a[k], b[k]) <= 1.05 * min(a[k], b[k]), "Exceeds proposed five-percent token tolerance")
    print(json.dumps({"bundles": result, "exposure_inventory": exposure_inventory(plan)}, indent=2))


if __name__ == "__main__":
    main()
