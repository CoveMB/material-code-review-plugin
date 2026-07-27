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
from types import SimpleNamespace

from scripts.material_review_evaluation.benchmark import CommandSpec, load_benchmark
from scripts.material_review_evaluation.model import (
    EvaluationError,
    canonical_hash,
    safe_relative_path,
    sha256_file,
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


if __name__ == "__main__":
    unittest.main()
