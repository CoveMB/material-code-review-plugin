from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGER = REPOSITORY_ROOT / "scripts" / "package_simplification_skill.py"
PACKAGE_VALIDATOR = REPOSITORY_ROOT / "scripts" / "validate_package.py"
SIMPLIFICATION_VALIDATOR = (
    REPOSITORY_ROOT / "skills" / "material-code-simplification" / "scripts" / "validate_package.py"
)


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

    def run_package_validator(self, fixture_root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(PACKAGE_VALIDATOR), "--package-root", str(fixture_root)],
            capture_output=True,
            text=True,
            check=False,
        )

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
