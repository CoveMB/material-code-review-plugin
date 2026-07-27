from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from scripts.material_review_evaluation.benchmark import load_benchmark
from scripts.material_review_evaluation.model import EvaluationError, safe_relative_path


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
