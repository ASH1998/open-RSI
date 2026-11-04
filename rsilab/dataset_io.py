"""Explicit pinned train/validation reads, with no eager final-test decoding."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re


def file_sha256(path: Path) -> str:
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def read_development_splits(root, *, source_hashes, expected_counts,
                            config='full', splits=('train', 'validation')):
    """Read only explicitly permitted Parquet splits after checksum verification.

    ``root`` contains config/split-00000-of-00001.parquet. Dependencies are
    imported only when called. Final-test/prompt splits are deliberately absent
    from this development API; a separately authorized final evaluator owns them.
    Checksums identify bytes, not dataset quality or semantic split separation.
    """
    root = Path(root)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError('Existing absolute dataset root required')
    if not isinstance(config, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', config):
        raise ValueError('Invalid dataset config')
    splits = tuple(splits)
    if not splits or len(set(splits)) != len(splits) or not set(splits) <= {'train', 'validation'}:
        raise ValueError('Development reads permit only unique train/validation splits')
    paths = {}
    for split in splits:
        key = f'{config}/{split}-00000-of-00001.parquet'
        expected = source_hashes.get(key)
        if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise ValueError('Missing pinned split checksum')
        count = expected_counts.get(split)
        if type(count) is not int or count < 1:
            raise ValueError('Missing positive source row count')
        path = root / key
        if path.parent.is_symlink() or path.is_symlink() or not path.is_file():
            raise ValueError('Missing or symlinked split file')
        if file_sha256(path) != expected:
            raise ValueError(f'Source checksum mismatch: {split}')
        paths[split] = path
    import pyarrow.parquet as parquet
    result = {}
    for split, path in paths.items():
        rows = parquet.read_table(path).to_pylist()
        if len(rows) != expected_counts[split]:
            raise ValueError(f'Source row count mismatch: {split}')
        result[split] = rows
    return result
