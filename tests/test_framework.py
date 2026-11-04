import contextlib
from dataclasses import FrozenInstanceError, replace
import io
import json
from pathlib import Path
import tempfile
import unittest

from rsilab import (
    Agent, FrozenJSON, Manifest, Provenance, RetainParentGate, RunResult, Split,
    Task, artifact_manifest, compare, digest,
)
from rsilab.cli import main
from rsilab.pilot import PilotEvaluator, pilot_tasks
from rsi.verification import VERIFIER_VERSION


def fixture():
    task = Task("task-1", "family-a", Split.DEV, "solve", FrozenJSON({"cases": [1]}))
    agent = Agent("parent", "openbmb/MiniCPM5-2B", "a" * 40, "b" * 64, "c" * 64)
    provenance = Provenance("d"*64, "e"*64, "f"*64, "0"*64, FrozenJSON({"python": "3.13"}), "A10")
    parent = Manifest("parent-run", agent, (task,), (42, 43), FrozenJSON({"max_new_tokens": 512}),
                      FrozenJSON({"temperature": 0}), provenance)
    candidate = replace(parent, run_id="candidate-run", agent=replace(agent, id="candidate", adapter_sha256="1"*64))
    def results(manifest, value):
        return [RunResult(manifest.run_id, manifest.agent.id, task.id, seed, "completed", FrozenJSON({}), value)
                for seed in manifest.seeds]
    return parent, candidate, results(parent, 0), results(candidate, 1)


class FrameworkTests(unittest.TestCase):
    def setUp(self):
        work = Path(__file__).resolve().parents[1] / "work"
        work.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="framework-test-", dir=work)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def test_deep_immutable_snapshot(self):
        source = {"nested": [{"key": 1}]}
        frozen = FrozenJSON(source)
        before = digest(frozen)
        source["nested"][0]["key"] = 2
        frozen.to_dict()["nested"][0]["key"] = 3
        self.assertEqual(before, digest(frozen))
        with self.assertRaises(FrozenInstanceError):
            frozen._canonical = "{}"

    def test_canonical_hash_and_manifest_roundtrip(self):
        parent, *_ = fixture()
        self.assertEqual(digest({"a": 1, "b": [2]}), digest({"b": [2], "a": 1}))
        copy = Manifest.from_dict(json.loads(json.dumps(parent.to_dict())))
        self.assertEqual(copy, parent)
        self.assertEqual(copy.sha256, parent.sha256)
        self.assertNotEqual(replace(copy, seeds=(7,)).sha256, parent.sha256)

    def test_invalid_json_hashes_and_seeds(self):
        parent, *_ = fixture()
        for value in ({"x": float("nan")}, {1: "not string"}, {"x": object()}):
            with self.subTest(value=value), self.assertRaises(ValueError): FrozenJSON(value)
        with self.assertRaises(ValueError): replace(parent.agent, model_revision="main")
        for seeds in ((True,), (-1,), (42, 42)):
            with self.subTest(seeds=seeds), self.assertRaises(ValueError): replace(parent, seeds=seeds)

    def test_duplicate_ids_and_cross_split_families(self):
        parent, *_ = fixture()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            replace(parent, tasks=parent.tasks * 2)
        with self.assertRaisesRegex(ValueError, "crosses splits"):
            replace(parent, tasks=parent.tasks + (replace(parent.tasks[0], id="task-2", split=Split.TRAIN),))

    def test_matched_gain_never_promotes(self):
        parent, candidate, left, right = fixture()
        result = compare(parent, candidate, left, right)
        self.assertTrue(result["matched"])
        self.assertEqual(result["splits"]["dev"]["mean_gain"], 1)
        self.assertEqual(result["splits"]["dev"]["pairs"], 2)
        self.assertFalse(result["promoted"])
        self.assertEqual(result["selected_agent_id"], "parent")
        self.assertFalse(RetainParentGate().decide(parent.agent, [candidate.agent]).promoted)

    def test_lower_is_better_and_failed_runs_retained(self):
        parent, candidate, left, right = fixture()
        left[0] = replace(left[0], status="failed")
        result = compare(parent, candidate, left, right, higher_is_better=False)
        self.assertEqual(result["splits"]["dev"]["mean_gain"], -1)
        self.assertEqual(result["pairs"][0]["parent_status"], "failed")

    def test_mismatched_controls_suppress_scores(self):
        parent, candidate, left, right = fixture()
        for altered in (
            replace(candidate, budget=FrozenJSON({"max_new_tokens": 1024})),
            replace(candidate, provenance=replace(candidate.provenance, hardware="T4")),
            replace(candidate, provenance=replace(candidate.provenance, evaluator_sha256="9"*64)),
            replace(candidate, settings=FrozenJSON({"temperature": 1})),
        ):
            with self.subTest(altered=altered):
                result = compare(parent, altered, left, right)
                self.assertFalse(result["matched"])
                self.assertEqual(result["pairs"], [])

    def test_missing_duplicate_wrong_identity_incomplete_results(self):
        parent, candidate, left, right = fixture()
        for rows in (right[:1], right + right[:1], [replace(right[0], agent_id="wrong"), right[1]],
                     [replace(right[0], status="incomplete"), right[1]],
                     [replace(right[0], score=None), right[1]]):
            with self.subTest(rows=rows): self.assertFalse(compare(parent, candidate, left, rows)["matched"])

    def test_invalid_result_measurements(self):
        *_, right = fixture()
        for changes in ({"score": float("inf")}, {"elapsed_seconds": -1}, {"tokens": True}, {"seed": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(right[0], **changes)

    def test_artifact_allowlist_checksums_and_escape(self):
        file = self.directory / "adapter.txt"
        file.write_text("adapter")
        manifest = artifact_manifest(self.directory, ["adapter.txt"]).to_dict()
        import hashlib
        self.assertEqual(manifest["files"]["adapter.txt"]["sha256"], hashlib.sha256(b"adapter").hexdigest())
        self.assertEqual(manifest["files"]["adapter.txt"]["bytes"], 7)
        for names in (["../outside"], [".env"], [str(file)], ["adapter.txt", "adapter.txt"], []):
            with self.subTest(names=names), self.assertRaises(ValueError): artifact_manifest(self.directory, names)
        link = self.directory / "escape"
        link.symlink_to(Path(__file__).resolve())
        with self.assertRaises(ValueError): artifact_manifest(self.directory, ["escape"])

    def test_pilot_evaluator_ignores_claimed_success(self):
        task = pilot_tasks("train", 1)[0]
        expected = task.trusted.to_dict()["cases"]
        result = RunResult("r", "a", task.id, 42, "completed", FrozenJSON({
            "verifier_version": VERIFIER_VERSION, "passed": False,
            "outputs": [{"ok": True, "value": case["expected"]} for case in expected],
        }))
        self.assertEqual(PilotEvaluator().score(task, result).value, 1)
        wrong = replace(result, evidence=FrozenJSON({"verifier_version": VERIFIER_VERSION, "passed": True, "outputs": []}))
        self.assertEqual(PilotEvaluator().score(task, wrong).value, 0)
        with self.assertRaises(ValueError): PilotEvaluator().score(task, replace(result, status="incomplete"))
        self.assertEqual(set(task.agent_input()), {"id", "prompt"})
        with self.assertRaises(ValueError): pilot_tasks(Split.SEALED)

    def test_cli_validate_and_reject_duplicate_json(self):
        parent, *_ = fixture()
        path = self.directory / "manifest.json"
        path.write_text(json.dumps(parent.to_dict()))
        output = io.StringIO()
        with contextlib.redirect_stdout(output): self.assertEqual(main(["validate", str(path)]), 0)
        self.assertEqual(json.loads(output.getvalue())["sha256"], parent.sha256)
        path.write_text('{"schema_version":1,"schema_version":2}')
        with contextlib.redirect_stderr(io.StringIO()): self.assertEqual(main(["validate", str(path)]), 2)


if __name__ == "__main__":
    unittest.main()
