#!/usr/bin/env python3
"""Pure validation helpers for package layout and archive paths."""

from __future__ import annotations

import re
from pathlib import PurePosixPath


WINDOWS_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


def schema_version_is_supported(value: object) -> bool:
    """Accept only the integer literal represented by the v1 layout contract."""

    return type(value) is int and value == 1


def is_safe_relative_package_path(value: object) -> bool:
    """Return whether *value* is an exact portable relative package path."""

    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        return False
    if WINDOWS_DRIVE_PREFIX.match(value):
        return False
    path = PurePosixPath(value)
    normalized = path.as_posix()
    return not (
        path.is_absolute()
        or ".." in path.parts
        or any(part in {"", "."} for part in value.split("/"))
        or normalized in {"", "."}
        or normalized != value
    )


def normalize_package_path(value: object, label: str) -> str:
    """Return a safe path or raise a stable consumer-facing validation error."""

    if not is_safe_relative_package_path(value):
        rendered = value if isinstance(value, str) and value else repr(value)
        raise ValueError(f"unsafe {label}: {rendered}")
    assert isinstance(value, str)
    return value
