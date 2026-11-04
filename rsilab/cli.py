"""Offline-only CLI. No credentials, provider imports, execution or uploads."""
import argparse
import json
from pathlib import Path
import sys

from .artifacts import artifact_manifest
from .comparison import compare
from .core import Manifest, RunResult, canonical_json, digest


def _load(path):
    # Reject duplicate JSON keys instead of silently validating the last value.
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="rsilab", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate an immutable run manifest and print its SHA256")
    validate.add_argument("manifest")
    paired = commands.add_parser("compare", help="Compare two manifests and complete trusted result lists")
    for name in ("parent_manifest", "candidate_manifest", "parent_results", "candidate_results"):
        paired.add_argument(name)
    paired.add_argument("--lower-is-better", action="store_true")
    pilot = commands.add_parser("pilot-report", help="Re-score existing pilot report JSON offline")
    pilot.add_argument("parent")
    pilot.add_argument("candidate")
    mbpp = commands.add_parser("mbpp-report", help="Strict offline comparison of complete frozen MBPP batch reports")
    mbpp.add_argument("study")
    mbpp.add_argument("--baseline", nargs="+", required=True)
    mbpp.add_argument("--candidate", nargs="+", required=True)
    mbpp.add_argument("--adapter-sha256", required=True)
    mbpp.add_argument("--training-report")
    artifacts = commands.add_parser("artifacts", help="Hash an explicit local artifact allowlist")
    artifacts.add_argument("root")
    artifacts.add_argument("paths", nargs="+")
    selected = commands.add_parser("learning-select", help="Audit saved attempts and select verified training targets offline")
    selected.add_argument("ledger")
    selected.add_argument("excluded_tasks")
    learning = commands.add_parser("learning-compare", help="Compare matched verified-learning parent and candidate reports")
    for field in ("parent", "candidate", "tasks", "retention_ids", "policy"):
        learning.add_argument(field)
    learning.add_argument("--initial-comparison")
    data = commands.add_parser("coding-data-freeze", help="Validate saved reference evidence and freeze stronger tasks offline")
    data.add_argument("selection")
    data.add_argument("audits")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            manifest = Manifest.from_dict(_load(args.manifest))
            result = {"valid": True, "run_id": manifest.run_id, "sha256": manifest.sha256}
        elif args.command == "compare":
            result = compare(Manifest.from_dict(_load(args.parent_manifest)), Manifest.from_dict(_load(args.candidate_manifest)),
                             [RunResult.from_dict(row) for row in _load(args.parent_results)],
                             [RunResult.from_dict(row) for row in _load(args.candidate_results)],
                             higher_is_better=not args.lower_is_better)
        elif args.command == "pilot-report":
            from .pilot import compare_pilot_reports
            result = compare_pilot_reports(_load(args.parent), _load(args.candidate))
        elif args.command == "mbpp-report":
            from .mbpp_report import build_mbpp_comparison
            result = build_mbpp_comparison(_load(args.study), [_load(path) for path in args.baseline],
                                          [_load(path) for path in args.candidate], adapter_sha256=args.adapter_sha256,
                                          training_report=_load(args.training_report) if args.training_report else None)
            result["matched"] = result["comparison"]["matched"]
        elif args.command == "learning-select":
            from .learning_commands import select_from_saved_ledger
            result = select_from_saved_ledger(_load(args.ledger), _load(args.excluded_tasks))
        elif args.command == "learning-compare":
            from .learning import LearningPolicy, compare_learning_run
            result = compare_learning_run(_load(args.parent), _load(args.candidate), tasks=_load(args.tasks),
                retention_ids=_load(args.retention_ids), policy=LearningPolicy(**_load(args.policy)),
                initial_comparison=_load(args.initial_comparison) if args.initial_comparison else None)
        elif args.command == "coding-data-freeze":
            from .coding_data import freeze_verified_dataset
            result = freeze_verified_dataset(_load(args.selection), _load(args.audits))
        else:
            inventory = artifact_manifest(args.root, args.paths)
            result = {"sha256": digest(inventory), "manifest": inventory.to_dict()}
        print(canonical_json(result))
        return 0 if result.get("matched", True) else 2
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(f"rsilab: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
