#!/usr/bin/env python3
"""Pure validation helpers for package layout and archive paths."""

from __future__ import annotations

import re
import stat
import unicodedata
from pathlib import PurePosixPath
from typing import Any


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


def regular_zip_external_attr(permissions: int) -> int:
    """Return explicit Unix regular-file metadata for a ZIP member."""

    return (stat.S_IFREG | (permissions & 0o777)) << 16


def regular_zip_member_metadata_error(
    create_system: int,
    external_attr: int,
) -> str | None:
    """Return why ZIP metadata cannot identify a Unix regular file."""

    if create_system != 3:
        return f"unsupported non-Unix creator system {create_system}"
    mode = (external_attr >> 16) & 0xFFFF
    member_type = stat.S_IFMT(mode)
    if member_type == 0:
        return "unsupported legacy Unix zero-type metadata"
    if not stat.S_ISREG(mode):
        return f"non-regular Unix member type {member_type:#07o}"
    return None


def portable_archive_member_key(archive_path: str) -> str:
    """Return a per-segment Windows-oriented collision identity."""

    return "/".join(
        unicodedata.normalize("NFC", part).casefold().rstrip(". ")
        for part in archive_path.split("/")
    )


def local_schema_reference_errors(document: Any, schema_path: str) -> list[str]:
    """Return deterministic errors for nonlocal or unresolved JSON Schema refs."""

    errors: list[str] = []

    def pointer_token(value: object) -> str:
        return str(value).replace("~", "~0").replace("/", "~1")

    def decode_token(token: str) -> str:
        decoded: list[str] = []
        index = 0
        while index < len(token):
            character = token[index]
            if character != "~":
                decoded.append(character)
                index += 1
                continue
            if index + 1 >= len(token) or token[index + 1] not in {"0", "1"}:
                raise ValueError(f"invalid JSON Pointer escape in token {token!r}")
            decoded.append("~" if token[index + 1] == "0" else "/")
            index += 2
        return "".join(decoded)

    def validate_reference(reference: object, location: str) -> None:
        prefix = f"{schema_path}: {location}: $ref {reference!r}: "
        if not isinstance(reference, str):
            errors.append(prefix + "reference must be a string")
            return
        if not reference.startswith("#"):
            errors.append(prefix + "nonlocal references are unsupported")
            return
        if reference == "#":
            return
        if not reference.startswith("#/") or "%" in reference:
            errors.append(prefix + "malformed percent-free local JSON Pointer")
            return
        try:
            tokens = [decode_token(token) for token in reference[2:].split("/")]
        except ValueError as exc:
            errors.append(prefix + str(exc))
            return

        target = document
        for token in tokens:
            if isinstance(target, dict):
                if token not in target:
                    errors.append(prefix + f"missing object key {token!r}")
                    return
                target = target[token]
            elif isinstance(target, list):
                if re.fullmatch(r"0|[1-9][0-9]*", token) is None:
                    errors.append(prefix + f"invalid array index {token!r}")
                    return
                array_index = int(token)
                if array_index >= len(target):
                    errors.append(prefix + f"array index out of range {token!r}")
                    return
                target = target[array_index]
            else:
                errors.append(prefix + f"cannot traverse scalar at token {token!r}")
                return

    def walk(value: Any, location: str) -> None:
        if isinstance(value, dict):
            if "$ref" in value:
                validate_reference(
                    value["$ref"],
                    f"{location}/{pointer_token('$ref')}",
                )
            for key in sorted(value):
                walk(value[key], f"{location}/{pointer_token(key)}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{location}/{index}")

    walk(document, "#")
    return errors
