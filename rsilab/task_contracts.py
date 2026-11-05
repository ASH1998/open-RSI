"""Apply and replay reviewed MBPP task contracts offline."""
from __future__ import annotations

import ast
from copy import deepcopy
from io import StringIO
from inspect import Parameter, Signature
import re
import tokenize

from rsi.mbpp_verification import MAX_TEST_BYTES, convert_mbpp_tests, decode_value, encode_value
from rsi.mbpp_verification_v2 import score_mbpp_outputs
from rsi.verification import MAX_CASES
from rsilab.coding_data import _literal_text
from rsilab.core import digest

__all__ = ["apply_task_contracts", "replay_task_contracts", "score_task_contract_outputs"]

VERSION = "mbpp-task-contracts-v1"
_SIGNATURE_MARKER = "\n\nRequired signature:\n"
_REVIEW_FIELDS = {"task_id", "source_sha256", "clarified_prompt", "review_note", "boundaries"}


def _text(value, field, limit=30_000):
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise ValueError(f"Invalid {field}: expected nonempty text of at most {limit} characters")
    return value


def _signature_and_prompt(task, clarified):
    original = _text(task["prompt"], "source prompt")
    before, marker, declaration = original.partition(_SIGNATURE_MARKER)
    preamble, separator, description = before.partition("\n\n")
    if not marker or not separator or not description.strip() or "\n" in declaration.strip():
        raise ValueError("Source prompt requires a policy, description and one signature line")
    tree = ast.parse(declaration.strip() + "\n    pass")
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("Invalid required function signature")
    function = tree.body[0]
    args = function.args
    if (function.name != task["entry_point"] or args.posonlyargs or args.vararg or args.kwonlyargs
            or args.kwarg or args.defaults or function.decorator_list):
        raise ValueError("Expected the source entry point and fixed positional-or-keyword parameters")
    signature = Signature([Parameter(arg.arg, Parameter.POSITIONAL_OR_KEYWORD) for arg in args.args])
    clarified = _text(clarified, "clarified_prompt")
    if _SIGNATURE_MARKER in clarified:
        new_before, _, new_declaration = clarified.partition(_SIGNATURE_MARKER)
        new_policy, new_separator, new_description = new_before.partition("\n\n")
        if (new_policy != preamble or not new_separator or not new_description.strip()
                or new_declaration != declaration):
            raise ValueError("Clarification changed source policy or required signature")
        prompt = clarified
    else:
        if "Required signature:" in clarified or clarified.startswith(preamble):
            raise ValueError("Malformed clarified prompt framing")
        prompt = preamble + "\n\n" + clarified + marker + declaration
    return signature, _text(prompt, "derived prompt")


def _compile(task, challenges):
    return convert_mbpp_tests(task["test_list"], task["entry_point"],
                              challenge_test_list=challenges,
                              test_setup_code=task.get("test_setup_code", ""),
                              test_imports=task.get("test_imports", []))


def _call_identity(signature, case):
    # Bind by parameter name so alternate keyword/positional spellings collide.
    bound = signature.bind(*decode_value(case["args"]), **decode_value(case["kwargs"]))
    return digest({key: encode_value(value) for key, value in bound.arguments.items()})


def _add_call(seen, signature, case, *, inherited=False):
    call_key = _call_identity(signature, case)
    outcome = digest([case["projections"], case["expected"]])
    outcomes = seen.setdefault(call_key, set())
    if outcomes and not inherited:
        if outcome not in outcomes:
            raise ValueError("Conflicting expectations or projections for the same call")
        raise ValueError("Duplicate call")
    outcomes.add(outcome)
    return call_key


def _visible_literal_calls(prompt, entry, signature):
    """Extract bounded direct literal calls embedded in otherwise arbitrary prose."""
    visible = set()
    for index, match in enumerate(re.finditer(rf"(?<!\w){re.escape(entry)}\s*\(", prompt)):
        if index >= MAX_CASES:
            raise ValueError("Too many entry point mentions to check in the prompt")
        tokens, depth = [], 0
        snippet = prompt[match.start():match.start() + MAX_TEST_BYTES]
        try:
            for token in tokenize.generate_tokens(StringIO(snippet).readline):
                tokens.append((token.type, token.string))
                if token.type != tokenize.OP:
                    continue
                if token.string in ("(", "[", "{"):
                    depth += 1
                elif token.string in (")", "]", "}"):
                    depth -= 1
                    if depth == 0:
                        expr = tokenize.untokenize(tokens)
                        case = convert_mbpp_tests([f"assert {expr} == None"], entry)["cases"][0]
                        visible.add(_call_identity(signature, case))
                        break
        except (tokenize.TokenError, SyntaxError, ValueError, TypeError):
            # A function signature or prose expression can contain nonliteral names.
            continue
    return visible


def _boundary(boundary, task, signature, seen, names, visible_calls):
    if type(boundary) is not dict or set(boundary) != {"name", "call", "expected"}:
        raise ValueError("A boundary requires exactly name, call and expected")
    name = _text(boundary["name"], "boundary name", 200)
    if name != name.strip() or name in names:
        raise ValueError("Invalid or duplicate boundary name")
    names.add(name)
    call = _text(boundary["call"], "boundary call", MAX_TEST_BYTES).strip()
    expression = ast.parse(call, mode="eval").body
    if (not isinstance(expression, ast.Call) or not isinstance(expression.func, ast.Name)
            or expression.func.id != task["entry_point"]):
        raise ValueError("Boundary must directly call the required entry point")
    # Use the production compiler's bounded literal grammar. It never executes
    # the assertion. Round-trip the independent tagged value through that grammar.
    expected = boundary["expected"]
    literal = _literal_text(decode_value(expected))
    assertion = f"assert {ast.unparse(expression)} == {literal}"
    case = convert_mbpp_tests([assertion], task["entry_point"])["cases"][0]
    if digest(case["expected"]) != digest(expected):
        raise ValueError("Boundary expected value failed typed literal round trip")
    if _add_call(seen, signature, case) in visible_calls:
        raise ValueError("Hidden boundary call appears in the student prompt")
    return assertion


def _derive(task, review):
    if type(task) is not dict or type(review) is not dict or set(review) != _REVIEW_FIELDS:
        raise ValueError("Expected a task and a review with the documented fields")
    task_id = _text(task["id"], "task ID", 200)
    if task["split"] != "train" or task["metadata"]["source_split"] != "train":
        raise ValueError("Task contracts require native training tasks")
    if task_id != review["task_id"] or digest(task) != review["source_sha256"]:
        raise ValueError(f"Review task order or source digest mismatch for {task_id}")
    _text(review["review_note"], "review_note")
    if type(review["boundaries"]) is not list:
        raise ValueError("boundaries must be a list")
    signature, prompt = _signature_and_prompt(task, review["clarified_prompt"])
    original_challenges = task["challenge_test_list"]
    if type(original_challenges) is not list:
        raise ValueError("Source challenge_test_list must be a list")
    original = _compile(task, original_challenges)
    if len(original["cases"]) + len(review["boundaries"]) > MAX_CASES:
        raise ValueError("Derived task exceeds the evaluator case limit")
    for key, value in original.items():
        if digest(task[key]) != digest(value):
            raise ValueError(f"Source {key} differs from its compiled assertions")
    seen = {}
    for case in original["cases"]:
        _add_call(seen, signature, case, inherited=True)
    names = set()
    visible = _visible_literal_calls(prompt, task["entry_point"], signature) if review["boundaries"] else set()
    additions = [_boundary(b, task, signature, seen, names, visible) for b in review["boundaries"]]
    challenges = original_challenges + additions
    compiled = _compile(task, challenges)
    offset = len(original["cases"])
    if digest(compiled["cases"][:offset]) != digest(original["cases"]):
        raise ValueError("Derived task changed original cases")
    derived = deepcopy(task)
    derived.update(compiled, challenge_test_list=challenges, prompt=prompt)
    lineage = {"task_id": task_id, "source_sha256": review["source_sha256"],
               "review_sha256": digest(review), "derived_sha256": digest(derived),
               "source_tests_sha256": task["source_tests_sha256"],
               "derived_tests_sha256": compiled["source_tests_sha256"],
               "source_case_count": offset,
               "boundaries": [{"name": b["name"], "case_index": i,
                               "case_sha256": digest(compiled["cases"][i])}
                              for i, b in enumerate(review["boundaries"], start=offset)]}
    return derived, lineage


def apply_task_contracts(original_tasks, reviews):
    """Derive evaluator tasks and public prompts using one ordered review per source.

    See docs/TASK_CONTRACTS.md for the review schema, tagged values and hash scope.
    Inputs are JSON data. No reference or candidate code executes here.
    """
    if (type(original_tasks) is not list or type(reviews) is not list
            or not original_tasks or len(reviews) != len(original_tasks)):
        raise ValueError("Supply one ordered review per task in a nonempty training list")
    tasks, prompts, lineage, ids = [], [], [], set()
    for index, (source, review) in enumerate(zip(original_tasks, reviews)):
        try:
            derived, link = _derive(source, review)
            task_id = derived["id"]
            if task_id in ids:
                raise ValueError("Duplicate task ID")
            ids.add(task_id)
            tasks.append(derived)
            prompts.append({"id": task_id, "prompt": derived["prompt"]})
            lineage.append(link)
        except (ValueError, KeyError, TypeError, SyntaxError, OverflowError, RecursionError) as exc:
            raise ValueError(f"Task contract at index {index}: {exc}") from exc
    record = {"version": VERSION, "source_sha256": digest(original_tasks), "reviews_sha256": digest(reviews),
              "tasks": tasks, "prompts": prompts, "lineage": lineage}
    return {**record, "sha256": digest(record)}


def replay_task_contracts(original_tasks, reviews, manifest, *, expected_sha256=None):
    """Rebuild from the supplied sources and reviews and verify the complete manifest."""
    rebuilt = apply_task_contracts(original_tasks, reviews)
    if expected_sha256 is not None and expected_sha256 != rebuilt["sha256"]:
        raise ValueError("Task contract digest differs from the external pin")
    if type(manifest) is not dict or digest(rebuilt) != digest(manifest):
        raise ValueError("Saved task contract differs from replay")
    return rebuilt


def _typed_identity(node):
    """Hashable identity of a transport value already validated by the scorer."""
    tag, value = node
    if tag in ("dict", "default_dict", "counter", "ordered_dict"):
        pairs = ((_typed_identity(k), _typed_identity(v)) for k, v in value)
        return tag, tuple(pairs) if tag == "ordered_dict" else frozenset(pairs)
    if tag in ("set", "frozenset"):
        return tag, frozenset(_typed_identity(v) for v in value)
    if tag in ("list", "tuple"):
        return tag, tuple(_typed_identity(v) for v in value)
    return tag, value


def _scoring_partition(manifest, task_id, expected_sha256):
    if (type(manifest) is not dict or manifest.get("version") != VERSION
            or manifest.get("sha256") != digest({k: v for k, v in manifest.items() if k != "sha256"})):
        raise ValueError("Invalid task contract manifest seal or version")
    if expected_sha256 is not None and manifest["sha256"] != expected_sha256:
        raise ValueError("Task contract digest differs from the external pin")
    tasks = [t for t in manifest["tasks"] if t["id"] == task_id]
    links = [link for link in manifest["lineage"] if link["task_id"] == task_id]
    if len(tasks) != 1 or len(links) != 1 or digest(tasks[0]) != links[0]["derived_sha256"]:
        raise ValueError("Missing, duplicate, or detached task contract")
    cases, link = tasks[0]["cases"], links[0]
    offset = link["source_case_count"]
    if (type(offset) is not int or not 1 <= offset <= len(cases)
            or len(link["boundaries"]) != len(cases) - offset):
        raise ValueError("Invalid source/boundary partition")
    for i, boundary in enumerate(link["boundaries"], start=offset):
        if (type(boundary["case_index"]) is not int or boundary["case_index"] != i
                or boundary["case_sha256"] != digest(cases[i]) or cases[i]["projections"] != []):
            raise ValueError("Invalid boundary index, projection or identity")
    return cases, offset


def score_task_contract_outputs(manifest, task_id, outputs, *, expected_sha256=None):
    """Score saved/isolated typed outputs for one task of a trusted reviewed manifest.

    Preserve V2 scoring on inherited cases. On added direct-call boundaries,
    additionally require recursive type-tag agreement and value equality.
    Supply the manifest seal from the trusted replay/external record when available.
    """
    try:
        cases, offset = _scoring_partition(manifest, task_id, expected_sha256)
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError("Malformed task contract manifest") from exc
    scored = score_mbpp_outputs(outputs, cases)
    source_count = boundary_count = 0
    if type(outputs) is list and len(outputs) == len(cases):
        failures = {d["case_index"]: (error, d) for error, d in
                    zip(scored["errors"], scored["case_diagnostics"], strict=True)}
        # A V2 pass establishes successful execution and valid bounded encoding.
        # Add a failure if Python equality admitted a different type anywhere.
        for i in range(offset, len(cases)):
            if i not in failures and _typed_identity(outputs[i]["value"]) != _typed_identity(cases[i]["expected"]):
                failures[i] = (f"case_{i}:wrong_typed_output", {
                    "case_index": i, "error_stage": "boundary_comparison", "error": "wrong_typed_output"})
        source_count = sum(i not in failures for i in range(offset))
        boundary_count = len(cases) - len(failures) - source_count
        ordered = [failures[i] for i in sorted(failures)]
        scored.update(passed=not failures, count=source_count + boundary_count,
                      errors=[error for error, _ in ordered], case_diagnostics=[d for _, d in ordered])
    return {**scored, "scorer_version": "task-contract-output-score-v1", "task_id": task_id,
            "manifest_sha256": manifest["sha256"], "source_passed_count": source_count,
            "source_total": offset, "boundary_passed_count": boundary_count, "boundary_total": len(cases) - offset}
