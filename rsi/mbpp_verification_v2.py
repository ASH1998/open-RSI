"""Versioned MBPP transport for exact standard-library mapping subclasses.

Accepts frozen v1 tasks unchanged. Candidate code runs only in disposable remote
sandboxes; tests, projections and scoring remain in the trusted parent.
"""
from __future__ import annotations

from collections import Counter as _Counter, OrderedDict as _OrderedDict, defaultdict as _DefaultDict
import hashlib
import inspect
import json
import math
from pathlib import Path
import time
from typing import Any

from . import mbpp_verification as v1
from . import verification as base

MBPP_VERIFIER_VERSION = "mbpp-typed-v2"
VERIFIER_VERSION = MBPP_VERIFIER_VERSION
MAX_VALUE_DEPTH = v1.MAX_VALUE_DEPTH
MAX_VALUE_NODES = v1.MAX_VALUE_NODES
MAX_INTEGER_BITS = v1.MAX_INTEGER_BITS
MAX_TEST_BYTES = v1.MAX_TEST_BYTES
MBPP_ALLOWED_IMPORTS = v1.MBPP_ALLOWED_IMPORTS


def encode_value(value):
    """Encode finite data from exact allowed types; never traverse arbitrary subclasses.

    Mapping subclasses get distinct tags to retain Python equality semantics.
    defaultdict factories and instance attributes are deliberately not serialized.
    """
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
        names = {list: "list", tuple: "tuple", set: "set", frozenset: "frozenset", dict: "dict",
                 _OrderedDict: "ordered_dict", _DefaultDict: "default_dict", _Counter: "counter"}
        if not any(kind is allowed for allowed in names):
            raise ValueError("unsupported_value")
        if kind in (dict, _OrderedDict, _DefaultDict, _Counter):
            # Use trusted implementations, ignoring per-instance overridden
            # items()/__iter__ on Counter. OrderedDict's own order is essential.
            if dict.__len__(item) > MAX_VALUE_NODES:
                raise ValueError("value_too_complex")
            pairs = _OrderedDict.items(item) if kind is _OrderedDict else dict.items(item)
            items = [[encode(k, depth + 1), encode(v, depth + 1)] for k, v in pairs]
        else:
            if len(item) > MAX_VALUE_NODES:
                raise ValueError("value_too_complex")
            items = [encode(v, depth + 1) for v in item]
            if kind in (set, frozenset):
                items.sort(key=lambda v: json.dumps(v, ensure_ascii=True, allow_nan=False))
        return [names[kind], items]

    return encode(value, 0)


def decode_value(value):
    """Reconstruct only exact builtin/allowlisted stdlib types from bounded JSON.

    No class names, factories, object hooks, pickle, or arbitrary callables cross
    this boundary. defaultdict(None) is sufficient for equality and projections.
    """
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
        if tag in ("dict", "ordered_dict", "default_dict", "counter"):
            if tag == "ordered_dict":
                result = _OrderedDict()
            elif tag == "default_dict":
                result = _DefaultDict(None)
            elif tag == "counter":
                result = _Counter()
            else:
                result = {}
            for pair in item:
                if type(pair) is not list or len(pair) != 2:
                    raise ValueError("invalid_dict_pair")
                key, val = decode(pair[0], depth + 1), decode(pair[1], depth + 1)
                if key in result:
                    raise ValueError("duplicate_dict_key")
                # Counter(iterable_of_pairs) would count pairs, so set entries
                # explicitly. OrderedDict must update its order tracking too.
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


def score_mbpp_outputs(outputs: Any, cases: list[dict]) -> dict:
    """Compare decoded trusted data with unchanged v1 authoritative expectations."""
    total, count, errors, diagnostics = len(cases), 0, [], []
    if type(outputs) is not list or len(outputs) != total:
        return {"passed": False, "count": 0, "total": total, "errors": ["invalid_output_count"],
                "case_diagnostics": [{"case_index": None, "error_stage": "output", "error": "invalid_output_count"}]}
    constructors = {"set": set, "frozenset": frozenset, "list": list, "tuple": tuple, "sorted": sorted}
    for index, (output, case) in enumerate(zip(outputs, cases)):
        if type(output) is not dict or output.get("ok") is not True or "value" not in output:
            errors.append(f"case_{index}:execution_error")
            stage = output.get("error_stage") if type(output) is dict else None
            error = output.get("error") if type(output) is dict else None
            diagnostics.append({"case_index": index,
                                "error_stage": stage if stage in ("candidate_call", "encode") else "output",
                                "error": error if type(error) is str and len(error) <= 80 and error.isidentifier()
                                else "ExecutionError"})
            continue
        stage = "decode"
        try:
            actual = decode_value(output["value"])
            stage = "projection_comparison"
            for projection in case["projections"]:
                actual = constructors[projection](actual)
                encode_value(actual)
            # Frozen source tests use only v1's literal builtin expectations.
            expected = v1.decode_value(case["expected"])
            match = actual == expected
        except (ValueError, TypeError, OverflowError, RecursionError) as exc:
            errors.append(f"case_{index}:invalid_result")
            diagnostics.append({"case_index": index, "error_stage": stage, "error": type(exc).__name__})
            continue
        if match:
            count += 1
        else:
            errors.append(f"case_{index}:wrong_output")
            diagnostics.append({"case_index": index, "error_stage": "projection_comparison", "error": "wrong_output"})
    return {"passed": count == total, "count": count, "total": total,
            "errors": errors, "case_diagnostics": diagnostics}


def _child_source() -> str:
    """Return trusted harness source; constructing this string executes no candidate."""
    preamble = ("import contextlib, json, math, os, resource, sys\n"
                "from collections import Counter as _Counter, OrderedDict as _OrderedDict, defaultdict as _DefaultDict\n"
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
            except BaseException as exc:
                results.append({"ok": False, "error": type(exc).__name__, "error_stage": "candidate_call"})
                continue
            try:
                encoded = encode_value(value)
                if len(json.dumps(encoded, allow_nan=False).encode()) > 8192:
                    raise ValueError("result_too_large")
                results.append({"ok": True, "value": encoded})
            except BaseException as exc:
                results.append({"ok": False, "error": type(exc).__name__, "error_stage": "encode"})
encoded = json.dumps(results, allow_nan=False)
if len(encoded.encode()) > 65536:
    raise ValueError("output_too_large")
sys.stdout.write(encoded)
'''


def evaluator_source_hashes() -> dict[str, str]:
    """Inventory of this evaluator, unchanged dependencies, and exact child source."""
    modules = {"rsi/mbpp_verification_v2.py": __file__,
               "rsi/mbpp_verification.py": v1.__file__, "rsi/verification.py": base.__file__}
    result = {name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name, path in modules.items()}
    result["child_source"] = hashlib.sha256(_child_source().encode()).hexdigest()
    return result


def verify_mbpp_candidate(code: str, task: dict, app: Any, *, timeout: int = base.SANDBOX_TIMEOUT_SECONDS) -> dict:
    """Rescore original frozen v1 tasks using v2; task fields are never modified.

    Main reserves each paid stage before invoking this function. This does not
    generate model outputs, train, retry, or write any original result record.
    """
    start = time.monotonic()
    result = {"passed": False, "count": 0, "total": 0, "errors": [],
              "verifier_version": MBPP_VERIFIER_VERSION,
              "source_compiler_version": v1.MBPP_VERIFIER_VERSION, "sandbox_id": None}
    try:
        v1._validate_task(task, timeout)
        result["total"] = len(task["cases"])
        result["evaluator_source_hashes"] = evaluator_source_hashes()
        candidate = base.extract_code(code)
        base.validate_code(candidate, task["entry_point"], allowed_imports=MBPP_ALLOWED_IMPORTS)
        result["candidate_sha256"] = hashlib.sha256(candidate.encode()).hexdigest()
        result["source_tests_sha256"] = task["source_tests_sha256"]
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


def calibration_cases() -> list[dict]:
    """Hand-authored remote calibration, never saved model/reference completions.

    Each item has id, code, original-format task, expected_passed, expected_count,
    and optional expected_error_stage for failed output records. Caller reserves and
    executes remotely; constructing this list performs only static compilation.
    """
    specifications = [
        ("builtin_identity", 'def solve(x): return x',
         ['assert solve((1, 2)) == (1, 2)', 'assert solve({1: [True, None]}) == {1: [True, None]}'], True, None),
        ("ordered_nested", 'from collections import OrderedDict\ndef solve(x): return [OrderedDict()] * x',
         ['assert solve(2) == [{}, {}]'], True, None),
        ("ordered_iteration", 'from collections import OrderedDict\ndef solve(x):\n d = OrderedDict([(1, "a"), (2, "b")])\n d.move_to_end(1)\n return d',
         ['assert list(solve(0)) == [2, 1]', 'assert solve(0) == {1: "a", 2: "b"}'], True, None),
        ("default_factory_never_called", 'from collections import defaultdict\ndef factory():\n raise RuntimeError("factory called")\ndef solve(x): return defaultdict(factory, {"x": x})',
         ['assert solve(3) == {"x": 3}'], True, None),
        ("counter_mapping", 'from collections import Counter\ndef solve(x): return Counter(x)',
         ['assert solve([1, 1, 2]) == {1: 2, 2: 1}'], True, None),
        ("nested_mapping_types", 'from collections import Counter, OrderedDict, defaultdict\ndef solve(x):\n return (OrderedDict([("a", Counter({1: 2}))]), [defaultdict(list, {2: [3]})])',
         ['assert solve(0) == ({"a": {1: 2}}, [{2: [3]}])'], True, None),
        ("wrong_mapping_value", 'from collections import OrderedDict\ndef solve(x): return OrderedDict(a=2)',
         ['assert solve(0) == {"a": 1}'], False, None),
        ("counter_zero_is_not_absent_dict_key", 'from collections import Counter\ndef solve(x): return Counter(a=1, b=0)',
         ['assert solve(0) == {"a": 1}'], False, None),
        ("tuple_is_not_list", 'def solve(x): return (1, 2)',
         ['assert solve(0) == [1, 2]'], False, None),
        ("custom_subclass_rejected", 'def solve(x):\n class Pretend(dict):\n  def __eq__(self, other): return True\n return Pretend(a=1)',
         ['assert solve(0) == {"a": 1}'], False, "encode"),
        ("callable_return_rejected", 'def solve(x): return lambda: x',
         ['assert solve(0) == 0'], False, "encode"),
        ("candidate_exception", 'def solve(x): raise ValueError("synthetic")',
         ['assert solve(0) == 0'], False, "candidate_call"),
    ]
    result = []
    for name, code, tests, expected, phase in specifications:
        task = v1.convert_mbpp_tests(tests, 'solve')
        record = {"id": name, "code": code, "task": task, "expected_passed": expected,
                  "expected_count": len(tests) if expected else 0}
        if phase:
            record["expected_error_stage"] = phase
        result.append(record)
    return result
