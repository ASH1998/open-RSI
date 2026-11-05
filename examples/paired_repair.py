"""Offline synthetic replay. No model calls or candidate executions."""
import hashlib
import json

from rsi.mbpp_verification import convert_mbpp_tests, encode_value
from rsilab import digest
from rsilab.paired_repair import audit_paired_repair, second_prompts
from rsilab.successor import inference_request_sha256
from rsilab.task_contracts import apply_task_contracts, score_task_contract_outputs


def main():
    tests = ["assert even(4) == True"]
    source = {"id": "example-even", "split": "train", "category": "numeric",
              "metadata": {"source_split": "train"}, "test_list": tests, "challenge_test_list": [],
              "prompt": "Return Python code only.\n\nCheck parity.\n\nRequired signature:\ndef even(x):",
              **convert_mbpp_tests(tests, "even")}
    review = {"task_id": source["id"], "source_sha256": digest(source),
              "clarified_prompt": "Return a boolean indicating whether x is even.",
              "review_note": "Check odd input and the declared return type.",
              "boundaries": [{"name": "odd", "call": "even(9)", "expected": encode_value(False)}]}
    manifest = apply_task_contracts([source], [review])
    task = manifest["tasks"][0]
    original = {"agent_id": "synthetic-base", "model_id": "example/model", "revision": "a" * 40,
                "tokenizer_revision": "b" * 40, "parent_agent_sha256": None, "adapter_sha256": None}
    learned = {**original, "agent_id": "synthetic-adapter", "parent_agent_sha256": digest(original),
               "adapter_sha256": "c" * 64}
    teachers = {"original": original, "learned": learned}
    # All IDs, hashes, hardware, tokens and costs in this example are fixtures.
    evaluator = {"version": "mbpp-typed-v2", "source_hashes": {"synthetic-executor": "d" * 64}}
    runtime = {"hardware": "fixture", "precision": "fixture", "packages": {"fixture": "1"},
               "source_hashes": {"rsilab/task_contracts.py": "e" * 64}}
    controls = {}
    for key, seed, temp in (("first", 42, 0.0), ("second", 31415, 0.7)):
        controls[key] = {"generation": {"seed": seed, "temperature": temp, "max_new_tokens": 512,
                                        "max_input_tokens": 2048, "enable_thinking": False},
                         "runtime": runtime, "evaluator": evaluator, "effective_seeds": [seed]}

    def record(correct, control):
        expr = "x % 2 == 0" if correct else "int(x % 2 == 0)"
        code = f"def even(x):\n    return {expr}"
        outputs = [{"ok": True, "value": encode_value(v)} for v in ((True, False) if correct else (1, 0))]
        verified = {**score_task_contract_outputs(manifest, task["id"], outputs),
                    "verifier_version": evaluator["version"], "evaluator_source_hashes": evaluator["source_hashes"],
                    "source_tests_sha256": task["source_tests_sha256"], "outputs": outputs,
                    "candidate_sha256": hashlib.sha256(code.encode()).hexdigest(), "sandbox_id": "synthetic"}
        generation = {"id": task["id"], "text": code, "hit_time_limit": False, "hit_token_limit": False,
                      "input_tokens": 44, "output_tokens": 12}
        row = {"generation": generation, "verification": verified, "task": task,
               "effective_seed": control["effective_seeds"][0]}
        if verified["passed"]:
            row["verified_code"] = code
        return row

    def run(role):
        cols = {}
        first = record(False, controls["first"])
        prompts = second_prompts(manifest, [first])
        for key in ("first", "sample", "repair"):
            control = controls["first" if key == "first" else "second"]
            sent = manifest["prompts"] if key == "first" else [{"id": task["id"], "prompt": prompts[key][task["id"]]}]
            row = first if key == "first" else record(role == "original" and key == "repair", control)
            cols[key] = {"controls": control, "records": [row], "prompts": sent,
                         "request_sha256": inference_request_sha256(teachers[role], control, sent)}
        return {"run_id": f"fixture-{role}", "teacher": teachers[role],
                "manifest_sha256": manifest["sha256"], "collections": cols}

    report = audit_paired_repair(manifest, teachers, controls, run("original"), run("learned"))
    print(json.dumps({"fixture": True, "original_sample_only": report["teachers"]["original"]["paired_unique"]["left_only"],
                      "original_repair_only": report["teachers"]["original"]["paired_unique"]["right_only"],
                      "child_gate": report["child_gate"]["reasons"]}, indent=2))


if __name__ == "__main__":
    main()
