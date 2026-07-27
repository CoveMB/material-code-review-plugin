from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGER = REPOSITORY_ROOT / "scripts" / "package_simplification_skill.py"
FULL_PACKAGER = REPOSITORY_ROOT / "scripts" / "package_plugin.py"
PACKAGE_VALIDATOR = REPOSITORY_ROOT / "scripts" / "validate_package.py"
REVIEW_VALIDATOR = REPOSITORY_ROOT / "skills" / "material-code-review" / "scripts" / "validate_package.py"
SIMPLIFICATION_VALIDATOR = (
    REPOSITORY_ROOT / "skills" / "material-code-simplification" / "scripts" / "validate_package.py"
)
DISTRIBUTION_LAYOUT = os.environ.get("MATERIAL_REVIEW_DISTRIBUTION_LAYOUT") == "1"


class StandalonePackagingTests(unittest.TestCase):
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
                "",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
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

    def replace_once(self, path: Path, original: str, replacement: str) -> None:
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count(original), 1, f"expected one occurrence in {path}")
        path.write_text(text.replace(original, replacement, 1), encoding="utf-8")

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

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_source_validator_requires_executable_evaluator_wrapper(self) -> None:
        for mutation in ("missing", "not executable"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp_directory:
                fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
                wrapper = fixture_root / "bin/material-review-evaluate"
                if mutation == "missing":
                    wrapper.unlink(missing_ok=True)
                else:
                    wrapper.parent.mkdir(parents=True, exist_ok=True)
                    wrapper.write_text(
                        "#!/usr/bin/env bash\nexit 0\n",
                        encoding="utf-8",
                    )
                    wrapper.chmod(0o644)

                validation_result = self.run_package_validator(fixture_root)

                self.assertNotEqual(validation_result.returncode, 0)
                self.assertIn("bin/material-review-evaluate", validation_result.stderr)

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_source_validator_still_validates_committed_evaluation_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
            manifest = (
                fixture_root
                / "evaluations/material-code-review/benchmarks/discogs-album-recovery/manifest.json"
            )
            manifest.write_text("{ invalid evaluation JSON\n", encoding="utf-8")

            validation_result = self.run_package_validator(
                fixture_root,
                distribution_layout=False,
            )

            self.assertNotEqual(validation_result.returncode, 0)
            self.assertIn(
                "evaluations/material-code-review/benchmarks/"
                "discogs-album-recovery/manifest.json",
                validation_result.stderr,
            )

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_source_validator_requires_evaluator_test_module(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
            evaluator_tests = (
                fixture_root / "scripts/tests/test_evaluate_material_review.py"
            )
            evaluator_tests.unlink()

            validation_result = self.run_package_validator(
                fixture_root,
                distribution_layout=False,
            )

            self.assertNotEqual(validation_result.returncode, 0)
            self.assertIn(
                "missing required file: scripts/tests/test_evaluate_material_review.py",
                validation_result.stderr,
            )

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
                "evaluations",
                "bin/material-review-evaluate",
                "scripts/evaluate_material_review.py",
                "scripts/material_review_evaluation",
                "scripts/tests/test_evaluate_material_review.py",
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
                "missing required file: bin/material-review-evaluate",
                validation_result.stderr,
            )

    def test_archive_validator_rejects_maintainer_only_evaluator_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            output = temp_root / "full-plugin.zip"
            package_result = self.run_full_packager(fixture_root, output)
            self.assertEqual(package_result.returncode, 0, package_result.stderr)
            with zipfile.ZipFile(output, "a") as archive:
                archive.writestr("evaluations/private-scratch.json", "{}\n")

            validation_result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(PACKAGE_VALIDATOR),
                    "--package-root",
                    str(fixture_root),
                    *(["--distribution-layout"] if DISTRIBUTION_LAYOUT else []),
                    "--full-archive",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            self.assertNotEqual(validation_result.returncode, 0)
            self.assertIn(
                "forbidden maintainer-only archive entry evaluations/private-scratch.json",
                validation_result.stderr,
            )

    def test_extracted_full_archive_runs_retained_validation_surface(self) -> None:
        if DISTRIBUTION_LAYOUT:
            for relative in (
                "bin/material-review-evaluate",
                "scripts/evaluate_material_review.py",
                "scripts/material_review_evaluation",
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
            archive_path = temp_root / "full-plugin.zip"
            package_result = self.run_full_packager(fixture_root, archive_path)
            self.assertEqual(package_result.returncode, 0, package_result.stderr)
            extracted_root = temp_root / "extracted"
            self.extract_archive_with_modes(archive_path, extracted_root)

            for relative in (
                "bin/material-review-evaluate",
                "scripts/evaluate_material_review.py",
                "scripts/material_review_evaluation",
                "scripts/tests/test_evaluate_material_review.py",
                "evaluations",
            ):
                self.assertFalse((extracted_root / relative).exists(), relative)

            validation_result = subprocess.run(
                ["make", "validate"],
                cwd=extracted_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )

            self.assertEqual(
                validation_result.returncode,
                0,
                validation_result.stdout + validation_result.stderr,
            )
            self.assertIn(
                "material-code-review package 1.2.0 is structurally valid",
                validation_result.stdout,
            )
            combined_output = validation_result.stdout + validation_result.stderr
            self.assertIn(
                "test_archive_validator_rejects_unsafe_and_incomplete_archives",
                combined_output,
            )
            self.assertRegex(
                combined_output,
                r"test_source_validator_requires_evaluator_test_module .* skipped ",
            )

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer evaluator is absent from distribution layouts",
    )
    def test_make_evaluator_requires_explicit_configuration_and_is_not_in_validation(
        self,
    ) -> None:
        for missing_variable in ("MODEL", "REASONING_EFFORT"):
            with self.subTest(missing=missing_variable):
                variables = {
                    "BASE_REF": "origin/main",
                    "CANDIDATE_REF": "HEAD",
                    "BENCHMARK": "discogs-album-recovery",
                    "MODEL": "gpt-5.6-sol",
                    "REASONING_EFFORT": "high",
                }
                variables.pop(missing_variable)
                result = subprocess.run(
                    [
                        "make",
                        "evaluate-review",
                        *(f"{name}={value}" for name, value in variables.items()),
                    ],
                    cwd=REPOSITORY_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn(
                    "BASE_REF, CANDIDATE_REF, BENCHMARK, MODEL, and REASONING_EFFORT are required",
                    result.stderr,
                )

        dry_run = subprocess.run(
            ["make", "-n", "validate"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        self.assertIn("scripts/evaluate_material_review.py", dry_run.stdout)
        self.assertIn("scripts/material_review_evaluation", dry_run.stdout)
        self.assertIn("bash -n bin/material-reviewctl bin/material-review-evaluate", dry_run.stdout)
        self.assertNotIn("scripts/evaluate_material_review.py compare", dry_run.stdout)

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

    def test_simplification_archive_ships_repair_direction_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_repository_fixture(temp_root)
            output = temp_root / "standalone.zip"

            package_result = self.run_packager(fixture_root, output)

            self.assertEqual(package_result.returncode, 0, package_result.stderr)
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
            self.assertTrue(
                {
                    "core/references/remediation-auditor-template.md",
                    "core/references/remediation-rubric.md",
                    "core/references/test-evidence-rubric.md",
                }.issubset(names)
            )

    def test_release_versions_are_aligned_and_independent(self) -> None:
        full_version = "1.2.0"
        simplification_version = "1.1.0"

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

        full_surfaces = (
            "scripts/package_plugin.py",
            "scripts/validate_package.py",
            "skills/material-code-review/scripts/reviewctl.py",
            "skills/material-code-review/scripts/validate_package.py",
        )
        for relative in full_surfaces:
            self.assertIn(full_version, (REPOSITORY_ROOT / relative).read_text(encoding="utf-8"))

        simplification_surfaces = (
            "scripts/package_simplification_skill.py",
            "skills/material-code-simplification/scripts/simplifyctl.py",
            "skills/material-code-simplification/scripts/validate_package.py",
        )
        for relative in simplification_surfaces:
            self.assertIn(
                simplification_version,
                (REPOSITORY_ROOT / relative).read_text(encoding="utf-8"),
            )

        self.assertNotEqual(full_version, simplification_version)

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

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "case-only collision is a source-checkout packaging fixture",
    )
    @unittest.skipIf(sys.platform.startswith("win"), "fixture requires POSIX filename semantics")
    def test_packager_rejects_case_only_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
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
