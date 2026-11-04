"""Verify generated Python inside disposable Modal Sandboxes.

Only arguments enter the Sandbox. Expected outputs and scoring stay in the
controller. AST checks reduce accidental misuse; they are not a security
boundary. The no-network, no-secret, no-mount Sandbox provides isolation.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import time
from typing import Any

VERIFIER_VERSION = "python-json-v2"
SANDBOX_CPU = 0.125
SANDBOX_MEMORY_MIB = 512
SANDBOX_TIMEOUT_SECONDS = 30
MAX_CODE_BYTES = 24_000
MAX_PAYLOAD_BYTES = 128_000
MAX_OUTPUT_BYTES = 65_536
MAX_CASES = 128
MAX_JSON_DEPTH = 32
ALLOWED_IMPORTS = frozenset({
    "math", "collections", "itertools", "functools", "bisect", "heapq", "statistics",
})
FORBIDDEN_NAMES = frozenset({
    "eval", "exec", "compile", "open", "input", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "__import__", "breakpoint", "help",
})


class CandidatePolicyError(ValueError):
    """The response uses Python features outside the pilot task policy."""


class TaskValidationError(ValueError):
    """The trusted task manifest is malformed; do not spend on execution."""


class CandidateOutputError(ValueError):
    """The sandbox returned an invalid or oversized result envelope."""


def _validate_json(value: Any, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise ValueError("json_too_deep")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _validate_json(item, depth + 1)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _validate_json(item, depth + 1)
        return
    raise ValueError("not_finite_json")


def _validate_task(task: Any, timeout: int) -> tuple[list[dict], dict]:
    try:
        if type(timeout) is not int or not 10 <= timeout <= SANDBOX_TIMEOUT_SECONDS:
            raise ValueError("invalid_sandbox_timeout")
        if not isinstance(task, dict):
            raise ValueError("invalid_task")
        entry = task.get("entry_point")
        if not isinstance(entry, str) or not entry.isidentifier() or entry.startswith("_"):
            raise ValueError("invalid_entry_point")
        cases = task.get("cases")
        if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
            raise ValueError("invalid_case_count")
        for case in cases:
            if not isinstance(case, dict) or not isinstance(case.get("args"), list) or "expected" not in case:
                raise ValueError("invalid_case")
            _validate_json(case["args"])
            _validate_json(case["expected"])
        tolerance = task.get("tolerance", {})
        if not isinstance(tolerance, dict) or set(tolerance) - {"rel_tol", "abs_tol"}:
            raise ValueError("invalid_tolerance")
        tolerance = {"rel_tol": tolerance.get("rel_tol", 1e-6),
                     "abs_tol": tolerance.get("abs_tol", 1e-8)}
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0
               for v in tolerance.values()):
            raise ValueError("invalid_tolerance")
        return cases, tolerance
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise TaskValidationError("invalid_task_or_settings") from exc


def extract_code(response: str) -> str:
    """Extract exactly one code block, or parse an unfenced Python response."""
    if not isinstance(response, str) or len(response.encode()) > MAX_CODE_BYTES:
        raise ValueError("candidate_too_large_or_not_text")
    # Models can prepend a private reasoning section; it is never executed.
    text = response.strip()
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1].strip()
    if "<think>" in text:
        raise ValueError("unfinished_reasoning")
    fences = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.DOTALL)
    if "```" in text:
        if len(fences) != 1 or text.count("```") != 2:
            raise ValueError("ambiguous_code_blocks")
        text = fences[0].strip()
    if not text:
        raise ValueError("empty_candidate")
    ast.parse(text)
    return text


def validate_code(code: str, entry_point: str) -> None:
    """Apply a deliberately small pure-Python task language before execution."""
    if not isinstance(entry_point, str) or not entry_point.isidentifier() or entry_point.startswith("_"):
        raise CandidatePolicyError("invalid_entry_point")
    tree = ast.parse(code)
    nodes = list(ast.walk(tree))
    if len(nodes) > 4_000:
        raise CandidatePolicyError("candidate_ast_too_large")
    if not any(isinstance(n, ast.FunctionDef) and n.name == entry_point for n in tree.body):
        raise CandidatePolicyError("entry_point_missing")
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign, ast.Expr)):
            raise CandidatePolicyError("unsupported_top_level_statement")
        if isinstance(node, ast.Expr) and not isinstance(node.value, ast.Constant):
            raise CandidatePolicyError("top_level_expression")
    for node in nodes:
        if isinstance(node, ast.Name) and (node.id in FORBIDDEN_NAMES or node.id.startswith("__")):
            raise CandidatePolicyError("forbidden_name")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise CandidatePolicyError("private_attribute")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.decorator_list:
            raise CandidatePolicyError("decorators_not_supported")
        if isinstance(node, ast.Import):
            if any(a.name not in ALLOWED_IMPORTS for a in node.names):
                raise CandidatePolicyError("unsupported_import")
        if isinstance(node, ast.ImportFrom):
            if node.level or node.module not in ALLOWED_IMPORTS or any(a.name.startswith("_") or a.name == "*" for a in node.names):
                raise CandidatePolicyError("unsupported_import")


def values_match(actual: Any, expected: Any, *, rel_tol: float = 1e-6, abs_tol: float = 1e-8) -> bool:
    """Compare JSON values without accepting NaN, infinity, or bool-as-number."""
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is bool and type(expected) is bool and actual == expected
    # Counts/indices are exact. Tolerance applies only to floating expectations.
    if type(expected) is int:
        return type(actual) in (int, float) and actual == expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        try:
            return math.isfinite(actual) and math.isfinite(expected) and math.isclose(actual, expected, rel_tol=rel_tol, abs_tol=abs_tol)
        except (OverflowError, ValueError):
            return actual == expected if type(actual) is int and type(expected) is int else False
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            values_match(a, b, rel_tol=rel_tol, abs_tol=abs_tol) for a, b in zip(actual, expected)
        )
    if isinstance(expected, dict):
        return isinstance(actual, dict) and actual.keys() == expected.keys() and all(
            values_match(actual[k], v, rel_tol=rel_tol, abs_tol=abs_tol) for k, v in expected.items()
        )
    return type(actual) is type(expected) and actual == expected


def score_outputs(outputs: Any, cases: list[dict], *, rel_tol: float = 1e-6, abs_tol: float = 1e-8) -> dict:
    if not isinstance(outputs, list) or len(outputs) != len(cases):
        return {"passed": False, "count": 0, "total": len(cases), "errors": ["invalid_output_count"]}
    count, errors = 0, []
    for index, (output, case) in enumerate(zip(outputs, cases)):
        if not isinstance(output, dict) or output.get("ok") is not True or "value" not in output:
            errors.append(f"case_{index}:execution_error")
        elif values_match(output.get("value"), case["expected"], rel_tol=rel_tol, abs_tol=abs_tol):
            count += 1
        else:
            errors.append(f"case_{index}:wrong_output")
    return {"passed": count == len(cases), "count": count, "total": len(cases), "errors": errors}


# Neither the child nor supervisor receives expected values. RLIMIT_FSIZE bounds
# ordinary child output files; the parent also bounds streamed, untrusted output.
_CHILD = r'''
import contextlib, json, os, resource, sys
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
        for args in payload["inputs"]:
            try:
                value = fn(*args)
                encoded = json.dumps(value, allow_nan=False)
                if len(encoded) > 8192:
                    raise ValueError("result_too_large")
                results.append({"ok": True, "value": json.loads(encoded)})
            except BaseException as exc:
                results.append({"ok": False, "error": type(exc).__name__})
encoded = json.dumps(results, allow_nan=False)
if len(encoded.encode()) > 65536:
    raise ValueError("output_too_large")
sys.stdout.write(encoded)
'''

_SUPERVISOR = r'''
import json, subprocess, sys, tempfile
payload = sys.argv[1]
child = sys.argv[2]
with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
    try:
        result = subprocess.run([sys.executable, "-I", "-S", "-c", child], input=payload.encode(),
                                stdout=output, stderr=errors, timeout=8)
        output.seek(0)
        data = output.read(65537)
        if result.returncode != 0 or len(data) > 65536:
            print(json.dumps({"error": "candidate_process_failed"}))
        else:
            print(data.decode())
    except subprocess.TimeoutExpired:
        print(json.dumps({"error": "candidate_timeout"}))
'''


def _read_output(stream: Any) -> str:
    chunks, size = [], 0
    for chunk in stream:
        size += len(chunk.encode())
        if size > MAX_OUTPUT_BYTES + 1:  # supervisor adds one newline
            raise CandidateOutputError("output_too_large")
        chunks.append(chunk)
    return "".join(chunks)


def _parse_output(raw: str) -> Any:
    try:
        output = json.loads(raw)
        _validate_json(output)
        return output
    except (ValueError, TypeError, RecursionError) as exc:
        raise CandidateOutputError("invalid_output_json") from exc


def verify_candidate(code: str, task: dict, app: Any, *, timeout: int = SANDBOX_TIMEOUT_SECONDS) -> dict:
    """Run one candidate; caller reserves budget before invoking this function.

    duration_seconds includes creation/provisioning/termination client wall time,
    not an authoritative Modal billed duration. No retries are performed here.
    """
    start = time.monotonic()
    result = {"passed": False, "count": 0, "total": 0, "errors": [],
              "verifier_version": VERIFIER_VERSION, "sandbox_id": None}
    sandbox = None
    stage = "preflight"
    try:
        cases, tolerance = _validate_task(task, timeout)
        result["total"] = len(cases)
        candidate = extract_code(code)
        validate_code(candidate, task["entry_point"])
        result["candidate_sha256"] = hashlib.sha256(candidate.encode()).hexdigest()
        payload = json.dumps({"code": candidate, "entry_point": task["entry_point"],
                              "inputs": [case["args"] for case in cases]}, allow_nan=False)
        if len(payload.encode()) > MAX_PAYLOAD_BYTES:
            raise ValueError("payload_too_large")
        stage = "provider"
        import modal

        sandbox = modal.Sandbox.create(
            "python", "-I", "-S", "-c", _SUPERVISOR, payload, _CHILD,
            app=app, image=modal.Image.debian_slim(python_version="3.11"),
            cpu=(SANDBOX_CPU, SANDBOX_CPU), memory=(SANDBOX_MEMORY_MIB, SANDBOX_MEMORY_MIB),
            timeout=timeout, block_network=True, secrets=[], volumes={},
            network_file_systems={}, env={}, runtime="gvisor",
            include_oidc_identity_token=False,
        )
        result["sandbox_id"] = sandbox.object_id
        raw = _read_output(sandbox.stdout)
        result["stdout"] = raw
        sandbox.wait()
        if sandbox.returncode != 0:
            result["errors"] = ["sandbox_process_failed"]
            result["error_kind"] = "candidate_execution"
        else:
            outputs = _parse_output(raw)
            # Bounded untrusted evidence, never an authoritative success flag.
            result["outputs"] = outputs
            if isinstance(outputs, dict) and type(outputs.get("error")) is str and outputs["error"] in {
                "candidate_process_failed", "candidate_timeout",
            }:
                result["errors"] = [outputs["error"]]
                result["error_kind"] = "candidate_execution"
            else:
                result.update(score_outputs(outputs, cases, **tolerance))
                if not result["passed"]:
                    result["error_kind"] = "candidate_execution"
    except TaskValidationError:
        result["errors"] = ["invalid_task_or_settings"]
        result["error_kind"] = "invalid_task"
    except CandidatePolicyError as exc:
        result["errors"] = [f"candidate_policy:{exc}"]
        result["error_kind"] = "candidate_policy"
    except CandidateOutputError as exc:
        result["errors"] = [str(exc)]
        result["error_kind"] = "candidate_execution"
    except Exception as exc:
        # Provider messages could include sensitive transport information.
        if stage == "preflight":
            result["errors"] = [f"invalid_candidate_or_payload:{type(exc).__name__}"]
            result["error_kind"] = "invalid_candidate"
        else:
            result["errors"] = [f"sandbox_error:{type(exc).__name__}"]
            result["error_kind"] = "infrastructure"
            result["infrastructure_error"] = True
    finally:
        if sandbox is not None:
            try:
                sandbox.terminate(wait=True)
            except Exception as exc:
                result["errors"].append(f"termination_error:{type(exc).__name__}")
                result["infrastructure_error"] = True
                result["error_kind"] = "infrastructure"
                result["passed"] = False
        result["duration_seconds"] = round(time.monotonic() - start, 6)
    return result
