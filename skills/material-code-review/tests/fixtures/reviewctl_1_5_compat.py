#!/usr/bin/env python3
"""Frozen controller-1.5 producer for state/v4 compatibility tests.

Provenance: baseline commit
``2fd383cd419c71b55251b83c7ac9f507ccda4529``; released controller version
``1.5.1``; complete source SHA-256
``7c8b13feb5603f0277003317d29a533fe46d3aef2fd0fda0658812d9642de6e6``.

The fixture preserves only the released state identity written after scope
freezing. It reuses an isolated test run's already-frozen scope and source
bundle so compatibility tests exercise real controller artifacts without
importing current controller code.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


STATE_SCHEMA = "material-review/state/v4"
WORKFLOW_PROFILE = "material_review"


class Controller15FixtureError(Exception):
    """The isolated run cannot represent a released controller-1.5 state."""


def load_object(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Controller15FixtureError(f"Could not load {context} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Controller15FixtureError(f"{context} must be a JSON object")
    return value


def write_state_v4(run_dir: Path) -> None:
    state_path = run_dir / "state.json"
    state = load_object(state_path, "state")
    scope = load_object(run_dir / "scope.json", "scope")
    scope_hash = scope.get("scope_hash")
    if not isinstance(scope_hash, str) or state.get("scope_hash") != scope_hash:
        raise Controller15FixtureError("state and scope must share one frozen scope_hash")

    state["schema_version"] = STATE_SCHEMA
    state["workflow_profile"] = WORKFLOW_PROFILE
    state["coverage_required"] = True
    state.pop("profile", None)
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        write_state_v4(args.run_dir)
        return 0
    except Controller15FixtureError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
