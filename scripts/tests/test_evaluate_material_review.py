from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path, PurePosixPath
from subprocess import CompletedProcess, TimeoutExpired
from types import SimpleNamespace

from scripts.material_review_evaluation.benchmark import CommandSpec, load_benchmark
from scripts.material_review_evaluation.artifacts import (
    NATIVE_SCHEMA_PROFILES,
    find_native_run,
    gate_a_command,
    gate_b_command,
    normalize_trial_evidence,
    validate_gate_a_artifacts,
    validate_gate_b_artifacts,
)
from scripts.material_review_evaluation.model import (
    EvaluationError,
    canonical_hash,
    safe_relative_path,
    sha256_file,
)
from scripts.material_review_evaluation.bundles import (
    build_agreement_bundle,
    build_comparison_bundle,
    build_trial_request,
    redact_machine_paths,
    scan_blinded_bundle,
)
from scripts.material_review_evaluation.executor import (
    CodexExecutor,
    InfrastructureFailure,
    SessionResult,
    SessionSpec,
)
from scripts.material_review_evaluation.workspace import (
    WorkspaceRecord,
    attest_clean_target,
    clean_owned_workspaces,
    create_trial_target,
    materialize_variant,
    prepare_target_mirror,
    resolve_variant,
    run_benchmark_commands,
    verify_benchmark_range,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVALUATION_ROOT = REPOSITORY_ROOT / "evaluations" / "material-code-review"


class BenchmarkLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def copy_benchmark(self) -> Path:
        copied_evaluation_root = (
            Path(self.temporary_directory.name) / "material-code-review"
        )
        shutil.copytree(EVALUATION_ROOT, copied_evaluation_root)
        return copied_evaluation_root / "benchmarks" / "discogs-album-recovery"

    def mutate_manifest(self, benchmark_root: Path, mutate: object) -> None:
        manifest_path = benchmark_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        mutate(manifest)  # type: ignore[operator]
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_discogs_benchmark_loads_exact_frozen_contract(self) -> None:
        benchmark = load_benchmark(EVALUATION_ROOT, "discogs-album-recovery")

        self.assertEqual(
            benchmark.target_repository,
            "https://github.com/CoveMB/discogs-collection.git",
        )
        self.assertEqual(
            benchmark.baseline_sha,
            "4e59c674dae10a4edcb8952818364c6faa255389",
        )
        self.assertEqual(
            benchmark.comparison_sha,
            "42a74b8619054800eca8502d8a687d3c98102565",
        )
        self.assertTrue(benchmark.require_immediate_parent)
        self.assertEqual(benchmark.review_mode, "range")
        self.assertEqual(benchmark.posture, "immutable")
        self.assertFalse(benchmark.include_untracked)
        self.assertEqual(benchmark.initial_trials, 2)
        self.assertTrue(benchmark.conditional_third)
        self.assertEqual(benchmark.infrastructure_retry_limit, 1)
        self.assertEqual(
            benchmark.gate_a_policy,
            "approve_all_retained_for_planning",
        )
        self.assertEqual(
            benchmark.gate_b_policy,
            "approve_validated_plan_no_repair",
        )
        self.assertEqual(
            tuple(command.argv for command in benchmark.dependency_installation_commands),
            (("npm", "ci", "--ignore-scripts"),),
        )
        self.assertEqual(
            tuple(command.argv for command in benchmark.baseline_validation_commands),
            (
                ("python3", "scripts/dev_checks.py", "--all"),
                ("python3", "-m", "compileall", "-q", "scripts", "tests"),
                ("npm", "run", "typecheck"),
                ("python3", "-m", "unittest", "discover", "-s", "tests"),
            ),
        )
        self.assertIn("causal_evidence", benchmark.required_lenses)
        self.assertIn("negative_controls", benchmark.required_lenses)
        self.assertEqual(
            benchmark.executor_isolation_modes,
            ("filesystem_blinding", "logical_blinding"),
        )
        self.assertIsInstance(benchmark.prohibitions, frozenset)
        self.assertIsInstance(benchmark.baseline_validation_commands, tuple)
        with self.assertRaises(FrozenInstanceError):
            benchmark.initial_trials = 3  # type: ignore[misc]
        with self.assertRaises(TypeError):
            benchmark.file_hashes["review_request_sha256"] = "0" * 64  # type: ignore[index]

    def test_prompt_hash_mismatch_is_rejected(self) -> None:
        benchmark_root = self.copy_benchmark()
        (benchmark_root / "review-request.md").write_text("changed\n", encoding="utf-8")

        with self.assertRaisesRegex(EvaluationError, "review_request_sha256"):
            load_benchmark(benchmark_root.parent.parent, benchmark_root.name)

    def test_oracle_hash_mismatch_is_rejected(self) -> None:
        benchmark_root = self.copy_benchmark()
        (benchmark_root / "judge-oracle.json").write_text("{}\n", encoding="utf-8")

        with self.assertRaisesRegex(EvaluationError, "judge_oracle_sha256"):
            load_benchmark(benchmark_root.parent.parent, benchmark_root.name)

    def test_rubric_hash_mismatch_is_rejected(self) -> None:
        benchmark_root = self.copy_benchmark()
        (benchmark_root.parent.parent / "judge-rubric.md").write_text(
            "changed\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(EvaluationError, "judge_rubric_sha256"):
            load_benchmark(benchmark_root.parent.parent, benchmark_root.name)

    def test_moving_target_ref_is_rejected(self) -> None:
        benchmark_root = self.copy_benchmark()
        self.mutate_manifest(
            benchmark_root,
            lambda manifest: manifest.__setitem__("comparison_sha", "main"),
        )

        with self.assertRaisesRegex(EvaluationError, "comparison_sha"):
            load_benchmark(benchmark_root.parent.parent, benchmark_root.name)

    def test_non_lowercase_git_sha_is_rejected(self) -> None:
        benchmark_root = self.copy_benchmark()
        self.mutate_manifest(
            benchmark_root,
            lambda manifest: manifest.__setitem__("baseline_sha", "A" * 40),
        )

        with self.assertRaisesRegex(EvaluationError, "baseline_sha"):
            load_benchmark(benchmark_root.parent.parent, benchmark_root.name)

    def test_non_https_repository_url_is_rejected(self) -> None:
        benchmark_root = self.copy_benchmark()
        self.mutate_manifest(
            benchmark_root,
            lambda manifest: manifest.__setitem__(
                "target_repository",
                "git@github.com:CoveMB/discogs-collection.git",
            ),
        )

        with self.assertRaisesRegex(EvaluationError, "target_repository"):
            load_benchmark(benchmark_root.parent.parent, benchmark_root.name)

    def test_private_https_repository_url_is_rejected(self) -> None:
        benchmark_root = self.copy_benchmark()
        self.mutate_manifest(
            benchmark_root,
            lambda manifest: manifest.__setitem__(
                "target_repository",
                "https://10.0.0.1/discogs-collection.git",
            ),
        )

        with self.assertRaisesRegex(EvaluationError, "target_repository"):
            load_benchmark(benchmark_root.parent.parent, benchmark_root.name)

    def test_unsafe_working_directory_is_rejected(self) -> None:
        benchmark_root = self.copy_benchmark()
        self.mutate_manifest(
            benchmark_root,
            lambda manifest: manifest["baseline_validation_commands"][0].__setitem__(
                "working_directory",
                "../outside",
            ),
        )

        with self.assertRaisesRegex(EvaluationError, "working_directory"):
            load_benchmark(benchmark_root.parent.parent, benchmark_root.name)

    def test_absolute_working_directory_is_rejected(self) -> None:
        benchmark_root = self.copy_benchmark()
        self.mutate_manifest(
            benchmark_root,
            lambda manifest: manifest["baseline_validation_commands"][0].__setitem__(
                "working_directory",
                "/tmp",
            ),
        )

        with self.assertRaisesRegex(EvaluationError, "working_directory"):
            load_benchmark(benchmark_root.parent.parent, benchmark_root.name)

    def test_windows_absolute_working_directory_is_rejected(self) -> None:
        benchmark_root = self.copy_benchmark()
        self.mutate_manifest(
            benchmark_root,
            lambda manifest: manifest["baseline_validation_commands"][0].__setitem__(
                "working_directory",
                "C:/target",
            ),
        )

        with self.assertRaisesRegex(EvaluationError, "working_directory"):
            load_benchmark(benchmark_root.parent.parent, benchmark_root.name)

    def test_shell_metacharacters_in_command_are_rejected(self) -> None:
        benchmark_root = self.copy_benchmark()
        self.mutate_manifest(
            benchmark_root,
            lambda manifest: manifest["baseline_validation_commands"][0][
                "argv"
            ].append(";touch"),
        )

        with self.assertRaisesRegex(EvaluationError, "shell metacharacter"):
            load_benchmark(benchmark_root.parent.parent, benchmark_root.name)

    def test_command_control_characters_are_rejected(self) -> None:
        benchmark_root = self.copy_benchmark()
        self.mutate_manifest(
            benchmark_root,
            lambda manifest: manifest["baseline_validation_commands"][0][
                "argv"
            ].append("unsafe\nargument"),
        )

        with self.assertRaisesRegex(EvaluationError, "control character"):
            load_benchmark(benchmark_root.parent.parent, benchmark_root.name)

    def test_command_executable_outside_allowlist_is_rejected(self) -> None:
        benchmark_root = self.copy_benchmark()
        self.mutate_manifest(
            benchmark_root,
            lambda manifest: manifest["baseline_validation_commands"][0][
                "argv"
            ].__setitem__(0, "bash"),
        )

        with self.assertRaisesRegex(EvaluationError, "executable"):
            load_benchmark(benchmark_root.parent.parent, benchmark_root.name)

    def test_missing_no_repair_prohibition_is_rejected(self) -> None:
        benchmark_root = self.copy_benchmark()
        self.mutate_manifest(
            benchmark_root,
            lambda manifest: manifest["prohibitions"].remove("repair"),
        )

        with self.assertRaisesRegex(EvaluationError, "repair"):
            load_benchmark(benchmark_root.parent.parent, benchmark_root.name)

    def test_unsupported_schema_version_is_rejected(self) -> None:
        benchmark_root = self.copy_benchmark()
        self.mutate_manifest(
            benchmark_root,
            lambda manifest: manifest.__setitem__(
                "schema",
                "material-review-evaluation/benchmark/v2",
            ),
        )

        with self.assertRaisesRegex(EvaluationError, "schema"):
            load_benchmark(benchmark_root.parent.parent, benchmark_root.name)


class SharedPrimitiveTests(unittest.TestCase):
    def test_safe_relative_path_accepts_repository_root(self) -> None:
        self.assertEqual(safe_relative_path(".", "working_directory").as_posix(), ".")

    def test_safe_relative_path_rejects_parent_traversal(self) -> None:
        with self.assertRaisesRegex(EvaluationError, "working_directory"):
            safe_relative_path("target/../../outside", "working_directory")


class WorkspaceManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.repository_root = self.root / "active-repository"
        self.workspace_root = self.root / "owned-workspaces"
        self.workspace_root.mkdir()
        self.run_git(self.repository_root, "init", "--quiet")
        self.run_git(self.repository_root, "config", "user.name", "Evaluator Tests")
        self.run_git(self.repository_root, "config", "user.email", "evaluator@example.invalid")
        (self.repository_root / "active.txt").write_text("active\n", encoding="utf-8")
        self.run_git(self.repository_root, "add", "active.txt")
        self.run_git(self.repository_root, "commit", "--quiet", "-m", "active")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def run_git(self, repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        repository.mkdir(parents=True, exist_ok=True)
        return subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def git(self, repository: Path, *arguments: str) -> str:
        return self.run_git(repository, *arguments).stdout.strip()

    def commit_file(
        self,
        repository: Path,
        relative_path: str,
        contents: str,
        subject: str = "later",
    ) -> str:
        path = repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        self.run_git(repository, "add", relative_path)
        self.run_git(repository, "commit", "--quiet", "-m", subject)
        return self.git(repository, "rev-parse", "HEAD")

    def create_skill_repository(self) -> Path:
        repository = self.root / (
            f"skill-repository-{len(list(self.root.glob('skill-repository-*')))}"
        )
        self.run_git(repository, "init", "--quiet")
        self.run_git(repository, "config", "user.name", "Evaluator Tests")
        self.run_git(repository, "config", "user.email", "evaluator@example.invalid")

        package_script = textwrap.dedent(
            """\
            import argparse
            import zipfile
            from pathlib import Path

            parser = argparse.ArgumentParser()
            parser.add_argument("--package-root", required=True)
            parser.add_argument("--output", required=True)
            parser.add_argument("--standalone-output", required=True)
            arguments = parser.parse_args()
            root = Path(arguments.package_root)
            with zipfile.ZipFile(arguments.output, "w") as archive:
                archive.writestr("discarded-full.txt", "full archive")
            with zipfile.ZipFile(arguments.standalone_output, "w") as archive:
                archive.writestr(
                    "SKILL.md",
                    (root / "skills/material-code-review/SKILL.md").read_text(),
                )
                archive.writestr("materialized-commit.txt", root.name + "\\n")
            """
        )
        validate_script = textwrap.dedent(
            """\
            import argparse
            import zipfile

            parser = argparse.ArgumentParser()
            parser.add_argument("--package-root", required=True)
            parser.add_argument("--standalone-archive", required=True)
            arguments = parser.parse_args()
            with zipfile.ZipFile(arguments.standalone_archive, "a") as archive:
                if "SKILL.md" not in archive.namelist():
                    raise SystemExit(1)
                archive.writestr("validator-ran.txt", "yes\\n")
            """
        )
        files = {
            "scripts/package_plugin.py": package_script,
            "scripts/validate_package.py": validate_script,
            "skills/material-code-review/SKILL.md": "historical workflow\n",
            ".codex-plugin/plugin.json": "{}\n",
            "evaluations/material-code-review/judge-oracle.json": "secret oracle\n",
            "scripts/material_review_evaluation/private.py": "evaluator only\n",
            "other-variant.txt": "not workflow content\n",
        }
        for relative_path, contents in files.items():
            path = repository / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")
        self.run_git(repository, "add", ".")
        self.run_git(repository, "commit", "--quiet", "-m", "historical workflow")
        self.run_git(repository, "branch", "candidate")
        return repository

    def create_target_repository(self, *, commits: int = 2) -> tuple[Path, tuple[str, ...]]:
        repository = self.root / (
            f"target-repository-{len(list(self.root.glob('target-repository-*')))}"
        )
        self.run_git(repository, "init", "--quiet")
        self.run_git(repository, "config", "user.name", "Evaluator Tests")
        self.run_git(repository, "config", "user.email", "evaluator@example.invalid")
        shas = [self.commit_file(repository, "tracked.txt", "one\n", "baseline")]
        for number in range(2, commits + 1):
            shas.append(
                self.commit_file(
                    repository,
                    "tracked.txt",
                    f"{number}\n",
                    f"comparison {number}",
                )
            )
        return repository, tuple(shas)

    def make_benchmark(self, baseline: str, comparison: str) -> object:
        return SimpleNamespace(baseline_sha=baseline, comparison_sha=comparison)

    def make_owned_workspace(self, trial_id: str = "trial-one") -> WorkspaceRecord:
        target, shas = self.create_target_repository()
        run_id = f"run-{trial_id}"
        mirror = prepare_target_mirror(target, self.workspace_root, run_id)
        benchmark = self.make_benchmark(shas[0], shas[1])
        verify_benchmark_range(mirror.path, benchmark)  # type: ignore[arg-type]
        return create_trial_target(
            mirror.path,
            benchmark,  # type: ignore[arg-type]
            self.workspace_root,
            run_id,
            trial_id,
        )

    def test_refs_resolve_once_to_sha_and_subject_hash(self) -> None:
        repository = self.create_skill_repository()

        resolved = resolve_variant(repository, "candidate")

        self.assertRegex(resolved.commit_sha, r"^[0-9a-f]{40}$")
        self.assertEqual(resolved.commit_sha, self.git(repository, "rev-parse", "candidate"))
        self.assertEqual(
            resolved.commit_subject_sha256,
            hashlib.sha256(b"historical workflow").hexdigest(),
        )

    def test_resolved_variant_remains_bound_after_ref_moves(self) -> None:
        repository = self.create_skill_repository()
        original = resolve_variant(repository, "candidate")
        self.commit_file(repository, "later.txt", "later\n")
        self.run_git(repository, "branch", "-f", "candidate", "HEAD")
        self.assertNotEqual(self.git(repository, "rev-parse", "candidate"), original.commit_sha)

        materialized = materialize_variant(
            repository,
            original,
            self.workspace_root,
            "run-one",
        )

        self.assertEqual(
            (materialized.path / "materialized-commit.txt").read_text().strip(),
            original.commit_sha,
        )

    def test_non_parent_benchmark_pair_is_rejected(self) -> None:
        target, shas = self.create_target_repository(commits=3)
        mirror = prepare_target_mirror(target, self.workspace_root, "run-one")

        with self.assertRaisesRegex(EvaluationError, "immediate parent"):
            verify_benchmark_range(
                mirror.path,
                self.make_benchmark(shas[0], shas[2]),  # type: ignore[arg-type]
            )

    def test_materialization_uses_historical_packager_and_exposes_only_workflow(self) -> None:
        repository = self.create_skill_repository()
        variant = resolve_variant(repository, "candidate")

        record = materialize_variant(repository, variant, self.workspace_root, "run-one")

        self.assertEqual((record.path / "validator-ran.txt").read_text(), "yes\n")
        self.assertFalse((record.path / ".git").exists())
        self.assertFalse((record.path / "evaluations").exists())
        self.assertFalse((record.path / "scripts/material_review_evaluation").exists())
        self.assertFalse((record.path / "judge-oracle.json").exists())
        self.assertFalse((record.path / "other-variant.txt").exists())
        run_root = self.workspace_root / "run-one"
        self.assertFalse(
            any(
                path.name == variant.commit_sha
                for path in (run_root / "sources").glob("*")
            )
        )
        self.assertFalse(
            any(path.name.startswith("discarded-full") for path in run_root.rglob("*"))
        )

    def test_materialization_rejects_symlink_from_git_archive(self) -> None:
        repository = self.create_skill_repository()
        os.symlink("SKILL.md", repository / "skills/material-code-review/link")
        self.run_git(repository, "add", "skills/material-code-review/link")
        self.run_git(repository, "commit", "--quiet", "-m", "unsafe archive")
        variant = resolve_variant(repository, "HEAD")

        with self.assertRaisesRegex(EvaluationError, "symlink"):
            materialize_variant(repository, variant, self.workspace_root, "run-two")

    def test_materialization_rejects_windows_drive_relative_tar_member(self) -> None:
        repository = self.create_skill_repository()
        self.commit_file(repository, "C:escape.txt", "outside\n", "unsafe TAR path")
        variant = resolve_variant(repository, "HEAD")

        with self.assertRaisesRegex(EvaluationError, "Windows drive"):
            materialize_variant(repository, variant, self.workspace_root, "run-tar")

    def test_materialization_rejects_evaluator_content_from_standalone_archive(self) -> None:
        repository = self.create_skill_repository()
        package_script = repository / "scripts/package_plugin.py"
        contents = package_script.read_text(encoding="utf-8")
        package_script.write_text(
            contents.replace(
                'archive.writestr("materialized-commit.txt", root.name + "\\n")',
                'archive.writestr("materialized-commit.txt", root.name + "\\n")\n'
                '    archive.writestr('
                '"evaluations/material-code-review/judge-oracle.json", "secret")',
            ),
            encoding="utf-8",
        )
        self.run_git(repository, "add", "scripts/package_plugin.py")
        self.run_git(repository, "commit", "--quiet", "-m", "unsafe standalone")
        variant = resolve_variant(repository, "HEAD")

        with self.assertRaisesRegex(EvaluationError, "evaluator or oracle"):
            materialize_variant(repository, variant, self.workspace_root, "run-three")

    def test_materialization_rejects_windows_drive_relative_zip_member(self) -> None:
        repository = self.create_skill_repository()
        package_script = repository / "scripts/package_plugin.py"
        contents = package_script.read_text(encoding="utf-8")
        package_script.write_text(
            contents.replace(
                'archive.writestr("materialized-commit.txt", root.name + "\\n")',
                'archive.writestr("materialized-commit.txt", root.name + "\\n")\n'
                '    archive.writestr("C:escape.txt", "outside")',
            ),
            encoding="utf-8",
        )
        self.run_git(repository, "add", "scripts/package_plugin.py")
        self.run_git(repository, "commit", "--quiet", "-m", "unsafe ZIP path")
        variant = resolve_variant(repository, "HEAD")

        with self.assertRaisesRegex(EvaluationError, "Windows drive"):
            materialize_variant(repository, variant, self.workspace_root, "run-zip")

    def test_trial_clone_is_detached_at_comparison_and_uses_owned_mirror(self) -> None:
        target, shas = self.create_target_repository()
        mirror = prepare_target_mirror(target, self.workspace_root, "run-one")
        benchmark = self.make_benchmark(shas[0], shas[1])

        record = create_trial_target(
            mirror.path,
            benchmark,  # type: ignore[arg-type]
            self.workspace_root,
            "run-one",
            "trial-one",
        )
        attestation = attest_clean_target(record)

        self.assertEqual(self.git(record.path, "rev-parse", "HEAD"), shas[1])
        self.assertEqual(attestation["branch"], "")
        self.assertEqual(attestation["remote_url"], str(mirror.path.resolve()))

    def test_cleanliness_attestation_detects_git_and_remote_changes(self) -> None:
        mutations = {
            "branch": lambda path: self.run_git(path, "switch", "--quiet", "-c", "changed"),
            "HEAD": lambda path: self.run_git(
                path, "commit", "--quiet", "--allow-empty", "-m", "changed"
            ),
            "index": lambda path: (
                (path / "tracked.txt").write_text("index\n", encoding="utf-8"),
                self.run_git(path, "add", "tracked.txt"),
            ),
            "worktree": lambda path: (path / "tracked.txt").write_text(
                "worktree\n", encoding="utf-8"
            ),
            "remote URL": lambda path: self.run_git(
                path,
                "remote",
                "set-url",
                "origin",
                str(self.root / "elsewhere"),
            ),
        }

        for number, (expected_message, mutate) in enumerate(mutations.items()):
            with self.subTest(change=expected_message):
                record = self.make_owned_workspace(f"trial-{number}")
                mutate(record.path)
                with self.assertRaisesRegex(EvaluationError, expected_message):
                    attest_clean_target(record)

    def test_cleanliness_attestation_detects_assume_unchanged_mutation(self) -> None:
        record = self.make_owned_workspace("trial-assume-unchanged")
        self.run_git(record.path, "update-index", "--assume-unchanged", "tracked.txt")
        (record.path / "tracked.txt").write_text("hidden change\n", encoding="utf-8")
        self.assertEqual(self.git(record.path, "status", "--porcelain=v1"), "")

        with self.assertRaisesRegex(EvaluationError, "index"):
            attest_clean_target(record)

    def test_benchmark_commands_record_separate_logs_hashes_and_timeout(self) -> None:
        target = self.root / "command-target"
        target.mkdir()
        (target / "emit.py").write_text(
            "import sys\n"
            "print('standard output')\n"
            "print('standard error', file=sys.stderr)\n"
            "raise SystemExit(3)\n",
            encoding="utf-8",
        )
        (target / "slow.py").write_text("import time\ntime.sleep(2)\n", encoding="utf-8")
        commands = (
            CommandSpec(("python3", "emit.py"), PurePosixPath("."), 5),
            CommandSpec(("python3", "slow.py"), PurePosixPath("."), 1),
        )

        results = run_benchmark_commands(target, commands, self.root / "command-logs")

        self.assertEqual(tuple(result.returncode for result in results), (3, 124))
        first_stdout = Path(results[0].stdout_path)
        first_stderr = Path(results[0].stderr_path)
        self.assertNotEqual(first_stdout, first_stderr)
        self.assertEqual(first_stdout.read_text(), "standard output\n")
        self.assertEqual(first_stderr.read_text(), "standard error\n")
        evidence = json.loads((self.root / "command-logs/command-000.json").read_text())
        self.assertEqual(evidence["stdout_sha256"], sha256_file(first_stdout))
        self.assertEqual(evidence["stderr_sha256"], sha256_file(first_stderr))
        self.assertEqual(
            evidence["normalized_failure_signature"],
            canonical_hash(
                {
                    "argv": ["python3", "emit.py"],
                    "returncode": 3,
                    "stdout": "standard output\n",
                    "stderr": "standard error\n",
                    "timed_out": False,
                }
            ),
        )

    def test_benchmark_commands_reject_working_directory_escape(self) -> None:
        target = self.root / "command-target"
        target.mkdir()
        command = CommandSpec(("python3", "missing.py"), PurePosixPath("../outside"), 5)

        with self.assertRaisesRegex(EvaluationError, "working directory"):
            run_benchmark_commands(target, (command,), self.root / "command-logs")

    def test_cleanup_refuses_unrecorded_path_and_repository_root(self) -> None:
        record = self.make_owned_workspace()
        unrecorded = record.path.parent / "unrecorded"
        shutil.copytree(record.path, unrecorded)

        with self.assertRaisesRegex(EvaluationError, "not recorded"):
            clean_owned_workspaces(self.repository_root, (replace(record, path=unrecorded),))
        with self.assertRaisesRegex(EvaluationError, "active repository"):
            clean_owned_workspaces(
                self.repository_root,
                (replace(record, path=self.repository_root),),
            )

    def test_cleanup_refuses_changed_recorded_workspace(self) -> None:
        record = self.make_owned_workspace()
        (record.path / "unexpected.txt").write_text("changed\n", encoding="utf-8")

        with self.assertRaisesRegex(EvaluationError, "unrecorded changes"):
            clean_owned_workspaces(self.repository_root, (record,))

    def test_cleanup_refuses_symlinked_workspace(self) -> None:
        record = self.make_owned_workspace()
        replacement = self.root / "replacement"
        replacement.mkdir()
        shutil.rmtree(record.path)
        record.path.symlink_to(replacement, target_is_directory=True)

        with self.assertRaisesRegex(EvaluationError, "symlink"):
            clean_owned_workspaces(self.repository_root, (record,))

    def test_cleanup_refuses_symlinked_run_root(self) -> None:
        target, _ = self.create_target_repository()
        outside = self.root / "outside-run"
        outside.mkdir()
        run_root = self.workspace_root / "run-symlink"
        run_root.symlink_to(outside, target_is_directory=True)
        record = prepare_target_mirror(target, self.workspace_root, "run-symlink")
        outside_mirror = outside / "mirrors" / "target.git"
        self.assertTrue(outside_mirror.is_dir())

        with self.assertRaisesRegex(EvaluationError, "symlink"):
            clean_owned_workspaces(self.repository_root, (record,))
        self.assertTrue(outside_mirror.is_dir())

    def test_cleanup_removes_only_exact_clean_recorded_directories(self) -> None:
        first = self.make_owned_workspace("trial-first")
        second = self.make_owned_workspace("trial-second")
        unrelated = self.workspace_root / "unrelated" / "targets" / "untouched"
        unrelated.mkdir(parents=True)

        removed = clean_owned_workspaces(self.repository_root, (first, second))

        self.assertEqual(set(removed), {first.path, second.path})
        self.assertFalse(first.path.exists())
        self.assertFalse(second.path.exists())
        self.assertTrue(unrelated.is_dir())


class NativeArtifactTests(unittest.TestCase):
    PROFILE_CONTROLLERS = {
        (
            "material-review/state/v1",
            "material-review/ledger/v1",
            "material-review/fix-plan/v1",
        ): "4a94e9ef0c0cdf811517ece3051e6d0df6161e64",
        (
            "material-review/state/v1",
            "material-review/ledger/v2",
            "material-review/fix-plan/v1",
        ): "2da06282630a0d93062a0a67dc92066055644ff1",
        (
            "material-review/state/v1",
            "material-review/ledger/v3",
            "material-review/fix-plan/v2",
        ): "0ca2ee9980fa20646c041c26fa5dfe03c8f22c8b",
    }

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.workspace_root = self.root / "owned-workspaces"
        self.workspace_root.mkdir()
        self.source_repository = self.root / "source-repository"
        self.run_git(self.source_repository, "init", "--quiet")
        self.run_git(
            self.source_repository,
            "config",
            "user.name",
            "Artifact Evaluator Tests",
        )
        self.run_git(
            self.source_repository,
            "config",
            "user.email",
            "artifact-evaluator@example.invalid",
        )
        self.baseline_sha = self.commit_file("tracked.txt", "baseline\n", "baseline")
        self.comparison_sha = self.commit_file(
            "tracked.txt",
            "comparison\n",
            "comparison",
        )
        mirror = prepare_target_mirror(
            self.source_repository,
            self.workspace_root,
            "artifact-evaluation",
        )
        benchmark = SimpleNamespace(
            baseline_sha=self.baseline_sha,
            comparison_sha=self.comparison_sha,
        )
        self.target = create_trial_target(
            mirror.path,
            benchmark,  # type: ignore[arg-type]
            self.workspace_root,
            "artifact-evaluation",
            "trial-target",
        )
        self.fixture_number = 0

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def run_git(
        self,
        repository: Path,
        *arguments: str,
    ) -> subprocess.CompletedProcess[str]:
        repository.mkdir(parents=True, exist_ok=True)
        return subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def commit_file(self, relative_path: str, contents: str, subject: str) -> str:
        path = self.source_repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        self.run_git(self.source_repository, "add", relative_path)
        self.run_git(self.source_repository, "commit", "--quiet", "-m", subject)
        return self.run_git(
            self.source_repository,
            "rev-parse",
            "HEAD",
        ).stdout.strip()

    def write_json(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def read_json(self, path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))

    def materialize_controller(self, profile: tuple[str, str, str], root: Path) -> Path:
        commit = self.PROFILE_CONTROLLERS[profile]
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(REPOSITORY_ROOT),
                "show",
                f"{commit}:skills/material-code-review/scripts/reviewctl.py",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        controller = root / "materialized-workflow" / "scripts" / "reviewctl.py"
        controller.parent.mkdir(parents=True)
        controller.write_text(completed.stdout, encoding="utf-8")
        return controller

    def native_run(
        self,
        *,
        profile: tuple[str, str, str] | None = None,
        findings: tuple[str, ...] = ("F001",),
        phase: str = "ADJUDICATED",
    ) -> SimpleNamespace:
        selected_profile = profile or next(iter(self.PROFILE_CONTROLLERS))
        self.fixture_number += 1
        trial_root = self.root / f"native-trial-{self.fixture_number}"
        trial_root.mkdir()
        controller = self.materialize_controller(selected_profile, trial_root)
        artifact_root = trial_root / "native-artifacts"
        run_id = f"native-run-{self.fixture_number}"
        completed = subprocess.run(
            [
                "python3",
                str(controller),
                "init",
                "--repo-root",
                str(self.target.path),
                "--artifact-root",
                str(artifact_root),
                "--run-id",
                run_id,
                "--scope",
                "range",
                "--base",
                self.baseline_sha,
                "--head",
                self.comparison_sha,
                "--exclude-untracked",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        run_directory = artifact_root / "runs" / run_id
        state = self.read_json(run_directory / "state.json")
        scope = self.read_json(run_directory / "scope.json")
        scope_hash = scope["scope_hash"]

        candidate_records = []
        kept_groups = []
        ledger_findings = []
        for number, finding_id in enumerate(findings, start=1):
            group_id = f"G{number:03d}"
            candidate_id = f"C{number:03d}"
            candidate_records.append(
                {
                    "candidate_id": candidate_id,
                    "reviewer_id": "evaluation-reviewer",
                    "local_id": f"local-{number}",
                }
            )
            kept_groups.append(
                {
                    "group_id": group_id,
                    "candidate_ids": [candidate_id],
                    "disposition": "keep",
                }
            )
            finding = {
                "finding_id": finding_id,
                "group_id": group_id,
                "candidate_ids": [candidate_id],
                "title": f"Finding {finding_id}",
                "severity": "high",
                "confidence": "high",
                "file": "tracked.txt",
                "line_start": 1,
                "line_end": 1,
                "evidence_side": "comparison",
                "evidence_quote": "comparison",
                "observable_consequence": "observable failure",
                "trigger_conditions": ["comparison checkout"],
                "validation": {"verdict": "confirmed"},
                "materiality": {"material": True},
                "decision_reason": "material defect",
                "recommended_action": "fix_now",
                "required_pre_fix_verification": [],
            }
            if selected_profile[1] == "material-review/ledger/v3":
                repair_direction = {
                    "objective": "preserve the expected output",
                    "constraints": ["change only the scoped file"],
                }
                finding["repair_direction"] = repair_direction
                finding["repair_direction_hash"] = canonical_hash(repair_direction)
                finding["repair_audit"] = {
                    "mode": "independent",
                    "verdict": "approved",
                    "auditor_id": "evaluation-direction-auditor",
                }
            else:
                finding["proposed_resolution"] = "preserve the expected output"
            ledger_findings.append(finding)

        discarded_group = {
            "group_id": "G999",
            "candidate_ids": ["C999"],
            "canonical_title": "Unsupported candidate",
            "file": "tracked.txt",
            "line_start": 1,
            "line_end": 1,
            "evidence_side": "comparison",
            "evidence_quote": "comparison",
            "validation": {"verdict": "rejected"},
            "materiality": {"material": False},
            "disposition": "discard",
            "discard_reason": "EVIDENCE_MISMATCH",
            "decision_reason": "not supported",
        }
        candidate_records.append(
            {
                "candidate_id": "C999",
                "reviewer_id": "evaluation-reviewer",
                "local_id": "local-discarded",
            }
        )
        candidates = {
            "schema_version": "material-review/candidates-normalized/v1",
            "scope_hash": scope_hash,
            "reviewer_sets": [],
            "candidates": candidate_records,
            "rejections": [],
        }
        candidate_bundle_hash = canonical_hash(candidates)
        candidates["candidate_bundle_hash"] = candidate_bundle_hash
        candidates["generated_at"] = "2026-07-27T11:59:00Z"
        self.write_json(run_directory / "candidates.json", candidates)

        adjudication_versions = {
            "material-review/ledger/v1": "material-review/adjudication/v1",
            "material-review/ledger/v2": "material-review/adjudication/v2",
            "material-review/ledger/v3": "material-review/adjudication/v3",
        }
        adjudication = {
            "schema_version": adjudication_versions[selected_profile[1]],
            "scope_hash": scope_hash,
            "candidate_bundle_hash": candidate_bundle_hash,
            "groups": [*kept_groups, discarded_group],
        }
        self.write_json(run_directory / "adjudication.normalized.json", adjudication)

        ledger = {
            "schema_version": selected_profile[1],
            "scope_hash": scope_hash,
            "candidate_bundle_hash": candidate_bundle_hash,
            "adjudicator_id": "evaluation-adjudicator",
            "verdict": "SHOULD FIX BEFORE MERGE" if findings else "READY",
            "summary": "Invented native ledger for evaluator contract tests.",
            "findings": ledger_findings,
            "discarded": [discarded_group],
            "limitations": ["invented fixture"],
        }
        ledger_hash = canonical_hash(ledger)
        ledger["ledger_hash"] = ledger_hash
        ledger["generated_at"] = "2026-07-27T12:00:00Z"
        self.write_json(run_directory / "ledger.json", ledger)

        state["phase"] = phase
        state["hashes"]["candidate_bundle_hash"] = candidate_bundle_hash  # type: ignore[index]
        state["hashes"]["ledger_hash"] = ledger_hash  # type: ignore[index]
        state["approved_findings"] = []

        findings_gate = None
        if phase != "ADJUDICATED":
            findings_gate = {
                "schema_version": "material-review/findings-gate/v1",
                "run_id": run_id,
                "scope_hash": scope_hash,
                "ledger_hash": ledger_hash,
                "decisions": {
                    "approved": list(findings),
                    "rejected": [],
                    "deferred": [],
                    "accepted_empty": not findings,
                },
                "user_statement": (
                    "Evaluation policy approves every retained finding for planning and no "
                    "others; repair is not authorized."
                    if findings
                    else "Evaluation policy accepts the empty material ledger; repair is not "
                    "authorized."
                ),
                "recorded_at": "2026-07-27T12:01:00Z",
            }
            receipt_hash = canonical_hash(findings_gate)
            findings_gate["receipt_hash"] = receipt_hash
            self.write_json(run_directory / "gates" / "findings.json", findings_gate)
            state["gates"]["findings"] = receipt_hash  # type: ignore[index]
            state["hashes"]["findings_gate_hash"] = receipt_hash  # type: ignore[index]
            state["approved_findings"] = sorted(findings)

        plan = None
        if phase in {
            "PLAN_VALIDATED",
            "PLAN_APPROVED",
            "FIXING",
            "VERIFYING",
            "REPAIR_REQUIRED",
            "PLAN_AMENDMENT_REQUIRED",
            "BLOCKED",
        }:
            plan = {
                "schema_version": selected_profile[2],
                "scope_hash": scope_hash,
                "findings_gate_hash": findings_gate["receipt_hash"],  # type: ignore[index]
                "plan_summary": "Invented exact evaluation plan.",
                "items": [
                    {
                        "finding_id": finding_id,
                        "root_cause": "incorrect tracked content",
                        "objective": "restore the expected content",
                        **(
                            {
                                "repair_direction_assessment": {
                                    "repair_direction_hash": next(
                                        finding["repair_direction_hash"]
                                        for finding in ledger_findings
                                        if finding["finding_id"] == finding_id
                                    ),
                                    "alternatives_considered": ["leave unchanged"],
                                    "diverges": False,
                                }
                            }
                            if selected_profile[2] == "material-review/fix-plan/v2"
                            else {}
                        ),
                        "depends_on": [],
                        "steps": ["Edit the scoped tracked content."],
                        "allowed_paths": ["tracked.txt"],
                        "tests": [
                            {
                                "id": f"test-{finding_id}",
                                "command": "python3 -m unittest",
                                "working_directory": ".",
                                "required": True,
                                "timeout_seconds": 120,
                                "purpose": "Verify the scoped correction.",
                            }
                        ],
                        "manual_verification": [],
                        "risk_controls": ["exact path boundary"],
                        "rollback_strategy": "restore the checkpoint",
                        "success_evidence": ["required test passes"],
                        "max_attempts": 2,
                    }
                    for finding_id in findings
                ],
                "global_tests": [
                    {
                        "id": "global-tests",
                        "command": "python3 -m unittest",
                        "working_directory": ".",
                        "required": True,
                        "timeout_seconds": 300,
                        "purpose": "Verify the complete scoped plan.",
                    }
                ],
                "no_unrelated_cleanup": True,
                "no_new_improvements_during_fix": True,
                "post_fix_review_scope": (
                    "approved_findings_and_fix_introduced_regressions_only"
                ),
                "scope_expansion_policy": "restore_and_reapprove",
                "max_repair_rounds": 1,
            }
            plan_hash = canonical_hash(plan)
            plan["plan_hash"] = plan_hash
            plan["validated_at"] = "2026-07-27T12:02:00Z"
            self.write_json(run_directory / "fix-plan.json", plan)
            state["hashes"]["plan_hash"] = plan_hash  # type: ignore[index]

        if phase in {
            "PLAN_APPROVED",
            "FIXING",
            "VERIFYING",
            "REPAIR_REQUIRED",
            "PLAN_AMENDMENT_REQUIRED",
            "BLOCKED",
        }:
            plan_gate = {
                "schema_version": "material-review/plan-gate/v1",
                "run_id": run_id,
                "scope_hash": scope_hash,
                "findings_gate_hash": findings_gate["receipt_hash"],  # type: ignore[index]
                "plan_hash": plan["plan_hash"],  # type: ignore[index]
                "approved": True,
                "user_statement": (
                    "Evaluation policy approves this exact validated plan for comparison "
                    "evidence only; no repair or plan command execution is authorized."
                ),
                "recorded_at": "2026-07-27T12:03:00Z",
            }
            plan_receipt_hash = canonical_hash(plan_gate)
            plan_gate["receipt_hash"] = plan_receipt_hash
            self.write_json(run_directory / "gates" / "plan.json", plan_gate)
            state["gates"]["plan"] = plan_receipt_hash  # type: ignore[index]
            state["hashes"]["plan_gate_hash"] = plan_receipt_hash  # type: ignore[index]

        self.write_json(run_directory / "state.json", state)
        return SimpleNamespace(
            trial_root=trial_root,
            run_directory=run_directory,
            controller=controller,
            target=self.target,
            profile=selected_profile,
        )

    def native_artifacts(
        self,
        *,
        findings: tuple[str, ...] = ("F001",),
        phase: str = "ADJUDICATED",
        profile: tuple[str, str, str] | None = None,
    ) -> object:
        native_run = self.native_run(
            findings=findings,
            phase=phase,
            profile=profile,
        )
        if phase == "ADJUDICATED" or phase == "COMPLETE":
            return validate_gate_a_artifacts(
                native_run.run_directory,
                native_run.controller,
                native_run.target,
            )
        return validate_gate_b_artifacts(
            native_run.run_directory,
            native_run.controller,
            native_run.target,
        )

    def rehash_ledger(self, native_run: SimpleNamespace, ledger: dict[str, object]) -> None:
        payload = dict(ledger)
        payload.pop("ledger_hash", None)
        payload.pop("generated_at", None)
        ledger_hash = canonical_hash(payload)
        ledger["ledger_hash"] = ledger_hash
        self.write_json(native_run.run_directory / "ledger.json", ledger)
        state = self.read_json(native_run.run_directory / "state.json")
        state["hashes"]["ledger_hash"] = ledger_hash  # type: ignore[index]
        self.write_json(native_run.run_directory / "state.json", state)

    def rehash_receipt(
        self,
        native_run: SimpleNamespace,
        gate_name: str,
        state_hash_name: str,
    ) -> dict[str, object]:
        path = native_run.run_directory / "gates" / f"{gate_name}.json"
        receipt = self.read_json(path)
        receipt.pop("receipt_hash", None)
        receipt_hash = canonical_hash(receipt)
        receipt["receipt_hash"] = receipt_hash
        self.write_json(path, receipt)
        state = self.read_json(native_run.run_directory / "state.json")
        state["gates"][gate_name] = receipt_hash  # type: ignore[index]
        state["hashes"][state_hash_name] = receipt_hash  # type: ignore[index]
        self.write_json(native_run.run_directory / "state.json", state)
        return receipt

    def rehash_plan_and_gate(
        self,
        native_run: SimpleNamespace,
        plan: dict[str, object],
    ) -> None:
        payload = dict(plan)
        payload.pop("plan_hash", None)
        payload.pop("validated_at", None)
        plan_hash = canonical_hash(payload)
        plan["plan_hash"] = plan_hash
        self.write_json(native_run.run_directory / "fix-plan.json", plan)

        gate_path = native_run.run_directory / "gates" / "plan.json"
        gate = self.read_json(gate_path)
        gate["plan_hash"] = plan_hash
        gate.pop("receipt_hash", None)
        receipt_hash = canonical_hash(gate)
        gate["receipt_hash"] = receipt_hash
        self.write_json(gate_path, gate)

        state = self.read_json(native_run.run_directory / "state.json")
        state["hashes"]["plan_hash"] = plan_hash  # type: ignore[index]
        state["hashes"]["plan_gate_hash"] = receipt_hash  # type: ignore[index]
        state["gates"]["plan"] = receipt_hash  # type: ignore[index]
        self.write_json(native_run.run_directory / "state.json", state)

    def test_all_declared_profiles_use_native_scope_and_status_authority(self) -> None:
        self.assertEqual(set(self.PROFILE_CONTROLLERS), NATIVE_SCHEMA_PROFILES)

        for profile in self.PROFILE_CONTROLLERS:
            with self.subTest(profile=profile):
                artifacts = self.native_artifacts(
                    profile=profile,
                    phase="PLAN_APPROVED",
                )
                self.assertEqual(artifacts.schema_profile, profile)
                self.assertTrue(artifacts.scope_freshness["fresh"])
                self.assertEqual(artifacts.controller_status["phase"], "PLAN_APPROVED")

    def test_gate_a_command_approves_every_retained_id_and_no_other_id(self) -> None:
        artifacts = self.native_artifacts(findings=("F002", "F001"))

        command = gate_a_command(artifacts)

        self.assertEqual(command.approved_ids, ("F001", "F002"))
        self.assertIn("F001,F002", command.argv)
        self.assertNotIn("--reject", command.argv)
        self.assertNotIn("--defer", command.argv)
        self.assertEqual(
            command.argv[-2:],
            (
                "--user-statement",
                "Evaluation policy approves every retained finding for planning and no others; "
                "repair is not authorized.",
            ),
        )

    def test_gate_a_command_accepts_an_empty_ledger_explicitly(self) -> None:
        artifacts = self.native_artifacts(findings=())

        command = gate_a_command(artifacts)

        self.assertEqual(command.approved_ids, ())
        self.assertIn("--accept-empty", command.argv)
        self.assertNotIn("--approve", command.argv)
        self.assertEqual(
            command.argv[-1],
            "Evaluation policy accepts the empty material ledger; repair is not authorized.",
        )

    def test_gate_a_command_is_accepted_by_the_materialized_controller(self) -> None:
        artifacts = self.native_artifacts(findings=("F001", "F002"))

        completed = subprocess.run(
            command := gate_a_command(artifacts).argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )

        self.assertEqual(completed.returncode, 0, (command, completed.stderr))
        state = self.read_json(artifacts.run_directory / "state.json")
        self.assertEqual(state["phase"], "FINDINGS_APPROVED")
        self.assertEqual(state["approved_findings"], ["F001", "F002"])

    def test_candidate_groups_require_one_complete_disposition(self) -> None:
        for mutation in ("missing", "duplicate"):
            with self.subTest(mutation=mutation):
                native_run = self.native_run()
                adjudication_path = native_run.run_directory / "adjudication.normalized.json"
                adjudication = self.read_json(adjudication_path)
                if mutation == "missing":
                    ledger = self.read_json(native_run.run_directory / "ledger.json")
                    ledger["discarded"] = []
                    self.rehash_ledger(native_run, ledger)
                else:
                    ledger = self.read_json(native_run.run_directory / "ledger.json")
                    ledger["discarded"].append(  # type: ignore[union-attr]
                        {
                            "group_id": "G001",
                            "candidate_ids": ["C001"],
                            "disposition": "discard",
                        }
                    )
                    self.rehash_ledger(native_run, ledger)
                self.write_json(adjudication_path, adjudication)

                with self.assertRaisesRegex(EvaluationError, "candidate group"):
                    validate_gate_a_artifacts(
                        native_run.run_directory,
                        native_run.controller,
                        native_run.target,
                    )

    def test_candidate_bundle_is_required_native_json(self) -> None:
        native_run = self.native_run()
        (native_run.run_directory / "candidates.json").unlink()

        with self.assertRaisesRegex(EvaluationError, "candidates.json"):
            validate_gate_a_artifacts(
                native_run.run_directory,
                native_run.controller,
                native_run.target,
            )

    def test_candidate_bundle_hash_and_native_links_are_checked(self) -> None:
        for mutation in ("embedded", "state", "ledger", "adjudication"):
            with self.subTest(mutation=mutation):
                native_run = self.native_run()
                if mutation == "embedded":
                    candidates_path = native_run.run_directory / "candidates.json"
                    candidates = self.read_json(candidates_path)
                    candidates["candidates"][0]["local_id"] = "tampered"  # type: ignore[index]
                    self.write_json(candidates_path, candidates)
                elif mutation == "state":
                    state_path = native_run.run_directory / "state.json"
                    state = self.read_json(state_path)
                    state["hashes"]["candidate_bundle_hash"] = "0" * 64  # type: ignore[index]
                    self.write_json(state_path, state)
                elif mutation == "ledger":
                    ledger = self.read_json(native_run.run_directory / "ledger.json")
                    ledger["candidate_bundle_hash"] = "0" * 64
                    self.rehash_ledger(native_run, ledger)
                else:
                    adjudication_path = native_run.run_directory / "adjudication.normalized.json"
                    adjudication = self.read_json(adjudication_path)
                    adjudication["candidate_bundle_hash"] = "0" * 64
                    self.write_json(adjudication_path, adjudication)

                with self.assertRaisesRegex(EvaluationError, "candidate bundle"):
                    validate_gate_a_artifacts(
                        native_run.run_directory,
                        native_run.controller,
                        native_run.target,
                    )

    def test_candidate_ids_are_partitioned_across_groups_exactly_once(self) -> None:
        for mutation in ("missing", "duplicate"):
            with self.subTest(mutation=mutation):
                native_run = self.native_run()
                adjudication_path = native_run.run_directory / "adjudication.normalized.json"
                adjudication = self.read_json(adjudication_path)
                ledger = self.read_json(native_run.run_directory / "ledger.json")
                if mutation == "missing":
                    adjudication["groups"] = adjudication["groups"][:-1]  # type: ignore[index]
                    ledger["discarded"] = []
                else:
                    adjudication["groups"][0]["candidate_ids"].append("C999")  # type: ignore[index]
                    ledger["findings"][0]["candidate_ids"].append("C999")  # type: ignore[index]
                self.write_json(adjudication_path, adjudication)
                self.rehash_ledger(native_run, ledger)

                with self.assertRaisesRegex(EvaluationError, "candidate ID"):
                    validate_gate_a_artifacts(
                        native_run.run_directory,
                        native_run.controller,
                        native_run.target,
                    )

    def test_embedded_ledger_and_state_hashes_are_independently_checked(self) -> None:
        for mutation in ("embedded", "state"):
            with self.subTest(mutation=mutation):
                native_run = self.native_run()
                if mutation == "embedded":
                    ledger_path = native_run.run_directory / "ledger.json"
                    ledger = self.read_json(ledger_path)
                    ledger["summary"] = "tampered after hashing"
                    self.write_json(ledger_path, ledger)
                else:
                    state_path = native_run.run_directory / "state.json"
                    state = self.read_json(state_path)
                    state["hashes"]["ledger_hash"] = "0" * 64  # type: ignore[index]
                    self.write_json(state_path, state)

                with self.assertRaisesRegex(EvaluationError, "ledger hash"):
                    validate_gate_a_artifacts(
                        native_run.run_directory,
                        native_run.controller,
                        native_run.target,
                    )

    def test_scope_hash_must_match_embedded_identity_and_state(self) -> None:
        for mutation in ("embedded", "state"):
            with self.subTest(mutation=mutation):
                native_run = self.native_run()
                if mutation == "embedded":
                    scope_path = native_run.run_directory / "scope.json"
                    scope = self.read_json(scope_path)
                    scope["identity"]["comparison_reference"] = "tampered"  # type: ignore[index]
                    self.write_json(scope_path, scope)
                else:
                    state_path = native_run.run_directory / "state.json"
                    state = self.read_json(state_path)
                    state["scope_hash"] = "0" * 64
                    self.write_json(state_path, state)

                with self.assertRaisesRegex(EvaluationError, "scope"):
                    validate_gate_a_artifacts(
                        native_run.run_directory,
                        native_run.controller,
                        native_run.target,
                    )

    def test_gate_a_receipt_approves_all_and_only_retained_ids(self) -> None:
        native_run = self.native_run(
            findings=("F001", "F002"),
            phase="PLAN_VALIDATED",
        )
        gate_path = native_run.run_directory / "gates" / "findings.json"
        receipt = self.read_json(gate_path)
        receipt["decisions"]["approved"] = ["F001"]  # type: ignore[index]
        self.write_json(gate_path, receipt)
        self.rehash_receipt(native_run, "findings", "findings_gate_hash")

        with self.assertRaisesRegex(EvaluationError, "all and only retained"):
            validate_gate_b_artifacts(
                native_run.run_directory,
                native_run.controller,
                native_run.target,
            )

    def test_empty_ledger_receipt_requires_accepted_empty(self) -> None:
        native_run = self.native_run(findings=(), phase="COMPLETE")
        gate_path = native_run.run_directory / "gates" / "findings.json"
        receipt = self.read_json(gate_path)
        receipt["decisions"]["accepted_empty"] = False  # type: ignore[index]
        self.write_json(gate_path, receipt)
        self.rehash_receipt(native_run, "findings", "findings_gate_hash")

        with self.assertRaisesRegex(EvaluationError, "accepted_empty"):
            validate_gate_a_artifacts(
                native_run.run_directory,
                native_run.controller,
                native_run.target,
            )

    def test_gate_receipt_embedded_and_state_hashes_are_checked(self) -> None:
        for gate_name, state_hash_name in (
            ("findings", "findings_gate_hash"),
            ("plan", "plan_gate_hash"),
        ):
            for mutation in ("embedded", "state"):
                with self.subTest(gate=gate_name, mutation=mutation):
                    native_run = self.native_run(phase="PLAN_APPROVED")
                    if mutation == "embedded":
                        gate_path = native_run.run_directory / "gates" / f"{gate_name}.json"
                        receipt = self.read_json(gate_path)
                        receipt["recorded_at"] = "tampered"
                        self.write_json(gate_path, receipt)
                    else:
                        state_path = native_run.run_directory / "state.json"
                        state = self.read_json(state_path)
                        state["hashes"][state_hash_name] = "0" * 64  # type: ignore[index]
                        self.write_json(state_path, state)

                    with self.assertRaisesRegex(EvaluationError, "receipt hash"):
                        validate_gate_b_artifacts(
                            native_run.run_directory,
                            native_run.controller,
                            native_run.target,
                        )

    def test_gate_receipts_require_the_native_v1_schemas(self) -> None:
        for gate_name, state_hash_name in (
            ("findings", "findings_gate_hash"),
            ("plan", "plan_gate_hash"),
        ):
            with self.subTest(gate=gate_name):
                native_run = self.native_run(phase="PLAN_APPROVED")
                gate_path = native_run.run_directory / "gates" / f"{gate_name}.json"
                receipt = self.read_json(gate_path)
                receipt["schema_version"] = f"material-review/{gate_name}-gate/v2"
                self.write_json(gate_path, receipt)
                self.rehash_receipt(native_run, gate_name, state_hash_name)

                with self.assertRaisesRegex(EvaluationError, "receipt schema"):
                    validate_gate_b_artifacts(
                        native_run.run_directory,
                        native_run.controller,
                        native_run.target,
                    )

    def test_gate_a_receipt_requires_the_exact_evaluation_policy_statement(self) -> None:
        for findings, phase in (
            (("F001",), "PLAN_VALIDATED"),
            ((), "COMPLETE"),
        ):
            with self.subTest(findings=findings):
                native_run = self.native_run(findings=findings, phase=phase)
                gate_path = native_run.run_directory / "gates" / "findings.json"
                receipt = self.read_json(gate_path)
                receipt["user_statement"] = "Ordinary approval authorizes repair."
                self.write_json(gate_path, receipt)
                self.rehash_receipt(native_run, "findings", "findings_gate_hash")

                with self.assertRaisesRegex(EvaluationError, "evaluation policy statement"):
                    validate_gate_a_artifacts(
                        native_run.run_directory,
                        native_run.controller,
                        native_run.target,
                    )

    def test_gate_b_receipt_requires_the_exact_evaluation_policy_statement(self) -> None:
        native_run = self.native_run(phase="PLAN_APPROVED")
        gate_path = native_run.run_directory / "gates" / "plan.json"
        receipt = self.read_json(gate_path)
        receipt["user_statement"] = "Approved for immediate repair execution."
        self.write_json(gate_path, receipt)
        self.rehash_receipt(native_run, "plan", "plan_gate_hash")

        with self.assertRaisesRegex(EvaluationError, "evaluation policy statement"):
            validate_gate_b_artifacts(
                native_run.run_directory,
                native_run.controller,
                native_run.target,
            )

    def test_gate_b_command_approves_only_the_exact_validated_plan(self) -> None:
        artifacts = self.native_artifacts(
            findings=("F002", "F001"),
            phase="PLAN_VALIDATED",
        )

        command = gate_b_command(artifacts)

        self.assertEqual(command.approved_ids, ("F001", "F002"))
        self.assertIn("--approve", command.argv)
        self.assertNotIn("--reject", command.argv)
        self.assertEqual(command.plan_hash, artifacts.plan["plan_hash"])
        self.assertEqual(
            command.argv[-1],
            "Evaluation policy approves this exact validated plan for comparison evidence "
            "only; no repair or plan command execution is authorized.",
        )

    def test_gate_b_command_is_accepted_and_stops_at_plan_approved(self) -> None:
        artifacts = self.native_artifacts(phase="PLAN_VALIDATED")

        completed = subprocess.run(
            gate_b_command(artifacts).argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        state = self.read_json(artifacts.run_directory / "state.json")
        self.assertEqual(state["phase"], "PLAN_APPROVED")

    def test_plan_hash_and_state_hash_are_independently_checked(self) -> None:
        for mutation in ("embedded", "state"):
            with self.subTest(mutation=mutation):
                native_run = self.native_run(phase="PLAN_VALIDATED")
                if mutation == "embedded":
                    plan_path = native_run.run_directory / "fix-plan.json"
                    plan = self.read_json(plan_path)
                    plan["plan_summary"] = "tampered after hashing"
                    self.write_json(plan_path, plan)
                else:
                    state_path = native_run.run_directory / "state.json"
                    state = self.read_json(state_path)
                    state["hashes"]["plan_hash"] = "0" * 64  # type: ignore[index]
                    self.write_json(state_path, state)

                with self.assertRaisesRegex(EvaluationError, "plan hash"):
                    validate_gate_b_artifacts(
                        native_run.run_directory,
                        native_run.controller,
                        native_run.target,
                    )

    def test_gate_b_receipt_must_bind_the_exact_plan_hash(self) -> None:
        native_run = self.native_run(phase="PLAN_APPROVED")
        gate_path = native_run.run_directory / "gates" / "plan.json"
        receipt = self.read_json(gate_path)
        receipt["plan_hash"] = "0" * 64
        self.write_json(gate_path, receipt)
        self.rehash_receipt(native_run, "plan", "plan_gate_hash")

        with self.assertRaisesRegex(EvaluationError, "exact validated plan hash"):
            validate_gate_b_artifacts(
                native_run.run_directory,
                native_run.controller,
                native_run.target,
            )

    def test_every_approved_id_appears_exactly_once_in_plan(self) -> None:
        for mutation in ("missing", "duplicate"):
            with self.subTest(mutation=mutation):
                native_run = self.native_run(
                    findings=("F001", "F002"),
                    phase="PLAN_VALIDATED",
                )
                plan_path = native_run.run_directory / "fix-plan.json"
                plan = self.read_json(plan_path)
                if mutation == "missing":
                    plan["items"] = plan["items"][:1]  # type: ignore[index]
                else:
                    plan["items"].append(plan["items"][0])  # type: ignore[index]
                payload = dict(plan)
                payload.pop("plan_hash")
                payload.pop("validated_at")
                plan_hash = canonical_hash(payload)
                plan["plan_hash"] = plan_hash
                self.write_json(plan_path, plan)
                state = self.read_json(native_run.run_directory / "state.json")
                state["hashes"]["plan_hash"] = plan_hash  # type: ignore[index]
                self.write_json(native_run.run_directory / "state.json", state)

                with self.assertRaisesRegex(EvaluationError, "exactly once"):
                    validate_gate_b_artifacts(
                        native_run.run_directory,
                        native_run.controller,
                        native_run.target,
                    )

    def test_plan_paths_must_remain_inside_the_frozen_scope(self) -> None:
        native_run = self.native_run(phase="PLAN_VALIDATED")
        plan_path = native_run.run_directory / "fix-plan.json"
        plan = self.read_json(plan_path)
        plan["items"][0]["allowed_paths"] = ["unrelated.txt"]  # type: ignore[index]
        payload = dict(plan)
        payload.pop("plan_hash")
        payload.pop("validated_at")
        plan_hash = canonical_hash(payload)
        plan["plan_hash"] = plan_hash
        self.write_json(plan_path, plan)
        state = self.read_json(native_run.run_directory / "state.json")
        state["hashes"]["plan_hash"] = plan_hash  # type: ignore[index]
        self.write_json(native_run.run_directory / "state.json", state)

        with self.assertRaisesRegex(EvaluationError, "frozen scope"):
            validate_gate_b_artifacts(
                native_run.run_directory,
                native_run.controller,
                native_run.target,
            )

    def test_mutation_phase_is_unconditionally_rejected(self) -> None:
        for phase in (
            "FIXING",
            "VERIFYING",
            "REPAIR_REQUIRED",
            "PLAN_AMENDMENT_REQUIRED",
            "BLOCKED",
        ):
            with self.subTest(phase=phase):
                native_run = self.native_run(phase=phase)
                with self.assertRaisesRegex(EvaluationError, "repair phase"):
                    validate_gate_b_artifacts(
                        native_run.run_directory,
                        native_run.controller,
                        native_run.target,
                    )

    def test_find_native_run_rejects_an_ambiguous_second_run(self) -> None:
        first = self.native_run()
        second_run = first.run_directory.parent / "second-run"
        shutil.copytree(first.run_directory, second_run)

        with self.assertRaisesRegex(EvaluationError, "multiple native review runs"):
            find_native_run(first.trial_root)

    def test_missing_native_json_is_rejected_without_markdown_reconstruction(self) -> None:
        native_run = self.native_run()
        (native_run.run_directory / "ledger.json").unlink()
        (native_run.run_directory / "ledger.md").write_text(
            "# Material ledger\n\nF001 is retained.\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(EvaluationError, "ledger.json"):
            validate_gate_a_artifacts(
                native_run.run_directory,
                native_run.controller,
                native_run.target,
            )

    def test_normalization_copies_only_comparison_evidence_and_never_mutates_native_files(
        self,
    ) -> None:
        artifacts = self.native_artifacts(phase="PLAN_APPROVED")
        before = {
            path.relative_to(artifacts.run_directory).as_posix(): path.read_bytes()
            for path in artifacts.run_directory.rglob("*")
            if path.is_file()
        }

        normalized = normalize_trial_evidence(
            artifacts,
            timing_metadata={"elapsed_seconds": 12.5},
            turn_metadata={"assistant_turns": 3},
            tool_metadata={"tool_calls": 7},
        )

        after = {
            path.relative_to(artifacts.run_directory).as_posix(): path.read_bytes()
            for path in artifacts.run_directory.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)
        self.assertEqual(normalized["native_schema_versions"]["ledger"], artifacts.ledger["schema_version"])
        self.assertEqual(normalized["ledger"]["findings"][0]["disposition"], "keep")
        self.assertEqual(
            normalized["ledger"]["discarded"][0]["canonical_title"],
            "Unsupported candidate",
        )
        self.assertEqual(
            normalized["ledger"]["discarded"][0]["evidence_quote"],
            "comparison",
        )
        self.assertEqual(normalized["gate_a"]["decisions"]["approved"], ["F001"])
        self.assertEqual(
            normalized["gate_a"]["user_statement"],
            "Evaluation policy approves every retained finding for planning and no others; "
            "repair is not authorized.",
        )
        self.assertEqual(normalized["plan"]["items"][0]["allowed_paths"], ["tracked.txt"])
        self.assertTrue(normalized["gate_b"]["approved"])
        self.assertEqual(
            normalized["gate_b"]["user_statement"],
            "Evaluation policy approves this exact validated plan for comparison evidence "
            "only; no repair or plan command execution is authorized.",
        )
        self.assertEqual(normalized["metadata"]["turns"], {"assistant_turns": 3})
        references = normalized["native_artifacts"]
        self.assertEqual(
            {reference["path"] for reference in references},
            set(before),
        )
        for reference in references:
            self.assertEqual(
                reference["sha256"],
                hashlib.sha256(before[reference["path"]]).hexdigest(),
            )

    def test_v3_normalization_preserves_repair_audit_and_plan_assessment(self) -> None:
        profile = (
            "material-review/state/v1",
            "material-review/ledger/v3",
            "material-review/fix-plan/v2",
        )
        artifacts = self.native_artifacts(
            profile=profile,
            phase="PLAN_APPROVED",
        )

        normalized = normalize_trial_evidence(artifacts)

        finding = normalized["ledger"]["findings"][0]
        self.assertEqual(finding["repair_audit"]["verdict"], "approved")
        self.assertEqual(
            finding["repair_direction_hash"],
            artifacts.ledger["findings"][0]["repair_direction_hash"],
        )
        self.assertEqual(
            normalized["plan"]["items"][0]["repair_direction_assessment"][
                "repair_direction_hash"
            ],
            artifacts.plan["items"][0]["repair_direction_assessment"][
                "repair_direction_hash"
            ],
        )

    def test_normalization_preserves_plan_authorization_and_finite_boundaries(self) -> None:
        artifacts = self.native_artifacts(phase="PLAN_APPROVED")

        normalized = normalize_trial_evidence(artifacts)

        item = normalized["plan"]["items"][0]
        self.assertEqual(item["depends_on"], [])
        self.assertEqual(item["steps"], ["Edit the scoped tracked content."])
        self.assertEqual(item["success_evidence"], ["required test passes"])
        self.assertEqual(item["max_attempts"], 2)
        self.assertEqual(item["tests"][0]["timeout_seconds"], 120)
        self.assertEqual(normalized["plan"]["global_tests"][0]["timeout_seconds"], 300)
        self.assertEqual(normalized["plan"]["max_repair_rounds"], 1)
        self.assertEqual(
            normalized["plan"]["scope_expansion_policy"],
            "restore_and_reapprove",
        )
        self.assertTrue(normalized["plan"]["no_unrelated_cleanup"])
        self.assertTrue(normalized["plan"]["no_new_improvements_during_fix"])
        self.assertEqual(
            normalized["plan"]["post_fix_review_scope"],
            "approved_findings_and_fix_introduced_regressions_only",
        )

    def test_distinct_native_plan_boundaries_remain_distinct_after_normalization(
        self,
    ) -> None:
        original = normalize_trial_evidence(
            self.native_artifacts(phase="PLAN_APPROVED")
        )
        native_run = self.native_run(phase="PLAN_APPROVED")
        plan = self.read_json(native_run.run_directory / "fix-plan.json")
        plan["items"][0]["max_attempts"] = 3  # type: ignore[index]
        plan["items"][0]["tests"][0]["timeout_seconds"] = 240  # type: ignore[index]
        plan["items"][0]["steps"].append("Re-run scoped validation.")  # type: ignore[index]
        plan["items"][0]["success_evidence"].append("manual evidence retained")  # type: ignore[index]
        plan["global_tests"][0]["timeout_seconds"] = 600  # type: ignore[index]
        plan["max_repair_rounds"] = 2
        self.rehash_plan_and_gate(native_run, plan)
        changed = normalize_trial_evidence(
            validate_gate_b_artifacts(
                native_run.run_directory,
                native_run.controller,
                native_run.target,
            )
        )

        original_item = original["plan"]["items"][0]
        changed_item = changed["plan"]["items"][0]
        self.assertNotEqual(original_item["max_attempts"], changed_item["max_attempts"])
        self.assertNotEqual(
            original_item["tests"][0]["timeout_seconds"],
            changed_item["tests"][0]["timeout_seconds"],
        )
        self.assertNotEqual(original_item["steps"], changed_item["steps"])
        self.assertNotEqual(
            original_item["success_evidence"],
            changed_item["success_evidence"],
        )
        self.assertNotEqual(
            original["plan"]["global_tests"],
            changed["plan"]["global_tests"],
        )
        self.assertNotEqual(
            original["plan"]["max_repair_rounds"],
            changed["plan"]["max_repair_rounds"],
        )


class SchemaContractTests(unittest.TestCase):
    def test_every_controlled_object_disallows_additional_properties(self) -> None:
        schemas_root = EVALUATION_ROOT / "schemas"

        for schema_path in schemas_root.glob("*.schema.json"):
            with self.subTest(schema=schema_path.name):
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                pending = [schema]
                while pending:
                    value = pending.pop()
                    if isinstance(value, dict):
                        if value.get("type") == "object":
                            self.assertIs(
                                value.get("additionalProperties"),
                                False,
                                msg=f"uncontrolled object in {schema_path}: {value}",
                            )
                        pending.extend(value.values())
                    elif isinstance(value, list):
                        pending.extend(value)


class RecordingRunner:
    def __init__(
        self,
        *,
        stdout: str,
        stderr: str = "",
        returncode: int = 0,
        error: BaseException | None = None,
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.error = error
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    @property
    def argv(self) -> list[str]:
        return self.calls[-1][0]

    @property
    def options(self) -> dict[str, object]:
        return self.calls[-1][1]

    def __call__(self, argv: list[str], **options: object) -> CompletedProcess[str]:
        self.calls.append((list(argv), dict(options)))
        if self.error is not None:
            raise self.error
        return CompletedProcess(
            argv,
            self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


class ExecutorAndBlindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.target_path = self.root / "target"
        self.workflow_path = self.root / "workflow"
        self.trial_output = self.root / "trial-output"
        self.bundle_output = self.root / "bundle-output"
        for path in (
            self.target_path,
            self.workflow_path,
            self.trial_output,
            self.bundle_output,
        ):
            path.mkdir()
        self.skill_path = self.workflow_path / "SKILL.md"
        self.skill_path.write_text("# Material review\n", encoding="utf-8")
        self.prompt_path = self.root / "prompt.md"
        self.prompt_path.write_text("Perform the anonymous task.\n", encoding="utf-8")
        self.schema_path = self.root / "output.schema.json"
        self.schema_path.write_text(
            json.dumps(
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["decision"],
                    "properties": {"decision": {"const": "ok"}},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.environment = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.root / "home"),
            "CODEX_HOME": str(self.root / "codex-home"),
            "LANG": "en_US.UTF-8",
            "TMPDIR": str(self.root / "tmp"),
            "LC_SECRET": "locale-shaped-secret",
            "OPENAI_API_KEY": "configured-openai-key",
            "SSH_AUTH_SOCK": str(self.root / "agent.sock"),
            "GITHUB_TOKEN": "github-secret",
            "AWS_SECRET_ACCESS_KEY": "cloud-secret",
            "UNRELATED": "do-not-inherit",
        }

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def session_spec(
        self,
        *,
        role: str = "trial",
        output_schema: Path | None = None,
        sandbox_mode: str = "workspace-write",
    ) -> SessionSpec:
        return SessionSpec(
            role=role,
            working_directory=(
                self.target_path if role == "trial" else self.bundle_output
            ),
            readable_workflow=self.workflow_path if role == "trial" else None,
            output_directory=self.trial_output,
            prompt_path=self.prompt_path,
            output_schema=output_schema,
            model="gpt-5.6",
            reasoning_effort="high",
            sandbox_mode=sandbox_mode,
            timeout_seconds=123,
        )

    def execute_with_schema(
        self,
        schema: dict[str, object],
        output: object,
    ) -> SessionResult:
        self.schema_path.write_text(json.dumps(schema) + "\n", encoding="utf-8")
        runner = RecordingRunner(
            stdout=self.successful_jsonl(final_output=json.dumps(output))
        )
        return CodexExecutor(runner=runner, environment=self.environment).start(
            self.session_spec(
                role="judge",
                output_schema=self.schema_path,
                sandbox_mode="read-only",
            )
        )

    @staticmethod
    def successful_jsonl(
        *,
        thread_id: str = "trial-session",
        final_output: str = "review paused at Gate A",
    ) -> str:
        events = (
            {"type": "thread.started", "thread_id": thread_id},
            {
                "type": "item.completed",
                "item": {
                    "id": "tool-1",
                    "type": "command_execution",
                    "command": "python3 reviewctl.py status",
                },
            },
            {
                "type": "item.completed",
                "item": {"id": "message-1", "type": "agent_message", "text": final_output},
            },
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 50,
                    "cached_input_tokens": 10,
                    "output_tokens": 20,
                },
            },
        )
        return "".join(json.dumps(event) + "\n" for event in events)

    def test_codex_start_records_thread_id_exact_configuration_and_narrow_environment(
        self,
    ) -> None:
        runner = RecordingRunner(stdout=self.successful_jsonl())

        result = CodexExecutor(runner=runner, environment=self.environment).start(
            self.session_spec()
        )

        self.assertEqual(result.session_id, "trial-session")
        self.assertEqual(result.status, "complete")
        self.assertIsNone(result.failure)
        self.assertEqual(
            runner.argv,
            [
                "codex",
                "exec",
                "--json",
                "--ignore-user-config",
                "--model",
                "gpt-5.6",
                "-c",
                "model_reasoning_effort=high",
                "--sandbox",
                "workspace-write",
                "--cd",
                str(self.target_path),
                "--add-dir",
                str(self.workflow_path),
                "--add-dir",
                str(self.trial_output),
                "-",
            ],
        )
        self.assertEqual(runner.options["timeout"], 123)
        self.assertIs(runner.options["shell"], False)
        self.assertEqual(
            set(runner.options["env"]),  # type: ignore[arg-type]
            {"PATH", "HOME", "CODEX_HOME", "LANG", "TMPDIR", "OPENAI_API_KEY"},
        )
        self.assertEqual(result.usage["input_tokens"], 50)
        self.assertEqual(len(result.tool_events), 1)
        self.assertTrue(result.stdout_path.is_file())
        self.assertTrue(result.stderr_path.is_file())
        self.assertNotIn("configured-openai-key", result.stdout_path.read_text())
        self.assertEqual(CodexExecutor(runner=runner).status("unknown"), "failed")

    def test_codex_resume_uses_recorded_session_and_configuration(self) -> None:
        runner = RecordingRunner(stdout=self.successful_jsonl())
        executor = CodexExecutor(runner=runner, environment=self.environment)
        spec = self.session_spec()
        executor.start(spec)
        runner.stdout = self.successful_jsonl(final_output="review paused at Gate B")

        result = executor.resume("trial-session", "Approve Gate A.", spec)

        self.assertEqual(result.session_id, "trial-session")
        self.assertEqual(
            runner.argv,
            [
                "codex",
                "exec",
                "resume",
                "--json",
                "--ignore-user-config",
                "--model",
                "gpt-5.6",
                "-c",
                "model_reasoning_effort=high",
                "-c",
                'sandbox_mode="workspace-write"',
                "trial-session",
                "-",
            ],
        )
        self.assertEqual(runner.options["cwd"], self.target_path)
        self.assertEqual(runner.options["input"], "Approve Gate A.")
        self.assertEqual(executor.status("trial-session"), "complete")

    def test_explicitly_empty_child_environment_does_not_inherit_parent_values(
        self,
    ) -> None:
        runner = RecordingRunner(stdout=self.successful_jsonl())

        CodexExecutor(runner=runner, environment={}).start(self.session_spec())

        self.assertEqual(runner.options["env"], {})

    def test_codex_logs_redact_every_configured_sensitive_value(self) -> None:
        runner = RecordingRunner(
            stdout=self.successful_jsonl(
                final_output="observed configured-openai-key and github-secret"
            ),
            stderr="diagnostic cloud-secret configured-openai-key",
        )

        result = CodexExecutor(
            runner=runner,
            environment=self.environment,
        ).start(self.session_spec())

        persisted = (
            result.stdout_path.read_text(encoding="utf-8")
            + result.stderr_path.read_text(encoding="utf-8")
        )
        for secret in (
            "configured-openai-key",
            "github-secret",
            "cloud-secret",
        ):
            self.assertNotIn(secret, persisted)
        self.assertIn("<redacted-credential>", persisted)

    def test_agreement_start_is_fresh_ephemeral_read_only_and_schema_validated(
        self,
    ) -> None:
        runner = RecordingRunner(
            stdout=self.successful_jsonl(final_output='{"decision":"ok"}')
        )

        result = CodexExecutor(runner=runner, environment=self.environment).start(
            self.session_spec(
                role="agreement",
                output_schema=self.schema_path,
                sandbox_mode="read-only",
            )
        )

        self.assertIsNone(result.failure)
        self.assertIn("--ephemeral", runner.argv)
        self.assertIn("--skip-git-repo-check", runner.argv)
        self.assertIn("--output-schema", runner.argv)
        self.assertIn(str(self.schema_path), runner.argv)
        self.assertEqual(runner.argv[runner.argv.index("--sandbox") + 1], "read-only")
        self.assertNotIn("--add-dir", runner.argv)

    def test_output_schema_pattern_accepts_matching_and_rejects_nonmatching_text(
        self,
    ) -> None:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["sha"],
            "properties": {
                "sha": {"type": "string", "pattern": "^[0-9a-f]{4}$"}
            },
        }

        matching = self.execute_with_schema(schema, {"sha": "1a2b"})
        nonmatching = self.execute_with_schema(schema, {"sha": "NOPE"})

        self.assertIsNone(matching.failure)
        self.assertEqual(nonmatching.status, "failed")
        self.assertEqual(nonmatching.failure.kind, "schema_invalid_output")  # type: ignore[union-attr]

    def test_output_schema_composition_conditionals_and_format_are_enforced(
        self,
    ) -> None:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "value", "choice", "nullable", "timestamp"],
            "properties": {
                "kind": {"enum": ["A", "B"]},
                "value": {
                    "allOf": [
                        {"type": "string"},
                        {"minLength": 2},
                        {"pattern": "^[AB]"},
                    ]
                },
                "choice": {
                    "oneOf": [
                        {"const": "x"},
                        {"type": "string"},
                    ]
                },
                "nullable": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "null"},
                    ]
                },
                "timestamp": {
                    "type": ["string", "null"],
                    "format": "date-time",
                },
            },
            "if": {
                "properties": {"kind": {"const": "A"}},
                "required": ["kind"],
            },
            "then": {"properties": {"value": {"pattern": "^A"}}},
            "else": {"properties": {"value": {"pattern": "^B"}}},
        }
        valid = {
            "kind": "A",
            "value": "Alpha",
            "choice": "y",
            "nullable": None,
            "timestamp": "2026-07-27T12:30:00Z",
        }
        invalid_cases = (
            {**valid, "value": "A"},
            {**valid, "value": "Beta"},
            {**valid, "kind": "B", "value": "Alpha"},
            {**valid, "choice": "x"},
            {**valid, "nullable": 5},
            {**valid, "timestamp": "not-a-date"},
        )

        self.assertIsNone(self.execute_with_schema(schema, valid).failure)
        for invalid in invalid_cases:
            with self.subTest(invalid=invalid):
                result = self.execute_with_schema(schema, invalid)
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.failure.kind, "schema_invalid_output")  # type: ignore[union-attr]

    def test_output_schema_integer_uses_mathematical_integrality(self) -> None:
        schema = {"type": "integer"}

        for valid in (1, 1.0, -2.0):
            with self.subTest(valid=valid):
                self.assertIsNone(self.execute_with_schema(schema, valid).failure)
        for invalid in (True, 1.5):
            with self.subTest(invalid=invalid):
                result = self.execute_with_schema(schema, invalid)
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.failure.kind, "schema_invalid_output")  # type: ignore[union-attr]

    def test_output_schema_date_time_accepts_rfc3339_case_and_offsets(self) -> None:
        schema = {"type": "string", "format": "date-time"}

        for valid in (
            "2026-07-27T12:30:00Z",
            "2026-07-27t12:30:00z",
            "2026-07-27T12:30:00.123456+05:30",
            "2026-07-27T12:30:00-23:59",
        ):
            with self.subTest(valid=valid):
                self.assertIsNone(self.execute_with_schema(schema, valid).failure)

    def test_output_schema_date_time_rejects_non_rfc3339_forms(self) -> None:
        schema = {"type": "string", "format": "date-time"}

        for invalid in (
            "2026-07-27",
            "2026-07-27 12:30:00Z",
            "2026-07-27T12:30:00",
            "2026-02-30T12:30:00Z",
            "2026-07-27T12:30:00+24:00",
            "2026-07-27T12:30:00+05:60",
        ):
            with self.subTest(invalid=invalid):
                result = self.execute_with_schema(schema, invalid)
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.failure.kind, "schema_invalid_output")  # type: ignore[union-attr]

    def test_output_schema_date_time_accepts_actual_leap_second_instants(
        self,
    ) -> None:
        schema = {"type": "string", "format": "date-time"}

        for valid in (
            "2016-12-31T23:59:60Z",
            "2016-12-31T15:59:60-08:00",
            "2017-01-01T00:59:60+01:00",
        ):
            with self.subTest(valid=valid):
                self.assertIsNone(self.execute_with_schema(schema, valid).failure)

    def test_output_schema_date_time_rejects_unannounced_leap_seconds(
        self,
    ) -> None:
        schema = {"type": "string", "format": "date-time"}

        for invalid in (
            "2026-07-27T12:30:60Z",
            "2016-12-31T23:59:60+01:00",
        ):
            with self.subTest(invalid=invalid):
                result = self.execute_with_schema(schema, invalid)
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.failure.kind, "schema_invalid_output")  # type: ignore[union-attr]

    def test_output_schema_with_unknown_keyword_fails_closed(self) -> None:
        result = self.execute_with_schema(
            {"type": "object", "unsupportedConstraint": True},
            {},
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failure.kind, "schema_invalid_output")  # type: ignore[union-attr]

    def test_output_schema_with_malformed_supported_constraint_fails_closed(
        self,
    ) -> None:
        result = self.execute_with_schema(
            {"type": "string", "minLength": "ignored"},
            "",
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failure.kind, "schema_invalid_output")  # type: ignore[union-attr]

    def test_codex_returns_typed_infrastructure_failures(self) -> None:
        cases = (
            (
                "nonzero_exit",
                RecordingRunner(stdout=self.successful_jsonl(), returncode=7),
                self.session_spec(),
            ),
            (
                "missing_thread_id",
                RecordingRunner(stdout='{"type":"turn.completed"}\n'),
                self.session_spec(),
            ),
            (
                "malformed_jsonl",
                RecordingRunner(stdout="not-json\n"),
                self.session_spec(),
            ),
            (
                "malformed_jsonl",
                RecordingRunner(stdout=self.successful_jsonl(thread_id="--last")),
                self.session_spec(),
            ),
            (
                "timeout",
                RecordingRunner(
                    stdout="",
                    error=TimeoutExpired(["codex", "exec"], timeout=123),
                ),
                self.session_spec(),
            ),
            (
                "schema_invalid_output",
                RecordingRunner(
                    stdout=self.successful_jsonl(final_output='{"decision":"wrong"}')
                ),
                self.session_spec(
                    role="judge",
                    output_schema=self.schema_path,
                    sandbox_mode="read-only",
                ),
            ),
        )
        for expected_kind, runner, spec in cases:
            with self.subTest(kind=expected_kind):
                result = CodexExecutor(
                    runner=runner,
                    environment=self.environment,
                ).start(spec)
                self.assertEqual(result.status, "failed")
                self.assertIsInstance(result.failure, InfrastructureFailure)
                self.assertEqual(result.failure.kind, expected_kind)  # type: ignore[union-attr]

    def test_trial_request_contains_only_anonymous_operational_inputs_and_hashes(
        self,
    ) -> None:
        review_request = self.root / "review-request.md"
        review_request.write_text("Review the frozen range.\n", encoding="utf-8")
        request_path = self.trial_output / "trial-request.md"
        record_path = self.trial_output / "trial-request.record.json"
        configuration = {
            "model": "gpt-5.6",
            "reasoning_effort": "high",
            "sandbox_mode": "workspace-write",
            "timeout_seconds": 123,
        }

        record = build_trial_request(
            request_path,
            record_path,
            review_request_path=review_request,
            materialized_skill_path=self.skill_path,
            target_path=self.target_path,
            artifact_root=self.trial_output,
            anonymous_trial_label="A-1",
            isolation_mode="filesystem_blinding",
            executor_configuration=configuration,
        )

        text = request_path.read_text(encoding="utf-8")
        self.assertIn("Review the frozen range.", text)
        self.assertIn(str(self.skill_path), text)
        self.assertIn(str(self.target_path), text)
        self.assertIn(str(self.trial_output), text)
        self.assertIn("read that exact skill and no other copy", text.lower())
        self.assertIn("filesystem_blinding", text)
        self.assertNotIn("feature/evaluator", text)
        expected_request_hash = hashlib.sha256(request_path.read_bytes()).hexdigest()
        expected_configuration_hash = hashlib.sha256(
            json.dumps(
                configuration,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(record["request_sha256"], expected_request_hash)
        self.assertEqual(
            record["executor_configuration_sha256"],
            expected_configuration_hash,
        )
        self.assertEqual(json.loads(record_path.read_text()), record)
        self.assertNotIn("model", record)

    def test_agreement_and_comparison_bundles_copy_only_allowlisted_inputs(self) -> None:
        normalized_a = self.root / "normalized-a.json"
        normalized_b = self.root / "normalized-b.json"
        normalized_a.write_text(
            json.dumps({"variant": "A", "artifact_path": str(self.target_path / "a")})
            + "\n",
            encoding="utf-8",
        )
        normalized_b.write_text(json.dumps({"variant": "B"}) + "\n", encoding="utf-8")
        agreement_a = self.root / "agreement-a.json"
        agreement_b = self.root / "agreement-b.json"
        agreement_a.write_text(json.dumps({"anonymous_variant": "A"}) + "\n")
        agreement_b.write_text(json.dumps({"anonymous_variant": "B"}) + "\n")
        rubric = self.root / "judge-rubric.md"
        oracle = self.root / "judge-oracle.json"
        rubric.write_text("Judge material quality.\n", encoding="utf-8")
        oracle.write_text(json.dumps({"non_exhaustive": True}) + "\n", encoding="utf-8")
        agreement_prompt = self.root / "agreement-prompt.md"
        comparison_prompt = self.root / "comparison-prompt.md"
        agreement_prompt.write_text("Compare one variant.\n", encoding="utf-8")
        comparison_prompt.write_text("Compare A and B.\n", encoding="utf-8")
        prefixes = {self.target_path: "<target>", self.root: "<run>"}

        agreement_bundle = build_agreement_bundle(
            self.root / "agreement-bundle",
            anonymous_variant="A",
            normalized_trials=(normalized_a,),
            prompt_path=agreement_prompt,
            schema_path=self.schema_path,
            path_prefixes=prefixes,
        )
        comparison_bundle = build_comparison_bundle(
            self.root / "comparison-bundle",
            variant_a_trials=(normalized_a,),
            variant_b_trials=(normalized_b,),
            agreement_a=agreement_a,
            agreement_b=agreement_b,
            rubric_path=rubric,
            oracle_path=oracle,
            prompt_path=comparison_prompt,
            schema_path=self.schema_path,
            path_prefixes=prefixes,
        )

        agreement_files = {
            path.relative_to(agreement_bundle).as_posix()
            for path in agreement_bundle.rglob("*")
            if path.is_file()
        }
        self.assertEqual(
            agreement_files,
            {"bundle.json", "prompt.md", "output.schema.json", "trials/trial-1.json"},
        )
        agreement_manifest = json.loads(
            (agreement_bundle / "bundle.json").read_text(encoding="utf-8")
        )
        self.assertEqual(agreement_manifest["anonymous_variant"], "A")
        self.assertNotIn("B", json.dumps(agreement_manifest))
        self.assertIn(
            "<target>/a",
            (agreement_bundle / "trials/trial-1.json").read_text(encoding="utf-8"),
        )
        comparison_files = {
            path.relative_to(comparison_bundle).as_posix()
            for path in comparison_bundle.rglob("*")
            if path.is_file()
        }
        self.assertEqual(
            comparison_files,
            {
                "bundle.json",
                "prompt.md",
                "output.schema.json",
                "judge-rubric.md",
                "judge-oracle.json",
                "variants/A/trial-1.json",
                "variants/B/trial-1.json",
                "agreements/A.json",
                "agreements/B.json",
            },
        )
        comparison_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in comparison_bundle.rglob("*")
            if path.is_file()
        )
        self.assertNotIn("private_map", comparison_text)
        self.assertNotIn("feature/evaluator", comparison_text)

    def test_agreement_bundle_rejects_trial_from_a_different_variant_slot(self) -> None:
        normalized_b = self.root / "normalized-b.json"
        normalized_b.write_text(json.dumps({"variant": "B"}) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(EvaluationError, "slot A"):
            build_agreement_bundle(
                self.root / "mismatched-agreement-bundle",
                anonymous_variant="A",
                normalized_trials=(normalized_b,),
                prompt_path=self.prompt_path,
                schema_path=self.schema_path,
                path_prefixes={self.root: "<run>"},
            )

    def test_comparison_bundle_rejects_swapped_trials(self) -> None:
        normalized_a = self.root / "normalized-slot-a.json"
        normalized_b = self.root / "normalized-slot-b.json"
        normalized_a.write_text(
            json.dumps({"anonymous_variant": "A"}) + "\n",
            encoding="utf-8",
        )
        normalized_b.write_text(
            json.dumps({"anonymous_variant": "B"}) + "\n",
            encoding="utf-8",
        )
        agreement_a = self.root / "agreement-slot-a.json"
        agreement_b = self.root / "agreement-slot-b.json"
        agreement_a.write_text(
            json.dumps({"anonymous_variant": "A"}) + "\n",
            encoding="utf-8",
        )
        agreement_b.write_text(
            json.dumps({"anonymous_variant": "B"}) + "\n",
            encoding="utf-8",
        )
        rubric = self.root / "rubric.md"
        oracle = self.root / "oracle.json"
        rubric.write_text("Judge material quality.\n", encoding="utf-8")
        oracle.write_text("{}\n", encoding="utf-8")
        common = {
            "rubric_path": rubric,
            "oracle_path": oracle,
            "prompt_path": self.prompt_path,
            "schema_path": self.schema_path,
            "path_prefixes": {self.root: "<run>"},
        }

        with self.assertRaisesRegex(EvaluationError, "trial.*slot A"):
            build_comparison_bundle(
                self.root / "swapped-trial-comparison",
                variant_a_trials=(normalized_b,),
                variant_b_trials=(normalized_a,),
                agreement_a=agreement_a,
                agreement_b=agreement_b,
                **common,
            )

    def test_comparison_bundle_rejects_swapped_agreements(self) -> None:
        normalized_a = self.root / "normalized-a-for-agreements.json"
        normalized_b = self.root / "normalized-b-for-agreements.json"
        normalized_a.write_text(json.dumps({"variant": "A"}) + "\n", encoding="utf-8")
        normalized_b.write_text(json.dumps({"variant": "B"}) + "\n", encoding="utf-8")
        agreement_a = self.root / "agreement-a-for-swap.json"
        agreement_b = self.root / "agreement-b-for-swap.json"
        agreement_a.write_text(
            json.dumps({"anonymous_variant": "A"}) + "\n",
            encoding="utf-8",
        )
        agreement_b.write_text(
            json.dumps({"anonymous_variant": "B"}) + "\n",
            encoding="utf-8",
        )
        rubric = self.root / "agreement-swap-rubric.md"
        oracle = self.root / "agreement-swap-oracle.json"
        rubric.write_text("Judge material quality.\n", encoding="utf-8")
        oracle.write_text("{}\n", encoding="utf-8")

        with self.assertRaisesRegex(EvaluationError, "agreement.*slot A"):
            build_comparison_bundle(
                self.root / "swapped-agreement-comparison",
                variant_a_trials=(normalized_a,),
                variant_b_trials=(normalized_b,),
                agreement_a=agreement_b,
                agreement_b=agreement_a,
                rubric_path=rubric,
                oracle_path=oracle,
                prompt_path=self.prompt_path,
                schema_path=self.schema_path,
                path_prefixes={self.root: "<run>"},
            )

    def test_redaction_uses_longest_configured_machine_prefix_first(self) -> None:
        redacted = redact_machine_paths(
            f"{self.root}/run/file {self.root}/other",
            {self.root: "<home>", self.root / "run": "<run>"},
        )

        self.assertEqual(redacted, "<run>/file <home>/other")

    def test_blinded_bundle_scan_rejects_identity_credentials_paths_and_symlinks(
        self,
    ) -> None:
        private_tokens = (
            "feature/evaluator",
            "9" * 40,
            "Secret evaluator commit subject",
        )
        leaks = (
            ("candidate ref feature/evaluator", "identity leak"),
            ("skill SHA " + "9" * 40, "identity leak"),
            ("Secret evaluator commit subject", "identity leak"),
            ("new variant performed better", "identity leak"),
            ("OPENAI_API_KEY=secret-value", "credential leak"),
            ('{"API_KEY":"secret-value"}', "credential leak"),
            ('{"MY_API_KEY":"secret-value"}', "credential leak"),
            (str(self.root / "machine"), "absolute path"),
        )
        for index, (text, message) in enumerate(leaks):
            bundle = self.root / f"leak-{index}"
            bundle.mkdir()
            (bundle / "artifact.txt").write_text(text, encoding="utf-8")
            with self.subTest(text=text):
                with self.assertRaisesRegex(EvaluationError, message):
                    scan_blinded_bundle(bundle, private_tokens)

        bundle = self.root / "symlink-bundle"
        bundle.mkdir()
        outside = self.root / "outside.txt"
        outside.write_text("outside\n", encoding="utf-8")
        os.symlink(outside, bundle / "escape")
        with self.assertRaisesRegex(EvaluationError, "symlink escape"):
            scan_blinded_bundle(bundle, private_tokens)

        bundle = self.root / "filename-bundle"
        bundle.mkdir()
        (bundle / ("9" * 40 + ".json")).write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(EvaluationError, "identity leak"):
            scan_blinded_bundle(bundle, private_tokens)

        bundle = self.root / "non-regular-bundle"
        bundle.mkdir()
        os.mkfifo(bundle / "pipe")
        with self.assertRaisesRegex(EvaluationError, "non-regular file"):
            scan_blinded_bundle(bundle, private_tokens)

    def test_blinded_bundle_scan_rejects_old_new_json_identity_values(self) -> None:
        for index, value in enumerate(
            (
                {"variant": "old"},
                {"anonymous_variant": "new"},
                {"metadata": {"skill_version": "old"}},
                {"candidate": {"metadata": {"variant": "old"}}},
            )
        ):
            bundle = self.root / f"json-identity-{index}"
            bundle.mkdir()
            (bundle / "artifact.json").write_text(
                json.dumps(value) + "\n",
                encoding="utf-8",
            )
            with self.subTest(value=value):
                with self.assertRaisesRegex(EvaluationError, "identity leak"):
                    scan_blinded_bundle(bundle)

    def test_blinded_bundle_scan_allows_old_new_in_nonidentity_json_fields(self) -> None:
        bundle = self.root / "json-nonidentity"
        bundle.mkdir()
        (bundle / "artifact.json").write_text(
            json.dumps(
                {
                    "status": "new",
                    "summary": "Old evidence was replaced by new evidence.",
                    "candidate": {"status": "new"},
                    "workflow": {"summary": "old"},
                }
            )
            + "\n",
            encoding="utf-8",
        )

        scan_blinded_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
