#!/usr/bin/env python3
"""Build a reproducible standalone material-code-simplification Agent Skill ZIP.

Run from the material-code-review-plugin repository root. The archive mirrors
its existing standalone contract: SKILL.md is at the ZIP root, while the shared
controller and schemas are packaged under core/.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path

SKILL_NAME = "material-code-simplification"
FIXED_TIMESTAMP = (2026, 7, 17, 0, 0, 0)
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".zip", ".sha256"}
WINDOWS_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


def include(path: Path) -> bool:
    return not any(part in EXCLUDED_PARTS for part in path.parts) and path.suffix.lower() not in EXCLUDED_SUFFIXES


def normalized_mode(path: Path) -> int:
    mode = stat.S_IMODE(path.stat().st_mode)
    return 0o755 if mode & 0o111 else 0o644


def validate_source_file(source: Path, allowed_root: Path) -> Path:
    try:
        allowed_root_info = allowed_root.lstat()
        source_info = source.lstat()
        resolved_root = allowed_root.resolve(strict=True)
        resolved_source = source.resolve(strict=True)
    except OSError as exc:
        raise SystemExit(f"cannot validate archive source {source}: {exc}") from exc

    if stat.S_ISLNK(allowed_root_info.st_mode):
        raise SystemExit(f"archive source root must not be a symlink: {allowed_root}")
    if stat.S_ISLNK(source_info.st_mode):
        raise SystemExit(f"archive source must not be a symlink: {source}")
    if not stat.S_ISREG(source_info.st_mode):
        raise SystemExit(f"archive source must be a regular file: {source}")
    if not resolved_source.is_relative_to(resolved_root):
        raise SystemExit(f"archive source escapes approved root {allowed_root}: {source}")
    return source


def normalize_archive_path(archive_path: str) -> str:
    normalized = archive_path.replace("\\", "/")
    if not normalized or "\x00" in normalized or normalized.startswith("/"):
        raise SystemExit(f"unsafe archive entry: {archive_path}")
    if WINDOWS_DRIVE_PREFIX.match(normalized):
        raise SystemExit(f"unsafe archive entry: {archive_path}")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SystemExit(f"unsafe archive entry: {archive_path}")
    return "/".join(parts)


def write_file(archive: zipfile.ZipFile, source: Path, archive_path: str) -> None:
    info = zipfile.ZipInfo(archive_path, date_time=FIXED_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = normalized_mode(source) << 16
    info.flag_bits |= 0x800
    archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def iter_files(root: Path):
    skill = root / "skills" / SKILL_NAME
    core = root / "skills" / "material-code-review"
    if not skill.is_dir():
        raise SystemExit(f"missing skill directory: {skill}")
    if not (core / "scripts" / "reviewctl.py").is_file():
        raise SystemExit(f"missing shared controller: {core / 'scripts' / 'reviewctl.py'}")

    for source in sorted(path for path in skill.rglob("*") if path.is_file() and include(path.relative_to(skill))):
        yield validate_source_file(source, skill), source.relative_to(skill).as_posix()
    for name in ("LICENSE", "SECURITY.md"):
        source = root / name
        if source.is_file():
            yield validate_source_file(source, root), name
    yield validate_source_file(core / "scripts" / "reviewctl.py", core), "core/reviewctl.py"
    for source in sorted((core / "schemas").glob("*.json")):
        yield validate_source_file(source, core), f"core/schemas/{source.name}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Plugin repository root")
    parser.add_argument(
        "--output",
        default=f"dist/{SKILL_NAME}.zip",
        help="Output ZIP path",
    )
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    output = Path(args.output).expanduser()
    if not output.is_absolute():
        output = root / output
    entries = sorted(iter_files(root), key=lambda item: item[1])
    resolved_output = output.resolve(strict=False)
    for source, _archive_path in entries:
        if source.resolve(strict=True) == resolved_output:
            raise SystemExit(f"output path aliases an archive source: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        seen: set[str] = set()
        with zipfile.ZipFile(temp, "w", allowZip64=True) as archive:
            archive.comment = b"material-code-simplification standalone Agent Skill"
            for source, archive_path in entries:
                normalized_archive_path = normalize_archive_path(archive_path)
                if normalized_archive_path in seen:
                    raise SystemExit(f"duplicate normalized archive entry: {normalized_archive_path}")
                seen.add(normalized_archive_path)
                write_file(archive, source, normalized_archive_path)
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{digest}  {output.name}\n", encoding="utf-8", newline="\n"
    )
    print(f"[OK] Wrote {output}")
    print(f"SHA-256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
