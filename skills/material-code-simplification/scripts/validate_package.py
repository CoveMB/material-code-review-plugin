#!/usr/bin/env python3
"""Validate material-code-simplification in full-plugin or standalone layout."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0.0"
BASE_REQUIRED = {
    "SKILL.md",
    "agents/openai.yaml",
    "scripts/simplifyctl.py",
    "scripts/validate_package.py",
    "tests/test_simplifyctl.py",
    "examples/field-mapping.md",
    "references/context-checklist.md",
    "references/simplification-rubric.md",
    "references/ai-agent-failure-catalog.md",
    "references/architecture-reviewer-template.md",
    "references/code-reviewer-template.md",
    "references/validator-template.md",
    "references/adjudicator-template.md",
    "references/planner-template.md",
    "references/refactorer-template.md",
    "references/postfix-verifier-template.md",
    "references/output-template.md",
    "references/failure-model.md",
    "references/workflow.md",
}
ARCHIVE_REQUIRED = BASE_REQUIRED | {
    "LICENSE",
    "SECURITY.md",
    "core/reviewctl.py",
    "core/schemas/candidate-set.schema.json",
    "core/schemas/adjudication.schema.json",
    "core/schemas/fix-plan.schema.json",
    "core/schemas/verification.schema.json",
}
ARCHIVE_EXECUTABLES = {
    "scripts/simplifyctl.py",
    "scripts/validate_package.py",
    "core/reviewctl.py",
}
ARCHIVE_FORBIDDEN_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".git",
}
ARCHIVE_FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".zip", ".sha256"}
ARCHIVE_COMMENT = b"material-code-simplification standalone Agent Skill"


def normalize_archive_member(name: str) -> str:
    normalized = name.replace("\\", "/")
    if not normalized or "\x00" in normalized or normalized.startswith("/"):
        raise ValueError(f"unsafe archive path: {name}")
    if re.match(r"^[A-Za-z]:", normalized):
        raise ValueError(f"unsafe archive path: {name}")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe archive path: {name}")
    return "/".join(parts)


def windows_collision_key(archive_path: str) -> str:
    """Derive a Windows-safe collision key that accounts for case-insensitive matching
    and trailing dots or spaces."""
    parts = archive_path.split("/")
    normalized_parts = []
    for part in parts:
        # Strip trailing dots and spaces (Windows semantics)
        stripped = part.rstrip(". ")
        # Convert to lowercase for case-insensitive comparison
        normalized_parts.append(stripped.lower())
    return "/".join(normalized_parts)


def validate_extracted_archive(
    archive: zipfile.ZipFile,
    members: list[tuple[zipfile.ZipInfo, str]],
    archive_path: Path,
) -> list[str]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="material-code-simplification-") as temp_directory:
        extraction_root = Path(temp_directory).resolve()
        try:
            for info, normalized_name in members:
                destination = extraction_root.joinpath(*normalized_name.split("/"))
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.resolve(strict=False).is_relative_to(extraction_root):
                    raise ValueError(f"extraction destination escapes temporary root: {normalized_name}")
                if destination.exists() or destination.is_symlink():
                    raise ValueError(f"duplicate extraction destination: {normalized_name}")
                with archive.open(info, "r") as source, destination.open("xb") as target:
                    shutil.copyfileobj(source, target)
                mode = (info.external_attr >> 16) & 0o777
                os.chmod(destination, mode or 0o644)
        except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
            return [f"{archive_path.name}: safe extraction failed: {exc}"]
    return errors


def validate_archive(archive_path: Path) -> list[str]:
    if not archive_path.is_file():
        return [f"archive not found: {archive_path}"]
    errors: list[str] = []
    MAX_MEMBERS = 10_000
    MAX_MEMBER_SIZE = 100 * 1024 * 1024
    MAX_CUMULATIVE_SIZE = 500 * 1024 * 1024
    MAX_COMPRESSION_RATIO = 100
    try:
        with zipfile.ZipFile(archive_path) as archive:
            if archive.comment != ARCHIVE_COMMENT:
                errors.append(f"{archive_path.name}: identifying archive comment mismatch")
            seen: set[str] = set()
            seen_windows_keys: set[str] = set()
            members: list[tuple[zipfile.ZipInfo, str]] = []
            info_by_name: dict[str, zipfile.ZipInfo] = {}
            cumulative_size = 0
            for info in archive.infolist():
                if len(seen) >= MAX_MEMBERS:
                    errors.append(f"{archive_path.name}: archive exceeds maximum member count of {MAX_MEMBERS}")
                    return errors
                if info.file_size > MAX_MEMBER_SIZE:
                    errors.append(
                        f"{archive_path.name}: member {info.filename} exceeds maximum size of {MAX_MEMBER_SIZE} bytes"
                    )
                    return errors
                cumulative_size += info.file_size
                if cumulative_size > MAX_CUMULATIVE_SIZE:
                    errors.append(
                        f"{archive_path.name}: cumulative expanded size exceeds maximum of {MAX_CUMULATIVE_SIZE} bytes"
                    )
                    return errors
                if info.compress_size > 0 and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                    errors.append(
                        f"{archive_path.name}: member {info.filename} compression ratio exceeds maximum of {MAX_COMPRESSION_RATIO}"
                    )
                    return errors
                try:
                    normalized_name = normalize_archive_member(info.filename)
                except ValueError as exc:
                    errors.append(f"{archive_path.name}: {exc}")
                    continue
                if normalized_name != info.filename:
                    errors.append(f"{archive_path.name}: non-canonical archive path: {info.filename}")
                if normalized_name in seen:
                    errors.append(f"{archive_path.name}: duplicate normalized entry: {normalized_name}")
                    continue
                seen.add(normalized_name)
                collision_key = windows_collision_key(normalized_name)
                if collision_key in seen_windows_keys:
                    errors.append(
                        f"{archive_path.name}: entry {normalized_name} collides with an earlier entry "
                        f"under Windows case-insensitive/trailing-character semantics"
                    )
                    continue
                seen_windows_keys.add(collision_key)
                info_by_name[normalized_name] = info
                members.append((info, normalized_name))
                relative = Path(normalized_name)
                if (
                    any(part in ARCHIVE_FORBIDDEN_PARTS for part in relative.parts)
                    or relative.suffix.lower() in ARCHIVE_FORBIDDEN_SUFFIXES
                    or normalized_name == "CODEX.md"
                ):
                    errors.append(f"{archive_path.name}: forbidden archive entry: {normalized_name}")
                member_mode = (info.external_attr >> 16) & 0o177777
                if info.is_dir() or stat.S_ISLNK(member_mode):
                    errors.append(f"{archive_path.name}: non-regular archive entry: {normalized_name}")
                if info.flag_bits & 0x1:
                    errors.append(f"{archive_path.name}: encrypted archive entry: {normalized_name}")

            for name in sorted(ARCHIVE_REQUIRED - seen):
                errors.append(f"{archive_path.name}: missing archive entry: {name}")
            for name in sorted(ARCHIVE_EXECUTABLES & seen):
                info = info_by_name[name]
                if info.create_system != 3 or not ((info.external_attr >> 16) & stat.S_IXUSR):
                    errors.append(f"{archive_path.name}: executable mode missing: {name}")

            if "SKILL.md" in seen:
                skill_text = archive.read(info_by_name["SKILL.md"]).decode("utf-8", errors="replace")
                if not skill_text.startswith("---\n") or "name: material-code-simplification" not in skill_text.split("---", 2)[1]:
                    errors.append(f"{archive_path.name}: SKILL.md identity mismatch")
            if "agents/openai.yaml" in seen:
                yaml_text = archive.read(info_by_name["agents/openai.yaml"]).decode(
                    "utf-8", errors="replace"
                )
                if "$material-code-simplification" not in yaml_text:
                    errors.append(f"{archive_path.name}: openai.yaml invocation mismatch")

            if not errors:
                errors.extend(validate_extracted_archive(archive, members, archive_path))
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        errors.append(f"{archive_path.name}: invalid ZIP: {exc}")
    return errors


def resolve_core() -> tuple[str, Path, Path] | None:
    full = ROOT.parent / "material-code-review"
    standalone = ROOT / "core"
    if (standalone / "reviewctl.py").is_file():
        return "standalone", standalone / "reviewctl.py", standalone / "schemas"
    if (full / "scripts" / "reviewctl.py").is_file():
        return "full-plugin", full / "scripts" / "reviewctl.py", full / "schemas"
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        action="append",
        default=[],
        help="Standalone simplification ZIP to validate and execute.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    errors: list[str] = []
    if sys.version_info < (3, 10):
        errors.append("Python 3.10+ is required")
    source_paths = list(ROOT.rglob("*"))
    for path in source_paths:
        if path.is_symlink():
            errors.append(f"symlinked source path present: {path.relative_to(ROOT).as_posix()}")
    actual = {path.relative_to(ROOT).as_posix() for path in source_paths if path.is_file()}
    for rel in sorted(BASE_REQUIRED - actual):
        errors.append(f"missing required skill file: {rel}")
    for path in source_paths:
        rel = path.relative_to(ROOT)
        if "__pycache__" in rel.parts or ".pytest_cache" in rel.parts or path.suffix in {".pyc", ".pyo"}:
            errors.append(f"generated file present: {rel.as_posix()}")

    core_layout = resolve_core()
    if core_layout is None:
        errors.append("missing shared controller: expected sibling material-code-review or standalone core/")
        layout, controller, schema_dir = "missing", ROOT / "missing", ROOT / "missing"
    else:
        layout, controller, schema_dir = core_layout
        for name in (
            "candidate-set.schema.json",
            "adjudication.schema.json",
            "fix-plan.schema.json",
            "verification.schema.json",
        ):
            if not (schema_dir / name).is_file():
                errors.append(f"missing shared schema: {schema_dir / name}")

    skill = ROOT / "SKILL.md"
    if skill.is_file():
        text = skill.read_text(encoding="utf-8")
        if not text.startswith("---\n") or "name: material-code-simplification" not in text.split("---", 2)[1]:
            errors.append("SKILL.md frontmatter is missing or has the wrong name")
        for rel in sorted(set(re.findall(r"`((?:references|examples)/[A-Za-z0-9._/-]+)`", text))):
            if not (ROOT / rel).is_file():
                errors.append(f"SKILL.md references missing file: {rel}")

    if schema_dir.is_dir():
        for path in schema_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                errors.append(f"invalid JSON in {path.name}: {exc}")
                continue
            if data.get("type") != "object" or data.get("additionalProperties") is not False:
                errors.append(f"schema must be object and fail closed: {path.name}")

    for path, label in ((ROOT / "scripts" / "simplifyctl.py", "simplifyctl.py"), (controller, "reviewctl.py")):
        if path.is_file() and not sys.platform.startswith("win") and not (path.stat().st_mode & stat.S_IXUSR):
            errors.append(f"{label} is not executable")

    yaml = ROOT / "agents" / "openai.yaml"
    if yaml.is_file():
        text = yaml.read_text(encoding="utf-8")
        for token in ("interface:", "display_name:", "default_prompt:", "allow_implicit_invocation:"):
            if token not in text:
                errors.append(f"openai.yaml missing {token}")

    archive_paths = [Path(raw).expanduser().resolve() for raw in args.archive]
    for archive_path in archive_paths:
        errors.extend(validate_archive(archive_path))

    if errors:
        print("[FAIL] material-code-simplification validation", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"[OK] material-code-simplification {VERSION} is structurally valid ({layout})")
    for archive_path in archive_paths:
        print(f"[OK] standalone archive is safe: {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
