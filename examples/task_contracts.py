"""A self-contained, offline example of reviewing a boundary and replaying it."""
import json

from rsi.mbpp_verification import convert_mbpp_tests, encode_value
from rsilab import digest
from rsilab.task_contracts import apply_task_contracts, replay_task_contracts, score_task_contract_outputs


def main():
    tests = ["assert in_window(4, 3, 5) == True"]
    source = {
        "id": "example-window", "split": "train", "category": "numeric",
        "metadata": {"source_split": "train", "dataset": "synthetic-example"},
        "prompt": "Return Python code only.\n\nCheck whether x is in the window.\n\n"
                  "Required signature:\ndef in_window(x, lo, hi):",
        "test_list": tests, "challenge_test_list": [],
        **convert_mbpp_tests(tests, "in_window"),
    }
    review = {
        "task_id": source["id"], "source_sha256": digest(source),
        "clarified_prompt": "Return a boolean indicating whether lo <= x < hi.",
        "review_note": "The written half-open interval excludes its upper endpoint.",
        "boundaries": [{"name": "upper_endpoint", "call": "in_window(5, 3, 5)",
                        "expected": encode_value(False)}],
    }
    manifest = apply_task_contracts([source], [review])
    replayed = replay_task_contracts([source], [review], manifest, expected_sha256=manifest["sha256"])
    # Synthetic saved outputs. In a study, obtain these from an isolated runner.
    outputs = [{"ok": True, "value": encode_value(v)} for v in (True, False)]
    score = score_task_contract_outputs(replayed, source["id"], outputs, expected_sha256=manifest["sha256"])
    print(json.dumps({"generation_request": replayed["prompts"][0],
                      "evaluator_case_count": len(replayed["tasks"][0]["cases"]),
                      "boundary_passed_count": score["boundary_passed_count"],
                      "manifest_sha256": replayed["sha256"]}, indent=2))


if __name__ == "__main__":
    main()
