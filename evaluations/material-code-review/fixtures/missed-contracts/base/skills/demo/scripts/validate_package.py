#!/usr/bin/env python3
"""Validate canonical paths and archive closure for the demo skill."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]


def is_canonical_git_path(value: str) -> bool:
    if not value or value.startswith(("/", "//")) or "\\" in value:
        return False
    if re.match(r"^[A-Za-z]:", value):
        return False
    path = PurePosixPath(value)
    return all(part not in {"", ".", ".."} for part in path.parts) and path.as_posix() == value


def required_archive_entries() -> set[str]:
    manifest = json.loads((ROOT / "package-layouts.json").read_text(encoding="utf-8"))
    return set(manifest["required_entries"])


def validate_archive_entries(entries: set[str]) -> list[str]:
    return [
        f"missing archive entry: {entry}"
        for entry in sorted(required_archive_entries() - entries)
    ]
