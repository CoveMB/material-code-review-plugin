#!/usr/bin/env python3
"""Frozen controller-1.2 compatibility probe for state downgrade tests.

Provenance: ``origin/main`` commit
``91246cf6f4ccbfa6082352a251a2d37b0f563fc2``; released controller version
``1.2.0``; complete source SHA-256
``67ca0210fd567c6e6fe22637c158e47f0a160b87548f1be7cd802c71df94289c``.

This fixture preserves only the released state loader and the candidate-set/v1
forward-mutation boundary needed by the causal compatibility test. It is never
imported by current controller code and must run only against isolated test runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


STATE_SCHEMA = "material-review/state/v1"
CANDIDATE_SCHEMA = "material-review/candidate-set/v1"


class Controller12Error(Exception):
    """Expected rejection from the frozen compatibility probe."""


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Controller12Error(f"Could not load JSON {path}: {exc}") from exc


def require_object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Controller12Error(f"{context} must be a JSON object")
    return value


def load_state(run_dir: Path) -> dict[str, Any]:
    """Released 1.2 state discriminator, retained without current logic."""
    state = require_object(load_json(run_dir / "state.json"), "state")
    if state.get("schema_version") != STATE_SCHEMA:
        raise Controller12Error(f"Unsupported state schema in {run_dir}")
    return state


def run_forward_candidate_boundary(
    run_dir: Path, candidate_path: Path, sentinel_path: Path
) -> None:
    state = load_state(run_dir)
    candidate = require_object(load_json(candidate_path), "candidate set")
    if candidate.get("schema_version") != CANDIDATE_SCHEMA:
        raise Controller12Error(f"{candidate_path}: unsupported schema_version")
    if candidate.get("scope_hash") != state.get("scope_hash"):
        raise Controller12Error(
            f"{candidate_path}: scope_hash does not match the active frozen scope"
        )

    sentinel_path.write_text("controller-1.2-forward-path-reached\n", encoding="utf-8")
    (run_dir / "candidates.json").write_text(
        json.dumps(
            {
                "schema_version": "material-review/candidates-normalized/v1",
                "scope_hash": state["scope_hash"],
                "compatibility_probe": "controller-1.2-forward-path-reached",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    state["phase"] = "CANDIDATES_CAPTURED"
    state.setdefault("events", []).append(
        {"event": "controller-1.2-forward-path-reached"}
    )
    (run_dir / "state.json").write_text(
        json.dumps(state, indent=2) + "\n", encoding="utf-8"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--sentinel", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        run_forward_candidate_boundary(args.run_dir, args.input, args.sentinel)
        return 0
    except Controller12Error as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
