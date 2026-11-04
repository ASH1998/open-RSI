"""Hash an explicit artifact allowlist without uploading or scanning a checkout."""
from pathlib import Path
from typing import Sequence

from .core import FrozenJSON
import hashlib


def artifact_manifest(root: str | Path, paths: Sequence[str]) -> FrozenJSON:
    root = Path(root).resolve(strict=True)
    inventory = {}
    for name in paths:
        relative = Path(name)
        if relative.is_absolute() or any(part.startswith(".") for part in relative.parts):
            raise ValueError("Use explicit relative artifact paths without hidden/traversal components")
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("Artifact must be a file inside the supplied root")
        key = relative.as_posix()
        if key in inventory:
            raise ValueError("Duplicate artifact path")
        hasher, size = hashlib.sha256(), 0
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
                size += len(chunk)
        inventory[key] = {"sha256": hasher.hexdigest(), "bytes": size}
    if not inventory:
        raise ValueError("At least one artifact is required")
    return FrozenJSON({"schema_version": 1, "files": inventory})
