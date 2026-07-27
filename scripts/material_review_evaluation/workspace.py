from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Sequence

from .benchmark import Benchmark, CommandSpec
from .model import (
    EvaluationError,
    atomic_write_json,
    canonical_hash,
    safe_relative_path,
    sha256_file,
)


_GIT_TIMEOUT_SECONDS = 30
_PACKAGING_TIMEOUT_SECONDS = 300
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_OWNER_SCHEMA = "material-review-evaluation/workspace-owner/v1"


@dataclass(frozen=True)
class ResolvedVariant:
    supplied_ref: str
    commit_sha: str
    commit_subject_sha256: str


@dataclass(frozen=True)
class WorkspaceRecord:
    kind: str
    path: Path
    owner_run_id: str
    expected_head: str | None
    initial_status_sha256: str


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    working_directory: str
    returncode: int
    stdout_path: str
    stderr_path: str
    started_at: str
    finished_at: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_identifier(value: str, context: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise EvaluationError(f"{context} must be a safe non-empty identifier")
    if value in {".", ".."}:
        raise EvaluationError(f"{context} must not be a relative-path marker")
    return value


def _run_process(
    argv: Sequence[str],
    *,
    working_directory: Path,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(argv),
            cwd=working_directory,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise EvaluationError(
            f"unable to execute {argv[0]!r}: {type(error).__name__}"
        ) from error


def _run_checked(
    argv: Sequence[str],
    *,
    working_directory: Path,
    timeout_seconds: int,
    context: str,
) -> subprocess.CompletedProcess[str]:
    completed = _run_process(
        argv,
        working_directory=working_directory,
        timeout_seconds=timeout_seconds,
    )
    if completed.returncode != 0:
        raise EvaluationError(
            f"{context} failed with exit code {completed.returncode}"
        )
    return completed


def _git_checked(
    repository: Path,
    arguments: Sequence[str],
    context: str,
) -> subprocess.CompletedProcess[str]:
    return _run_checked(
        ["git", "-C", str(repository), *arguments],
        working_directory=repository.parent,
        timeout_seconds=_GIT_TIMEOUT_SECONDS,
        context=context,
    )


def _git_output(repository: Path, arguments: Sequence[str], context: str) -> str:
    return _git_checked(repository, arguments, context).stdout.rstrip("\n")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ensure_sha(value: str, context: str) -> str:
    if not _SHA_PATTERN.fullmatch(value):
        raise EvaluationError(f"{context} did not resolve to a 40-character Git SHA")
    return value


def resolve_variant(repo_root: Path, ref: str) -> ResolvedVariant:
    """Resolve a supplied skill ref once and retain only blinded commit metadata."""

    repository = Path(repo_root).resolve(strict=True)
    if not isinstance(ref, str) or not ref or any(character in ref for character in "\x00\n\r"):
        raise EvaluationError("variant ref must be a non-empty single-line string")
    top_level = Path(
        _git_output(repository, ["rev-parse", "--show-toplevel"], "repository discovery")
    ).resolve(strict=True)
    if top_level != repository:
        raise EvaluationError("repo_root must identify the exact Git repository root")

    commit_sha = _ensure_sha(
        _git_output(
            repository,
            ["rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
            "variant resolution",
        ),
        "variant ref",
    )
    subject = _git_output(
        repository,
        ["show", "-s", "--format=%s", commit_sha],
        "commit subject lookup",
    )
    return ResolvedVariant(
        supplied_ref=ref,
        commit_sha=commit_sha,
        commit_subject_sha256=_sha256_text(subject),
    )


def verify_benchmark_range(mirror: Path, benchmark: Benchmark) -> None:
    """Require the frozen comparison commit to be the baseline's immediate child."""

    repository = Path(mirror).resolve(strict=True)
    baseline = _ensure_sha(benchmark.baseline_sha, "benchmark baseline")
    comparison = _ensure_sha(benchmark.comparison_sha, "benchmark comparison")
    parent = _ensure_sha(
        _git_output(
            repository,
            ["rev-parse", "--verify", "--end-of-options", f"{comparison}^"],
            "benchmark parent resolution",
        ),
        "comparison parent",
    )
    if parent != baseline:
        raise EvaluationError(
            "benchmark comparison must have the baseline as its immediate parent"
        )


def _validate_archive_name(name: str, context: str) -> PurePosixPath:
    if not name or "\\" in name or any(character in name for character in "\x00\n\r"):
        raise EvaluationError(f"{context} contains an unsafe path")
    path = PurePosixPath(name)
    windows_path = PureWindowsPath(name)
    if windows_path.drive:
        raise EvaluationError(f"{context} contains a Windows drive")
    if path.is_absolute() or windows_path.is_absolute() or ".." in path.parts:
        raise EvaluationError(f"{context} escapes the extraction root")
    normalized = PurePosixPath(*[part for part in path.parts if part not in {"", "."}])
    if not normalized.parts:
        raise EvaluationError(f"{context} is empty after normalization")
    return normalized


def _safe_extract_tar(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    seen: set[str] = set()
    try:
        with tarfile.open(archive_path, "r:*") as archive:
            for member in archive.getmembers():
                relative = _validate_archive_name(member.name, "TAR member")
                normalized = relative.as_posix()
                if normalized in seen:
                    raise EvaluationError(f"duplicate TAR member: {normalized}")
                seen.add(normalized)
                if member.issym():
                    raise EvaluationError(f"TAR symlink member is forbidden: {normalized}")
                if member.islnk():
                    raise EvaluationError(f"TAR hard-link member is forbidden: {normalized}")
                if member.ischr() or member.isblk() or member.isfifo() or member.isdev():
                    raise EvaluationError(f"TAR device or FIFO member is forbidden: {normalized}")
                target = destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise EvaluationError(f"unsupported TAR member type: {normalized}")
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise EvaluationError(f"unable to read TAR member: {normalized}")
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(member.mode & 0o777)
    except (OSError, tarfile.TarError) as error:
        raise EvaluationError(
            f"unable to extract source snapshot: {type(error).__name__}"
        ) from error


def _safe_extract_zip(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    seen: set[str] = set()
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                relative = _validate_archive_name(member.filename, "ZIP member")
                normalized = relative.as_posix()
                if normalized in seen:
                    raise EvaluationError(f"duplicate ZIP member: {normalized}")
                seen.add(normalized)
                parts = relative.parts
                if (
                    ".git" in parts
                    or ".superpowers" in parts
                    or "evaluations" in parts
                    or "material_review_evaluation" in parts
                    or relative.name == "judge-oracle.json"
                ):
                    raise EvaluationError(
                        f"standalone archive contains evaluator or oracle content: {normalized}"
                    )
                unix_mode = member.external_attr >> 16
                file_type = stat.S_IFMT(unix_mode)
                if file_type == stat.S_IFLNK:
                    raise EvaluationError(f"ZIP symlink member is forbidden: {normalized}")
                if file_type in {stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK}:
                    raise EvaluationError(f"ZIP device or FIFO member is forbidden: {normalized}")
                if member.flag_bits & 0x1:
                    raise EvaluationError(f"encrypted ZIP member is forbidden: {normalized}")
                target = destination.joinpath(*relative.parts)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                permissions = unix_mode & 0o777
                target.chmod(permissions or 0o644)
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise EvaluationError(
            f"unable to extract standalone archive: {type(error).__name__}"
        ) from error


def _inventory(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for entry in sorted(path.rglob("*")):
        relative = entry.relative_to(path).as_posix()
        if entry.is_symlink():
            raise EvaluationError(f"workspace inventory contains a symlink: {relative}")
        if entry.is_dir():
            continue
        if not entry.is_file():
            raise EvaluationError(f"workspace inventory contains a special file: {relative}")
        entries.append(
            {
                "path": relative,
                "mode": stat.S_IMODE(entry.stat().st_mode),
                "sha256": sha256_file(entry),
            }
        )
    return entries


def _inventory_hash(path: Path) -> str:
    return canonical_hash(_inventory(path))


def _record_file(run_root: Path, workspace_path: Path) -> Path:
    identifier = _sha256_text(str(workspace_path.resolve(strict=False)))
    return run_root / ".workspace-records" / f"{identifier}.json"


def _register_record(
    workspace_root: Path,
    record: WorkspaceRecord,
    state: dict[str, Any],
) -> None:
    run_root = workspace_root / record.owner_run_id
    registry = _record_file(run_root, record.path)
    registry.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        registry,
        {
            "schema": _OWNER_SCHEMA,
            "workspace_root": str(workspace_root),
            "record": {
                **asdict(record),
                "path": str(record.path),
            },
            "state": state,
        },
    )


def _derive_run_root(record: WorkspaceRecord) -> tuple[Path, Path]:
    absolute = record.path.absolute()
    matching = [parent for parent in absolute.parents if parent.name == record.owner_run_id]
    if not matching:
        raise EvaluationError("workspace path is not beneath its recorded run")
    run_root = matching[0]
    return run_root.parent, run_root


def _load_registered_record(record: WorkspaceRecord) -> tuple[Path, dict[str, Any]]:
    workspace_root, run_root = _derive_run_root(record)
    registry = _record_file(run_root, record.path)
    if registry.is_symlink() or not registry.is_file():
        raise EvaluationError(f"workspace is not recorded for cleanup: {record.path}")
    try:
        value = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvaluationError("workspace ownership record is unreadable") from error
    expected_record = {**asdict(record), "path": str(record.path)}
    if (
        not isinstance(value, dict)
        or value.get("schema") != _OWNER_SCHEMA
        or value.get("workspace_root") != str(workspace_root)
        or value.get("record") != expected_record
        or not isinstance(value.get("state"), dict)
    ):
        raise EvaluationError(f"workspace is not recorded for cleanup: {record.path}")
    return registry, value["state"]


def _write_command_evidence(
    evidence_path: Path,
    *,
    argv: Sequence[str],
    working_directory: Path,
    returncode: int,
    stdout_path: Path,
    stderr_path: Path,
    started_at: str,
    finished_at: str,
    timed_out: bool,
    normalized_failure_signature: str,
) -> None:
    atomic_write_json(
        evidence_path,
        {
            "argv": list(argv),
            "working_directory": str(working_directory),
            "returncode": returncode,
            "stdout_path": str(stdout_path),
            "stdout_sha256": sha256_file(stdout_path),
            "stderr_path": str(stderr_path),
            "stderr_sha256": sha256_file(stderr_path),
            "started_at": started_at,
            "finished_at": finished_at,
            "timed_out": timed_out,
            "normalized_failure_signature": normalized_failure_signature,
        },
    )


def _run_materialization_command(
    argv: Sequence[str],
    *,
    working_directory: Path,
    timeout_seconds: int,
    evidence_root: Path,
    label: str,
) -> dict[str, Any]:
    stdout_path = evidence_root / f"{label}.stdout.log"
    stderr_path = evidence_root / f"{label}.stderr.log"
    started_at = _utc_now()
    completed = _run_process(
        argv,
        working_directory=working_directory,
        timeout_seconds=timeout_seconds,
    )
    finished_at = _utc_now()
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    signature = canonical_hash(
        {
            "argv": list(argv),
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "timed_out": False,
        }
    )
    evidence_path = evidence_root / f"{label}.json"
    _write_command_evidence(
        evidence_path,
        argv=argv,
        working_directory=working_directory,
        returncode=completed.returncode,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        started_at=started_at,
        finished_at=finished_at,
        timed_out=False,
        normalized_failure_signature=signature,
    )
    if completed.returncode != 0:
        raise EvaluationError(
            f"variant-specific {label} failed; evidence: {evidence_path}"
        )
    return json.loads(evidence_path.read_text(encoding="utf-8"))


def materialize_variant(
    repo_root: Path,
    variant: ResolvedVariant,
    workspace_root: Path,
    run_id: str,
    *,
    anonymous_identifier: str | None = None,
) -> WorkspaceRecord:
    """Package and validate one immutable historical skill distribution."""

    repository = Path(repo_root).resolve(strict=True)
    workspace = Path(workspace_root).resolve(strict=False)
    workspace.mkdir(parents=True, exist_ok=True)
    _require_identifier(run_id, "run_id")
    _ensure_sha(variant.commit_sha, "resolved variant")
    identifier = _require_identifier(
        anonymous_identifier or f"workflow-{uuid.uuid4().hex}",
        "anonymous workflow identifier",
    )

    run_root = workspace / run_id
    variant_root = run_root / "variants" / identifier
    private_materialization = run_root / "private" / "materialization" / identifier
    evidence_root = private_materialization / "evidence"
    source_snapshot = private_materialization / "source"
    workflow = variant_root / "workflow" / "material-code-review"
    source_archive = evidence_root / "source.tar"
    full_archive = evidence_root / "discarded-full.zip"
    standalone_archive = evidence_root / "standalone.zip"
    materialization_evidence = evidence_root / "materialization.json"
    if variant_root.exists() or source_snapshot.exists():
        raise EvaluationError("variant workspace already exists")

    evidence_root.mkdir(parents=True)
    source_snapshot.parent.mkdir(parents=True, exist_ok=True)
    command_evidence: list[dict[str, Any]] = []
    try:
        _run_checked(
            [
                "git",
                "-C",
                str(repository),
                "archive",
                "--format=tar",
                f"--output={source_archive}",
                variant.commit_sha,
            ],
            working_directory=repository,
            timeout_seconds=_GIT_TIMEOUT_SECONDS,
            context="variant source archive",
        )
        _safe_extract_tar(source_archive, source_snapshot)
        package_script = source_snapshot / "scripts/package_plugin.py"
        validator_script = source_snapshot / "scripts/validate_package.py"
        if not package_script.is_file() or not validator_script.is_file():
            raise EvaluationError("selected variant lacks its packager or validator")

        command_evidence.append(
            _run_materialization_command(
                [
                    sys.executable,
                    str(package_script),
                    "--package-root",
                    str(source_snapshot),
                    "--output",
                    str(full_archive),
                    "--standalone-output",
                    str(standalone_archive),
                ],
                working_directory=source_snapshot,
                timeout_seconds=_PACKAGING_TIMEOUT_SECONDS,
                evidence_root=evidence_root,
                label="package",
            )
        )
        command_evidence.append(
            _run_materialization_command(
                [
                    sys.executable,
                    str(validator_script),
                    "--package-root",
                    str(source_snapshot),
                    "--standalone-archive",
                    str(standalone_archive),
                ],
                working_directory=source_snapshot,
                timeout_seconds=_PACKAGING_TIMEOUT_SECONDS,
                evidence_root=evidence_root,
                label="validate",
            )
        )
        _safe_extract_zip(standalone_archive, workflow)
        inventory = _inventory(workflow)
        inventory_sha256 = canonical_hash(inventory)
        atomic_write_json(
            materialization_evidence,
            {
                "status": "complete",
                "supplied_ref": variant.supplied_ref,
                "commit_sha": variant.commit_sha,
                "commit_subject_sha256": variant.commit_subject_sha256,
                "source_archive_sha256": sha256_file(source_archive),
                "standalone_archive_sha256": sha256_file(standalone_archive),
                "inventory_sha256": inventory_sha256,
                "commands": command_evidence,
            },
        )
        record = WorkspaceRecord(
            kind="variant-workflow",
            path=workflow,
            owner_run_id=run_id,
            expected_head=None,
            initial_status_sha256=inventory_sha256,
        )
        _register_record(workspace, record, {"inventory_sha256": inventory_sha256})
        return record
    except EvaluationError as error:
        if not materialization_evidence.exists():
            atomic_write_json(
                materialization_evidence,
                {
                    "status": "failed",
                    "supplied_ref": variant.supplied_ref,
                    "commit_sha": variant.commit_sha,
                    "commit_subject_sha256": variant.commit_subject_sha256,
                    "error_type": type(error).__name__,
                    "commands": command_evidence,
                },
            )
        raise
    finally:
        if source_snapshot.exists() and not source_snapshot.is_symlink():
            shutil.rmtree(source_snapshot)
        for discarded in (full_archive, full_archive.with_suffix(full_archive.suffix + ".sha256")):
            try:
                discarded.unlink()
            except FileNotFoundError:
                pass


def _content_inventory(inventory: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {"path": str(entry["path"]), "sha256": str(entry["sha256"])}
        for entry in inventory
    ]


def _make_tree_read_only(path: Path) -> None:
    entries = sorted(path.rglob("*"), key=lambda entry: len(entry.parts), reverse=True)
    for entry in entries:
        if entry.is_symlink():
            raise EvaluationError("workflow snapshot contains a symlink")
        mode = stat.S_IMODE(entry.stat().st_mode)
        if entry.is_dir():
            entry.chmod((mode & ~0o222) | 0o500)
        elif entry.is_file():
            entry.chmod(mode & ~0o222)
        else:
            raise EvaluationError("workflow snapshot contains a special file")
    root_mode = stat.S_IMODE(path.stat().st_mode)
    path.chmod((root_mode & ~0o222) | 0o500)


def _make_tree_owner_writable(path: Path) -> None:
    path.chmod(stat.S_IMODE(path.stat().st_mode) | 0o700)
    for entry in path.rglob("*"):
        mode = stat.S_IMODE(entry.stat().st_mode)
        if entry.is_dir():
            entry.chmod(mode | 0o700)
        elif entry.is_file():
            entry.chmod(mode | 0o600)


def attest_immutable_workflow(record: WorkspaceRecord) -> dict[str, str]:
    """Verify a registered canonical or per-attempt workflow has not changed."""

    if record.kind not in {"variant-workflow", "trial-workflow"}:
        raise EvaluationError("workflow attestation requires a workflow record")
    _, initial = _load_registered_record(record)
    current_inventory_sha256 = _inventory_hash(record.path)
    if (
        current_inventory_sha256 != record.initial_status_sha256
        or current_inventory_sha256 != initial.get("inventory_sha256")
    ):
        raise EvaluationError("workflow has unrecorded changes")
    if record.kind == "trial-workflow":
        for entry in (record.path, *record.path.rglob("*")):
            if entry.is_symlink() or not (entry.is_dir() or entry.is_file()):
                raise EvaluationError("workflow has unrecorded changes")
            if stat.S_IMODE(entry.stat().st_mode) & 0o222:
                raise EvaluationError("workflow has unrecorded changes")
    return {"inventory_sha256": current_inventory_sha256}


def create_trial_workflow(
    canonical_workflow: WorkspaceRecord,
    workspace_root: Path,
    run_id: str,
    trial_identifier: str,
) -> WorkspaceRecord:
    """Create one anonymous, read-only workflow snapshot for a single attempt."""

    if canonical_workflow.kind != "variant-workflow":
        raise EvaluationError("trial workflow source must be a canonical variant workflow")
    workspace = Path(workspace_root).resolve(strict=True)
    _require_identifier(run_id, "run_id")
    _require_identifier(trial_identifier, "trial workflow identifier")
    if canonical_workflow.owner_run_id != run_id:
        raise EvaluationError("trial workflow source belongs to a different run")
    source_workspace, _ = _derive_run_root(canonical_workflow)
    if source_workspace.resolve(strict=True) != workspace:
        raise EvaluationError("trial workflow source belongs to a different workspace root")
    attest_immutable_workflow(canonical_workflow)
    source_inventory = _inventory(canonical_workflow.path)

    destination = (
        workspace
        / run_id
        / "trial-workflows"
        / trial_identifier
        / "material-code-review"
    )
    if destination.exists() or destination.is_symlink():
        raise EvaluationError("trial workflow workspace already exists")
    destination.parent.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copytree(canonical_workflow.path, destination, symlinks=False)
        copied_inventory = _inventory(destination)
        if _content_inventory(copied_inventory) != _content_inventory(source_inventory):
            raise EvaluationError("trial workflow does not match its canonical source")
        _make_tree_read_only(destination)
        inventory_sha256 = _inventory_hash(destination)
        record = WorkspaceRecord(
            kind="trial-workflow",
            path=destination,
            owner_run_id=run_id,
            expected_head=None,
            initial_status_sha256=inventory_sha256,
        )
        _register_record(
            workspace,
            record,
            {
                "inventory_sha256": inventory_sha256,
                "source_inventory_sha256": canonical_workflow.initial_status_sha256,
            },
        )
        attest_immutable_workflow(record)
        return record
    except BaseException:
        if destination.exists() and not destination.is_symlink():
            destination.chmod(0o700)
            for entry in destination.rglob("*"):
                if entry.is_dir():
                    entry.chmod(0o700)
                elif entry.is_file():
                    entry.chmod(0o600)
            shutil.rmtree(destination)
        raise


def _mirror_attestation(mirror: Path) -> dict[str, str]:
    head = _git_output(mirror, ["rev-parse", "HEAD"], "mirror HEAD lookup")
    refs = _git_output(
        mirror,
        ["for-each-ref", "--format=%(refname)%00%(objectname)%00%(symref)"],
        "mirror refs lookup",
    )
    objects = _git_output(
        mirror,
        ["rev-list", "--objects", "--all", "HEAD"],
        "mirror object range lookup",
    )
    remote = _git_output(
        mirror,
        ["config", "--get", "remote.origin.url"],
        "mirror remote lookup",
    )
    return {
        "head": head,
        "refs_sha256": _sha256_text(refs),
        "object_range_sha256": _sha256_text(objects),
        "remote_url": remote,
    }


def prepare_target_mirror(
    source_repository: Benchmark | str | Path,
    workspace_root: Path,
    run_id: str,
) -> WorkspaceRecord:
    """Create the one run-owned mirror from which all target trials clone."""

    workspace = Path(workspace_root).resolve(strict=False)
    workspace.mkdir(parents=True, exist_ok=True)
    _require_identifier(run_id, "run_id")
    mirror = workspace / run_id / "mirrors" / "target.git"
    if mirror.exists():
        raise EvaluationError("target mirror already exists")
    mirror.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(source_repository, Benchmark):
        source = source_repository.target_repository
    elif isinstance(source_repository, Path):
        source = str(source_repository.resolve(strict=True))
    elif (
        isinstance(source_repository, str)
        and source_repository
        and not any(character in source_repository for character in "\x00\n\r")
    ):
        source = source_repository
    else:
        raise EvaluationError("target repository must be a validated URL or local Path")
    _run_checked(
        ["git", "clone", "--mirror", "--no-local", source, str(mirror)],
        working_directory=mirror.parent,
        timeout_seconds=_GIT_TIMEOUT_SECONDS,
        context="target mirror clone",
    )
    state = _mirror_attestation(mirror)
    record = WorkspaceRecord(
        kind="target-mirror",
        path=mirror,
        owner_run_id=run_id,
        expected_head=state["head"],
        initial_status_sha256=canonical_hash(state),
    )
    _register_record(workspace, record, state)
    return record


def _target_attestation(target: Path) -> dict[str, str]:
    head = _git_output(target, ["rev-parse", "HEAD"], "target HEAD lookup")
    branch_process = _run_process(
        ["git", "-C", str(target), "symbolic-ref", "--short", "-q", "HEAD"],
        working_directory=target,
        timeout_seconds=_GIT_TIMEOUT_SECONDS,
    )
    if branch_process.returncode not in {0, 1}:
        raise EvaluationError("target branch lookup failed")
    branch = branch_process.stdout.rstrip("\n")
    status = _git_output(
        target,
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        "target status lookup",
    )
    index_flags = _git_output(
        target,
        ["ls-files", "-v", "-z"],
        "target index flags lookup",
    )
    refs = _git_output(
        target,
        ["for-each-ref", "--format=%(refname)%00%(objectname)%00%(symref)"],
        "target refs lookup",
    )
    objects = _git_output(
        target,
        ["rev-list", "--objects", "--all", "HEAD"],
        "target object range lookup",
    )
    remote_process = _run_process(
        ["git", "-C", str(target), "config", "--get", "remote.origin.url"],
        working_directory=target,
        timeout_seconds=_GIT_TIMEOUT_SECONDS,
    )
    if remote_process.returncode not in {0, 1}:
        raise EvaluationError("target remote lookup failed")
    return {
        "head": head,
        "branch": branch,
        "status_sha256": _sha256_text(status),
        "index_flags_sha256": _sha256_text(index_flags),
        "refs_sha256": _sha256_text(refs),
        "object_range_sha256": _sha256_text(objects),
        "remote_url": remote_process.stdout.rstrip("\n"),
    }


def _require_owned_mirror(
    mirror: Path,
    workspace: Path,
    run_id: str,
) -> None:
    expected = workspace / run_id / "mirrors" / "target.git"
    if mirror != expected or mirror.is_symlink():
        raise EvaluationError("trial source must be the exact run-owned local mirror")
    head = _git_output(mirror, ["rev-parse", "HEAD"], "mirror ownership lookup")
    candidate = WorkspaceRecord(
        kind="target-mirror",
        path=mirror,
        owner_run_id=run_id,
        expected_head=head,
        initial_status_sha256=canonical_hash(_mirror_attestation(mirror)),
    )
    _load_registered_record(candidate)


def create_trial_target(
    mirror: Path,
    benchmark: Benchmark,
    workspace_root: Path,
    run_id: str,
    trial_id: str,
) -> WorkspaceRecord:
    """Create a fresh detached target clone from the run-owned local mirror."""

    workspace = Path(workspace_root).resolve(strict=False)
    _require_identifier(run_id, "run_id")
    _require_identifier(trial_id, "trial_id")
    mirror_path = Path(mirror).resolve(strict=True)
    _require_owned_mirror(mirror_path, workspace, run_id)
    verify_benchmark_range(mirror_path, benchmark)

    target = workspace / run_id / "targets" / trial_id
    if target.exists():
        raise EvaluationError("trial target already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    _run_checked(
        ["git", "clone", "--no-checkout", "--no-local", str(mirror_path), str(target)],
        working_directory=target.parent,
        timeout_seconds=_GIT_TIMEOUT_SECONDS,
        context="trial target clone",
    )
    _git_checked(
        target,
        ["checkout", "--quiet", "--detach", benchmark.comparison_sha],
        "trial target checkout",
    )
    state = _target_attestation(target)
    if state["head"] != benchmark.comparison_sha or state["branch"]:
        raise EvaluationError("trial target is not detached at the comparison SHA")
    if state["remote_url"] != str(mirror_path):
        raise EvaluationError("trial target remote is not the run-owned local mirror")
    record = WorkspaceRecord(
        kind="trial-target",
        path=target,
        owner_run_id=run_id,
        expected_head=benchmark.comparison_sha,
        initial_status_sha256=state["status_sha256"],
    )
    _register_record(workspace, record, state)
    return record


def _git_differs(target: Path, arguments: Sequence[str]) -> bool:
    completed = _run_process(
        ["git", "-C", str(target), *arguments],
        working_directory=target,
        timeout_seconds=_GIT_TIMEOUT_SECONDS,
    )
    if completed.returncode not in {0, 1}:
        raise EvaluationError("target cleanliness diff failed")
    return completed.returncode == 1


def attest_clean_target(record: WorkspaceRecord) -> dict[str, object]:
    """Re-attest a trial clone against every recorded immutable Git property."""

    if record.kind != "trial-target" or record.expected_head is None:
        raise EvaluationError("cleanliness attestation requires a trial-target record")
    if record.path.is_symlink():
        raise EvaluationError("cleanliness attestation refuses a symlinked target")
    _, initial = _load_registered_record(record)
    current = _target_attestation(record.path)
    if current["head"] != record.expected_head or current["head"] != initial.get("head"):
        raise EvaluationError("target HEAD changed after trial creation")
    if current["branch"] != initial.get("branch"):
        raise EvaluationError("target branch changed after trial creation")
    if current["remote_url"] != initial.get("remote_url"):
        raise EvaluationError("target remote URL changed after trial creation")
    if current["index_flags_sha256"] != initial.get("index_flags_sha256"):
        raise EvaluationError("target index flags changed after trial creation")
    if current["status_sha256"] != record.initial_status_sha256:
        if _git_differs(record.path, ["diff", "--cached", "--quiet"]):
            raise EvaluationError("target index changed after trial creation")
        if _git_differs(record.path, ["diff", "--quiet"]):
            raise EvaluationError("target worktree changed after trial creation")
        raise EvaluationError("target has unrecorded changes after trial creation")
    if current["refs_sha256"] != initial.get("refs_sha256"):
        raise EvaluationError("target refs changed after trial creation")
    if current["object_range_sha256"] != initial.get("object_range_sha256"):
        raise EvaluationError("target object range changed after trial creation")
    return dict(current)


def _normalize_command_output(value: str, target: Path, logs_root: Path) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.replace(str(target), "<TARGET>").replace(str(logs_root), "<LOGS>")


def run_benchmark_commands(
    target: Path | WorkspaceRecord,
    commands: tuple[CommandSpec, ...],
    logs_root: Path,
) -> tuple[CommandResult, ...]:
    """Execute validated manifest commands with isolated, hashed logs."""

    target_path = (
        target.path if isinstance(target, WorkspaceRecord) else Path(target)
    ).resolve(strict=True)
    log_directory = Path(logs_root).resolve(strict=False)
    log_directory.mkdir(parents=True, exist_ok=False)
    results: list[CommandResult] = []
    for index, command in enumerate(commands):
        if (
            not isinstance(command, CommandSpec)
            or not command.argv
            or command.timeout_seconds <= 0
        ):
            raise EvaluationError("benchmark commands must be validated CommandSpec values")
        safe_working_directory = safe_relative_path(
            command.working_directory.as_posix(),
            "benchmark command working directory",
        )
        working_directory = target_path.joinpath(*safe_working_directory.parts).resolve(
            strict=True
        )
        try:
            working_directory.relative_to(target_path)
        except ValueError as error:
            raise EvaluationError("benchmark command working directory escapes target") from error
        if not working_directory.is_dir():
            raise EvaluationError("benchmark command working directory must be a directory")

        stdout_path = log_directory / f"command-{index:03d}.stdout.log"
        stderr_path = log_directory / f"command-{index:03d}.stderr.log"
        evidence_path = log_directory / f"command-{index:03d}.json"
        started_at = _utc_now()
        timed_out = False
        try:
            completed = subprocess.run(
                list(command.argv),
                cwd=working_directory,
                check=False,
                capture_output=True,
                text=True,
                timeout=command.timeout_seconds,
                shell=False,
            )
            returncode = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as error:
            timed_out = True
            returncode = 124
            stdout = error.stdout or ""
            stderr = error.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
        except OSError as error:
            returncode = 127
            stdout = ""
            stderr = f"unable to execute command: {type(error).__name__}\n"
        finished_at = _utc_now()
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        normalized_signature = canonical_hash(
            {
                "argv": list(command.argv),
                "returncode": returncode,
                "stdout": _normalize_command_output(stdout, target_path, log_directory),
                "stderr": _normalize_command_output(stderr, target_path, log_directory),
                "timed_out": timed_out,
            }
        )
        _write_command_evidence(
            evidence_path,
            argv=command.argv,
            working_directory=working_directory,
            returncode=returncode,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            started_at=started_at,
            finished_at=finished_at,
            timed_out=timed_out,
            normalized_failure_signature=normalized_signature,
        )
        results.append(
            CommandResult(
                argv=command.argv,
                working_directory=command.working_directory.as_posix(),
                returncode=returncode,
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
                started_at=started_at,
                finished_at=finished_at,
            )
        )
    return tuple(results)


def _git_common_directory(repository: Path) -> Path | None:
    if not repository.is_dir():
        return None
    completed = _run_process(
        ["git", "-C", str(repository), "rev-parse", "--git-common-dir"],
        working_directory=repository,
        timeout_seconds=_GIT_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        return None
    common = Path(completed.stdout.rstrip("\n"))
    if not common.is_absolute():
        common = repository / common
    return common.resolve(strict=True)


def _reject_active_repository_alias(protected_repository: Path, candidate: Path) -> None:
    protected = protected_repository.resolve(strict=True)
    resolved = candidate.resolve(strict=True)
    if (
        resolved == protected
        or protected in resolved.parents
        or resolved in protected.parents
    ):
        raise EvaluationError("cleanup refuses the active repository or its path aliases")
    protected_git = _git_common_directory(protected)
    candidate_git = _git_common_directory(resolved)
    if protected_git is not None and candidate_git == protected_git:
        raise EvaluationError("cleanup refuses an active repository worktree alias")


def _reject_symlink_components(workspace_root: Path, candidate: Path) -> None:
    relative = candidate.absolute().relative_to(workspace_root.absolute())
    current = workspace_root.absolute()
    for part in (None, *relative.parts):
        if part is not None:
            current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError as error:
            raise EvaluationError(f"recorded workspace is missing: {candidate}") from error
        if stat.S_ISLNK(mode):
            raise EvaluationError(f"cleanup refuses a symlinked workspace: {candidate}")


def clean_owned_workspaces(
    repository_root: Path,
    records: Iterable[WorkspaceRecord],
) -> tuple[Path, ...]:
    """Remove only exact, registered, unchanged descendants owned by a run."""

    protected = Path(repository_root)
    approved: list[tuple[WorkspaceRecord, Path]] = []
    seen: set[Path] = set()
    for record in records:
        if not isinstance(record, WorkspaceRecord):
            raise EvaluationError("cleanup accepts only WorkspaceRecord values")
        path = record.path.absolute()
        if path.is_symlink():
            raise EvaluationError(f"cleanup refuses a symlinked workspace: {path}")
        if not path.exists() or not path.is_dir():
            raise EvaluationError(f"recorded workspace is missing: {path}")
        _reject_active_repository_alias(protected, path)
        workspace_root, run_root = _derive_run_root(record)
        try:
            relative = path.relative_to(run_root)
        except ValueError as error:
            raise EvaluationError("workspace is not a descendant of its run root") from error
        if len(relative.parts) < 2:
            raise EvaluationError("workspace cleanup target is too broad")
        _reject_symlink_components(workspace_root, path)
        if path in seen:
            raise EvaluationError("duplicate workspace cleanup target")
        seen.add(path)
        registry, initial = _load_registered_record(record)
        if record.kind == "trial-target":
            attest_clean_target(record)
        elif record.kind in {"variant-workflow", "trial-workflow"}:
            attest_immutable_workflow(record)
        elif record.kind == "target-mirror":
            if canonical_hash(_mirror_attestation(path)) != record.initial_status_sha256:
                raise EvaluationError("target mirror has unrecorded changes")
        else:
            raise EvaluationError(f"unsupported workspace kind: {record.kind}")
        approved.append((record, registry))

    removed: list[Path] = []
    for record, registry in approved:
        if record.kind == "trial-workflow":
            _make_tree_owner_writable(record.path)
        shutil.rmtree(record.path)
        registry.unlink()
        removed.append(record.path)
    return tuple(removed)
