#!/usr/bin/env python3
"""Build reproducible full-plugin and standalone Codex-skill ZIP archives."""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
import sys
import zipfile
from pathlib import Path
from typing import Iterable

VERSION = "1.1.0"
FIXED_TIMESTAMP = (2026, 7, 17, 0, 0, 0)
EXCLUDED_PARTS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hypothesis",
    ".tox",
    ".nox",
    "dist",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".zip", ".sha256"}


def should_include(path: Path, root: Path, explicit_outputs: set[Path]) -> bool:
    resolved = path.resolve()
    if resolved in explicit_outputs:
        return False
    relative = path.relative_to(root)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if path.name in {".DS_Store", "Thumbs.db"}:
        return False
    return path.is_file() and not path.is_symlink()


def iter_full_files(root: Path, explicit_outputs: set[Path]) -> Iterable[tuple[Path, str]]:
    for path in sorted(root.rglob("*")):
        if should_include(path, root, explicit_outputs):
            yield path, path.relative_to(root).as_posix()


def iter_standalone_files(root: Path) -> Iterable[tuple[Path, str]]:
    skill = root / "skills/material-code-review"
    mappings: list[tuple[Path, str]] = [
        (skill / "SKILL.md", "SKILL.md"),
        (root / "LICENSE", "LICENSE"),
        (root / "SECURITY.md", "SECURITY.md"),
        (root / "CODEX.md", "CODEX.md"),
    ]
    for subdir in ("scripts", "references", "schemas", "agents", "examples", "tests"):
        base = skill / subdir
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(skill).as_posix()
            if any(part in EXCLUDED_PARTS for part in Path(relative).parts):
                continue
            if path.suffix.lower() in EXCLUDED_SUFFIXES:
                continue
            mappings.append((path, relative))
    for path, archive_name in sorted(mappings, key=lambda item: item[1]):
        if not path.is_file():
            raise FileNotFoundError(f"Standalone archive input is missing: {path}")
        yield path, archive_name


def write_entry(zf: zipfile.ZipFile, source: Path, archive_name: str) -> None:
    data = source.read_bytes()
    info = zipfile.ZipInfo(filename=archive_name, date_time=FIXED_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    mode = source.stat().st_mode
    permissions = 0o755 if mode & stat.S_IXUSR else 0o644
    info.external_attr = permissions << 16
    info.flag_bits |= 0x800  # UTF-8 names
    zf.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build_archive(output: Path, entries: Iterable[tuple[Path, str]], comment: str) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(f".{output.name}.tmp")
    if temp.exists():
        temp.unlink()
    seen: set[str] = set()
    with zipfile.ZipFile(temp, "w", allowZip64=True) as zf:
        zf.comment = comment.encode("utf-8")
        for source, archive_name in entries:
            normalized = archive_name.replace("\\", "/").lstrip("/")
            if not normalized or normalized in seen or ".." in Path(normalized).parts:
                raise ValueError(f"Unsafe or duplicate archive entry: {archive_name}")
            seen.add(normalized)
            write_entry(zf, source, normalized)
    temp.replace(output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum_path = output.with_suffix(output.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {output.name}\n", encoding="utf-8", newline="\n")
    return digest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", default=".", help="Source package root.")
    parser.add_argument(
        "--output",
        default=f"material-code-review-plugin-{VERSION}.zip",
        help="Full plugin ZIP output path.",
    )
    parser.add_argument(
        "--standalone-output",
        default=f"material-code-review-codex-skill-{VERSION}.zip",
        help="Standalone Codex skill ZIP output path; pass an empty string to skip.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.package_root).resolve()
    if not (root / ".codex-plugin/plugin.json").is_file():
        print(f"[FAIL] Not a Codex plugin root: {root}", file=sys.stderr)
        return 1

    output = Path(args.output).expanduser().resolve()
    standalone_output = Path(args.standalone_output).expanduser().resolve() if args.standalone_output else None
    explicit_outputs = {output}
    if standalone_output:
        explicit_outputs.add(standalone_output)
    explicit_outputs.update(path.with_suffix(path.suffix + ".sha256") for path in list(explicit_outputs))

    full_digest = build_archive(
        output,
        iter_full_files(root, explicit_outputs),
        f"material-code-review Codex plugin {VERSION}",
    )
    print(f"[OK] Full Codex plugin ZIP: {output}")
    print(f"SHA-256: {full_digest}")

    if standalone_output:
        standalone_digest = build_archive(
            standalone_output,
            iter_standalone_files(root),
            f"material-code-review standalone Codex skill {VERSION}",
        )
        print(f"[OK] Standalone Codex skill ZIP: {standalone_output}")
        print(f"SHA-256: {standalone_digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
