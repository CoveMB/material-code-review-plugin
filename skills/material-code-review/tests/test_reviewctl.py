from __future__ import annotations

import contextlib
import copy
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

    def make_run_legacy(self) -> None:
        state = self.load("state.json")
        state.pop("coverage_required", None)
        state.pop("workflow_profile", None)
        (self.run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    def reach_plan_approved(self) -> None:
        self.approve_and_plan()

    def reach_fixing(self) -> None:
        self.approve_and_plan()
        self.run_tool("begin-fix", "--repo-root", str(self.repo), "--run-id", self.run_id)

    def coverage_plan(
        self,
        scope_hash: str,
        *,
        output_paths_present: bool = True,
        persisted_config_present: bool = True,
        omit_lens: str | None = None,
    ) -> dict:
        assessments = [
            {
                "code": "user_selectable_output_paths",
                "present": output_paths_present,
                "rationale": "Configurable generated and report destinations were checked.",
                "evidence_paths": ["calc.py"] if output_paths_present else [],
            },
            {
                "code": "persisted_config_semantics",
                "present": persisted_config_present,
                "rationale": "Optional durable configuration semantics were checked.",
                "evidence_paths": ["calc.py"] if persisted_config_present else [],
            },
        ]
        assignments = (
            "correctness",
            "test_adequacy",
            "standards_alignment",
            "reliability",
            "migration_data_safety",
            "api_config_compatibility",
        )
        return {
            "schema_version": "material-review/coverage-plan/v1",
            "scope_hash": scope_hash,
            "workflow_profile": "material_review",
            "risk_assessments": assessments,
            "lenses": [
                {
                    "lens_id": lens_id,
                    "required": True,
                    "reviewer_id": "shared-reviewer" if lens_id in {"migration_data_safety", "api_config_compatibility"} else lens_id,
                    "independence_group": "model-a",
                    "review_mode": "subagent",
                }
                for lens_id in assignments
                if lens_id != omit_lens
            ],
        }

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
                "files_reviewed": ["calc.py"],
                "areas": ["correctness", "standards"],
                "limitations": [],
            },
        }

    def empty_candidate_set_v2(self, scope_hash: str, coverage_hash: str, assignment: dict) -> dict:
        return {
            "schema_version": "material-review/candidate-set/v2",
            "scope_hash": scope_hash,
            "coverage_plan_hash": coverage_hash,
            "lens_id": assignment["lens_id"],
            "reviewer_id": assignment["reviewer_id"],
            "independence_group": assignment["independence_group"],
            "review_mode": assignment["review_mode"],
            "findings": [],
            "coverage": {"files_reviewed": ["calc.py"], "areas": [assignment["lens_id"]], "limitations": []},
        }

    def init_with_recorded_coverage(self) -> str:
        scope_hash = self.init()
        plan_path = self.write_json("coverage-input.json", self.coverage_plan(scope_hash))
        self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(plan_path))
        return scope_hash

    def candidate_paths_for_coverage(
        self,
        scope_hash: str,
        *,
        primary_candidate: dict | None = None,
        omit_lens: str | None = None,
    ) -> list[Path]:
        plan = self.load("coverage-plan.json")
        coverage_hash = plan["coverage_plan_hash"]
        paths: list[Path] = []
        for assignment in plan["lenses"]:
            lens_id = assignment["lens_id"]
            if lens_id == omit_lens:
                continue
            if lens_id == "correctness":
                payload = primary_candidate or self.candidate_set(scope_hash)
                payload["schema_version"] = "material-review/candidate-set/v2"
                payload["coverage_plan_hash"] = coverage_hash
                payload["lens_id"] = lens_id
                payload["reviewer_id"] = assignment["reviewer_id"]
                payload["independence_group"] = assignment["independence_group"]
                payload["review_mode"] = assignment["review_mode"]
            else:
                payload = self.empty_candidate_set_v2(scope_hash, coverage_hash, assignment)
            paths.append(self.write_json(f"candidate-{lens_id}.json", payload))
        return paths

    def ingest_candidate_paths(self, paths: list[Path], *, expected: int = 0) -> tuple[str, str]:
        input_args = [value for path in paths for value in ("--input", str(path))]
        return self.run_tool("ingest-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id, *input_args, expected=expected)

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
                "repair_direction": {
                    "status": "reviewed",
                    "confidence": "high",
                    "root_cause": "The implementation violates the established addition contract.",
                    "objective": "Restore addition while preserving the public function signature.",
                    "smallest_safe_change": "Restore the addition operator and retain the existing API.",
                    "constraints_to_preserve": ["Keep the public add(a, b) signature unchanged."],
                    "state_or_exception_cases": ["Negative operands retain addition semantics."],
                    "alternatives_checked": ["Changing the test would redefine established behavior."],
                    "required_test_evidence": ["A regression test fails for subtraction and passes for addition."],
                    "open_user_decisions": [],
                    "known_limits": []
                },
            }
        ]
        groups[0]["repair_audit"] = {
            "scope_hash": scope_hash,
            "candidate_ids": ["C001"],
            "repair_direction_hash": reviewctl.canonical_hash(groups[0]["repair_direction"]),
            "mode": "independent",
            "auditor_id": "repair-auditor",
            "independence_group": "model-c",
            "trigger": "retained_group",
            "rationale": "A fresh audit confirmed the smallest safe root-cause correction.",
            "evidence_checked": ["calc.py:2", "test_calc.py:2"],
            "counterevidence": ["Changing the test would redefine the established contract."],
        }
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
                    "repair_direction": None,
                    "repair_audit": None,
                }
            )
        return {
            "schema_version": "material-review/adjudication/v3",
            "scope_hash": scope_hash,
            "candidate_bundle_hash": candidate_hash,
            "adjudicator_id": "controller",
            "groups": groups,
            "verdict": "SHOULD FIX BEFORE MERGE",
            "summary": "One material correctness defect remains.",
            "limitations": [],
        }

    def reach_adjudicated(self, *, include_style: bool = True) -> str:
        scope_hash = self.init_with_recorded_coverage()
        paths = self.candidate_paths_for_coverage(
            scope_hash, primary_candidate=self.candidate_set(scope_hash, include_style=include_style)
        )
        self.ingest_candidate_paths(paths)
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
        finding = self.load("ledger.json")["findings"][0]
        direction = finding["repair_direction"]
        return {
            "schema_version": "material-review/fix-plan/v2",
            "scope_hash": scope_hash,
            "findings_gate_hash": gate_hash,
            "plan_summary": "Restore addition and run the regression command.",
            "items": [
                {
                    "finding_id": "F001",
                    "root_cause": "The operator was changed from addition to subtraction.",
                    "objective": "add(1, 2) returns 3.",
                    "repair_direction_assessment": {
                        "repair_direction_hash": finding["repair_direction_hash"],
                        "constraint_handling": [
                            {"source": value, "handling": f"Preserve this constraint: {value}"}
                            for value in direction["constraints_to_preserve"]
                        ],
                        "state_or_exception_handling": [
                            {"source": value, "handling": f"Exercise and preserve this case: {value}"}
                            for value in direction["state_or_exception_cases"]
                        ],
                        "open_user_decision_handling": [
                            {"source": value, "handling": f"Resolve this decision before mutation: {value}"}
                            for value in direction["open_user_decisions"]
                        ],
                        "alternatives_considered": direction["alternatives_checked"]
                        or ["No wider alternative is needed for this local correction."],
                        "diverges": False,
                        "divergence_rationale": None,
                    },
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

    def test_ledger_uses_adjudicated_repair_direction(self) -> None:
        scope_hash = self.init_with_recorded_coverage()
        candidates = self.candidate_set(scope_hash, include_style=False)
        candidates["findings"][0]["proposed_resolution"] = "Unsafe candidate suggestion."
        self.ingest_candidate_paths(self.candidate_paths_for_coverage(scope_hash, primary_candidate=candidates))
        candidate_hash = self.load("candidates.json")["candidate_bundle_hash"]
        adjudication = self.adjudication(scope_hash, candidate_hash, include_style=False)
        adjudication["groups"][0]["repair_direction"]["smallest_safe_change"] = "Restore only the operator."
        adjudication["groups"][0]["repair_audit"]["repair_direction_hash"] = reviewctl.canonical_hash(
            adjudication["groups"][0]["repair_direction"]
        )
        adjudication_path = self.write_json("adjudication-repair.json", adjudication)
        self.run_tool("compile-ledger", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(adjudication_path))
        ledger = self.load("ledger.json")
        self.assertEqual(ledger["findings"][0]["repair_direction"]["smallest_safe_change"], "Restore only the operator.")
        self.assertEqual(
            ledger["findings"][0]["repair_direction_hash"],
            reviewctl.canonical_hash(ledger["findings"][0]["repair_direction"]),
        )
        self.assertEqual(ledger["findings"][0]["repair_audit"]["mode"], "independent")
        rendered = (self.run_dir / "ledger.md").read_text(encoding="utf-8")
        self.assertIn("Gate A approves findings for repair planning only", rendered)
        self.assertIn("Repair-direction audit", rendered)
        self.assertIn("repair-auditor", rendered)
        self.assertNotIn("Unsafe candidate suggestion", rendered)
        self.assertNotIn("Suggested response", rendered)

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
            "schema_version": "material-review/fix-plan/v2",
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

    def test_plan_rejects_legacy_or_unbound_direction_assessments(self) -> None:
        scope_hash = self.reach_adjudicated(include_style=False)
        self.run_tool(
            "gate-findings", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--approve", "F001", "--user-statement", "Approve F001.",
        )
        gate_hash = self.load("gates/findings.json")["receipt_hash"]
        valid_plan = self.plan_payload(scope_hash, gate_hash)

        legacy = copy.deepcopy(valid_plan)
        legacy["schema_version"] = "material-review/fix-plan/v1"
        wrong_hash = copy.deepcopy(valid_plan)
        wrong_hash["items"][0]["repair_direction_assessment"]["repair_direction_hash"] = "0" * 64
        missing_constraint = copy.deepcopy(valid_plan)
        missing_constraint["items"][0]["repair_direction_assessment"]["constraint_handling"] = []
        missing_state = copy.deepcopy(valid_plan)
        missing_state["items"][0]["repair_direction_assessment"]["state_or_exception_handling"] = []
        unexplained_divergence = copy.deepcopy(valid_plan)
        unexplained_divergence["items"][0]["repair_direction_assessment"]["diverges"] = True

        for name, payload in (
            ("legacy", legacy),
            ("wrong-hash", wrong_hash),
            ("missing-constraint", missing_constraint),
            ("missing-state", missing_state),
            ("unexplained-divergence", unexplained_divergence),
        ):
            with self.subTest(name=name):
                path = self.write_json(f"{name}.json", payload)
                self.run_tool(
                    "validate-plan", "--repo-root", str(self.repo), "--run-id", self.run_id,
                    "--input", str(path), expected=2,
                )
                self.assertEqual(self.load("state.json")["phase"], "FINDINGS_APPROVED")

        valid_path = self.write_json("valid-v2-plan.json", valid_plan)
        self.run_tool(
            "validate-plan", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--input", str(valid_path),
        )
        rendered = (self.run_dir / "fix-plan.md").read_text(encoding="utf-8")
        self.assertIn("Repair-direction assessment", rendered)
        self.assertIn(valid_plan["items"][0]["repair_direction_assessment"]["repair_direction_hash"], rendered)

    def test_direction_assessment_requires_every_open_user_decision(self) -> None:
        direction = {
            **self.adjudication("a" * 64, "b" * 64, include_style=False)["groups"][0]["repair_direction"],
            "status": "needs_user_decision",
            "open_user_decisions": ["Choose whether the public contract may change."],
        }
        finding = {
            "finding_id": "F001",
            "repair_direction": direction,
            "repair_direction_hash": reviewctl.canonical_hash(direction),
        }
        assessment = {
            "repair_direction_hash": finding["repair_direction_hash"],
            "constraint_handling": [
                {"source": value, "handling": "Preserve it."}
                for value in direction["constraints_to_preserve"]
            ],
            "state_or_exception_handling": [
                {"source": value, "handling": "Exercise it."}
                for value in direction["state_or_exception_cases"]
            ],
            "open_user_decision_handling": [],
            "alternatives_considered": ["Retain the current public contract."],
            "diverges": False,
            "divergence_rationale": None,
        }
        with self.assertRaisesRegex(reviewctl.ReviewError, "cover each approved direction entry exactly"):
            reviewctl.validate_repair_direction_assessment(
                assessment,
                "assessment",
                finding=finding,
            )

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
        scope_hash = self.init_with_recorded_coverage()
        self.ingest_candidate_paths(self.candidate_paths_for_coverage(scope_hash))
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
        scope_hash = self.init_with_recorded_coverage()
        candidate_set = {
            "schema_version": "material-review/candidate-set/v2",
            "scope_hash": scope_hash,
            "coverage_plan_hash": self.load("coverage-plan.json")["coverage_plan_hash"],
            "lens_id": "correctness",
            "reviewer_id": "correctness",
            "independence_group": "model-a",
            "review_mode": "subagent",
            "findings": [],
            "coverage": {
                "files_reviewed": ["calc.py"],
                "areas": ["correctness"],
                "limitations": [],
            },
        }
        self.ingest_candidate_paths(self.candidate_paths_for_coverage(scope_hash, primary_candidate=candidate_set))
        candidate_hash = self.load("candidates.json")["candidate_bundle_hash"]
        adjudication = {
            "schema_version": "material-review/adjudication/v3",
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
        scope_hash = self.init_with_recorded_coverage()
        scope = self.load("scope.json")
        calc_entry = next(item for item in scope["identity"]["files"] if item["path"] == "calc.py")
        snapshot_rel = calc_entry["comparison_state"]["snapshot_path"]
        (self.run_dir / snapshot_rel).write_text("def add(a, b):\n    return 999\n", encoding="utf-8")
        self.ingest_candidate_paths(self.candidate_paths_for_coverage(scope_hash), expected=2)
        rejection = self.load("candidate-ingestion-failure.json")["rejections"][0]["reason"]
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

    def test_coverage_plan_records_exhaustive_risk_assessments(self) -> None:
        scope_hash = self.init()
        path = self.write_json("coverage-input.json", self.coverage_plan(scope_hash))
        self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path))
        state = self.load("state.json")
        artifact = self.load("coverage-plan.json")
        self.assertEqual(state["phase"], "CONTEXT_FROZEN")
        self.assertEqual(state["hashes"]["coverage_plan_hash"], artifact["coverage_plan_hash"])
        self.assertEqual({item["code"] for item in artifact["risk_assessments"]}, {
            "user_selectable_output_paths", "persisted_config_semantics",
        })

    def test_coverage_plan_requires_each_positive_risk_lens(self) -> None:
        scope_hash = self.init()
        for missing in ("reliability", "migration_data_safety", "api_config_compatibility"):
            path = self.write_json(f"missing-{missing}.json", self.coverage_plan(scope_hash, omit_lens=missing))
            _, stderr = self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path), expected=2)
            self.assertIn(f"requires {missing}", stderr)

    def test_coverage_plan_allows_repeated_reviewer_identity(self) -> None:
        scope_hash = self.init()
        path = self.write_json("shared-reviewer.json", self.coverage_plan(scope_hash))
        self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path))

    def test_coverage_plan_is_idempotent_but_not_replaceable(self) -> None:
        scope_hash = self.init()
        original = self.coverage_plan(scope_hash)
        path = self.write_json("coverage.json", original)
        self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path))
        event_count = len(self.load("state.json")["events"])
        self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path))
        self.assertEqual(len(self.load("state.json")["events"]), event_count)
        original["risk_assessments"][0]["rationale"] = "Replacement attempt."
        replacement = self.write_json("replacement.json", original)
        _, stderr = self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(replacement), expected=2)
        self.assertIn("Coverage plan is already recorded", stderr)

    def test_ingest_refuses_missing_required_lens_without_authoritative_artifacts(self) -> None:
        scope_hash = self.init_with_recorded_coverage()
        paths = self.candidate_paths_for_coverage(scope_hash, omit_lens="migration_data_safety")
        _, stderr = self.ingest_candidate_paths(paths, expected=2)
        self.assertIn("Missing required review coverage: migration_data_safety", stderr)
        self.assertEqual(self.load("state.json")["phase"], "CONTEXT_FROZEN")
        self.assertFalse((self.run_dir / "candidates.json").exists())
        self.assertTrue((self.run_dir / "candidate-ingestion-failure.json").exists())

    def test_ingest_before_recording_coverage_leaves_run_and_candidate_artifacts_unchanged(self) -> None:
        scope_hash = self.init()
        candidate_path = self.write_json("unrecorded-candidate.json", self.candidate_set(scope_hash))
        state_before = self.load("state.json")

        _, stderr = self.ingest_candidate_paths([candidate_path], expected=2)

        self.assertIn("Coverage plan is not recorded", stderr)
        self.assertEqual(self.load("state.json"), state_before)
        for artifact in (
            "candidates.json",
            "candidate-rejections.json",
            "candidates.md",
            "candidate-ingestion-failure.json",
        ):
            self.assertFalse((self.run_dir / artifact).exists(), artifact)

    def test_ingest_refuses_stale_plan_hash_and_wrong_lens(self) -> None:
        scope_hash = self.init_with_recorded_coverage()
        paths = self.candidate_paths_for_coverage(scope_hash)
        payload = json.loads(paths[0].read_text(encoding="utf-8"))
        payload["coverage_plan_hash"] = "0" * 64
        paths[0].write_text(json.dumps(payload), encoding="utf-8")
        _, stderr = self.ingest_candidate_paths(paths, expected=2)
        self.assertIn("coverage_plan_hash does not match", stderr)

    def test_required_lens_must_cover_risk_evidence_paths(self) -> None:
        scope_hash = self.init_with_recorded_coverage()
        paths = self.candidate_paths_for_coverage(scope_hash)
        migration = next(path for path in paths if "migration_data_safety" in path.name)
        payload = json.loads(migration.read_text(encoding="utf-8"))
        payload["coverage"]["files_reviewed"] = ["test_calc.py"]
        migration.write_text(json.dumps(payload), encoding="utf-8")
        _, stderr = self.ingest_candidate_paths(paths, expected=2)
        self.assertIn("did not review required risk paths: calc.py", stderr)

    def test_complete_wave_binds_coverage_hash_and_retry_succeeds(self) -> None:
        scope_hash = self.init_with_recorded_coverage()
        incomplete = self.candidate_paths_for_coverage(scope_hash, omit_lens="reliability")
        self.ingest_candidate_paths(incomplete, expected=2)
        complete = self.candidate_paths_for_coverage(scope_hash)
        self.ingest_candidate_paths(complete)
        state = self.load("state.json")
        candidates = self.load("candidates.json")
        self.assertEqual(candidates["coverage_plan_hash"], state["hashes"]["coverage_plan_hash"])
        self.assertEqual(state["phase"], "CANDIDATES_CAPTURED")

    def test_ingest_rejects_duplicate_or_unassigned_lens_without_authoritative_write(self) -> None:
        for name, mutation, expected_error in (
            ("duplicate", lambda payload: payload.update({"lens_id": "correctness"}), "Duplicate candidate lens_id: correctness"),
            ("unassigned", lambda payload: payload.update({"lens_id": "unassigned"}), "Lens is absent from coverage plan: unassigned"),
        ):
            with self.subTest(name=name):
                self.run_id = f"test-run-{name}"
                scope_hash = self.init_with_recorded_coverage()
                paths = self.candidate_paths_for_coverage(scope_hash)
                payload = json.loads(paths[1].read_text(encoding="utf-8"))
                mutation(payload)
                paths[1].write_text(json.dumps(payload), encoding="utf-8")
                _, stderr = self.ingest_candidate_paths(paths, expected=2)
                self.assertIn(expected_error, stderr)
                self.assertFalse((self.run_dir / "candidates.json").exists())

    def test_ingest_rejects_assignment_identity_mismatch(self) -> None:
        for field in ("reviewer_id", "independence_group", "review_mode"):
            with self.subTest(field=field):
                self.run_id = f"test-run-{field}"
                scope_hash = self.init_with_recorded_coverage()
                paths = self.candidate_paths_for_coverage(scope_hash)
                payload = json.loads(paths[0].read_text(encoding="utf-8"))
                payload[field] = "controller" if field == "review_mode" else "wrong-identity"
                paths[0].write_text(json.dumps(payload), encoding="utf-8")
                _, stderr = self.ingest_candidate_paths(paths, expected=2)
                self.assertIn("candidate identity does not match coverage assignment: correctness", stderr)

    def test_ingest_rejects_out_of_scope_coverage_paths(self) -> None:
        scope_hash = self.init_with_recorded_coverage()
        paths = self.candidate_paths_for_coverage(scope_hash)
        payload = json.loads(paths[0].read_text(encoding="utf-8"))
        payload["coverage"]["files_reviewed"].append("outside.py")
        paths[0].write_text(json.dumps(payload), encoding="utf-8")
        _, stderr = self.ingest_candidate_paths(paths, expected=2)
        self.assertIn("coverage.files_reviewed contains a path outside the frozen scope", stderr)

    def test_material_review_rejects_v1_candidate_set(self) -> None:
        scope_hash = self.init_with_recorded_coverage()
        path = self.write_json("candidate-v1.json", self.candidate_set(scope_hash))
        _, stderr = self.ingest_candidate_paths([path], expected=2)
        self.assertIn("unsupported schema_version", stderr)
        self.assertFalse((self.run_dir / "candidates.json").exists())

    def test_material_review_rejects_a_v2_set_with_any_invalid_finding(self) -> None:
        scope_hash = self.init_with_recorded_coverage()
        paths = self.candidate_paths_for_coverage(scope_hash)
        payload = json.loads(paths[0].read_text(encoding="utf-8"))
        payload["findings"][0]["line_start"] = 0
        paths[0].write_text(json.dumps(payload), encoding="utf-8")
        _, stderr = self.ingest_candidate_paths(paths, expected=2)
        self.assertIn("candidate set includes invalid finding", stderr)
        self.assertFalse((self.run_dir / "candidates.json").exists())

    def test_ingest_rejects_missing_or_tampered_recorded_coverage(self) -> None:
        for name, mutate in (
            ("missing", lambda: (self.run_dir / "coverage-plan.json").unlink()),
            ("tampered", lambda: (self.run_dir / "coverage-plan.json").write_text("{}", encoding="utf-8")),
        ):
            with self.subTest(name=name):
                self.run_id = f"test-run-{name}"
                scope_hash = self.init_with_recorded_coverage()
                paths = self.candidate_paths_for_coverage(scope_hash)
                mutate()
                self.ingest_candidate_paths(paths, expected=2)
                self.assertTrue((self.run_dir / "candidate-ingestion-failure.json").exists())
                self.assertFalse((self.run_dir / "candidates.json").exists())

    def test_invalid_retry_preserves_prior_authoritative_bundle(self) -> None:
        scope_hash = self.init_with_recorded_coverage()
        self.ingest_candidate_paths(self.candidate_paths_for_coverage(scope_hash))
        original = (self.run_dir / "candidates.json").read_text(encoding="utf-8")
        paths = self.candidate_paths_for_coverage(scope_hash)
        payload = json.loads(paths[0].read_text(encoding="utf-8"))
        payload["findings"][0]["line_start"] = 0
        paths[0].write_text(json.dumps(payload), encoding="utf-8")
        self.ingest_candidate_paths(paths, expected=2)
        self.assertEqual((self.run_dir / "candidates.json").read_text(encoding="utf-8"), original)
        self.assertEqual(self.load("state.json")["phase"], "CANDIDATES_CAPTURED")
        self.assertTrue((self.run_dir / "candidate-ingestion-failure.json").exists())

    def test_missing_input_retry_writes_diagnostic_without_replacing_authoritative_bundle(self) -> None:
        scope_hash = self.init_with_recorded_coverage()
        paths = self.candidate_paths_for_coverage(scope_hash)
        self.ingest_candidate_paths(paths)
        original_candidates = (self.run_dir / "candidates.json").read_text(encoding="utf-8")
        original_markdown = (self.run_dir / "candidates.md").read_text(encoding="utf-8")
        original_rejections = (self.run_dir / "candidate-rejections.json").read_text(encoding="utf-8")
        original_state = self.load("state.json")
        missing = self.out / "missing-candidate.json"

        _, stderr = self.ingest_candidate_paths([*paths, missing], expected=2)

        self.assertIn("Expected artifact file is missing", stderr)
        self.assertEqual((self.run_dir / "candidates.json").read_text(encoding="utf-8"), original_candidates)
        self.assertEqual((self.run_dir / "candidates.md").read_text(encoding="utf-8"), original_markdown)
        self.assertEqual(
            (self.run_dir / "candidate-rejections.json").read_text(encoding="utf-8"), original_rejections
        )
        state = self.load("state.json")
        self.assertEqual(state["phase"], original_state["phase"])
        self.assertEqual(
            state["hashes"]["candidate_bundle_hash"], original_state["hashes"]["candidate_bundle_hash"]
        )
        failure = self.load("candidate-ingestion-failure.json")
        self.assertEqual(failure["input_hashes"], [reviewctl.sha256_file(path) for path in paths])
        self.assertIn("Expected artifact file is missing", failure["rejections"][0]["reason"])

    def test_compile_ledger_rejects_deleted_tampered_or_stale_coverage_binding(self) -> None:
        for name in ("deleted", "tampered", "stale-candidate"):
            with self.subTest(name=name):
                self.run_id = f"test-run-{name}"
                scope_hash = self.init_with_recorded_coverage()
                self.ingest_candidate_paths(self.candidate_paths_for_coverage(scope_hash))
                candidate_hash = self.load("candidates.json")["candidate_bundle_hash"]
                adjudication_path = self.write_json(
                    f"adjudication-{name}.json", self.adjudication(scope_hash, candidate_hash)
                )
                if name == "deleted":
                    (self.run_dir / "coverage-plan.json").unlink()
                elif name == "tampered":
                    artifact = self.load("coverage-plan.json")
                    artifact["risk_assessments"][0]["rationale"] = "Tampered."
                    (self.run_dir / "coverage-plan.json").write_text(json.dumps(artifact), encoding="utf-8")
                else:
                    bundle = self.load("candidates.json")
                    bundle["coverage_plan_hash"] = "0" * 64
                    bundle.pop("candidate_bundle_hash")
                    unhashed = dict(bundle)
                    unhashed.pop("generated_at")
                    bundle["candidate_bundle_hash"] = reviewctl.canonical_hash(unhashed)
                    (self.run_dir / "candidates.json").write_text(json.dumps(bundle), encoding="utf-8")
                    state = self.load("state.json")
                    state["hashes"]["candidate_bundle_hash"] = bundle["candidate_bundle_hash"]
                    (self.run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
                _, stderr = self.run_tool(
                    "compile-ledger", "--repo-root", str(self.repo), "--run-id", self.run_id,
                    "--input", str(adjudication_path), expected=2,
                )
                self.assertIn("coverage", stderr.lower())

    def test_coverage_plan_rejects_missing_assessment_code(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan(scope_hash)
        del plan["risk_assessments"][0]["code"]
        path = self.write_json("missing-assessment-code.json", plan)
        _, stderr = self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path), expected=2)
        self.assertIn("risk_assessments[0]", stderr)

    def test_coverage_plan_rejects_duplicate_assessment_code(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan(scope_hash)
        plan["risk_assessments"][1]["code"] = "user_selectable_output_paths"
        path = self.write_json("duplicate-assessment-code.json", plan)
        _, stderr = self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path), expected=2)
        self.assertIn("assessment codes", stderr)

    def test_coverage_plan_rejects_false_assessment_with_evidence_paths(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan(scope_hash, output_paths_present=False)
        plan["risk_assessments"][0]["evidence_paths"] = ["calc.py"]
        path = self.write_json("false-with-paths.json", plan)
        _, stderr = self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path), expected=2)
        self.assertIn("must be empty", stderr)

    def test_coverage_plan_rejects_true_assessment_without_evidence_paths(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan(scope_hash)
        plan["risk_assessments"][0]["evidence_paths"] = []
        path = self.write_json("true-without-paths.json", plan)
        _, stderr = self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path), expected=2)
        self.assertIn("at least one", stderr)

    def test_coverage_plan_rejects_evidence_path_outside_scope(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan(scope_hash)
        plan["risk_assessments"][0]["evidence_paths"] = ["test_calc.py"]
        path = self.write_json("outside-scope-path.json", plan)
        _, stderr = self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path), expected=2)
        self.assertIn("not in the frozen scope", stderr)

    def test_coverage_plan_rejects_extra_top_level_or_nested_field(self) -> None:
        scope_hash = self.init()
        for name, mutate in (
            ("extra-top-level", lambda plan: plan.update({"unexpected": True})),
            ("extra-nested", lambda plan: plan["lenses"][0].update({"unexpected": True})),
        ):
            plan = self.coverage_plan(scope_hash)
            mutate(plan)
            path = self.write_json(f"{name}.json", plan)
            _, stderr = self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path), expected=2)
            self.assertIn("invalid fields", stderr)

    def test_coverage_plan_rejects_duplicate_lens_ids(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan(scope_hash)
        plan["lenses"][1]["lens_id"] = plan["lenses"][0]["lens_id"]
        path = self.write_json("duplicate-lens.json", plan)
        _, stderr = self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path), expected=2)
        self.assertIn("unique", stderr)

    def test_coverage_plan_rejects_required_core_or_risk_lens_marked_optional(self) -> None:
        scope_hash = self.init()
        for lens_id in ("correctness", "reliability", "migration_data_safety"):
            plan = self.coverage_plan(scope_hash)
            next(item for item in plan["lenses"] if item["lens_id"] == lens_id)["required"] = False
            path = self.write_json(f"optional-{lens_id}.json", plan)
            _, stderr = self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path), expected=2)
            self.assertIn(f"requires {lens_id}", stderr)

    def test_coverage_plan_rejects_unsupported_review_mode(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan(scope_hash)
        plan["lenses"][0]["review_mode"] = "peer"
        path = self.write_json("unsupported-review-mode.json", plan)
        _, stderr = self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path), expected=2)
        self.assertIn("review_mode", stderr)

    def test_coverage_plan_rejects_stale_scope_hash(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan("0" * 64)
        self.assertNotEqual(plan["scope_hash"], scope_hash)
        path = self.write_json("stale-scope-hash.json", plan)
        _, stderr = self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path), expected=2)
        self.assertIn("scope hash", stderr)

    def test_coverage_plan_rejects_pre_contract_state(self) -> None:
        scope_hash = self.init()
        self.make_run_legacy()
        path = self.write_json("pre-contract-state.json", self.coverage_plan(scope_hash))
        _, stderr = self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path), expected=2)
        self.assertIn("Run predates required coverage", stderr)

    def test_legacy_context_run_cannot_record_coverage_or_ingest(self) -> None:
        scope_hash = self.init()
        self.make_run_legacy()
        plan = self.write_json("legacy-plan.json", self.coverage_plan(scope_hash))
        for command in (
            ("record-coverage", "--input", str(plan)),
            (
                "ingest-candidates",
                "--input",
                str(self.write_json("legacy-candidate.json", self.candidate_set(scope_hash))),
            ),
        ):
            _, stderr = self.run_tool(
                command[0],
                "--repo-root",
                str(self.repo),
                "--run-id",
                self.run_id,
                *command[1:],
                expected=2,
            )
            self.assertIn("Run predates required coverage; start a new run.", stderr)

    def test_legacy_adjudicated_run_cannot_advance_gate_a(self) -> None:
        self.reach_adjudicated()
        self.make_run_legacy()
        _, stderr = self.run_tool(
            "gate-findings",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--approve",
            "F001",
            "--user-statement",
            "Attempt legacy approval.",
            expected=2,
        )
        self.assertIn("Run predates required coverage; start a new run.", stderr)
        self.assertEqual(self.load("state.json")["phase"], "ADJUDICATED")

    def test_legacy_candidates_run_cannot_adjudicate_or_create_artifacts(self) -> None:
        scope_hash = self.init_with_recorded_coverage()
        paths = self.candidate_paths_for_coverage(scope_hash)
        self.ingest_candidate_paths(paths)
        candidate_hash = self.load("candidates.json")["candidate_bundle_hash"]
        adjudication_path = self.write_json(
            "legacy-adjudication.json", self.adjudication(scope_hash, candidate_hash)
        )
        self.make_run_legacy()
        before = self.load("state.json")
        self.assertEqual(before["phase"], reviewctl.PHASE_CANDIDATES)
        for artifact in ("adjudication.normalized.json", "adjudication.md", "ledger.json", "ledger.md"):
            self.assertFalse((self.run_dir / artifact).exists())

        _, stderr = self.run_tool(
            "compile-ledger",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(adjudication_path),
            expected=2,
        )

        self.assertIn("Run predates required coverage; start a new run.", stderr)
        after = self.load("state.json")
        self.assertEqual(after["phase"], before["phase"])
        self.assertEqual(after["hashes"], before["hashes"])
        self.assertEqual(after["events"], before["events"])
        for artifact in ("adjudication.normalized.json", "adjudication.md", "ledger.json", "ledger.md"):
            self.assertFalse((self.run_dir / artifact).exists())

    def test_legacy_plan_approved_run_cannot_begin_fix(self) -> None:
        self.reach_plan_approved()
        self.make_run_legacy()
        _, stderr = self.run_tool(
            "begin-fix", "--repo-root", str(self.repo), "--run-id", self.run_id, expected=2
        )
        self.assertIn("Run predates required coverage; start a new run.", stderr)
        self.assertFalse((self.run_dir / "checkpoints" / "pre-fix").exists())

    def test_legacy_fixing_run_can_abort_and_restore(self) -> None:
        self.reach_fixing()
        original = (self.repo / "calc.py").read_text(encoding="utf-8")
        (self.repo / "calc.py").write_text("def add(a, b):\n    return 999\n", encoding="utf-8")
        self.make_run_legacy()
        self.run_tool(
            "abort-fixes",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--reason",
            "Retire legacy run safely.",
        )
        self.assertEqual((self.repo / "calc.py").read_text(encoding="utf-8"), original)
        self.assertEqual(self.load("state.json")["phase"], "ABORTED")

    def test_legacy_run_preserves_allowed_observation_and_rollback_rules(self) -> None:
        self.init()
        self.make_run_legacy()
        _, stderr = self.run_tool(
            "status", "--repo-root", str(self.repo), "--run-id", self.run_id, "--json"
        )
        self.assertEqual(stderr, "")
        _, stderr = self.run_tool(
            "check-scope", "--repo-root", str(self.repo), "--run-id", self.run_id
        )
        self.assertEqual(stderr, "")
        _, stderr = self.run_tool(
            "rollback-finding",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--finding",
            "F001",
            "--reason",
            "No active finding exists.",
            expected=2,
        )
        self.assertIn("rollback-finding requires an active finding in FIXING phase", stderr)

    def test_legacy_active_fixing_run_can_rollback_and_restore(self) -> None:
        self.reach_fixing()
        self.run_tool(
            "start-finding",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--finding",
            "F001",
        )
        original = (self.repo / "calc.py").read_text(encoding="utf-8")
        (self.repo / "calc.py").write_text("def add(a, b):\n    return 999\n", encoding="utf-8")
        self.make_run_legacy()
        self.run_tool(
            "rollback-finding",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--finding",
            "F001",
            "--reason",
            "Retire the legacy active finding safely.",
        )
        self.assertEqual((self.repo / "calc.py").read_text(encoding="utf-8"), original)
        state = self.load("state.json")
        self.assertEqual(state["phase"], "FIXING")
        self.assertIsNone(state["active_finding"])

    def test_legacy_run_rejects_later_lifecycle_commands_before_mutation(self) -> None:
        scope_hash = self.init()
        self.make_run_legacy()
        state_path = self.run_dir / "state.json"
        initial_state = state_path.read_bytes()
        initial_source = (self.repo / "calc.py").read_bytes()
        plan = self.write_json("legacy-forward-plan.json", self.coverage_plan(scope_hash))
        for command in (
            ("compile-ledger", "--input", str(plan)),
            ("validate-plan", "--input", str(plan)),
            ("gate-plan", "--approve", "--user-statement", "Attempt legacy Gate B."),
            ("start-finding", "--finding", "F001"),
            ("run-test", "--finding", "F001", "--test", "unit-regression"),
            ("finish-finding", "--finding", "F001", "--status", "fixed", "--note", "Attempt legacy completion."),
            ("run-global-test", "--test", "global-regression"),
            ("prepare-verification",),
            ("record-verification", "--input", str(plan)),
            ("begin-repair",),
        ):
            _, stderr = self.run_tool(
                command[0],
                "--repo-root",
                str(self.repo),
                "--run-id",
                self.run_id,
                *command[1:],
                expected=2,
            )
            self.assertIn("Run predates required coverage; start a new run.", stderr)
            self.assertEqual(state_path.read_bytes(), initial_state)
            self.assertEqual((self.repo / "calc.py").read_bytes(), initial_source)


if __name__ == "__main__":
    unittest.main()
