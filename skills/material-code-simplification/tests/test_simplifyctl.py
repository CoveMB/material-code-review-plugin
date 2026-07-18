from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "simplifyctl.py"
SPEC = importlib.util.spec_from_file_location("material_simplifyctl", SCRIPT)
assert SPEC and SPEC.loader
simplifyctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(simplifyctl)

VALIDATOR_SCRIPT = SCRIPT.with_name("validate_package.py")
VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "material_simplification_validator", VALIDATOR_SCRIPT
)
assert VALIDATOR_SPEC and VALIDATOR_SPEC.loader
simplification_validator = importlib.util.module_from_spec(VALIDATOR_SPEC)
VALIDATOR_SPEC.loader.exec_module(simplification_validator)


class SimplifyCtlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test User")
        (self.repo / "src").mkdir()
        (self.repo / "tests").mkdir()
        (self.repo / "src" / "service.py").write_text(
            "def value():\n    return 1\n", encoding="utf-8"
        )
        (self.repo / "src" / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.repo / "tests" / "test_service.py").write_text(
            "from src.service import value\nassert value() == 1\n", encoding="utf-8"
        )
        self.git("add", ".")
        self.git("commit", "-qm", "initial")
        self.run_id = "simplify-run"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=self.repo, check=True, capture_output=True, text=True
        )
        return result.stdout.strip()

    def run_tool(self, *args: str, expected: int = 0) -> tuple[str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = simplifyctl.main(list(args))
        if result != expected:
            self.fail(
                f"simplifyctl returned {result}, expected {expected}\n"
                f"stdout:\n{stdout.getvalue()}\nstderr:\n{stderr.getvalue()}"
            )
        return stdout.getvalue(), stderr.getvalue()

    @property
    def run_dir(self) -> Path:
        return self.repo / ".git" / "material-code-review" / "runs" / self.run_id

    def load(self, relative: str):
        return json.loads((self.run_dir / relative).read_text(encoding="utf-8"))

    def write_json(self, name: str, value) -> Path:
        path = self.root / name
        path.write_text(json.dumps(value, indent=2), encoding="utf-8")
        return path

    def init_src(self, *extra: str) -> None:
        self.run_tool(
            "init",
            "--repo-root",
            str(self.repo),
            "--scope",
            "codebase",
            "--path",
            "src",
            "--run-id",
            self.run_id,
            *extra,
        )

    def test_init_defaults_to_codebase_scope(self) -> None:
        self.run_tool(
            "init",
            "--repo-root",
            str(self.repo),
            "--path",
            "src",
            "--exclude-untracked",
            "--run-id",
            self.run_id,
        )
        self.assertEqual(self.load("scope.json")["identity"]["actual_scope"], "codebase")

    def test_bundled_core_precedes_sibling_with_full_plugin_fallback(self) -> None:
        skill = self.root / "layout" / "material-code-simplification"
        bundled_controller = skill / "core" / "reviewctl.py"
        sibling_controller = skill.parent / "material-code-review" / "scripts" / "reviewctl.py"
        bundled_controller.parent.mkdir(parents=True)
        sibling_controller.parent.mkdir(parents=True)
        bundled_controller.write_text("MARKER = 'bundled'\n", encoding="utf-8")
        sibling_controller.write_text("MARKER = 'sibling'\n", encoding="utf-8")

        original_skill_dir = simplifyctl._skill_dir
        original_validator_root = simplification_validator.ROOT
        previous_core_module = sys.modules.get("material_reviewctl_core")
        simplifyctl._skill_dir = lambda: skill
        simplification_validator.ROOT = skill
        try:
            self.assertEqual(simplifyctl._load_core().MARKER, "bundled")
            layout, controller, _schemas = simplification_validator.resolve_core()
            self.assertEqual(layout, "standalone")
            self.assertEqual(controller, bundled_controller)

            bundled_controller.unlink()
            self.assertEqual(simplifyctl._load_core().MARKER, "sibling")
            layout, controller, _schemas = simplification_validator.resolve_core()
            self.assertEqual(layout, "full-plugin")
            self.assertEqual(controller, sibling_controller)
        finally:
            simplifyctl._skill_dir = original_skill_dir
            simplification_validator.ROOT = original_validator_root
            if previous_core_module is None:
                sys.modules.pop("material_reviewctl_core", None)
            else:
                sys.modules["material_reviewctl_core"] = previous_core_module

    def test_selection_budgets_fail_closed(self) -> None:
        self.run_tool(
            "init",
            "--repo-root",
            str(self.repo),
            "--scope",
            "codebase",
            "--path",
            "src",
            "--max-selected-files",
            "1",
            "--run-id",
            self.run_id,
            expected=2,
        )
        self.assertFalse(self.run_dir.exists())
        self.run_tool(
            "init",
            "--repo-root",
            str(self.repo),
            "--scope",
            "codebase",
            "--path",
            "src",
            "--max-selected-bytes",
            "1",
            "--run-id",
            self.run_id,
            expected=2,
        )
        self.assertFalse(self.run_dir.exists())

    def test_explicit_change_scope_delegates_to_core(self) -> None:
        captured: list[str] = []
        original = simplifyctl.core.main

        def delegated(values):
            captured.extend(values)
            return 37

        simplifyctl.core.main = delegated
        try:
            self.run_tool(
                "init",
                "--repo-root",
                str(self.repo),
                "--scope",
                "auto",
                expected=37,
            )
        finally:
            simplifyctl.core.main = original
        self.assertEqual(captured[0], "init")
        self.assertIn("auto", captured)

    @unittest.skipUnless(hasattr(Path, "symlink_to"), "symlinks unavailable")
    def test_selected_symlink_target_is_frozen_and_stales(self) -> None:
        link = self.repo / "src" / "current.py"
        try:
            link.symlink_to("service.py")
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        self.git("add", "src/current.py")
        self.git("commit", "-qm", "add selected symlink")
        self.init_src("--exclude-untracked")
        scope = self.load("scope.json")["identity"]
        entry = next(item for item in scope["files"] if item["path"] == "src/current.py")
        self.assertEqual(entry["comparison_state"]["worktree_kind"], "symlink")
        self.assertEqual(
            (self.run_dir / entry["comparison_state"]["snapshot_path"]).read_text(encoding="utf-8"),
            "service.py",
        )
        link.unlink()
        link.symlink_to("helper.py")
        self.run_tool(
            "check-scope",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            expected=2,
        )

    def test_codebase_scope_includes_clean_selected_files(self) -> None:
        self.init_src("--exclude-untracked")
        paths = {entry["path"] for entry in self.load("files.json")}
        self.assertEqual(paths, {"src/helper.py", "src/service.py"})
        scope = self.load("scope.json")["identity"]
        self.assertEqual(scope["actual_scope"], "codebase")
        self.assertEqual(scope["baseline_sha"], "0" * 40)
        self.assertEqual(scope["path_selectors"], ["src"])
        self.assertEqual(scope["exclude_path_selectors"], [])
        self.assertTrue(scope["mutable"])
        self.assertEqual(
            {entry["baseline_state"]["type"] for entry in scope["files"]}, {"missing"}
        )
        self.assertTrue(
            all(entry["comparison_state"]["type"] == "file" for entry in scope["files"])
        )

    def test_selected_change_makes_scope_stale(self) -> None:
        self.init_src("--exclude-untracked")
        (self.repo / "src" / "service.py").write_text(
            "def value():\n    return 2\n", encoding="utf-8"
        )
        self.run_tool(
            "check-scope",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            expected=2,
        )
        self.assertTrue((self.run_dir / "scope-staleness.json").is_file())

    def test_unselected_change_does_not_change_selected_scope(self) -> None:
        self.init_src("--exclude-untracked")
        (self.repo / "tests" / "test_service.py").write_text(
            "from src.service import value\nassert value() in {1, 2}\n", encoding="utf-8"
        )
        self.run_tool(
            "check-scope",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
        )

    def test_selected_untracked_file_is_included_by_default(self) -> None:
        (self.repo / "src" / "new.py").write_text("NEW = True\n", encoding="utf-8")
        self.init_src()
        paths = {entry["path"] for entry in self.load("files.json")}
        self.assertIn("src/new.py", paths)
        tracked = {entry["path"]: entry["tracked"] for entry in self.load("files.json")}
        self.assertFalse(tracked["src/new.py"])

    def test_transient_filter_applies_only_to_untracked_paths(self) -> None:
        cache_directory = self.repo / "src" / "__pycache__"
        cache_directory.mkdir()
        tracked_path = cache_directory / "tracked.pyc"
        untracked_path = cache_directory / "untracked.pyc"
        tracked_path.write_bytes(b"tracked cache artifact")
        self.git("add", "--", "src/__pycache__/tracked.pyc")
        self.git("commit", "-qm", "track explicit cache artifact")
        untracked_path.write_bytes(b"untracked cache artifact")

        self.init_src()

        entries = {entry["path"]: entry for entry in self.load("files.json")}
        self.assertIn("src/__pycache__/tracked.pyc", entries)
        self.assertTrue(entries["src/__pycache__/tracked.pyc"]["tracked"])
        self.assertNotIn("src/__pycache__/untracked.pyc", entries)

    def test_head_change_stales_even_when_selected_content_is_unchanged(self) -> None:
        self.init_src("--exclude-untracked")
        (self.repo / "tests" / "test_service.py").write_text(
            "from src.service import value\nassert value() == 1  # same contract\n",
            encoding="utf-8",
        )
        self.git("add", "tests/test_service.py")
        self.git("commit", "-qm", "outside selected scope")
        self.run_tool(
            "check-scope",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            expected=2,
        )

    def test_selected_mode_change_stales_scope(self) -> None:
        target = self.repo / "src" / "service.py"
        before = stat.S_IMODE(target.stat().st_mode)
        desired = before | stat.S_IXUSR
        if desired == before:
            desired = before & ~stat.S_IXUSR
        self.init_src("--exclude-untracked")
        try:
            os.chmod(target, desired)
        except OSError as exc:
            self.skipTest(f"mode changes unavailable: {exc}")
        if stat.S_IMODE(target.stat().st_mode) == before:
            self.skipTest("filesystem did not preserve the requested mode change")
        self.run_tool(
            "check-scope",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            expected=2,
        )

    def test_exclusion_and_unmatched_selector_fail_closed(self) -> None:
        self.run_tool(
            "init",
            "--repo-root",
            str(self.repo),
            "--scope",
            "codebase",
            "--path",
            "src",
            "--exclude-path",
            "src",
            "--run-id",
            self.run_id,
            expected=2,
        )
        self.run_tool(
            "init",
            "--repo-root",
            str(self.repo),
            "--scope",
            "codebase",
            "--path",
            "missing",
            "--run-id",
            self.run_id,
            expected=2,
        )

    def test_unsafe_selector_is_rejected(self) -> None:
        self.run_tool(
            "init",
            "--repo-root",
            str(self.repo),
            "--scope",
            "codebase",
            "--path",
            "../outside",
            "--run-id",
            self.run_id,
            expected=2,
        )

    @unittest.skipIf(os.name == "nt", "fixture requires POSIX filename semantics")
    def test_trailing_space_git_path_fails_before_run_creation(self) -> None:
        unusual_path = "src/trailing.py "
        (self.repo / unusual_path).write_text("VALUE = 2\n", encoding="utf-8")
        self.git("add", "--", unusual_path)
        self.git("commit", "-qm", "add trailing-space path")

        _stdout, stderr = self.run_tool(
            "init",
            "--repo-root",
            str(self.repo),
            "--scope",
            "codebase",
            "--path",
            "src",
            "--exclude-untracked",
            "--run-id",
            self.run_id,
            expected=2,
        )

        self.assertIn("unsupported repository path spelling", stderr)
        self.assertIn(repr(unusual_path), stderr)
        self.assertFalse(self.run_dir.exists())

    @unittest.skipIf(os.name == "nt", "fixture requires POSIX filename semantics")
    def test_backslash_git_path_and_normalized_alias_fail_before_run_creation(self) -> None:
        unusual_path = "src/name\\part.py"
        normalized_alias = self.repo / "src" / "name" / "part.py"
        normalized_alias.parent.mkdir()
        (self.repo / unusual_path).write_text("VALUE = 'backslash'\n", encoding="utf-8")
        normalized_alias.write_text("VALUE = 'slash'\n", encoding="utf-8")
        self.git("add", "--", unusual_path, "src/name/part.py")
        self.git("commit", "-qm", "add colliding path spellings")

        _stdout, stderr = self.run_tool(
            "init",
            "--repo-root",
            str(self.repo),
            "--scope",
            "codebase",
            "--path",
            "src",
            "--exclude-untracked",
            "--run-id",
            self.run_id,
            expected=2,
        )

        self.assertIn("unsupported repository path spelling", stderr)
        self.assertIn(repr(unusual_path), stderr)
        self.assertFalse(self.run_dir.exists())

    @unittest.skipIf(os.name == "nt", "fixture requires POSIX filename semantics")
    def test_narrow_selectors_use_literal_git_pathspecs_before_decoding(self) -> None:
        unrelated_path = "other/name\\part.py"
        (self.repo / "other").mkdir()
        (self.repo / unrelated_path).write_text("VALUE = 'outside selection'\n", encoding="utf-8")
        self.git("add", "--", unrelated_path)
        self.git("commit", "-qm", "add unrelated unusual path")
        calls: list[tuple[str, ...]] = []
        original_git_bytes = simplifyctl.core.git_bytes

        def captured_git_bytes(repo: Path, *arguments: str, **options) -> bytes:
            calls.append(arguments)
            return original_git_bytes(repo, *arguments, **options)

        simplifyctl.core.git_bytes = captured_git_bytes
        try:
            self.run_tool(
                "init",
                "--repo-root",
                str(self.repo),
                "--scope",
                "codebase",
                "--path",
                "src",
                "--path",
                "tests",
                "--exclude-untracked",
                "--run-id",
                self.run_id,
            )
        finally:
            simplifyctl.core.git_bytes = original_git_bytes

        paths = {entry["path"] for entry in self.load("files.json")}
        self.assertEqual(paths, {"src/helper.py", "src/service.py", "tests/test_service.py"})
        ls_files_calls = [call for call in calls if call and call[0] == "ls-files"]
        self.assertEqual(len(ls_files_calls), 1)
        self.assertIn("--", ls_files_calls[0])
        self.assertIn(":(literal)src", ls_files_calls[0])
        self.assertIn(":(literal)tests", ls_files_calls[0])

    def test_root_selector_deliberately_uses_repository_wide_git_call(self) -> None:
        calls: list[tuple[str, ...]] = []
        original_git_bytes = simplifyctl.core.git_bytes

        def captured_git_bytes(repo: Path, *arguments: str, **options) -> bytes:
            calls.append(arguments)
            return original_git_bytes(repo, *arguments, **options)

        simplifyctl.core.git_bytes = captured_git_bytes
        try:
            self.run_tool(
                "init",
                "--repo-root",
                str(self.repo),
                "--scope",
                "codebase",
                "--path",
                ".",
                "--exclude-untracked",
                "--run-id",
                self.run_id,
            )
        finally:
            simplifyctl.core.git_bytes = original_git_bytes

        paths = {entry["path"] for entry in self.load("files.json")}
        self.assertEqual(paths, {"src/helper.py", "src/service.py", "tests/test_service.py"})
        ls_files_calls = [call for call in calls if call and call[0] == "ls-files"]
        self.assertEqual(len(ls_files_calls), 1)
        self.assertFalse(any(argument.startswith(":(literal)") for argument in ls_files_calls[0]))

    def test_codebase_scope_completes_full_gated_repair_lifecycle(self) -> None:
        self.init_src("--exclude-untracked")
        scope_hash = self.load("state.json")["scope_hash"]
        candidate = {
            "schema_version": "material-review/candidate-set/v1",
            "scope_hash": scope_hash,
            "reviewer_id": "codebase-correctness",
            "independence_group": "fixture-reviewer",
            "review_mode": "subagent",
            "findings": [
                {
                    "local_id": "service-value",
                    "title": "service returns the obsolete fixture value",
                    "nature": "defect",
                    "category": "correctness",
                    "severity": "medium",
                    "confidence": "certain",
                    "file": "src/service.py",
                    "line_start": 2,
                    "line_end": 2,
                    "evidence_side": "comparison",
                    "evidence_quote": "    return 1",
                    "scope_relation": "primary",
                    "related_changed_files": ["src/service.py"],
                    "direct_dependency": True,
                    "observable_consequence": "The fixture service exposes the old value.",
                    "trigger_conditions": "Call value().",
                    "counterevidence_checked": ["No wrapper changes the returned integer."],
                    "why_not_preference": "The fixture contract requires the replacement value.",
                    "proposed_resolution": "Return the replacement fixture value.",
                    "estimated_fix_risk": "low",
                    "requires_user_decision": False,
                    "assumptions": [],
                }
            ],
            "coverage": {
                "files_reviewed": ["src/helper.py", "src/service.py"],
                "areas": ["correctness"],
                "limitations": [],
            },
        }
        candidate_path = self.write_json("codebase-candidate.json", candidate)
        self.run_tool(
            "ingest-candidates",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(candidate_path),
        )
        candidate_hash = self.load("candidates.json")["candidate_bundle_hash"]
        adjudication = {
            "schema_version": "material-review/adjudication/v1",
            "scope_hash": scope_hash,
            "candidate_bundle_hash": candidate_hash,
            "adjudicator_id": "fixture-adjudicator",
            "groups": [
                {
                    "group_id": "G001",
                    "candidate_ids": ["C001"],
                    "canonical_title": "service returns the obsolete fixture value",
                    "nature": "defect",
                    "category": "correctness",
                    "severity": "medium",
                    "confidence": "certain",
                    "file": "src/service.py",
                    "line_start": 2,
                    "line_end": 2,
                    "evidence_side": "comparison",
                    "evidence_quote": "    return 1",
                    "source_reviewers": ["codebase-correctness"],
                    "source_independence_groups": ["fixture-reviewer"],
                    "validation": {
                        "mode": "independent",
                        "validator_id": "fixture-validator",
                        "independence_group": "fixture-validator",
                        "verdict": "confirmed",
                        "reason": "The comparison-side source contains the obsolete value.",
                        "evidence_checked": ["src/service.py:2"],
                        "counterevidence": ["No alternative return path exists."],
                        "causality": "exposed",
                        "root_cause_supported": True,
                    },
                    "materiality": {
                        "concrete_evidence": True,
                        "plausible_negative_consequence": True,
                        "beyond_preference": True,
                        "current_scope_relevance": True,
                        "improvement_current_cost": None,
                        "improvement_benefit_exceeds_churn": None,
                        "coverage_targets_fragile_behavior": None,
                    },
                    "disposition": "keep",
                    "decision_reason": "The deterministic fixture contract requires repair.",
                    "discard_reason_code": None,
                    "recommended_action": "fix_now",
                    "required_pre_fix_verification": None,
                }
            ],
            "verdict": "SHOULD FIX BEFORE MERGE",
            "summary": "The selected codebase fixture has one repairable finding.",
            "limitations": [],
        }
        adjudication_path = self.write_json("codebase-adjudication.json", adjudication)
        self.run_tool(
            "compile-ledger",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(adjudication_path),
        )
        self.run_tool(
            "gate-findings",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--approve",
            "F001",
            "--user-statement",
            "Approve the selected codebase fixture finding.",
        )
        gate_hash = self.load("gates/findings.json")["receipt_hash"]
        plan_payload = {
            "schema_version": "material-review/fix-plan/v1",
            "scope_hash": scope_hash,
            "findings_gate_hash": gate_hash,
            "plan_summary": "Replace the fixture value and run a non-mutating regression.",
            "items": [
                {
                    "finding_id": "F001",
                    "root_cause": "The service still returns the obsolete fixture value.",
                    "objective": "value() returns 2.",
                    "depends_on": [],
                    "steps": ["Replace the obsolete return value with 2."],
                    "allowed_paths": ["src/service.py"],
                    "tests": [
                        {
                            "id": "codebase-regression",
                            "command": "grep -Fq 'return 2' src/service.py",
                            "working_directory": ".",
                            "required": True,
                            "timeout_seconds": 30,
                            "purpose": "Verify the controlled codebase-scope repair.",
                        }
                    ],
                    "manual_verification": [],
                    "rollback_strategy": "Restore the per-finding checkpoint.",
                    "risk_controls": ["Change only the selected service source."],
                    "success_evidence": ["codebase-regression exits 0"],
                    "max_attempts": 2,
                }
            ],
            "global_tests": [],
            "no_unrelated_cleanup": True,
            "no_new_improvements_during_fix": True,
            "post_fix_review_scope": "approved_findings_and_fix_introduced_regressions_only",
            "scope_expansion_policy": "restore_and_reapprove",
            "max_repair_rounds": 1,
        }
        plan_path = self.write_json("codebase-plan.json", plan_payload)
        self.run_tool(
            "validate-plan",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(plan_path),
        )
        self.run_tool(
            "gate-plan",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--approve",
            "--user-statement",
            "Approve the exact codebase fixture plan.",
        )
        self.run_tool("begin-fix", "--repo-root", str(self.repo), "--run-id", self.run_id)
        self.run_tool(
            "start-finding",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--finding",
            "F001",
        )
        (self.repo / "src" / "service.py").write_text(
            "def value():\n    return 2\n", encoding="utf-8"
        )
        self.run_tool(
            "run-test",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--finding",
            "F001",
            "--test",
            "codebase-regression",
        )
        self.run_tool(
            "finish-finding",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--finding",
            "F001",
            "--status",
            "fixed",
            "--note",
            "Replaced the selected fixture value.",
        )
        self.run_tool(
            "prepare-verification", "--repo-root", str(self.repo), "--run-id", self.run_id
        )
        plan = self.load("fix-plan.json")
        fix_summary = self.load("fix-summary.json")
        verification = {
            "schema_version": "material-review/verification/v1",
            "scope_hash": scope_hash,
            "plan_hash": plan["plan_hash"],
            "fix_summary_hash": fix_summary["fix_summary_hash"],
            "verifier_id": "fixture-postfix",
            "independence_group": "fixture-postfix",
            "mode": "independent",
            "finding_results": [
                {
                    "finding_id": "F001",
                    "status": "resolved",
                    "root_cause_resolved": True,
                    "reason": "The selected source returns the replacement value.",
                    "evidence_checked": ["src/service.py:2 -- return 2"],
                    "tests_checked": ["codebase-regression"],
                }
            ],
            "regressions": [],
            "record_only_observations": [
                {
                    "title": "Unrelated fixture ideas remain out of scope",
                    "file": "src/helper.py",
                    "line_start": 1,
                    "reason": "Post-fix verification does not reopen improvements.",
                }
            ],
            "verdict": "pass",
            "summary": "The approved codebase finding is resolved without a repair regression.",
            "limitations": [],
        }
        verification_path = self.write_json("codebase-verification.json", verification)
        self.run_tool(
            "record-verification",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(verification_path),
        )

        state = self.load("state.json")
        self.assertEqual(state["phase"], "COMPLETE")
        self.assertEqual(self.load("scope.json")["identity"]["actual_scope"], "codebase")
        self.assertEqual(self.load("ledger.json")["findings"][0]["finding_id"], "F001")
        self.assertEqual(plan["items"][0]["allowed_paths"], ["src/service.py"])
        self.assertEqual(fix_summary["changed_paths"], ["src/service.py"])
        self.assertEqual(state["finding_status"]["F001"]["status"], "fixed")
        self.assertEqual(
            state["finding_status"]["F001"]["history"][-1]["tests"]["codebase-regression"][-1][
                "exit_code"
            ],
            0,
        )
        self.assertFalse((self.run_dir / "fix-plan.amended.json").exists())


if __name__ == "__main__":
    unittest.main()
