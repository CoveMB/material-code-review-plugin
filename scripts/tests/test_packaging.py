from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import importlib.util
import multiprocessing
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGER = REPOSITORY_ROOT / "scripts" / "package_simplification_skill.py"
FULL_PACKAGER = REPOSITORY_ROOT / "scripts" / "package_plugin.py"
PACKAGE_VALIDATOR = REPOSITORY_ROOT / "scripts" / "validate_package.py"
REVIEW_VALIDATOR = REPOSITORY_ROOT / "skills" / "material-code-review" / "scripts" / "validate_package.py"
REVIEW_LAYOUT_MANIFEST = (
    REPOSITORY_ROOT / "skills" / "material-code-review" / "package-layouts.json"
)
SIMPLIFICATION_VALIDATOR = (
    REPOSITORY_ROOT / "skills" / "material-code-simplification" / "scripts" / "validate_package.py"
)
DISTRIBUTION_LAYOUT = not (REPOSITORY_ROOT / ".git").exists()
PROMPT_DRIVEN_EVALUATOR_PATHS = (
    ".agents/skills/material-review-evaluation/SKILL.md",
    "evaluations/material-code-review/README.md",
    "evaluations/material-code-review/cases/discogs-custom-playlists.json",
    "evaluations/material-code-review/cases/missed-contracts.json",
    "evaluations/material-code-review/prompts/reviewer.md",
    "evaluations/material-code-review/prompts/challenger.md",
    "evaluations/material-code-review/prompts/judge.md",
    "evaluations/material-code-review/rubric.md",
    "evaluations/material-code-review/fixtures/missed-contracts/base/AGENTS.md",
    "evaluations/material-code-review/fixtures/missed-contracts/base/scripts/validate_package.py",
    "evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/scripts/validate_package.py",
    "evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/references/workflow.md",
    "evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/schemas/candidate-set.json",
    "evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/schemas/coverage-plan.json",
    "evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/package-layouts.json",
    "evaluations/material-code-review/fixtures/missed-contracts/review/scripts/validate_package.py",
    "evaluations/material-code-review/fixtures/missed-contracts/review/skills/demo/scripts/validate_package.py",
    "evaluations/material-code-review/fixtures/missed-contracts/review/skills/demo/references/workflow.md",
    "evaluations/material-code-review/fixtures/missed-contracts/review/skills/demo/schemas/candidate-set.json",
    "evaluations/material-code-review/fixtures/missed-contracts/review/skills/demo/schemas/coverage-plan.json",
)
MAINTAINER_EVALUATOR_PATHS = PROMPT_DRIVEN_EVALUATOR_PATHS + (
    "EVALUATION.md",
)
RETIRED_EVALUATOR_DOCUMENTS = (
    "docs/superpowers/plans/2026-07-27-material-review-version-evaluator.md",
    "docs/superpowers/specs/2026-07-27-material-review-version-evaluation-design.md",
)
# Split literals intentionally keep repo-wide legacy-token scans from matching this test file.
LEGACY_EVALUATOR_PATHS = (
    "bin/material-review-" "evaluate",
    "scripts/evaluate_material_review.py",
    "scripts/tests/test_evaluate_material_review.py",
    "scripts/material_review_" "evaluation",
    "evaluations/material-code-review/benchmarks",
    "evaluations/material-code-review/schemas",
    "evaluations/material-code-review/prompts/trial-" "agreement.md",
    "evaluations/material-code-review/prompts/comparison-" "judge.md",
    "evaluations/material-code-review/judge-rubric.md",
)
WORKFLOW_BLOCK_START = "Discovery order is fixed:\n\n```text\n"
WORKFLOW_BLOCK_END = "\n```"
WORKFLOW_SCOPE_CHECK = (
    'python3 "$SKILL_DIR/scripts/reviewctl.py" check-scope --repo-root .'
)
VALID_WORKFLOW_DISCOVERY_BLOCK = "\n".join(
    (
        "init",
        "context record and change-unit inventory (manual; see references/context-checklist.md)",
        WORKFLOW_SCOPE_CHECK,
        "record-coverage",
        "dispatch assignments",
        "ingest one complete assignment-matched wave",
        "validate",
        "repair-direction audit",
        "compile-ledger",
        "Gate A",
        "validate plan",
        "Gate B",
    )
)
OBLIGATION_WORKFLOW_BLOCK_START = (
    "<!-- material-review-obligation-workflow-contract:start -->"
)
OBLIGATION_WORKFLOW_BLOCK_END = (
    "<!-- material-review-obligation-workflow-contract:end -->"
)
VALID_OBLIGATION_WORKFLOW_BLOCK = "\n".join(
    (
        OBLIGATION_WORKFLOW_BLOCK_START,
        "check_contracts=controller-derived",
        "obligation_check_results=evidence_items",
        "obligation_evidence_paths=all_required_review_paths",
        OBLIGATION_WORKFLOW_BLOCK_END,
    )
)


def _load_publication_module(module_path: str, label: str):
    spec = importlib.util.spec_from_file_location(label, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load publication module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hold_publication_locks(
    module_path: str,
    destinations: list[str],
    entered,
    release,
    results,
) -> None:
    try:
        module = _load_publication_module(module_path, "publication_lock_holder")
        with module._publication_locks(
            [Path(path) for path in destinations], timeout_seconds=5.0
        ):
            entered.set()
            if not release.wait(10.0):
                raise TimeoutError("test did not release held publication locks")
    except BaseException as error:
        results.put((type(error).__name__, str(error)))
    else:
        results.put(("ok", ""))


def _run_controlled_publication(
    module_path: str,
    staged_outputs: list[tuple[str, str]],
    owner_label: str,
    started,
    first_replacement,
    release_first,
    results,
) -> None:
    try:
        module = _load_publication_module(
            module_path, f"controlled_publication_{owner_label}"
        )
        paths = [(Path(destination), Path(staged)) for destination, staged in staged_outputs]
        original_replace = module.os.replace
        paused = False

        def controlled_replace(source, destination):
            nonlocal paused
            result = original_replace(source, destination)
            if (
                first_replacement is not None
                and not paused
                and Path(source) == paths[0][1]
                and Path(destination) == paths[0][0]
            ):
                paused = True
                first_replacement.set()
                if not release_first.wait(10.0):
                    raise TimeoutError("test did not release the first publication")
            return result

        module.os.replace = controlled_replace
        started.set()
        module.publish_staged_outputs(paths, owner_label=owner_label)
    except BaseException as error:
        results.put((type(error).__name__, str(error)))
    else:
        results.put(("ok", ""))

FULL_REVIEW_FIXED_CONTRACTS = {
    ".agents/plugins/marketplace.json",
    ".claude-plugin/marketplace.json",
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    "AGENTS.md",
    "CHANGELOG.md",
    "CODEX.md",
    "LICENSE",
    "Makefile",
    "README.md",
    "SECURITY.md",
    "SKILL.md",
    "THIRD_PARTY.md",
    "bin/material-reviewctl",
    "bin/material-reviewctl.cmd",
    "bin/material-reviewctl.ps1",
    "examples/codex-project-config/.codex/agents/material_adjudicator.toml",
    "examples/codex-project-config/.codex/agents/material_candidate.toml",
    "examples/codex-project-config/.codex/agents/material_postfix.toml",
    "examples/codex-project-config/.codex/agents/material_validator.toml",
    "examples/codex-project-config/.codex/config.toml",
    "scripts/package_plugin.py",
    "scripts/package_publication.py",
    "scripts/package_simplification_skill.py",
    "scripts/tests/test_packaging.py",
    "scripts/validate_package.py",
}
STANDALONE_REVIEW_FIXED_CONTRACTS = {"CODEX.md", "LICENSE", "SECURITY.md"}
REVIEW_CONTRACT_SUBDIRECTORIES = ("agents", "references", "schemas", "scripts", "tests")


class StandalonePackagingTests(unittest.TestCase):
    def expected_review_layout_manifest(self, root: Path) -> dict[str, object]:
        skill_prefix = Path("skills/material-code-review")
        skill_root = root / skill_prefix
        skill_sources = {
            (skill_prefix / "SKILL.md").as_posix(),
            (skill_prefix / "package-layouts.json").as_posix(),
        }
        for subdirectory in REVIEW_CONTRACT_SUBDIRECTORIES:
            directory = skill_root / subdirectory
            if not directory.is_dir():
                continue
            skill_sources.update(
                path.relative_to(root).as_posix()
                for path in directory.rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and "__pycache__" not in path.parts
                and path.suffix not in {".pyc", ".pyo"}
            )

        full_sources = set(FULL_REVIEW_FIXED_CONTRACTS) | skill_sources
        simplification_root = root / "skills/material-code-simplification"
        full_sources.update(
            path.relative_to(root).as_posix()
            for path in simplification_root.rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        )
        for subdirectory in ("agents", "commands"):
            full_sources.update(
                path.relative_to(root).as_posix()
                for path in (root / subdirectory).rglob("*")
                if path.is_file() and not path.is_symlink()
            )

        standalone_sources = set(STANDALONE_REVIEW_FIXED_CONTRACTS) | skill_sources
        return {
            "schema_version": 1,
            "layouts": {
                "full-plugin": {
                    "canonical_skill": "skills/material-code-review/SKILL.md",
                    "required_mappings": [
                        {"source": source, "destination": source}
                        for source in sorted(full_sources)
                    ],
                },
                "standalone": {
                    "canonical_skill": "SKILL.md",
                    "required_mappings": [
                        {
                            "source": source,
                            "destination": (
                                Path(source).relative_to(skill_prefix).as_posix()
                                if Path(source).is_relative_to(skill_prefix)
                                else source
                            ),
                        }
                        for source in sorted(standalone_sources)
                    ],
                },
            },
        }

    def write_review_layout_manifest(
        self,
        fixture_root: Path,
        manifest: dict[str, object] | None = None,
    ) -> dict[str, object]:
        manifest = manifest or self.expected_review_layout_manifest(fixture_root)
        manifest_path = (
            fixture_root / REVIEW_LAYOUT_MANIFEST.relative_to(REPOSITORY_ROOT)
        )
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest

    def load_static_version_helper(self, validator: Path):
        spec = importlib.util.spec_from_file_location(
            f"version_validator_{validator.parent.parent.name}_{validator.stat().st_mtime_ns}",
            validator,
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.validate_static_version_declaration

    def create_repository_fixture(self, destination: Path) -> Path:
        fixture_root = destination / "repository"
        (fixture_root / "skills").mkdir(parents=True)
        shutil.copytree(
            REPOSITORY_ROOT / "skills" / "material-code-simplification",
            fixture_root / "skills" / "material-code-simplification",
            symlinks=True,
        )
        shutil.copytree(
            REPOSITORY_ROOT / "skills" / "material-code-review",
            fixture_root / "skills" / "material-code-review",
            symlinks=True,
        )
        for name in ("LICENSE", "SECURITY.md", "CODEX.md"):
            source = REPOSITORY_ROOT / name
            if source.is_file():
                shutil.copy2(source, fixture_root / name)
        return fixture_root

    def create_full_plugin_fixture(self, destination: Path) -> Path:
        fixture_root = destination / "full-plugin"
        shutil.copytree(
            REPOSITORY_ROOT,
            fixture_root,
            ignore=shutil.ignore_patterns(
                ".git",
                "__pycache__",
                ".pytest_cache",
                ".mypy_cache",
                ".ruff_cache",
                "*.pyc",
                "*.pyo",
                "dist",
                "*.zip",
                "*.sha256",
            ),
        )
        return fixture_root

    def run_packager(self, fixture_root: Path, output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(PACKAGER), "--root", str(fixture_root), "--output", str(output)],
            capture_output=True,
            text=True,
            check=False,
        )

    def run_full_packager(
        self,
        fixture_root: Path,
        output: Path,
        *,
        standalone_output: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        packager = fixture_root / FULL_PACKAGER.relative_to(REPOSITORY_ROOT)
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(packager),
                "--package-root",
                str(fixture_root),
                "--output",
                str(output),
                "--standalone-output",
                "" if standalone_output is None else str(standalone_output),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def load_fixture_module(self, path: Path, label: str):
        spec = importlib.util.spec_from_file_location(label, path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def publication_packagers(self, fixture_root: Path, label: str):
        return (
            self.load_fixture_module(
                fixture_root / "scripts/package_plugin.py",
                f"full_publication_{label}",
            ),
            self.load_fixture_module(
                fixture_root / "scripts/package_simplification_skill.py",
                f"simplification_publication_{label}",
            ),
        )

    def run_package_validator(
        self,
        fixture_root: Path,
        *,
        distribution_layout: bool | None = None,
    ) -> subprocess.CompletedProcess[str]:
        use_distribution_layout = (
            DISTRIBUTION_LAYOUT
            if distribution_layout is None
            else distribution_layout
        )
        arguments = [
            sys.executable,
            "-B",
            str(PACKAGE_VALIDATOR),
            "--package-root",
            str(fixture_root),
        ]
        if use_distribution_layout:
            arguments.append("--distribution-layout")
        return subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            check=False,
        )

    def extract_archive_with_modes(self, archive_path: Path, destination: Path) -> None:
        destination.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                extracted = Path(archive.extract(member, destination))
                mode = (member.external_attr >> 16) & 0o777
                if mode and extracted.is_file():
                    extracted.chmod(mode)

    def run_review_validator(self, fixture_root: Path) -> subprocess.CompletedProcess[str]:
        validator = fixture_root / REVIEW_VALIDATOR.relative_to(REPOSITORY_ROOT)
        return subprocess.run(
            [sys.executable, "-B", str(validator)],
            capture_output=True,
            text=True,
            check=False,
        )

    def run_simplification_validator(self, fixture_root: Path) -> subprocess.CompletedProcess[str]:
        validator = fixture_root / SIMPLIFICATION_VALIDATOR.relative_to(REPOSITORY_ROOT)
        return subprocess.run(
            [sys.executable, "-B", str(validator)],
            capture_output=True,
            text=True,
            check=False,
        )

    def replace_once(self, path: Path, original: str, replacement: str) -> None:
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count(original), 1, f"expected one occurrence in {path}")
        path.write_text(text.replace(original, replacement, 1), encoding="utf-8")

    def replace_workflow_discovery_block(self, path: Path, block: str) -> None:
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count(WORKFLOW_BLOCK_START), 1)
        prefix, remainder = text.split(WORKFLOW_BLOCK_START, 1)
        _, separator, suffix = remainder.partition(WORKFLOW_BLOCK_END)
        self.assertEqual(separator, WORKFLOW_BLOCK_END)
        path.write_text(
            f"{prefix}{WORKFLOW_BLOCK_START}{block}{WORKFLOW_BLOCK_END}{suffix}",
            encoding="utf-8",
        )

    def rewrite_archive_entry(
        self,
        source: Path,
        destination: Path,
        entry: str,
        contents: bytes,
    ) -> None:
        with zipfile.ZipFile(source) as source_archive:
            members = source_archive.infolist()
            self.assertEqual([member.filename for member in members].count(entry), 1)
            comment = source_archive.comment
            payloads = {
                member.filename: source_archive.read(member)
                for member in members
            }
        with zipfile.ZipFile(destination, "w") as destination_archive:
            destination_archive.comment = comment
            for member in members:
                payload = contents if member.filename == entry else payloads[member.filename]
                destination_archive.writestr(member, payload)

    def remove_archive_entry(
        self,
        source: Path,
        destination: Path,
        entry: str,
    ) -> None:
        with zipfile.ZipFile(source) as source_archive:
            members = source_archive.infolist()
            self.assertEqual([member.filename for member in members].count(entry), 1)
            comment = source_archive.comment
            payloads = {
                member.filename: source_archive.read(member)
                for member in members
            }
        with zipfile.ZipFile(destination, "w") as destination_archive:
            destination_archive.comment = comment
            for member in members:
                if member.filename != entry:
                    destination_archive.writestr(member, payloads[member.filename])

    def ensure_archive_entry(
        self,
        archive_path: Path,
        entry: str,
        contents: bytes,
    ) -> None:
        with zipfile.ZipFile(archive_path) as archive:
            if entry in archive.namelist():
                return
        with zipfile.ZipFile(archive_path, "a") as archive:
            member = zipfile.ZipInfo(entry)
            member.create_system = 3
            member.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(member, contents)

    def run_review_archive_validator(
        self,
        fixture_root: Path,
        archive: Path,
        *,
        standalone: bool,
    ) -> subprocess.CompletedProcess[str]:
        arguments = [
            sys.executable,
            "-B",
            str(PACKAGE_VALIDATOR),
            "--package-root",
            str(fixture_root),
        ]
        if DISTRIBUTION_LAYOUT:
            arguments.append("--distribution-layout")
        arguments.extend(
            ["--standalone-archive" if standalone else "--full-archive", str(archive)]
        )
        return subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def build_review_archives(
        self,
        temp_root: Path,
        fixture_root: Path,
        manifest: dict[str, object] | None = None,
    ) -> tuple[dict[str, object], Path, Path]:
        manifest = self.write_review_layout_manifest(fixture_root, manifest)
        full_archive = temp_root / "full-plugin.zip"
        standalone_archive = temp_root / "material-review.zip"
        package_result = self.run_full_packager(
            fixture_root,
            full_archive,
            standalone_output=standalone_archive,
        )
        self.assertEqual(package_result.returncode, 0, package_result.stderr)
        manifest_bytes = (
            fixture_root / REVIEW_LAYOUT_MANIFEST.relative_to(REPOSITORY_ROOT)
        ).read_bytes()
        self.ensure_archive_entry(
            standalone_archive,
            "package-layouts.json",
            manifest_bytes,
        )
        return manifest, full_archive, standalone_archive

    def copy_archive_with_member_metadata(
        self,
        source: Path,
        destination: Path,
        entry: str,
        *,
        create_system: int,
        mode: int,
    ) -> None:
        with zipfile.ZipFile(source) as source_archive:
            members = source_archive.infolist()
            self.assertEqual([member.filename for member in members].count(entry), 1)
            comment = source_archive.comment
            payloads = {
                member.filename: source_archive.read(member)
                for member in members
            }
        with zipfile.ZipFile(destination, "w") as destination_archive:
            destination_archive.comment = comment
            for member in members:
                copied_member = copy.copy(member)
                if copied_member.filename == entry:
                    copied_member.create_system = create_system
                    copied_member.external_attr = mode << 16
                destination_archive.writestr(
                    copied_member,
                    payloads[member.filename],
                )

    def test_review_archives_require_regular_unix_member_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            _, full_archive, standalone_archive = self.build_review_archives(
                temp_root,
                fixture_root,
            )

            second_full = temp_root / "second-full-plugin.zip"
            second_standalone = temp_root / "second-material-review.zip"
            second_result = self.run_full_packager(
                fixture_root,
                second_full,
                standalone_output=second_standalone,
            )
            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            self.assertEqual(full_archive.read_bytes(), second_full.read_bytes())
            self.assertEqual(standalone_archive.read_bytes(), second_standalone.read_bytes())

            for archive_path, standalone in (
                (full_archive, False),
                (standalone_archive, True),
            ):
                with zipfile.ZipFile(archive_path) as archive:
                    members = archive.infolist()
                    self.assertTrue(members)
                    permissions = set()
                    for member in members:
                        mode = (member.external_attr >> 16) & 0xFFFF
                        self.assertEqual(member.create_system, 3, member.filename)
                        self.assertTrue(stat.S_ISREG(mode), member.filename)
                        permissions.add(stat.S_IMODE(mode))
                    self.assertIn(0o644, permissions)
                    self.assertIn(0o755, permissions)
                    target = members[0].filename

                valid_result = self.run_review_archive_validator(
                    fixture_root,
                    archive_path,
                    standalone=standalone,
                )
                self.assertEqual(valid_result.returncode, 0, valid_result.stderr)

                rejected_modes = (
                    stat.S_IFLNK | 0o777,
                    stat.S_IFDIR | 0o755,
                    stat.S_IFCHR | 0o600,
                    stat.S_IFBLK | 0o600,
                    stat.S_IFIFO | 0o600,
                    stat.S_IFSOCK | 0o600,
                )
                for index, mode in enumerate(rejected_modes):
                    mutated = temp_root / f"{archive_path.stem}-nonregular-{index}.zip"
                    self.copy_archive_with_member_metadata(
                        archive_path,
                        mutated,
                        target,
                        create_system=3,
                        mode=mode,
                    )
                    result = self.run_review_archive_validator(
                        fixture_root,
                        mutated,
                        standalone=standalone,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f"archive member {target}", result.stderr)
                    self.assertIn("non-regular Unix member type", result.stderr)

                legacy = temp_root / f"{archive_path.stem}-legacy-zero-type.zip"
                self.copy_archive_with_member_metadata(
                    archive_path,
                    legacy,
                    target,
                    create_system=3,
                    mode=0o644,
                )
                legacy_result = self.run_review_archive_validator(
                    fixture_root,
                    legacy,
                    standalone=standalone,
                )
                self.assertNotEqual(legacy_result.returncode, 0)
                self.assertIn("unsupported legacy Unix zero-type metadata", legacy_result.stderr)

                non_unix = temp_root / f"{archive_path.stem}-non-unix.zip"
                self.copy_archive_with_member_metadata(
                    archive_path,
                    non_unix,
                    target,
                    create_system=0,
                    mode=stat.S_IFREG | 0o644,
                )
                non_unix_result = self.run_review_archive_validator(
                    fixture_root,
                    non_unix,
                    standalone=standalone,
                )
                self.assertNotEqual(non_unix_result.returncode, 0)
                self.assertIn("unsupported non-Unix creator system 0", non_unix_result.stderr)

    def run_simplification_archive_validator(self, archive: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(SIMPLIFICATION_VALIDATOR), "--archive", str(archive)],
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )

    @unittest.skipIf(sys.platform.startswith("win"), "fixture requires POSIX symlinks")
    def test_packager_and_source_validator_reject_symlinked_skill_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_repository_fixture(temp_root)
            external = temp_root / "external-secret.txt"
            external.write_text("must not be packaged\n", encoding="utf-8")
            target = fixture_root / "skills" / "material-code-simplification" / "examples" / "field-mapping.md"
            target.unlink()
            target.symlink_to(external)

            output = temp_root / "standalone.zip"
            package_result = self.run_packager(fixture_root, output)
            self.assertNotEqual(package_result.returncode, 0)
            self.assertIn("must not be a symlink", package_result.stderr)
            self.assertFalse(output.exists())

            validator = (
                fixture_root
                / "skills"
                / "material-code-simplification"
                / "scripts"
                / "validate_package.py"
            )
            validation_result = subprocess.run(
                [sys.executable, "-B", str(validator)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(validation_result.returncode, 0)
            self.assertIn("symlinked source path present: examples/field-mapping.md", validation_result.stderr)

    @unittest.skipIf(sys.platform.startswith("win"), "fixture requires POSIX filename semantics")
    def test_packager_rejects_windows_normalized_name_collision_before_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_repository_fixture(temp_root)
            skill_root = fixture_root / "skills" / "material-code-simplification"
            (skill_root / "examples\\field-mapping.md").write_text("collision\n", encoding="utf-8")
            output = temp_root / "standalone.zip"
            output.write_bytes(b"existing archive")

            package_result = self.run_packager(fixture_root, output)

            self.assertNotEqual(package_result.returncode, 0)
            self.assertIn("duplicate normalized archive entry: examples/field-mapping.md", package_result.stderr)
            self.assertEqual(output.read_bytes(), b"existing archive")

    def test_publication_locks_serialize_partially_overlapping_sets(self) -> None:
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            module_path = str(REPOSITORY_ROOT / "scripts/package_publication.py")
            shared = temp_root / "shared.zip"
            independent = temp_root / "independent.zip"
            entered = context.Event()
            release = context.Event()
            results = context.Queue()
            holder = context.Process(
                target=_hold_publication_locks,
                args=(module_path, [str(shared)], entered, release, results),
            )
            holder.start()
            try:
                self.assertTrue(entered.wait(10.0), "lock holder did not start")
                module = _load_publication_module(
                    module_path, "publication_overlap_parent"
                )

                with module._publication_locks(
                    [independent], timeout_seconds=0.1
                ):
                    pass

                with self.assertRaises(module.PublicationLockTimeoutError):
                    with module._publication_locks(
                        [independent, shared], timeout_seconds=0.1
                    ):
                        self.fail("overlapping lock set entered unexpectedly")

                with module._publication_locks(
                    [independent], timeout_seconds=0.1
                ):
                    pass
            finally:
                release.set()
                holder.join(10.0)
                if holder.is_alive():
                    holder.terminate()
                    holder.join(5.0)

            self.assertEqual(holder.exitcode, 0)
            self.assertEqual(results.get(timeout=2.0), ("ok", ""))

    def test_publication_concurrent_generations_remain_coherent(self) -> None:
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            module_path = str(REPOSITORY_ROOT / "scripts/package_publication.py")
            archive = temp_root / "release.zip"
            checksum = temp_root / "release.zip.sha256"
            staged_a = [temp_root / "a.zip.stage", temp_root / "a.sha.stage"]
            staged_b = [temp_root / "b.zip.stage", temp_root / "b.sha.stage"]
            staged_a[0].write_bytes(b"archive-a")
            staged_a[1].write_bytes(b"checksum-a")
            staged_b[0].write_bytes(b"archive-b")
            staged_b[1].write_bytes(b"checksum-b")
            destinations_a = [
                (str(archive), str(staged_a[0])),
                (str(checksum), str(staged_a[1])),
            ]
            destinations_b = [
                (str(archive), str(staged_b[0])),
                (str(checksum), str(staged_b[1])),
            ]
            a_started = context.Event()
            b_started = context.Event()
            a_first_replacement = context.Event()
            release_a = context.Event()
            results = context.Queue()
            writer_a = context.Process(
                target=_run_controlled_publication,
                args=(
                    module_path,
                    destinations_a,
                    "writer-a",
                    a_started,
                    a_first_replacement,
                    release_a,
                    results,
                ),
            )
            writer_b = context.Process(
                target=_run_controlled_publication,
                args=(
                    module_path,
                    destinations_b,
                    "writer-b",
                    b_started,
                    None,
                    release_a,
                    results,
                ),
            )
            writer_a.start()
            try:
                self.assertTrue(a_started.wait(10.0), "writer A did not start")
                self.assertTrue(
                    a_first_replacement.wait(10.0),
                    "writer A did not reach the controlled replacement",
                )
                writer_b.start()
                self.assertTrue(b_started.wait(10.0), "writer B did not start")
                writer_b.join(0.25)
                self.assertTrue(
                    writer_b.is_alive(),
                    "overlapping writer completed while the first lock was held",
                )
            finally:
                release_a.set()
                writer_a.join(10.0)
                if writer_b.pid is not None:
                    writer_b.join(10.0)
                for process in (writer_a, writer_b):
                    if process.is_alive():
                        process.terminate()
                        process.join(5.0)

            self.assertEqual(writer_a.exitcode, 0)
            self.assertEqual(writer_b.exitcode, 0)
            self.assertEqual(
                sorted([results.get(timeout=2.0), results.get(timeout=2.0)]),
                [("ok", ""), ("ok", "")],
            )
            self.assertIn(
                (archive.read_bytes(), checksum.read_bytes()),
                {
                    (b"archive-a", b"checksum-a"),
                    (b"archive-b", b"checksum-b"),
                },
            )

    def test_publication_windows_lock_adapter_uses_one_locked_byte(self) -> None:
        module = _load_publication_module(
            str(REPOSITORY_ROOT / "scripts/package_publication.py"),
            "publication_windows_adapter",
        )
        fake_msvcrt = mock.Mock()
        fake_msvcrt.LK_NBLCK = 2
        fake_msvcrt.LK_UNLCK = 0
        with tempfile.TemporaryFile() as lock_file, mock.patch.object(
            module.os, "name", "nt"
        ), mock.patch.dict(sys.modules, {"msvcrt": fake_msvcrt}):
            descriptor = lock_file.fileno()
            module._acquire_descriptor_lock(descriptor)
            module._release_descriptor_lock(descriptor)

        self.assertEqual(
            fake_msvcrt.locking.call_args_list,
            [
                mock.call(descriptor, fake_msvcrt.LK_NBLCK, 1),
                mock.call(descriptor, fake_msvcrt.LK_UNLCK, 1),
            ],
        )

    def test_packager_publication_is_collision_safe_and_recoverable(self) -> None:
        def load_packager(fixture_root: Path, label: str):
            path = fixture_root / "scripts/package_plugin.py"
            spec = importlib.util.spec_from_file_location(
                f"full_packager_{label}", path
            )
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

        def invoke(module, fixture_root: Path, full_output: Path, standalone_output: Path) -> int:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                return module.main(
                    [
                        "--package-root",
                        str(fixture_root),
                        "--output",
                        str(full_output),
                        "--standalone-output",
                        str(standalone_output),
                    ]
                )

        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            full_output = temp_root / "full.zip"
            standalone_output = temp_root / "standalone.zip"
            result = self.run_full_packager(
                fixture_root, full_output, standalone_output=standalone_output
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(full_output) as archive:
                self.assertEqual(
                    archive.comment,
                    b"material-code-review Codex plugin 1.7.0",
                )
            with zipfile.ZipFile(standalone_output) as archive:
                self.assertEqual(
                    archive.comment,
                    b"material-code-review standalone Codex skill 1.7.0",
                )
            for output in (full_output, standalone_output):
                checksum = output.with_suffix(output.suffix + ".sha256")
                digest, filename = checksum.read_text(encoding="utf-8").split()
                self.assertEqual(filename, output.name)
                self.assertEqual(digest, hashlib.sha256(output.read_bytes()).hexdigest())

        collision_cases = (
            ("same-archive", lambda root: (root / "same.zip", root / "same.zip")),
            (
                "archive-sidecar",
                lambda root: (root / "full.zip", root / "full.zip.sha256"),
            ),
        )
        for label, outputs in collision_cases:
            with self.subTest(collision=label), tempfile.TemporaryDirectory() as temp_directory:
                temp_root = Path(temp_directory)
                fixture_root = self.create_full_plugin_fixture(temp_root)
                full_output, standalone_output = outputs(temp_root)
                full_output.write_bytes(b"full sentinel")
                if standalone_output != full_output:
                    standalone_output.write_bytes(b"standalone sentinel")
                result = self.run_full_packager(
                    fixture_root,
                    full_output,
                    standalone_output=standalone_output,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("output destinations alias each other", result.stderr)
                self.assertEqual(full_output.read_bytes(), b"full sentinel")
                if standalone_output != full_output:
                    self.assertEqual(
                        standalone_output.read_bytes(), b"standalone sentinel"
                    )

        if not sys.platform.startswith("win"):
            with tempfile.TemporaryDirectory() as temp_directory:
                temp_root = Path(temp_directory)
                fixture_root = self.create_full_plugin_fixture(temp_root)
                target = temp_root / "target.zip"
                target.write_bytes(b"target sentinel")
                symlink_output = temp_root / "full.zip"
                symlink_output.symlink_to(target)
                result = self.run_full_packager(
                    fixture_root,
                    symlink_output,
                    standalone_output=temp_root / "standalone.zip",
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("must not be a symlink", result.stderr)
                self.assertEqual(target.read_bytes(), b"target sentinel")
                self.assertTrue(symlink_output.is_symlink())

        for failure_step in range(1, 9):
            with self.subTest(publication_failure=failure_step), tempfile.TemporaryDirectory() as temp_directory:
                temp_root = Path(temp_directory)
                fixture_root = self.create_full_plugin_fixture(temp_root)
                module = load_packager(fixture_root, f"publish_{failure_step}")
                full_output = temp_root / "full.zip"
                standalone_output = temp_root / "standalone.zip"
                destinations = (
                    full_output,
                    full_output.with_suffix(".zip.sha256"),
                    standalone_output,
                    standalone_output.with_suffix(".zip.sha256"),
                )
                sentinels = {}
                for index, destination in enumerate(destinations):
                    data = f"sentinel-{index}".encode("utf-8")
                    destination.write_bytes(data)
                    sentinels[destination] = data
                unrelated_temp = temp_root / ".full.zip.tmp"
                unrelated_temp.write_bytes(b"unrelated")
                original_replace = module.os.replace
                calls = 0

                def fail_once(source, destination):
                    nonlocal calls
                    calls += 1
                    if calls == failure_step:
                        raise OSError(f"injected publication failure {failure_step}")
                    return original_replace(source, destination)

                with mock.patch.object(module.os, "replace", side_effect=fail_once):
                    self.assertEqual(
                        invoke(module, fixture_root, full_output, standalone_output),
                        1,
                    )
                for destination, data in sentinels.items():
                    self.assertEqual(destination.read_bytes(), data)
                self.assertEqual(unrelated_temp.read_bytes(), b"unrelated")
                self.assertEqual(
                    list(temp_root.glob(".*.material-review-*-*")), []
                )

        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            module = load_packager(fixture_root, "build_failure")
            full_output = temp_root / "full.zip"
            standalone_output = temp_root / "standalone.zip"
            full_output.write_bytes(b"full sentinel")
            standalone_output.write_bytes(b"standalone sentinel")
            original_build = module.build_archive
            builds = 0

            def fail_second_build(*arguments, **keywords):
                nonlocal builds
                builds += 1
                if builds == 2:
                    raise OSError("injected standalone build failure")
                return original_build(*arguments, **keywords)

            with mock.patch.object(module, "build_archive", side_effect=fail_second_build):
                self.assertEqual(
                    invoke(module, fixture_root, full_output, standalone_output), 1
                )
            self.assertEqual(full_output.read_bytes(), b"full sentinel")
            self.assertEqual(standalone_output.read_bytes(), b"standalone sentinel")

    def test_simplification_packager_publication_is_recoverable(self) -> None:
        def load_simplification_packager(fixture_root: Path, label: str):
            path = fixture_root / "scripts/package_simplification_skill.py"
            spec = importlib.util.spec_from_file_location(
                f"simplification_packager_{label}", path
            )
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

        def invoke(module, fixture_root: Path, output: Path) -> int:
            arguments = [
                str(fixture_root / "scripts/package_simplification_skill.py"),
                "--root",
                str(fixture_root),
                "--output",
                str(output),
            ]
            with mock.patch.object(sys, "argv", arguments), contextlib.redirect_stdout(
                io.StringIO()
            ), contextlib.redirect_stderr(io.StringIO()):
                return module.main()

        def owned_paths(directory: Path, output: Path) -> list[Path]:
            checksum = output.with_suffix(output.suffix + ".sha256")
            prefixes = (f".{output.name}.", f".{checksum.name}.")
            return sorted(
                path for path in directory.iterdir() if path.name.startswith(prefixes)
            )

        def assert_publication_failure(
            failure_step: int, *, existing_destinations: bool
        ) -> None:
            with tempfile.TemporaryDirectory() as temp_directory:
                temp_root = Path(temp_directory)
                fixture_root = self.create_full_plugin_fixture(temp_root)
                destination_state = "existing" if existing_destinations else "absent"
                module = load_simplification_packager(
                    fixture_root, f"{destination_state}_{failure_step}"
                )
                output = temp_root / "simplification.zip"
                checksum = output.with_suffix(output.suffix + ".sha256")
                if existing_destinations:
                    output.write_bytes(b"archive sentinel")
                    checksum.write_bytes(b"checksum sentinel")
                unrelated = temp_root / "unrelated.tmp"
                unrelated.write_bytes(b"unrelated")
                original_replace = module.os.replace
                calls = 0

                def fail_once(source, destination):
                    nonlocal calls
                    calls += 1
                    if calls == failure_step:
                        raise OSError(f"injected publication failure {failure_step}")
                    return original_replace(source, destination)

                with mock.patch.object(module.os, "replace", side_effect=fail_once):
                    with self.assertRaisesRegex(
                        OSError, f"injected publication failure {failure_step}"
                    ):
                        invoke(module, fixture_root, output)

                if existing_destinations:
                    self.assertEqual(output.read_bytes(), b"archive sentinel")
                    self.assertEqual(checksum.read_bytes(), b"checksum sentinel")
                else:
                    self.assertFalse(output.exists())
                    self.assertFalse(checksum.exists())
                self.assertEqual(unrelated.read_bytes(), b"unrelated")
                self.assertEqual(owned_paths(temp_root, output), [])


        for failure_step in range(1, 5):
            with self.subTest(existing_destination_failure=failure_step):
                assert_publication_failure(
                    failure_step, existing_destinations=True
                )

        for failure_step in range(1, 3):
            with self.subTest(absent_destination_failure=failure_step):
                assert_publication_failure(
                    failure_step, existing_destinations=False
                )

        if not sys.platform.startswith("win"):
            with tempfile.TemporaryDirectory() as temp_directory:
                temp_root = Path(temp_directory)
                fixture_root = self.create_full_plugin_fixture(temp_root)
                module = load_simplification_packager(fixture_root, "symlink_success")
                output = temp_root / "simplification.zip"
                target = temp_root / "symlink-target.zip"
                target.write_bytes(b"symlink target sentinel")
                output.symlink_to(target)

                self.assertEqual(invoke(module, fixture_root, output), 0)

                self.assertFalse(output.is_symlink())
                self.assertEqual(target.read_bytes(), b"symlink target sentinel")
                self.assertEqual(owned_paths(temp_root, output), [])

            with tempfile.TemporaryDirectory() as temp_directory:
                temp_root = Path(temp_directory)
                fixture_root = self.create_full_plugin_fixture(temp_root)
                module = load_simplification_packager(fixture_root, "dangling_symlink_failure")
                output = temp_root / "simplification.zip"
                checksum = output.with_suffix(output.suffix + ".sha256")
                symlink_target = temp_root / "missing-symlink-target.zip"
                output.symlink_to(symlink_target)
                original_replace = module.os.replace

                def fail_checksum_publication(source, destination):
                    if Path(destination) == checksum:
                        raise OSError("injected checksum publication failure")
                    return original_replace(source, destination)

                with mock.patch.object(
                    module.os, "replace", side_effect=fail_checksum_publication
                ):
                    with self.assertRaisesRegex(
                        OSError, "injected checksum publication failure"
                    ):
                        invoke(module, fixture_root, output)

                self.assertTrue(output.is_symlink())
                self.assertEqual(output.readlink(), symlink_target)
                self.assertFalse(checksum.exists())
                self.assertEqual(owned_paths(temp_root, output), [])

        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            module = load_simplification_packager(fixture_root, "directory_destination")
            output = temp_root / "simplification.zip"
            checksum = output.with_suffix(output.suffix + ".sha256")
            output.mkdir()
            directory_sentinel = output / "sentinel.txt"
            directory_sentinel.write_bytes(b"directory sentinel")
            checksum.write_bytes(b"checksum sentinel")

            with self.assertRaises(IsADirectoryError):
                invoke(module, fixture_root, output)

            self.assertTrue(output.is_dir())
            self.assertEqual(directory_sentinel.read_bytes(), b"directory sentinel")
            self.assertEqual(checksum.read_bytes(), b"checksum sentinel")
            self.assertEqual(owned_paths(temp_root, output), [])

        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            module = load_simplification_packager(fixture_root, "success")
            output = temp_root / "simplification.zip"
            checksum = output.with_suffix(output.suffix + ".sha256")
            output.write_bytes(b"archive sentinel")
            checksum.write_bytes(b"checksum sentinel")

            self.assertEqual(invoke(module, fixture_root, output), 0)

            digest, filename = checksum.read_text(encoding="utf-8").split()
            self.assertEqual(filename, output.name)
            self.assertEqual(digest, hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(owned_paths(temp_root, output), [])

    def test_publication_recovery_retains_unrestored_backups(self) -> None:
        for packager_name in ("full", "simplification"):
            with self.subTest(packager=packager_name), tempfile.TemporaryDirectory() as temp_directory:
                temp_root = Path(temp_directory)
                fixture_root = self.create_full_plugin_fixture(temp_root)
                modules = self.publication_packagers(fixture_root, packager_name)
                module = modules[0] if packager_name == "full" else modules[1]
                destinations = [temp_root / "first.zip", temp_root / "second.zip"]
                staged = [temp_root / "first.stage", temp_root / "second.stage"]
                for index, destination in enumerate(destinations):
                    destination.write_bytes(f"prior-{index}".encode("utf-8"))
                    staged[index].write_bytes(f"new-{index}".encode("utf-8"))
                original_replace = module.os.replace

                def fail_forward_and_first_restore(source, destination):
                    source_path = Path(source)
                    destination_path = Path(destination)
                    if source_path == staged[1] and destination_path == destinations[1]:
                        raise OSError("injected forward publication failure")
                    if (
                        "-backup-" in source_path.name
                        and destination_path == destinations[0]
                    ):
                        raise OSError("injected backup restoration failure")
                    return original_replace(source, destination)

                with mock.patch.object(
                    module.os,
                    "replace",
                    side_effect=fail_forward_and_first_restore,
                ):
                    with self.assertRaises(module.PublicationRecoveryError) as caught:
                        module.publish_staged_outputs(
                            list(zip(destinations, staged, strict=True))
                        )

                error = caught.exception
                self.assertIsInstance(error, OSError)
                self.assertIsInstance(error.__cause__, OSError)
                self.assertIn("injected forward publication failure", str(error.__cause__))
                record = error.recovery_record
                self.assertEqual(
                    record["schema_version"], "package-publication/recovery/v1"
                )
                self.assertEqual(len(record["unrestored_backups"]), 1)
                mapping = record["unrestored_backups"][0]
                self.assertEqual(mapping["destination"], str(destinations[0]))
                backup = Path(mapping["backup"])
                self.assertTrue(backup.is_file())
                self.assertEqual(backup.read_bytes(), b"prior-0")
                self.assertFalse(destinations[0].exists())
                self.assertEqual(destinations[1].read_bytes(), b"prior-1")
                self.assertFalse(any(path.exists() for path in staged))

    def test_publication_recovery_handles_interrupts(self) -> None:
        for packager_name in ("full", "simplification"):
            for interruption in (KeyboardInterrupt("stop publication"), SystemExit(23)):
                with self.subTest(
                    packager=packager_name,
                    interruption=type(interruption).__name__,
                ), tempfile.TemporaryDirectory() as temp_directory:
                    temp_root = Path(temp_directory)
                    fixture_root = self.create_full_plugin_fixture(temp_root)
                    modules = self.publication_packagers(
                        fixture_root,
                        f"{packager_name}_{type(interruption).__name__}",
                    )
                    module = modules[0] if packager_name == "full" else modules[1]
                    destinations = [temp_root / "first.zip", temp_root / "second.zip"]
                    staged = [temp_root / "first.stage", temp_root / "second.stage"]
                    for index, destination in enumerate(destinations):
                        destination.write_bytes(f"prior-{index}".encode("utf-8"))
                        staged[index].write_bytes(f"new-{index}".encode("utf-8"))
                    original_replace = module.os.replace

                    def interrupt_second_publication(source, destination):
                        if Path(source) == staged[1] and Path(destination) == destinations[1]:
                            raise interruption
                        return original_replace(source, destination)

                    with mock.patch.object(
                        module.os,
                        "replace",
                        side_effect=interrupt_second_publication,
                    ):
                        with self.assertRaises(type(interruption)) as caught:
                            module.publish_staged_outputs(
                                list(zip(destinations, staged, strict=True))
                            )
                    self.assertIs(caught.exception, interruption)
                    self.assertEqual(destinations[0].read_bytes(), b"prior-0")
                    self.assertEqual(destinations[1].read_bytes(), b"prior-1")
                    self.assertFalse(any(path.exists() for path in staged))

        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            module = self.publication_packagers(fixture_root, "interrupt_cleanup")[0]
            destinations = [temp_root / "first.zip", temp_root / "second.zip"]
            staged = [temp_root / "first.stage", temp_root / "second.stage"]
            for index, destination in enumerate(destinations):
                destination.write_bytes(f"prior-{index}".encode("utf-8"))
                staged[index].write_bytes(f"new-{index}".encode("utf-8"))
            interruption = KeyboardInterrupt("cleanup interruption")
            original_replace = module.os.replace
            original_unlink = Path.unlink

            def interrupt_second_publication(source, destination):
                if Path(source) == staged[1] and Path(destination) == destinations[1]:
                    raise interruption
                return original_replace(source, destination)

            def fail_staged_cleanup(path, *arguments, **keywords):
                if path == staged[1]:
                    raise OSError("injected staged cleanup failure")
                return original_unlink(path, *arguments, **keywords)

            with mock.patch.object(
                module.os, "replace", side_effect=interrupt_second_publication
            ), mock.patch.object(Path, "unlink", new=fail_staged_cleanup):
                with self.assertRaises(KeyboardInterrupt) as caught:
                    module.publish_staged_outputs(
                        list(zip(destinations, staged, strict=True))
                    )
            self.assertIs(caught.exception, interruption)
            record = interruption.publication_recovery_record
            self.assertEqual(len(record["cleanup_failures"]), 1)
            self.assertEqual(record["cleanup_failures"][0]["path"], str(staged[1]))

    def test_package_layout_rejects_drive_shaped_and_unsafe_paths_in_every_consumer(self) -> None:
        unsafe_paths = (
            "C:/escape",
            "c:escape",
            "/absolute",
            "../parent",
            "folder\\entry",
            "",
            ".",
            "//server/share",
            "\\\\?\\C:\\device",
        )
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            publisher = self.load_fixture_module(
                fixture_root / "scripts/package_plugin.py", "unsafe_layout_publisher"
            )
            source_validator = self.load_fixture_module(
                fixture_root / "scripts/validate_package.py", "unsafe_layout_source_validator"
            )
            shipped_validator = self.load_fixture_module(
                fixture_root / "skills/material-code-review/scripts/validate_package.py",
                "unsafe_layout_shipped_validator",
            )
            manifest_path = fixture_root / "skills/material-code-review/package-layouts.json"
            canonical = json.loads(manifest_path.read_text(encoding="utf-8"))

            for index, unsafe in enumerate(unsafe_paths):
                with self.subTest(path=unsafe):
                    manifest = json.loads(json.dumps(canonical))
                    manifest["layouts"]["full-plugin"]["required_mappings"][0][
                        "source"
                    ] = unsafe
                    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "unsafe manifest source"):
                        publisher.load_layout_manifest(fixture_root)
                    errors: list[str] = []
                    self.assertIsNone(
                        source_validator.load_layout_manifest(fixture_root, errors)
                    )
                    self.assertTrue(any("unsafe layout source" in error for error in errors))
                    shipped_validator.ROOT = fixture_root / "skills/material-code-review"
                    shipped_errors: list[str] = []
                    self.assertIsNone(
                        shipped_validator.load_layout_contract(shipped_errors)
                    )
                    self.assertTrue(
                        any("unsafe layout source" in error for error in shipped_errors)
                    )

            manifest_path.write_text(json.dumps(canonical), encoding="utf-8")
            self.assertEqual(
                publisher.normalize_manifest_path(
                    "skills/material-code-review/SKILL.md", "control"
                ),
                "skills/material-code-review/SKILL.md",
            )

            _, full_archive, _ = self.build_review_archives(temp_root, fixture_root)
            unsafe_archive = temp_root / "drive-member.zip"
            shutil.copy2(full_archive, unsafe_archive)
            with zipfile.ZipFile(unsafe_archive, "a") as archive:
                archive.writestr("C:/escape.txt", "unsafe")
            result = self.run_review_archive_validator(
                fixture_root, unsafe_archive, standalone=False
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsafe archive path C:/escape.txt", result.stderr)

    def test_package_layout_schema_version_requires_exact_integer(self) -> None:
        invalid_versions = (True, False, 1.0, "1", None, 0, 2, [], {})
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            publisher = self.load_fixture_module(
                fixture_root / "scripts/package_plugin.py", "schema_layout_publisher"
            )
            source_validator = self.load_fixture_module(
                fixture_root / "scripts/validate_package.py", "schema_layout_source_validator"
            )
            shipped_validator = self.load_fixture_module(
                fixture_root / "skills/material-code-review/scripts/validate_package.py",
                "schema_layout_shipped_validator",
            )
            manifest_path = fixture_root / "skills/material-code-review/package-layouts.json"
            canonical = json.loads(manifest_path.read_text(encoding="utf-8"))

            for version in invalid_versions:
                with self.subTest(version=version):
                    manifest = json.loads(json.dumps(canonical))
                    manifest["schema_version"] = version
                    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "schema_version must be 1"):
                        publisher.load_layout_manifest(fixture_root)
                    errors: list[str] = []
                    self.assertIsNone(
                        source_validator.load_layout_manifest(fixture_root, errors)
                    )
                    self.assertIn(
                        "package layout manifest schema_version must be 1", errors
                    )
                    shipped_validator.ROOT = fixture_root / "skills/material-code-review"
                    shipped_errors: list[str] = []
                    self.assertIsNone(
                        shipped_validator.load_layout_contract(shipped_errors)
                    )
                    self.assertIn(
                        "package layout manifest schema_version must be 1",
                        shipped_errors,
                    )

            missing = json.loads(json.dumps(canonical))
            missing.pop("schema_version")
            manifest_path.write_text(json.dumps(missing), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema_version must be 1"):
                publisher.load_layout_manifest(fixture_root)

            manifest_path.write_text(json.dumps(canonical), encoding="utf-8")
            self.assertEqual(
                publisher.load_layout_manifest(fixture_root).keys(),
                canonical["layouts"].keys(),
            )

    @unittest.skipIf(sys.platform.startswith("win"), "fixture requires POSIX filename semantics")
    def test_packager_rejects_unsafe_consumer_paths(self) -> None:
        for unsafe_name in ("..\\escape.txt", "C:\\escape.txt"):
            with self.subTest(unsafe_name=unsafe_name), tempfile.TemporaryDirectory() as temp_directory:
                temp_root = Path(temp_directory)
                fixture_root = self.create_repository_fixture(temp_root)
                skill_root = fixture_root / "skills" / "material-code-simplification"
                (skill_root / unsafe_name).write_text("unsafe\n", encoding="utf-8")

                package_result = self.run_packager(fixture_root, temp_root / "standalone.zip")

                self.assertNotEqual(package_result.returncode, 0)
                self.assertIn(f"unsafe archive entry: {unsafe_name}", package_result.stderr)

    def test_archive_omits_review_specific_codex_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_repository_fixture(temp_root)
            output = temp_root / "standalone.zip"

            package_result = self.run_packager(fixture_root, output)

            self.assertEqual(package_result.returncode, 0, package_result.stderr)
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertNotIn("CODEX.md", names)
                self.assertIn("LICENSE", names)
                self.assertIn("SECURITY.md", names)
                self.assertIn("SKILL.md", names)
                self.assertIn("agents/openai.yaml", names)
                self.assertIn("core/reviewctl.py", names)
                self.assertIn("name: material-code-simplification", archive.read("SKILL.md").decode("utf-8"))
                self.assertIn(
                    "$material-code-simplification",
                    archive.read("agents/openai.yaml").decode("utf-8"),
                )

    def test_in_skill_output_is_reproducible_without_temporary_self_inclusion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_repository_fixture(temp_root)
            output = (
                fixture_root
                / "skills"
                / "material-code-simplification"
                / "artifacts"
                / "standalone.zip"
            )

            first_result = self.run_packager(fixture_root, output)
            self.assertEqual(first_result.returncode, 0, first_result.stderr)
            first_archive = output.read_bytes()

            second_result = self.run_packager(fixture_root, output)
            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            self.assertEqual(output.read_bytes(), first_archive)
            with zipfile.ZipFile(output) as archive:
                self.assertFalse(
                    any(name.startswith("artifacts/.standalone.zip.") for name in archive.namelist()),
                    archive.namelist(),
                )

    def test_packager_rejects_output_that_aliases_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_repository_fixture(temp_root)
            output = fixture_root / "skills" / "material-code-simplification" / "SKILL.md"
            original = output.read_bytes()

            package_result = self.run_packager(fixture_root, output)

            self.assertNotEqual(package_result.returncode, 0)
            self.assertIn("output path aliases an archive source", package_result.stderr)
            self.assertEqual(output.read_bytes(), original)

    def test_source_validator_ignores_root_gitfile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
            (fixture_root / ".git").write_text("gitdir: /tmp/example-worktree\n", encoding="utf-8")

            validation_result = self.run_package_validator(fixture_root)

            self.assertEqual(validation_result.returncode, 0, validation_result.stderr)

    def test_source_validator_still_rejects_nested_gitfile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
            nested_gitfile = fixture_root / "vendor" / ".git"
            nested_gitfile.parent.mkdir()
            nested_gitfile.write_text("gitdir: /tmp/vendor-repository\n", encoding="utf-8")

            validation_result = self.run_package_validator(fixture_root)

            self.assertNotEqual(validation_result.returncode, 0)
            self.assertIn("forbidden generated/VCS path in source package: vendor/.git", validation_result.stderr)

    def test_shipped_reviewer_prompts_bind_v6_assignments_in_source_and_archive(self) -> None:
        required_tokens = (
            "candidate-set-v6.schema.json",
            "coverage_plan_hash",
            "coverage_context_hash",
            "assignment_id",
            "assignment_kind",
            "obligation_id",
            "required_review_paths",
            "required_checks",
            "lens_id",
            "reviewer_id",
            "independence_group",
            "review_mode",
            "frozen source",
            "actual process",
        )
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            output = temp_root / "full-plugin.zip"
            package_result = self.run_full_packager(
                fixture_root,
                output,
                standalone_output=temp_root / "standalone.zip",
            )
            self.assertEqual(package_result.returncode, 0, package_result.stderr)

            source_prompts = {
                path.relative_to(fixture_root).as_posix(): path.read_text(encoding="utf-8")
                for path in sorted((fixture_root / "agents").glob("*-reviewer.md"))
            }
            self.assertEqual(
                set(source_prompts),
                {
                    "agents/correctness-reviewer.md",
                    "agents/risk-reviewer.md",
                    "agents/standards-reviewer.md",
                    "agents/test-reviewer.md",
                },
            )
            with zipfile.ZipFile(output) as archive:
                archive_prompts = {
                    path: archive.read(path).decode("utf-8")
                    for path in source_prompts
                }

        self.assertEqual(archive_prompts, source_prompts)
        for path, prompt in source_prompts.items():
            with self.subTest(prompt=path):
                self.assertNotIn("candidate-set.schema.json", prompt)
                for token in required_tokens:
                    self.assertIn(token, prompt)
                if path == "agents/risk-reviewer.md":
                    for token in (
                        "unit_ids",
                        "primary_paths",
                        "context_paths",
                        "scenario",
                        "check",
                        "evidence paths",
                    ):
                        self.assertIn(token, prompt)
                else:
                    self.assertIn("every required path", prompt)

    def test_review_adjudication_v4_and_host_consumer_ship_in_all_layouts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            full_archive = temp_root / "full-plugin.zip"
            review_archive = temp_root / "review-skill.zip"
            simplification_archive = temp_root / "simplification-skill.zip"

            package_result = self.run_full_packager(
                fixture_root,
                full_archive,
                standalone_output=review_archive,
            )
            simplification_result = self.run_packager(
                fixture_root,
                simplification_archive,
            )

            self.assertEqual(package_result.returncode, 0, package_result.stderr)
            self.assertEqual(
                simplification_result.returncode,
                0,
                simplification_result.stderr,
            )

            source_schema_path = (
                fixture_root
                / "skills/material-code-review/schemas/adjudication-v4.schema.json"
            )
            self.assertTrue(
                source_schema_path.is_file(),
                "material review must ship its strict adjudication-v4 schema",
            )
            source_schema = json.loads(source_schema_path.read_text(encoding="utf-8"))
            source_host_consumer = (
                fixture_root / "agents/finding-adjudicator.md"
            ).read_text(encoding="utf-8")
            self.assertEqual(
                source_schema["properties"]["schema_version"]["const"],
                "material-review/adjudication/v4",
            )
            self.assertIn("source_lenses", source_schema["properties"]["groups"]["items"]["required"])
            self.assertIn("schemas/adjudication-v4.schema.json", source_host_consumer)
            self.assertNotIn("schemas/adjudication.schema.json", source_host_consumer)

            with zipfile.ZipFile(full_archive) as archive:
                full_names = set(archive.namelist())
                full_host_consumer = archive.read(
                    "agents/finding-adjudicator.md"
                ).decode("utf-8")
                full_controller = archive.read(
                    "skills/material-code-review/scripts/reviewctl.py"
                ).decode("utf-8")
            self.assertIn(
                "skills/material-code-review/schemas/adjudication-v4.schema.json",
                full_names,
            )
            self.assertIn("agents/finding-adjudicator.md", full_names)
            self.assertEqual(full_host_consumer, source_host_consumer)
            self.assertIn("material-review/adjudication/v4", full_controller)
            self.assertIn("material-review/ledger/v4", full_controller)

            with zipfile.ZipFile(review_archive) as archive:
                review_names = set(archive.namelist())
                review_skill = archive.read("SKILL.md").decode("utf-8")
                review_adjudicator = archive.read(
                    "references/adjudicator-template.md"
                ).decode("utf-8")
                review_schema = json.loads(
                    archive.read("schemas/adjudication-v4.schema.json")
                )
            self.assertIn("schemas/adjudication-v4.schema.json", review_names)
            self.assertIn("scripts/reviewctl.py", review_names)
            self.assertIn("schemas/adjudication-v4.schema.json", review_skill)
            self.assertIn("schemas/adjudication-v4.schema.json", review_adjudicator)
            self.assertEqual(
                review_schema["properties"]["schema_version"]["const"],
                "material-review/adjudication/v4",
            )

            with zipfile.ZipFile(simplification_archive) as archive:
                simplification_names = set(archive.namelist())
                simplification_schema = json.loads(
                    archive.read("core/schemas/adjudication.schema.json")
                )
                simplification_adjudicator = archive.read(
                    "references/adjudicator-template.md"
                ).decode("utf-8")
                simplification_workflow = archive.read(
                    "references/workflow.md"
                ).decode("utf-8")
                simplification_controller = archive.read(
                    "core/reviewctl.py"
                ).decode("utf-8")
            self.assertIn("core/schemas/adjudication-v4.schema.json", simplification_names)
            self.assertIn("core/schemas/adjudication.schema.json", simplification_names)
            self.assertEqual(
                simplification_schema["properties"]["schema_version"]["const"],
                "material-review/adjudication/v3",
            )
            self.assertIn("adjudication/v3", simplification_adjudicator)
            self.assertIn("adjudication/v3", simplification_workflow)
            self.assertNotIn("adjudication-v4.schema.json", simplification_adjudicator)
            self.assertIn("material-review/candidates-normalized/v1", simplification_controller)
            self.assertIn("material-review/adjudication/v3", simplification_controller)
            self.assertIn("material-review/ledger/v3", simplification_controller)

            missing_archive = temp_root / "simplification-without-adjudication-v4.zip"
            with zipfile.ZipFile(simplification_archive) as source_archive:
                with zipfile.ZipFile(missing_archive, "w") as target_archive:
                    target_archive.comment = source_archive.comment
                    for member in source_archive.infolist():
                        if member.filename == "core/schemas/adjudication-v4.schema.json":
                            continue
                        target_archive.writestr(member, source_archive.read(member))
            missing_archive_result = self.run_simplification_archive_validator(
                missing_archive
            )
            self.assertNotEqual(missing_archive_result.returncode, 0)
            self.assertEqual(
                missing_archive_result.stderr,
                "[FAIL] material-code-simplification validation\n"
                "- simplification-without-adjudication-v4.zip: missing archive entry: "
                "core/schemas/adjudication-v4.schema.json\n",
            )

            extracted_layout = temp_root / "extracted-simplification"
            self.extract_archive_with_modes(simplification_archive, extracted_layout)
            extracted_schema_path = (
                extracted_layout / "core/schemas/adjudication-v4.schema.json"
            )
            extracted_schema_path.unlink()
            extracted_result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(extracted_layout / "scripts/validate_package.py"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(extracted_result.returncode, 0)
            self.assertEqual(
                extracted_result.stderr,
                "[FAIL] material-code-simplification validation\n"
                f"- missing shared schema: {extracted_schema_path.resolve()}\n",
            )

            source_schema_path.unlink()
            source_result = self.run_simplification_validator(fixture_root)
            self.assertNotEqual(source_result.returncode, 0)
            self.assertEqual(
                source_result.stderr,
                "[FAIL] material-code-simplification validation\n"
                f"- missing shared schema: {source_schema_path.resolve()}\n",
            )

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_source_validator_still_validates_committed_evaluation_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
            case = (
                fixture_root
                / "evaluations/material-code-review/cases/discogs-custom-playlists.json"
            )
            case.write_text("{ invalid evaluation JSON\n", encoding="utf-8")

            validation_result = self.run_package_validator(
                fixture_root,
                distribution_layout=False,
            )

            self.assertNotEqual(validation_result.returncode, 0)
            self.assertIn(
                "evaluations/material-code-review/cases/discogs-custom-playlists.json",
                validation_result.stderr,
            )

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_validation_ignores_malformed_local_evaluation_run_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
            interrupted_run = fixture_root / ".evaluation-runs/interrupted/run.json"
            interrupted_run.parent.mkdir(parents=True, exist_ok=True)
            interrupted_run.write_text("{ incomplete local evidence\n", encoding="utf-8")

            validation_result = self.run_package_validator(
                fixture_root,
                distribution_layout=False,
            )
            json_result = subprocess.run(
                ["make", "json"],
                cwd=fixture_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            self.assertEqual(validation_result.returncode, 0, validation_result.stderr)
            self.assertEqual(
                json_result.returncode,
                0,
                json_result.stdout + json_result.stderr,
            )

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_prompt_driven_evaluation_case_is_frozen(self) -> None:
        case_path = (
            REPOSITORY_ROOT
            / "evaluations/material-code-review/cases/discogs-custom-playlists.json"
        )
        self.assertTrue(case_path.is_file(), f"missing frozen case: {case_path}")
        case = json.loads(case_path.read_text(encoding="utf-8"))

        expected = {
            "schema_version": "material-review-evaluation/case/v1",
            "case_id": "discogs-custom-playlists",
            "target_type": "git_repository",
            "repository": "https://github.com/CoveMB/discogs-collection.git",
            "branch_label": "custom-playlists",
            "base_commit": "361e1740fa164fafc590e7dc8903a87b069592cb",
            "review_commit": "3050f047c4cb1a7b32237844ec7cf68a5675c957",
            "require_immediate_parent": True,
            "review_mode": "range",
            "posture": "immutable",
        }
        self.assertEqual(case, expected)

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_missed_contracts_fixture_identity_matches_generalized_guidance(self) -> None:
        evaluation_root = REPOSITORY_ROOT / "evaluations/material-code-review"
        case_path = evaluation_root / "cases/missed-contracts.json"
        self.assertTrue(case_path.is_file(), f"missing frozen case: {case_path}")
        case = json.loads(case_path.read_text(encoding="utf-8"))
        self.assertEqual(case["target_type"], "git_fixture")
        self.assertEqual(
            set(case["required_root_ids"]),
            {
                "version-decoy",
                "workflow-missing-scope",
                "path-language",
                "risk-cardinality",
                "archive-closure",
            },
        )

        fixture = case["fixture"]
        base_root = REPOSITORY_ROOT / fixture["base_root"]
        review_root = REPOSITORY_ROOT / fixture["review_root"]
        expected_base_files = {
            "AGENTS.md",
            "scripts/validate_package.py",
            "skills/demo/scripts/validate_package.py",
            "skills/demo/references/workflow.md",
            "skills/demo/schemas/candidate-set.json",
            "skills/demo/schemas/coverage-plan.json",
            "skills/demo/package-layouts.json",
        }
        expected_review_files = expected_base_files - {
            "AGENTS.md",
            "skills/demo/package-layouts.json",
        }
        self.assertEqual(
            {
                path.relative_to(base_root).as_posix()
                for path in base_root.rglob("*")
                if path.is_file()
            },
            expected_base_files,
        )
        self.assertEqual(
            {
                path.relative_to(review_root).as_posix()
                for path in review_root.rglob("*")
                if path.is_file()
            },
            expected_review_files,
        )

        with tempfile.TemporaryDirectory() as temp_directory:
            repository = Path(temp_directory) / "fixture-repository"
            shutil.copytree(base_root, repository)
            subprocess.run(
                ["git", "init", "-q"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            )
            environment = dict(os.environ)
            environment.update(
                {
                    "GIT_AUTHOR_NAME": fixture["author_name"],
                    "GIT_AUTHOR_EMAIL": fixture["author_email"],
                    "GIT_COMMITTER_NAME": fixture["author_name"],
                    "GIT_COMMITTER_EMAIL": fixture["author_email"],
                    "GIT_AUTHOR_DATE": fixture["base_timestamp"],
                    "GIT_COMMITTER_DATE": fixture["base_timestamp"],
                }
            )
            subprocess.run(
                ["git", "add", "--all"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-q",
                    "-m",
                    fixture["base_message"],
                ],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            base_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            base_tree = subprocess.run(
                ["git", "rev-parse", "HEAD^{tree}"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

            shutil.copytree(review_root, repository, dirs_exist_ok=True)
            environment["GIT_AUTHOR_DATE"] = fixture["review_timestamp"]
            environment["GIT_COMMITTER_DATE"] = fixture["review_timestamp"]
            subprocess.run(
                ["git", "add", "--all"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-q",
                    "-m",
                    fixture["review_message"],
                ],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            review_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            review_tree = subprocess.run(
                ["git", "rev-parse", "HEAD^{tree}"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            changed_paths = set(
                subprocess.run(
                    [
                        "git",
                        "diff-tree",
                        "--no-commit-id",
                        "--name-only",
                        "-r",
                        review_commit,
                    ],
                    cwd=repository,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.splitlines()
            )

        self.assertEqual(base_tree, fixture["base_tree"])
        self.assertEqual(review_tree, fixture["review_tree"])
        self.assertEqual(base_commit, fixture["base_commit"])
        self.assertEqual(review_commit, fixture["review_commit"])
        self.assertEqual(changed_paths, expected_review_files)

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_evaluator_requires_sha1_initialization_and_attestation(self) -> None:
        skill_path = (
            REPOSITORY_ROOT / ".agents/skills/material-review-evaluation/SKILL.md"
        )
        text = skill_path.read_text(encoding="utf-8")
        initialization = "git init --object-format=sha1"
        attestation = "git rev-parse --show-object-format"
        before_mutation = "before-add-commit-or-dispatch"
        self.assertIn(initialization, text)
        self.assertIn(attestation, text)
        self.assertIn(before_mutation, text)
        self.assertLess(text.index(initialization), text.index(attestation))

        mutations = (
            (
                initialization,
                "git init",
                "maintainer evaluator must initialize fixture repositories as SHA-1",
            ),
            (
                attestation,
                "git rev-parse --git-dir",
                "maintainer evaluator must attest the fixture object format",
            ),
            (
                before_mutation,
                "after-add-before-commit-or-dispatch",
                "maintainer evaluator must attest SHA-1 before fixture mutation or dispatch",
            ),
        )
        for original, replacement, expected_error in mutations:
            with self.subTest(mutation=replacement), tempfile.TemporaryDirectory() as temp_directory:
                fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
                self.replace_once(
                    fixture_root / ".agents/skills/material-review-evaluation/SKILL.md",
                    original,
                    replacement,
                )
                result = self.run_package_validator(
                    fixture_root,
                    distribution_layout=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_missed_contracts_fixture_reconstructs_sha1_under_hostile_default(self) -> None:
        evaluation_root = REPOSITORY_ROOT / "evaluations/material-code-review"
        case = json.loads(
            (evaluation_root / "cases/missed-contracts.json").read_text(
                encoding="utf-8"
            )
        )
        fixture = case["fixture"]
        base_root = REPOSITORY_ROOT / fixture["base_root"]
        review_root = REPOSITORY_ROOT / fixture["review_root"]

        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            repository = temp_root / "fixture-repository"
            shutil.copytree(base_root, repository)
            hostile_config = temp_root / "hostile-gitconfig"
            hostile_config.write_text(
                "[init]\n\tdefaultObjectFormat = sha256\n",
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment.update(
                {
                    "GIT_CONFIG_GLOBAL": str(hostile_config),
                    "GIT_CONFIG_SYSTEM": os.devnull,
                    "GIT_DEFAULT_HASH": "sha256",
                    "GIT_AUTHOR_NAME": fixture["author_name"],
                    "GIT_AUTHOR_EMAIL": fixture["author_email"],
                    "GIT_COMMITTER_NAME": fixture["author_name"],
                    "GIT_COMMITTER_EMAIL": fixture["author_email"],
                    "GIT_AUTHOR_DATE": fixture["base_timestamp"],
                    "GIT_COMMITTER_DATE": fixture["base_timestamp"],
                }
            )
            subprocess.run(
                ["git", "init", "-q", "--object-format=sha1"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            object_format = subprocess.run(
                ["git", "rev-parse", "--show-object-format"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            ).stdout.strip()
            self.assertEqual(object_format, "sha1")

            def commit(message: str, timestamp: str) -> tuple[str, str]:
                environment["GIT_AUTHOR_DATE"] = timestamp
                environment["GIT_COMMITTER_DATE"] = timestamp
                subprocess.run(
                    ["git", "add", "--all"],
                    cwd=repository,
                    check=True,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
                subprocess.run(
                    [
                        "git",
                        "-c",
                        "commit.gpgsign=false",
                        "commit",
                        "-q",
                        "-m",
                        message,
                    ],
                    cwd=repository,
                    check=True,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
                commit_oid = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=repository,
                    check=True,
                    capture_output=True,
                    text=True,
                    env=environment,
                ).stdout.strip()
                tree_oid = subprocess.run(
                    ["git", "rev-parse", "HEAD^{tree}"],
                    cwd=repository,
                    check=True,
                    capture_output=True,
                    text=True,
                    env=environment,
                ).stdout.strip()
                return commit_oid, tree_oid

            base_commit, base_tree = commit(
                fixture["base_message"], fixture["base_timestamp"]
            )
            shutil.copytree(review_root, repository, dirs_exist_ok=True)
            review_commit, review_tree = commit(
                fixture["review_message"], fixture["review_timestamp"]
            )

        self.assertEqual(base_tree, fixture["base_tree"])
        self.assertEqual(review_tree, fixture["review_tree"])
        self.assertEqual(base_commit, fixture["base_commit"])
        self.assertEqual(review_commit, fixture["review_commit"])

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_missed_contracts_worker_guidance_is_unseeded_and_oracle_remains_private(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "missed_contracts_guidance_validator",
            PACKAGE_VALIDATOR,
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)

        case = json.loads(
            (
                REPOSITORY_ROOT
                / "evaluations/material-code-review/cases/missed-contracts.json"
            ).read_text(encoding="utf-8")
        )
        denied_values = (
            *case["required_root_ids"],
            *case["root_contracts"].values(),
            *validator.MISSED_CONTRACT_RETIRED_GUIDANCE,
        )
        self.assertEqual(
            set(case["root_contracts"]),
            set(case["required_root_ids"]),
        )
        self.assertEqual(
            tuple(validator.MISSED_CONTRACT_WORKER_GUIDANCE_PATHS),
            (
                "evaluations/material-code-review/fixtures/missed-contracts/base/AGENTS.md",
                "evaluations/material-code-review/prompts/reviewer.md",
                "evaluations/material-code-review/prompts/challenger.md",
                "evaluations/material-code-review/prompts/judge.md",
                "evaluations/material-code-review/rubric.md",
            ),
        )
        for relative in validator.MISSED_CONTRACT_WORKER_GUIDANCE_PATHS:
            text = (REPOSITORY_ROOT / relative).read_text(encoding="utf-8").casefold()
            for denied in denied_values:
                self.assertNotIn(denied.casefold(), text, (relative, denied))

        errors: list[str] = []
        validator.validate_missed_contracts_worker_guidance(
            REPOSITORY_ROOT,
            errors,
        )
        self.assertEqual(errors, [])

        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
            agents_path = (
                fixture_root
                / "evaluations/material-code-review/fixtures/missed-contracts/base/AGENTS.md"
            )
            original_agents = agents_path.read_text(encoding="utf-8")
            for denied in denied_values:
                with self.subTest(known_leak=denied):
                    agents_path.write_text(
                        f"{original_agents}\n{denied}\n",
                        encoding="utf-8",
                    )
                    contamination_errors: list[str] = []
                    validator.validate_missed_contracts_worker_guidance(
                        fixture_root,
                        contamination_errors,
                    )
                    self.assertEqual(
                        contamination_errors,
                        [
                            "missed-contracts worker guidance is contaminated: "
                            "evaluations/material-code-review/fixtures/"
                            "missed-contracts/base/AGENTS.md"
                        ],
                    )
            agents_path.write_text(original_agents, encoding="utf-8")

            for relative in validator.MISSED_CONTRACT_WORKER_GUIDANCE_PATHS:
                with self.subTest(worker_input=relative):
                    path = fixture_root / relative
                    original = path.read_text(encoding="utf-8")
                    path.write_text(
                        f"{original}\n{case['required_root_ids'][0]}\n",
                        encoding="utf-8",
                    )
                    contamination_errors = []
                    validator.validate_missed_contracts_worker_guidance(
                        fixture_root,
                        contamination_errors,
                    )
                    self.assertEqual(len(contamination_errors), 1)
                    self.assertIn(relative, contamination_errors[0])
                    path.write_text(original, encoding="utf-8")

        base = REPOSITORY_ROOT / case["fixture"]["base_root"]
        review = REPOSITORY_ROOT / case["fixture"]["review_root"]
        source_controls = (
            (
                "scripts/validate_package.py",
                "ast.parse",
                'if \'VERSION = "2.0.0"\' not in source',
            ),
            (
                "skills/demo/references/workflow.md",
                "check-scope",
                "record-coverage",
            ),
            (
                "skills/demo/schemas/candidate-set.json",
                '"$ref"',
                '"minLength"',
            ),
            (
                "skills/demo/schemas/coverage-plan.json",
                '"uniqueItems"',
                '"minItems"',
            ),
            (
                "skills/demo/scripts/validate_package.py",
                'ROOT / "package-layouts.json"',
                "REQUIRED_ARCHIVE_ENTRIES",
            ),
        )
        for relative, baseline_evidence, review_evidence in source_controls:
            with self.subTest(source_root=relative):
                self.assertIn(
                    baseline_evidence,
                    (base / relative).read_text(encoding="utf-8"),
                )
                self.assertIn(
                    review_evidence,
                    (review / relative).read_text(encoding="utf-8"),
                )

        skill = (
            REPOSITORY_ROOT / ".agents/skills/material-review-evaluation/SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertLess(
            skill.index("## 6. Dispatch the blinded judge and reveal afterward"),
            skill.index("## 7. Apply the bounded missed-contracts acceptance rule"),
        )
        self.assertIn(
            "apply it only after a durable blinded judgment and identity reveal",
            skill,
        )
        self.assertIn("contamination_dispatch=false", skill)

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_missed_contracts_case_policy_is_closed_and_dimensionally_validated(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "closed_missed_contracts_policy_validator",
            PACKAGE_VALIDATOR,
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)

        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
            case_path = (
                fixture_root
                / "evaluations/material-code-review/cases/missed-contracts.json"
            )
            canonical = json.loads(case_path.read_text(encoding="utf-8"))

            def validate_case(case: object) -> list[str]:
                case_path.write_text(
                    json.dumps(case, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                errors: list[str] = []
                validator.validate_maintainer_evaluator_cases(
                    fixture_root,
                    errors,
                )
                return errors

            self.assertEqual(validate_case(canonical), [])

            mutations: list[tuple[str, dict[str, object], str]] = []

            missing_top = json.loads(json.dumps(canonical))
            del missing_top["schema_version"]
            mutations.append(
                ("missing top-level", missing_top, "top-level policy missing key")
            )
            extra_top = json.loads(json.dumps(canonical))
            extra_top["unexpected"] = True
            mutations.append(
                ("extra top-level", extra_top, "top-level policy has unexpected key")
            )
            wrong_top_type = json.loads(json.dumps(canonical))
            wrong_top_type["require_immediate_parent"] = 1
            mutations.append(
                ("top-level wrong type", wrong_top_type, "has wrong type")
            )
            wrong_top_value = json.loads(json.dumps(canonical))
            wrong_top_value["review_mode"] = "single"
            mutations.append(
                ("top-level wrong value", wrong_top_value, "top-level policy review_mode has wrong value")
            )

            missing_fixture = json.loads(json.dumps(canonical))
            del missing_fixture["fixture"]["author_name"]
            mutations.append(
                ("missing fixture", missing_fixture, "fixture policy missing key: author_name")
            )
            extra_fixture = json.loads(json.dumps(canonical))
            extra_fixture["fixture"]["unexpected"] = "value"
            mutations.append(
                ("extra fixture", extra_fixture, "fixture policy has unexpected key")
            )
            wrong_fixture_type = json.loads(json.dumps(canonical))
            wrong_fixture_type["fixture"]["base_timestamp"] = False
            mutations.append(
                ("fixture wrong type", wrong_fixture_type, "fixture policy base_timestamp has wrong type")
            )
            wrong_fixture_value = json.loads(json.dumps(canonical))
            wrong_fixture_value["fixture"]["author_name"] = "Another Author"
            mutations.append(
                ("fixture wrong value", wrong_fixture_value, "fixture policy author_name has wrong value")
            )

            roots_wrong_type = json.loads(json.dumps(canonical))
            roots_wrong_type["required_root_ids"] = "version-decoy"
            mutations.append(
                ("root list wrong type", roots_wrong_type, "required_root_ids must be a list")
            )
            roots_duplicate = json.loads(json.dumps(canonical))
            roots_duplicate["required_root_ids"][-1] = roots_duplicate["required_root_ids"][0]
            mutations.append(
                ("root duplicate", roots_duplicate, "must contain exactly five unique IDs")
            )
            roots_wrong_value = json.loads(json.dumps(canonical))
            roots_wrong_value["required_root_ids"][-1] = "unknown-root"
            mutations.append(
                ("root wrong value", roots_wrong_value, "required_root_ids values have drifted")
            )

            missing_contract = json.loads(json.dumps(canonical))
            del missing_contract["root_contracts"]["version-decoy"]
            mutations.append(
                ("root contract missing", missing_contract, "root-oracle root_contracts policy missing key")
            )
            extra_contract = json.loads(json.dumps(canonical))
            extra_contract["root_contracts"]["unknown-root"] = "unknown"
            mutations.append(
                ("root contract extra", extra_contract, "root-oracle root_contracts policy has unexpected key")
            )
            wrong_contract_type = json.loads(json.dumps(canonical))
            wrong_contract_type["root_contracts"] = []
            mutations.append(
                ("root contracts wrong type", wrong_contract_type, "root-oracle root_contracts policy must be an object")
            )
            wrong_contract_value = json.loads(json.dumps(canonical))
            wrong_contract_value["root_contracts"]["version-decoy"] = "changed"
            mutations.append(
                ("root contract wrong value", wrong_contract_value, "root-oracle root_contracts policy version-decoy has wrong value")
            )

            for dimension, expected_policy in (
                ("acceptance", validator.MISSED_CONTRACT_ACCEPTANCE_POLICY),
                ("attempt", validator.MISSED_CONTRACT_ATTEMPT_POLICY),
            ):
                case_key = "attempt_policy" if dimension == "attempt" else dimension
                extra = json.loads(json.dumps(canonical))
                extra[case_key]["unexpected"] = True
                mutations.append(
                    (
                        f"{dimension} extra",
                        extra,
                        f"{dimension} policy has unexpected key",
                    )
                )
                for key, expected_value in expected_policy.items():
                    missing = json.loads(json.dumps(canonical))
                    del missing[case_key][key]
                    mutations.append(
                        (
                            f"{dimension} missing {key}",
                            missing,
                            f"{dimension} policy missing key: {key}",
                        )
                    )
                    wrong_type = json.loads(json.dumps(canonical))
                    wrong_type[case_key][key] = (
                        1 if isinstance(expected_value, bool) else False
                    )
                    mutations.append(
                        (
                            f"{dimension} wrong type {key}",
                            wrong_type,
                            f"{dimension} policy {key} has wrong type",
                        )
                    )
                    wrong_value = json.loads(json.dumps(canonical))
                    wrong_value[case_key][key] = (
                        not expected_value
                        if isinstance(expected_value, bool)
                        else expected_value + 1
                    )
                    mutations.append(
                        (
                            f"{dimension} wrong value {key}",
                            wrong_value,
                            f"{dimension} policy {key} has wrong value",
                        )
                    )

            for name, mutated, expected_error in mutations:
                with self.subTest(name=name):
                    errors = validate_case(mutated)
                    self.assertTrue(
                        any(expected_error in error for error in errors),
                        errors,
                    )

            cross_dimension = json.loads(json.dumps(canonical))
            cross_dimension["acceptance"]["require_no_mutation"] = False
            cross_dimension["fixture"]["base_tree"] = "0" * 40
            errors = validate_case(cross_dimension)
            self.assertTrue(
                any(
                    "acceptance policy require_no_mutation has wrong value" in error
                    for error in errors
                ),
                errors,
            )
            self.assertIn("missed-contracts fixture base_tree has drifted", errors)

            case_path.write_text("[]\n", encoding="utf-8")
            errors = []
            validator.validate_maintainer_evaluator_cases(fixture_root, errors)
            self.assertTrue(
                any("must contain an object" in error for error in errors),
                errors,
            )
            case_path.write_text("{\n", encoding="utf-8")
            malformed_result = self.run_package_validator(
                fixture_root,
                distribution_layout=False,
            )
            self.assertNotEqual(malformed_result.returncode, 0)
            self.assertIn("invalid JSON", malformed_result.stderr)

            case_path.write_text(
                json.dumps(canonical, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            errors = []
            validator.validate_maintainer_evaluator_cases(fixture_root, errors)
            self.assertEqual(errors, [])

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_challenger_is_case_only_and_blinded(self) -> None:
        skill = (
            REPOSITORY_ROOT / ".agents/skills/material-review-evaluation/SKILL.md"
        ).read_text(encoding="utf-8")
        challenger_path = (
            REPOSITORY_ROOT
            / "evaluations/material-code-review/prompts/challenger.md"
        )
        self.assertTrue(challenger_path.is_file(), challenger_path)
        challenger = challenger_path.read_text(encoding="utf-8")
        for controlled_term in (
            "case:missed-contracts",
            "candidate findings are forbidden",
            "fork_turns=none",
            "NO_COVERAGE_GAP",
        ):
            self.assertIn(controlled_term, skill)
        for controlled_term in (
            "The root dispatcher must provide zero inherited task history.",
            "Candidate findings and check results are forbidden",
            "expected roots",
            "variant identities",
            "NO_COVERAGE_GAP",
        ):
            self.assertIn(controlled_term, challenger)

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_challenger_claim_is_limited_to_declarative_coverage(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "declarative_challenger_validator",
            PACKAGE_VALIDATOR,
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)

        errors: list[str] = []
        validator.validate_maintainer_evaluator_challenger(
            REPOSITORY_ROOT,
            errors,
        )
        self.assertEqual(errors, [])

        skill_text = (
            REPOSITORY_ROOT / ".agents/skills/material-review-evaluation/SKILL.md"
        ).read_text(encoding="utf-8")
        contract_errors: list[str] = []
        contract = validator.parse_evaluator_contract(
            skill_text,
            validator.EVALUATOR_CHALLENGER_CONTRACT_START,
            validator.EVALUATOR_CHALLENGER_CONTRACT_END,
            contract_errors,
            "challenger boundary contract",
        )
        self.assertEqual(contract_errors, [])
        self.assertEqual(contract, validator.EVALUATOR_CHALLENGER_CONTRACT)
        self.assertEqual(
            set(contract["challenger_inputs"].split(",")),
            {
                "frozen-source",
                "change-units",
                "risk-decisions",
                "obligations",
                "obligation-check-contracts",
                "assignments",
                "limitations",
            },
        )
        forbidden = set(contract["challenger_forbidden"].split(","))
        self.assertTrue(
            {"candidates", "candidate-sets", "check-results"}.issubset(forbidden)
        )
        self.assertEqual(contract["no_coverage_gap_proves"], "declarative-coverage-only")
        self.assertEqual(contract["challenge_response_to_reviewer"], "false")
        self.assertEqual(contract["default_discogs_challenger"], "false")

        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
            skill_path = (
                fixture_root / ".agents/skills/material-review-evaluation/SKILL.md"
            )
            canonical_skill = skill_path.read_text(encoding="utf-8")

            def validate_skill(mutated_skill: str) -> list[str]:
                skill_path.write_text(mutated_skill, encoding="utf-8")
                mutation_errors: list[str] = []
                validator.validate_maintainer_evaluator_challenger(
                    fixture_root,
                    mutation_errors,
                )
                return mutation_errors

            complete_inputs = contract["challenger_inputs"]
            for field in complete_inputs.split(","):
                with self.subTest(missing_declarative_field=field):
                    missing_inputs = ",".join(
                        value
                        for value in complete_inputs.split(",")
                        if value != field
                    )
                    mutated = canonical_skill.replace(
                        f"challenger_inputs={complete_inputs}",
                        f"challenger_inputs={missing_inputs}",
                        1,
                    )
                    self.assertIn(
                        "maintainer evaluator challenger boundary contract is incomplete",
                        validate_skill(mutated),
                    )

            for forbidden_input in ("candidates", "candidate-sets", "check-results"):
                with self.subTest(forbidden_input=forbidden_input):
                    mutated = canonical_skill.replace(
                        f"challenger_inputs={complete_inputs}",
                        f"challenger_inputs={complete_inputs},{forbidden_input}",
                        1,
                    )
                    self.assertIn(
                        "maintainer evaluator challenger boundary contract is incomplete",
                        validate_skill(mutated),
                    )

            for original, replacement, label in (
                (
                    "challenger_outcomes=NO_COVERAGE_GAP,COVERAGE_GAP",
                    "challenger_outcomes=",
                    "empty response language",
                ),
                (
                    "challenger_outcomes=NO_COVERAGE_GAP,COVERAGE_GAP",
                    "challenger_outcomes=NO_COVERAGE_GAP,UNKNOWN",
                    "invalid response language",
                ),
                (
                    "invalid_empty_or_gap=blocks-success-no-retry",
                    "invalid_empty_or_gap=allows-success",
                    "invalid response acceptance",
                ),
            ):
                with self.subTest(response_state=label):
                    mutated = canonical_skill.replace(original, replacement, 1)
                    self.assertIn(
                        "maintainer evaluator challenger boundary contract is incomplete",
                        validate_skill(mutated),
                    )

            native_result_controls = {
                "native_check_results_fresh": "stale",
                "native_check_results_complete": "incomplete",
                "native_check_results_unblocked": "blocked",
                "native_check_results_unique": "duplicated",
                "native_check_results_resolved": "unresolved",
            }
            for key, state in native_result_controls.items():
                with self.subTest(native_check_result=state):
                    mutated = canonical_skill.replace(
                        f"{key}=true",
                        f"{key}=false",
                        1,
                    )
                    self.assertIn(
                        "maintainer evaluator challenger boundary contract is incomplete",
                        validate_skill(mutated),
                    )

            old_check_claim = (
                "stale, incomplete, blocked, or unsafe check evidence"
            )
            challenger_path = (
                fixture_root
                / "evaluations/material-code-review/prompts/challenger.md"
            )
            challenger_path.write_text(
                challenger_path.read_text(encoding="utf-8")
                + f"\n- {old_check_claim};\n",
                encoding="utf-8",
            )
            skill_path.write_text(canonical_skill, encoding="utf-8")
            prompt_errors: list[str] = []
            validator.validate_maintainer_evaluator_challenger(
                fixture_root,
                prompt_errors,
            )
            self.assertIn(
                "challenger prompt must not claim authority over unseen check-result evidence",
                prompt_errors,
            )

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_source_validator_rejects_missed_contract_fixture_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
            workflow = (
                fixture_root
                / "evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/references/workflow.md"
            )
            workflow.write_text(
                workflow.read_text(encoding="utf-8") + "\nDrifted fixture content.\n",
                encoding="utf-8",
            )

            result = self.run_package_validator(
                fixture_root,
                distribution_layout=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missed-contracts fixture base_tree has drifted", result.stderr)
            self.assertIn("missed-contracts fixture base_commit has drifted", result.stderr)

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_prompt_driven_evaluation_prompts_define_controlled_contract(self) -> None:
        evaluation_root = REPOSITORY_ROOT / "evaluations/material-code-review"
        evaluator_skill = (
            REPOSITORY_ROOT / ".agents/skills/material-review-evaluation/SKILL.md"
        ).read_text(encoding="utf-8")
        required_paths = {
            "README": evaluation_root / "README.md",
            "reviewer prompt": evaluation_root / "prompts/reviewer.md",
            "judge prompt": evaluation_root / "prompts/judge.md",
            "rubric": evaluation_root / "rubric.md",
        }
        for label, path in required_paths.items():
            self.assertTrue(path.is_file(), f"missing {label}: {path}")

        reviewer = required_paths["reviewer prompt"].read_text(encoding="utf-8")
        for controlled_term in (
            "361e1740fa164fafc590e7dc8903a87b069592cb..3050f047c4cb1a7b32237844ec7cf68a5675c957",
            "Gate A",
            "Gate B",
            "accept-empty",
            "No repair is authorized.",
            "retained findings",
            "discarded findings",
            "plan hash",
            "limitations",
        ):
            self.assertIn(controlled_term, reviewer)

        self.assertIn(
            "An empty ledger still requires explicit Gate-A acceptance.",
            reviewer,
        )
        self.assertNotIn("coverage-plan/v3", reviewer)
        for controlled_term in (
            "coverage-plan version required by the supplied materialized skill",
            "change-unit owners and affected consumers",
            "specialist scenario decisions",
            "exact assignment paths and checks",
        ):
            self.assertIn(controlled_term, reviewer)

        judge = required_paths["judge prompt"].read_text(encoding="utf-8")
        for outcome in (
            "VARIANT_A_STRONGER",
            "VARIANT_B_STRONGER",
            "MATERIAL_TIE",
            "INSUFFICIENT_EVIDENCE",
        ):
            self.assertIn(outcome, judge)
        self.assertIn("Do not infer or guess variant identities.", judge)

        rubric = required_paths["rubric"].read_text(encoding="utf-8").lower()
        dimension_headings = (
            "1. **finding correctness:**",
            "2. **coverage:**",
            "3. **precision:**",
            "4. **plan quality:**",
            "5. **safety:**",
            "6. **usability:**",
        )
        positions = [rubric.index(heading) for heading in dimension_headings]
        self.assertEqual(positions, sorted(positions))

        readme = required_paths["README"].read_text(encoding="utf-8")
        self.assertIn(
            "$material-review-evaluation base:<skill-ref> candidate:<skill-ref>",
            readme,
        )
        self.assertIn("directional local evidence", readme)

        disposition_states = (
            "ALL_APPROVED_PLAN",
            "MIXED_DISPOSITIONS_NONCOMPARABLE",
            "NO_APPROVED_FINDINGS",
            "ACCEPTED_EMPTY_LEDGER",
            "INVALID_OR_MISSING_EVIDENCE",
        )
        for label, contract_text in (
            ("evaluator skill", evaluator_skill),
            ("reviewer prompt", reviewer),
            ("judge prompt", judge),
            ("rubric", required_paths["rubric"].read_text(encoding="utf-8")),
        ):
            with self.subTest(contract=label):
                for state in disposition_states:
                    self.assertIn(state, contract_text)
                self.assertIn("DISPOSITION_NONCOMPARABLE", contract_text)

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_prompt_driven_evaluation_skill_has_discoverable_contract(self) -> None:
        skill_path = (
            REPOSITORY_ROOT
            / ".agents/skills/material-review-evaluation/SKILL.md"
        )
        self.assertTrue(skill_path.is_file(), f"missing evaluator skill: {skill_path}")
        text = skill_path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"), "skill must start with frontmatter")
        _, frontmatter_text, body = text.split("---", 2)
        frontmatter = {
            key.strip(): value.strip().strip('"')
            for line in frontmatter_text.strip().splitlines()
            for key, value in (line.split(":", 1),)
        }

        self.assertEqual(frontmatter["name"], "material-review-evaluation")
        self.assertTrue(frontmatter["description"].startswith("Use when "))
        self.assertEqual(
            frontmatter["argument-hint"],
            "[case:<case-id>] base:<skill-ref> candidate:<skill-ref>",
        )

        for controlled_term in (
            "$material-review-evaluation base:<skill-ref> candidate:<skill-ref>",
            "VARIANT_A_STRONGER",
            "VARIANT_B_STRONGER",
            "MATERIAL_TIE",
            "INSUFFICIENT_EVIDENCE",
            ".evaluation-runs/",
            "private-variant-map.json",
            "361e1740fa164fafc590e7dc8903a87b069592cb",
            "3050f047c4cb1a7b32237844ec7cf68a5675c957",
            "Combined Gate-A checkpoint",
            "Never approve Gate B.",
            "--accept-empty",
            "trusted local clone source",
            "Missing reviewer evidence",
        ):
            self.assertIn(controlled_term, body)

        self.assertIn(
            "always pause both valid variants at Gate A",
            body,
        )
        self.assertIn(
            "terminate with `INSUFFICIENT_EVIDENCE`",
            body,
        )

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_evaluator_assets_require_attested_root_anchor(self) -> None:
        asset_path = "evaluations/material-code-review/cases/discogs-custom-playlists.json"

        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
            validation_result = self.run_package_validator(
                fixture_root,
                distribution_layout=False,
            )
            self.assertEqual(validation_result.returncode, 0, validation_result.stderr)

        mutations = (
            (
                "pre-anchor asset reference",
                lambda root: self.replace_once(
                    root / ".agents/skills/material-review-evaluation/SKILL.md",
                    "# Material review evaluation",
                    f"# Material review evaluation\n\n- `{asset_path}`",
                ),
                "maintainer evaluator asset referenced before repository root attestation",
            ),
            (
                "missing asset",
                lambda root: (root / asset_path).unlink(),
                f"maintainer evaluator asset is missing: {asset_path}",
            ),
            (
                "non-regular asset",
                lambda root: (
                    (root / asset_path).unlink(),
                    (root / asset_path).mkdir(),
                ),
                f"maintainer evaluator asset is not a regular file: {asset_path}",
            ),
            (
                "skill-relative declaration",
                lambda root: self.replace_once(
                    root / ".agents/skills/material-review-evaluation/SKILL.md",
                    f"- `{asset_path}`",
                    f"- `.agents/skills/material-review-evaluation/{asset_path}`",
                ),
                "maintainer evaluator asset allowlist must match the repository-root contract",
            ),
            (
                "root-escaping declaration",
                lambda root: self.replace_once(
                    root / ".agents/skills/material-review-evaluation/SKILL.md",
                    f"- `{asset_path}`",
                    "- `../discogs-custom-playlists.json`",
                ),
                "maintainer evaluator asset path escapes the repository root",
            ),
            (
                "missing initial clean attestation",
                lambda root: self.replace_once(
                    root / ".agents/skills/material-review-evaluation/SKILL.md",
                    "2. Immediately capture the active material-review repository's `HEAD` "
                    "and porcelain status. Require an empty status.\n",
                    "",
                ),
                "maintainer evaluator lacks initial clean checkout attestation",
            ),
            (
                "late initial clean attestation",
                lambda root: (
                    self.replace_once(
                        root / ".agents/skills/material-review-evaluation/SKILL.md",
                        "2. Immediately capture the active material-review repository's `HEAD` "
                        "and porcelain status. Require an empty status.\n",
                        "",
                    ),
                    self.replace_once(
                        root / ".agents/skills/material-review-evaluation/SKILL.md",
                        "<!-- evaluator-asset-allowlist:end -->",
                        "<!-- evaluator-asset-allowlist:end -->\n\n"
                        "2. Immediately capture the active material-review repository's `HEAD` "
                        "and porcelain status. Require an empty status.",
                    ),
                ),
                "maintainer evaluator clean checkout attestation must precede asset resolution",
            ),
        )
        for label, mutate, expected_error in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_directory:
                fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
                mutate(fixture_root)

                validation_result = self.run_package_validator(
                    fixture_root,
                    distribution_layout=False,
                )

                self.assertNotEqual(validation_result.returncode, 0)
                self.assertIn(expected_error, validation_result.stderr)

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_evaluator_worker_dispatch_requires_empty_history(self) -> None:
        mutations = (
            (
                ".agents/skills/material-review-evaluation/SKILL.md",
                "reviewer_history=none",
                "reviewer_history=bounded",
                "maintainer evaluator dispatch contract must require empty history for reviewers",
            ),
            (
                ".agents/skills/material-review-evaluation/SKILL.md",
                "challenger_history=none",
                "challenger_history=bounded",
                "maintainer evaluator dispatch contract must require empty history for challengers",
            ),
            (
                ".agents/skills/material-review-evaluation/SKILL.md",
                "initial_judge_history=none",
                "initial_judge_history=bounded",
                "maintainer evaluator dispatch contract must require empty history for the initial judge",
            ),
            (
                ".agents/skills/material-review-evaluation/SKILL.md",
                "replacement_judge_history=none",
                "replacement_judge_history=bounded",
                "maintainer evaluator dispatch contract must require empty history for the replacement judge",
            ),
            (
                "evaluations/material-code-review/prompts/reviewer.md",
                "The root dispatcher must provide zero inherited task history.",
                "",
                "reviewer prompt must require zero inherited task history",
            ),
            (
                "evaluations/material-code-review/prompts/challenger.md",
                "The root dispatcher must provide zero inherited task history.",
                "",
                "challenger prompt must require zero inherited task history",
            ),
            (
                "evaluations/material-code-review/prompts/judge.md",
                "The root dispatcher must provide zero inherited task history.",
                "",
                "judge prompt must require zero inherited task history",
            ),
            (
                ".agents/skills/material-review-evaluation/SKILL.md",
                "Immediately before each reviewer, challenger, or judge dispatch, recapture the active "
                "material-review repository's `HEAD` and porcelain status and require an exact "
                "match to the initial clean attestation.",
                "",
                "maintainer evaluator must re-attest the active checkout before every dispatch",
            ),
            (
                ".agents/skills/material-review-evaluation/SKILL.md",
                "Root-side verification is authoritative;",
                "Dispatch verification is shared;",
                "maintainer evaluator dispatch verification must remain root-authoritative",
            ),
            (
                "evaluations/material-code-review/prompts/reviewer.md",
                "Root-side verification of the empty-history host primitive and supplied "
                "allowlist is authoritative; no private dispatch receipt or other private "
                "orchestration data is worker-visible.",
                "Do not proceed if the dispatch receipt does not attest an empty-history host "
                "primitive.",
                "reviewer prompt must keep dispatch verification root-side",
            ),
            (
                "evaluations/material-code-review/prompts/judge.md",
                "Root-side verification of the empty-history host primitive and supplied "
                "allowlist is authoritative; no private dispatch receipt or other private "
                "orchestration data is worker-visible.",
                "Do not proceed if the dispatch receipt does not attest an empty-history host "
                "primitive.",
                "judge prompt must keep dispatch verification root-side",
            ),
            (
                "evaluations/material-code-review/prompts/reviewer.md",
                "Never request or reconstruct parent-task context.",
                "Do not proceed if the dispatch receipt is unavailable. Never request or "
                "reconstruct parent-task context.",
                "reviewer prompt must not require a private dispatch receipt",
            ),
            (
                "evaluations/material-code-review/prompts/judge.md",
                "Never request or reconstruct parent-task context or a prior judge response.",
                "Do not proceed if the dispatch receipt is unavailable. Never request or "
                "reconstruct parent-task context or a prior judge response.",
                "judge prompt must not require a private dispatch receipt",
            ),
        )
        for relative, original, replacement, expected_error in mutations:
            with self.subTest(relative=relative, original=original), tempfile.TemporaryDirectory() as temp_directory:
                fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
                path = fixture_root / relative
                text = path.read_text(encoding="utf-8")
                path.write_text(text.replace(original, replacement, 1), encoding="utf-8")

                validation_result = self.run_package_validator(
                    fixture_root,
                    distribution_layout=False,
                )

                self.assertNotEqual(validation_result.returncode, 0)
                self.assertIn(expected_error, validation_result.stderr)

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_evaluator_reviewer_return_contract_separates_gate_a_and_final_results(
        self,
    ) -> None:
        mutations = (
            (
                "### Gate-A pre-disposition return",
                "### Pre-disposition return",
                "reviewer prompt must define the Gate-A pre-disposition return",
            ),
            (
                "4. `No-mutation attestation` — state that no product edit, repair, or "
                "repository mutation was authorized or performed.\n\n"
                "Do not require or fabricate a plan",
                "4. `No-mutation attestation` — state that no product edit, repair, or "
                "repository mutation was authorized or performed.\n"
                "5. `Plan` — provide a repair plan.\n\n"
                "Do not require or fabricate a plan",
                "reviewer Gate-A pre-disposition return must not require a plan",
            ),
            (
                "### Final return after dispositions",
                "### Return after dispositions",
                "reviewer prompt must define the final return after dispositions",
            ),
            (
                "For `ALL_APPROVED_PLAN` only, also return `Plan`",
                "For every outcome, also return `Plan`",
                "reviewer prompt must limit plan evidence to ALL_APPROVED_PLAN",
            ),
        )
        for original, replacement, expected_error in mutations:
            with self.subTest(original=original), tempfile.TemporaryDirectory() as temp_directory:
                fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
                reviewer_prompt = (
                    fixture_root
                    / "evaluations/material-code-review/prompts/reviewer.md"
                )
                self.replace_once(reviewer_prompt, original, replacement)

                validation_result = self.run_package_validator(
                    fixture_root,
                    distribution_layout=False,
                )

                self.assertNotEqual(validation_result.returncode, 0)
                self.assertIn(expected_error, validation_result.stderr)

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_evaluator_fails_closed_when_context_isolation_is_unavailable(self) -> None:
        mutations = (
            (
                "isolation_unavailable_dispatch=false",
                "isolation_unavailable_dispatch=true",
                "maintainer evaluator isolation failure must not dispatch a worker",
            ),
            (
                "isolation_unverifiable_dispatch=false",
                "isolation_unverifiable_dispatch=true",
                "maintainer evaluator unverifiable isolation must not dispatch a worker",
            ),
            (
                "bounded_nonempty_dispatch=false",
                "bounded_nonempty_dispatch=true",
                "maintainer evaluator bounded non-empty history must not dispatch a worker",
            ),
            (
                "isolation_failure_outcome=INSUFFICIENT_EVIDENCE",
                "isolation_failure_outcome=MATERIAL_TIE",
                "maintainer evaluator isolation failure must produce INSUFFICIENT_EVIDENCE",
            ),
            (
                "isolation_failure_winner=none",
                "isolation_failure_winner=variant-a",
                "maintainer evaluator isolation failure must produce no winner",
            ),
            (
                "isolation_failure_gate_progression=false",
                "isolation_failure_gate_progression=true",
                "maintainer evaluator isolation failure must not progress a user gate",
            ),
            (
                "isolation_failure_repair_publication_egress=false",
                "isolation_failure_repair_publication_egress=true",
                "maintainer evaluator isolation failure must not repair, publish, or egress source",
            ),
        )
        for original, replacement, expected_error in mutations:
            with self.subTest(original=original), tempfile.TemporaryDirectory() as temp_directory:
                fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
                skill = fixture_root / ".agents/skills/material-review-evaluation/SKILL.md"
                text = skill.read_text(encoding="utf-8")
                skill.write_text(text.replace(original, replacement, 1), encoding="utf-8")

                validation_result = self.run_package_validator(
                    fixture_root,
                    distribution_layout=False,
                )

                self.assertNotEqual(validation_result.returncode, 0)
                self.assertIn(expected_error, validation_result.stderr)

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_evaluator_gate_a_disposition_policy_fails_closed(self) -> None:
        mutations = (
            (
                "all_approved=ALL_APPROVED_PLAN",
                "all_approved=DISPOSITION_NONCOMPARABLE",
                "maintainer evaluator all-approved state must retain Gate-B plan capture",
            ),
            (
                "mixed_reject_or_defer=MIXED_DISPOSITIONS_NONCOMPARABLE",
                "mixed_reject_or_defer=ALL_APPROVED_PLAN",
                "maintainer evaluator mixed dispositions must be non-comparable",
            ),
            (
                "zero_approved=NO_APPROVED_FINDINGS",
                "zero_approved=ACCEPTED_EMPTY_LEDGER",
                "maintainer evaluator zero-approved state must preserve native no-approved-findings completion",
            ),
            (
                "accepted_empty=ACCEPTED_EMPTY_LEDGER",
                "accepted_empty=NO_APPROVED_FINDINGS",
                "maintainer evaluator accepted-empty state must remain distinct",
            ),
            (
                "invalid_or_missing=INVALID_OR_MISSING_EVIDENCE",
                "invalid_or_missing=ACCEPTED_EMPTY_LEDGER",
                "maintainer evaluator invalid or missing evidence must remain distinct",
            ),
            (
                "reject_or_defer_policy=DISPOSITION_NONCOMPARABLE",
                "reject_or_defer_policy=COMPARE_PARTIAL",
                "maintainer evaluator rejection or deferral policy must fail closed",
            ),
            (
                "reject_or_defer_outcome=INSUFFICIENT_EVIDENCE",
                "reject_or_defer_outcome=MATERIAL_TIE",
                "maintainer evaluator rejection or deferral must produce INSUFFICIENT_EVIDENCE",
            ),
            (
                "reject_or_defer_plan=false",
                "reject_or_defer_plan=true",
                "maintainer evaluator rejection or deferral must not fabricate a plan",
            ),
            (
                "native_controller_change=false",
                "native_controller_change=true",
                "maintainer evaluator disposition policy must not change the native controller",
            ),
        )
        for original, replacement, expected_error in mutations:
            with self.subTest(original=original), tempfile.TemporaryDirectory() as temp_directory:
                fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
                skill = fixture_root / ".agents/skills/material-review-evaluation/SKILL.md"
                text = skill.read_text(encoding="utf-8")
                skill.write_text(text.replace(original, replacement, 1), encoding="utf-8")

                validation_result = self.run_package_validator(
                    fixture_root,
                    distribution_layout=False,
                )

                self.assertNotEqual(validation_result.returncode, 0)
                self.assertIn(expected_error, validation_result.stderr)

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_evaluator_accepts_only_valid_anonymous_judgment(self) -> None:
        mutations = (
            (
                ".agents/skills/material-review-evaluation/SKILL.md",
                "public_outcomes=VARIANT_A_STRONGER,VARIANT_B_STRONGER,MATERIAL_TIE,INSUFFICIENT_EVIDENCE",
                "public_outcomes=VARIANT_A_STRONGER,VARIANT_B_STRONGER,MATERIAL_TIE,JUDGE_INVALID",
                "maintainer evaluator judge protocol must preserve the four public outcomes",
            ),
            (
                ".agents/skills/material-review-evaluation/SKILL.md",
                "valid_outcome_count=1",
                "valid_outcome_count=2",
                "maintainer evaluator must accept exactly one judge outcome",
            ),
            (
                ".agents/skills/material-review-evaluation/SKILL.md",
                "required_sections=Outcome,Finding comparison,Repair-plan comparison,Limitations and uncertainty,Citations",
                "required_sections=Outcome,Citations",
                "maintainer evaluator must validate every ordered judge section",
            ),
            (
                ".agents/skills/material-review-evaluation/SKILL.md",
                "citations=anonymous-artifacts,frozen-source",
                "citations=anonymous-artifacts",
                "maintainer evaluator must validate anonymous artifact and frozen-source citations",
            ),
            (
                ".agents/skills/material-review-evaluation/SKILL.md",
                "identity_data=forbidden",
                "identity_data=allowed",
                "maintainer evaluator must reject identity-bearing judgment data",
            ),
            (
                ".agents/skills/material-review-evaluation/SKILL.md",
                "judgment_before_mapping=true",
                "judgment_before_mapping=false",
                "maintainer evaluator must write judgment before revealing the private mapping",
            ),
            (
                "evaluations/material-code-review/prompts/judge.md",
                "The root accepts a response only after validating the complete judge protocol.",
                "",
                "judge prompt must require root-side protocol validation",
            ),
        )
        for relative, original, replacement, expected_error in mutations:
            with self.subTest(original=original), tempfile.TemporaryDirectory() as temp_directory:
                fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
                path = fixture_root / relative
                text = path.read_text(encoding="utf-8")
                path.write_text(text.replace(original, replacement, 1), encoding="utf-8")

                validation_result = self.run_package_validator(
                    fixture_root,
                    distribution_layout=False,
                )

                self.assertNotEqual(validation_result.returncode, 0)
                self.assertIn(expected_error, validation_result.stderr)

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_evaluator_judge_failures_are_bounded_and_fail_closed(self) -> None:
        mutations = (
            (
                "max_attempts=2",
                "max_attempts=3",
                "maintainer evaluator judge protocol must allow at most two attempts",
            ),
            (
                "attempt_2_trigger=first-identity-leak-only",
                "attempt_2_trigger=any-invalid-return",
                "maintainer evaluator second judge attempt must be limited to a first identity leak",
            ),
            (
                "other_invalid_first_replacement=false",
                "other_invalid_first_replacement=true",
                "maintainer evaluator must not retry other invalid first judgments",
            ),
            (
                "second_leak_replacement=false",
                "second_leak_replacement=true",
                "maintainer evaluator must not retry a second identity leak",
            ),
            (
                "terminal_outcome=INSUFFICIENT_EVIDENCE",
                "terminal_outcome=MATERIAL_TIE",
                "maintainer evaluator invalid judge terminal must produce INSUFFICIENT_EVIDENCE",
            ),
            (
                "terminal_winner=none",
                "terminal_winner=variant-a",
                "maintainer evaluator invalid judge terminal must produce no winner",
            ),
            (
                "private_terminal_reason=judge-invalid",
                "private_terminal_reason=public-fifth-outcome",
                "maintainer evaluator judge-invalid reason must remain private",
            ),
            (
                "raw_attempts=private-local",
                "raw_attempts=judge-input",
                "maintainer evaluator raw judge attempts must remain private local evidence",
            ),
            (
                "interrupted_run=preserve-and-new-invocation",
                "interrupted_run=resume",
                "maintainer evaluator interrupted runs must not become judge retries",
            ),
            (
                "repair_publication_egress_resume=false",
                "repair_publication_egress_resume=true",
                "maintainer evaluator invalid judge terminal must not repair, publish, egress, or resume",
            ),
        )
        for original, replacement, expected_error in mutations:
            with self.subTest(original=original), tempfile.TemporaryDirectory() as temp_directory:
                fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
                skill = fixture_root / ".agents/skills/material-review-evaluation/SKILL.md"
                text = skill.read_text(encoding="utf-8")
                skill.write_text(text.replace(original, replacement, 1), encoding="utf-8")

                validation_result = self.run_package_validator(
                    fixture_root,
                    distribution_layout=False,
                )

                self.assertNotEqual(validation_result.returncode, 0)
                self.assertIn(expected_error, validation_result.stderr)

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_source_uses_only_prompt_driven_evaluation_surface(self) -> None:
        missing_prompt_sources = [
            relative
            for relative in MAINTAINER_EVALUATOR_PATHS
            if not (REPOSITORY_ROOT / relative).is_file()
        ]
        present_legacy_paths = [
            relative
            for relative in LEGACY_EVALUATOR_PATHS
            if (REPOSITORY_ROOT / relative).exists()
        ]
        makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
        stale_make_tokens = [
            token
            for token in (
                "evaluate-" "review",
                "EVALUATOR_PYTHON",
                "EVALUATOR_WRAPPER",
                "scripts/evaluate_material_review.py",
                "bin/material-review-" "evaluate",
            )
            if token in makefile
        ]

        self.assertEqual(missing_prompt_sources, [])
        self.assertEqual(present_legacy_paths, [])
        self.assertEqual(stale_make_tokens, [])

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_source_validator_requires_prompt_driven_evaluation_sources(self) -> None:
        for relative in MAINTAINER_EVALUATOR_PATHS:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temp_directory:
                fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
                (fixture_root / relative).unlink()

                validation_result = self.run_package_validator(
                    fixture_root,
                    distribution_layout=False,
                )

                self.assertNotEqual(validation_result.returncode, 0)
                self.assertIn(
                    f"missing required file: {relative}",
                    validation_result.stderr,
                )

    def test_retired_evaluator_documents_are_not_source_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))

            for relative in RETIRED_EVALUATOR_DOCUMENTS:
                self.assertFalse((fixture_root / relative).exists(), relative)

            validation_result = self.run_package_validator(
                fixture_root,
                distribution_layout=False,
            )

            self.assertEqual(validation_result.returncode, 0, validation_result.stderr)

    def test_retired_evaluator_document_reactivation_fails(self) -> None:
        inventories = (
            "MAINTAINER_SOURCE_REQUIRED = {\n",
            "EVALUATOR_CONTEXT_FREE_DOCS = (\n",
        )
        for inventory_start in inventories:
            for relative in RETIRED_EVALUATOR_DOCUMENTS:
                with self.subTest(inventory_start=inventory_start, relative=relative), tempfile.TemporaryDirectory() as temp_directory:
                    fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
                    fixture_validator = fixture_root / "scripts" / "validate_package.py"
                    self.replace_once(
                        fixture_validator,
                        inventory_start,
                        f'{inventory_start}    "{relative}",\n',
                    )

                    validation_result = subprocess.run(
                        [
                            sys.executable,
                            "-B",
                            str(fixture_validator),
                            "--package-root",
                            str(fixture_root),
                        ],
                        capture_output=True,
                        text=True,
                        check=False,
                    )

                    self.assertNotEqual(validation_result.returncode, 0)
                    self.assertIn(
                        "retired maintainer-source path reintroduced into active inventory: "
                        f"{relative}",
                        validation_result.stderr,
                    )

    def test_retired_evaluator_documents_remain_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
            initialize_repository_result = subprocess.run(
                ["git", "init", "-q"],
                cwd=fixture_root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                initialize_repository_result.returncode,
                0,
                initialize_repository_result.stderr,
            )
            for relative in RETIRED_EVALUATOR_DOCUMENTS:
                with self.subTest(relative=relative):
                    check_ignore_result = subprocess.run(
                        ["git", "check-ignore", "-v", "--", relative],
                        cwd=fixture_root,
                        capture_output=True,
                        text=True,
                        check=False,
                    )

                    self.assertEqual(check_ignore_result.returncode, 0, check_ignore_result.stderr)
                    matched_rule, ignored_path = check_ignore_result.stdout.rstrip().split("\t", 1)
                    _, _, pattern = matched_rule.rpartition(":")
                    self.assertEqual(ignored_path, relative)
                    self.assertEqual(pattern, "docs/superpowers/")

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_source_validator_validates_prompt_driven_skill_frontmatter(self) -> None:
        mutations = (
            (
                "name: material-review-evaluation",
                "name: renamed-evaluator",
                "maintainer evaluator skill has wrong name",
            ),
            (
                "description: Use when ",
                "description: Compare when ",
                "maintainer evaluator skill description must start with 'Use when '",
            ),
            (
                'argument-hint: "[case:<case-id>] base:<skill-ref> candidate:<skill-ref>"',
                'argument-hint: "left:<skill-ref> right:<skill-ref>"',
                "maintainer evaluator skill has wrong argument hint",
            ),
        )
        for original, replacement, expected_error in mutations:
            with self.subTest(expected_error=expected_error), tempfile.TemporaryDirectory() as temp_directory:
                fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
                skill = fixture_root / ".agents/skills/material-review-evaluation/SKILL.md"
                self.replace_once(skill, original, replacement)

                validation_result = self.run_package_validator(
                    fixture_root,
                    distribution_layout=False,
                )

                self.assertNotEqual(validation_result.returncode, 0)
                self.assertIn(expected_error, validation_result.stderr)

    def test_git_checkout_requires_maintainer_surface_when_all_files_are_missing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
            (fixture_root / ".git").mkdir()
            for relative in (
                ".evaluation-runs",
                ".superpowers",
                "docs/superpowers",
                ".agents/skills/material-review-evaluation",
                "evaluations",
            ):
                path = fixture_root / relative
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)

            validation_result = subprocess.run(
                ["make", "package-check"],
                cwd=fixture_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            self.assertNotEqual(validation_result.returncode, 0)
            self.assertIn(
                "missing required file: .agents/skills/material-review-evaluation/SKILL.md",
                validation_result.stderr,
            )

    def test_archive_validator_rejects_maintainer_only_evaluator_entries(self) -> None:
        archive_cases = (
            (
                "full",
                "--full-archive",
                ".agents/skills/material-review-evaluation/SKILL.md",
                "---\nname: material-review-evaluation\n---\n",
            ),
            (
                "full-noncanonical-dot",
                "--full-archive",
                "./.agents/skills/material-review-evaluation/SKILL.md",
                "---\nname: material-review-evaluation\n---\n",
            ),
            (
                "full-noncanonical-slash",
                "--full-archive",
                ".agents//skills/material-review-evaluation/SKILL.md",
                "---\nname: material-review-evaluation\n---\n",
            ),
            (
                "full-noncanonical-backslash",
                "--full-archive",
                ".agents\\skills\\material-review-evaluation\\SKILL.md",
                "---\nname: material-review-evaluation\n---\n",
            ),
            (
                "full-retired-document",
                "--full-archive",
                RETIRED_EVALUATOR_DOCUMENTS[0],
                "retired maintainer document\n",
            ),
            (
                "standalone-retired-document",
                "--standalone-archive",
                RETIRED_EVALUATOR_DOCUMENTS[0],
                "retired maintainer document\n",
            ),
        )
        for label, archive_flag, entry, contents in archive_cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_directory:
                temp_root = Path(temp_directory)
                fixture_root = self.create_full_plugin_fixture(temp_root)
                full_output = temp_root / "full-plugin.zip"
                standalone_output = temp_root / "material-review.zip"
                package_result = self.run_full_packager(
                    fixture_root,
                    full_output,
                    standalone_output=standalone_output,
                )
                self.assertEqual(package_result.returncode, 0, package_result.stderr)
                output = full_output if archive_flag == "--full-archive" else standalone_output
                with zipfile.ZipFile(output, "a") as archive:
                    archive.writestr(entry, contents)

                validation_result = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(PACKAGE_VALIDATOR),
                        "--package-root",
                        str(fixture_root),
                        *(["--distribution-layout"] if DISTRIBUTION_LAYOUT else []),
                        archive_flag,
                        str(output),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )

                self.assertNotEqual(validation_result.returncode, 0)
                expected_error = (
                    "forbidden maintainer-only archive entry"
                    if entry.startswith((".agents/skills/", "docs/superpowers/"))
                    else "noncanonical archive path"
                )
                self.assertIn(expected_error, validation_result.stderr)

    def test_full_archive_excludes_maintainer_evaluation_and_keeps_marketplace(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            output = temp_root / "full-plugin.zip"

            package_result = self.run_full_packager(fixture_root, output)

            self.assertEqual(package_result.returncode, 0, package_result.stderr)
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
            self.assertNotIn(
                ".agents/skills/material-review-evaluation/SKILL.md",
                names,
            )
            self.assertFalse(any(name.startswith("evaluations/") for name in names))
            self.assertFalse(any(name.startswith(".evaluation-runs/") for name in names))
            self.assertIn(".agents/plugins/marketplace.json", names)
            for relative in LEGACY_EVALUATOR_PATHS:
                self.assertFalse(
                    any(
                        name == relative or name.startswith(f"{relative}/")
                        for name in names
                    ),
                    relative,
                )

    def test_every_archive_excludes_maintainer_only_plans_and_evaluations(
        self,
    ) -> None:
        forbidden_prefixes = (
            "docs/superpowers/",
            ".agents/skills/material-review-evaluation/",
            "evaluations/",
        )
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            _, full_archive, review_archive = self.build_review_archives(
                temp_root,
                fixture_root,
            )
            simplification_archive = temp_root / "simplification.zip"
            result = self.run_packager(fixture_root, simplification_archive)
            self.assertEqual(result.returncode, 0, result.stderr)

            for archive_path in (
                full_archive,
                review_archive,
                simplification_archive,
            ):
                with self.subTest(archive=archive_path.name), zipfile.ZipFile(
                    archive_path
                ) as archive:
                    names = archive.namelist()
                    for prefix in forbidden_prefixes:
                        self.assertFalse(
                            any(name.startswith(prefix) for name in names),
                            f"{archive_path.name} contains {prefix}",
                        )

    def test_review_layout_manifest_matches_packager(self) -> None:
        self.assertTrue(
            REVIEW_LAYOUT_MANIFEST.is_file(),
            "material-review packaging requires a canonical layout manifest",
        )
        expected_manifest = self.expected_review_layout_manifest(REPOSITORY_ROOT)
        actual_manifest = json.loads(REVIEW_LAYOUT_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(actual_manifest, expected_manifest)

        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            ancillary_source = (
                fixture_root
                / "skills/material-code-review/examples/allowed-ancillary.md"
            )
            ancillary_source.write_text("safe ancillary content\n", encoding="utf-8")
            manifest, full_archive, standalone_archive = self.build_review_archives(
                temp_root,
                fixture_root,
            )

            for layout_name, archive_path, ancillary_destination in (
                (
                    "full-plugin",
                    full_archive,
                    "skills/material-code-review/examples/allowed-ancillary.md",
                ),
                ("standalone", standalone_archive, "examples/allowed-ancillary.md"),
            ):
                with self.subTest(layout=layout_name), zipfile.ZipFile(
                    archive_path
                ) as archive:
                    names = set(archive.namelist())
                    layout = manifest["layouts"][layout_name]
                    required = {
                        mapping["destination"]
                        for mapping in layout["required_mappings"]
                    }
                    self.assertTrue(required.issubset(names), sorted(required - names))
                    self.assertIn(ancillary_destination, names)

                validation_result = self.run_review_archive_validator(
                    fixture_root,
                    archive_path,
                    standalone=layout_name == "standalone",
                )
                self.assertEqual(
                    validation_result.returncode,
                    0,
                    validation_result.stderr,
                )

    def test_review_layout_manifest_rejects_invalid_mapping(self) -> None:
        cases = [
            (
                "absent",
                "full-plugin",
                {
                    "source": "skills/material-code-review/missing-contract.txt",
                    "destination": "skills/material-code-review/missing-contract.txt",
                },
                "required source is missing: "
                "skills/material-code-review/missing-contract.txt",
            ),
            (
                "unsafe",
                "standalone",
                {
                    "source": "skills/material-code-review/examples/README.md",
                    "destination": "../escape.md",
                },
                "unsafe manifest destination: ../escape.md",
            ),
            (
                "duplicate",
                "full-plugin",
                None,
                "duplicate manifest source: .agents/plugins/marketplace.json",
            ),
            (
                "maintainer-only",
                "standalone",
                {
                    "source": "evaluations/f004-maintainer-only.txt",
                    "destination": "evaluations/f004-maintainer-only.txt",
                },
                "maintainer-only manifest mapping: evaluations/f004-maintainer-only.txt "
                "-> evaluations/f004-maintainer-only.txt",
            ),
            (
                "unmappable",
                "standalone",
                {
                    "source": "skills/material-code-review/examples/README.md",
                    "destination": "references/not-the-generated-destination.md",
                },
                "manifest mapping is not generated: "
                "skills/material-code-review/examples/README.md -> "
                "references/not-the-generated-destination.md",
            ),
            (
                "excluded",
                "standalone",
                {
                    "source": "skills/material-code-review/examples/excluded-contract.zip",
                    "destination": "examples/excluded-contract.zip",
                },
                "excluded manifest mapping: "
                "skills/material-code-review/examples/excluded-contract.zip -> "
                "examples/excluded-contract.zip",
            ),
            (
                "duplicate-destination",
                "standalone",
                {
                    "source": "skills/material-code-review/examples/README.md",
                    "destination": "SKILL.md",
                },
                "duplicate manifest destination: SKILL.md",
            ),
        ]
        if not sys.platform.startswith("win"):
            cases.append(
                (
                    "symlink-source",
                    "standalone",
                    {
                        "source": "skills/material-code-review/examples/symlink-contract.md",
                        "destination": "examples/symlink-contract.md",
                    },
                    "required source must not be a symlink: "
                    "skills/material-code-review/examples/symlink-contract.md",
                )
            )
        for label, layout_name, mapping, expected_error in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temp_directory:
                temp_root = Path(temp_directory)
                fixture_root = self.create_full_plugin_fixture(temp_root)
                maintainer_source = fixture_root / "evaluations/f004-maintainer-only.txt"
                maintainer_source.parent.mkdir(parents=True, exist_ok=True)
                maintainer_source.write_text("maintainer only\n", encoding="utf-8")
                excluded_source = (
                    fixture_root
                    / "skills/material-code-review/examples/excluded-contract.zip"
                )
                excluded_source.write_bytes(b"excluded archive input")
                symlink_target = temp_root / "symlink-target.md"
                symlink_target.write_text("external target\n", encoding="utf-8")
                if not sys.platform.startswith("win"):
                    (
                        fixture_root
                        / "skills/material-code-review/examples/symlink-contract.md"
                    ).symlink_to(symlink_target)
                manifest = self.expected_review_layout_manifest(fixture_root)
                required_mappings = manifest["layouts"][layout_name][
                    "required_mappings"
                ]
                required_mappings.append(
                    dict(required_mappings[0]) if mapping is None else mapping
                )
                self.write_review_layout_manifest(fixture_root, manifest)

                full_output = temp_root / "full-plugin.zip"
                standalone_output = temp_root / "material-review.zip"
                full_output.write_bytes(b"existing full archive")
                standalone_output.write_bytes(b"existing standalone archive")
                full_checksum = full_output.with_suffix(".zip.sha256")
                standalone_checksum = standalone_output.with_suffix(".zip.sha256")
                full_checksum.write_bytes(b"existing full checksum")
                standalone_checksum.write_bytes(b"existing standalone checksum")
                result = self.run_full_packager(
                    fixture_root,
                    full_output,
                    standalone_output=standalone_output,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"[FAIL] {expected_error}\n", result.stderr)
                self.assertEqual(full_output.read_bytes(), b"existing full archive")
                self.assertEqual(
                    standalone_output.read_bytes(),
                    b"existing standalone archive",
                )
                self.assertEqual(
                    full_checksum.read_bytes(),
                    b"existing full checksum",
                )
                self.assertEqual(
                    standalone_checksum.read_bytes(),
                    b"existing standalone checksum",
                )

    def test_review_archives_reject_each_missing_required_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            manifest, full_archive, standalone_archive = self.build_review_archives(
                temp_root,
                fixture_root,
            )
            for layout_name, source_archive, standalone in (
                ("full-plugin", full_archive, False),
                ("standalone", standalone_archive, True),
            ):
                mappings = manifest["layouts"][layout_name]["required_mappings"]
                for index, mapping in enumerate(mappings):
                    destination = mapping["destination"]
                    with self.subTest(layout=layout_name, member=destination):
                        incomplete_archive = (
                            temp_root / f"{layout_name}-missing-{index:03d}.zip"
                        )
                        self.remove_archive_entry(
                            source_archive,
                            incomplete_archive,
                            destination,
                        )
                        result = self.run_review_archive_validator(
                            fixture_root,
                            incomplete_archive,
                            standalone=standalone,
                        )
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(
                            f"{incomplete_archive.name}: missing archive entry {destination}",
                            result.stderr,
                        )

    def test_review_archive_validation_enforces_bounded_zip_policy_before_reads(self) -> None:
        def rewrite_central_sizes(
            source: Path,
            destination: Path,
            replacements: dict[str, tuple[int, int]],
        ) -> None:
            payload = bytearray(source.read_bytes())
            signature = b"PK\x01\x02"
            cursor = 0
            replaced: set[str] = set()
            while True:
                offset = payload.find(signature, cursor)
                if offset < 0:
                    break
                filename_size = int.from_bytes(payload[offset + 28 : offset + 30], "little")
                extra_size = int.from_bytes(payload[offset + 30 : offset + 32], "little")
                comment_size = int.from_bytes(payload[offset + 32 : offset + 34], "little")
                filename_start = offset + 46
                filename_end = filename_start + filename_size
                filename = bytes(payload[filename_start:filename_end]).decode("utf-8")
                if filename in replacements:
                    compressed_size, expanded_size = replacements[filename]
                    payload[offset + 20 : offset + 24] = compressed_size.to_bytes(4, "little")
                    payload[offset + 24 : offset + 28] = expanded_size.to_bytes(4, "little")
                    replaced.add(filename)
                cursor = filename_end + extra_size + comment_size
            self.assertEqual(replaced, set(replacements))
            destination.write_bytes(payload)

        spec = importlib.util.spec_from_file_location(
            "bounded_review_archive_validator",
            PACKAGE_VALIDATOR,
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        self.assertEqual(validator.MAX_ARCHIVE_MEMBERS, 10_000)
        self.assertEqual(validator.MAX_ARCHIVE_MEMBER_SIZE, 100 * 1024 * 1024)
        self.assertEqual(
            validator.MAX_ARCHIVE_CUMULATIVE_SIZE,
            500 * 1024 * 1024,
        )
        self.assertEqual(validator.MAX_ARCHIVE_COMPRESSION_RATIO, 100)

        class LyingArchive:
            def getinfo(self, name: str) -> str:
                return name

            def open(self, _member: str, _mode: str) -> io.BytesIO:
                return io.BytesIO(b"123456789")

        with mock.patch.object(validator, "MAX_ARCHIVE_MEMBER_SIZE", 8):
            with self.assertRaisesRegex(
                validator.ArchiveResourceError,
                "exceeds bounded read limit",
            ):
                validator.read_bounded_archive_member(
                    LyingArchive(),
                    "lying-member.bin",
                    "lying.zip",
                )

        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            _, full_archive, standalone_archive = self.build_review_archives(
                temp_root,
                fixture_root,
            )

            for layout_name, source_archive, standalone in (
                ("full", full_archive, False),
                ("standalone", standalone_archive, True),
            ):
                with self.subTest(layout=layout_name, state="normal"):
                    result = self.run_review_archive_validator(
                        fixture_root,
                        source_archive,
                        standalone=standalone,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)

                binary_archive = temp_root / f"{layout_name}-binary.zip"
                shutil.copy2(source_archive, binary_archive)
                self.ensure_archive_entry(
                    binary_archive,
                    "ancillary/random.bin",
                    b"\xff\x00\xfe\x01" * 64,
                )
                with self.subTest(layout=layout_name, state="binary-in-limit"):
                    result = self.run_review_archive_validator(
                        fixture_root,
                        binary_archive,
                        standalone=standalone,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)

                with zipfile.ZipFile(source_archive) as archive:
                    regular_names = [
                        member.filename
                        for member in archive.infolist()
                        if not member.filename.endswith("/")
                    ]
                self.assertGreaterEqual(len(regular_names), 6)
                metadata_cases = (
                    (
                        "member-size",
                        {regular_names[0]: (1, 100 * 1024 * 1024 + 1)},
                        "exceeds maximum size",
                    ),
                    (
                        "cumulative-size",
                        {
                            name: (90 * 1024 * 1024, 90 * 1024 * 1024)
                            for name in regular_names[:6]
                        },
                        "cumulative expanded size exceeds maximum",
                    ),
                    (
                        "ratio",
                        {regular_names[0]: (1, 101)},
                        "compression ratio exceeds maximum",
                    ),
                    (
                        "zero-compressed",
                        {regular_names[0]: (0, 1)},
                        "has zero compressed size",
                    ),
                )
                for case_name, replacements, expected_error in metadata_cases:
                    with self.subTest(layout=layout_name, state=case_name):
                        malformed = temp_root / f"{layout_name}-{case_name}.zip"
                        rewrite_central_sizes(
                            source_archive,
                            malformed,
                            replacements,
                        )
                        result = self.run_review_archive_validator(
                            fixture_root,
                            malformed,
                            standalone=standalone,
                        )
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(expected_error, result.stderr)
                        self.assertNotIn("missing archive entry", result.stderr)

                member_count_archive = temp_root / f"{layout_name}-member-count.zip"
                with zipfile.ZipFile(member_count_archive, "w") as archive:
                    for index in range(10_001):
                        archive.writestr(f"empty-{index:05d}/", b"")
                with self.subTest(layout=layout_name, state="member-count"):
                    result = self.run_review_archive_validator(
                        fixture_root,
                        member_count_archive,
                        standalone=standalone,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("exceeds maximum member count of 10000", result.stderr)
                    self.assertNotIn("missing archive entry", result.stderr)

                manifest_entry = (
                    "package-layouts.json"
                    if standalone
                    else "skills/material-code-review/package-layouts.json"
                )
                malformed_text_archive = temp_root / f"{layout_name}-malformed-text.zip"
                self.rewrite_archive_entry(
                    source_archive,
                    malformed_text_archive,
                    manifest_entry,
                    b'{"schema_version":',
                )
                with self.subTest(layout=layout_name, state="semantic-after-preflight"):
                    result = self.run_review_archive_validator(
                        fixture_root,
                        malformed_text_archive,
                        standalone=standalone,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(
                        "archived package layout manifest has invalid JSON",
                        result.stderr,
                    )
                    self.assertNotIn("maximum", result.stderr)

    def test_full_plugin_manifest_requires_complete_simplification_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            manifest, full_archive, standalone_archive = self.build_review_archives(
                temp_root, fixture_root
            )
            simplification_sources = {
                path.relative_to(fixture_root).as_posix()
                for path in (
                    fixture_root / "skills/material-code-simplification"
                ).rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and "__pycache__" not in path.parts
                and path.suffix not in {".pyc", ".pyo"}
            }
            simplification_sources.add("scripts/package_simplification_skill.py")
            full_mappings = manifest["layouts"]["full-plugin"]["required_mappings"]
            mapped = {
                mapping["source"]: mapping["destination"]
                for mapping in full_mappings
            }
            self.assertEqual(
                {source: mapped.get(source) for source in simplification_sources},
                {source: source for source in simplification_sources},
            )

            source_validation = self.run_package_validator(fixture_root)
            self.assertEqual(source_validation.returncode, 0, source_validation.stderr)
            archive_validation = self.run_review_archive_validator(
                fixture_root, full_archive, standalone=False
            )
            self.assertEqual(
                archive_validation.returncode, 0, archive_validation.stderr
            )

            for index, destination in enumerate(sorted(simplification_sources)):
                with self.subTest(missing=destination):
                    incomplete = temp_root / f"missing-simplification-{index:02d}.zip"
                    self.remove_archive_entry(
                        full_archive, incomplete, destination
                    )
                    result = self.run_review_archive_validator(
                        fixture_root, incomplete, standalone=False
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(
                        f"missing archive entry {destination}", result.stderr
                    )

            with zipfile.ZipFile(standalone_archive) as archive:
                self.assertFalse(
                    any(
                        name.startswith("skills/material-code-simplification/")
                        for name in archive.namelist()
                    )
                )
            simplification_archive = temp_root / "simplification.zip"
            simplification_result = self.run_packager(
                fixture_root, simplification_archive
            )
            self.assertEqual(
                simplification_result.returncode, 0, simplification_result.stderr
            )
            simplification_validation = self.run_simplification_archive_validator(
                simplification_archive
            )
            self.assertEqual(
                simplification_validation.returncode,
                0,
                simplification_validation.stderr,
            )

        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            manifest = self.expected_review_layout_manifest(fixture_root)
            self.write_review_layout_manifest(fixture_root, manifest)
            missing_source = fixture_root / "skills/material-code-simplification/SKILL.md"
            missing_source.unlink()
            full_output = temp_root / "full.zip"
            standalone_output = temp_root / "standalone.zip"
            destinations = (
                full_output,
                full_output.with_suffix(".zip.sha256"),
                standalone_output,
                standalone_output.with_suffix(".zip.sha256"),
            )
            for index, destination in enumerate(destinations):
                destination.write_bytes(f"sentinel-{index}".encode("utf-8"))
            result = self.run_full_packager(
                fixture_root,
                full_output,
                standalone_output=standalone_output,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "required source is missing: skills/material-code-simplification/SKILL.md",
                result.stderr,
            )
            for index, destination in enumerate(destinations):
                self.assertEqual(
                    destination.read_bytes(), f"sentinel-{index}".encode("utf-8")
                )

    def test_review_archives_reject_missing_materiality_and_adjudication_contracts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            _, full_archive, standalone_archive = self.build_review_archives(
                temp_root,
                fixture_root,
            )
            suffixes = (
                "references/materiality-rubric.md",
                "schemas/adjudication.schema.json",
                "schemas/adjudication-v4.schema.json",
                "tests/fixtures/reviewctl_1_2_compat.py",
            )
            for layout_name, source_archive, standalone, prefix in (
                (
                    "full-plugin",
                    full_archive,
                    False,
                    "skills/material-code-review/",
                ),
                ("standalone", standalone_archive, True, ""),
            ):
                for index, suffix in enumerate(suffixes):
                    destination = f"{prefix}{suffix}"
                    with self.subTest(layout=layout_name, member=destination):
                        incomplete_archive = (
                            temp_root
                            / f"{layout_name}-missing-contract-{index:02d}.zip"
                        )
                        self.remove_archive_entry(
                            source_archive,
                            incomplete_archive,
                            destination,
                        )
                        result = self.run_review_archive_validator(
                            fixture_root,
                            incomplete_archive,
                            standalone=standalone,
                        )
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(
                            f"{incomplete_archive.name}: missing archive entry {destination}",
                            result.stderr,
                        )

    def test_review_archive_reference_closure_uses_archived_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            manifest, full_archive, standalone_archive = self.build_review_archives(
                temp_root,
                fixture_root,
            )
            trusted_manifest = json.loads(
                (
                    fixture_root
                    / REVIEW_LAYOUT_MANIFEST.relative_to(REPOSITORY_ROOT)
                ).read_text(encoding="utf-8")
            )
            for layout_name, source_archive, standalone, manifest_entry in (
                (
                    "full-plugin",
                    full_archive,
                    False,
                    "skills/material-code-review/package-layouts.json",
                ),
                ("standalone", standalone_archive, True, "package-layouts.json"),
            ):
                malformed_archive = (
                    temp_root / f"{layout_name}-malformed-archived-manifest.zip"
                )
                self.rewrite_archive_entry(
                    source_archive,
                    malformed_archive,
                    manifest_entry,
                    b'{"schema_version":',
                )
                with self.subTest(layout=layout_name, manifest="malformed"):
                    malformed_result = self.run_review_archive_validator(
                        fixture_root,
                        malformed_archive,
                        standalone=standalone,
                    )
                    self.assertNotEqual(malformed_result.returncode, 0)
                    self.assertIn(
                        f"{malformed_archive.name}: archived package layout manifest "
                        "has invalid JSON",
                        malformed_result.stderr,
                    )

                unsafe_malformed_archive = (
                    temp_root
                    / f"{layout_name}-unsafe-before-malformed-manifest.zip"
                )
                shutil.copy2(malformed_archive, unsafe_malformed_archive)
                with zipfile.ZipFile(unsafe_malformed_archive, "a") as archive:
                    archive.writestr("../escape-before-manifest.txt", "unsafe")
                with self.subTest(layout=layout_name, manifest="unsafe-first"):
                    unsafe_result = self.run_review_archive_validator(
                        fixture_root,
                        unsafe_malformed_archive,
                        standalone=standalone,
                    )
                    self.assertNotEqual(unsafe_result.returncode, 0)
                    self.assertIn("unsafe archive path", unsafe_result.stderr)
                    self.assertNotIn(
                        "archived package layout manifest has invalid JSON",
                        unsafe_result.stderr,
                    )

                weakened_manifest = json.loads(json.dumps(trusted_manifest))
                mappings = weakened_manifest["layouts"][layout_name][
                    "required_mappings"
                ]
                compatibility_destination = (
                    "skills/material-code-review/tests/fixtures/"
                    "reviewctl_1_2_compat.py"
                    if layout_name == "full-plugin"
                    else "tests/fixtures/reviewctl_1_2_compat.py"
                )
                weakened_manifest["layouts"][layout_name]["required_mappings"] = [
                    mapping
                    for mapping in mappings
                    if mapping["destination"] != compatibility_destination
                ]
                self.assertEqual(
                    len(mappings)
                    - len(
                        weakened_manifest["layouts"][layout_name][
                            "required_mappings"
                        ]
                    ),
                    1,
                )
                weakened_archive = (
                    temp_root / f"{layout_name}-weakened-archived-manifest.zip"
                )
                self.rewrite_archive_entry(
                    source_archive,
                    weakened_archive,
                    manifest_entry,
                    (
                        json.dumps(weakened_manifest, indent=2, sort_keys=True)
                        + "\n"
                    ).encode("utf-8"),
                )
                with self.subTest(layout=layout_name, manifest="weakened-compat"):
                    weakened_result = self.run_review_archive_validator(
                        fixture_root,
                        weakened_archive,
                        standalone=standalone,
                    )
                    self.assertNotEqual(weakened_result.returncode, 0)
                    self.assertIn(
                        f"{weakened_archive.name}: archived package layout manifest "
                        "differs from trusted source contract",
                        weakened_result.stderr,
                    )

            reference = "references/archive-only-contract.md"
            for layout_name, source_archive, standalone in (
                ("full-plugin", full_archive, False),
                ("standalone", standalone_archive, True),
            ):
                layout = manifest["layouts"][layout_name]
                skill_entry = layout["canonical_skill"]
                reference_entry = (
                    (Path(skill_entry).parent / reference).as_posix()
                    if Path(skill_entry).parent != Path(".")
                    else reference
                )
                with zipfile.ZipFile(source_archive) as archive:
                    archived_skill = archive.read(skill_entry)
                mutated_skill = (
                    archived_skill
                    + f"\nArchived-only closure probe: `{reference}`.\n".encode("utf-8")
                )
                missing_reference_archive = (
                    temp_root / f"{layout_name}-archived-skill-missing-reference.zip"
                )
                self.rewrite_archive_entry(
                    source_archive,
                    missing_reference_archive,
                    skill_entry,
                    mutated_skill,
                )

                missing_result = self.run_review_archive_validator(
                    fixture_root,
                    missing_reference_archive,
                    standalone=standalone,
                )
                self.assertNotEqual(missing_result.returncode, 0)
                self.assertIn(
                    f"archived SKILL references missing entry {reference_entry}",
                    missing_result.stderr,
                )

                present_reference_archive = (
                    temp_root / f"{layout_name}-archived-skill-with-reference.zip"
                )
                shutil.copy2(missing_reference_archive, present_reference_archive)
                self.ensure_archive_entry(
                    present_reference_archive,
                    reference_entry,
                    b"archive-only reference\n",
                )
                present_result = self.run_review_archive_validator(
                    fixture_root,
                    present_reference_archive,
                    standalone=standalone,
                )
                self.assertEqual(
                    present_result.returncode,
                    0,
                    present_result.stderr,
                )

    def test_full_packager_is_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            self.write_review_layout_manifest(fixture_root)
            ancillary_source = (
                fixture_root
                / "skills/material-code-review/examples/reproducible-ancillary.md"
            )
            ancillary_source.write_text("reproducible ancillary\n", encoding="utf-8")
            first_full = temp_root / "first-full.zip"
            first_standalone = temp_root / "first-standalone.zip"
            second_full = temp_root / "second-full.zip"
            second_standalone = temp_root / "second-standalone.zip"

            first_result = self.run_full_packager(
                fixture_root,
                first_full,
                standalone_output=first_standalone,
            )
            second_result = self.run_full_packager(
                fixture_root,
                second_full,
                standalone_output=second_standalone,
            )
            self.assertEqual(first_result.returncode, 0, first_result.stderr)
            self.assertEqual(second_result.returncode, 0, second_result.stderr)

            for first, second, manifest_entry in (
                (
                    first_full,
                    second_full,
                    "skills/material-code-review/package-layouts.json",
                ),
                (first_standalone, second_standalone, "package-layouts.json"),
            ):
                with self.subTest(archive=first.name):
                    self.assertEqual(first.read_bytes(), second.read_bytes())
                    with zipfile.ZipFile(first) as first_archive, zipfile.ZipFile(
                        second
                    ) as second_archive:
                        first_info = first_archive.infolist()
                        second_info = second_archive.infolist()
                        self.assertEqual(
                            [member.filename for member in first_info],
                            sorted(member.filename for member in first_info),
                        )
                        self.assertEqual(
                            [
                                (
                                    member.filename,
                                    member.date_time,
                                    member.external_attr,
                                )
                                for member in first_info
                            ],
                            [
                                (
                                    member.filename,
                                    member.date_time,
                                    member.external_attr,
                                )
                                for member in second_info
                            ],
                        )
                        self.assertIn(manifest_entry, first_archive.namelist())

    def test_review_archives_ship_obligation_coverage_contract(self) -> None:
        source_root = REPOSITORY_ROOT / "skills" / "material-code-review"
        source_candidate = (source_root / "schemas/candidate-set-v6.schema.json").read_bytes()
        source_legacy_candidate = (
            source_root / "schemas/candidate-set-v5.schema.json"
        ).read_bytes()
        source_coverage = (source_root / "schemas/coverage-plan-v5.schema.json").read_bytes()
        source_legacy_coverage = (
            source_root / "schemas/coverage-plan-v4.schema.json"
        ).read_bytes()
        source_helper = (source_root / "scripts/obligation_contract.py").read_bytes()
        candidate_schema = json.loads(source_candidate)
        coverage_schema = json.loads(source_coverage)
        self.assertEqual(
            candidate_schema["$defs"]["repositoryRelativeGitPath"],
            coverage_schema["$defs"]["repositoryRelativeGitPath"],
        )
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            _, full_output, standalone_output = self.build_review_archives(
                temp_root, fixture_root
            )
            expected_suffixes = {
                "references/review-obligations.md",
                "schemas/coverage-plan-v2.schema.json",
                "schemas/coverage-plan-v3.schema.json",
                "schemas/coverage-plan-v4.schema.json",
                "schemas/coverage-plan-v5.schema.json",
                "schemas/candidate-set-v3.schema.json",
                "schemas/candidate-set-v4.schema.json",
                "schemas/candidate-set-v5.schema.json",
                "schemas/candidate-set-v6.schema.json",
                "scripts/package_layout_contract.py",
                "scripts/obligation_contract.py",
                "tests/fixtures/obligation-corpus.json",
                "tests/fixtures/reviewctl_1_3_compat.py",
                "tests/fixtures/reviewctl_1_4_compat.py",
                "tests/fixtures/reviewctl_1_5_compat.py",
                "tests/fixtures/reviewctl_1_6_compat.py",
                "tests/test_obligation_contract.py",
                "tests/test_obligation_corpus.py",
            }
            for archive_path, prefix in (
                (full_output, "skills/material-code-review/"),
                (standalone_output, ""),
            ):
                with self.subTest(archive=archive_path.name), zipfile.ZipFile(
                    archive_path
                ) as archive:
                    names = set(archive.namelist())
                    self.assertTrue(
                        {f"{prefix}{suffix}" for suffix in expected_suffixes}.issubset(names)
                    )
                    self.assertEqual(
                        archive.read(f"{prefix}schemas/candidate-set-v6.schema.json"),
                        source_candidate,
                    )
                    self.assertEqual(
                        archive.read(f"{prefix}schemas/candidate-set-v5.schema.json"),
                        source_legacy_candidate,
                    )
                    self.assertEqual(
                        archive.read(f"{prefix}schemas/coverage-plan-v5.schema.json"),
                        source_coverage,
                    )
                    self.assertEqual(
                        archive.read(f"{prefix}schemas/coverage-plan-v4.schema.json"),
                        source_legacy_coverage,
                    )
                    self.assertEqual(
                        archive.read(f"{prefix}scripts/obligation_contract.py"),
                        source_helper,
                    )
    def test_shared_controller_dependency_ships_in_every_runtime_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            _, full_archive, review_archive = self.build_review_archives(
                temp_root,
                fixture_root,
            )
            simplification_archive = temp_root / "simplification.zip"
            result = self.run_packager(fixture_root, simplification_archive)
            self.assertEqual(result.returncode, 0, result.stderr)

            expected = {
                full_archive: "skills/material-code-review/scripts/obligation_contract.py",
                review_archive: "scripts/obligation_contract.py",
                simplification_archive: "core/obligation_contract.py",
            }
            for archive_path, member in expected.items():
                with self.subTest(archive=archive_path.name), zipfile.ZipFile(
                    archive_path
                ) as archive:
                    self.assertIn(member, archive.namelist())

    def test_new_contract_files_are_required_not_incidental(self) -> None:
        manifest = json.loads(REVIEW_LAYOUT_MANIFEST.read_text(encoding="utf-8"))
        suffixes = {
            "references/review-obligations.md",
            "schemas/coverage-plan-v2.schema.json",
            "schemas/coverage-plan-v3.schema.json",
            "schemas/coverage-plan-v4.schema.json",
            "schemas/coverage-plan-v5.schema.json",
            "schemas/candidate-set-v3.schema.json",
            "schemas/candidate-set-v4.schema.json",
            "schemas/candidate-set-v5.schema.json",
            "schemas/candidate-set-v6.schema.json",
            "scripts/package_layout_contract.py",
            "scripts/obligation_contract.py",
            "tests/fixtures/obligation-corpus.json",
            "tests/fixtures/reviewctl_1_3_compat.py",
            "tests/fixtures/reviewctl_1_4_compat.py",
            "tests/fixtures/reviewctl_1_5_compat.py",
            "tests/fixtures/reviewctl_1_6_compat.py",
            "tests/test_obligation_contract.py",
            "tests/test_obligation_corpus.py",
        }
        for layout_name, prefix in (
            ("full-plugin", "skills/material-code-review/"),
            ("standalone", ""),
        ):
            destinations = {
                item["destination"]
                for item in manifest["layouts"][layout_name]["required_mappings"]
            }
            with self.subTest(layout=layout_name):
                self.assertTrue(
                    {f"{prefix}{suffix}" for suffix in suffixes}.issubset(destinations)
                )
        full_destinations = {
            item["destination"]
            for item in manifest["layouts"]["full-plugin"]["required_mappings"]
        }
        self.assertIn("scripts/package_publication.py", full_destinations)

    def test_extracted_full_archive_runs_retained_validation_surface(self) -> None:
        if DISTRIBUTION_LAYOUT:
            for relative in (
                "bin/material-review-" "evaluate",
                "scripts/evaluate_material_review.py",
                "scripts/material_review_" "evaluation",
                "scripts/tests/test_evaluate_material_review.py",
                "evaluations",
            ):
                self.assertFalse((REPOSITORY_ROOT / relative).exists(), relative)
            validation_result = self.run_package_validator(
                REPOSITORY_ROOT,
                distribution_layout=True,
            )
            self.assertEqual(
                validation_result.returncode,
                0,
                validation_result.stderr,
            )
            return

        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            _, archive_path, standalone_archive = self.build_review_archives(
                temp_root,
                fixture_root,
            )
            extracted_root = temp_root / "extracted"
            self.extract_archive_with_modes(archive_path, extracted_root)
            standalone_root = temp_root / "standalone-extracted"
            self.extract_archive_with_modes(standalone_archive, standalone_root)

            for relative in (
                "bin/material-review-" "evaluate",
                "scripts/evaluate_material_review.py",
                "scripts/material_review_" "evaluation",
                "scripts/tests/test_evaluate_material_review.py",
                "evaluations",
            ):
                self.assertFalse((extracted_root / relative).exists(), relative)

            validation_result = subprocess.run(
                ["make", "package-check"],
                cwd=extracted_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            self.assertEqual(
                validation_result.returncode,
                0,
                validation_result.stdout + validation_result.stderr,
            )
            self.assertIn(
                "material-code-review package 1.7.0 is structurally valid",
                validation_result.stdout,
            )
            targeted_test_result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "unittest",
                    "scripts.tests.test_packaging.StandalonePackagingTests."
                    "test_archive_validator_rejects_unsafe_and_incomplete_archives",
                    "scripts.tests.test_packaging.StandalonePackagingTests."
                    "test_source_validator_requires_prompt_driven_evaluation_sources",
                    "-v",
                ],
                cwd=extracted_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            combined_output = targeted_test_result.stdout + targeted_test_result.stderr
            self.assertEqual(targeted_test_result.returncode, 0, combined_output)
            self.assertIn(
                "test_archive_validator_rejects_unsafe_and_incomplete_archives",
                combined_output,
            )
            self.assertRegex(
                combined_output,
                r"test_source_validator_requires_prompt_driven_evaluation_sources .* skipped ",
            )

            expected_full_validator = (
                "skills/material-code-review/scripts/validate_package.py"
            )
            expected_full_manifest = (
                "skills/material-code-review/package-layouts.json"
            )
            relocation_cases = (
                (
                    "missing-validator",
                    "remove",
                    expected_full_validator,
                    "package layout full-plugin does not map its validator to "
                    f"{expected_full_validator}",
                    True,
                ),
                (
                    "wrong-validator",
                    "redirect",
                    expected_full_validator,
                    "package layout full-plugin validator destination is "
                    "skills/material-code-review/scripts/wrong-validator.py; expected "
                    f"{expected_full_validator}",
                    True,
                ),
                (
                    "missing-manifest",
                    "remove",
                    expected_full_manifest,
                    "package layout full-plugin does not map its manifest to "
                    f"{expected_full_manifest}",
                    False,
                ),
                (
                    "wrong-manifest",
                    "redirect",
                    expected_full_manifest,
                    "package layout full-plugin manifest destination is "
                    "skills/material-code-review/wrong-package-layouts.json; expected "
                    f"{expected_full_manifest}",
                    False,
                ),
            )
            for (
                label,
                mutation,
                expected_destination,
                expected_error,
                exercise_fallback,
            ) in relocation_cases:
                with self.subTest(relocation=label):
                    case_root = temp_root / f"extracted-{label}"
                    shutil.copytree(extracted_root, case_root)
                    case_manifest_path = (
                        case_root
                        / "skills/material-code-review/package-layouts.json"
                    )
                    case_manifest = json.loads(
                        case_manifest_path.read_text(encoding="utf-8")
                    )
                    full_mappings = case_manifest["layouts"]["full-plugin"][
                        "required_mappings"
                    ]
                    matching = [
                        mapping
                        for mapping in full_mappings
                        if mapping["destination"] == expected_destination
                    ]
                    self.assertEqual(len(matching), 1)
                    if mutation == "remove":
                        full_mappings.remove(matching[0])
                    elif expected_destination == expected_full_validator:
                        matching[0]["destination"] = (
                            "skills/material-code-review/scripts/wrong-validator.py"
                        )
                    else:
                        matching[0]["destination"] = (
                            "skills/material-code-review/wrong-package-layouts.json"
                        )
                    if exercise_fallback:
                        standalone_mappings = case_manifest["layouts"][
                            "standalone"
                        ]["required_mappings"]
                        case_manifest["layouts"]["standalone"][
                            "required_mappings"
                        ] = [
                            mapping
                            for mapping in standalone_mappings
                            if mapping["destination"]
                            not in {"CODEX.md", "LICENSE", "SECURITY.md"}
                        ]
                        (case_root / "AGENTS.md").unlink()
                    case_manifest_path.write_text(
                        json.dumps(case_manifest, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )

                    case_result = subprocess.run(
                        [
                            sys.executable,
                            "-B",
                            str(
                                case_root
                                / "skills/material-code-review/scripts/validate_package.py"
                            ),
                        ],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertNotEqual(case_result.returncode, 0)
                    self.assertIn(expected_error, case_result.stderr)
                    if exercise_fallback:
                        self.assertIn(
                            "missing required layout file: AGENTS.md",
                            case_result.stderr,
                        )
                        self.assertNotIn(
                            "missing required layout file: CODEX.md",
                            case_result.stderr,
                        )

            full_contract = (
                extracted_root
                / "skills/material-code-review/schemas/adjudication-v4.schema.json"
            )
            full_contract.unlink()
            full_embedded_result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(
                        extracted_root
                        / "skills/material-code-review/scripts/validate_package.py"
                    ),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(full_embedded_result.returncode, 0)
            self.assertIn(
                "missing required layout file: "
                "skills/material-code-review/schemas/adjudication-v4.schema.json",
                full_embedded_result.stderr,
            )

            standalone_contract = (
                standalone_root / "tests/fixtures/reviewctl_1_2_compat.py"
            )
            standalone_contract.unlink()
            standalone_embedded_result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(standalone_root / "scripts/validate_package.py"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(standalone_embedded_result.returncode, 0)
            self.assertIn(
                "missing required layout file: "
                "tests/fixtures/reviewctl_1_2_compat.py",
                standalone_embedded_result.stderr,
            )

    def test_extracted_full_archive_package_uses_distribution_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            archive_path = temp_root / "full-plugin.zip"
            package_result = self.run_full_packager(fixture_root, archive_path)
            self.assertEqual(package_result.returncode, 0, package_result.stderr)
            extracted_root = temp_root / "extracted"
            self.extract_archive_with_modes(archive_path, extracted_root)
            distribution_directory = temp_root / "repacked"

            validation_result = subprocess.run(
                [
                    "make",
                    "-o",
                    "validate",
                    "package",
                    f"DIST_DIR={distribution_directory}",
                ],
                cwd=extracted_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            self.assertEqual(
                validation_result.returncode,
                0,
                validation_result.stdout + validation_result.stderr,
            )
            self.assertTrue(
                (distribution_directory / "material-code-review-plugin-1.7.0.zip").is_file()
            )

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "source wrapper ordering regression requires a source checkout",
    )
    def test_make_targets_reject_invalid_first_shell_wrapper(self) -> None:
        for target in ("shell", "package-check"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temp_directory:
                fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
                (fixture_root / ".git").mkdir()
                review_wrapper = fixture_root / "bin/material-reviewctl"
                review_wrapper.write_text(
                    "#!/usr/bin/env bash\nif then\n",
                    encoding="utf-8",
                )

                result = subprocess.run(
                    ["make", target],
                    cwd=fixture_root,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("material-reviewctl", result.stdout + result.stderr)

    def test_extracted_full_archive_shell_targets_check_only_shipped_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            archive_path = temp_root / "full-plugin.zip"
            package_result = self.run_full_packager(fixture_root, archive_path)
            self.assertEqual(package_result.returncode, 0, package_result.stderr)
            extracted_root = temp_root / "extracted"
            self.extract_archive_with_modes(archive_path, extracted_root)

            self.assertTrue((extracted_root / "bin/material-reviewctl").is_file())
            self.assertFalse(
                (extracted_root / ("bin/material-review-" "evaluate")).exists()
            )
            for target in ("shell", "package-check"):
                with self.subTest(target=target):
                    result = subprocess.run(
                        ["make", target],
                        cwd=extracted_root,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=60,
                    )

                    self.assertEqual(
                        result.returncode,
                        0,
                        result.stdout + result.stderr,
                    )

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "ambient-layout spoofing regression requires a source checkout",
    )
    def test_ambient_distribution_environment_cannot_skip_source_checks(self) -> None:
        environment = os.environ.copy()
        environment["MATERIAL_REVIEW_DISTRIBUTION_LAYOUT"] = "1"
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "unittest",
                "scripts.tests.test_packaging.StandalonePackagingTests."
                "test_source_validator_requires_prompt_driven_evaluation_sources",
                "-v",
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

        combined_output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, combined_output)
        self.assertNotIn("skipped", combined_output)
        self.assertIn(
            "test_source_validator_requires_prompt_driven_evaluation_sources",
            combined_output,
        )

    def test_review_validators_require_implicit_invocation_true(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
            metadata = fixture_root / "skills" / "material-code-review" / "agents" / "openai.yaml"
            self.replace_once(
                metadata,
                "  allow_implicit_invocation: true",
                "  allow_implicit_invocation: false",
            )

            source_result = self.run_package_validator(fixture_root)
            standalone_result = self.run_review_validator(fixture_root)

            expected = "openai.yaml must set policy.allow_implicit_invocation exactly to true"
            self.assertNotEqual(source_result.returncode, 0)
            self.assertIn(expected, source_result.stderr)
            self.assertNotEqual(standalone_result.returncode, 0)
            self.assertIn(expected, standalone_result.stderr)

    def test_review_validators_require_workflow_order(self) -> None:
        mutations = (
            (
                "missing",
                VALID_WORKFLOW_DISCOVERY_BLOCK.replace(
                    f"{WORKFLOW_SCOPE_CHECK}\n",
                    "",
                    1,
                ),
                "workflow discovery order marker missing or duplicate",
            ),
            (
                "duplicate",
                VALID_WORKFLOW_DISCOVERY_BLOCK.replace(
                    WORKFLOW_SCOPE_CHECK,
                    f"{WORKFLOW_SCOPE_CHECK}\n{WORKFLOW_SCOPE_CHECK}",
                    1,
                ),
                "workflow discovery order marker missing or duplicate",
            ),
            (
                "reordered",
                VALID_WORKFLOW_DISCOVERY_BLOCK.replace(
                    f"{WORKFLOW_SCOPE_CHECK}\nrecord-coverage",
                    f"record-coverage\n{WORKFLOW_SCOPE_CHECK}",
                    1,
                ),
                "workflow discovery order markers out of order",
            ),
        )
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            source_workflow = (
                fixture_root
                / "skills/material-code-review/references/workflow.md"
            )
            self.replace_workflow_discovery_block(
                source_workflow,
                VALID_WORKFLOW_DISCOVERY_BLOCK,
            )
            standalone_root = temp_root / "standalone-review"
            shutil.copytree(
                fixture_root / "skills/material-code-review",
                standalone_root,
            )
            for contract in sorted(STANDALONE_REVIEW_FIXED_CONTRACTS):
                shutil.copy2(fixture_root / contract, standalone_root / contract)
            standalone_workflow = standalone_root / "references/workflow.md"

            source_intact = self.run_package_validator(fixture_root)
            standalone_intact = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(standalone_root / "scripts/validate_package.py"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(source_intact.returncode, 0, source_intact.stderr)
            self.assertEqual(standalone_intact.returncode, 0, standalone_intact.stderr)

            for label, mutation, expected_error in mutations:
                with self.subTest(label=label):
                    self.replace_workflow_discovery_block(source_workflow, mutation)
                    self.replace_workflow_discovery_block(standalone_workflow, mutation)
                    source_result = self.run_package_validator(fixture_root)
                    standalone_result = subprocess.run(
                        [
                            sys.executable,
                            "-B",
                            str(standalone_root / "scripts/validate_package.py"),
                        ],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertNotEqual(source_result.returncode, 0)
                    self.assertIn(expected_error, source_result.stderr)
                    self.assertNotEqual(standalone_result.returncode, 0)
                    self.assertIn(expected_error, standalone_result.stderr)
                    self.replace_workflow_discovery_block(
                        source_workflow,
                        VALID_WORKFLOW_DISCOVERY_BLOCK,
                    )
                    self.replace_workflow_discovery_block(
                        standalone_workflow,
                        VALID_WORKFLOW_DISCOVERY_BLOCK,
                    )

    def test_review_validators_require_obligation_workflow_contract(self) -> None:
        decoy = (
            "<!-- decoy: check_contracts evidence_items "
            "all_required_review_paths -->"
        )
        mutations = (
            (
                "missing-block-with-decoy",
                decoy,
                False,
            ),
            (
                "missing-start",
                VALID_OBLIGATION_WORKFLOW_BLOCK.replace(
                    OBLIGATION_WORKFLOW_BLOCK_START,
                    decoy,
                    1,
                ),
                False,
            ),
            (
                "missing-end",
                VALID_OBLIGATION_WORKFLOW_BLOCK.replace(
                    OBLIGATION_WORKFLOW_BLOCK_END,
                    decoy,
                    1,
                ),
                False,
            ),
            (
                "duplicate-block",
                f"{VALID_OBLIGATION_WORKFLOW_BLOCK}\n{VALID_OBLIGATION_WORKFLOW_BLOCK}",
                False,
            ),
            (
                "duplicate-entry",
                VALID_OBLIGATION_WORKFLOW_BLOCK.replace(
                    "check_contracts=controller-derived",
                    "check_contracts=controller-derived\n"
                    "check_contracts=controller-derived",
                    1,
                ),
                False,
            ),
            (
                "malformed-value-with-decoy",
                VALID_OBLIGATION_WORKFLOW_BLOCK.replace(
                    "obligation_check_results=evidence_items",
                    "obligation_check_results=check_results",
                    1,
                )
                + f"\n{decoy}",
                False,
            ),
            (
                "weakened-check-contracts-with-decoy",
                VALID_OBLIGATION_WORKFLOW_BLOCK.replace(
                    "check_contracts=controller-derived",
                    "check_contracts=reviewer-derived",
                    1,
                )
                + f"\n{decoy}",
                False,
            ),
            (
                "weakened-path-scope-with-decoy",
                VALID_OBLIGATION_WORKFLOW_BLOCK.replace(
                    "obligation_evidence_paths=all_required_review_paths",
                    "obligation_evidence_paths=reported_review_paths",
                    1,
                )
                + f"\n{decoy}",
                False,
            ),
            (
                "relocated-outside-canonical-owner",
                decoy,
                True,
            ),
        )
        expected_error = "obligation workflow contract"
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            source_skill = fixture_root / "skills/material-code-review/SKILL.md"
            canonical_skill = source_skill.read_text(encoding="utf-8")
            self.assertEqual(canonical_skill.count(VALID_OBLIGATION_WORKFLOW_BLOCK), 1)

            standalone_root = temp_root / "standalone-review"
            shutil.copytree(
                fixture_root / "skills/material-code-review",
                standalone_root,
            )
            for contract in sorted(STANDALONE_REVIEW_FIXED_CONTRACTS):
                shutil.copy2(fixture_root / contract, standalone_root / contract)
            standalone_skill = standalone_root / "SKILL.md"

            source_intact = self.run_package_validator(fixture_root)
            standalone_intact = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(standalone_root / "scripts/validate_package.py"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(source_intact.returncode, 0, source_intact.stderr)
            self.assertEqual(standalone_intact.returncode, 0, standalone_intact.stderr)

            source_relocation = fixture_root / "README.md"
            standalone_relocation = standalone_root / "CODEX.md"
            source_relocation_text = source_relocation.read_text(encoding="utf-8")
            standalone_relocation_text = standalone_relocation.read_text(encoding="utf-8")
            for label, replacement, relocate in mutations:
                with self.subTest(label=label):
                    source_skill.write_text(
                        canonical_skill.replace(
                            VALID_OBLIGATION_WORKFLOW_BLOCK,
                            replacement,
                            1,
                        ),
                        encoding="utf-8",
                    )
                    standalone_skill.write_text(
                        canonical_skill.replace(
                            VALID_OBLIGATION_WORKFLOW_BLOCK,
                            replacement,
                            1,
                        ),
                        encoding="utf-8",
                    )
                    source_relocation.write_text(
                        source_relocation_text
                        + (f"\n{VALID_OBLIGATION_WORKFLOW_BLOCK}\n" if relocate else ""),
                        encoding="utf-8",
                    )
                    standalone_relocation.write_text(
                        standalone_relocation_text
                        + (f"\n{VALID_OBLIGATION_WORKFLOW_BLOCK}\n" if relocate else ""),
                        encoding="utf-8",
                    )

                    source_result = self.run_package_validator(fixture_root)
                    standalone_result = subprocess.run(
                        [
                            sys.executable,
                            "-B",
                            str(standalone_root / "scripts/validate_package.py"),
                        ],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertNotEqual(source_result.returncode, 0)
                    self.assertIn(expected_error, source_result.stderr)
                    self.assertNotEqual(standalone_result.returncode, 0)
                    self.assertIn(expected_error, standalone_result.stderr)

    def test_review_archives_require_workflow_order(self) -> None:
        mutations = (
            (
                "missing",
                VALID_WORKFLOW_DISCOVERY_BLOCK.replace(
                    f"{WORKFLOW_SCOPE_CHECK}\n",
                    "",
                    1,
                ),
                "workflow discovery order marker missing or duplicate",
            ),
            (
                "reordered",
                VALID_WORKFLOW_DISCOVERY_BLOCK.replace(
                    f"{WORKFLOW_SCOPE_CHECK}\nrecord-coverage",
                    f"record-coverage\n{WORKFLOW_SCOPE_CHECK}",
                    1,
                ),
                "workflow discovery order markers out of order",
            ),
        )
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            source_workflow = (
                fixture_root
                / "skills/material-code-review/references/workflow.md"
            )
            self.replace_workflow_discovery_block(
                source_workflow,
                VALID_WORKFLOW_DISCOVERY_BLOCK,
            )
            full_archive = temp_root / "full-plugin.zip"
            standalone_archive = temp_root / "material-review.zip"
            package_result = self.run_full_packager(
                fixture_root,
                full_archive,
                standalone_output=standalone_archive,
            )
            self.assertEqual(package_result.returncode, 0, package_result.stderr)
            source_result = self.run_package_validator(fixture_root)
            self.assertEqual(source_result.returncode, 0, source_result.stderr)

            archive_cases = (
                (
                    "full",
                    full_archive,
                    "--full-archive",
                    "skills/material-code-review/references/workflow.md",
                ),
                (
                    "standalone",
                    standalone_archive,
                    "--standalone-archive",
                    "references/workflow.md",
                ),
            )
            for layout, source_archive, archive_flag, workflow_entry in archive_cases:
                for mutation_name, block, expected_error in mutations:
                    with self.subTest(layout=layout, mutation=mutation_name):
                        with zipfile.ZipFile(source_archive) as archive:
                            workflow = archive.read(workflow_entry).decode("utf-8")
                        prefix, remainder = workflow.split(WORKFLOW_BLOCK_START, 1)
                        _, separator, suffix = remainder.partition(WORKFLOW_BLOCK_END)
                        self.assertEqual(separator, WORKFLOW_BLOCK_END)
                        mutated_workflow = (
                            f"{prefix}{WORKFLOW_BLOCK_START}{block}"
                            f"{WORKFLOW_BLOCK_END}{suffix}"
                        ).encode("utf-8")
                        mutated_archive = (
                            temp_root / f"{layout}-{mutation_name}.zip"
                        )
                        self.rewrite_archive_entry(
                            source_archive,
                            mutated_archive,
                            workflow_entry,
                            mutated_workflow,
                        )
                        validation_result = subprocess.run(
                            [
                                sys.executable,
                                "-B",
                                str(PACKAGE_VALIDATOR),
                                "--package-root",
                                str(fixture_root),
                                *(
                                    ["--distribution-layout"]
                                    if DISTRIBUTION_LAYOUT
                                    else []
                                ),
                                archive_flag,
                                str(mutated_archive),
                            ],
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        self.assertNotEqual(validation_result.returncode, 0)
                        self.assertIn(expected_error, validation_result.stderr)

    def test_review_validators_require_activation_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
            skill = fixture_root / "skills" / "material-code-review" / "SKILL.md"
            self.replace_once(
                skill,
                "## Activation eligibility preflight",
                "## Review eligibility",
            )

            source_result = self.run_package_validator(fixture_root)
            standalone_result = self.run_review_validator(fixture_root)

            self.assertNotEqual(source_result.returncode, 0)
            self.assertIn("canonical skill activation preflight missing marker", source_result.stderr)
            self.assertNotEqual(standalone_result.returncode, 0)
            self.assertIn("SKILL.md activation preflight missing marker", standalone_result.stderr)

    def test_source_validator_requires_aligned_activation_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
            manifest = fixture_root / ".codex-plugin" / "plugin.json"
            self.replace_once(
                manifest,
                '"shortDescription": "Material-defect review of Git changes"',
                '"shortDescription": "Evidence-gated review"',
            )

            validation_result = self.run_package_validator(fixture_root)

            self.assertNotEqual(validation_result.returncode, 0)
            self.assertIn(
                "Codex manifest shortDescription does not match the Git-change activation contract",
                validation_result.stderr,
            )

    def test_completed_standalone_archive_is_structurally_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_repository_fixture(temp_root)
            output = temp_root / "standalone.zip"
            package_result = self.run_packager(fixture_root, output)
            self.assertEqual(package_result.returncode, 0, package_result.stderr)

            validation_result = self.run_simplification_archive_validator(output)

            self.assertEqual(validation_result.returncode, 0, validation_result.stderr)
            self.assertIn("standalone archive is safe", validation_result.stdout)

    def test_simplification_archive_ships_shared_controller_closure(self) -> None:
        source_review_root = REPOSITORY_ROOT / "skills" / "material-code-review"
        source_candidate_v1_bytes = (source_review_root / "schemas" / "candidate-set.schema.json").read_bytes()
        source_candidate_v2_bytes = (source_review_root / "schemas" / "candidate-set-v2.schema.json").read_bytes()
        source_candidate_v3_bytes = (source_review_root / "schemas" / "candidate-set-v3.schema.json").read_bytes()
        source_candidate_v4_bytes = (source_review_root / "schemas" / "candidate-set-v4.schema.json").read_bytes()
        source_candidate_v5_bytes = (source_review_root / "schemas" / "candidate-set-v5.schema.json").read_bytes()
        source_candidate_v6_bytes = (source_review_root / "schemas" / "candidate-set-v6.schema.json").read_bytes()
        source_coverage_bytes = (source_review_root / "schemas" / "coverage-plan.schema.json").read_bytes()
        source_coverage_v2_bytes = (source_review_root / "schemas" / "coverage-plan-v2.schema.json").read_bytes()
        source_coverage_v3_bytes = (source_review_root / "schemas" / "coverage-plan-v3.schema.json").read_bytes()
        source_coverage_v4_bytes = (source_review_root / "schemas" / "coverage-plan-v4.schema.json").read_bytes()
        source_coverage_v5_bytes = (source_review_root / "schemas" / "coverage-plan-v5.schema.json").read_bytes()
        source_controller_bytes = (source_review_root / "scripts" / "reviewctl.py").read_bytes()
        source_obligation_contract_bytes = (source_review_root / "scripts" / "obligation_contract.py").read_bytes()
        definition_name = "canonical_repository_relative_git_path"
        self.assertIn("$defs", json.loads(source_candidate_v2_bytes))
        self.assertIn("$defs", json.loads(source_coverage_bytes))
        self.assertEqual(
            json.loads(source_candidate_v2_bytes)["$defs"][definition_name],
            json.loads(source_coverage_bytes)["$defs"][definition_name],
        )
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_repository_fixture(temp_root)
            output = temp_root / "standalone.zip"

            package_result = self.run_packager(fixture_root, output)

            self.assertEqual(package_result.returncode, 0, package_result.stderr)
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                controller_bytes = archive.read("core/reviewctl.py")
                controller = controller_bytes.decode("utf-8")
                adapter = archive.read("scripts/simplifyctl.py").decode("utf-8")
                self.assertEqual(
                    archive.read("core/schemas/candidate-set.schema.json"),
                    source_candidate_v1_bytes,
                )
                self.assertEqual(
                    archive.read("core/schemas/candidate-set-v2.schema.json"),
                    source_candidate_v2_bytes,
                )
                self.assertEqual(
                    archive.read("core/schemas/candidate-set-v3.schema.json"),
                    source_candidate_v3_bytes,
                )
                self.assertEqual(
                    archive.read("core/schemas/candidate-set-v4.schema.json"),
                    source_candidate_v4_bytes,
                )
                self.assertEqual(
                    archive.read("core/schemas/candidate-set-v5.schema.json"),
                    source_candidate_v5_bytes,
                )
                self.assertEqual(
                    archive.read("core/schemas/candidate-set-v6.schema.json"),
                    source_candidate_v6_bytes,
                )
                self.assertEqual(
                    archive.read("core/schemas/coverage-plan.schema.json"),
                    source_coverage_bytes,
                )
                self.assertEqual(
                    archive.read("core/schemas/coverage-plan-v2.schema.json"),
                    source_coverage_v2_bytes,
                )
                self.assertEqual(
                    archive.read("core/schemas/coverage-plan-v3.schema.json"),
                    source_coverage_v3_bytes,
                )
                self.assertEqual(
                    archive.read("core/schemas/coverage-plan-v4.schema.json"),
                    source_coverage_v4_bytes,
                )
                self.assertEqual(
                    archive.read("core/schemas/coverage-plan-v5.schema.json"),
                    source_coverage_v5_bytes,
                )
                self.assertEqual(controller_bytes, source_controller_bytes)
                self.assertEqual(
                    archive.read("core/obligation_contract.py"),
                    source_obligation_contract_bytes,
                )
            self.assertTrue(
                {
                    "core/references/remediation-auditor-template.md",
                    "core/references/remediation-rubric.md",
                    "core/references/test-evidence-rubric.md",
                }.issubset(names)
            )
            self.assertTrue(
                {
                    "core/schemas/candidate-set.schema.json",
                    "core/schemas/candidate-set-v2.schema.json",
                    "core/schemas/candidate-set-v3.schema.json",
                    "core/schemas/candidate-set-v4.schema.json",
                    "core/schemas/candidate-set-v5.schema.json",
                    "core/schemas/candidate-set-v6.schema.json",
                    "core/schemas/coverage-plan.schema.json",
                    "core/schemas/coverage-plan-v2.schema.json",
                    "core/schemas/coverage-plan-v3.schema.json",
                    "core/schemas/coverage-plan-v4.schema.json",
                    "core/schemas/coverage-plan-v5.schema.json",
                    "core/obligation_contract.py",
                }.issubset(names)
            )
            self.assertIn(
                'TOOL_VERSION = "1.7.0"',
                controller,
            )
            self.assertIn(
                'ADAPTER_VERSION = "1.3.0"',
                adapter,
            )

    def test_simplification_archive_rejects_each_new_shared_contract_omission(
        self,
    ) -> None:
        required_members = (
            "core/obligation_contract.py",
            "core/schemas/candidate-set-v3.schema.json",
            "core/schemas/candidate-set-v4.schema.json",
            "core/schemas/candidate-set-v5.schema.json",
            "core/schemas/candidate-set-v6.schema.json",
            "core/schemas/coverage-plan-v2.schema.json",
            "core/schemas/coverage-plan-v3.schema.json",
            "core/schemas/coverage-plan-v4.schema.json",
            "core/schemas/coverage-plan-v5.schema.json",
        )
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_repository_fixture(temp_root)
            source_archive = temp_root / "simplification.zip"
            package_result = self.run_packager(fixture_root, source_archive)
            self.assertEqual(package_result.returncode, 0, package_result.stderr)

            for index, member in enumerate(required_members):
                with self.subTest(member=member):
                    incomplete_archive = temp_root / f"missing-shared-{index}.zip"
                    self.remove_archive_entry(
                        source_archive,
                        incomplete_archive,
                        member,
                    )
                    result = self.run_simplification_archive_validator(
                        incomplete_archive
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f"missing archive entry: {member}", result.stderr)

    def test_release_1_7_0_and_simplification_1_3_0_are_aligned(self) -> None:
        full_version = "1.7.0"
        simplification_version = "1.3.0"

        for relative in (
            ".codex-plugin/plugin.json",
            ".claude-plugin/plugin.json",
            ".claude-plugin/marketplace.json",
        ):
            manifest = json.loads((REPOSITORY_ROOT / relative).read_text(encoding="utf-8"))
            self.assertEqual(manifest["version"], full_version)

        makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn(f"VERSION := {full_version}", makefile)
        self.assertIn(f"SIMPLIFY_VERSION := {simplification_version}", makefile)
        self.assertIn("material-code-simplification-codex-skill-$(SIMPLIFY_VERSION).zip", makefile)

        helper = self.load_static_version_helper(PACKAGE_VALIDATOR)
        python_version_owners = (
            ("scripts/package_plugin.py", "VERSION", full_version),
            ("scripts/validate_package.py", "VERSION", full_version),
            ("skills/material-code-review/scripts/reviewctl.py", "TOOL_VERSION", full_version),
            ("skills/material-code-review/scripts/validate_package.py", "VERSION", full_version),
            ("scripts/package_simplification_skill.py", "VERSION", simplification_version),
            (
                "skills/material-code-simplification/scripts/simplifyctl.py",
                "ADAPTER_VERSION",
                simplification_version,
            ),
            (
                "skills/material-code-simplification/scripts/validate_package.py",
                "VERSION",
                simplification_version,
            ),
            (
                "skills/material-code-simplification/scripts/validate_package.py",
                "CORE_VERSION",
                full_version,
            ),
        )
        for relative, constant_name, expected_value in python_version_owners:
            with self.subTest(relative=relative):
                self.assertIsNone(
                    helper(
                        (REPOSITORY_ROOT / relative).read_bytes(),
                        constant_name,
                        expected_value,
                        relative,
                    )
                )

        self.assertNotEqual(full_version, simplification_version)

        for relative in (
            "scripts/package_plugin.py",
            "scripts/package_simplification_skill.py",
        ):
            with self.subTest(timestamp_owner=relative):
                source = (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
                self.assertIn(
                    "FIXED_TIMESTAMP = (2026, 7, 30, 0, 0, 0)",
                    source,
                )

    def test_static_version_assignment_contracts_are_aligned(self) -> None:
        helpers = tuple(
            self.load_static_version_helper(path)
            for path in (PACKAGE_VALIDATOR, REVIEW_VALIDATOR, SIMPLIFICATION_VALIDATOR)
        )
        cases = (
            ("direct literal", 'TOOL_VERSION = "1.3.0"\n', None),
            ("comment decoy", '# TOOL_VERSION = "1.3.0"\n', "missing"),
            ("docstring decoy", "'''TOOL_VERSION = \"1.3.0\"'''\n", "missing"),
            ("wrong literal", 'TOOL_VERSION = "0.0.0"\n', "wrong value"),
            ("same duplicate", 'TOOL_VERSION = "1.3.0"\nTOOL_VERSION = "1.3.0"\n', "duplicate/competing"),
            ("different duplicate", 'TOOL_VERSION = "1.3.0"\nTOOL_VERSION = "0.0.0"\n', "duplicate/competing"),
            ("control-flow duplicate", 'TOOL_VERSION = "1.3.0"\nif True:\n    TOOL_VERSION = "1.3.0"\n', "duplicate/competing"),
            ("nested excluded", 'def version():\n    TOOL_VERSION = "0.0.0"\nTOOL_VERSION = "1.3.0"\n', None),
            ("function definition binding", 'TOOL_VERSION = "1.3.0"\ndef TOOL_VERSION():\n    pass\n', "duplicate/competing"),
            ("async definition binding", 'TOOL_VERSION = "1.3.0"\nasync def TOOL_VERSION():\n    pass\n', "duplicate/competing"),
            ("class definition binding", 'TOOL_VERSION = "1.3.0"\nclass TOOL_VERSION:\n    pass\n', "duplicate/competing"),
            ("function decorator binding", 'TOOL_VERSION = "1.3.0"\n@(TOOL_VERSION := lambda function: function)\ndef version():\n    pass\n', "duplicate/competing"),
            ("function default binding", 'TOOL_VERSION = "1.3.0"\ndef version(value=(TOOL_VERSION := "1.3.0")):\n    pass\n', "duplicate/competing"),
            ("function annotation binding", 'TOOL_VERSION = "1.3.0"\ndef version(value: (TOOL_VERSION := "1.3.0")):\n    pass\n', "duplicate/competing"),
            ("lambda default binding", 'TOOL_VERSION = "1.3.0"\ncallback = lambda value=(TOOL_VERSION := "0.0.0"): value\n', "duplicate/competing"),
            ("class decorator binding", 'TOOL_VERSION = "1.3.0"\n@(TOOL_VERSION := lambda cls: cls)\nclass version:\n    pass\n', "duplicate/competing"),
            ("class base binding", 'TOOL_VERSION = "1.3.0"\nclass version((TOOL_VERSION := object)):\n    pass\n', "duplicate/competing"),
            ("class keyword binding", 'TOOL_VERSION = "1.3.0"\nclass version(metaclass=(TOOL_VERSION := type)):\n    pass\n', "duplicate/competing"),
            ("class local excluded", 'TOOL_VERSION = "1.3.0"\nclass version:\n    TOOL_VERSION = "0.0.0"\n', None),
            ("class global without binding", 'TOOL_VERSION = "1.3.0"\nclass version:\n    global TOOL_VERSION\n', None),
            ("class global direct binding", 'TOOL_VERSION = "1.3.0"\nclass version:\n    global TOOL_VERSION\n    TOOL_VERSION = "0.0.0"\n', "duplicate/competing"),
            ("nested class global direct binding", 'TOOL_VERSION = "1.3.0"\nclass outer:\n    class inner:\n        global TOOL_VERSION\n        TOOL_VERSION = "0.0.0"\n', "duplicate/competing"),
            ("class global definition binding", 'TOOL_VERSION = "1.3.0"\nclass version:\n    global TOOL_VERSION\n    def TOOL_VERSION():\n        pass\n', "duplicate/competing"),
            ("class global import binding", 'TOOL_VERSION = "1.3.0"\nclass version:\n    global TOOL_VERSION\n    from release import TOOL_VERSION\n', "duplicate/competing"),
            ("class global loop-target binding", 'TOOL_VERSION = "1.3.0"\nclass version:\n    global TOOL_VERSION\n    for TOOL_VERSION in ():\n        pass\n', "duplicate/competing"),
            ("function global binding excluded", 'TOOL_VERSION = "1.3.0"\ndef version():\n    global TOOL_VERSION\n    TOOL_VERSION = "0.0.0"\n', None),
            ("wildcard import", "from release import *\n", "non-direct/nonliteral"),
            ("direct plus wildcard import", 'TOOL_VERSION = "1.3.0"\nfrom release import *\n', "duplicate/competing"),
            ("complex target load", 'TOOL_VERSION = "1.3.0"\nregistry[TOOL_VERSION] = metadata\n', None),
            ("nested named expression binding", 'registry[(TOOL_VERSION := "1.3.0")] = metadata\n', "non-direct/nonliteral"),
            ("missing", "pass\n", "missing"),
            ("computed", 'TOOL_VERSION = "1." + "3.0"\n', "non-direct/nonliteral"),
            ("formatted", 'TOOL_VERSION = f"{1}.3.0"\n', "non-direct/nonliteral"),
            ("non-string", "TOOL_VERSION = 13\n", "non-direct/nonliteral"),
            ("indirect", 'alias = "1.3.0"\nTOOL_VERSION = alias\n', "non-direct/nonliteral"),
            ("destructuring", 'TOOL_VERSION, other = ("1.3.0", "x")\n', "non-direct/nonliteral"),
            ("annotated", 'TOOL_VERSION: str = "1.3.0"\n', "non-direct/nonliteral"),
            ("imported", "from release import TOOL_VERSION\n", "non-direct/nonliteral"),
            ("augmented", 'TOOL_VERSION = "1."\nTOOL_VERSION += "3.0"\n', "duplicate/competing"),
            ("deleted", 'TOOL_VERSION = "1.3.0"\ndel TOOL_VERSION\n', "duplicate/competing"),
            ("named expression", 'if (TOOL_VERSION := "1.3.0"):\n    pass\n', "non-direct/nonliteral"),
            ("syntax", 'TOOL_VERSION = "1.3.0"\nif\n', "syntax"),
        )
        for name, source, expected_cause in cases:
            with self.subTest(name=name):
                results = tuple(
                    helper(source, "TOOL_VERSION", "1.3.0", "fixture.py")
                    for helper in helpers
                )
                self.assertEqual(results, (results[0],) * len(results))
                if expected_cause is None:
                    self.assertIsNone(results[0])
                else:
                    self.assertIsNotNone(results[0])
                    self.assertIn("fixture.py", results[0])
                    self.assertIn("TOOL_VERSION", results[0])
                    self.assertIn(expected_cause, results[0])

        invalid_utf8 = b'TOOL_VERSION = "1.3.0"\xff\n'
        results = tuple(
            helper(invalid_utf8, "TOOL_VERSION", "1.3.0", "member.py")
            for helper in helpers
        )
        self.assertEqual(results, (results[0],) * len(results))
        self.assertIn("member.py", results[0])
        self.assertIn("TOOL_VERSION", results[0])
        self.assertIn("UTF-8", results[0])

    def test_static_version_helper_accepts_only_immediate_module_body_literal(self) -> None:
        helpers = tuple(
            self.load_static_version_helper(path)
            for path in (PACKAGE_VALIDATOR, REVIEW_VALIDATOR, SIMPLIFICATION_VALIDATOR)
        )
        cases = (
            ("direct", 'TOOL_VERSION = "1.5.0"\n', None),
            ("wrong", 'TOOL_VERSION = "0.0.0"\n', "wrong value"),
            ("missing", "# TOOL_VERSION = '1.5.0'\n", "missing"),
            ("if false", 'if False:\n    TOOL_VERSION = "1.5.0"\n', "non-direct/nonliteral"),
            ("while", 'while False:\n    TOOL_VERSION = "1.5.0"\n', "non-direct/nonliteral"),
            ("for", 'for unused in ():\n    TOOL_VERSION = "1.5.0"\n', "non-direct/nonliteral"),
            ("with", 'with context():\n    TOOL_VERSION = "1.5.0"\n', "non-direct/nonliteral"),
            ("try", 'try:\n    TOOL_VERSION = "1.5.0"\nexcept Exception:\n    pass\n', "non-direct/nonliteral"),
            ("match", 'match value:\n    case _:\n        TOOL_VERSION = "1.5.0"\n', "non-direct/nonliteral"),
            (
                "direct plus nested",
                'TOOL_VERSION = "1.5.0"\nif False:\n    TOOL_VERSION = "1.5.0"\n',
                "duplicate/competing",
            ),
            (
                "function local excluded",
                'def local():\n    TOOL_VERSION = "0.0.0"\nTOOL_VERSION = "1.5.0"\n',
                None,
            ),
            (
                "module evaluated default",
                'TOOL_VERSION = "1.5.0"\ndef local(value=(TOOL_VERSION := "0.0.0")):\n    pass\n',
                "duplicate/competing",
            ),
            (
                "class local excluded",
                'TOOL_VERSION = "1.5.0"\nclass Local:\n    TOOL_VERSION = "0.0.0"\n',
                None,
            ),
            (
                "class global competing",
                'TOOL_VERSION = "1.5.0"\nclass Local:\n    global TOOL_VERSION\n    TOOL_VERSION = "0.0.0"\n',
                "duplicate/competing",
            ),
            (
                "never execute inspected source",
                'raise RuntimeError("must not execute")\nTOOL_VERSION = "1.5.0"\n',
                None,
            ),
        )
        for name, source, expected_cause in cases:
            with self.subTest(name=name):
                results = tuple(
                    helper(source, "TOOL_VERSION", "1.5.0", "fixture.py")
                    for helper in helpers
                )
                self.assertEqual(results, (results[0],) * len(results))
                if expected_cause is None:
                    self.assertIsNone(results[0])
                else:
                    self.assertIsNotNone(results[0])
                    self.assertIn(expected_cause, results[0])

        for relative, constant_name, expected_value in (
            ("scripts/package_plugin.py", "VERSION", "1.7.0"),
            ("skills/material-code-review/scripts/reviewctl.py", "TOOL_VERSION", "1.7.0"),
            ("skills/material-code-simplification/scripts/simplifyctl.py", "ADAPTER_VERSION", "1.3.0"),
        ):
            for helper in helpers:
                self.assertIsNone(
                    helper(
                        (REPOSITORY_ROOT / relative).read_bytes(),
                        constant_name,
                        expected_value,
                        relative,
                    )
                )

    def test_static_version_helper_has_one_source_owner_and_ships_to_every_layout(self) -> None:
        helper = REPOSITORY_ROOT / "skills/material-code-review/scripts/static_version_contract.py"
        validators = (
            PACKAGE_VALIDATOR,
            REVIEW_VALIDATOR,
            SIMPLIFICATION_VALIDATOR,
        )
        inspected_sources = (helper, *validators)
        self.assertEqual(
            sum(
                path.read_text(encoding="utf-8").count(
                    "def validate_static_version_declaration("
                )
                for path in inspected_sources
            ),
            1,
        )
        for validator in validators:
            source = validator.read_text(encoding="utf-8")
            self.assertIn("from static_version_contract import", source)
            self.assertNotIn("class BindingVisitor", source)

        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            _, full_archive, review_archive = self.build_review_archives(
                temp_root,
                fixture_root,
            )
            simplification_archive = temp_root / "simplification.zip"
            simplification_result = self.run_packager(
                fixture_root,
                simplification_archive,
            )
            self.assertEqual(
                simplification_result.returncode,
                0,
                simplification_result.stderr,
            )

            archive_helpers = (
                (full_archive, "skills/material-code-review/scripts/static_version_contract.py"),
                (review_archive, "scripts/static_version_contract.py"),
                (simplification_archive, "core/static_version_contract.py"),
            )
            for archive_path, member in archive_helpers:
                with self.subTest(archive=archive_path.name, member=member):
                    with zipfile.ZipFile(archive_path) as archive:
                        self.assertEqual(archive.namelist().count(member), 1)

            full_root = temp_root / "extracted-full"
            review_root = temp_root / "extracted-review"
            simplification_root = temp_root / "extracted-simplification"
            self.extract_archive_with_modes(full_archive, full_root)
            self.extract_archive_with_modes(review_archive, review_root)
            self.extract_archive_with_modes(simplification_archive, simplification_root)

            isolated_commands = (
                (
                    sys.executable,
                    "-B",
                    str(full_root / "scripts/validate_package.py"),
                    "--package-root",
                    str(full_root),
                    "--distribution-layout",
                ),
                (
                    sys.executable,
                    "-B",
                    str(full_root / "skills/material-code-review/scripts/validate_package.py"),
                ),
                (
                    sys.executable,
                    "-B",
                    str(full_root / "skills/material-code-simplification/scripts/validate_package.py"),
                ),
                (
                    sys.executable,
                    "-B",
                    str(review_root / "scripts/validate_package.py"),
                ),
                (
                    sys.executable,
                    "-B",
                    str(simplification_root / "scripts/validate_package.py"),
                ),
            )
            for command in isolated_commands:
                with self.subTest(validator=command[2]):
                    result = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=60,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)

            missing_full = temp_root / "missing-full-helper.zip"
            self.remove_archive_entry(
                full_archive,
                missing_full,
                "skills/material-code-review/scripts/static_version_contract.py",
            )
            missing_full_result = self.run_review_archive_validator(
                fixture_root,
                missing_full,
                standalone=False,
            )
            self.assertNotEqual(missing_full_result.returncode, 0)
            self.assertIn("static_version_contract.py", missing_full_result.stderr)

            missing_review = temp_root / "missing-review-helper.zip"
            self.remove_archive_entry(
                review_archive,
                missing_review,
                "scripts/static_version_contract.py",
            )
            missing_review_result = self.run_review_archive_validator(
                fixture_root,
                missing_review,
                standalone=True,
            )
            self.assertNotEqual(missing_review_result.returncode, 0)
            self.assertIn("static_version_contract.py", missing_review_result.stderr)

            missing_simplification = temp_root / "missing-simplification-helper.zip"
            self.remove_archive_entry(
                simplification_archive,
                missing_simplification,
                "core/static_version_contract.py",
            )
            missing_simplification_result = self.run_simplification_archive_validator(
                missing_simplification
            )
            self.assertNotEqual(missing_simplification_result.returncode, 0)
            self.assertIn(
                "missing archive entry: core/static_version_contract.py",
                missing_simplification_result.stderr,
            )

    def test_review_validators_reject_version_decoys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
            controller = fixture_root / "skills/material-code-review/scripts/reviewctl.py"
            self.replace_once(
                controller,
                'TOOL_VERSION = "1.7.0"',
                '# TOOL_VERSION = "1.7.0"\nTOOL_VERSION = "0.0.0"',
            )
            root_result = self.run_package_validator(fixture_root)
            review_result = self.run_review_validator(fixture_root)
            for result in (root_result, review_result):
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("reviewctl.py", result.stderr)
                self.assertIn("TOOL_VERSION", result.stderr)
                self.assertIn("wrong value", result.stderr)

    def test_root_validator_rejects_packager_version_decoys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
            packager = fixture_root / "scripts/package_plugin.py"
            self.replace_once(
                packager,
                'VERSION = "1.7.0"',
                'VERSION = "1.7.0"\nif True:\n    VERSION = "1.7.0"',
            )
            result = self.run_package_validator(fixture_root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("scripts/package_plugin.py", result.stderr)
            self.assertIn("VERSION", result.stderr)
            self.assertIn("duplicate/competing", result.stderr)

    def test_simplification_validator_rejects_source_version_decoys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
            controller = fixture_root / "skills/material-code-review/scripts/reviewctl.py"
            adapter = fixture_root / "skills/material-code-simplification/scripts/simplifyctl.py"
            self.replace_once(
                controller,
                'TOOL_VERSION = "1.7.0"',
                'TOOL_VERSION = "0.0.0"\n# TOOL_VERSION = "1.7.0"',
            )
            self.replace_once(
                adapter,
                'ADAPTER_VERSION = "1.3.0"',
                'ADAPTER_VERSION = "1.3.0"\nADAPTER_VERSION = "1.3.0"',
            )
            result = self.run_simplification_validator(fixture_root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("reviewctl.py", result.stderr)
            self.assertIn("TOOL_VERSION", result.stderr)
            self.assertIn("wrong value", result.stderr)
            self.assertIn("simplifyctl.py", result.stderr)
            self.assertIn("ADAPTER_VERSION", result.stderr)
            self.assertIn("duplicate/competing", result.stderr)

    def test_simplification_archive_rejects_version_decoys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            controller = fixture_root / "skills/material-code-review/scripts/reviewctl.py"
            adapter = fixture_root / "skills/material-code-simplification/scripts/simplifyctl.py"
            self.replace_once(
                controller,
                'TOOL_VERSION = "1.7.0"',
                '# TOOL_VERSION = "1.7.0"\nTOOL_VERSION = "0.0.0"',
            )
            self.replace_once(
                adapter,
                'ADAPTER_VERSION = "1.3.0"',
                'ADAPTER_VERSION = "1.3.0"\nif True:\n    ADAPTER_VERSION = "1.3.0"',
            )
            archive = temp_root / "standalone.zip"
            package_result = self.run_packager(fixture_root, archive)
            self.assertEqual(package_result.returncode, 0, package_result.stderr)
            result = self.run_simplification_archive_validator(archive)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("core/reviewctl.py", result.stderr)
            self.assertIn("TOOL_VERSION", result.stderr)
            self.assertIn("wrong value", result.stderr)
            self.assertIn("scripts/simplifyctl.py", result.stderr)
            self.assertIn("ADAPTER_VERSION", result.stderr)
            self.assertIn("duplicate/competing", result.stderr)

            unsafe_archive = temp_root / "unsafe-before-version-parse.zip"
            with zipfile.ZipFile(unsafe_archive, "w") as unsafe_zip:
                unsafe_zip.comment = b"material-code-simplification standalone Agent Skill 1.3.0"
                unsafe_zip.writestr("../unsafe.txt", "unsafe")
                unsafe_zip.writestr("core/reviewctl.py", b'\xff')
            unsafe_result = self.run_simplification_archive_validator(unsafe_archive)
            self.assertNotEqual(unsafe_result.returncode, 0)
            self.assertIn("unsafe archive path", unsafe_result.stderr)
            self.assertNotIn("core/reviewctl.py: TOOL_VERSION declaration has invalid UTF-8", unsafe_result.stderr)

    def test_archive_validator_rejects_unsafe_and_incomplete_archives(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            unsafe_archive = temp_root / "unsafe.zip"
            with zipfile.ZipFile(unsafe_archive, "w") as archive:
                archive.comment = b"material-code-simplification standalone Agent Skill"
                archive.writestr("../escape.txt", "escape")

            unsafe_result = self.run_simplification_archive_validator(unsafe_archive)

            self.assertNotEqual(unsafe_result.returncode, 0)
            self.assertIn("unsafe archive path", unsafe_result.stderr)

            incomplete_archive = temp_root / "incomplete.zip"
            with zipfile.ZipFile(incomplete_archive, "w") as archive:
                archive.comment = b"material-code-simplification standalone Agent Skill"
                archive.writestr("SKILL.md", "---\nname: material-code-simplification\n---\n")

            incomplete_result = self.run_simplification_archive_validator(incomplete_archive)

            self.assertNotEqual(incomplete_result.returncode, 0)
            self.assertIn("missing archive entry: core/reviewctl.py", incomplete_result.stderr)

            fixture_root = self.create_full_plugin_fixture(temp_root)
            ancillary = (
                fixture_root
                / "skills/material-code-review/examples/safe-ancillary.txt"
            )
            ancillary.write_text("safe ancillary content\n", encoding="utf-8")
            _, full_archive, standalone_archive = self.build_review_archives(
                temp_root,
                fixture_root,
            )
            with zipfile.ZipFile(full_archive) as archive:
                self.assertIn(
                    "skills/material-code-review/examples/safe-ancillary.txt",
                    archive.namelist(),
                )
            with zipfile.ZipFile(standalone_archive) as archive:
                self.assertIn("examples/safe-ancillary.txt", archive.namelist())
            for archive_path, standalone in (
                (full_archive, False),
                (standalone_archive, True),
            ):
                valid_result = self.run_review_archive_validator(
                    fixture_root,
                    archive_path,
                    standalone=standalone,
                )
                self.assertEqual(valid_result.returncode, 0, valid_result.stderr)

            unsafe_review_archive = temp_root / "unsafe-review.zip"
            shutil.copy2(full_archive, unsafe_review_archive)
            with zipfile.ZipFile(unsafe_review_archive, "a") as archive:
                archive.writestr("../escape.txt", "escape")
            unsafe_review_result = self.run_review_archive_validator(
                fixture_root,
                unsafe_review_archive,
                standalone=False,
            )
            self.assertNotEqual(unsafe_review_result.returncode, 0)
            self.assertIn("unsafe archive path", unsafe_review_result.stderr)

            missing_contract = "tests/fixtures/reviewctl_1_2_compat.py"
            incomplete_review_archive = temp_root / "incomplete-review.zip"
            self.remove_archive_entry(
                standalone_archive,
                incomplete_review_archive,
                missing_contract,
            )
            incomplete_review_result = self.run_review_archive_validator(
                fixture_root,
                incomplete_review_archive,
                standalone=True,
            )
            self.assertNotEqual(incomplete_review_result.returncode, 0)
            self.assertIn(
                f"{incomplete_review_archive.name}: missing archive entry {missing_contract}",
                incomplete_review_result.stderr,
            )

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "case-only collision is a source-checkout packaging fixture",
    )
    def test_archive_member_collisions_use_one_portable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            review_packager = self.load_fixture_module(
                fixture_root / "scripts/package_plugin.py",
                "portable_review_packager",
            )
            simplification_packager = self.load_fixture_module(
                fixture_root / "scripts/package_simplification_skill.py",
                "portable_simplification_packager",
            )
            source = fixture_root / "README.md"
            alias_pairs = (
                ("Aliases/Readme.txt", "aliases/readme.txt"),
                ("aliases/Caf\u00e9.txt", "aliases/Cafe\u0301.TXT"),
                ("aliases/name.txt", "aliases/name.txt. "),
                ("nested./File.txt", "nested/file.txt"),
            )

            for index, (first, second) in enumerate(alias_pairs):
                with self.subTest(builder="review", first=first, second=second):
                    output = temp_root / f"review-collision-{index}.zip"
                    with self.assertRaisesRegex(
                        ValueError, "Portable archive member collision"
                    ):
                        review_packager.build_archive(
                            output,
                            [(source, first), (source, second)],
                            "portable collision test",
                        )

                    single = temp_root / f"review-single-{index}.zip"
                    review_packager.build_archive(
                        single,
                        [(source, first)],
                        "portable single-name control",
                    )
                    with zipfile.ZipFile(single) as archive:
                        self.assertEqual(archive.namelist(), [first])

                with self.subTest(builder="simplification", first=first, second=second):
                    output = temp_root / f"simplification-collision-{index}.zip"
                    checksum = output.with_suffix(".zip.sha256")
                    output.write_bytes(b"archive sentinel")
                    checksum.write_bytes(b"checksum sentinel")
                    with mock.patch.object(
                        simplification_packager,
                        "iter_files",
                        return_value=[(source, first), (source, second)],
                    ), mock.patch.object(
                        sys,
                        "argv",
                        [
                            "package_simplification_skill.py",
                            "--root",
                            str(fixture_root),
                            "--output",
                            str(output),
                        ],
                    ):
                        with self.assertRaisesRegex(
                            SystemExit, "portable archive member collision"
                        ):
                            simplification_packager.main()
                    self.assertEqual(output.read_bytes(), b"archive sentinel")
                    self.assertEqual(checksum.read_bytes(), b"checksum sentinel")

            distinct_first = temp_root / "distinct-first.zip"
            distinct_second = temp_root / "distinct-second.zip"
            distinct_entries = [
                (source, "nested/alpha.txt"),
                (source, "nested/beta.txt"),
            ]
            review_packager.build_archive(
                distinct_first,
                distinct_entries,
                "portable distinct control",
            )
            review_packager.build_archive(
                distinct_second,
                distinct_entries,
                "portable distinct control",
            )
            self.assertEqual(distinct_first.read_bytes(), distinct_second.read_bytes())

            _, full_archive, standalone_archive = self.build_review_archives(
                temp_root,
                fixture_root,
            )
            simplification_archive = temp_root / "material-simplification.zip"
            simplification_result = self.run_packager(
                fixture_root,
                simplification_archive,
            )
            self.assertEqual(
                simplification_result.returncode,
                0,
                simplification_result.stderr,
            )
            with zipfile.ZipFile(simplification_archive) as archive:
                self.assertIn("core/package_layout_contract.py", archive.namelist())
            self.assertEqual(
                self.run_simplification_archive_validator(
                    simplification_archive
                ).returncode,
                0,
            )

            def archive_with_alias_pair(
                source_archive: Path,
                destination_archive: Path,
                first: str,
                second: str,
            ) -> None:
                with zipfile.ZipFile(source_archive) as archive:
                    members = archive.infolist()
                    comment = archive.comment
                    payloads = {
                        member.filename: archive.read(member)
                        for member in members
                    }
                with zipfile.ZipFile(destination_archive, "w") as archive:
                    archive.comment = comment
                    for member in members:
                        archive.writestr(member, payloads[member.filename])
                    for name in (first, second):
                        info = zipfile.ZipInfo(name, date_time=(2026, 7, 30, 0, 0, 0))
                        info.create_system = 3
                        info.external_attr = (stat.S_IFREG | 0o644) << 16
                        archive.writestr(info, b"alias collision\n")

            validator_cases = (
                (full_archive, False, "review-full"),
                (standalone_archive, True, "review-standalone"),
            )
            for source_archive, standalone, label in validator_cases:
                first, second = alias_pairs[1]
                mutated = temp_root / f"{label}-alias.zip"
                archive_with_alias_pair(source_archive, mutated, first, second)
                result = self.run_review_archive_validator(
                    fixture_root,
                    mutated,
                    standalone=standalone,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("portable archive member collision", result.stderr)
                self.assertIn(first, result.stderr)
                self.assertIn(second, result.stderr)

            first, second = alias_pairs[1]
            mutated_simplification = temp_root / "simplification-alias.zip"
            archive_with_alias_pair(
                simplification_archive,
                mutated_simplification,
                first,
                second,
            )
            result = self.run_simplification_archive_validator(
                mutated_simplification
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("portable archive member collision", result.stderr)
            self.assertIn(first, result.stderr)
            self.assertIn(second, result.stderr)

    def test_schema_local_reference_closure_uses_source_and_archived_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            contract = self.load_fixture_module(
                fixture_root
                / "skills/material-code-review/scripts/package_layout_contract.py",
                "schema_reference_contract",
            )

            closed_document = {
                "$defs": {"a/b": {"~key": [{"type": "string"}]}},
                "allOf": [
                    {"$ref": "#"},
                    {"$ref": "#/$defs/a~1b/~0key/0"},
                    {"$ref": "#/$defs/a~1b/~0key/0"},
                ],
                "nonsemantic": {"accepted": True},
            }
            self.assertEqual(
                contract.local_schema_reference_errors(closed_document, "closed.json"),
                [],
            )

            invalid_documents = (
                ({"$ref": "#/$defs/missing"}, "missing object key"),
                ({"$defs": {}, "$ref": "#/$defs/bad~2token"}, "invalid JSON Pointer escape"),
                ({"items": [], "$ref": "#/items/not-an-index"}, "invalid array index"),
                ({"items": [], "$ref": "#/items/0"}, "array index out of range"),
                ({"value": 1, "$ref": "#/value/child"}, "cannot traverse scalar"),
                ({"$ref": "#/%24defs/item"}, "malformed percent-free local JSON Pointer"),
                ({"$ref": "https://example.invalid/schema"}, "nonlocal references are unsupported"),
                ({"$ref": "file:///tmp/schema.json"}, "nonlocal references are unsupported"),
                ({"$ref": "other.schema.json#/$defs/item"}, "nonlocal references are unsupported"),
                ({"$ref": 7}, "reference must be a string"),
            )
            for document, expected_error in invalid_documents:
                with self.subTest(expected_error=expected_error):
                    errors = contract.local_schema_reference_errors(
                        document,
                        "invalid.json",
                    )
                    self.assertEqual(len(errors), 1)
                    self.assertIn("invalid.json: #/$ref", errors[0])
                    self.assertIn(expected_error, errors[0])

            candidate_path = (
                fixture_root
                / "skills/material-code-review/schemas/candidate-set-v5.schema.json"
            )
            candidate_document = json.loads(candidate_path.read_text(encoding="utf-8"))
            candidate_document["$defs"].pop("identifier")
            candidate_path.write_text(
                json.dumps(candidate_document, indent=2) + "\n",
                encoding="utf-8",
            )
            source_result = self.run_package_validator(fixture_root)
            self.assertNotEqual(source_result.returncode, 0)
            self.assertIn("candidate-set-v5.schema.json", source_result.stderr)
            self.assertIn("#/$defs/identifier", source_result.stderr)
            self.assertIn("missing object key 'identifier'", source_result.stderr)

            fixture_root = self.create_full_plugin_fixture(temp_root / "archive-fixture")
            _, full_archive, standalone_archive = self.build_review_archives(
                temp_root / "archive-fixture",
                fixture_root,
            )
            simplification_archive = temp_root / "schema-simplification.zip"
            package_result = self.run_packager(
                fixture_root,
                simplification_archive,
            )
            self.assertEqual(package_result.returncode, 0, package_result.stderr)

            valid_candidate = json.loads(
                (
                    fixture_root
                    / "skills/material-code-review/schemas/candidate-set-v5.schema.json"
                ).read_text(encoding="utf-8")
            )
            valid_candidate["$defs"].pop("identifier")
            invalid_candidate_bytes = (
                json.dumps(valid_candidate, indent=2) + "\n"
            ).encode("utf-8")

            review_archive_cases = (
                (
                    full_archive,
                    "skills/material-code-review/schemas/candidate-set-v5.schema.json",
                    False,
                    "mutated-full-schema.zip",
                ),
                (
                    standalone_archive,
                    "schemas/candidate-set-v5.schema.json",
                    True,
                    "mutated-standalone-schema.zip",
                ),
            )
            for source_archive, entry, standalone, name in review_archive_cases:
                mutated = temp_root / name
                self.rewrite_archive_entry(
                    source_archive,
                    mutated,
                    entry,
                    invalid_candidate_bytes,
                )
                result = self.run_review_archive_validator(
                    fixture_root,
                    mutated,
                    standalone=standalone,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(entry, result.stderr)
                self.assertIn("#/$defs/identifier", result.stderr)
                self.assertIn("missing object key 'identifier'", result.stderr)

            mutated_simplification = temp_root / "mutated-simplification-schema.zip"
            self.rewrite_archive_entry(
                simplification_archive,
                mutated_simplification,
                "core/schemas/candidate-set-v5.schema.json",
                invalid_candidate_bytes,
            )
            result = self.run_simplification_archive_validator(
                mutated_simplification
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("core/schemas/candidate-set-v5.schema.json", result.stderr)
            self.assertIn("#/$defs/identifier", result.stderr)
            self.assertIn("missing object key 'identifier'", result.stderr)

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "case-only collision is a source-checkout packaging fixture",
    )
    @unittest.skipIf(sys.platform.startswith("win"), "fixture requires POSIX filename semantics")
    def test_packager_rejects_case_only_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            case_sensitivity_probe = temp_root / "case-sensitivity-probe"
            case_sensitivity_probe.touch()
            if (temp_root / "CASE-SENSITIVITY-PROBE").exists():
                self.skipTest("temporary filesystem is case-insensitive")

            fixture_root = self.create_repository_fixture(temp_root)
            skill_root = fixture_root / "skills" / "material-code-simplification"
            # Create a file that differs only in case from an existing file
            (skill_root / "skill.md").write_text("collision\n", encoding="utf-8")
            output = temp_root / "standalone.zip"

            package_result = self.run_packager(fixture_root, output)

            self.assertNotEqual(package_result.returncode, 0)
            self.assertIn("collides with an earlier entry", package_result.stderr)
            self.assertIn("Windows case-insensitive", package_result.stderr)

    @unittest.skipIf(sys.platform.startswith("win"), "fixture requires POSIX filename semantics")
    def test_packager_rejects_trailing_dot_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_repository_fixture(temp_root)
            skill_root = fixture_root / "skills" / "material-code-simplification"
            # Create a file with trailing dot that collides with an existing file
            (skill_root / "SKILL.md.").write_text("collision\n", encoding="utf-8")
            output = temp_root / "standalone.zip"

            package_result = self.run_packager(fixture_root, output)

            self.assertNotEqual(package_result.returncode, 0)
            self.assertIn("collides with an earlier entry", package_result.stderr)
            self.assertIn("trailing-character", package_result.stderr)

    @unittest.skipIf(sys.platform.startswith("win"), "fixture requires POSIX filename semantics")
    def test_packager_rejects_trailing_space_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_repository_fixture(temp_root)
            skill_root = fixture_root / "skills" / "material-code-simplification"
            # Create a file with trailing space that collides with an existing file
            (skill_root / "SKILL.md ").write_text("collision\n", encoding="utf-8")
            output = temp_root / "standalone.zip"

            package_result = self.run_packager(fixture_root, output)

            self.assertNotEqual(package_result.returncode, 0)
            self.assertIn("collides with an earlier entry", package_result.stderr)
            self.assertIn("trailing-character", package_result.stderr)


if __name__ == "__main__":
    unittest.main()
