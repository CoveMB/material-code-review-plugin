#!/usr/bin/env python3
"""Frozen controller-1.4 producer for state/v3 compatibility tests.

Provenance: baseline commit
``6135f0725467a0541561723237302fdb694957dc``; released controller version
``1.4.1``; complete source SHA-256
``21eef3c352b4d66b9d11a2589645462e05dd15f50645fec497c6974516dba47a``.

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


STATE_SCHEMA = "material-review/state/v3"
WORKFLOW_PROFILE = "material_review"


class Controller14FixtureError(Exception):
    """The isolated run cannot represent a released controller-1.4 state."""


def load_object(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Controller14FixtureError(f"Could not load {context} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Controller14FixtureError(f"{context} must be a JSON object")
    return value


def write_state_v3(run_dir: Path) -> None:
    state_path = run_dir / "state.json"
    state = load_object(state_path, "state")
    scope = load_object(run_dir / "scope.json", "scope")
    scope_hash = scope.get("scope_hash")
    if not isinstance(scope_hash, str) or state.get("scope_hash") != scope_hash:
        raise Controller14FixtureError("state and scope must share one frozen scope_hash")

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
        write_state_v3(args.run_dir)
        return 0
    except Controller14FixtureError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
