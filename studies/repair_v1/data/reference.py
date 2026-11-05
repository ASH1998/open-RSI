"""Offline worker for hash-pinned, reviewed MBPP references only."""
import hashlib
import json
import resource
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from rsi.datasets import SOURCE_HASHES
from rsi.mbpp_verification import MBPP_ALLOWED_IMPORTS
from rsi.mbpp_verification_v2 import decode_value, encode_value
from rsi.verification import CandidatePolicyError, extract_code, validate_code
from rsilab import digest
from rsilab.dataset_io import read_development_splits
from studies.repair_v1.data.reviews import CONTRACTS

# These exact pinned references use an additional standard-library import.
# Candidate code still receives only the MBPP policy in its prompt.
REFERENCE_IMPORTS = {663: {"sys"}, 688: {"cmath"}, 717: {"sys"}, 910: {"datetime"}, 938: {"sys"}}


# These reviewed native sources respectively read a local parameter named
# input or use list.__add__ as the zip operation. Both patterns are forbidden
# for generated code. The exception is restricted to the exact pinned references.
REVIEWED_POLICY_EXCEPTIONS = {
    644: ("forbidden_name", "02f70d21e8e3a467a800b4eab4dfdc897c6546afdbe4276bf8d05c3fddf8ae76"),
    696: ("private_attribute", "b810a5bd0af90e231888974e612d60e7a2ff49a16e32790cf361240f2f2d75ed"),
    832: ("forbidden_name", "52024e2af7fc2b6efff0f4abfb173b345dee57892c89b70e67951dab2696efab"),
}


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    rows = read_development_splits(ROOT / "data/mbpp/raw", source_hashes=SOURCE_HASHES,
                                   expected_counts={"train": 374}, splits=("train",))
    native = {r["task_id"]: r for r in rows["train"]}
    requests = json.load(sys.stdin)
    if [r["source_id"] for r in requests] != sorted(CONTRACTS):
        raise ValueError("Expected exactly the reviewed native train source IDs")
    reports = []
    for request in requests:
        if set(request) != {"source_id", "source_row_sha256", "entry_point", "inputs"}:
            raise ValueError("Only identity and inputs may reach the reference worker")
        source_id = request["source_id"]
        row = native[source_id]
        if digest(row) != request["source_row_sha256"]:
            raise ValueError(f"Original row differs for {source_id}")
        reference = extract_code(row["code"])
        entry = request["entry_point"]
        sha = hashlib.sha256(reference.encode()).hexdigest()
        try:
            validate_code(reference, entry, allowed_imports=MBPP_ALLOWED_IMPORTS | REFERENCE_IMPORTS.get(source_id, set()))
        except CandidatePolicyError as exc:
            if REVIEWED_POLICY_EXCEPTIONS.get(source_id) != (str(exc), sha):
                raise
        namespace = {}
        exec(compile(reference, f"<pinned MBPP {source_id}>", "exec"), namespace)
        outputs = []
        for case in request["inputs"]:
            if set(case) != {"args", "kwargs"}:
                raise ValueError("Reference received extraneous input")
            value = namespace[entry](*decode_value(case["args"]), **decode_value(case["kwargs"]))
            outputs.append({"ok": True, "value": encode_value(value)})
        reports.append({"source_id": source_id, "reference_sha256": sha,
                        "outputs": outputs})
    json.dump(reports, sys.stdout, allow_nan=False)


if __name__ == "__main__":
    main()
