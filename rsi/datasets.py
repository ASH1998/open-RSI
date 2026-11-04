"""Pinned MBPP data import. Parse source code/tests as data; never execute them.

Raw source assets and all generated manifests belong under ignored data/mbpp.
The pools are pre-verifier candidates, not approved training labels or benchmarks.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import re
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

DATASET_ID = "google-research-datasets/mbpp"
REVISION = "4bb6404fdc6cacfda99d4ac4205087b89d32030c"
IMPORTER_VERSION = "mbpp-import-v1"
DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data" / "mbpp"
SOURCE_SPLITS = ("train", "validation", "test", "prompt")
COUNTS = {"full": (374, 90, 500, 10), "sanitized": (120, 43, 257, 7)}
ALLOWED_IMPORTS = ("math", "collections", "itertools", "functools", "bisect", "heapq", "statistics",
                   "re", "string", "operator", "array")
SOURCE_HASHES = {
    "README.md": "6377d5c76ba46b9e650daa6d5eb592e671c9b15586e39f23f50ed9bf2ac54cf6",
    "full/train-00000-of-00001.parquet": "09d125ca31edacb7800be8c67c45abff618faf0214ff551291817d06bdb914ae",
    "full/validation-00000-of-00001.parquet": "3f0ec060987432d99fe8fb409d31e6c67445b208a01741c5583517c80a10fe80",
    "full/test-00000-of-00001.parquet": "566fd53060ffba5766dace1d1e2f4c38906781526de222b0dfbdbc325b696c77",
    "full/prompt-00000-of-00001.parquet": "a053e4bb85ceb77430ae80592addb4ca4dc6ba087592f9e04537800ee88b7431",
    "sanitized/train-00000-of-00001.parquet": "d95f8ad6d2fff08fe4826122d6e3e31f75716825d0c5c340d297aca5e9e0de0e",
    "sanitized/validation-00000-of-00001.parquet": "27e065fcab3c863959933328a7fdbf404e1bcb5464b1be6fe0dcd9530e420204",
    "sanitized/test-00000-of-00001.parquet": "e9e9efa2c0d59ef5e55537a9d126b8f875d5ac010a8d75628d76824884e15850",
    "sanitized/prompt-00000-of-00001.parquet": "73c623309b7b5d65fd5661204b35f779f8e66301aa9832d1ad4b8fc3b21151fd",
}
# Conservative text quarantine protects the existing pilot's final domains.
SEALED_DOMAIN = re.compile(
    r"\b(graph|graphs|reachability|reachable|adjacency|breadth|levenshtein|traversal|traverse|bfs|dfs)\b|"
    r"edit[ _-]*distance|shortest[ _-]*path|depth[ _-]*first|transitive[ _-]*closure",
    re.I,
)
STOP_WORDS = frozenset("write a an the python function to of in for given and is that with from find".split())


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _root(path) -> Path:
    root = Path(path).resolve()
    if not root.is_relative_to(DEFAULT_ROOT.resolve()):
        raise ValueError("dataset writes must stay under project data/mbpp")
    return root


def download_mbpp(root=DEFAULT_ROOT) -> dict:
    """Download public immutable bytes without HF SDK credentials or remote code."""
    root = _root(root)
    sources = {}
    for name, expected in SOURCE_HASHES.items():
        path = root / "raw" / name
        url = f"https://huggingface.co/datasets/{DATASET_ID}/resolve/{REVISION}/{name}"
        if path.exists():
            data = path.read_bytes()
        else:
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read(2_000_001)
        if len(data) > 2_000_000 or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"source checksum mismatch: {name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
        sources[name] = {"url": url, "sha256": expected, "bytes": len(data)}
    manifest = {"dataset": DATASET_ID, "revision": REVISION, "license": "CC-BY-4.0", "files": sources}
    (root / "raw" / "source.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def load_mbpp(root=DEFAULT_ROOT, config="full") -> dict[str, list[dict]]:
    """Read pinned Parquet bytes, preserving every raw field. Requires pyarrow."""
    if config not in COUNTS:
        raise ValueError("config must be full or sanitized")
    import pyarrow.parquet as pq

    result = {}
    for split, expected_count in zip(SOURCE_SPLITS, COUNTS[config]):
        name = f"{config}/{split}-00000-of-00001.parquet"
        path = Path(root) / "raw" / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != SOURCE_HASHES[name]:
            raise ValueError(f"source checksum mismatch: {name}")
        rows = pq.read_table(path).to_pylist()
        if len(rows) != expected_count:
            raise ValueError(f"source row count mismatch: {name}")
        result[split] = rows
    return result


def _text(row) -> str:
    return row.get("text", row.get("prompt", ""))


def _tokens(text) -> set[str]:
    return set(re.findall(r"[a-z]+|\d+", text.lower())) - STOP_WORDS


class _CanonicalCode(ast.NodeTransformer):
    """Detect renamed/constant-changed templates; deliberately conservative."""
    def __init__(self):
        self.names = {}

    def name(self, value):
        return self.names.setdefault(value, f"v{len(self.names)}")

    def visit_Name(self, node):
        node.id = self.name(node.id)
        return node

    def visit_arg(self, node):
        node.arg = self.name(node.arg)
        return self.generic_visit(node)

    def visit_FunctionDef(self, node):
        node.name = self.name(node.name)
        return self.generic_visit(node)

    def visit_Constant(self, node):
        # Literal changes alone must not send near-duplicate templates across splits.
        return ast.copy_location(ast.Constant(value=type(node.value).__name__), node)


def _fingerprint(row):
    text = " ".join(sorted(_tokens(_text(row))))
    try:
        tree = _CanonicalCode().visit(ast.parse(row["code"]))
        code = ast.dump(tree, include_attributes=False)
    except (SyntaxError, ValueError):
        code = "invalid:" + row["code"]
    return text, digest(code)


def _signature(row):
    tree = ast.parse(row["code"])
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    called = set()
    for test in row["test_list"] + row.get("challenge_test_list", []):
        for node in ast.walk(ast.parse(test)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called.add(node.func.id)
    entries = set(functions) & called
    if len(entries) != 1:
        raise ValueError("ambiguous_or_missing_entry_point")
    name = entries.pop()
    if name.startswith("_") or functions[name].decorator_list:
        raise ValueError("unsupported_entry_point")
    arguments = copy.deepcopy(functions[name].args)
    for arg in arguments.posonlyargs + arguments.args + arguments.kwonlyargs:
        arg.annotation = None
    if arguments.vararg:
        arguments.vararg.annotation = None
    if arguments.kwarg:
        arguments.kwarg.annotation = None
    for default in arguments.defaults + [x for x in arguments.kw_defaults if x is not None]:
        ast.literal_eval(default)  # Literal parsing only; no calls or attribute lookup.
    return name, f"def {name}({ast.unparse(arguments)}):"


def _validate_rows(rows):
    if set(rows) != set(SOURCE_SPLITS):
        raise ValueError("all four source splits are required for duplicate screening")
    ids = set()
    for split in SOURCE_SPLITS:
        for row in rows[split]:
            if (type(row.get("task_id")) is not int or row["task_id"] in ids
                    or not isinstance(_text(row), str) or not _text(row).strip()
                    or not isinstance(row.get("code"), str)
                    or not isinstance(row.get("test_list"), list) or not row["test_list"]
                    or not all(isinstance(t, str) for t in row["test_list"])):
                raise ValueError("invalid_or_duplicate_source_row")
            for field in ("challenge_test_list", "test_imports"):
                if field in row and (not isinstance(row[field], list)
                                     or not all(isinstance(t, str) for t in row[field])):
                    raise ValueError("invalid_source_tests")
            if "test_setup_code" in row and not isinstance(row["test_setup_code"], str):
                raise ValueError("invalid_source_setup")
            ids.add(row["task_id"])


def build_mbpp_pools(rows, *, config="full", seed=42) -> dict:
    """Enumerate every eligible train/dev task; do not sample test/prompt rows.

    Duplicate detection considers all source splits. Components spanning splits
    are quarantined completely. In-split components keep one lowest-ID member.
    Heuristic clusters are not a proof of semantic/family disjointness.
    """
    if config not in COUNTS or type(seed) is not int:
        raise ValueError("invalid config or seed")
    _validate_rows(rows)
    items = sorted(((s, r) for s in SOURCE_SPLITS for r in rows[s]), key=lambda x: x[1]["task_id"])
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    prints = [_fingerprint(r) for _, r in items]
    tokens = [_tokens(_text(r)) for _, r in items]
    for i in range(len(items)):
        for j in range(i):
            text_i, code_i = prints[i]
            text_j, code_j = prints[j]
            overlap = len(tokens[i] & tokens[j]) / max(1, len(tokens[i] | tokens[j]))
            similar = (text_i == text_j or code_i == code_j or
                       (overlap >= 0.70 and SequenceMatcher(None, text_i, text_j).ratio() >= 0.80))
            if similar:
                parent[find(i)] = find(j)
    groups = {}
    for i, item in enumerate(items):
        groups.setdefault(find(i), []).append(item)

    pools, exclusions, clusters = {"train": [], "dev": []}, [], []
    for group in groups.values():
        ids = [r["task_id"] for _, r in group]
        cluster_id = "mbpp-cluster-" + digest(ids)[:16]
        splits = {s for s, _ in group}
        clusters.append({"id": cluster_id, "source_ids": ids, "source_splits": sorted(splits)})
        for split, row in group:
            if split not in ("train", "validation"):
                continue
            reason = None
            if len(splits) > 1:
                reason = "cross_split_duplicate_cluster"
            elif row["task_id"] != min(ids):
                reason = "within_split_duplicate_cluster"
            elif SEALED_DOMAIN.search(_text(row) + " " + row["code"]):
                reason = "protected_pilot_final_domain"
            try:
                entry, signature = _signature(row) if reason is None else (None, None)
            except (SyntaxError, ValueError, TypeError, RecursionError):
                reason = "unsupported_signature_or_test_syntax"
            if reason:
                exclusions.append({"source_id": row["task_id"], "source_split": split, "reason": reason,
                                   "cluster_id": cluster_id})
                continue
            target = "dev" if split == "validation" else "train"
            prompt = ("Implement the following Python function. Return concise, self-contained Python code only; "
                      "no explanation or long comments. Include required imports. Only these modules are permitted: "
                      + ", ".join(ALLOWED_IMPORTS) + ". Do not read stdin, print, access files, "
                      "or use dynamic execution, introspection, or decorators.\n\n"
                      + _text(row).strip() + "\n\nRequired signature:\n" + signature)
            task = {
                "id": f"mbpp-{config}-{row['task_id']}", "family": cluster_id, "split": target,
                "prompt": prompt, "entry_point": entry, "verification_mode": "python_assertions",
                "test_list": copy.deepcopy(row["test_list"]),
                "test_setup_code": row.get("test_setup_code", ""),
                "test_imports": copy.deepcopy(row.get("test_imports", [])),
                "challenge_test_list": copy.deepcopy(row.get("challenge_test_list", [])),
                "metadata": {"dataset": DATASET_ID, "revision": REVISION, "config": config,
                             "source_split": split, "source_id": row["task_id"],
                             "source_row_sha256": digest(row), "license": "CC-BY-4.0",
                             "importer_version": IMPORTER_VERSION, "cluster_id": cluster_id,
                             "family_review_required": True, "allowed_imports": list(ALLOWED_IMPORTS)},
            }
            task["metadata"]["task_sha256"] = digest(task)
            pools[target].append(task)
    for split in pools:
        pools[split].sort(key=lambda t: digest([IMPORTER_VERSION, seed, t["id"]]))
    result = {"dataset": DATASET_ID, "revision": REVISION, "config": config, "seed": seed,
              "importer_version": IMPORTER_VERSION, "source_sha256": SOURCE_HASHES,
              "source_counts": {s: len(rows[s]) for s in SOURCE_SPLITS}, "pools": pools,
              "eligible_counts": {s: len(pools[s]) for s in pools}, "exclusions": exclusions,
              "duplicate_clusters": clusters, "ready_for_training": False,
              "required_gates": ["supported_test_conversion", "remote_reference_audit",
                                 "semantic_family_review", "frozen_protocol_and_budget"]}
    result["manifest_sha256"] = digest(result)
    return result


def select_tasks(manifest, split, count, *, eligible_ids=None) -> list[dict]:
    """Select an exact count from deterministic order after external filtering.

    Insufficient rows raises rather than borrowing from another source split.
    Caller must record its exclusions and freeze converted task hashes separately.
    """
    if split not in ("train", "dev") or type(count) is not int or count < 1:
        raise ValueError("select only a positive train/dev count")
    allowed = None if eligible_ids is None else set(eligible_ids)
    available = manifest["pools"][split]
    if allowed is not None:
        known = {t["id"] for t in available}
        if allowed - known:
            raise ValueError("eligible_ids contain unknown or wrong-split tasks")
        available = [t for t in available if t["id"] in allowed]
    if len(available) < count:
        raise ValueError(f"requested {count} {split} tasks; only {len(available)} eligible")
    return copy.deepcopy(available[:count])


def model_input(task) -> dict:
    """The only supported model projection; hidden fields must stay controller-side."""
    return {"prompt": task["prompt"], "entry_point": task["entry_point"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--config", choices=tuple(COUNTS), default="full")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    root = _root(args.root)
    if args.download:
        download_mbpp(root)
    manifest = build_mbpp_pools(load_mbpp(root, args.config), config=args.config, seed=args.seed)
    output = root / f"pools-{args.config}-seed{args.seed}.json"
    data = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if output.exists() and output.read_text() != data:
        raise ValueError("refusing to overwrite a different frozen pool manifest")
    root.mkdir(parents=True, exist_ok=True)
    output.write_text(data)
    print(json.dumps({"path": str(output), "eligible_counts": manifest["eligible_counts"],
                      "manifest_sha256": manifest["manifest_sha256"]}))


if __name__ == "__main__":
    main()
