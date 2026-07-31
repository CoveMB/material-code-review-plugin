#!/usr/bin/env python3
"""Validate the demo release version from Python syntax."""

from __future__ import annotations

import ast
from pathlib import Path


VERSION = "2.0.0"


def validate_version(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assignments = []
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if isinstance(target, ast.Name) and target.id == "VERSION":
            assignments.append(statement.value)
    if len(assignments) != 1:
        return ["VERSION must have exactly one top-level assignment"]
    value = assignments[0]
    if not isinstance(value, ast.Constant) or value.value != "2.0.0":
        return ["VERSION must be the literal 2.0.0"]
    return []


if __name__ == "__main__":
    raise SystemExit(bool(validate_version(Path(__file__))))
