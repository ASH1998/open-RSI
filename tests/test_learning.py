"""Synthetic provider-independent workflow evidence; no candidate execution."""
import copy
from dataclasses import FrozenInstanceError
import hashlib
import unittest

from rsilab import digest
from rsilab.learning import (AttemptLedger, LearningPolicy, build_repair_prompt,
                             compare_learning_run, select_verified_targets)

EVALUATOR = {"version": "test-v2", "source_hashes": {"verifier.py": digest("verifier")}}


def task(index, split="train", category=None):
    return {"id": f"{split}-{index:03}", "split": split, "category": category or ("text", "numeric", "collections")[index % 3],
            "prompt": f"Implement task {split} {index}.", "cases": [{"private_expected": "NEVER_FEED_EXPECTED"}],
            "source_tests_sha256": digest(["tests", split, index])}


def record(item, passed=True, code=None):
    code = code or f"def solve():\n    return {item['id']!r}"
    verification = {"passed": passed, "count": int(passed), "total": 1,
                    "errors": [] if passed else ["case_0:wrong_output"],
                    "verifier_version": EVALUATOR["version"], "evaluator_source_hashes": copy.deepcopy(EVALUATOR["source_hashes"]),
                    "candidate_sha256": hashlib.sha256(code.encode()).hexdigest(), "source_tests_sha256": item["source_tests_sha256"]}
    row = {"task": copy.deepcopy(item), "generation": {"id": item["id"], "text": code,
           "hit_token_limit": False, "hit_time_limit": False, "input_tokens": 30, "output_tokens": 20}, "verification": verification}
    if passed:
        row["verified_code"] = code
    return row


def ledger_fixture(count=24, categories=None):
    items = [task(index, category=categories[index] if categories else None) for index in range(count)]
    ledger = AttemptLedger(items, excluded_tasks=[task(0, "dev"), task(0, "final")])
    for item in items:
        ledger.add(record(item), source_run_id="generation-0")
        ledger.add(record(item), source_run_id="generation-1", attempt_index=1, attempt_kind="sample")
    return ledger


def comparison_fixture(gain=3):
    tasks = [task(index) for index in range(32)] + [task(index, "dev") for index in range(32)]
    controls = {"task_sha256": digest(tasks), "hardware": "NVIDIA L40S", "packages": {"torch": "test"},
                "model": {"model_id": "openbmb/test", "revision": "a" * 40}, "evaluator": copy.deepcopy(EVALUATOR),
                "source_hashes": {"worker.py": digest("worker")},
                "generation": {"seed": 42, "temperature": 0.0, "max_new_tokens": 512, "max_input_tokens": 2048,
                               "enable_thinking": False, "attempts_per_task": 1}}
    def arm(name, extra):
        rows = []
        for index, item in enumerate(tasks):
            passed = index < 20 if index < 32 else index < 42 + extra
            rows.append({**record(item, passed), "effective_seed": 42 + index % 32})
        return {"run_id": name, "agent_id": name, "adapter_sha256": None if name == "parent" else digest(name),
                "controls": copy.deepcopy(controls), "records": rows}
    parent, candidate = arm("parent", 0), arm("candidate-42", gain)
    candidate["training"] = {"seed": 42, "fresh_adapter": True, "parent_adapter_sha256": None,
                             "adapter_sha256": candidate["adapter_sha256"], "selection_sha256": digest("selection")}
    return parent, candidate, tasks, [item["id"] for item in tasks[:32]]


class LearningTests(unittest.TestCase):
    def compare(self, fixture, **kwargs):
        parent, candidate, tasks, retention = fixture
        return compare_learning_run(parent, candidate, tasks=tasks, retention_ids=retention, **kwargs)

    def test_policy_immutable_hashed_and_cannot_weaken_gates(self):
        policy = LearningPolicy()
        with self.assertRaises(FrozenInstanceError): policy.min_targets = 1
        self.assertEqual(policy.sha256, digest(policy.to_dict()))
        for args in ({"min_targets": 23}, {"min_categories": 2}, {"max_category_share": .61},
                     {"dev_count": 31}, {"min_dev_gain": 2}, {"initial_seed": 43}, {"max_repairs": 4}):
            with self.subTest(args=args), self.assertRaises(ValueError): LearningPolicy(**args)

    def test_raw_failure_repair_chain_snapshots_and_earliest_verified_target(self):
        items = [task(i) for i in range(24)]
        ledger = AttemptLedger(items)
        failed = record(items[0], False)
        first = ledger.add(failed, source_run_id="first")
        failed["generation"]["text"] = "mutated"
        sample = ledger.add(record(items[0], False), source_run_id="sample", attempt_index=1, attempt_kind="sample")
        repaired = ledger.add(record(items[0]), source_run_id="repair", attempt_index=2,
                              attempt_kind="repair", parent_attempt_id=sample["attempt_id"])
        for item in items[1:]:
            ledger.add(record(item), source_run_id="first")
            ledger.add(record(item), source_run_id="sample", attempt_index=1, attempt_kind="sample")
        result = select_verified_targets(ledger)
        self.assertTrue(result["eligible"])
        self.assertEqual(len(ledger.records), 49)
        self.assertNotEqual(ledger.records[0]["record"]["generation"]["text"], "mutated")
        self.assertEqual(result["selected"][0]["attempt_id"], repaired["attempt_id"])
        self.assertEqual(result["selected"][0]["parent_attempt_id"], sample["attempt_id"])
        returned = ledger.records
        returned[0]["record"]["verification"]["passed"] = True
        self.assertFalse(ledger.records[0]["record"]["verification"]["passed"])

    def test_repair_parent_index_budget_and_success_constraints(self):
        item = task(0)
        ledger = AttemptLedger([item])
        first = ledger.add(record(item, False), source_run_id="first")
        sample = ledger.add(record(item, False), source_run_id="sample", attempt_index=1, attempt_kind="sample")
        with self.assertRaisesRegex(ValueError, "link"):
            ledger.add(record(item), source_run_id="repair", attempt_index=2, attempt_kind="repair", parent_attempt_id="wrong")
        ledger.add(record(item), source_run_id="repair", attempt_index=2, attempt_kind="repair", parent_attempt_id=sample["attempt_id"])
        with self.assertRaises(ValueError): ledger.add(record(item), source_run_id="fourth", attempt_index=3)
        successful = AttemptLedger([item])
        row = successful.add(record(item), source_run_id="first")
        sample = successful.add(record(item, False), source_run_id="sample", attempt_index=1, attempt_kind="sample")
        with self.assertRaisesRegex(ValueError, "failing both"):
            successful.add(record(item), source_run_id="repair", attempt_index=2, attempt_kind="repair", parent_attempt_id=sample["attempt_id"])

    def test_heldout_and_known_duplicate_leakage_rejected(self):
        for split in ("dev", "final", "test", "sealed"):
            with self.subTest(split=split), self.assertRaises(ValueError): AttemptLedger([task(0, split)])
        item, excluded = task(0), task(0, "dev")
        for key in ("cluster_id", "source_row_sha256", "duplicate_group"):
            a, b = copy.deepcopy(item), copy.deepcopy(excluded)
            a["metadata"] = b["metadata"] = {key: "same"}
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "overlap"):
                AttemptLedger([a], excluded_tasks=[b])
        spoof = task(0)
        spoof["metadata"] = {"source_split": "validation"}
        with self.assertRaises(ValueError): AttemptLedger([spoof])
        ledger = AttemptLedger([item])
        changed = record(item)
        changed["task"]["cases"] = [{}]
        with self.assertRaisesRegex(ValueError, "frozen"):
            ledger.add(changed, source_run_id="x")

    def test_repair_prompt_never_copies_private_tests_reference_or_raw_errors(self):
        item = task(0)
        item["reference_code"] = "NEVER_FEED_REFERENCE"
        verification = record(item, False)["verification"]
        verification.update(stdout="NEVER_FEED_STDOUT", errors=["case_0:wrong_output", "secret-api-key", "case_999:execution_error"],
                            outputs=[{"value": "NEVER_FEED_VALUE"}])
        prompt = build_repair_prompt(item, "def solve():\n    return 0", verification)
        self.assertIn("def solve()", prompt)
        self.assertIn("Check 0: wrong_output", prompt)
        for secret in ("NEVER_FEED", "secret-api-key", "case_999"):
            self.assertNotIn(secret, prompt)
        bounded = build_repair_prompt(item, "x" * 10000, verification)
        self.assertLessEqual(len(bounded), LearningPolicy().max_prompt_chars)
        self.assertIn("[previous code truncated]", bounded)
        item["prompt"] = "x" * 16000
        with self.assertRaisesRegex(ValueError, "exceeds bound"):
            build_repair_prompt(item, "x", verification)

    def test_dedup_and_diversity_gates(self):
        items = [task(i) for i in range(24)]
        ledger = AttemptLedger(items)
        for item in reversed(items): ledger.add(record(item, code="def solve():\n    return 1"), source_run_id="x")
        result = select_verified_targets(ledger)
        self.assertEqual(result["selected_count"], 1)
        self.assertEqual(result["selected"][0]["task_id"], items[0]["id"])
        self.assertFalse(result["eligible"])
        dominant = select_verified_targets(ledger_fixture(categories=["text"] * 15 + ["numeric"] * 5 + ["collections"] * 4))
        self.assertIn("category_share_exceeded", dominant["reasons"])
        self.assertTrue(select_verified_targets(ledger_fixture())["eligible"])

    def test_success_code_and_test_digests_are_bound(self):
        for field in ("candidate_sha256", "source_tests_sha256"):
            item = task(0)
            row = record(item)
            row["verification"][field] = "0" * 64
            ledger = AttemptLedger([item])
            ledger.add(row, source_run_id="x")
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "digest mismatch"):
                select_verified_targets(ledger)
        row = record(item)
        row["generation"]["text"] = "unrelated generated answer"
        ledger = AttemptLedger([item])
        ledger.add(row, source_run_id="x")
        with self.assertRaisesRegex(ValueError, "absent"):
            select_verified_targets(ledger)

    def test_infrastructure_is_preserved_and_blocks_selection_and_repair(self):
        item = task(0)
        row = record(item, False)
        row["verification"]["infrastructure_error"] = True
        ledger = AttemptLedger([item])
        first = ledger.add(row, source_run_id="x")
        self.assertEqual(ledger.records[0]["record"], row)
        self.assertIn("incomplete_or_invalid_attempt_evidence", select_verified_targets(ledger)["reasons"])
        sample = ledger.add(record(item, False), source_run_id="sample", attempt_index=1, attempt_kind="sample")
        with self.assertRaises(ValueError):
            ledger.add(record(item), source_run_id="y", attempt_index=2, attempt_kind="repair", parent_attempt_id=sample["attempt_id"])
        with self.assertRaises(ValueError): build_repair_prompt(item, "code", row["verification"])

    def test_missing_training_attempts_and_evaluator_drift_block_gate(self):
        items = [task(i) for i in range(25)]
        ledger = AttemptLedger(items)
        for index, item in enumerate(items[:24]):
            row = record(item)
            if index == 0: row["verification"]["evaluator_source_hashes"]["verifier.py"] = digest("other")
            ledger.add(row, source_run_id="x")
        result = select_verified_targets(ledger)
        self.assertIn("missing_training_attempts", result["reasons"])
        self.assertIn("mixed_target_evaluators", result["reasons"])
        self.assertFalse(result["eligible"])

    def test_independent_sample_after_success_and_first_success_selection(self):
        items = [task(i) for i in range(24)]
        ledger = AttemptLedger(items)
        first_ids = {}
        for item in reversed(items):
            first_ids[item["id"]] = ledger.add(record(item), source_run_id="greedy")["attempt_id"]
            ledger.add(record(item, code=f"def solve():\n    return 'sample {item['id']}'"),
                       source_run_id="sample", attempt_index=1, attempt_kind="sample")
        result = select_verified_targets(ledger)
        self.assertTrue(result["eligible"])
        self.assertEqual(len(ledger.records), 48)
        self.assertTrue(all(row["attempt_id"] == first_ids[row["task_id"]] for row in result["selected"]))

    def test_repair_task_quota_and_missing_second_attempt_block(self):
        items = [task(i) for i in range(2)]
        ledger = AttemptLedger(items, policy=LearningPolicy(max_repair_tasks=1))
        samples = []
        for item in items:
            ledger.add(record(item, False), source_run_id="greedy")
            samples.append(ledger.add(record(item, False), source_run_id="sample", attempt_index=1, attempt_kind="sample"))
        ledger.add(record(items[0]), source_run_id="repair", attempt_index=2, attempt_kind="repair", parent_attempt_id=samples[0]["attempt_id"])
        with self.assertRaisesRegex(ValueError, "quota"):
            ledger.add(record(items[1]), source_run_id="repair", attempt_index=2, attempt_kind="repair", parent_attempt_id=samples[1]["attempt_id"])
        partial = AttemptLedger(items)
        partial.add(record(items[0]), source_run_id="greedy")
        self.assertEqual(select_verified_targets(partial)["incomplete_task_ids"], [item["id"] for item in items])

    def test_promising_gate_retains_parent_and_only_recommends_replication(self):
        fixture = comparison_fixture()
        before = digest(fixture)
        result = self.compare(fixture)
        self.assertTrue(result["matched"])
        self.assertTrue(result["promising"])
        self.assertTrue(result["replication_recommended"])
        self.assertEqual(result["next_training_seed"], 43)
        self.assertEqual(result["scores"]["dev"]["net_success_gain"], 3)
        self.assertFalse(result["promoted"])
        self.assertEqual(result["selected_agent_id"], "parent")
        self.assertEqual(before, digest(fixture))

    def test_configured_16_retention_and_single_batch_48_seed_offsets(self):
        parent, candidate, tasks, retention = comparison_fixture()
        tasks = tasks[:16] + tasks[32:]
        for report in (parent, candidate):
            report["records"] = report["records"][:16] + report["records"][32:]
            report["controls"]["task_sha256"] = digest(tasks)
            for index, row in enumerate(report["records"]): row["effective_seed"] = 42 + index
        result = self.compare((parent, candidate, tasks, retention[:16]), policy=LearningPolicy(retention_count=16))
        self.assertTrue(result["promising"])
        self.assertEqual(result["scores"]["retention"]["total"], 16)

    def test_two_net_gains_or_one_retention_loss_blocks_replication(self):
        self.assertFalse(self.compare(comparison_fixture(gain=2))["replication_recommended"])
        fixture = comparison_fixture()
        item = fixture[1]["records"][0]
        item["verification"].update(passed=False, count=0, errors=["case_0:wrong_output"])
        result = self.compare(fixture)
        self.assertFalse(result["promising"])
        self.assertEqual(result["scores"]["retention"]["lost_parent_successes"], 1)

    def test_control_or_effective_seed_drift_prevents_comparison(self):
        for key, value in (("hardware", "other-gpu"), ("packages", {"torch": "other"}),
                           ("model", {"model_id": "other", "revision": "a" * 40})):
            fixture = comparison_fixture()
            fixture[1]["controls"][key] = value
            with self.subTest(key=key):
                result = self.compare(fixture)
                self.assertFalse(result["matched"])
                self.assertEqual(result["scores"], {})
                self.assertFalse(result["promising"])
        fixture = comparison_fixture()
        fixture[1]["records"][0]["effective_seed"] += 1
        self.assertIn("unmatched_effective_seeds", self.compare(fixture)["reasons"])

    def test_missing_or_reordered_results_rejected(self):
        for mutation in (lambda rows: rows.pop(), lambda rows: rows.reverse()):
            fixture = comparison_fixture()
            mutation(fixture[1]["records"])
            with self.assertRaisesRegex(ValueError, "coverage/order"):
                self.compare(fixture)

    def test_evaluator_truncation_infrastructure_and_token_evidence_rejected(self):
        for mutation in (
            lambda row: row["verification"].update(verifier_version="drift"),
            lambda row: row["generation"].update(hit_token_limit=True),
            lambda row: row["verification"].update(infrastructure_error=True),
            lambda row: row["generation"].update(output_tokens=513),
            lambda row: row["verification"].update(count=0),
        ):
            fixture = comparison_fixture()
            mutation(fixture[1]["records"][0])
            with self.assertRaises(ValueError): self.compare(fixture)

    def test_fresh_adapter_required(self):
        fixture = comparison_fixture()
        fixture[1]["training"]["fresh_adapter"] = False
        with self.assertRaisesRegex(ValueError, "Fresh-adapter"):
            self.compare(fixture)

    def test_seed43_requires_matching_promising_seed42_and_same_selection(self):
        fixture = comparison_fixture()
        first = self.compare(fixture)
        candidate = fixture[1]
        candidate.update(run_id="candidate-43", agent_id="candidate-43", adapter_sha256=digest("adapter43"))
        candidate["training"].update(seed=43, adapter_sha256=candidate["adapter_sha256"])
        with self.assertRaisesRegex(ValueError, "replication requires"):
            self.compare(fixture)
        result = self.compare(fixture, initial_comparison=first)
        self.assertTrue(result["promising"])
        self.assertFalse(result["replication_recommended"])
        self.assertIsNone(result["next_training_seed"])
        self.assertFalse(result["promoted"])
        candidate["training"]["selection_sha256"] = digest("different labels")
        with self.assertRaisesRegex(ValueError, "replication requires"):
            self.compare(fixture, initial_comparison=first)


if __name__ == "__main__":
    unittest.main()
