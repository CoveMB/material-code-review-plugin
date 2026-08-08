#!/usr/bin/env python3
"""Build reproducible full-plugin and standalone Codex-skill ZIP archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))
SHARED_SCRIPT_DIRECTORY = (
    SCRIPT_DIRECTORY.parent / "skills/material-code-review/scripts"
)
if str(SHARED_SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPT_DIRECTORY))

from package_layout_contract import (  # noqa: E402
    normalize_package_path,
    portable_archive_member_key,
    regular_zip_external_attr,
    schema_version_is_supported,
)
from package_publication import (  # noqa: E402
    PublicationRecoveryError,
    allocate_owned_path as allocate_shared_owned_path,
    cleanup_owned_paths,
    publish_staged_outputs as publish_shared_staged_outputs,
)

VERSION = "1.7.0"
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
    return normalize_package_path(value, f"manifest {label}")


def load_layout_manifest(root: Path) -> dict[str, dict[str, object]]:
    manifest_path = root / LAYOUT_MANIFEST_SOURCE
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"layout manifest is missing: {LAYOUT_MANIFEST_SOURCE.as_posix()}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"layout manifest is invalid: {exc}") from exc
    if not isinstance(manifest, dict) or not schema_version_is_supported(
        manifest.get("schema_version")
    ):
        raise ValueError("layout manifest schema_version must be 1")
    layouts = manifest.get("layouts")
    if not isinstance(layouts, dict) or set(layouts) != set(LAYOUT_NAMES):
        raise ValueError("layout manifest must define full-plugin and standalone")
    normalized_layouts: dict[str, dict[str, object]] = {}
    for layout_name in LAYOUT_NAMES:
        layout = layouts[layout_name]
        if not isinstance(layout, dict):
            raise ValueError(f"layout {layout_name} must be an object")
        canonical_skill = normalize_manifest_path(
            layout.get("canonical_skill"),
            f"canonical skill for {layout_name}",
        )
        mappings = layout.get("required_mappings")
        if not isinstance(mappings, list) or not mappings:
            raise ValueError(
                f"layout {layout_name} required_mappings must be a non-empty array"
            )
        normalized_mappings: list[dict[str, str]] = []
        for index, mapping in enumerate(mappings):
            if not isinstance(mapping, dict) or set(mapping) != {
                "source",
                "destination",
            }:
                raise ValueError(
                    f"layout {layout_name} mapping {index} must contain source and destination"
                )
            normalized_mappings.append(
                {
                    "source": normalize_manifest_path(mapping["source"], "source"),
                    "destination": normalize_manifest_path(
                        mapping["destination"], "destination"
                    ),
                }
            )
        normalized_layouts[layout_name] = {
            "canonical_skill": canonical_skill,
            "required_mappings": normalized_mappings,
        }
    return normalized_layouts


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
    info.external_attr = regular_zip_external_attr(permissions)
    info.flag_bits |= 0x800  # UTF-8 names
    zf.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build_archive(output: Path, entries: Iterable[tuple[Path, str]], comment: str) -> str:
    seen: set[str] = set()
    portable_names: dict[str, str] = {}
    with zipfile.ZipFile(output, "w", allowZip64=True) as zf:
        zf.comment = comment.encode("utf-8")
        for source, archive_name in entries:
            try:
                normalized = normalize_package_path(archive_name, "archive entry")
            except ValueError as exc:
                raise ValueError(
                    f"Unsafe or duplicate archive entry: {archive_name}"
                ) from exc
            if normalized in seen:
                raise ValueError(f"Unsafe or duplicate archive entry: {archive_name}")
            seen.add(normalized)
            portable_key = portable_archive_member_key(normalized)
            prior_name = portable_names.get(portable_key)
            if prior_name is not None:
                raise ValueError(
                    "Portable archive member collision: "
                    f"{prior_name} and {normalized}"
                )
            portable_names[portable_key] = normalized
            write_entry(zf, source, normalized)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return digest


def destination_identity(path: Path) -> tuple[Path, str]:
    resolved = path.resolve(strict=False)
    portable_key = unicodedata.normalize("NFC", str(resolved)).casefold()
    return resolved, portable_key


def validate_publication_destinations(
    *, root: Path, destinations: list[Path], source_paths: set[Path]
) -> None:
    identities: list[tuple[Path, Path, str]] = []
    for destination in destinations:
        resolved, portable_key = destination_identity(destination)
        try:
            info = destination.lstat()
        except FileNotFoundError:
            info = None
        if destination.is_symlink():
            raise ValueError(f"output destination must not be a symlink: {destination}")
        if info is not None and not stat.S_ISREG(info.st_mode):
            raise ValueError(f"output destination must be absent or a regular file: {destination}")
        identities.append((destination, resolved, portable_key))

    for index, (destination, resolved, portable_key) in enumerate(identities):
        for other_destination, other_resolved, other_key in identities[index + 1 :]:
            if portable_key == other_key or resolved == other_resolved:
                raise ValueError(
                    f"output destinations alias each other: {destination} and {other_destination}"
                )
            if resolved in other_resolved.parents or other_resolved in resolved.parents:
                raise ValueError(
                    f"output destinations overlap as parent and child: {destination} and {other_destination}"
                )
        if resolved in source_paths:
            raise ValueError(f"output destination aliases a packaged source file: {destination}")
        if resolved == root:
            raise ValueError(f"output destination aliases the package root: {destination}")


def allocate_owned_path(destination: Path, purpose: str) -> Path:
    return allocate_shared_owned_path(destination, purpose, "material-review")


def publish_staged_outputs(staged_outputs: list[tuple[Path, Path]]) -> None:
    publish_shared_staged_outputs(staged_outputs, owner_label="material-review")


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

    output = Path(os.path.abspath(Path(args.output).expanduser()))
    standalone_output = (
        Path(os.path.abspath(Path(args.standalone_output).expanduser()))
        if args.standalone_output
        else None
    )
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

    destinations = [output, output.with_suffix(output.suffix + ".sha256")]
    if standalone_output:
        destinations.extend(
            [
                standalone_output,
                standalone_output.with_suffix(standalone_output.suffix + ".sha256"),
            ]
        )
    source_paths = {source.resolve() for source, _ in full_entries}
    if standalone_entries is not None:
        source_paths.update(source.resolve() for source, _ in standalone_entries)

    staged_outputs: list[tuple[Path, Path]] = []
    try:
        validate_publication_destinations(
            root=root, destinations=destinations, source_paths=source_paths
        )
        full_stage = allocate_owned_path(output, "archive")
        staged_outputs.append((output, full_stage))
        full_digest = build_archive(
            full_stage,
            full_entries,
            f"material-code-review Codex plugin {VERSION}",
        )
        full_checksum = output.with_suffix(output.suffix + ".sha256")
        full_checksum_stage = allocate_owned_path(full_checksum, "checksum")
        full_checksum_stage.write_text(
            f"{full_digest}  {output.name}\n", encoding="utf-8", newline="\n"
        )
        staged_outputs.append((full_checksum, full_checksum_stage))

        standalone_digest: str | None = None
        if standalone_output:
            assert standalone_entries is not None
            standalone_stage = allocate_owned_path(standalone_output, "archive")
            staged_outputs.append((standalone_output, standalone_stage))
            standalone_digest = build_archive(
                standalone_stage,
                standalone_entries,
                f"material-code-review standalone Codex skill {VERSION}",
            )
            standalone_checksum = standalone_output.with_suffix(
                standalone_output.suffix + ".sha256"
            )
            standalone_checksum_stage = allocate_owned_path(
                standalone_checksum, "checksum"
            )
            standalone_checksum_stage.write_text(
                f"{standalone_digest}  {standalone_output.name}\n",
                encoding="utf-8",
                newline="\n",
            )
            staged_outputs.append((standalone_checksum, standalone_checksum_stage))
        publish_staged_outputs(staged_outputs)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        cleanup_owned_paths([staged for _, staged in staged_outputs])
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    print(f"[OK] Full Codex plugin ZIP: {output}")
    print(f"SHA-256: {full_digest}")
    if standalone_output:
        assert standalone_digest is not None
        print(f"[OK] Standalone Codex skill ZIP: {standalone_output}")
        print(f"SHA-256: {standalone_digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
