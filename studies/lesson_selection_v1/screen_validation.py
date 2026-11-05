"""Calibrate two MBPP validation references, then screen them for fresh evaluation."""
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
# The child runs with -I and reads only pinned MBPP validation references.
sys.path.insert(0, str(ROOT))

from rsi.datasets import SOURCE_HASHES
from rsi.mbpp_verification import convert_mbpp_task, encode_value
from rsi.mbpp_verification_v2 import decode_value
from rsi.verification import extract_code, validate_code
from rsilab import digest
from rsilab.coding_data import PINNED_POOL_SHA256
from rsilab.dataset_io import read_development_splits
from studies.repair_v1.data.prepare import identities


REFERENCE_HASHES = {
    531: "039cc591683f752f499ac6551a2d05d080353b500ad0f5c6604e89b791911449",
    575: "57c5da128cbf0af0c8ec917e44afeef9b67b60d40d76bc450f26e36551647b1c",
}
# Reachable coin amounts and intervals containing the requested nonmultiple.
EXTRA = {
    531: [(([1, 3, 4], 3, 6), 2), (([2, 5], 2, 0), 0), (([2, 2, 5], 3, 9), 3)],
    575: [((2, 1, 2, 3), 3), ((5, 1, 6, 6), 6), ((3, 2, 3, 5), 5)],
}


def read(name):
    return json.loads((ROOT / name).read_text())


def overlapping_coin_cases(task, pool, exposed):
    old = next(t for t in pool["pools"]["train"] if t["id"] == "mbpp-full-918")
    if old["id"] not in {row["id"] for row in exposed}:
        raise ValueError("Missing historical coin-change exposure")
    old_cases = convert_mbpp_task(old)["cases"]
    same_input = {digest([c["args"], c["kwargs"]]): c for c in old_cases}
    overlaps = []
    for case in task["cases"]:
        previous = same_input.get(digest([case["args"], case["kwargs"]]))
        if previous is not None:
            overlaps.append({"args": decode_value(case["args"]),
                             "minimum_coins": decode_value(case["expected"]),
                             "combination_count": decode_value(previous["expected"])})
    return overlaps


def check_nonmultiples(function):
    checked = 0
    for divisor in range(2, 9):
        for lower in range(1, 11):
            for upper in range(lower, lower + 11):
                # Generate the complete permitted answer list, independently
                # of the reference's early-stop scan.
                answers = sorted(set(range(lower, upper + 1))
                                 - set(range(((lower + divisor - 1) // divisor) * divisor, upper + 1, divisor)))
                for rank, expected in enumerate(answers, start=1):
                    if encode_value(function(divisor, rank, lower, upper)) != encode_value(expected):
                        raise ValueError("Nonmultiple reference disagrees on bounded domain")
                    checked += 1
    return checked


def worker():
    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    pool = read("data/mbpp/pools-full-seed42.json")
    if digest({k: v for k, v in pool.items() if k != "manifest_sha256"}) != PINNED_POOL_SHA256:
        raise ValueError("Importer pool changed")
    prior = read("data/task-contracts-v1/prior-exposure.json")
    cohort = read("data/repair-v1/selected/cohort.json")
    exposed = prior + cohort["train"] + cohort["evaluation"]
    if digest(exposed) != "e3aeb4c84914a0b621c5781d9175c3e001ba25ceec993b7bcd92da52b9638226":
        raise ValueError("Repair exposure history changed")
    excluded = set().union(*(identities(t) for t in exposed))
    rows = read_development_splits(ROOT / "data/mbpp/raw", source_hashes=SOURCE_HASHES,
                                   expected_counts={"validation": 90}, splits=("validation",))
    native = {r["task_id"]: r for r in rows["validation"]}
    screened = []
    for original in pool["pools"]["dev"]:
        number = original["metadata"]["source_id"]
        if number not in REFERENCE_HASHES:
            continue
        if identities(original) & excluded or digest(native[number]) != original["metadata"]["source_row_sha256"]:
            raise ValueError("Exposure overlap or detached native row")
        excluded.update(identities(original))
        task = convert_mbpp_task(original)
        reference = extract_code(native[number]["code"])
        if hashlib.sha256(reference.encode()).hexdigest() != REFERENCE_HASHES[number]:
            raise ValueError("Unexpected reference")
        validate_code(reference, task["entry_point"], allowed_imports={"sys"} if number == 531 else set())
        namespace = {}
        exec(compile(reference, f"<pinned MBPP validation {number}>", "exec"), namespace)
        fn = namespace[task["entry_point"]]
        for c in task["cases"]:
            if c["projections"] or encode_value(fn(*decode_value(c["args"]), **decode_value(c["kwargs"]))) != c["expected"]:
                raise ValueError("Native typed assertion failed")
        for args, expected in EXTRA[number]:
            if any(encode_value(args) == c["args"] for c in task["cases"]):
                raise ValueError("Repeated native input")
            if encode_value(fn(*args)) != encode_value(expected):
                raise ValueError("Independent boundary disagrees")
        result = {"id": task["id"], "native_cases": len(task["cases"]), "new_checks": len(EXTRA[number])}
        if number == 531:
            overlaps = overlapping_coin_cases(task, pool, exposed)
            if len(overlaps) != 2:
                raise ValueError("Historical overlap evidence changed")
            result.update(disposition="quarantine_for_fresh_comparison", exposed_task="mbpp-full-918",
                          matching_native_inputs=overlaps)
        else:
            result.update(disposition="retain_for_bounded_development", bounded_reference_cases=check_nonmultiples(fn))
        screened.append(result)
    if len(screened) != len(REFERENCE_HASHES):
        raise ValueError("Incomplete screen")
    print(json.dumps(sorted(screened, key=lambda row: row["id"]), indent=2))


if __name__ == "__main__":
    if sys.argv[1:] == ["--worker"]:
        worker()
    else:
        subprocess.run([sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--worker"],
                       cwd=ROOT, env={"TMPDIR": str(ROOT / ".cache/tmp")}, timeout=45, check=True)
