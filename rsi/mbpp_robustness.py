"""Post-hoc MBPP diagnostics: frozen original assertions plus manual extra cases.

This module reads no files, runs no model/reference code, and launches no jobs.
The outputs are diagnostic task copies, never replacement study tasks or labels.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable

from .mbpp_verification import convert_mbpp_tests

VERSION = "mbpp-robustness-v1"
DATASET = "google-research-datasets/mbpp"
REVISION = "4bb6404fdc6cacfda99d4ac4205087b89d32030c"

# entry point, pinned source-row hash, original compiled source-test hash.
SOURCE_CONTRACTS = {
    512: ("count_element_freq", "07370a0e6fa34a5949f85e564ac84d034a46e817a8e7a492b430180a209e16ab", "5b1f45a8007fca03f01034c1a926111a85c1acd1315a19d4da5e89837aec0618"),
    520: ("get_lcm", "6aa5fa7116fe1b7504b75a8f96a71a39edf72978846eb28c83a7954e4c3368af", "7d310abc9702040c4501c9b7920941ba2c176f274395465d91af82eda02158a7"),
    557: ("toggle_string", "2e371b948a5e8baf9abb22ef0950f682345b861e48a0cb5aaf070873a7c94f93", "bfebb0a855f095e8d50256f5f4c21c94fa38ff021cf1196b7f0d5d43555d21ac"),
    558: ("digit_distance_nums", "08392e00cc015db1d10abbb30d3fd18919676f99c08fa79cb0032f39307e43b3", "5ddc59c6a8b96655a2a41f3fa69ab790eebf5da4fd718c0fd3bbb46a6fbf571d"),
    568: ("empty_list", "cd9b7bcde88ac3f91e2e152c6a4202b0f6d5209ff59a036196f58dd79f17a771", "47bc39bf51622479eda031901f897da3230144a990be9173a2f1fd07e4fa8aee"),
    576: ("is_Sub_Array", "11b7fe7cbc20769233b2923ab6b3b2b36d6fbb650f0576e492c6b801a5b4f421", "25b32420ada697dac4ba66a8f83829d53ea9bd7cf3ecafd0ea844739482dff8c"),
    928: ("change_date_format", "9c6751049707177dbcb7adff103ed71982597be7fa8e8c4b607f6745e83fb2d6", "d866eecf8fa3d0404c4c089aa33ce8b97eb0ae05d23a26884434b5b390f78376"),
}
TASK_IDS = tuple(f"mbpp-full-{number}" for number in SOURCE_CONTRACTS)

# Literal equalities only. Expectations are manually derived from the contracts;
# neither reference implementations nor saved candidate outputs supply answers.
_EXTRA_TESTS = {
    512: (
        "assert count_element_freq(()) == {}",
        "assert count_element_freq(((), ((),))) == {}",
        "assert count_element_freq((4,)) == {4: 1}",
        "assert count_element_freq((1, (2, (1, 2)), (), 1)) == {1: 3, 2: 2}",
        "assert count_element_freq((0, (-1, 0), (-1, (-1,)))) == {0: 2, -1: 3}",
        "assert count_element_freq((3, (3,), ((3,),), 3)) == {3: 4}",
    ),
    520: (
        "assert get_lcm([1, 1]) == 1",
        "assert get_lcm([6, 6]) == 6",
        "assert get_lcm([4, 8, 16]) == 16",
        "assert get_lcm([6, 10, 15]) == 30",
        "assert get_lcm([5, 7]) == 35",
        "assert get_lcm([12, 18, 30]) == 180",
    ),
    557: (
        "assert toggle_string('') == ''",
        "assert toggle_string('ABCXYZ') == 'abcxyz'",
        "assert toggle_string('abcxyz') == 'ABCXYZ'",
        "assert toggle_string('aA zZ') == 'Aa Zz'",
        "assert toggle_string('123-!?') == '123-!?'",
        "assert toggle_string('Ab_9-Z!') == 'aB_9-z!'",
    ),
    558: (
        "assert digit_distance_nums(42, 42) == 0",
        "assert digit_distance_nums(10, 1) == 9",
        "assert digit_distance_nums(1, 10) == 9",
        "assert digit_distance_nums(1000, 1) == 27",
        "assert digit_distance_nums(100, 90) == 1",
        "assert digit_distance_nums(1234, 1000) == 9",
    ),
    568: (
        "assert empty_list(0) == []",
        "assert empty_list(1) == [{}]",
        "assert empty_list(2) == [{}, {}]",
        "assert empty_list(8) == [{}, {}, {}, {}, {}, {}, {}, {}]",
    ),
    576: (
        "assert is_Sub_Array([1, 2], [2, 1], 2, 2) == False",
        "assert is_Sub_Array([1, 2, 9], [2, 1], 3, 2) == False",
        "assert is_Sub_Array([1, 9, 2], [1, 2], 3, 2) == False",
        "assert is_Sub_Array([9, 1, 2], [1, 2], 3, 2) == True",
        "assert is_Sub_Array([8, 9, 1, 2], [1, 2], 4, 2) == True",
        "assert is_Sub_Array([1, 1, 2], [1, 2], 3, 2) == True",
        "assert is_Sub_Array([1, 2, 1, 2, 3], [1, 2, 3], 5, 3) == True",
        "assert is_Sub_Array([4], [4], 1, 1) == True",
        "assert is_Sub_Array([4], [5], 1, 1) == False",
        "assert is_Sub_Array([1], [1, 2], 1, 2) == False",
    ),
    928: (
        "assert change_date_format('2000-02-29') == '29-02-2000'",
        "assert change_date_format('1999-12-31') == '31-12-1999'",
        "assert change_date_format('2024-11-03') == '03-11-2024'",
        "assert change_date_format('1900-01-01') == '01-01-1900'",
        "assert change_date_format('2024-03-09') == '09-03-2024'",
    ),
}


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def build_tasks(original_tasks: Iterable[dict]) -> list[dict]:
    """Return seven deterministic copies with original + additional assertions.

    Pass the frozen manifest's ``tasks`` list (extra unselected tasks are ignored).
    Require each selected original exactly once; reject changed source contracts
    or cases. Input order does not affect output order. No files are read/written.
    IDs end in ``-robustness-v1``; ``metadata.original_task_id`` joins saved outputs.
    Original split/family/prompt remain provenance, not new held-out assignments.
    """
    selected = {}
    for task in original_tasks:
        if not isinstance(task, dict):
            raise ValueError("original_tasks must contain task dictionaries")
        task_id = task.get("id")
        if task_id in TASK_IDS:
            if task_id in selected:
                raise ValueError(f"duplicate original task: {task_id}")
            selected[task_id] = task
    missing = set(TASK_IDS) - selected.keys()
    if missing:
        raise ValueError(f"missing original tasks: {', '.join(sorted(missing))}")

    result = []
    for number, (entry, row_hash, tests_hash) in SOURCE_CONTRACTS.items():
        original = selected[f"mbpp-full-{number}"]
        metadata = original.get("metadata", {})
        if (original.get("entry_point") != entry or metadata.get("dataset") != DATASET
                or metadata.get("revision") != REVISION or metadata.get("config") != "full"
                or metadata.get("source_id") != number
                or metadata.get("source_row_sha256") != row_hash):
            raise ValueError(f"source contract mismatch: {original['id']}")
        compiled = convert_mbpp_tests(
            original.get("test_list"), entry,
            test_setup_code=original.get("test_setup_code", ""),
            test_imports=original.get("test_imports", []),
            challenge_test_list=original.get("challenge_test_list", []),
        )
        if compiled["source_tests_sha256"] != tests_hash or any(
                original.get(key) != value for key, value in compiled.items()):
            raise ValueError(f"original tests or compiled cases changed: {original['id']}")
        # All seven pinned tasks have no challenge/setup tests. Keep their cases
        # byte-for-byte as a prefix; new assertions follow in this separate copy.
        extra = list(_EXTRA_TESTS[number])
        combined = original["test_list"] + extra
        task = copy.deepcopy(original)
        task.update(convert_mbpp_tests(combined, entry))
        task["id"] = f"{original['id']}-robustness-v1"
        task["test_list"] = combined
        task["metadata"]["original_task_id"] = original["id"]
        # This imported hash describes the original, not the diagnostic copy.
        imported_hash = task["metadata"].pop("task_sha256", None)
        task["metadata"]["robustness"] = {
            "version": VERSION,
            "classification": "post-hoc diagnostic coverage",
            "held_out_evidence": False,
            "training_label_eligible": False,
            "original_task_sha256": _digest(original),
            "original_imported_task_sha256": imported_hash,
            "original_source_tests_sha256": tests_hash,
            "original_case_count": len(original["cases"]),
            "additional_case_count": len(extra),
            "additional_assertions_sha256": _digest(extra),
            "combined_cases_sha256": _digest(task["cases"]),
            "expectation_method": "manual specification-derived literal equalities",
        }
        result.append(task)
    return result
