from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reviewctl.py"
SPEC = importlib.util.spec_from_file_location("material_reviewctl", SCRIPT)
assert SPEC and SPEC.loader
reviewctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reviewctl)


class ReviewCtlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.out = self.root / "out"
        self.repo.mkdir()
        self.out.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test User")
        (self.repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        (self.repo / "test_calc.py").write_text(
            "from calc import add\nassert add(1, 2) == 3\n", encoding="utf-8"
        )
        self.git("add", ".")
        self.git("commit", "-qm", "initial")
        (self.repo / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        self.run_id = "test-run"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args], cwd=self.repo, check=True, capture_output=True, text=True
        )
        return completed.stdout.strip()

    def run_tool(self, *args: str, expected: int = 0) -> tuple[str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = reviewctl.main(list(args))
        if result != expected:
            self.fail(
                f"reviewctl returned {result}, expected {expected}\n"
                f"stdout:\n{stdout.getvalue()}\nstderr:\n{stderr.getvalue()}"
            )
        return stdout.getvalue(), stderr.getvalue()

    @property
    def run_dir(self) -> Path:
        return self.repo / ".git" / "material-code-review" / "runs" / self.run_id

    def load(self, relative: str):
        return json.loads((self.run_dir / relative).read_text(encoding="utf-8"))

    def write_json(self, name: str, value) -> Path:
        path = self.out / name
        path.write_text(json.dumps(value, indent=2), encoding="utf-8")
        return path

    def init(self) -> str:
        self.run_tool(
            "init",
            "--repo-root",
            str(self.repo),
            "--scope",
            "uncommitted",
            "--run-id",
            self.run_id,
        )
        return self.load("state.json")["scope_hash"]

    def candidate_set(self, scope_hash: str, *, include_style: bool = True):
        findings = [
            {
                "local_id": "a-wrong-op",
                "title": "add subtracts the second operand",
                "nature": "defect",
                "category": "correctness",
                "severity": "high",
                "confidence": "certain",
                "file": "calc.py",
                "line_start": 2,
                "line_end": 2,
                "evidence_side": "comparison",
                "evidence_quote": "    return a - b",
                "scope_relation": "primary",
                "related_changed_files": ["calc.py"],
                "direct_dependency": True,
                "observable_consequence": "Non-symmetric additions return the wrong result.",
                "trigger_conditions": "Call add with a nonzero second operand.",
                "counterevidence_checked": ["Existing test expects add(1, 2) == 3."],
                "why_not_preference": "The existing contract and test define addition semantics.",
                "proposed_resolution": "Restore the addition operator.",
                "estimated_fix_risk": "low",
                "requires_user_decision": False,
                "assumptions": [],
            }
        ]
        if include_style:
            findings.append(
                {
                    "local_id": "b-rename",
                    "title": "rename add to add_numbers",
                    "nature": "improvement",
                    "category": "standards",
                    "severity": "low",
                    "confidence": "high",
                    "file": "calc.py",
                    "line_start": 1,
                    "line_end": 1,
                    "evidence_side": "comparison",
                    "evidence_quote": "def add(a, b):",
                    "scope_relation": "primary",
                    "related_changed_files": ["calc.py"],
                    "direct_dependency": False,
                    "observable_consequence": "The shorter name could be read less explicitly.",
                    "trigger_conditions": "A maintainer reads the helper name.",
                    "counterevidence_checked": ["No repository naming rule requires the longer name."],
                    "why_not_preference": "Claimed as readability, though no semantic issue exists.",
                    "proposed_resolution": "Rename the function and callers.",
                    "estimated_fix_risk": "medium",
                    "requires_user_decision": True,
                    "assumptions": [],
                }
            )
        return {
            "schema_version": "material-review/candidate-set/v1",
            "scope_hash": scope_hash,
            "reviewer_id": "correctness",
            "independence_group": "model-a",
            "review_mode": "subagent",
            "findings": findings,
            "coverage": {
                "files_reviewed": ["calc.py", "test_calc.py"],
                "areas": ["correctness", "standards"],
                "limitations": [],
            },
        }

    def adjudication(self, scope_hash: str, candidate_hash: str, *, include_style: bool = True):
        groups = [
            {
                "group_id": "G001",
                "candidate_ids": ["C001"],
                "canonical_title": "add subtracts the second operand",
                "nature": "defect",
                "category": "correctness",
                "severity": "high",
                "confidence": "certain",
                "file": "calc.py",
                "line_start": 2,
                "line_end": 2,
                "evidence_side": "comparison",
                "evidence_quote": "    return a - b",
                "source_reviewers": ["correctness"],
                "source_independence_groups": ["model-a"],
                "validation": {
                    "mode": "independent",
                    "validator_id": "validator",
                    "independence_group": "model-b",
                    "verdict": "confirmed",
                    "reason": "The operator contradicts the function contract and test.",
                    "evidence_checked": ["calc.py:2", "test_calc.py:2"],
                    "counterevidence": ["No wrapper corrects the result."],
                    "causality": "introduced",
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
                "decision_reason": "The change deterministically breaks core behavior.",
                "discard_reason_code": None,
                "recommended_action": "fix_now",
                "required_pre_fix_verification": None,
            }
        ]
        if include_style:
            groups.append(
                {
                    "group_id": "G002",
                    "candidate_ids": ["C002"],
                    "canonical_title": "rename add to add_numbers",
                    "nature": "improvement",
                    "category": "standards",
                    "severity": "low",
                    "confidence": "high",
                    "file": "calc.py",
                    "line_start": 1,
                    "line_end": 1,
                    "evidence_side": "comparison",
                    "evidence_quote": "def add(a, b):",
                    "source_reviewers": ["correctness"],
                    "source_independence_groups": ["model-a"],
                    "validation": {
                        "mode": "independent",
                        "validator_id": "validator",
                        "independence_group": "model-b",
                        "verdict": "rejected",
                        "reason": "No rule or semantic consequence supports the rename.",
                        "evidence_checked": ["calc.py:1"],
                        "counterevidence": ["Existing API and test use add consistently."],
                        "causality": "introduced",
                        "root_cause_supported": False,
                    },
                    "materiality": {
                        "concrete_evidence": True,
                        "plausible_negative_consequence": False,
                        "beyond_preference": False,
                        "current_scope_relevance": True,
                        "improvement_current_cost": False,
                        "improvement_benefit_exceeds_churn": False,
                        "coverage_targets_fragile_behavior": None,
                    },
                    "disposition": "discard",
                    "decision_reason": "This is a naming preference with API churn and no demonstrated cost.",
                    "discard_reason_code": "STYLE_OR_LINTER",
                    "recommended_action": "none",
                    "required_pre_fix_verification": None,
                }
            )
        return {
            "schema_version": "material-review/adjudication/v1",
            "scope_hash": scope_hash,
            "candidate_bundle_hash": candidate_hash,
            "adjudicator_id": "controller",
            "groups": groups,
            "verdict": "SHOULD FIX BEFORE MERGE",
            "summary": "One material correctness defect remains.",
            "limitations": [],
        }

    def reach_adjudicated(self, *, include_style: bool = True) -> str:
        scope_hash = self.init()
        candidate_path = self.write_json(
            "candidate.json", self.candidate_set(scope_hash, include_style=include_style)
        )
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
        adjudication_path = self.write_json(
            "adjudication.json",
            self.adjudication(scope_hash, candidate_hash, include_style=include_style),
        )
        self.run_tool(
            "compile-ledger",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(adjudication_path),
        )
        return scope_hash

    def plan_payload(
        self,
        scope_hash: str,
        gate_hash: str,
        *,
        allowed_paths: list[str] | None = None,
        test_command: str = "grep -Fq 'return a + b' calc.py",
        global_tests: list[dict] | None = None,
    ) -> dict:
        return {
            "schema_version": "material-review/fix-plan/v1",
            "scope_hash": scope_hash,
            "findings_gate_hash": gate_hash,
            "plan_summary": "Restore addition and run the regression command.",
            "items": [
                {
                    "finding_id": "F001",
                    "root_cause": "The operator was changed from addition to subtraction.",
                    "objective": "add(1, 2) returns 3.",
                    "depends_on": [],
                    "steps": ["Replace subtraction with addition."],
                    "allowed_paths": allowed_paths or ["calc.py"],
                    "tests": [
                        {
                            "id": "unit-regression",
                            "command": test_command,
                            "working_directory": ".",
                            "required": True,
                            "timeout_seconds": 30,
                            "purpose": "Verify the approved operator repair.",
                        }
                    ],
                    "manual_verification": [],
                    "rollback_strategy": "Restore the per-finding checkpoint.",
                    "risk_controls": ["Do not change the public signature."],
                    "success_evidence": ["unit-regression exits 0"],
                    "max_attempts": 2,
                }
            ],
            "global_tests": global_tests or [],
            "no_unrelated_cleanup": True,
            "no_new_improvements_during_fix": True,
            "post_fix_review_scope": "approved_findings_and_fix_introduced_regressions_only",
            "scope_expansion_policy": "restore_and_reapprove",
            "max_repair_rounds": 1,
        }

    def approve_and_plan(
        self,
        *,
        test_command: str = "grep -Fq 'return a + b' calc.py",
        global_tests: list[dict] | None = None,
    ) -> tuple[str, dict]:
        scope_hash = self.reach_adjudicated()
        self.run_tool(
            "gate-findings",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--approve",
            "F001",
            "--user-statement",
            "Approve F001 and reject no other kept finding.",
        )
        gate_hash = self.load("gates/findings.json")["receipt_hash"]
        plan = self.plan_payload(
            scope_hash,
            gate_hash,
            test_command=test_command,
            global_tests=global_tests,
        )
        plan_path = self.write_json("plan.json", plan)
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
            "Approve the exact plan and command.",
        )
        return scope_hash, self.load("fix-plan.json")

    def begin_fixed_and_prepare(self) -> tuple[str, dict, dict]:
        scope_hash, plan = self.approve_and_plan()
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
        (self.repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        self.run_tool(
            "run-test",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--finding",
            "F001",
            "--test",
            "unit-regression",
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
            "Restored addition.",
        )
        self.run_tool(
            "prepare-verification",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
        )
        return scope_hash, plan, self.load("fix-summary.json")

    def test_scope_includes_untracked_and_detects_staleness(self) -> None:
        (self.repo / "new_module.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.init()
        paths = {entry["path"] for entry in self.load("files.json")}
        self.assertEqual(paths, {"calc.py", "new_module.py"})
        (self.repo / "calc.py").write_text("def add(a, b):\n    return a * b\n", encoding="utf-8")
        self.run_tool(
            "check-scope",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            expected=2,
        )
        self.assertTrue((self.run_dir / "scope-staleness.json").exists())

    def test_ledger_keeps_and_discards_every_candidate_and_gate_is_exact(self) -> None:
        self.reach_adjudicated(include_style=True)
        ledger = self.load("ledger.json")
        self.assertEqual([item["finding_id"] for item in ledger["findings"]], ["F001"])
        self.assertEqual(ledger["discarded"][0]["discard_reason_code"], "STYLE_OR_LINTER")
        self.run_tool(
            "gate-findings",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--user-statement",
            "No disposition supplied.",
            expected=2,
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
            "Approve F001.",
        )
        self.assertEqual(self.load("state.json")["phase"], "FINDINGS_APPROVED")

    def test_plan_rejects_unapproved_or_missing_ids(self) -> None:
        scope_hash = self.reach_adjudicated()
        self.run_tool(
            "gate-findings",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--approve",
            "F001",
            "--user-statement",
            "Approve F001.",
        )
        gate_hash = self.load("gates/findings.json")["receipt_hash"]
        invalid_plan = {
            "schema_version": "material-review/fix-plan/v1",
            "scope_hash": scope_hash,
            "findings_gate_hash": gate_hash,
            "plan_summary": "Invalid empty item set.",
            "items": [],
            "global_tests": [],
            "no_unrelated_cleanup": True,
            "no_new_improvements_during_fix": True,
            "post_fix_review_scope": "approved_findings_and_fix_introduced_regressions_only",
            "scope_expansion_policy": "restore_and_reapprove",
            "max_repair_rounds": 1,
        }
        path = self.write_json("invalid-plan.json", invalid_plan)
        self.run_tool(
            "validate-plan",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(path),
            expected=2,
        )
        self.assertEqual(self.load("state.json")["phase"], "FINDINGS_APPROVED")

    def test_plan_rejects_directory_write_boundaries(self) -> None:
        scope_hash = self.reach_adjudicated()
        self.run_tool(
            "gate-findings",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--approve",
            "F001",
            "--user-statement",
            "Approve F001.",
        )
        gate_hash = self.load("gates/findings.json")["receipt_hash"]
        (self.repo / "existing-dir").mkdir()
        invalid_plan = self.plan_payload(scope_hash, gate_hash, allowed_paths=["existing-dir"])
        path = self.write_json("directory-plan.json", invalid_plan)
        self.run_tool(
            "validate-plan",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(path),
            expected=2,
        )
        self.assertEqual(self.load("state.json")["phase"], "FINDINGS_APPROVED")

    def test_gate_a_all_rejected_preserves_material_verdict(self) -> None:
        self.reach_adjudicated()
        self.run_tool(
            "gate-findings",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--reject",
            "F001",
            "--user-statement",
            "Reject F001 and make no repair.",
        )
        self.assertEqual(self.load("state.json")["phase"], "COMPLETE")
        completion = (self.run_dir / "completion.md").read_text(encoding="utf-8")
        self.assertIn("No findings were approved for repair.", completion)
        self.assertIn("SHOULD FIX BEFORE MERGE", completion)
        self.assertNotIn("No material improvements recommended.", completion)

    def test_ready_verdict_is_rejected_when_a_finding_is_kept(self) -> None:
        scope_hash = self.init()
        candidate_path = self.write_json("candidate.json", self.candidate_set(scope_hash))
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
        adjudication = self.adjudication(scope_hash, candidate_hash)
        adjudication["verdict"] = "READY"
        path = self.write_json("invalid-ready.json", adjudication)
        self.run_tool(
            "compile-ledger",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(path),
            expected=2,
        )
        self.assertEqual(self.load("state.json")["phase"], "CANDIDATES_CAPTURED")

    def test_boundary_violation_is_rejected_and_checkpoint_restores(self) -> None:
        self.approve_and_plan()
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
        original_test = (self.repo / "test_calc.py").read_text(encoding="utf-8")
        (self.repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        (self.repo / "test_calc.py").write_text("raise RuntimeError('unapproved')\n", encoding="utf-8")
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
            "Bad attempt.",
            expected=2,
        )
        self.run_tool(
            "rollback-finding",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--finding",
            "F001",
            "--reason",
            "Unapproved test file changed.",
        )
        self.assertEqual((self.repo / "calc.py").read_text(encoding="utf-8"), "def add(a, b):\n    return a - b\n")
        self.assertEqual((self.repo / "test_calc.py").read_text(encoding="utf-8"), original_test)

    def test_approved_test_cannot_silently_mutate_an_allowed_path(self) -> None:
        mutation_command = "printf 'def add(a, b):\\n    return 999\\n' > calc.py"
        self.approve_and_plan(test_command=mutation_command)
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
        repaired = "def add(a, b):\n    return a + b\n"
        (self.repo / "calc.py").write_text(repaired, encoding="utf-8")
        self.run_tool(
            "run-test",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--finding",
            "F001",
            "--test",
            "unit-regression",
            expected=2,
        )
        self.assertEqual((self.repo / "calc.py").read_text(encoding="utf-8"), repaired)
        state = self.load("state.json")
        result = state["active_finding"]["test_results"]["unit-regression"][-1]
        self.assertTrue(result["restored_after_mutation"])
        self.assertEqual(result["changed_paths_by_test"], ["calc.py"])

    def test_global_test_cannot_silently_mutate_an_allowed_path(self) -> None:
        global_test = {
            "id": "global-regression",
            "command": "printf 'def add(a, b):\\n    return 999\\n' > calc.py",
            "working_directory": ".",
            "required": True,
            "timeout_seconds": 30,
            "purpose": "Exercise the global-test non-mutation control.",
        }
        self.approve_and_plan(global_tests=[global_test])
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
        repaired = "def add(a, b):\n    return a + b\n"
        (self.repo / "calc.py").write_text(repaired, encoding="utf-8")
        self.run_tool(
            "run-test",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--finding",
            "F001",
            "--test",
            "unit-regression",
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
            "Restored addition.",
        )
        self.run_tool(
            "run-global-test",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--test",
            "global-regression",
            expected=2,
        )
        self.assertEqual((self.repo / "calc.py").read_text(encoding="utf-8"), repaired)
        result = self.load("state.json")["global_test_results"]["global-regression"][-1]
        self.assertTrue(result["restored_after_mutation"])
        self.assertEqual(result["changed_paths_by_test"], ["calc.py"])
        self.assertEqual(result["control_mutations_by_test"], [])

    @unittest.skipUnless(hasattr(Path, "symlink_to"), "symlinks unavailable")
    def test_checkpoint_preserves_final_symlink_and_rejects_parent_escape(self) -> None:
        target = self.repo / "target.txt"
        target.write_text("target\n", encoding="utf-8")
        link = self.repo / "link.txt"
        try:
            link.symlink_to("target.txt")
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")

        resolved = reviewctl.repo_path(self.repo, "link.txt")
        self.assertEqual(reviewctl.path_state(resolved)["type"], "symlink")
        checkpoint = self.out / "symlink-checkpoint"
        reviewctl.create_checkpoint(self.repo, checkpoint, ["link.txt", "target.txt"])
        link.unlink()
        link.write_text("not a link\n", encoding="utf-8")
        reviewctl.restore_checkpoint(self.repo, checkpoint)
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.readlink(), Path("target.txt"))

        outside = self.root / "outside"
        outside.mkdir()
        escape = self.repo / "escape"
        escape.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(reviewctl.ReviewError):
            reviewctl.repo_path(self.repo, "escape/file.txt")

    def test_end_to_end_success_reaches_complete_without_reopening_improvements(self) -> None:
        scope_hash, plan, fix_summary = self.begin_fixed_and_prepare()
        verification = {
            "schema_version": "material-review/verification/v1",
            "scope_hash": scope_hash,
            "plan_hash": plan["plan_hash"],
            "fix_summary_hash": fix_summary["fix_summary_hash"],
            "verifier_id": "postfix",
            "independence_group": "model-c",
            "mode": "independent",
            "finding_results": [
                {
                    "finding_id": "F001",
                    "status": "resolved",
                    "root_cause_resolved": True,
                    "reason": "The approved operator repair is present and its required test passed.",
                    "evidence_checked": ["calc.py:2 -- return a + b"],
                    "tests_checked": ["unit-regression"],
                }
            ],
            "regressions": [],
            "record_only_observations": [
                {
                    "title": "Potential naming preference remains out of scope",
                    "file": "calc.py",
                    "line_start": 1,
                    "reason": "Recorded only; post-fix verification cannot start a new improvement loop.",
                }
            ],
            "verdict": "pass",
            "summary": "The approved finding is resolved with no fix-caused regression.",
            "limitations": [],
        }
        path = self.write_json("verification-pass.json", verification)
        self.run_tool(
            "record-verification",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(path),
        )
        self.assertEqual(self.load("state.json")["phase"], "COMPLETE")
        recorded = self.load("verification.json")
        self.assertEqual(recorded["record_only_observations"][0]["title"], "Potential naming preference remains out of scope")
        self.assertFalse((self.run_dir / "fix-plan.amended.json").exists())

    def test_empty_material_set_requires_explicit_gate_and_completes(self) -> None:
        scope_hash = self.init()
        candidate_set = {
            "schema_version": "material-review/candidate-set/v1",
            "scope_hash": scope_hash,
            "reviewer_id": "correctness",
            "independence_group": "model-a",
            "review_mode": "subagent",
            "findings": [],
            "coverage": {
                "files_reviewed": ["calc.py", "test_calc.py"],
                "areas": ["correctness"],
                "limitations": [],
            },
        }
        candidate_path = self.write_json("empty-candidate.json", candidate_set)
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
            "adjudicator_id": "controller",
            "groups": [],
            "verdict": "READY",
            "summary": "No candidate passed the materiality and evidence gates.",
            "limitations": [],
        }
        adjudication_path = self.write_json("empty-adjudication.json", adjudication)
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
            "--accept-empty",
            "--user-statement",
            "Accept the empty material finding set.",
        )
        self.assertEqual(self.load("state.json")["phase"], "COMPLETE")
        completion = (self.run_dir / "completion.md").read_text(encoding="utf-8")
        self.assertIn("No material improvements recommended.", completion)

    def test_out_of_plan_regression_requires_amendment(self) -> None:
        scope_hash, plan, fix_summary = self.begin_fixed_and_prepare()
        verification = {
            "schema_version": "material-review/verification/v1",
            "scope_hash": scope_hash,
            "plan_hash": plan["plan_hash"],
            "fix_summary_hash": fix_summary["fix_summary_hash"],
            "verifier_id": "postfix",
            "independence_group": "model-c",
            "mode": "independent",
            "finding_results": [
                {
                    "finding_id": "F001",
                    "status": "unresolved",
                    "root_cause_resolved": False,
                    "reason": "A claimed regression requires a test-file repair.",
                    "evidence_checked": ["calc.py:2"],
                    "tests_checked": ["unit-regression"],
                }
            ],
            "regressions": [
                {
                    "regression_id": "R001",
                    "title": "Test expectation needs an unapproved edit",
                    "severity": "medium",
                    "file": "test_calc.py",
                    "line_start": 2,
                    "evidence_quote": "assert add(1, 2) == 3",
                    "caused_by_fix": True,
                    "repair_owner_finding_id": "F001",
                    "repair_paths": ["test_calc.py"],
                    "reason": "Repair request is intentionally outside the approved path for this contract test.",
                }
            ],
            "record_only_observations": [
                {
                    "title": "Unrelated naming idea",
                    "file": "calc.py",
                    "line_start": 1,
                    "reason": "Record-only; the verifier cannot reopen improvement review.",
                }
            ],
            "verdict": "repair_required",
            "summary": "The requested repair exceeds the Gate-B path boundary.",
            "limitations": [],
        }
        path = self.write_json("verification-out-of-plan.json", verification)
        self.run_tool(
            "record-verification",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(path),
        )
        self.assertEqual(self.load("state.json")["phase"], "PLAN_AMENDMENT_REQUIRED")
        self.assertEqual(self.load("verification.json")["record_only_observations"][0]["title"], "Unrelated naming idea")


    def test_run_id_and_in_worktree_artifact_root_are_rejected(self) -> None:
        self.run_tool(
            "init",
            "--repo-root",
            str(self.repo),
            "--scope",
            "uncommitted",
            "--run-id",
            "../escape",
            expected=2,
        )
        self.run_tool(
            "init",
            "--repo-root",
            str(self.repo),
            "--scope",
            "uncommitted",
            "--run-id",
            "safe-run",
            "--artifact-root",
            str(self.repo / "review-artifacts"),
            expected=2,
        )
        self.assertFalse((self.root / "escape").exists())
        self.assertFalse((self.repo / "review-artifacts").exists())

    def test_shared_artifact_run_cannot_be_reused_for_another_repository(self) -> None:
        shared = self.out / "shared-artifacts"
        self.run_tool(
            "init",
            "--repo-root",
            str(self.repo),
            "--scope",
            "uncommitted",
            "--run-id",
            self.run_id,
            "--artifact-root",
            str(shared),
        )

        repo_two = self.root / "repo-two"
        repo_two.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo_two, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_two, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_two, check=True)
        (repo_two / "calc.py").write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo_two, check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo_two, check=True)
        (repo_two / "calc.py").write_text("VALUE = 2\n", encoding="utf-8")

        self.run_tool(
            "check-scope",
            "--repo-root",
            str(repo_two),
            "--run-id",
            self.run_id,
            "--artifact-root",
            str(shared),
            expected=2,
        )

    def test_tampered_plan_is_rejected_before_gate_b(self) -> None:
        scope_hash = self.reach_adjudicated()
        self.run_tool(
            "gate-findings",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--approve",
            "F001",
            "--user-statement",
            "Approve F001.",
        )
        gate_hash = self.load("gates/findings.json")["receipt_hash"]
        plan_path = self.write_json("plan.json", self.plan_payload(scope_hash, gate_hash))
        self.run_tool(
            "validate-plan",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(plan_path),
        )
        persisted = self.load("fix-plan.json")
        persisted["items"][0]["steps"].append("Unapproved extra edit.")
        (self.run_dir / "fix-plan.json").write_text(json.dumps(persisted, indent=2), encoding="utf-8")
        self.run_tool(
            "gate-plan",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--approve",
            "--user-statement",
            "Attempt to approve a tampered plan.",
            expected=2,
        )
        self.assertEqual(self.load("state.json")["phase"], "PLAN_VALIDATED")

    def test_tampered_frozen_snapshot_is_rejected_during_ingestion(self) -> None:
        scope_hash = self.init()
        scope = self.load("scope.json")
        calc_entry = next(item for item in scope["identity"]["files"] if item["path"] == "calc.py")
        snapshot_rel = calc_entry["comparison_state"]["snapshot_path"]
        (self.run_dir / snapshot_rel).write_text("def add(a, b):\n    return 999\n", encoding="utf-8")
        candidate_path = self.write_json("candidate.json", self.candidate_set(scope_hash))
        self.run_tool(
            "ingest-candidates",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(candidate_path),
            expected=2,
        )
        rejection = self.load("candidate-rejections.json")[0]["reason"]
        self.assertIn("failed its content hash check", rejection)

    def test_checkpoint_snapshot_tampering_blocks_restore_before_mutation(self) -> None:
        checkpoint = self.out / "tamper-checkpoint"
        reviewctl.create_checkpoint(self.repo, checkpoint, ["calc.py"])
        (checkpoint / "content" / "calc.py").write_text("tampered\n", encoding="utf-8")
        modified = "def add(a, b):\n    return 777\n"
        (self.repo / "calc.py").write_text(modified, encoding="utf-8")
        with self.assertRaises(reviewctl.ReviewError):
            reviewctl.restore_checkpoint(self.repo, checkpoint)
        self.assertEqual((self.repo / "calc.py").read_text(encoding="utf-8"), modified)

    def test_plan_rejects_unsafe_test_identifier(self) -> None:
        scope_hash = self.reach_adjudicated()
        self.run_tool(
            "gate-findings",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--approve",
            "F001",
            "--user-statement",
            "Approve F001.",
        )
        gate_hash = self.load("gates/findings.json")["receipt_hash"]
        plan = self.plan_payload(scope_hash, gate_hash)
        plan["items"][0]["tests"][0]["id"] = "../escape"
        path = self.write_json("unsafe-test-id-plan.json", plan)
        self.run_tool(
            "validate-plan",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(path),
            expected=2,
        )


if __name__ == "__main__":
    unittest.main()
