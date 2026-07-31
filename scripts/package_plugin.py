#!/usr/bin/env python3
"""Build reproducible full-plugin and standalone Codex-skill ZIP archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable

VERSION = "1.4.0"
FIXED_TIMESTAMP = (2026, 7, 30, 0, 0, 0)
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
MAINTAINER_ONLY_PREFIXES = (
    ".agents/skills/material-review-evaluation/",
    ".evaluation-runs/",
    ".superpowers/",
    "docs/superpowers/",
    "evaluations/",
)
LAYOUT_MANIFEST_SOURCE = Path("skills/material-code-review/package-layouts.json")
LAYOUT_NAMES = ("full-plugin", "standalone")


def is_maintainer_only_path(relative: Path) -> bool:
    archive_name = relative.as_posix()
    return archive_name.startswith(MAINTAINER_ONLY_PREFIXES)


def should_include(path: Path, root: Path, explicit_outputs: set[Path]) -> bool:
    resolved = path.resolve()
    if resolved in explicit_outputs:
        return False
    relative = path.relative_to(root)
    if is_maintainer_only_path(relative):
        return False
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
        (skill / "package-layouts.json", "package-layouts.json"),
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


def normalize_manifest_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"unsafe manifest {label}: {value!r}")
    if "\\" in value:
        raise ValueError(f"unsafe manifest {label}: {value}")
    path = PurePosixPath(value)
    normalized = path.as_posix()
    if (
        path.is_absolute()
        or ".." in path.parts
        or normalized in {"", "."}
        or normalized != value
    ):
        raise ValueError(f"unsafe manifest {label}: {value}")
    return normalized


def load_layout_manifest(root: Path) -> dict[str, dict[str, object]]:
    manifest_path = root / LAYOUT_MANIFEST_SOURCE
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"layout manifest is missing: {LAYOUT_MANIFEST_SOURCE.as_posix()}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"layout manifest is invalid: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("layout manifest schema_version must be 1")
    layouts = manifest.get("layouts")
    if not isinstance(layouts, dict) or set(layouts) != set(LAYOUT_NAMES):
        raise ValueError("layout manifest must define full-plugin and standalone")
    return layouts


def validate_layout_mappings(
    root: Path,
    layout_name: str,
    layout: object,
    generated_entries: list[tuple[Path, str]],
) -> None:
    if not isinstance(layout, dict):
        raise ValueError(f"layout {layout_name} must be an object")
    canonical_skill = normalize_manifest_path(
        layout.get("canonical_skill"),
        f"canonical skill for {layout_name}",
    )
    mappings = layout.get("required_mappings")
    if not isinstance(mappings, list) or not mappings:
        raise ValueError(f"layout {layout_name} required_mappings must be a non-empty array")

    seen_sources: set[str] = set()
    seen_destinations: set[str] = set()
    required_pairs: list[tuple[Path, str]] = []
    for index, mapping in enumerate(mappings):
        if not isinstance(mapping, dict) or set(mapping) != {"source", "destination"}:
            raise ValueError(f"layout {layout_name} mapping {index} must contain source and destination")
        source = normalize_manifest_path(mapping["source"], "source")
        destination = normalize_manifest_path(mapping["destination"], "destination")
        if source in seen_sources:
            raise ValueError(f"duplicate manifest source: {source}")
        if destination in seen_destinations:
            raise ValueError(f"duplicate manifest destination: {destination}")
        seen_sources.add(source)
        seen_destinations.add(destination)

        source_relative = Path(source)
        destination_relative = Path(destination)
        if is_maintainer_only_path(source_relative) or is_maintainer_only_path(
            destination_relative
        ):
            raise ValueError(
                f"maintainer-only manifest mapping: {source} -> {destination}"
            )
        if (
            any(part in EXCLUDED_PARTS for part in source_relative.parts)
            or any(part in EXCLUDED_PARTS for part in destination_relative.parts)
            or source_relative.suffix.lower() in EXCLUDED_SUFFIXES
            or destination_relative.suffix.lower() in EXCLUDED_SUFFIXES
            or source_relative.name in {".DS_Store", "Thumbs.db"}
            or destination_relative.name in {".DS_Store", "Thumbs.db"}
        ):
            raise ValueError(f"excluded manifest mapping: {source} -> {destination}")

        source_path = root.joinpath(*PurePosixPath(source).parts)
        if source_path.is_symlink():
            raise ValueError(f"required source must not be a symlink: {source}")
        if not source_path.is_file():
            raise ValueError(f"required source is missing: {source}")
        required_pairs.append((source_path.resolve(), destination))

    if canonical_skill not in seen_destinations:
        raise ValueError(
            f"layout {layout_name} canonical skill is not a required destination: "
            f"{canonical_skill}"
        )

    generated_pairs = {
        (source.resolve(), normalize_manifest_path(destination, "generated destination"))
        for source, destination in generated_entries
    }
    for source_path, destination in required_pairs:
        if (source_path, destination) not in generated_pairs:
            source = source_path.relative_to(root).as_posix()
            raise ValueError(
                f"manifest mapping is not generated: {source} -> {destination}"
            )


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

    try:
        layouts = load_layout_manifest(root)
        full_entries = list(iter_full_files(root, explicit_outputs))
        validate_layout_mappings(
            root,
            "full-plugin",
            layouts["full-plugin"],
            full_entries,
        )
        standalone_entries: list[tuple[Path, str]] | None = None
        if standalone_output:
            standalone_entries = list(iter_standalone_files(root))
            validate_layout_mappings(
                root,
                "standalone",
                layouts["standalone"],
                standalone_entries,
            )
    except (OSError, ValueError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    full_digest = build_archive(
        output,
        full_entries,
        f"material-code-review Codex plugin {VERSION}",
    )
    print(f"[OK] Full Codex plugin ZIP: {output}")
    print(f"SHA-256: {full_digest}")

    if standalone_output:
        assert standalone_entries is not None
        standalone_digest = build_archive(
            standalone_output,
            standalone_entries,
            f"material-code-review standalone Codex skill {VERSION}",
        )
        print(f"[OK] Standalone Codex skill ZIP: {standalone_output}")
        print(f"SHA-256: {standalone_digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
