"""Deterministic pilot tasks with family-disjoint train/dev/test splits.

Only ``prompt`` and ``entry_point`` are model-visible. Cases, references, and
expected outputs belong to the trusted controller. No candidate code runs here.
"""
from __future__ import annotations

import hashlib
import inspect
import itertools
import json
import math
import random
import textwrap

SUITE_VERSION = "pilot-v2"
TASK_IMPORTS = ("math", "collections", "itertools", "functools", "bisect", "heapq", "statistics")
SPLIT_FAMILIES = {
    "train": ("masked_mean", "stable_softmax", "gradient_clip", "sequence_pad"),
    "dev": ("group_reduce", "interval_union"),
    "test": ("edit_distance", "graph_reachability"),
}


def _ref_masked_mean(config, rows):
    if config["axis"] == "column":
        groups = list(zip(*rows)) if rows else []
    else:
        groups = rows
    result = []
    for group in groups:
        values = [x for x in group if x is not None]
        result.append(sum(values) / len(values) if values else config["empty"])
    return result


def _ref_stable_softmax(config, values):
    if not values:
        return []
    scaled = [x / config["temperature"] for x in values]
    maximum = max(scaled)
    shifted = [x - maximum for x in scaled]
    denominator = sum(math.exp(x) for x in shifted)
    if config["output"] == "log":
        return [x - math.log(denominator) for x in shifted]
    return [math.exp(x) / denominator for x in shifted]


def _ref_gradient_clip(config, values):
    norm_type = config["norm"]
    if norm_type == "l1":
        norm = sum(abs(x) for x in values)
    elif norm_type == "l2":
        norm = math.sqrt(sum(x * x for x in values))
    else:
        norm = max((abs(x) for x in values), default=0)
    factor = min(1.0, config["limit"] / norm) if norm else 1.0
    return [x * factor for x in values]


def _ref_sequence_pad(config, rows):
    result = []
    width = config["width"]
    for row in rows:
        cropped = list(row[:width] if config["keep"] == "first" else row[-width:])
        padding = [config["pad"]] * (width - len(cropped))
        result.append(padding + cropped if config["side"] == "left" else cropped + padding)
    return result


def _ref_group_reduce(config, pairs):
    groups = {}
    for key, value in pairs:
        key = key.lower() if config["lowercase"] else key
        groups.setdefault(key, []).append(value)
    result = []
    for key in sorted(groups):
        values = groups[key]
        operation = config["operation"]
        if operation == "sum":
            reduced = sum(values)
        elif operation == "max":
            reduced = max(values)
        elif operation == "count":
            reduced = len(values)
        else:
            reduced = sum(values) / len(values)
        result.append([key, reduced])
    return result


def _ref_interval_union(config, intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1] + config["gap"]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    if config["output"] == "length":
        return sum(end - start for start, end in merged)
    return merged


def _ref_edit_distance(config, source, target):
    previous = [j * config["insert"] for j in range(len(target) + 1)]
    for i, left in enumerate(source, 1):
        current = [i * config["delete"]]
        for j, right in enumerate(target, 1):
            current.append(min(
                previous[j] + config["delete"],
                current[-1] + config["insert"],
                previous[j - 1] + (0 if left == right else config["replace"]),
            ))
        previous = current
    return previous[-1]


def _ref_graph_reachability(config, node_count, edges, start):
    adjacency = [[] for _ in range(node_count)]
    for left, right in edges:
        adjacency[left].append(right)
        if not config["directed"]:
            adjacency[right].append(left)
    distances = [-1] * node_count
    distances[start] = 0
    queue = [start]
    for node in queue:
        for neighbor in adjacency[node]:
            if distances[neighbor] == -1:
                distances[neighbor] = distances[node] + 1
                queue.append(neighbor)
    mode = config["output"]
    if mode == "distances":
        return distances
    if mode == "count":
        return sum(distance >= 0 for distance in distances)
    if mode == "nodes":
        return [node for node, distance in enumerate(distances) if distance >= 0]
    return [[node for node, distance in enumerate(distances) if distance == layer]
            for layer in range(max(distances) + 1)]


_REFERENCES = {name.removeprefix("_ref_"): value for name, value in list(globals().items())
               if name.startswith("_ref_")}


def _variants(family):
    if family == "masked_mean":
        return [dict(axis=axis, empty=empty) for axis, empty in itertools.product(
            ("row", "column"), (-2, -1, 0, 1))]
    if family == "stable_softmax":
        return [dict(temperature=t, output=out) for t, out in itertools.product(
            (0.5, 1, 2, 4), ("probabilities", "log"))]
    if family == "gradient_clip":
        return [dict(norm=norm, limit=limit) for norm, limit in itertools.product(
            ("l1", "l2", "linf"), (1, 2, 4))]
    if family == "sequence_pad":
        return [dict(width=width, keep=keep, side=side, pad=-1)
                for width, keep, side in itertools.product((2, 4), ("first", "last"), ("left", "right"))]
    if family == "group_reduce":
        return [dict(operation=op, lowercase=lower) for op, lower in itertools.product(
            ("sum", "max", "count", "mean"), (False, True))]
    if family == "interval_union":
        return [dict(gap=gap, output=out) for gap, out in itertools.product(
            (0, 1, 2, 3), ("intervals", "length"))]
    if family == "edit_distance":
        return [dict(insert=i, delete=d, replace=r) for i, d, r in itertools.product(
            (1, 2), (1, 2), (1, 3))]
    return [dict(directed=directed, output=output) for directed, output in itertools.product(
        (False, True), ("distances", "count", "nodes", "layers"))]


def _description(family, c):
    if family == "masked_mean":
        return ("solve(rows): rows is a rectangular list of finite real numbers of magnitude at most 1000000, with None for missing values. "
                f"Return one arithmetic mean per {c['axis']}, excluding None but including zero. "
                f"An entirely missing group returns {c['empty']}. Empty rows=[] returns []. "
                "Zero-width rectangular rows are allowed.")
    if family == "stable_softmax":
        return ("solve(values): values is a list of finite real logits of magnitude at most 1000000. "
                f"Compute numerically stable softmax with temperature {c['temperature']}; "
                f"return {'natural logarithms of the probabilities' if c['output'] == 'log' else 'the probabilities'}. "
                "Empty input returns []. Handle very large positive and negative logits without overflow; "
                "for log output avoid taking log of an underflowed probability.")
    if family == "gradient_clip":
        return (f"solve(values): clip a numeric gradient vector to {c['norm']} norm at most {c['limit']}. "
                "Inputs are finite real numbers of magnitude at most 1000000. "
                "Scale the whole vector by one common factor if needed; otherwise retain its values. "
                "l1=sum(abs(x)), l2=sqrt(sum(x*x)), linf=max(abs(x)). Empty input returns []; "
                "zero vectors remain zero. Do not independently clamp individual coordinates.")
    if family == "sequence_pad":
        return (f"solve(rows): return new integer rows of exactly width {c['width']}. "
                f"For an overlong row keep its {c['keep']} {c['width']} values. "
                f"For a short row pad on the {c['side']} with {c['pad']}. "
                "Preserve row order. Empty outer input returns []; empty inner rows become padding.")
    if family == "group_reduce":
        return ("solve(pairs): pairs is a list of [ASCII string key, integer value] pairs. "
                f"{'Lowercase' if c['lowercase'] else 'Preserve case in'} keys before grouping. "
                f"Reduce each group using {c['operation']}. Return [key, reduced_value] pairs "
                "sorted by key using Python string ordering. Empty input returns [].")
    if family == "interval_union":
        return ("solve(intervals): input contains [start,end] integer intervals with start<=end, "
                "in arbitrary order. Sort and repeatedly merge when the next start is at most "
                f"the current end plus {c['gap']}; merging replaces both intervals by their bounding span. "
                f"Return {'the sorted merged intervals' if c['output'] == 'intervals' else 'the sum of end-start over merged spans (including any bridged gaps)'}. "
                f"Empty input returns {'[]' if c['output'] == 'intervals' else '0'}. "
                "Nested, duplicate, touching, and zero-length intervals are possible.")
    if family == "edit_distance":
        return ("solve(source,target): return the minimum cost to transform source into target using "
                f"single-character insertion cost {c['insert']}, deletion cost {c['delete']}, "
                f"and substitution cost {c['replace']}. Matching characters cost zero. "
                "Use Unicode characters, not bytes. Strings may be empty; transpositions are not an operation.")
    return ("solve(node_count,edges,start): vertices are integers 0 through node_count-1, "
            "node_count>=1, start is valid, and every edge endpoint is valid. "
            f"Edges are {'directed' if c['directed'] else 'undirected'} [u,v] pairs; duplicates and self loops are allowed. "
            "Compute shortest unweighted path distances from start. "
            + {"distances": "Return distances by vertex index, with -1 for unreachable vertices.",
               "count": "Return the number of reachable vertices, including start.",
               "nodes": "Return reachable vertex IDs in ascending order, including start.",
               "layers": "Return lists of reachable IDs grouped by increasing distance, sorted within each layer. The first layer contains start."}[c["output"]])


def _inputs(family, rng):
    """First input is public; subsequent cases are only for the evaluator."""
    if family == "masked_mean":
        public = [[[2, None], [4, 8]]]
        hidden = [[[]], [[[]]], [[[None, None], [None, None]]], [[[0, 2], [None, -4]]]]
        hidden += [[[[rng.choice([None, -5, -1, 0, 2, 7]) for _ in range(3)] for _ in range(4)]] for _ in range(4)]
    elif family == "stable_softmax":
        public = [[0, 1, 2]]
        hidden = [[[]], [[7]], [[10000, 10001, 9998]], [[-10000, -10000]], [[1000, -1000]], [[0, 0, 0, 0]]]
        hidden += [[[rng.randint(-30, 30) for _ in range(7)]] for _ in range(3)]
    elif family == "gradient_clip":
        public = [[3, 4]]
        hidden = [[[]], [[0, 0]], [[-9, 0, 12]], [[0.1, -0.2]], [[1, 1, 1, 1]], [[-1000]]]
        hidden += [[[rng.randint(-10, 10) for _ in range(5)]] for _ in range(3)]
    elif family == "sequence_pad":
        public = [[[1, 2, 3], [4]]]
        hidden = [[[]], [[[]]], [[[1, 2, 3, 4, 5, 6], [], [-1, -2]]], [[[0], [0, 0, 0, 0]]]]
        hidden += [[[[rng.randint(-3, 5) for _ in range(rng.randrange(7))] for _ in range(4)]] for _ in range(3)]
    elif family == "group_reduce":
        public = [[["a", 2], ["b", 3], ["a", 4]]]
        hidden = [[[]], [[["A", -3], ["a", 4], ["A", 0]]], [[["", 2], ["", -2], ["B", -10]]]]
        hidden += [[[[rng.choice(["A", "a", "b", "B", "x"]), rng.randint(-9, 9)] for _ in range(9)]] for _ in range(4)]
    elif family == "interval_union":
        public = [[[0, 2], [1, 4], [8, 9]]]
        hidden = [[[]], [[[0, 0]]], [[[5, 8], [0, 9], [1, 2], [5, 8]]], [[[-5, -3], [-3, 0]]], [[[0, 1], [3, 4], [6, 7]]]]
        hidden += [[[[a, a + rng.randrange(5)] for a in [rng.randint(-5, 10) for _ in range(7)]]] for _ in range(3)]
    elif family == "edit_distance":
        public = ["cat", "cut"]
        hidden = [["", ""], ["", "abc"], ["abc", ""], ["ab", "ba"], ["café", "cafe"], ["aaaa", "a"], ["kitten", "sitting"]]
        hidden += [["".join(rng.choices("abc", k=5)), "".join(rng.choices("abc", k=4))] for _ in range(3)]
    else:
        public = [4, [[0, 1], [1, 2]], 0]
        hidden = [[1, [], 0], [4, [], 2], [4, [[0, 1], [1, 0], [1, 1], [1, 2], [0, 1]], 2], [5, [[0, 1], [1, 2], [3, 4]], 4]]
        hidden += [[6, [[rng.randrange(6), rng.randrange(6)] for _ in range(8)], rng.randrange(6)] for _ in range(4)]
    return public, hidden


def build_tasks(split: str, count_per_family: int = 4, seed: int = 0) -> list[dict]:
    """Build fixed task manifests; callers must not send ``cases`` to a model.

    Between one and eight semantic variants per family are supported. Seeds alter
    configuration selection and hidden cases, but never the split assignment.
    """
    if not isinstance(split, str) or split not in SPLIT_FAMILIES:
        raise ValueError("split must be train, dev, or test")
    if type(count_per_family) is not int or not 1 <= count_per_family <= 8:
        raise ValueError("count_per_family must be an integer between 1 and 8")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    tasks = []
    for family in SPLIT_FAMILIES[split]:
        digest = hashlib.sha256(f"{SUITE_VERSION}:{seed}:{family}".encode()).digest()
        rng = random.Random(int.from_bytes(digest[:8], "big"))
        variants = _variants(family)
        rng.shuffle(variants)
        for config in variants[:count_per_family]:
            public, hidden = _inputs(family, rng)
            reference = _REFERENCES[family]
            example = {"args": public, "expected": reference(config, *public)}
            unique = {json.dumps(public, sort_keys=True)}
            cases = []
            for args in hidden:
                key = json.dumps(args, sort_keys=True)
                if key not in unique:
                    unique.add(key)
                    cases.append({"args": args, "expected": reference(config, *args)})
            manifest = {"suite_version": SUITE_VERSION, "family": family,
                        "split": split, "config": config, "seed": seed, "cases": cases}
            suffix = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:12]
            prompt = ("Write a Python function named solve. Built-in functions and these imports are allowed: "
                      + ", ".join(TASK_IMPORTS) + ". No other imports are permitted. "
                      "Do not use decorators, file I/O, dynamic code execution, or introspection. "
                      "Return the result; do not read stdin or print. Respond with Python code only.\n\n"
                      + _description(family, config) + "\n\nExample (JSON arguments and result):\n"
                      + json.dumps(example, ensure_ascii=False))
            floating_output = family in {"masked_mean", "stable_softmax", "gradient_clip"} or (
                family == "group_reduce" and config["operation"] == "mean")
            tasks.append({"id": f"{split}-{family}-{suffix}", "family": family,
                          "split": split, "prompt": prompt, "entry_point": "solve",
                          "cases": cases, "examples": [example],
                          "metadata": {"suite_version": SUITE_VERSION, "config": config, "seed": seed},
                          "tolerance": {"rel_tol": 1e-6 if floating_output else 0.0,
                                        "abs_tol": 1e-7 if floating_output else 0.0}})
    return tasks


def reference_solution(task: dict) -> str:
    """Return trusted solution code for verifier tests ONLY, never SFT labels."""
    family = task["family"]
    reference = _REFERENCES[family]
    source = textwrap.dedent(inspect.getsource(reference))
    return ("import math\n\n" + source + "\n\ndef solve(*args):\n"
            f"    return {reference.__name__}({task['metadata']['config']!r}, *args)\n")
