#!/usr/bin/env python3
"""Frozen controller-1.3 producer for state/v2 compatibility tests.

Provenance: baseline commit
``c6b78b442a9aa5712b3d2aea74746579c58ece1c``; released controller version
``1.3.0``; complete source SHA-256
``267a58337179fbec1c3740904682601ff12a94f21949263bb8fa06d510a2b48e``.

The fixture preserves only the released state identity written after scope
freezing.  It reuses an isolated test run's already-frozen scope and source
bundle so compatibility tests exercise real controller artifacts without
importing current controller code.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


STATE_SCHEMA = "material-review/state/v2"
WORKFLOW_PROFILE = "material_review"


class Controller13FixtureError(Exception):
    """The isolated run cannot represent a released controller-1.3 state."""


def load_object(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Controller13FixtureError(f"Could not load {context} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Controller13FixtureError(f"{context} must be a JSON object")
    return value


def write_state_v2(run_dir: Path) -> None:
    state_path = run_dir / "state.json"
    state = load_object(state_path, "state")
    scope = load_object(run_dir / "scope.json", "scope")
    scope_hash = scope.get("scope_hash")
    if not isinstance(scope_hash, str) or state.get("scope_hash") != scope_hash:
        raise Controller13FixtureError("state and scope must share one frozen scope_hash")

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
        write_state_v2(args.run_dir)
        return 0
    except Controller13FixtureError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
