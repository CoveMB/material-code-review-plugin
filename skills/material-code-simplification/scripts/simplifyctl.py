#!/usr/bin/env python3
"""Codebase-scope adapter for the material-code-review evidence controller.

The shared controller remains authoritative for candidates, adjudication, user
receipts, plans, checkpoints, tests, repair bounds, and verification. This file
adds one scope mode only: a deterministic snapshot of selected current files.
It intentionally depends only on the Python standard library and the packaged
sibling/standalone core controller.
"""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import os
import shutil
import stat
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence

ADAPTER_VERSION = "1.0.0"
PROFILE_NAME = "material-code-simplification"
CODEBASE_SCOPE = "codebase"
NO_BASELINE_SHA = "0" * 40
DEFAULT_MAX_SELECTED_FILES = 5_000
DEFAULT_MAX_SELECTED_BYTES = 512 * 1024 * 1024


def _skill_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _core_candidates() -> list[Path]:
    skill = _skill_dir()
    return [
        skill / "core" / "reviewctl.py",
        skill.parent / "material-code-review" / "scripts" / "reviewctl.py",
    ]


def _load_core() -> Any:
    for path in _core_candidates():
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location("material_reviewctl_core", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        previous = sys.modules.get(spec.name)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            if previous is None:
                sys.modules.pop(spec.name, None)
            else:
                sys.modules[spec.name] = previous
            raise
        return module
    locations = "\n  - ".join(str(path) for path in _core_candidates())
    raise RuntimeError(
        "Could not locate the material-code-review controller. Expected one of:\n"
        f"  - {locations}"
    )


core = _load_core()


def _require_core_surface() -> None:
    required = {
        "ReviewError",
        "STATE_SCHEMA",
        "SCOPE_SCHEMA",
        "TOOL_VERSION",
        "PHASE_CONTEXT",
        "resolve_repo_root",
        "resolve_artifact_root",
        "normalize_run_id",
        "normalize_repo_path",
        "repo_path",
        "git_bytes",
        "resolve_commit",
        "current_branch",
        "source_state_from_bytes",
        "sha256_bytes",
        "scope_identity_hash",
        "snapshot_sources",
        "write_source_bundle_files",
        "save_state",
        "make_run_id",
        "utc_now",
        "atomic_write_json",
        "atomic_write_text",
        "is_transient_runtime_path",
        "recompute_scope_from_state",
        "main",
    }
    missing = sorted(name for name in required if not hasattr(core, name))
    if missing:
        raise RuntimeError(
            "The packaged material-code-review controller is incompatible with "
            f"this adapter; missing: {', '.join(missing)}"
        )

    expected_parameters = {
        "resolve_artifact_root": {"repo", "raw"},
        "normalize_repo_path": {"raw", "allow_dot"},
        "source_state_from_bytes": {"data"},
        "scope_identity_hash": {"identity"},
        "snapshot_sources": {"repo", "run_dir", "scope", "max_file_bytes", "max_total_bytes"},
        "write_source_bundle_files": {"run_dir", "scope", "limitations"},
        "save_state": {"run_dir", "state"},
        "recompute_scope_from_state": {"repo", "state"},
        "main": {"argv"},
    }
    incompatible: list[str] = []
    for name, expected in expected_parameters.items():
        try:
            actual = set(inspect.signature(getattr(core, name)).parameters)
        except (TypeError, ValueError):
            incompatible.append(f"{name}(signature unavailable)")
            continue
        missing_parameters = sorted(expected - actual)
        if missing_parameters:
            incompatible.append(f"{name}(missing {', '.join(missing_parameters)})")
    if incompatible:
        raise RuntimeError(
            "The packaged material-code-review controller has incompatible internal signatures: "
            + "; ".join(incompatible)
        )


_require_core_surface()
_ORIGINAL_RECOMPUTE_SCOPE = core.recompute_scope_from_state


def _normalize_selector(raw: str) -> str:
    return core.normalize_repo_path(raw, allow_dot=True)


def _matches_prefix(path: str, selector: str) -> bool:
    return selector == "." or path == selector or path.startswith(selector + "/")


def _selected(path: str, includes: list[str], excludes: list[str]) -> bool:
    return any(_matches_prefix(path, selector) for selector in includes) and not any(
        _matches_prefix(path, selector) for selector in excludes
    )


def _decode_z_paths(raw: bytes) -> list[str]:
    paths: list[str] = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        decoded = os.fsdecode(item)
        try:
            normalized = core.normalize_repo_path(decoded)
        except core.ReviewError as exc:
            raise core.ReviewError(
                f"Git reported an unsupported repository path spelling: {ascii(decoded)}"
            ) from exc
        if normalized != decoded:
            raise core.ReviewError(
                f"Git reported an unsupported repository path spelling: {ascii(decoded)}"
            )
        paths.append(decoded)
    return paths


def _literal_git_pathspec_arguments(includes: Sequence[str]) -> list[str]:
    if "." in includes:
        return []
    return ["--", *(f":(literal){selector}" for selector in includes)]


def _git_scope_paths(repo: Path, arguments: Sequence[str], includes: Sequence[str]) -> list[str]:
    return _decode_z_paths(
        core.git_bytes(
            repo,
            "ls-files",
            *arguments,
            "-z",
            *_literal_git_pathspec_arguments(includes),
        )
    )


def _read_current_source(
    repo: Path, path: str, *, max_bytes: int | None = None
) -> tuple[bytes, int, str] | None:
    target = core.repo_path(repo, path)
    try:
        info = target.lstat()
    except FileNotFoundError:
        return None
    mode = stat.S_IMODE(info.st_mode)
    if stat.S_ISLNK(info.st_mode):
        data = os.fsencode(os.readlink(target))
    elif stat.S_ISREG(info.st_mode):
        if max_bytes is not None and info.st_size > max_bytes:
            raise core.ReviewError(
                f"Selected file {path} is {info.st_size} bytes, exceeding the remaining "
                f"--max-selected-bytes budget of {max_bytes}; narrow or exclude the path"
            )
        data = target.read_bytes()
    else:
        return None
    if max_bytes is not None and len(data) > max_bytes:
        raise core.ReviewError(
            f"Selected source {path} exceeds the remaining --max-selected-bytes budget of {max_bytes}"
        )
    return data, mode, "symlink" if stat.S_ISLNK(info.st_mode) else "file"


def build_codebase_scope(
    repo: Path,
    *,
    path_selectors: Sequence[str],
    exclude_path_selectors: Sequence[str],
    include_untracked: bool,
    max_selected_files: int = DEFAULT_MAX_SELECTED_FILES,
    max_selected_bytes: int = DEFAULT_MAX_SELECTED_BYTES,
) -> dict[str, Any]:
    """Build a frozen identity for selected files in the current worktree.

    The baseline side is intentionally marked missing. Codebase-mode evidence
    must cite the comparison snapshot, because there is no meaningful before
    tree. File content, file mode, selection, branch, and HEAD identity all
    contribute to the scope hash.
    """

    if max_selected_files < 1 or max_selected_bytes < 1:
        raise core.ReviewError("Codebase selection budgets must be positive")

    includes = sorted({_normalize_selector(item) for item in path_selectors} or {"."})
    excludes = sorted({_normalize_selector(item) for item in exclude_path_selectors})
    head_sha = core.resolve_commit(repo, "HEAD")
    branch = core.current_branch(repo)
    tracked = _git_scope_paths(repo, ["--cached"], includes)
    untracked: list[str] = []
    if include_untracked:
        untracked = [
            path
            for path in _git_scope_paths(repo, ["--others", "--exclude-standard"], includes)
            if not core.is_transient_runtime_path(path)
        ]

    candidate_paths = [(path, True) for path in tracked] + [(path, False) for path in untracked]
    selected_paths: list[tuple[str, bool]] = []
    matched_by_include = {selector: False for selector in includes}
    for path, is_tracked in candidate_paths:
        for selector in includes:
            if _matches_prefix(path, selector):
                matched_by_include[selector] = True
        if _selected(path, includes, excludes):
            selected_paths.append((path, is_tracked))
            if len(selected_paths) > max_selected_files:
                raise core.ReviewError(
                    f"Codebase scope selected more than the --max-selected-files budget of "
                    f"{max_selected_files}; narrow the paths or raise the budget explicitly"
                )
    selected_paths.sort(key=lambda item: item[0])

    unmatched = sorted(
        selector for selector, matched in matched_by_include.items() if not matched and selector != "."
    )
    if unmatched:
        raise core.ReviewError(
            "Codebase path selector matched no tracked/current untracked file: "
            + ", ".join(unmatched)
        )
    entries: list[dict[str, Any]] = []
    limitations: list[str] = []
    selected_total_bytes = 0
    for path, is_tracked in selected_paths:
        current = _read_current_source(
            repo, path, max_bytes=max_selected_bytes - selected_total_bytes
        )
        if current is None:
            limitations.append(
                f"{path} was selected by Git but is not a regular file or final symlink in the current worktree"
            )
            continue
        data, mode, kind = current
        selected_total_bytes += len(data)
        if selected_total_bytes > max_selected_bytes:
            raise core.ReviewError(
                f"Codebase scope exceeds the --max-selected-bytes budget of {max_selected_bytes}; "
                "narrow the paths, exclude large assets, or raise the budget explicitly"
            )
        comparison_state = core.source_state_from_bytes(data)
        comparison_state["mode"] = mode
        comparison_state["worktree_kind"] = kind
        entries.append(
            {
                "status": "S",
                "path": path,
                "old_path": None,
                "tracked": is_tracked,
                "baseline_state": core.source_state_from_bytes(None),
                "comparison_state": comparison_state,
            }
        )

    if not entries:
        raise core.ReviewError(
            "The resolved codebase scope contains no current files after exclusions"
        )

    empty = b""
    identity = {
        "schema_version": core.SCOPE_SCHEMA,
        "actual_scope": CODEBASE_SCOPE,
        "base_reference": "codebase-snapshot",
        "head_reference": None,
        "baseline_sha": NO_BASELINE_SHA,
        "comparison_kind": "working-tree",
        "comparison_reference": "working-tree",
        "comparison_sha": head_sha,
        "include_untracked": include_untracked,
        "mutable": True,
        "branch": branch,
        "workspace_head_sha": head_sha,
        "patch_sha256": core.sha256_bytes(empty),
        "staged_patch_sha256": core.sha256_bytes(empty),
        "unstaged_patch_sha256": core.sha256_bytes(empty),
        "path_selectors": includes,
        "exclude_path_selectors": excludes,
        "selection_limitations": limitations,
        "max_selected_files": max_selected_files,
        "max_selected_bytes": max_selected_bytes,
        "selected_total_bytes": selected_total_bytes,
        "files": entries,
    }
    return {
        "identity": identity,
        "scope_hash": core.scope_identity_hash(identity),
        "patch": empty,
        "staged_patch": empty,
        "unstaged_patch": empty,
    }


def _recompute_scope_from_state(repo: Path, state: dict[str, Any]) -> dict[str, Any]:
    params = state.get("scope_params", {})
    if params.get("actual_scope") == CODEBASE_SCOPE:
        return build_codebase_scope(
            repo,
            path_selectors=params.get("path_selectors", ["."]),
            exclude_path_selectors=params.get("exclude_path_selectors", []),
            include_untracked=bool(params.get("include_untracked", True)),
            max_selected_files=int(params.get("max_selected_files", DEFAULT_MAX_SELECTED_FILES)),
            max_selected_bytes=int(params.get("max_selected_bytes", DEFAULT_MAX_SELECTED_BYTES)),
        )
    return _ORIGINAL_RECOMPUTE_SCOPE(repo, state)


# check_scope_fresh resolves this symbol from the core module at runtime.
core.recompute_scope_from_state = _recompute_scope_from_state


def _append_codebase_scope_notes(run_dir: Path, identity: dict[str, Any]) -> None:
    scope_md = run_dir / "scope.md"
    text = scope_md.read_text(encoding="utf-8") if scope_md.is_file() else "# Frozen review scope\n"
    additions = [
        "",
        "## Codebase selection",
        "",
        "- Evidence side: `comparison` (there is no before-tree in codebase mode)",
        "- Included prefixes: "
        + ", ".join(f"`{item}`" for item in identity["path_selectors"]),
        f"- Selected source bytes: `{identity['selected_total_bytes']}`",
        f"- Selection budgets: `{identity['max_selected_files']}` files / `{identity['max_selected_bytes']}` bytes",
        "- Excluded prefixes: "
        + (
            ", ".join(f"`{item}`" for item in identity["exclude_path_selectors"])
            if identity["exclude_path_selectors"]
            else "none"
        ),
    ]
    if identity.get("selection_limitations"):
        additions.extend(["", "### Selection limitations", ""])
        additions.extend(f"- {item}" for item in identity["selection_limitations"])
    core.atomic_write_text(scope_md, text.rstrip() + "\n" + "\n".join(additions) + "\n")


def command_init_codebase(args: argparse.Namespace) -> int:
    repo = core.resolve_repo_root(args.repo_root)
    artifact_root = core.resolve_artifact_root(repo, args.artifact_root)
    run_id = core.normalize_run_id(args.run_id) if args.run_id else core.make_run_id()
    runs_root = artifact_root / "runs"
    run_dir = runs_root / run_id
    if run_dir.exists():
        raise core.ReviewError(f"Run already exists: {run_dir}")

    scope = build_codebase_scope(
        repo,
        path_selectors=args.path,
        exclude_path_selectors=args.exclude_path,
        include_untracked=not args.exclude_untracked,
        max_selected_files=args.max_selected_files,
        max_selected_bytes=args.max_selected_bytes,
    )

    runs_root.mkdir(parents=True, exist_ok=True)
    temp_run_dir = runs_root / f".{run_id}.initializing-{uuid.uuid4().hex[:8]}"
    temp_run_dir.mkdir(parents=False, exist_ok=False)
    try:
        snapshot_limitations = core.snapshot_sources(
            repo,
            temp_run_dir,
            scope,
            max_file_bytes=args.max_snapshot_file_bytes,
            max_total_bytes=args.max_snapshot_total_bytes,
        )
        core.write_source_bundle_files(temp_run_dir, scope, snapshot_limitations)
        identity = scope["identity"]
        _append_codebase_scope_notes(temp_run_dir, identity)
        profile = {
            "profile": PROFILE_NAME,
            "adapter_version": ADAPTER_VERSION,
            "core_tool_version": core.TOOL_VERSION,
            "scope_mode": CODEBASE_SCOPE,
            "path_selectors": identity["path_selectors"],
            "exclude_path_selectors": identity["exclude_path_selectors"],
            "max_selected_files": identity["max_selected_files"],
            "max_selected_bytes": identity["max_selected_bytes"],
            "selected_total_bytes": identity["selected_total_bytes"],
            "created_at": core.utc_now(),
        }
        core.atomic_write_json(temp_run_dir / "profile.json", profile)
        state = {
            "schema_version": core.STATE_SCHEMA,
            "tool_version": core.TOOL_VERSION,
            "run_id": run_id,
            "repo_root": str(repo),
            "artifact_root": str(artifact_root),
            "phase": core.PHASE_CONTEXT,
            "created_at": core.utc_now(),
            "updated_at": core.utc_now(),
            "scope_hash": scope["scope_hash"],
            "scope_params": {
                "actual_scope": CODEBASE_SCOPE,
                "base_reference": identity["base_reference"],
                "head_reference": None,
                "include_untracked": identity["include_untracked"],
                "path_selectors": identity["path_selectors"],
                "exclude_path_selectors": identity["exclude_path_selectors"],
                "max_selected_files": identity["max_selected_files"],
                "max_selected_bytes": identity["max_selected_bytes"],
            },
            "mutation_allowed": True,
            "hashes": {},
            "gates": {},
            "approved_findings": [],
            "finding_status": {},
            "global_test_results": {},
            "active_finding": None,
            "repair_round": 0,
            "repair_targets": [],
            "expected_workspace_guard_hash": None,
            "pre_fix_checkpoint": None,
            "profile": PROFILE_NAME,
            "events": [
                {
                    "at": core.utc_now(),
                    "event": "scope_frozen",
                    "scope_hash": scope["scope_hash"],
                    "profile": PROFILE_NAME,
                }
            ],
        }
        core.save_state(temp_run_dir, state)
        os.replace(temp_run_dir, run_dir)
    except Exception:
        shutil.rmtree(temp_run_dir, ignore_errors=True)
        raise

    print(f"[OK] Frozen codebase scope: {scope['scope_hash']}")
    print(f"Run ID: {run_id}")
    print(f"Artifact directory: {run_dir}")
    print("Mode: codebase")
    print(f"Selected files: {len(scope['identity']['files'])}")
    print(f"Selected source bytes: {scope['identity']['selected_total_bytes']}")
    print(
        "Included prefixes: "
        + ", ".join(scope["identity"]["path_selectors"])
    )
    print(
        "Excluded prefixes: "
        + (
            ", ".join(scope["identity"]["exclude_path_selectors"])
            if scope["identity"]["exclude_path_selectors"]
            else "none"
        )
    )
    print("Mutation aligned: true")
    return 0


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return value


def _build_codebase_init_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simplifyctl.py init",
        description="Freeze a bounded snapshot of selected current codebase files.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--artifact-root", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--scope", choices=[CODEBASE_SCOPE], default=CODEBASE_SCOPE)
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="Repository-relative file or directory prefix to include; repeatable. Default: repository root.",
    )
    parser.add_argument(
        "--exclude-path",
        action="append",
        default=[],
        help="Repository-relative file or directory prefix to exclude; repeatable.",
    )
    parser.add_argument(
        "--exclude-untracked",
        action="store_true",
        help="Exclude untracked files. Selected untracked files are included by default.",
    )
    parser.add_argument(
        "--max-selected-files",
        type=_positive_int,
        default=DEFAULT_MAX_SELECTED_FILES,
        help="Fail closed when the selected boundary contains more files.",
    )
    parser.add_argument(
        "--max-selected-bytes",
        type=_positive_int,
        default=DEFAULT_MAX_SELECTED_BYTES,
        help="Fail closed when selected current source exceeds this byte budget.",
    )
    parser.add_argument("--max-snapshot-file-bytes", type=_positive_int, default=2 * 1024 * 1024)
    parser.add_argument("--max-snapshot-total-bytes", type=_positive_int, default=25 * 1024 * 1024)
    return parser


def _option_value(argv: Sequence[str], option: str) -> str | None:
    for index, item in enumerate(argv):
        if item == option and index + 1 < len(argv):
            return argv[index + 1]
        prefix = option + "="
        if item.startswith(prefix):
            return item[len(prefix) :]
    return None


def _print_help() -> None:
    print(
        "Material Code Simplification controller adapter\n\n"
        "Additional scope:\n"
        "  simplifyctl.py init --scope codebase [--path PATH]... "
        "[--exclude-path PATH]...\n\n"
        "All other commands and change-scope init modes are delegated to the "
        "material-code-review controller. Run:\n"
        "  simplifyctl.py init --scope codebase --help\n"
        "  simplifyctl.py <core-command> --help\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if not values or values in (["--help"], ["-h"]):
        _print_help()
        return 0
    requested_scope = _option_value(values[1:], "--scope") if values[0] == "init" else None
    if values[0] == "init" and requested_scope in {None, CODEBASE_SCOPE}:
        parser = _build_codebase_init_parser()
        try:
            args = parser.parse_args(values[1:])
            args.artifact_root = args.artifact_root or None
            args.run_id = args.run_id or None
            return int(command_init_codebase(args))
        except core.ReviewError as exc:
            print(f"[FAIL] {exc}", file=sys.stderr)
            return 2
        except RuntimeError as exc:
            print(f"[FAIL] {exc}", file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            print("[FAIL] Interrupted", file=sys.stderr)
            return 130
    return int(core.main(values))


if __name__ == "__main__":
    raise SystemExit(main())
