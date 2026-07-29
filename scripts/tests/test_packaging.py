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
DISTRIBUTION_LAYOUT = not (REPOSITORY_ROOT / ".git").exists()
PROMPT_DRIVEN_EVALUATOR_PATHS = (
    ".agents/skills/material-review-evaluation/SKILL.md",
    "evaluations/material-code-review/README.md",
    "evaluations/material-code-review/cases/discogs-custom-playlists.json",
    "evaluations/material-code-review/prompts/reviewer.md",
    "evaluations/material-code-review/prompts/judge.md",
    "evaluations/material-code-review/rubric.md",
)
MAINTAINER_EVALUATOR_PATHS = PROMPT_DRIVEN_EVALUATOR_PATHS + (
    "EVALUATION.md",
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
        "maintainer discovery-recall case is absent from distribution layouts",
    )
    def test_material_review_discovery_recall_case_is_frozen_and_maintainer_only(
        self,
    ) -> None:
        relative = "evaluations/material-code-review/cases/pr-3-discovery-recall.json"
        case_path = REPOSITORY_ROOT / relative
        self.assertTrue(case_path.is_file(), f"missing frozen case: {case_path}")
        case = json.loads(case_path.read_text(encoding="utf-8"))

        self.assertEqual(case["schema_version"], "material-review/discovery-recall-case/v1")
        self.assertEqual(case["repository"], "CoveMB/material-code-review-plugin")
        self.assertEqual(case["pull_request"], 3)
        self.assertEqual(case["base_commit"], "8ebeb7ae2a1f28acfe297c258f703865280c4fa4")
        self.assertEqual(case["head_commit"], "c740131b0953a04a93cbe1c970dcbf36dae8bca1")
        self.assertEqual(
            {item["id"] for item in case["expected_material_failure_modes"]},
            {
                "checkout-attestation-order",
                "private-receipt-visibility",
                "complete-disposition-propagation",
                "phase-specific-return-schema",
                "required-document-validation",
                "casefolded-maintainer-archive-path",
                "evaluator-entrypoint-root-boundary",
            },
        )
        self.assertEqual(len(case["expected_material_failure_modes"]), 7)
        self.assertEqual(
            {item["id"] for item in case["low_value_controls"]},
            {"make-json-deduplication", "split-literal-comment", "minor-test-economy"},
        )
        self.assertEqual(len(case["low_value_controls"]), 3)
        self.assertEqual(
            case["max_executions"], {"baseline": 1, "post_change_confirmation": 1}
        )

        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            full_output = temp_root / "full-plugin.zip"
            standalone_output = temp_root / "standalone.zip"
            packager = fixture_root / FULL_PACKAGER.relative_to(REPOSITORY_ROOT)
            package_result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(packager),
                    "--package-root",
                    str(fixture_root),
                    "--output",
                    str(full_output),
                    "--standalone-output",
                    str(standalone_output),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(package_result.returncode, 0, package_result.stderr)
            with zipfile.ZipFile(full_output) as archive:
                self.assertNotIn(relative, set(archive.namelist()))
            with zipfile.ZipFile(standalone_output) as archive:
                self.assertNotIn(relative, set(archive.namelist()))

    @unittest.skipIf(
        DISTRIBUTION_LAYOUT,
        "maintainer discovery-recall case is absent from distribution layouts",
    )
    def test_pull_request_scope_contract_is_aligned_and_validated(self) -> None:
        canonical_skill = REPOSITORY_ROOT / "skills/material-code-review/SKILL.md"
        command = REPOSITORY_ROOT / "commands/material-review.md"
        case_path = (
            REPOSITORY_ROOT
            / "evaluations/material-code-review/cases/pr-3-discovery-recall.json"
        )
        expected_hint = (
            'argument-hint: "[scope:auto|uncommitted|branch|pull_request|range] '
            '[base:<ref>] [head:<ref>] [depth:auto|full] [external-review:off|ask]"'
        )
        self.assertIn(expected_hint, canonical_skill.read_text(encoding="utf-8"))
        self.assertIn(expected_hint, command.read_text(encoding="utf-8"))
        case = json.loads(case_path.read_text(encoding="utf-8"))
        self.assertIn("scope:pull_request", case["review_request"])

        with tempfile.TemporaryDirectory() as temp:
            fixture_root = self.create_full_plugin_fixture(Path(temp))
            fixture_command = fixture_root / "commands/material-review.md"
            fixture_command.write_text(
                fixture_command.read_text(encoding="utf-8").replace(
                    "branch|pull_request|range", "branch|range"
                ),
                encoding="utf-8",
            )
            validation_result = self.run_package_validator(
                fixture_root, distribution_layout=False
            )
            self.assertNotEqual(validation_result.returncode, 0)
            self.assertIn(
                "command argument hint does not match canonical review skill",
                validation_result.stderr,
            )

    def test_pre_verification_recovery_contract_is_packaged_and_validated(self) -> None:
        markers = (
            "refresh-finding-test",
            "begin-pre-verification-repair",
            "latest failed or stale required test evidence",
        )
        review_skill = REPOSITORY_ROOT / "skills/material-code-review/SKILL.md"
        simplification_skill = (
            REPOSITORY_ROOT / "skills/material-code-simplification/SKILL.md"
        )
        controller = (
            REPOSITORY_ROOT
            / "skills/material-code-review/scripts/reviewctl.py"
        )
        for path in (review_skill, simplification_skill):
            text = path.read_text(encoding="utf-8")
            for marker in markers:
                self.assertIn(marker, text, f"missing recovery marker in {path}")
        controller_text = controller.read_text(encoding="utf-8")
        for marker in markers[:2]:
            self.assertIn(marker, controller_text)

        with tempfile.TemporaryDirectory() as temp:
            fixture_root = self.create_full_plugin_fixture(Path(temp))
            fixture_skill = fixture_root / "skills/material-code-review/SKILL.md"
            fixture_skill.write_text(
                fixture_skill.read_text(encoding="utf-8").replace(
                    "latest failed or stale required test evidence",
                    "failed evidence",
                ),
                encoding="utf-8",
            )
            validation_result = self.run_package_validator(
                fixture_root, distribution_layout=False
            )
            self.assertNotEqual(validation_result.returncode, 0)
            self.assertIn(
                "canonical skill recovery contract missing marker",
                validation_result.stderr,
            )

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
        dimensions = (
            "finding correctness",
            "coverage",
            "precision",
            "plan quality",
            "safety",
            "usability",
        )
        positions = [rubric.index(dimension) for dimension in dimensions]
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
            "base:<skill-ref> candidate:<skill-ref>",
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
                "evaluations/material-code-review/prompts/judge.md",
                "The root dispatcher must provide zero inherited task history.",
                "",
                "judge prompt must require zero inherited task history",
            ),
            (
                ".agents/skills/material-review-evaluation/SKILL.md",
                "Immediately before each reviewer or judge dispatch, recapture the active "
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
                'argument-hint: "base:<skill-ref> candidate:<skill-ref>"',
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
        entries = (
            ".agents/skills/material-review-evaluation/SKILL.md",
            "./.agents/skills/material-review-evaluation/SKILL.md",
            ".agents//skills/material-review-evaluation/SKILL.md",
            ".agents\\skills\\material-review-evaluation\\SKILL.md",
        )
        for entry in entries:
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as temp_directory:
                temp_root = Path(temp_directory)
                fixture_root = self.create_full_plugin_fixture(temp_root)
                output = temp_root / "full-plugin.zip"
                package_result = self.run_full_packager(fixture_root, output)
                self.assertEqual(package_result.returncode, 0, package_result.stderr)
                with zipfile.ZipFile(output, "a") as archive:
                    archive.writestr(
                        entry,
                        "---\nname: material-review-evaluation\n---\n",
                    )

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
                expected_error = (
                    "forbidden maintainer-only archive entry"
                    if entry.startswith(".agents/skills/")
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

    def test_full_archive_requires_material_review_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            complete_archive = temp_root / "full-plugin.zip"
            package_result = self.run_full_packager(fixture_root, complete_archive)
            self.assertEqual(package_result.returncode, 0, package_result.stderr)

            validator_arguments = [
                sys.executable,
                "-B",
                str(PACKAGE_VALIDATOR),
                "--package-root",
                str(fixture_root),
                *(["--distribution-layout"] if DISTRIBUTION_LAYOUT else []),
                "--full-archive",
            ]
            complete_result = subprocess.run(
                [*validator_arguments, str(complete_archive)],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(complete_result.returncode, 0, complete_result.stderr)

            incomplete_archive = temp_root / "full-plugin-missing-command.zip"
            with zipfile.ZipFile(complete_archive) as source, zipfile.ZipFile(
                incomplete_archive, "w"
            ) as destination:
                for member in source.infolist():
                    if member.filename != "commands/material-review.md":
                        destination.writestr(member, source.read(member.filename))

            self.assertTrue(
                (fixture_root / "commands/material-review.md").is_file(),
                "the separately validated source fixture must remain intact",
            )
            incomplete_result = subprocess.run(
                [*validator_arguments, str(incomplete_archive)],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertNotEqual(incomplete_result.returncode, 0)
            self.assertIn(
                f"{incomplete_archive.name}: missing archive entry commands/material-review.md",
                incomplete_result.stderr,
            )

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
            archive_path = temp_root / "full-plugin.zip"
            package_result = self.run_full_packager(fixture_root, archive_path)
            self.assertEqual(package_result.returncode, 0, package_result.stderr)
            extracted_root = temp_root / "extracted"
            self.extract_archive_with_modes(archive_path, extracted_root)

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
                "material-code-review package 1.2.0 is structurally valid",
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
                (distribution_directory / "material-code-review-plugin-1.2.0.zip").is_file()
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

    def test_material_review_runtime_contracts_are_required(self) -> None:
        required = {
            "schemas/coverage-plan.schema.json",
            "schemas/candidate-preflight.schema.json",
            "schemas/fallback-assignment.schema.json",
            "schemas/reviewer-failure-attestation.schema.json",
            "schemas/coverage-status.schema.json",
            "references/protocol-coherence-lens.md",
        }
        for relative in sorted(required):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temp_directory:
                fixture_root = self.create_full_plugin_fixture(Path(temp_directory))
                (fixture_root / "skills" / "material-code-review" / relative).unlink()

                source_result = self.run_package_validator(fixture_root)
                standalone_result = self.run_review_validator(fixture_root)

                self.assertNotEqual(source_result.returncode, 0)
                self.assertIn(
                    f"missing required file: skills/material-code-review/{relative}",
                    source_result.stderr,
                )
                self.assertNotEqual(standalone_result.returncode, 0)
                self.assertIn(
                    f"missing required skill file: {relative}", standalone_result.stderr
                )

        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)
            full_output = temp_root / "full-plugin.zip"
            standalone_output = temp_root / "material-review-standalone.zip"
            packager = fixture_root / FULL_PACKAGER.relative_to(REPOSITORY_ROOT)
            package_result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(packager),
                    "--package-root",
                    str(fixture_root),
                    "--output",
                    str(full_output),
                    "--standalone-output",
                    str(standalone_output),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(package_result.returncode, 0, package_result.stderr)
            with zipfile.ZipFile(standalone_output) as archive:
                standalone_names = set(archive.namelist())
            with zipfile.ZipFile(full_output) as archive:
                full_names = set(archive.namelist())
            self.assertTrue(required.issubset(standalone_names))
            self.assertTrue(
                {f"skills/material-code-review/{relative}" for relative in required}.issubset(
                    full_names
                )
            )
            self.assertIn("agents/protocol-reviewer.md", full_names)

    def test_unparseable_origin_provenance_contract_is_shipped(self) -> None:
        markers = ("evidence_handling", "unparseable_origin_degraded")
        review_surfaces = (
            "SKILL.md",
            "scripts/reviewctl.py",
            "schemas/candidate-preflight.schema.json",
            "schemas/coverage-status.schema.json",
            "references/workflow.md",
            "references/failure-model.md",
        )
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            fixture_root = self.create_full_plugin_fixture(temp_root)

            source_result = self.run_package_validator(fixture_root)
            standalone_source_result = self.run_review_validator(fixture_root)
            self.assertEqual(source_result.returncode, 0, source_result.stderr)
            self.assertEqual(
                standalone_source_result.returncode,
                0,
                standalone_source_result.stderr,
            )

            full_output = temp_root / "full-plugin.zip"
            standalone_output = temp_root / "material-review-standalone.zip"
            packager = fixture_root / FULL_PACKAGER.relative_to(REPOSITORY_ROOT)
            package_result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(packager),
                    "--package-root",
                    str(fixture_root),
                    "--output",
                    str(full_output),
                    "--standalone-output",
                    str(standalone_output),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(package_result.returncode, 0, package_result.stderr)

            simplification_output = temp_root / "material-simplification.zip"
            simplification_result = self.run_packager(
                fixture_root, simplification_output
            )
            self.assertEqual(
                simplification_result.returncode,
                0,
                simplification_result.stderr,
            )

            archive_surfaces = {
                full_output: tuple(
                    f"skills/material-code-review/{relative}"
                    for relative in review_surfaces
                ),
                standalone_output: review_surfaces,
                simplification_output: (
                    "core/reviewctl.py",
                    "core/schemas/candidate-preflight.schema.json",
                    "core/schemas/coverage-status.schema.json",
                ),
            }
            for archive_path, surfaces in archive_surfaces.items():
                with self.subTest(archive=archive_path.name), zipfile.ZipFile(
                    archive_path
                ) as archive:
                    for relative in surfaces:
                        text = archive.read(relative).decode("utf-8")
                        for marker in markers:
                            self.assertIn(marker, text, f"{relative} lacks {marker}")

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
            self.assertTrue(
                {
                    "core/schemas/coverage-plan.schema.json",
                    "core/schemas/candidate-preflight.schema.json",
                    "core/schemas/fallback-assignment.schema.json",
                    "core/schemas/reviewer-failure-attestation.schema.json",
                    "core/schemas/coverage-status.schema.json",
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
