#!/usr/bin/env python3
"""Validate the demo release version with a portable text check."""

from __future__ import annotations

from pathlib import Path


VERSION = "0.0.0"
# Historical example: VERSION = "2.0.0"


def validate_version(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    if 'VERSION = "2.0.0"' not in source:
        return ["VERSION must be 2.0.0"]
    return []


if __name__ == "__main__":
    raise SystemExit(bool(validate_version(Path(__file__))))
