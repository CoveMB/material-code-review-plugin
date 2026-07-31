#!/usr/bin/env python3
"""Validate canonical paths and the demo archive."""

from __future__ import annotations

import re
from pathlib import PurePosixPath


REQUIRED_ARCHIVE_ENTRIES = {
    "references/workflow.md",
    "schemas/candidate-set.json",
    "scripts/validate_package.py",
}


def is_canonical_git_path(value: str) -> bool:
    if not value or value.startswith(("/", "//")) or "\\" in value:
        return False
    if re.match(r"^[A-Za-z]:", value):
        return False
    path = PurePosixPath(value)
    return all(part not in {"", ".", ".."} for part in path.parts) and path.as_posix() == value


def validate_archive_entries(entries: set[str]) -> list[str]:
    return [
        f"missing archive entry: {entry}"
        for entry in sorted(REQUIRED_ARCHIVE_ENTRIES - entries)
    ]
