"""Compile a bounded MBPP assertion subset; score outside candidate sandboxes.

No dataset source is eval/exec'd here. The parser constructs only finite builtin
values. Candidate execution exists exclusively in the remote child source.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import keyword
import math
import time
from typing import Any

from . import verification as base

MBPP_VERIFIER_VERSION = "mbpp-typed-v1"
VERIFICATION_MODE = "mbpp_typed_v1"
MAX_VALUE_DEPTH = 8
MAX_VALUE_NODES = 4096
MAX_INTEGER_BITS = 4096
MAX_TEST_BYTES = 24_000
MBPP_ALLOWED_IMPORTS = base.ALLOWED_IMPORTS | {"re", "string", "operator", "array"}
PROJECTIONS = frozenset({"set", "frozenset", "list", "tuple", "sorted"})


class UnsupportedTest(ValueError):
    """Stable exclusion reason for an entire unconverted MBPP task."""


UnsupportedMBPPTest = UnsupportedTest


def encode_value(value):
    """Typed JSON for exact builtin containers; shared with the remote child."""
    budget = [MAX_VALUE_NODES]

    def encode(item, depth):
        budget[0] -= 1
        if budget[0] < 0 or depth > MAX_VALUE_DEPTH:
            raise ValueError("value_too_complex")
        kind = type(item)
        if item is None:
            return ["none", None]
        if kind is bool:
            return ["bool", item]
        if kind is int and item.bit_length() <= MAX_INTEGER_BITS:
            return ["int", item]
        if kind is float and math.isfinite(item):
            return ["float", item]
        if kind is str and len(item.encode()) <= MAX_TEST_BYTES:
            return ["str", item]
        names = {list: "list", tuple: "tuple", set: "set", frozenset: "frozenset", dict: "dict"}
        if kind not in names or len(item) > MAX_VALUE_NODES:
            raise ValueError("unsupported_value")
        if kind is dict:
            items = [[encode(k, depth + 1), encode(v, depth + 1)] for k, v in item.items()]
        else:
            items = [encode(v, depth + 1) for v in item]
            if kind in (set, frozenset):
                items.sort(key=lambda v: json.dumps(v, ensure_ascii=True, allow_nan=False))
        return [names[kind], items]

    return encode(value, 0)


def decode_value(value):
    """Decode only bounded builtin values, never object hooks or code strings."""
    budget = [MAX_VALUE_NODES]

    def decode(node, depth):
        budget[0] -= 1
        if budget[0] < 0 or depth > MAX_VALUE_DEPTH:
            raise ValueError("value_too_complex")
        if type(node) is not list or len(node) != 2 or type(node[0]) is not str:
            raise ValueError("invalid_typed_value")
        tag, item = node
        scalar = {"none": type(None), "bool": bool, "int": int, "float": float, "str": str}
        if tag in scalar:
            if type(item) is not scalar[tag] or encode_value(item)[0] != tag:
                raise ValueError("invalid_scalar")
            return item
        if type(item) is not list or len(item) > MAX_VALUE_NODES:
            raise ValueError("invalid_container")
        if tag == "dict":
            result = {}
            for pair in item:
                if type(pair) is not list or len(pair) != 2:
                    raise ValueError("invalid_dict_pair")
                key, val = decode(pair[0], depth + 1), decode(pair[1], depth + 1)
                if key in result:
                    raise ValueError("duplicate_dict_key")
                result[key] = val
            return result
        constructors = {"list": list, "tuple": tuple, "set": set, "frozenset": frozenset}
        if tag not in constructors:
            raise ValueError("unknown_value_tag")
        result = constructors[tag](decode(v, depth + 1) for v in item)
        if tag in ("set", "frozenset") and len(result) != len(item):
            raise ValueError("duplicate_set_item")
        return result

    return decode(value, 0)


def _literal(node: ast.AST, depth: int = 0) -> Any:
    """Small data grammar; no arbitrary arithmetic, attributes, names or calls."""
    if depth > MAX_VALUE_DEPTH:
        raise UnsupportedTest("literal_too_deep")
    child = lambda n: _literal(n, depth + 1)
    if isinstance(node, ast.Constant) and type(node.value) in (type(None), bool, int, float, str):
        value = node.value
    elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        ctor = {ast.List: list, ast.Tuple: tuple, ast.Set: set}[type(node)]
        value = ctor(child(n) for n in node.elts)
    elif isinstance(node, ast.Dict) and all(n is not None for n in node.keys):
        value = {child(k): child(v) for k, v in zip(node.keys, node.values)}
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        number = child(node.operand)
        if type(number) not in (int, float):
            raise UnsupportedTest("unsupported_unary_literal")
        value = -number if isinstance(node.op, ast.USub) else number
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        constructors = {"set": set, "frozenset": frozenset, "tuple": tuple,
                        "list": list, "dict": dict, "sorted": sorted}
        if node.func.id not in constructors or node.keywords or len(node.args) > 1:
            raise UnsupportedTest("unsupported_literal_call")
        value = constructors[node.func.id](*(child(n) for n in node.args))
    else:
        raise UnsupportedTest("nonliteral_test_value")
    encode_value(value)  # bound values from constructors, numbers and strings
    return value


def _parse_test(source: str, entry_point: str | None) -> tuple[str, dict]:
    if type(source) is not str or len(source.encode()) > MAX_TEST_BYTES:
        raise UnsupportedTest("test_too_large_or_not_text")
    tree = ast.parse(source.strip())
    if sum(1 for _ in ast.walk(tree)) > MAX_VALUE_NODES:
        raise UnsupportedTest("test_ast_too_large")
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Assert):
        raise UnsupportedTest("expected_one_assert")
    assertion = tree.body[0]
    if assertion.msg is not None:
        raise UnsupportedTest("assert_message_unsupported")
    comparison = assertion.test
    if not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1 or not isinstance(comparison.ops[0], ast.Eq):
        raise UnsupportedTest("expected_equality_assert")
    left, right = comparison.left, comparison.comparators[0]
    # Support either side of equality without interpreting candidate expressions.
    try:
        expected = _literal(right)
        actual = left
    except (ValueError, TypeError, OverflowError):
        expected = _literal(left)
        actual = right
    projections = []
    while (isinstance(actual, ast.Call) and isinstance(actual.func, ast.Name)
           and actual.func.id in PROJECTIONS and actual.func.id != entry_point):
        if len(actual.args) != 1 or actual.keywords:
            raise UnsupportedTest("unsupported_projection")
        projections.append(actual.func.id)
        actual = actual.args[0]
    if not isinstance(actual, ast.Call) or not isinstance(actual.func, ast.Name):
        raise UnsupportedTest("expected_direct_function_call")
    name = actual.func.id
    if not name.isidentifier() or name.startswith("_") or keyword.iskeyword(name) or name in PROJECTIONS | {"dict"}:
        raise UnsupportedTest("unsupported_entry_point")
    if entry_point is not None and name != entry_point:
        raise UnsupportedTest("multiple_or_mismatched_entry_points")
    if any(k.arg is None for k in actual.keywords):
        raise UnsupportedTest("keyword_unpacking_unsupported")
    kwargs = {k.arg: _literal(k.value) for k in actual.keywords}
    if len(kwargs) != len(actual.keywords):
        raise UnsupportedTest("duplicate_keyword")
    return name, {"args": encode_value(tuple(_literal(n) for n in actual.args)),
                  "kwargs": encode_value(kwargs), "expected": encode_value(expected),
                  "projections": list(reversed(projections))}


def convert_mbpp_tests(test_list: list[str], entry_point: str | None = None, *,
                       test_setup_code: str = "", test_imports: list[str] | tuple = (),
                       challenge_test_list: list[str] | tuple = ()) -> dict:
    """Convert every supplied assertion or reject the whole task with a reason.

    Setup/import code is never executed or injected. Even import-only setup is
    rejected because it can alter the meaning of an otherwise builtin call.
    """
    try:
        if (type(test_setup_code) is not str or test_setup_code.strip()
                or type(test_imports) not in (list, tuple) or test_imports):
            raise UnsupportedTest("test_setup_or_imports_unsupported")
        if type(test_list) is not list or not test_list or type(challenge_test_list) not in (list, tuple):
            raise UnsupportedTest("invalid_test_lists")
        tests = test_list + list(challenge_test_list)
        if len(tests) > base.MAX_CASES:
            raise UnsupportedTest("too_many_tests")
        if entry_point is not None and (type(entry_point) is not str or not entry_point.isidentifier()):
            raise UnsupportedTest("invalid_entry_point")
        cases = []
        for index, source in enumerate(tests):
            entry_point, case = _parse_test(source, entry_point)
            case["source_test_index"] = index
            case["source_test_kind"] = "test" if index < len(test_list) else "challenge"
            cases.append(case)
        task = {"verification_mode": VERIFICATION_MODE, "entry_point": entry_point,
                "cases": cases, "mbpp_compiler_version": MBPP_VERIFIER_VERSION,
                "source_tests_sha256": hashlib.sha256(json.dumps(tests, ensure_ascii=True).encode()).hexdigest(),
                "source_test_count": len(test_list), "challenge_test_count": len(challenge_test_list)}
        _validate_task(task, base.SANDBOX_TIMEOUT_SECONDS)
        return task
    except UnsupportedTest:
        raise
    except (ValueError, TypeError, SyntaxError, OverflowError, RecursionError) as exc:
        raise UnsupportedTest(f"invalid_or_unsupported_test:{type(exc).__name__}") from exc


def convert_mbpp_task(task: dict) -> dict:
    """Compile a raw dataset manifest, preserving its provenance and prompt."""
    if type(task) is not dict or task.get("verification_mode", "python_assertions") != "python_assertions":
        raise UnsupportedTest("expected_raw_mbpp_task")
    compiled = convert_mbpp_tests(task.get("test_list"), task.get("entry_point"),
                                  test_setup_code=task.get("test_setup_code", ""),
                                  test_imports=task.get("test_imports", []),
                                  challenge_test_list=task.get("challenge_test_list", []))
    return {**task, **compiled}


def convert_mbpp_record(record: dict) -> dict:
    """Alias for full/sanitized MBPP rows; code fields are never read or executed."""
    return convert_mbpp_task(record)


def _validate_task(task: dict, timeout: int) -> None:
    try:
        if type(timeout) is not int or not 10 <= timeout <= base.SANDBOX_TIMEOUT_SECONDS:
            raise ValueError("invalid_timeout")
        if type(task) is not dict or task.get("verification_mode") != VERIFICATION_MODE:
            raise ValueError("invalid_mode")
        if task.get("mbpp_compiler_version") != MBPP_VERIFIER_VERSION:
            raise ValueError("invalid_compiler_version")
        entry = task.get("entry_point")
        if type(entry) is not str or not entry.isidentifier() or entry.startswith("_") or keyword.iskeyword(entry):
            raise ValueError("invalid_entry_point")
        cases = task.get("cases")
        if type(cases) is not list or not 1 <= len(cases) <= base.MAX_CASES:
            raise ValueError("invalid_cases")
        regular, challenge = task.get("source_test_count"), task.get("challenge_test_count")
        if (type(regular) is not int or regular < 1 or type(challenge) is not int
                or challenge < 0 or regular + challenge != len(cases)):
            raise ValueError("test_count_mismatch")
        source_hash = task.get("source_tests_sha256")
        if type(source_hash) is not str or len(source_hash) != 64 or any(c not in "0123456789abcdef" for c in source_hash):
            raise ValueError("invalid_source_hash")
        for index, case in enumerate(cases):
            if (type(case["source_test_index"]) is not int or case["source_test_index"] != index
                    or case["source_test_kind"] != ("test" if index < regular else "challenge")):
                raise ValueError("test_identity_mismatch")
            args, kwargs = decode_value(case["args"]), decode_value(case["kwargs"])
            decode_value(case["expected"])
            if type(args) is not tuple or type(kwargs) is not dict or any(type(k) is not str for k in kwargs):
                raise ValueError("invalid_call_arguments")
            projections = case["projections"]
            if type(projections) is not list or len(projections) > MAX_VALUE_DEPTH:
                raise ValueError("invalid_projections")
            if any(type(p) is not str or p not in PROJECTIONS for p in projections):
                raise ValueError("invalid_projection")
        if len(json.dumps(cases, allow_nan=False).encode()) > base.MAX_PAYLOAD_BYTES:
            raise ValueError("cases_too_large")
    except (ValueError, KeyError, TypeError, OverflowError, RecursionError) as exc:
        raise base.TaskValidationError("invalid_mbpp_task") from exc


def score_mbpp_outputs(outputs: Any, cases: list[dict]) -> dict:
    """Evaluate equality of decoded builtins in the parent; no candidate methods."""
    total, count, errors = len(cases), 0, []
    if type(outputs) is not list or len(outputs) != total:
        return {"passed": False, "count": 0, "total": total, "errors": ["invalid_output_count"]}
    constructors = {"set": set, "frozenset": frozenset, "list": list, "tuple": tuple, "sorted": sorted}
    for index, (output, case) in enumerate(zip(outputs, cases)):
        if type(output) is not dict or output.get("ok") is not True or "value" not in output:
            errors.append(f"case_{index}:execution_error")
            continue
        try:
            actual = decode_value(output["value"])
            for projection in case["projections"]:
                actual = constructors[projection](actual)
                encode_value(actual)
            expected = decode_value(case["expected"])
            # Deliberately Python ==, including numeric bool/int equality, with
            # no tolerance. This preserves the source assertion's semantics.
            match = actual == expected
        except (ValueError, TypeError, OverflowError, RecursionError):
            errors.append(f"case_{index}:invalid_result")
            continue
        if match:
            count += 1
        else:
            errors.append(f"case_{index}:wrong_output")
    return {"passed": count == total, "count": count, "total": total, "errors": errors}


def _child_source() -> str:
    # Ship our trusted codec implementation as source, with no project mounts.
    # This function constructs a string; it never executes the string locally.
    preamble = ("import contextlib, json, math, os, resource, sys\n"
                f"MAX_VALUE_DEPTH={MAX_VALUE_DEPTH}\nMAX_VALUE_NODES={MAX_VALUE_NODES}\n"
                f"MAX_INTEGER_BITS={MAX_INTEGER_BITS}\nMAX_TEST_BYTES={MAX_TEST_BYTES}\n")
    return preamble + inspect.getsource(encode_value) + "\n" + inspect.getsource(decode_value) + r'''
resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
resource.setrlimit(resource.RLIMIT_NPROC, (16, 16))
payload = json.loads(sys.stdin.read(128001))
namespace = {"__name__": "candidate"}
results = []
with open(os.devnull, "w") as discard:
    with contextlib.redirect_stdout(discard), contextlib.redirect_stderr(discard):
        exec(compile(payload["code"], "candidate.py", "exec"), namespace)
        fn = namespace[payload["entry_point"]]
        for call in payload["inputs"]:
            try:
                value = fn(*decode_value(call["args"]), **decode_value(call["kwargs"]))
                encoded = encode_value(value)
                if len(json.dumps(encoded, allow_nan=False).encode()) > 8192:
                    raise ValueError("result_too_large")
                results.append({"ok": True, "value": encoded})
            except BaseException as exc:
                results.append({"ok": False, "error": type(exc).__name__})
encoded = json.dumps(results, allow_nan=False)
if len(encoded.encode()) > 65536:
    raise ValueError("output_too_large")
sys.stdout.write(encoded)
'''


def verify_mbpp_candidate(code: str, task: dict, app: Any, *, timeout: int = base.SANDBOX_TIMEOUT_SECONDS) -> dict:
    """Verify a compiled MBPP task; caller must reserve before any paid launch."""
    start = time.monotonic()
    result = {"passed": False, "count": 0, "total": 0, "errors": [],
              "verifier_version": MBPP_VERIFIER_VERSION, "sandbox_id": None}
    try:
        _validate_task(task, timeout)
        result["total"] = len(task["cases"])
        candidate = base.extract_code(code)
        base.validate_code(candidate, task["entry_point"], allowed_imports=MBPP_ALLOWED_IMPORTS)
        result["candidate_sha256"] = hashlib.sha256(candidate.encode()).hexdigest()
        result["source_tests_sha256"] = task.get("source_tests_sha256")
        payload = json.dumps({"code": candidate, "entry_point": task["entry_point"],
                              "inputs": [{"args": c["args"], "kwargs": c["kwargs"]} for c in task["cases"]]},
                             allow_nan=False)
        if len(payload.encode()) > base.MAX_PAYLOAD_BYTES:
            raise ValueError("payload_too_large")
        result.update(base._run_sandbox(payload, app, timeout, child=_child_source(), total=len(task["cases"]),
                                       score=lambda outputs: score_mbpp_outputs(outputs, task["cases"])))
    except base.TaskValidationError:
        result["errors"] = ["invalid_mbpp_task"]
        result["error_kind"] = "invalid_task"
    except base.CandidatePolicyError as exc:
        result["errors"] = [f"candidate_policy:{exc}"]
        result["error_kind"] = "candidate_policy"
    except Exception as exc:
        result["errors"] = [f"invalid_candidate_or_payload:{type(exc).__name__}"]
        result["error_kind"] = "invalid_candidate"
    finally:
        result["duration_seconds"] = round(time.monotonic() - start, 6)
    return result
