from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


class EvaluationError(ValueError):
    """Raised when committed evaluation data violates its contract."""


def canonical_hash(value: Any) -> str:
    """Return a stable SHA-256 digest for a JSON-compatible value."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the lowercase SHA-256 digest of a file's exact bytes."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_json(path: Path, value: Any) -> None:
    """Durably replace a JSON file without exposing a partial write."""

    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise


def safe_relative_path(value: object, context: str) -> PurePosixPath:
    """Validate a POSIX path that must stay within a controller-owned root."""

    if not isinstance(value, str) or not value:
        raise EvaluationError(f"{context} must be a non-empty relative POSIX path")
    if "\\" in value or any(character in value for character in "\x00\n\r"):
        raise EvaluationError(f"{context} contains an unsafe path character")

    path = PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).is_absolute() or ".." in path.parts:
        raise EvaluationError(f"{context} must not be absolute or traverse a parent")
    return path
