from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reviewctl.py"
CONTROLLER_1_2_COMPAT = Path(__file__).resolve().parent / "fixtures" / "reviewctl_1_2_compat.py"
CONTROLLER_1_2_COMPAT_SHA256 = "67460c72d04a23758dc94d6d336a6c0884b8b5e3cf4dd4d1d8d544c153abdac2"
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
        state["schema_version"] = "material-review/state/v1"
        state.pop("coverage_required", None)
        state.pop("workflow_profile", None)
        (self.run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    def run_controller_1_2_compat(
        self, *, run_dir: Path, candidate_path: Path, sentinel_path: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CONTROLLER_1_2_COMPAT),
                "--run-dir",
                str(run_dir),
                "--input",
                str(candidate_path),
                "--sentinel",
                str(sentinel_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

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
                "source_lenses": ["correctness"],
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
                    "source_lenses": ["correctness"],
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
            "schema_version": "material-review/adjudication/v4",
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

    def reach_fixed_stale_final_state(
        self,
        *,
        test_command: str = "grep -Fq 'return a + b' calc.py",
    ) -> tuple[str, dict]:
        scope_hash, plan = self.approve_and_plan(test_command=test_command)
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
        (self.repo / "calc.py").write_text(
            "def add(a, b):\n    return a + b\n", encoding="utf-8"
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

        # Emulate a later approved finding changing the same Gate-B path after
        # this finding was retained. The later finding would update the
        # controller's expected aggregate guard without reopening F001.
        (self.repo / "calc.py").write_text(
            "def add(a, b):\n    return a + b\n# later shared repair\n",
            encoding="utf-8",
        )
        state = self.load("state.json")
        state["expected_workspace_guard_hash"] = reviewctl.workspace_guard(self.repo)[
            "guard_hash"
        ]
        (self.run_dir / "state.json").write_text(
            json.dumps(state, indent=2), encoding="utf-8"
        )
        _, stderr = self.run_tool(
            "prepare-verification",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            expected=2,
        )
        self.assertIn("F001:unit-regression stale for approved paths", stderr)
        return scope_hash, plan

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

    def test_fixed_finding_refreshes_stale_test_without_reopening_attempt(self) -> None:
        self.reach_fixed_stale_final_state()
        state_before = self.load("state.json")
        history_before = copy.deepcopy(state_before["finding_status"]["F001"]["history"])
        guard_before = reviewctl.workspace_guard(self.repo)

        self.run_tool(
            "refresh-finding-test",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--finding",
            "F001",
            "--test",
            "unit-regression",
        )

        state_after = self.load("state.json")
        status = state_after["finding_status"]["F001"]
        self.assertEqual(status["status"], "fixed")
        self.assertEqual(status["attempts"], state_before["finding_status"]["F001"]["attempts"])
        self.assertEqual(status["history"], history_before)
        self.assertIsNone(state_after["active_finding"])
        self.assertEqual(reviewctl.workspace_guard(self.repo), guard_before)
        result = state_after["finding_test_refresh_results"]["F001"]["unit-regression"][-1]
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["timed_out"])
        self.assertEqual(result["changed_paths_by_test"], [])
        self.assertEqual(result["control_mutations_by_test"], [])
        self.assertEqual(result["allowed_paths_hash"], reviewctl.path_subset_hash(self.repo, ["calc.py"]))
        self.assertEqual(
            result["fixed_attempt_hash"], history_before[-1]["attempt_hash"]
        )

        self.run_tool(
            "prepare-verification",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
        )
        self.assertEqual(self.load("state.json")["phase"], reviewctl.PHASE_VERIFYING)

    def test_fixed_finding_refresh_restores_and_rejects_test_mutation(self) -> None:
        mutation_command = (
            "if grep -Fq '# later shared repair' calc.py; then "
            "printf 'def add(a, b):\\n    return 999\\n' > calc.py; "
            "else grep -Fq 'return a + b' calc.py; fi"
        )
        self.reach_fixed_stale_final_state(test_command=mutation_command)
        final_source = (self.repo / "calc.py").read_bytes()
        state_before = self.load("state.json")
        history_before = copy.deepcopy(state_before["finding_status"]["F001"]["history"])

        _, stderr = self.run_tool(
            "refresh-finding-test",
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

        self.assertIn("Approved test mutated the workspace and was restored", stderr)
        self.assertEqual((self.repo / "calc.py").read_bytes(), final_source)
        state_after = self.load("state.json")
        self.assertEqual(state_after["finding_status"]["F001"]["history"], history_before)
        self.assertEqual(
            state_after["finding_status"]["F001"]["attempts"],
            state_before["finding_status"]["F001"]["attempts"],
        )
        result = state_after["finding_test_refresh_results"]["F001"]["unit-regression"][-1]
        self.assertTrue(result["restored_after_mutation"])
        self.assertEqual(result["changed_paths_by_test"], ["calc.py"])

    def test_marked_state_v1_run_can_refresh_and_complete_without_migration(self) -> None:
        scope_hash, plan = self.reach_fixed_stale_final_state()
        state_path = self.run_dir / "state.json"
        state = self.load("state.json")
        state["schema_version"] = "material-review/state/v1"
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

        self.run_tool(
            "refresh-finding-test",
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
            "prepare-verification",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
        )
        fix_summary = self.load("fix-summary.json")
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
                    "reason": "The final shared-file state retains the approved repair.",
                    "evidence_checked": ["calc.py:2 -- return a + b"],
                    "tests_checked": ["unit-regression"],
                }
            ],
            "regressions": [],
            "record_only_observations": [],
            "verdict": "pass",
            "summary": "The approved finding is resolved at the final shared-file state.",
            "limitations": [],
        }
        verification_path = self.write_json("state-v1-verification.json", verification)
        self.run_tool(
            "record-verification",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(verification_path),
        )

        completed = self.load("state.json")
        self.assertEqual(completed["schema_version"], "material-review/state/v1")
        self.assertEqual(completed["phase"], reviewctl.PHASE_COMPLETE)

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
            "schema_version": "material-review/adjudication/v4",
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

    def test_material_review_lens_provenance_is_deterministic(self) -> None:
        (self.repo / "test_calc.py").write_text(
            "from calc import add\nassert add(1, 2) == 3\n# ordering fixture\n",
            encoding="utf-8",
        )
        candidate_order_by_input_order: dict[
            str, list[tuple[str, str, int, str, str]]
        ] = {}
        retained_scope_hash = ""

        for order_name, reverse_inputs in (("forward", False), ("reverse", True)):
            self.run_id = f"lens-provenance-{order_name}"
            scope_hash = self.init()
            plan = self.coverage_plan(scope_hash)
            for assignment in plan["lenses"]:
                if assignment["lens_id"] in {"correctness", "test_adequacy"}:
                    assignment["reviewer_id"] = "shared-reviewer"
                    assignment["independence_group"] = "shared-model"
                    assignment["review_mode"] = "subagent"
            plan_path = self.write_json(f"coverage-{order_name}.json", plan)
            self.run_tool(
                "record-coverage",
                "--repo-root",
                str(self.repo),
                "--run-id",
                self.run_id,
                "--input",
                str(plan_path),
            )
            recorded_plan = self.load("coverage-plan.json")
            candidate_findings = self.candidate_set(scope_hash, include_style=True)["findings"]
            tied_finding = copy.deepcopy(candidate_findings[0])
            tied_finding["local_id"] = "m-tied"
            earlier_test_finding = copy.deepcopy(tied_finding)
            earlier_test_finding["local_id"] = "a-testing"
            later_correctness_finding = copy.deepcopy(tied_finding)
            later_correctness_finding["local_id"] = "z-correctness"
            earlier_file_test_finding = copy.deepcopy(tied_finding)
            earlier_file_test_finding["local_id"] = "n-file-order"
            later_file_correctness_finding = copy.deepcopy(tied_finding)
            later_file_correctness_finding.update(
                {
                    "local_id": "n-file-order",
                    "file": "test_calc.py",
                    "line_start": 1,
                    "line_end": 1,
                    "evidence_quote": "from calc import add",
                    "related_changed_files": ["test_calc.py"],
                }
            )
            earlier_line_test_finding = copy.deepcopy(tied_finding)
            earlier_line_test_finding.update(
                {
                    "local_id": "o-line-order",
                    "line_start": 1,
                    "line_end": 1,
                    "evidence_quote": "def add(a, b):",
                }
            )
            later_line_correctness_finding = copy.deepcopy(tied_finding)
            later_line_correctness_finding["local_id"] = "o-line-order"
            discarded_finding = candidate_findings[1]
            candidate_paths: list[Path] = []
            for assignment in recorded_plan["lenses"]:
                payload = self.empty_candidate_set_v2(
                    scope_hash,
                    recorded_plan["coverage_plan_hash"],
                    assignment,
                )
                if assignment["lens_id"] == "correctness":
                    payload["findings"] = [
                        copy.deepcopy(tied_finding),
                        copy.deepcopy(later_correctness_finding),
                        copy.deepcopy(later_file_correctness_finding),
                        copy.deepcopy(later_line_correctness_finding),
                    ]
                elif assignment["lens_id"] == "test_adequacy":
                    payload["findings"] = [
                        copy.deepcopy(tied_finding),
                        copy.deepcopy(earlier_test_finding),
                        copy.deepcopy(earlier_file_test_finding),
                        copy.deepcopy(earlier_line_test_finding),
                    ]
                elif assignment["lens_id"] == "standards_alignment":
                    payload["findings"] = [copy.deepcopy(discarded_finding)]
                candidate_paths.append(
                    self.write_json(
                        f"{order_name}-{assignment['lens_id']}.json",
                        payload,
                    )
                )
            if reverse_inputs:
                candidate_paths.reverse()

            self.ingest_candidate_paths(candidate_paths)

            bundle = self.load("candidates.json")
            self.assertEqual(
                bundle["schema_version"],
                "material-review/candidates-normalized/v2",
            )
            self.assertEqual(
                [candidate.get("lens_id") for candidate in bundle["candidates"]],
                [
                    "test_adequacy",
                    "correctness",
                    "test_adequacy",
                    "test_adequacy",
                    "correctness",
                    "test_adequacy",
                    "correctness",
                    "correctness",
                    "standards_alignment",
                ],
            )
            self.assertTrue(
                all("coverage_plan_hash" not in candidate for candidate in bundle["candidates"])
            )
            self.assertEqual(
                {reviewer_set["lens_id"] for reviewer_set in bundle["reviewer_sets"]},
                {assignment["lens_id"] for assignment in recorded_plan["lenses"]},
            )
            self.assertEqual(len(bundle["reviewer_sets"]), len(recorded_plan["lenses"]))
            rendered_candidates = (self.run_dir / "candidates.md").read_text(encoding="utf-8")
            self.assertIn("lens `correctness`", rendered_candidates)
            self.assertIn("lens `test_adequacy`", rendered_candidates)
            self.assertIn("lens `standards_alignment`", rendered_candidates)
            candidate_order_by_input_order[order_name] = [
                (
                    candidate["local_id"],
                    candidate["file"],
                    candidate["line_start"],
                    candidate["lens_id"],
                    candidate["candidate_id"],
                )
                for candidate in bundle["candidates"]
            ]
            retained_scope_hash = scope_hash

        self.assertEqual(
            candidate_order_by_input_order,
            {
                "forward": [
                    ("a-testing", "calc.py", 2, "test_adequacy", "C001"),
                    ("m-tied", "calc.py", 2, "correctness", "C002"),
                    ("m-tied", "calc.py", 2, "test_adequacy", "C003"),
                    ("n-file-order", "calc.py", 2, "test_adequacy", "C004"),
                    ("n-file-order", "test_calc.py", 1, "correctness", "C005"),
                    ("o-line-order", "calc.py", 1, "test_adequacy", "C006"),
                    ("o-line-order", "calc.py", 2, "correctness", "C007"),
                    ("z-correctness", "calc.py", 2, "correctness", "C008"),
                    ("b-rename", "calc.py", 1, "standards_alignment", "C009"),
                ],
                "reverse": [
                    ("a-testing", "calc.py", 2, "test_adequacy", "C001"),
                    ("m-tied", "calc.py", 2, "correctness", "C002"),
                    ("m-tied", "calc.py", 2, "test_adequacy", "C003"),
                    ("n-file-order", "calc.py", 2, "test_adequacy", "C004"),
                    ("n-file-order", "test_calc.py", 1, "correctness", "C005"),
                    ("o-line-order", "calc.py", 1, "test_adequacy", "C006"),
                    ("o-line-order", "calc.py", 2, "correctness", "C007"),
                    ("z-correctness", "calc.py", 2, "correctness", "C008"),
                    ("b-rename", "calc.py", 1, "standards_alignment", "C009"),
                ],
            },
        )

        bundle_path = self.run_dir / "candidates.json"
        state_path = self.run_dir / "state.json"
        original_bundle = self.load("candidates.json")
        original_bundle_bytes = bundle_path.read_bytes()
        original_state_bytes = state_path.read_bytes()

        def persisted_run_bytes() -> dict[str, bytes]:
            return {
                path.relative_to(self.run_dir).as_posix(): path.read_bytes()
                for path in self.run_dir.rglob("*")
                if path.is_file()
            }

        base_adjudication = self.adjudication(
            retained_scope_hash,
            original_bundle["candidate_bundle_hash"],
            include_style=True,
        )
        group = base_adjudication["groups"][0]
        group["candidate_ids"] = [
            "C001",
            "C002",
            "C003",
            "C004",
            "C005",
            "C006",
            "C007",
            "C008",
        ]
        group["source_reviewers"] = ["shared-reviewer"]
        group["source_independence_groups"] = ["shared-model"]
        group["source_lenses"] = ["correctness", "test_adequacy"]
        group["repair_audit"]["candidate_ids"] = [
            "C001",
            "C002",
            "C003",
            "C004",
            "C005",
            "C006",
            "C007",
            "C008",
        ]
        discarded_group = base_adjudication["groups"][1]
        discarded_group["candidate_ids"] = ["C009"]
        discarded_group["source_reviewers"] = ["standards_alignment"]
        discarded_group["source_lenses"] = ["standards_alignment"]

        for name, mutate in (
            (
                "old-normalized-version",
                lambda payload: payload.update(
                    {"schema_version": "material-review/candidates-normalized/v1"}
                ),
            ),
            (
                "lensless-normalized-candidate",
                lambda payload: payload["candidates"][0].pop("lens_id"),
            ),
        ):
            with self.subTest(current_candidate_artifact=name):
                mutated_bundle = copy.deepcopy(original_bundle)
                mutate(mutated_bundle)
                mutated_bundle.pop("candidate_bundle_hash")
                mutated_bundle.pop("generated_at")
                mutated_hash = reviewctl.canonical_hash(mutated_bundle)
                mutated_bundle["candidate_bundle_hash"] = mutated_hash
                mutated_bundle["generated_at"] = original_bundle["generated_at"]
                bundle_path.write_text(json.dumps(mutated_bundle), encoding="utf-8")
                state = json.loads(original_state_bytes)
                state["hashes"]["candidate_bundle_hash"] = mutated_hash
                state_path.write_text(json.dumps(state), encoding="utf-8")
                expected_events = copy.deepcopy(state["events"])
                mutated_authority = persisted_run_bytes()

                _, retry_stderr = self.ingest_candidate_paths(
                    candidate_paths,
                    expected=2,
                )
                expected_cause = (
                    "normalized candidates schema_version does not match the active "
                    "workflow profile: expected material-review/candidates-normalized/v2, "
                    "got material-review/candidates-normalized/v1"
                    if name == "old-normalized-version"
                    else "normalized candidates.candidates[0].lens_id must be a string"
                )
                self.assertEqual(
                    retry_stderr,
                    "[FAIL] Existing normalized candidate authority is incompatible with "
                    "the active workflow profile; start a new run. Cause: "
                    f"{expected_cause}\n",
                )
                self.assertEqual(persisted_run_bytes(), mutated_authority)
                self.assertEqual(self.load("state.json")["events"], expected_events)

                adjudication = copy.deepcopy(base_adjudication)
                adjudication["candidate_bundle_hash"] = mutated_hash
                adjudication_path = self.write_json(
                    f"{name}-adjudication.json", adjudication
                )

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

                self.assertEqual(stderr, f"[FAIL] {expected_cause}\n")
                self.assertFalse((self.run_dir / "ledger.json").exists())
                self.assertEqual(persisted_run_bytes(), mutated_authority)
                self.assertEqual(self.load("state.json")["events"], expected_events)
                bundle_path.write_bytes(original_bundle_bytes)
                state_path.write_bytes(original_state_bytes)

        invalid_adjudications: list[tuple[str, dict]] = []
        for name in ("omitted", "extra", "wrong", "duplicate", "unsorted"):
            invalid = copy.deepcopy(base_adjudication)
            if name == "omitted":
                invalid["groups"][0].pop("source_lenses")
            elif name == "extra":
                invalid["groups"][0]["source_lenses"] = [
                    "correctness",
                    "security",
                    "test_adequacy",
                ]
            elif name == "wrong":
                invalid["groups"][0]["source_lenses"] = ["correctness"]
            elif name == "duplicate":
                invalid["groups"][0]["source_lenses"] = [
                    "correctness",
                    "correctness",
                ]
            else:
                invalid["groups"][0]["source_lenses"] = [
                    "test_adequacy",
                    "correctness",
                ]
            invalid_adjudications.append((name, invalid))
        old_adjudication = copy.deepcopy(base_adjudication)
        old_adjudication["schema_version"] = "material-review/adjudication/v3"
        invalid_adjudications.append(("old-version", old_adjudication))

        for name, adjudication in invalid_adjudications:
            with self.subTest(adjudication=name):
                adjudication_path = self.write_json(
                    f"invalid-source-lenses-{name}.json", adjudication
                )
                unchanged_authority = persisted_run_bytes()
                unchanged_events = copy.deepcopy(self.load("state.json")["events"])
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
                expected_error = {
                    "omitted": (
                        "adjudication.groups[0] has invalid fields: missing source_lenses"
                    ),
                    "extra": (
                        "adjudication.groups[0].source_lenses must be the exact sorted "
                        "candidate-source lenses"
                    ),
                    "wrong": (
                        "adjudication.groups[0].source_lenses must be the exact sorted "
                        "candidate-source lenses"
                    ),
                    "duplicate": (
                        "adjudication.groups[0].source_lenses must contain unique values"
                    ),
                    "unsorted": (
                        "adjudication.groups[0].source_lenses must be the exact sorted "
                        "candidate-source lenses"
                    ),
                    "old-version": (
                        "Adjudication schema_version does not match the active workflow "
                        "profile: expected material-review/adjudication/v4, got "
                        "material-review/adjudication/v3"
                    ),
                }[name]
                self.assertEqual(stderr, f"[FAIL] {expected_error}\n")
                self.assertFalse((self.run_dir / "ledger.json").exists())
                self.assertEqual(persisted_run_bytes(), unchanged_authority)
                self.assertEqual(self.load("state.json")["events"], unchanged_events)

        valid_adjudication_path = self.write_json(
            "valid-lens-adjudication.json", base_adjudication
        )
        self.run_tool(
            "compile-ledger",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(valid_adjudication_path),
        )
        normalized_adjudication = self.load("adjudication.normalized.json")
        ledger = self.load("ledger.json")
        self.assertEqual(
            normalized_adjudication["schema_version"],
            "material-review/adjudication/v4",
        )
        self.assertEqual(
            normalized_adjudication["groups"][0]["source_lenses"],
            ["correctness", "test_adequacy"],
        )
        self.assertEqual(ledger["schema_version"], "material-review/ledger/v4")
        self.assertEqual(
            ledger["findings"][0]["source_lenses"],
            ["correctness", "test_adequacy"],
        )
        self.assertEqual(
            ledger["discarded"][0]["source_lenses"],
            ["standards_alignment"],
        )
        rendered_ledger = (self.run_dir / "ledger.md").read_text(encoding="utf-8")
        self.assertIn("Source lenses: correctness, test_adequacy", rendered_ledger)
        self.assertIn("lenses standards_alignment", rendered_ledger)

        normalized_adjudication_path = self.run_dir / "adjudication.normalized.json"
        original_adjudication_bytes = normalized_adjudication_path.read_bytes()
        for name, mutate, expected_cause in (
            (
                "old-persisted-adjudication-version",
                lambda payload: payload.update(
                    {"schema_version": "material-review/adjudication/v3"}
                ),
                "Adjudication schema_version does not match the active workflow profile: "
                "expected material-review/adjudication/v4, got material-review/adjudication/v3",
            ),
            (
                "lensless-persisted-adjudication",
                lambda payload: payload["groups"][0].pop("source_lenses"),
                "adjudication.groups[0] has invalid fields: missing source_lenses",
            ),
        ):
            with self.subTest(existing_adjudication_authority=name):
                mutated_adjudication = copy.deepcopy(normalized_adjudication)
                mutate(mutated_adjudication)
                normalized_adjudication_path.write_text(
                    json.dumps(mutated_adjudication), encoding="utf-8"
                )
                mutated_authority = persisted_run_bytes()
                expected_events = copy.deepcopy(self.load("state.json")["events"])

                _, stderr = self.run_tool(
                    "compile-ledger",
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    "--input",
                    str(valid_adjudication_path),
                    expected=2,
                )

                self.assertEqual(
                    stderr,
                    "[FAIL] Existing normalized adjudication or ledger authority is "
                    "incompatible with the active workflow profile; start a new run. "
                    f"Cause: {expected_cause}\n",
                )
                self.assertEqual(persisted_run_bytes(), mutated_authority)
                self.assertEqual(self.load("state.json")["events"], expected_events)
                normalized_adjudication_path.write_bytes(original_adjudication_bytes)

        ledger_path = self.run_dir / "ledger.json"
        original_ledger = self.load("ledger.json")
        original_ledger_bytes = ledger_path.read_bytes()
        adjudicated_state_bytes = state_path.read_bytes()
        for name, mutate in (
            (
                "old-ledger-version",
                lambda payload: payload.update({"schema_version": "material-review/ledger/v3"}),
            ),
            (
                "lensless-ledger",
                lambda payload: payload["findings"][0].pop("source_lenses"),
            ),
            (
                "lensless-discarded-ledger",
                lambda payload: payload["discarded"][0].pop("source_lenses"),
            ),
        ):
            with self.subTest(current_ledger_artifact=name):
                mutated_ledger = copy.deepcopy(original_ledger)
                mutate(mutated_ledger)
                mutated_ledger.pop("ledger_hash")
                mutated_ledger.pop("generated_at")
                mutated_hash = reviewctl.canonical_hash(mutated_ledger)
                mutated_ledger["ledger_hash"] = mutated_hash
                mutated_ledger["generated_at"] = original_ledger["generated_at"]
                ledger_path.write_text(json.dumps(mutated_ledger), encoding="utf-8")
                state = json.loads(adjudicated_state_bytes)
                state["hashes"]["ledger_hash"] = mutated_hash
                state_path.write_text(json.dumps(state), encoding="utf-8")
                mutated_authority = persisted_run_bytes()
                expected_events = copy.deepcopy(state["events"])
                expected_cause = {
                    "old-ledger-version": (
                        "ledger schema_version does not match the active workflow profile: "
                        "expected material-review/ledger/v4, got material-review/ledger/v3"
                    ),
                    "lensless-ledger": (
                        "ledger provenance entry[0].source_lenses must be an array"
                    ),
                    "lensless-discarded-ledger": (
                        "ledger provenance entry[1].source_lenses must be an array"
                    ),
                }[name]

                _, recompile_stderr = self.run_tool(
                    "compile-ledger",
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    "--input",
                    str(valid_adjudication_path),
                    expected=2,
                )
                self.assertEqual(
                    recompile_stderr,
                    "[FAIL] Existing normalized adjudication or ledger authority is "
                    "incompatible with the active workflow profile; start a new run. "
                    f"Cause: {expected_cause}\n",
                )
                self.assertEqual(persisted_run_bytes(), mutated_authority)
                self.assertEqual(self.load("state.json")["events"], expected_events)

                _, stderr = self.run_tool(
                    "gate-findings",
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    "--approve",
                    "F001",
                    "--user-statement",
                    "Reject incompatible current artifacts.",
                    expected=2,
                )

                self.assertEqual(stderr, f"[FAIL] {expected_cause}\n")
                self.assertFalse((self.run_dir / "gates" / "findings.json").exists())
                self.assertEqual(persisted_run_bytes(), mutated_authority)
                self.assertEqual(self.load("state.json")["events"], expected_events)
                ledger_path.write_bytes(original_ledger_bytes)
                state_path.write_bytes(adjudicated_state_bytes)

        legacy_state = json.loads(adjudicated_state_bytes)
        legacy_state["schema_version"] = "material-review/state/v1"
        legacy_state.pop("coverage_required")
        legacy_state.pop("workflow_profile")
        state_path.write_text(json.dumps(legacy_state), encoding="utf-8")
        legacy_state_bytes = state_path.read_bytes()
        _, stderr = self.run_tool(
            "gate-findings",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--approve",
            "F001",
            "--user-statement",
            "A legacy run must remain restart-only.",
            expected=2,
        )
        self.assertIn("Run predates required coverage; start a new run.", stderr)
        self.assertEqual(state_path.read_bytes(), legacy_state_bytes)
        self.assertEqual(ledger_path.read_bytes(), original_ledger_bytes)
        self.assertFalse((self.run_dir / "gates" / "findings.json").exists())

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

    def test_coverage_plan_schema_requires_each_risk_code_exactly_once(self) -> None:
        schema_path = Path(__file__).resolve().parents[1] / "schemas" / "coverage-plan.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        risk_assessments = schema["properties"]["risk_assessments"]
        item_schema = risk_assessments["items"]

        self.assertEqual(risk_assessments["minItems"], 2)
        self.assertEqual(risk_assessments["maxItems"], 2)
        self.assertEqual(risk_assessments["items"], item_schema)
        self.assertEqual(
            item_schema["required"],
            ["code", "present", "rationale", "evidence_paths"],
        )
        self.assertFalse(item_schema["additionalProperties"])
        self.assertEqual(
            item_schema["properties"],
            {
                "code": {
                    "enum": [
                        "user_selectable_output_paths",
                        "persisted_config_semantics",
                    ]
                },
                "present": {"type": "boolean"},
                "rationale": {"type": "string", "minLength": 1},
                "evidence_paths": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": {"$ref": "#/$defs/canonical_repository_relative_git_path"},
                },
            },
        )
        self.assertIn("allOf", risk_assessments)
        cardinality_constraints = risk_assessments["allOf"]
        self.assertEqual(len(cardinality_constraints), 2)
        self.assertEqual(
            {
                constraint["contains"]["properties"]["code"]["const"]: (
                    constraint["minContains"],
                    constraint["maxContains"],
                )
                for constraint in cardinality_constraints
            },
            {
                "user_selectable_output_paths": (1, 1),
                "persisted_config_semantics": (1, 1),
            },
        )
        self.assertEqual(
            item_schema["allOf"],
            [
                {
                    "if": {"properties": {"present": {"const": True}}},
                    "then": {"properties": {"evidence_paths": {"minItems": 1}}},
                    "else": {"properties": {"evidence_paths": {"maxItems": 0}}},
                }
            ],
        )

        def satisfies_literal_contract(assessments: list[dict]) -> bool:
            expected_codes = {
                "user_selectable_output_paths",
                "persisted_config_semantics",
            }
            expected_keys = {"code", "present", "rationale", "evidence_paths"}
            if len(assessments) != 2:
                return False
            if {assessment.get("code") for assessment in assessments} != expected_codes:
                return False
            for assessment in assessments:
                if set(assessment) != expected_keys:
                    return False
                if not isinstance(assessment["present"], bool):
                    return False
                if not isinstance(assessment["rationale"], str) or not assessment["rationale"]:
                    return False
                evidence_paths = assessment["evidence_paths"]
                if not isinstance(evidence_paths, list) or len(evidence_paths) != len(set(evidence_paths)):
                    return False
                try:
                    for path in evidence_paths:
                        reviewctl.require_canonical_repo_path(path, "coverage plan evidence path")
                except reviewctl.ReviewError:
                    return False
                if assessment["present"] and not evidence_paths:
                    return False
                if not assessment["present"] and evidence_paths:
                    return False
            return True

        assessments = self.coverage_plan("0" * 64)["risk_assessments"]
        reversed_assessments = list(reversed(copy.deepcopy(assessments)))
        duplicate_output_paths = copy.deepcopy(assessments)
        duplicate_output_paths[1] = {
            "code": "user_selectable_output_paths",
            "present": False,
            "rationale": "Output paths are unavailable in this alternative assessment.",
            "evidence_paths": [],
        }
        duplicate_persisted_config = copy.deepcopy(assessments)
        duplicate_persisted_config[0] = {
            "code": "persisted_config_semantics",
            "present": False,
            "rationale": "Persisted configuration is unavailable in this alternative assessment.",
            "evidence_paths": [],
        }

        self.assertTrue(satisfies_literal_contract(assessments))
        self.assertTrue(satisfies_literal_contract(reversed_assessments))
        self.assertFalse(satisfies_literal_contract(duplicate_output_paths))
        self.assertFalse(satisfies_literal_contract(duplicate_persisted_config))

        invalid_contract_fixtures = (
            ("wrong-count", assessments[:1]),
            ("extra-key", [{**assessments[0], "extra": True}, assessments[1]]),
            ("non-boolean-present", [{**assessments[0], "present": "true"}, assessments[1]]),
            ("empty-rationale", [{**assessments[0], "rationale": ""}, assessments[1]]),
            ("duplicate-evidence-path", [{**assessments[0], "evidence_paths": ["calc.py", "calc.py"]}, assessments[1]]),
            ("unsafe-evidence-path", [{**assessments[0], "evidence_paths": ["./calc.py"]}, assessments[1]]),
            ("present-without-evidence", [{**assessments[0], "evidence_paths": []}, assessments[1]]),
            ("absent-with-evidence", [{**assessments[0], "present": False}, assessments[1]]),
        )
        for name, invalid_assessments in invalid_contract_fixtures:
            with self.subTest(contract="invalid", fixture=name):
                self.assertFalse(satisfies_literal_contract(invalid_assessments))

        for output_paths_present, persisted_config_present in (
            (True, True),
            (True, False),
            (False, True),
            (False, False),
        ):
            with self.subTest(
                output_paths_present=output_paths_present,
                persisted_config_present=persisted_config_present,
            ):
                conditional_assessments = self.coverage_plan(
                    "0" * 64,
                    output_paths_present=output_paths_present,
                    persisted_config_present=persisted_config_present,
                )["risk_assessments"]
                self.assertTrue(satisfies_literal_contract(conditional_assessments))

        scope_hash = self.init()
        state = self.load("state.json")
        for valid_assessments in (assessments, reversed_assessments):
            controller_plan = self.coverage_plan(scope_hash)
            controller_plan["risk_assessments"] = copy.deepcopy(valid_assessments)
            controller_plan["scope_hash"] = scope_hash
            with self.subTest(controller="valid", codes=[item["code"] for item in valid_assessments]):
                validated = reviewctl.validate_coverage_plan(
                    controller_plan,
                    run_dir=self.run_dir,
                    state=state,
                )
                self.assertEqual(validated["risk_assessments"], valid_assessments)

        for duplicate_assessments, missing_code in (
            (duplicate_output_paths, "persisted_config_semantics"),
            (duplicate_persisted_config, "user_selectable_output_paths"),
        ):
            controller_plan = self.coverage_plan(scope_hash)
            controller_plan["risk_assessments"] = copy.deepcopy(duplicate_assessments)
            controller_plan["scope_hash"] = scope_hash
            with self.subTest(controller="duplicate", missing_code=missing_code):
                with self.assertRaises(reviewctl.ReviewError) as raised:
                    reviewctl.validate_coverage_plan(
                        controller_plan,
                        run_dir=self.run_dir,
                        state=state,
                    )
                self.assertIn("assessment codes", str(raised.exception))

        out_of_scope_plan = self.coverage_plan(scope_hash)
        out_of_scope_plan["risk_assessments"][0]["evidence_paths"] = ["outside.py"]
        with self.assertRaises(reviewctl.ReviewError) as raised:
            reviewctl.validate_coverage_plan(out_of_scope_plan, run_dir=self.run_dir, state=state)
        self.assertIn("paths not in the frozen scope", str(raised.exception))

    def test_material_review_v2_paths_require_canonical_git_spelling(self) -> None:
        schema_root = Path(__file__).resolve().parents[1] / "schemas"
        candidate_schema = json.loads(
            (schema_root / "candidate-set-v2.schema.json").read_text(encoding="utf-8")
        )
        coverage_schema = json.loads(
            (schema_root / "coverage-plan.schema.json").read_text(encoding="utf-8")
        )
        definition_name = "canonical_repository_relative_git_path"
        self.assertIn("$defs", candidate_schema)
        self.assertIn("$defs", coverage_schema)
        candidate_definition = candidate_schema["$defs"][definition_name]
        coverage_definition = coverage_schema["$defs"][definition_name]
        self.assertEqual(candidate_definition, coverage_definition)
        reference = {"$ref": f"#/$defs/{definition_name}"}
        finding_properties = candidate_schema["properties"]["findings"]["items"]["properties"]
        self.assertEqual(finding_properties["file"], reference)
        self.assertEqual(finding_properties["related_changed_files"]["items"], reference)
        self.assertEqual(
            candidate_schema["properties"]["coverage"]["properties"]["files_reviewed"]["items"],
            reference,
        )
        self.assertEqual(
            coverage_schema["properties"]["risk_assessments"]["items"]["properties"]
            ["evidence_paths"]["items"],
            reference,
        )

        def collect_references(value: object) -> list[str]:
            if isinstance(value, dict):
                references = [value["$ref"]] if "$ref" in value else []
                for nested in value.values():
                    references.extend(collect_references(nested))
                return references
            if isinstance(value, list):
                references: list[str] = []
                for nested in value:
                    references.extend(collect_references(nested))
                return references
            return []

        expected_reference = f"#/$defs/{definition_name}"
        self.assertEqual(collect_references(candidate_schema), [expected_reference] * 3)
        self.assertEqual(collect_references(coverage_schema), [expected_reference])

        boundary_class = (
            r"[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680"
            r"\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]"
        )
        expected_pattern = (
            r"^(?![A-Za-z]:)(?!/)(?![^\u0000]*\\)(?![^\u0000]*//)"
            r"(?![^\u0000]*/$)(?!\.git(?:/|$))(?!\.{1,2}(?:/|$))"
            r"(?![^\u0000]*/\.{1,2}(?:/|$))"
            + f"(?!{boundary_class})"
            + r"(?![^\u0000]*"
            + boundary_class
            + r"$)"
            + r"(?![^\u0000]*\u0000)[^\u0000]+$"
        )
        required_boundary_fragments = (
            r"\u0009-\u000d",
            r"\u001c-\u0020",
            r"\u0085",
            r"\u00a0",
            r"\u1680",
            r"\u2000-\u200a",
            r"\u2028",
            r"\u2029",
            r"\u202f",
            r"\u205f",
            r"\u3000",
            r"\ufeff",
        )
        boundary_code_points = (
            *range(0x0009, 0x000E),
            *range(0x001C, 0x0021),
            0x0085,
            0x00A0,
            0x1680,
            *range(0x2000, 0x200B),
            0x2028,
            0x2029,
            0x202F,
            0x205F,
            0x3000,
            0xFEFF,
        )
        for code_point in boundary_code_points:
            character = chr(code_point)
            internal_path = f"directory/a{character}b.py"
            with self.subTest(unicode_boundary="internal", code_point=f"U+{code_point:04X}"):
                self.assertEqual(
                    reviewctl.require_canonical_repo_path(internal_path, "path field"),
                    internal_path,
                )
            for path in (f"{character}calc.py", f"calc.py{character}"):
                with self.subTest(
                    unicode_boundary="external",
                    code_point=f"U+{code_point:04X}",
                    path=ascii(path),
                ):
                    with self.assertRaises(reviewctl.ReviewError) as raised:
                        reviewctl.require_canonical_repo_path(path, "path field")
                    self.assertIn(
                        "canonical repository-relative forward-slash Git path",
                        str(raised.exception),
                    )
        for fragment in required_boundary_fragments:
            with self.subTest(schema_boundary_fragment=fragment):
                self.assertIn(fragment, candidate_definition["pattern"])
        self.assertNotIn(r"\s", candidate_definition["pattern"])
        self.assertEqual(candidate_definition["pattern"], expected_pattern)

        canonical_paths = (
            "directory with space/name.py",
            "src/name.with.dots.py",
            ".config/tool.py",
            "src/name:with-colon.py",
        )
        unsafe_paths = {
            "backslash": "src\\module.py",
            "leading-dot-slash": "./calc.py",
            "surrounding-whitespace": " calc.py ",
            "absolute": "/calc.py",
            "unc": "//server/share.py",
            "drive-rooted": "C:/calc.py",
            "drive-relative": "C:calc.py",
            "repeated-separator": "src//calc.py",
            "dot-component": "src/./calc.py",
            "parent-component": "src/../calc.py",
            "git-rooted": ".git/config",
            "trailing-separator": "src/",
            "empty": "",
            "nul": "calc.py\0",
        }
        for path in canonical_paths:
            with self.subTest(runtime="positive", path=path):
                self.assertEqual(
                    reviewctl.require_canonical_repo_path(path, "path field"),
                    path,
                )
        field_contexts = (
            "coverage plan.risk_assessments[0].evidence_paths[0]",
            "candidate.json.findings[0].file",
            "candidate.json.findings[0].related_changed_files[0]",
            "candidate.json.coverage.files_reviewed[0]",
        )
        for label, path in unsafe_paths.items():
            for context in field_contexts:
                with self.subTest(runtime="negative", case=label, field=context):
                    with self.assertRaises(reviewctl.ReviewError) as raised:
                        reviewctl.require_canonical_repo_path(path, context)
                    self.assertIn(context, str(raised.exception))
                    self.assertIn("canonical repository-relative forward-slash Git path", str(raised.exception))
        with self.assertRaises(reviewctl.ReviewError) as raised:
            reviewctl.require_canonical_repo_path(7, "candidate.json.findings[0].file")
        self.assertIn("candidate.json.findings[0].file must be a string", str(raised.exception))

        for path in canonical_paths:
            target = self.repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("VALUE = 1\n", encoding="utf-8")
            self.git("add", "--", path)
        self.git("commit", "-qm", "add canonical path fixtures")
        for path in canonical_paths:
            (self.repo / path).write_text("VALUE = 2\n", encoding="utf-8")

        scope_hash = self.init()
        state = self.load("state.json")
        for path in canonical_paths:
            plan = self.coverage_plan(scope_hash)
            plan["risk_assessments"][0]["evidence_paths"] = [path]
            validated = reviewctl.validate_coverage_plan(plan, run_dir=self.run_dir, state=state)
            self.assertEqual(validated["risk_assessments"][0]["evidence_paths"], [path])
        for label, path in unsafe_paths.items():
            plan = self.coverage_plan(scope_hash)
            plan["risk_assessments"][0]["evidence_paths"] = [path]
            with self.subTest(field="coverage evidence", case=label):
                with self.assertRaises(reviewctl.ReviewError) as raised:
                    reviewctl.validate_coverage_plan(plan, run_dir=self.run_dir, state=state)
                self.assertIn("coverage plan.risk_assessments[0].evidence_paths[0]", str(raised.exception))
                self.assertIn("canonical repository-relative forward-slash Git path", str(raised.exception))

        out_of_scope_plan = self.coverage_plan(scope_hash)
        out_of_scope_plan["risk_assessments"][0]["evidence_paths"] = ["outside.py"]
        with self.assertRaises(reviewctl.ReviewError) as raised:
            reviewctl.validate_coverage_plan(out_of_scope_plan, run_dir=self.run_dir, state=state)
        self.assertIn("paths not in the frozen scope", str(raised.exception))
        self.assertNotIn("canonical repository-relative", str(raised.exception))

        invalid_scope_and_path_plan = self.coverage_plan("0" * 64)
        invalid_scope_and_path_plan["risk_assessments"][0]["evidence_paths"] = ["./calc.py"]
        with self.assertRaises(reviewctl.ReviewError) as raised:
            reviewctl.validate_coverage_plan(
                invalid_scope_and_path_plan,
                run_dir=self.run_dir,
                state=state,
            )
        self.assertIn("coverage plan.risk_assessments[0].evidence_paths[0]", str(raised.exception))
        self.assertIn("canonical repository-relative forward-slash Git path", str(raised.exception))
        canonical_path_invalid_scope_plan = self.coverage_plan("0" * 64)
        with self.assertRaises(reviewctl.ReviewError) as raised:
            reviewctl.validate_coverage_plan(
                canonical_path_invalid_scope_plan,
                run_dir=self.run_dir,
                state=state,
            )
        self.assertIn("scope hash does not match", str(raised.exception))
        self.assertNotIn("canonical repository-relative", str(raised.exception))

        coverage_state_before = self.load("state.json")
        invalid_plan = self.coverage_plan(scope_hash)
        invalid_plan["risk_assessments"][0]["evidence_paths"] = ["./calc.py"]
        invalid_plan_path = self.write_json("invalid-canonical-coverage.json", invalid_plan)
        _, stderr = self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(invalid_plan_path),
            expected=2,
        )
        self.assertIn("coverage plan.risk_assessments[0].evidence_paths[0]", stderr)
        self.assertIn("canonical repository-relative forward-slash Git path", stderr)
        self.assertEqual(self.load("state.json"), coverage_state_before)
        self.assertFalse((self.run_dir / "coverage-plan.json").exists())
        self.assertNotIn("coverage_plan_hash", self.load("state.json")["hashes"])

        valid_plan_path = self.write_json("canonical-coverage.json", self.coverage_plan(scope_hash))
        self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(valid_plan_path),
        )
        state = self.load("state.json")
        recorded_plan = self.load("coverage-plan.json")
        assignment = next(item for item in recorded_plan["lenses"] if item["lens_id"] == "correctness")

        def candidate_payload() -> dict:
            payload = self.candidate_set(scope_hash, include_style=False)
            payload.update(
                {
                    "schema_version": "material-review/candidate-set/v2",
                    "coverage_plan_hash": recorded_plan["coverage_plan_hash"],
                    "lens_id": assignment["lens_id"],
                    "reviewer_id": assignment["reviewer_id"],
                    "independence_group": assignment["independence_group"],
                    "review_mode": assignment["review_mode"],
                }
            )
            return payload

        for path in canonical_paths:
            payload = candidate_payload()
            payload["findings"][0].update(
                {
                    "file": path,
                    "line_start": 1,
                    "line_end": 1,
                    "evidence_quote": "VALUE = 2",
                    "related_changed_files": [path],
                }
            )
            payload["coverage"]["files_reviewed"] = [path]
            normalized, _ = reviewctl.validate_candidate_set(
                payload,
                source_file=Path("canonical-candidate.json"),
                repo=self.repo,
                run_dir=self.run_dir,
                state=state,
            )
            self.assertEqual(normalized["coverage"]["files_reviewed"], [path])
            self.assertEqual(normalized["findings"][0]["file"], path)
            self.assertEqual(normalized["findings"][0]["related_changed_files"], [path])

        candidate_fields = {
            "findings[0].file": lambda payload, path: payload["findings"][0].__setitem__("file", path),
            "findings[0].related_changed_files[0]": lambda payload, path: payload["findings"][0].__setitem__(
                "related_changed_files", [path]
            ),
            "coverage.files_reviewed[0]": lambda payload, path: payload["coverage"].__setitem__(
                "files_reviewed", [path]
            ),
        }
        for field, mutate in candidate_fields.items():
            payload = candidate_payload()
            payload["coverage_plan_hash"] = "0" * 64
            mutate(payload, "./calc.py")
            with self.subTest(field=field, authority="invalid-path-first"):
                with self.assertRaises(reviewctl.ReviewError) as raised:
                    reviewctl.validate_candidate_set(
                        payload,
                        source_file=Path("candidate.json"),
                        repo=self.repo,
                        run_dir=self.run_dir,
                        state=state,
                    )
                self.assertIn(field, str(raised.exception))
                self.assertIn(
                    "canonical repository-relative forward-slash Git path",
                    str(raised.exception),
                )
        canonical_path_invalid_authority = candidate_payload()
        canonical_path_invalid_authority["coverage_plan_hash"] = "0" * 64
        with self.assertRaises(reviewctl.ReviewError) as raised:
            reviewctl.validate_candidate_set(
                canonical_path_invalid_authority,
                source_file=Path("candidate.json"),
                repo=self.repo,
                run_dir=self.run_dir,
                state=state,
            )
        self.assertIn("coverage_plan_hash does not match", str(raised.exception))
        self.assertNotIn("canonical repository-relative", str(raised.exception))

        for field, mutate in candidate_fields.items():
            for label, path in unsafe_paths.items():
                payload = candidate_payload()
                mutate(payload, path)
                with self.subTest(field=field, case=label):
                    with self.assertRaises(reviewctl.ReviewError) as raised:
                        reviewctl.validate_candidate_set(
                            payload,
                            source_file=Path("candidate.json"),
                            repo=self.repo,
                            run_dir=self.run_dir,
                            state=state,
                        )
                    self.assertIn(field, str(raised.exception))
                    self.assertIn(
                        "canonical repository-relative forward-slash Git path",
                        str(raised.exception),
                    )

        candidate_state_before = self.load("state.json")
        atomic_cases = {
            "findings[0].file": " calc.py ",
            "findings[0].related_changed_files[0]": "calc\\py",
            "coverage.files_reviewed[0]": "calc.py/",
        }
        for field, path in atomic_cases.items():
            paths = self.candidate_paths_for_coverage(scope_hash)
            candidate_path = next(
                item
                for item in paths
                if json.loads(item.read_text(encoding="utf-8"))["findings"]
            )
            payload = json.loads(candidate_path.read_text(encoding="utf-8"))
            candidate_fields[field](payload, path)
            candidate_path.write_text(json.dumps(payload), encoding="utf-8")
            _, stderr = self.ingest_candidate_paths(paths, expected=2)
            self.assertIn(field, stderr)
            self.assertIn("canonical repository-relative forward-slash Git path", stderr)
            self.assertEqual(self.load("state.json"), candidate_state_before)
            self.assertFalse((self.run_dir / "candidates.json").exists())
            self.assertNotIn("candidate_bundle_hash", self.load("state.json")["hashes"])
            self.assertTrue((self.run_dir / "candidate-ingestion-failure.json").exists())

        out_of_scope_paths = self.candidate_paths_for_coverage(scope_hash)
        out_of_scope_payload = json.loads(out_of_scope_paths[0].read_text(encoding="utf-8"))
        out_of_scope_payload["coverage"]["files_reviewed"] = ["outside.py"]
        out_of_scope_paths[0].write_text(json.dumps(out_of_scope_payload), encoding="utf-8")
        _, stderr = self.ingest_candidate_paths(out_of_scope_paths, expected=2)
        self.assertIn("coverage.files_reviewed contains a path outside the frozen scope", stderr)
        self.assertNotIn("canonical repository-relative", stderr)
        self.assertEqual(self.load("state.json"), candidate_state_before)

        bad_evidence_paths = self.candidate_paths_for_coverage(scope_hash)
        bad_evidence_candidate = next(
            item
            for item in bad_evidence_paths
            if json.loads(item.read_text(encoding="utf-8"))["findings"]
        )
        bad_evidence_payload = json.loads(bad_evidence_candidate.read_text(encoding="utf-8"))
        bad_evidence_payload["findings"][0]["evidence_quote"] = "not present in the frozen source"
        bad_evidence_candidate.write_text(json.dumps(bad_evidence_payload), encoding="utf-8")
        _, stderr = self.ingest_candidate_paths(bad_evidence_paths, expected=2)
        self.assertIn("Evidence quote was not found", stderr)
        self.assertNotIn("canonical repository-relative", stderr)
        self.assertEqual(self.load("state.json"), candidate_state_before)

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

    def test_conditional_risk_lenses_cover_four_state_matrix(self) -> None:
        output_path = "generated_output.py"
        config_path = "persisted_config.py"
        optional_lens = "supplementary_observability"

        # These untracked files become distinct, real paths in each frozen scope.
        (self.repo / output_path).write_text("OUTPUT_ROOT = 'reports'\n", encoding="utf-8")
        (self.repo / config_path).write_text("DEFAULT_FORMAT = 'json'\n", encoding="utf-8")

        def prepare_run(
            name: str, *, output_present: bool, config_present: bool
        ) -> tuple[str, dict]:
            self.run_id = f"test-run-risk-matrix-{name}"
            scope_hash = self.init()
            plan = self.coverage_plan(
                scope_hash,
                output_paths_present=output_present,
                persisted_config_present=config_present,
            )
            plan["risk_assessments"][0]["evidence_paths"] = [output_path] if output_present else []
            plan["risk_assessments"][1]["evidence_paths"] = [config_path] if config_present else []
            required = {"correctness", "test_adequacy", "standards_alignment"}
            if output_present:
                required.add("reliability")
            if config_present:
                required.update({"migration_data_safety", "api_config_compatibility"})
            plan["lenses"] = [
                assignment for assignment in plan["lenses"] if assignment["lens_id"] in required
            ]
            plan["lenses"].append(
                {
                    "lens_id": optional_lens,
                    "required": False,
                    "reviewer_id": optional_lens,
                    "independence_group": "model-a",
                    "review_mode": "subagent",
                }
            )
            plan_path = self.write_json(f"risk-matrix-{name}-plan.json", plan)
            self.run_tool(
                "record-coverage",
                "--repo-root",
                str(self.repo),
                "--run-id",
                self.run_id,
                "--input",
                str(plan_path),
            )
            return scope_hash, plan

        def candidate_paths(
            name: str, scope_hash: str, plan: dict, *, omit_lens: str | None = None,
            reviewed_paths: dict[str, list[str]] | None = None,
        ) -> list[Path]:
            coverage_hash = self.load("coverage-plan.json")["coverage_plan_hash"]
            paths: list[Path] = []
            for assignment in plan["lenses"]:
                lens_id = assignment["lens_id"]
                if lens_id == omit_lens:
                    continue
                payload = self.empty_candidate_set_v2(scope_hash, coverage_hash, assignment)
                payload["coverage"]["files_reviewed"] = (reviewed_paths or {}).get(
                    lens_id, ["calc.py"]
                )
                paths.append(self.write_json(f"risk-matrix-{name}-{lens_id}.json", payload))
            return paths

        def assert_non_authoritative_failure(state_before: dict) -> None:
            self.assertEqual(self.load("state.json"), state_before)
            self.assertEqual(self.load("state.json")["phase"], "CONTEXT_FROZEN")
            self.assertNotIn("candidate_bundle_hash", self.load("state.json")["hashes"])
            for artifact in ("candidates.json", "candidate-rejections.json", "candidates.md"):
                self.assertFalse((self.run_dir / artifact).exists(), artifact)
            diagnostic = self.load("candidate-ingestion-failure.json")
            self.assertNotIn("candidate_bundle_hash", diagnostic)
            self.assertNotIn("candidates", diagnostic)

        matrix = (
            (
                "neither",
                False,
                False,
                {"correctness", "test_adequacy", "standards_alignment"},
            ),
            (
                "output-only",
                True,
                False,
                {"correctness", "test_adequacy", "standards_alignment", "reliability"},
            ),
            (
                "config-only",
                False,
                True,
                {
                    "correctness",
                    "test_adequacy",
                    "standards_alignment",
                    "migration_data_safety",
                    "api_config_compatibility",
                },
            ),
            (
                "both",
                True,
                True,
                {
                    "correctness",
                    "test_adequacy",
                    "standards_alignment",
                    "reliability",
                    "migration_data_safety",
                    "api_config_compatibility",
                },
            ),
        )
        for name, output_present, config_present, minimum_required in matrix:
            with self.subTest(state=name, result="complete-wave"):
                scope_hash, plan = prepare_run(
                    name, output_present=output_present, config_present=config_present
                )
                recorded = self.load("coverage-plan.json")
                assessments = {item["code"]: item for item in recorded["risk_assessments"]}
                self.assertEqual(set(assessments), {
                    "user_selectable_output_paths", "persisted_config_semantics"
                })
                self.assertEqual(
                    assessments["user_selectable_output_paths"]["evidence_paths"],
                    [output_path] if output_present else [],
                )
                self.assertEqual(
                    assessments["persisted_config_semantics"]["evidence_paths"],
                    [config_path] if config_present else [],
                )
                self.assertEqual(
                    {item["lens_id"] for item in recorded["lenses"] if item["required"]},
                    minimum_required,
                )
                self.assertIn(optional_lens, {item["lens_id"] for item in recorded["lenses"]})
                self.assertFalse(
                    next(item for item in recorded["lenses"] if item["lens_id"] == optional_lens)["required"]
                )

                reviewed_paths = {
                    "reliability": [output_path],
                    "migration_data_safety": [config_path],
                    "api_config_compatibility": [config_path],
                }
                paths = candidate_paths(name, scope_hash, plan, reviewed_paths=reviewed_paths)
                self.ingest_candidate_paths(paths)
                state = self.load("state.json")
                self.assertEqual(state["phase"], "CANDIDATES_CAPTURED")
                candidates = self.load("candidates.json")
                self.assertEqual(candidates["coverage_plan_hash"], recorded["coverage_plan_hash"])
                self.assertEqual(
                    {item["lens_id"] for item in candidates["reviewer_sets"]},
                    {item["lens_id"] for item in recorded["lenses"]},
                )
                for assignment in recorded["lenses"]:
                    reviewer_set = next(
                        item for item in candidates["reviewer_sets"]
                        if item["lens_id"] == assignment["lens_id"]
                    )
                    self.assertEqual(
                        (reviewer_set["reviewer_id"], reviewer_set["independence_group"], reviewer_set["review_mode"]),
                        (assignment["reviewer_id"], assignment["independence_group"], assignment["review_mode"]),
                    )

        for lens_id in ("correctness", "test_adequacy", "standards_alignment"):
            with self.subTest(lens=lens_id, control="missing-unconditional-core-lens"):
                name = f"{lens_id}-missing-core-lens"
                scope_hash, plan = prepare_run(
                    name, output_present=False, config_present=False
                )
                state_before = self.load("state.json")
                _, stderr = self.ingest_candidate_paths(
                    candidate_paths(name, scope_hash, plan, omit_lens=lens_id),
                    expected=2,
                )
                self.assertEqual(stderr, f"[FAIL] Missing required review coverage: {lens_id}\n")
                assert_non_authoritative_failure(state_before)

        specialists = (
            ("reliability", output_path, config_path),
            ("migration_data_safety", config_path, output_path),
            ("api_config_compatibility", config_path, output_path),
        )
        for lens_id, own_path, other_path in specialists:
            for control, omitted_lens, lens_paths, expected_cause in (
                (
                    "missing-lens",
                    lens_id,
                    None,
                    f"Missing required review coverage: {lens_id}",
                ),
                (
                    "missing-own-risk-path",
                    None,
                    {lens_id: ["calc.py"]},
                    f"{lens_id} did not review required risk paths: {own_path}",
                ),
                (
                    "substituted-other-risk-path",
                    None,
                    {lens_id: [other_path]},
                    f"{lens_id} did not review required risk paths: {own_path}",
                ),
            ):
                with self.subTest(lens=lens_id, control=control):
                    name = f"{lens_id}-{control}"
                    scope_hash, plan = prepare_run(name, output_present=True, config_present=True)
                    reviewed_paths = {
                        "reliability": [output_path],
                        "migration_data_safety": [config_path],
                        "api_config_compatibility": [config_path],
                    }
                    if lens_paths:
                        reviewed_paths.update(lens_paths)
                    state_before = self.load("state.json")
                    _, stderr = self.ingest_candidate_paths(
                        candidate_paths(
                            name,
                            scope_hash,
                            plan,
                            omit_lens=omitted_lens,
                            reviewed_paths=reviewed_paths,
                        ),
                        expected=2,
                    )
                    self.assertEqual(stderr, f"[FAIL] {expected_cause}\n")
                    assert_non_authoritative_failure(state_before)

    def test_required_core_lenses_cannot_have_empty_file_assignments(self) -> None:
        core_lens_ids = {"correctness", "test_adequacy", "standards_alignment"}
        coverage_cases = (
            ("correctness", False),
            ("test_adequacy", False),
            ("standards_alignment", False),
            ("migration_data_safety", True),
        )
        for empty_lens_id, conditional_risk_present in coverage_cases:
            with self.subTest(empty_lens_id=empty_lens_id):
                self.run_id = f"test-run-empty-{empty_lens_id}"
                scope_hash = self.init()
                plan = self.coverage_plan(
                    scope_hash,
                    output_paths_present=conditional_risk_present,
                    persisted_config_present=conditional_risk_present,
                )
                if not conditional_risk_present:
                    plan["lenses"] = [
                        assignment
                        for assignment in plan["lenses"]
                        if assignment["lens_id"] in core_lens_ids
                    ]
                plan_path = self.write_json(
                    f"coverage-input-{empty_lens_id}.json",
                    plan,
                )
                self.run_tool(
                    "record-coverage",
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    "--input",
                    str(plan_path),
                )
                coverage_hash = self.load("coverage-plan.json")["coverage_plan_hash"]
                paths = []
                for assignment in plan["lenses"]:
                    payload = self.empty_candidate_set_v2(
                        scope_hash,
                        coverage_hash,
                        assignment,
                    )
                    paths.append(
                        self.write_json(
                            f"candidate-{empty_lens_id}-{assignment['lens_id']}.json",
                            payload,
                        )
                    )

                self.ingest_candidate_paths(paths)
                candidates_before = (self.run_dir / "candidates.json").read_bytes()
                state_before = self.load("state.json")
                self.assertEqual(self.load("candidates.json")["candidates"], [])

                empty_path = next(
                    path
                    for path in paths
                    if path.name == f"candidate-{empty_lens_id}-{empty_lens_id}.json"
                )
                payload = json.loads(empty_path.read_text(encoding="utf-8"))
                payload["coverage"]["files_reviewed"] = []
                empty_path.write_text(json.dumps(payload), encoding="utf-8")

                _, stderr = self.ingest_candidate_paths(paths, expected=2)

                self.assertIn(
                    f"{empty_path.name}.coverage.files_reviewed must name at least one "
                    "frozen-scope path",
                    stderr,
                )
                self.assertEqual(
                    (self.run_dir / "candidates.json").read_bytes(),
                    candidates_before,
                )
                self.assertEqual(self.load("state.json"), state_before)
                self.assertTrue(
                    (self.run_dir / "candidate-ingestion-failure.json").exists()
                )

        self.run_id = "test-run-out-of-scope"
        scope_hash = self.init_with_recorded_coverage()
        out_of_scope_paths = self.candidate_paths_for_coverage(scope_hash)
        payload = json.loads(out_of_scope_paths[0].read_text(encoding="utf-8"))
        payload["coverage"]["files_reviewed"] = ["outside.py"]
        out_of_scope_paths[0].write_text(json.dumps(payload), encoding="utf-8")
        _, stderr = self.ingest_candidate_paths(out_of_scope_paths, expected=2)
        self.assertIn(
            "coverage.files_reviewed contains a path outside the frozen scope",
            stderr,
        )

        self.run_id = "test-run-risk-path"
        scope_hash = self.init_with_recorded_coverage()
        risk_paths = self.candidate_paths_for_coverage(scope_hash)
        migration = next(path for path in risk_paths if "migration_data_safety" in path.name)
        payload = json.loads(migration.read_text(encoding="utf-8"))
        payload["coverage"]["files_reviewed"] = ["test_calc.py"]
        migration.write_text(json.dumps(payload), encoding="utf-8")
        _, stderr = self.ingest_candidate_paths(risk_paths, expected=2)
        self.assertIn("did not review required risk paths: calc.py", stderr)

        schema_path = Path(__file__).resolve().parents[1] / "schemas" / "candidate-set-v2.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["coverage"]["properties"]["files_reviewed"]["minItems"], 1)
        self.assertNotIn("minItems", schema["properties"]["findings"])

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

    def test_candidate_set_v2_binding_fields_are_strict_and_atomic(self) -> None:
        """Reject incomplete or malformed review bindings before authority capture."""
        authoritative_artifacts = (
            "candidates.json",
            "candidate-rejections.json",
            "candidates.md",
        )

        self.run_id = "test-run-v2-binding-complete"
        scope_hash = self.init_with_recorded_coverage()
        complete_paths = self.candidate_paths_for_coverage(scope_hash)
        recorded_coverage_hash = self.load("coverage-plan.json")["coverage_plan_hash"]
        self.ingest_candidate_paths(complete_paths)
        complete_state = self.load("state.json")
        complete_candidates = self.load("candidates.json")
        self.assertEqual(complete_state["phase"], "CANDIDATES_CAPTURED")
        self.assertEqual(complete_state["hashes"]["coverage_plan_hash"], recorded_coverage_hash)
        self.assertEqual(complete_candidates["coverage_plan_hash"], recorded_coverage_hash)

        def assert_rejected_binding(
            name: str, mutate, expected_error: str
        ) -> None:
            self.run_id = f"test-run-v2-binding-{name}"
            bound_scope_hash = self.init_with_recorded_coverage()
            paths = self.candidate_paths_for_coverage(bound_scope_hash)
            candidate_path = next(path for path in paths if "correctness" in path.name)
            payload = json.loads(candidate_path.read_text(encoding="utf-8"))
            mutate(payload)
            candidate_path.write_text(json.dumps(payload), encoding="utf-8")
            state_before = (self.run_dir / "state.json").read_bytes()

            _, stderr = self.ingest_candidate_paths(paths, expected=2)

            self.assertEqual(
                stderr,
                "[FAIL] Candidate ingestion failed: "
                + expected_error.format(source=candidate_path.resolve())
                + "\n",
            )
            self.assertEqual((self.run_dir / "state.json").read_bytes(), state_before)
            for artifact in authoritative_artifacts:
                self.assertFalse((self.run_dir / artifact).exists(), artifact)

        for field, expected_error in (
            ("schema_version", "{source}.schema_version must be a string"),
            ("coverage_plan_hash", "candidate set {source} has invalid fields: missing coverage_plan_hash"),
            ("lens_id", "candidate set {source} has invalid fields: missing lens_id"),
            ("reviewer_id", "candidate set {source} has invalid fields: missing reviewer_id"),
            ("independence_group", "candidate set {source} has invalid fields: missing independence_group"),
            ("review_mode", "candidate set {source} has invalid fields: missing review_mode"),
        ):
            with self.subTest(binding="missing", field=field):
                assert_rejected_binding(
                    f"missing-{field}",
                    lambda payload, field=field: payload.pop(field),
                    expected_error,
                )

        for name, mutate, expected_error in (
            (
                "schema-version-wrong-type",
                lambda payload: payload.update({"schema_version": 2}),
                "{source}.schema_version must be a string",
            ),
            (
                "schema-version-invalid",
                lambda payload: payload.update({"schema_version": "material-review/candidate-set/v1"}),
                "{source}: unsupported schema_version",
            ),
            (
                "coverage-hash-wrong-type",
                lambda payload: payload.update({"coverage_plan_hash": 2}),
                "{source}.coverage_plan_hash must be a string",
            ),
            (
                "coverage-hash-invalid-pattern",
                lambda payload: payload.update({"coverage_plan_hash": "A" * 64}),
                "{source}.coverage_plan_hash must be a lowercase SHA-256 digest",
            ),
            (
                "lens-wrong-type",
                lambda payload: payload.update({"lens_id": 2}),
                "{source}.lens_id must be a string",
            ),
            (
                "lens-invalid-pattern",
                lambda payload: payload.update({"lens_id": "invalid-lens"}),
                "{source}.lens_id has an invalid format",
            ),
            (
                "reviewer-wrong-type",
                lambda payload: payload.update({"reviewer_id": 2}),
                "{source}.reviewer_id must be a string",
            ),
            (
                "reviewer-empty",
                lambda payload: payload.update({"reviewer_id": ""}),
                "{source}.reviewer_id must not be empty",
            ),
            (
                "independence-wrong-type",
                lambda payload: payload.update({"independence_group": 2}),
                "{source}.independence_group must be a string",
            ),
            (
                "independence-empty",
                lambda payload: payload.update({"independence_group": ""}),
                "{source}.independence_group must not be empty",
            ),
            (
                "review-mode-wrong-type",
                lambda payload: payload.update({"review_mode": 2}),
                "{source}.review_mode must be a string",
            ),
            (
                "review-mode-unsupported",
                lambda payload: payload.update({"review_mode": "unsupported"}),
                "{source}.review_mode must be one of ['controller', 'external', 'subagent']",
            ),
        ):
            with self.subTest(binding="malformed", case=name):
                assert_rejected_binding(name, mutate, expected_error)

        schema_path = (
            Path(__file__).resolve().parents[1]
            / "schemas"
            / "candidate-set-v2.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(
            schema["required"],
            [
                "schema_version",
                "scope_hash",
                "coverage_plan_hash",
                "lens_id",
                "reviewer_id",
                "independence_group",
                "review_mode",
                "findings",
                "coverage",
            ],
        )
        self.assertEqual(
            reviewctl.CANDIDATE_SCHEMA_REVIEW,
            "material-review/candidate-set/v2",
        )
        self.assertEqual(
            schema["properties"]["schema_version"]["const"],
            "material-review/candidate-set/v2",
        )
        self.assertEqual(
            schema["properties"]["coverage_plan_hash"],
            {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        )
        self.assertEqual(
            schema["properties"]["lens_id"],
            {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
        )
        self.assertEqual(
            schema["properties"]["reviewer_id"],
            {"type": "string", "minLength": 1},
        )
        self.assertEqual(
            schema["properties"]["independence_group"],
            {"type": "string", "minLength": 1},
        )
        self.assertEqual(
            schema["properties"]["review_mode"]["enum"],
            ["subagent", "controller", "external"],
        )
        self.assertEqual(
            reviewctl.REVIEW_MODES,
            {"subagent", "controller", "external"},
        )

    def test_candidate_ingestion_is_write_once_and_idempotent(self) -> None:
        authoritative_names = (
            "candidates.json",
            "candidate-rejections.json",
            "candidates.md",
            "state.json",
        )

        def authority_bytes() -> dict[str, bytes]:
            return {
                name: (self.run_dir / name).read_bytes()
                for name in authoritative_names
                if (self.run_dir / name).exists()
            }

        def renamed_reordered_inputs(paths: list[Path], prefix: str) -> list[Path]:
            renamed: list[Path] = []
            for index, path in enumerate(reversed(paths)):
                renamed.append(
                    self.write_json(
                        f"{prefix}-{index}.json",
                        json.loads(path.read_text(encoding="utf-8")),
                    )
                )
            return renamed

        scope_hash = self.init_with_recorded_coverage()
        primary = self.candidate_set(scope_hash, include_style=False)
        complete = self.candidate_paths_for_coverage(
            scope_hash,
            primary_candidate=primary,
        )

        incomplete = [path for path in complete if "reliability" not in path.name]
        self.ingest_candidate_paths(incomplete, expected=2)
        self.assertEqual(self.load("state.json")["phase"], "CONTEXT_FROZEN")
        self.assertFalse((self.run_dir / "candidates.json").exists())

        invalid = renamed_reordered_inputs(complete, "pre-authority-invalid")
        invalid_correctness = next(
            path
            for path in invalid
            if json.loads(path.read_text(encoding="utf-8"))["lens_id"] == "correctness"
        )
        invalid_payload = json.loads(invalid_correctness.read_text(encoding="utf-8"))
        invalid_payload["findings"][0]["line_start"] = 0
        invalid_correctness.write_text(json.dumps(invalid_payload), encoding="utf-8")
        self.ingest_candidate_paths(invalid, expected=2)
        self.assertEqual(self.load("state.json")["phase"], "CONTEXT_FROZEN")
        self.assertFalse((self.run_dir / "candidates.json").exists())

        missing = self.out / "pre-authority-unavailable.json"
        self.ingest_candidate_paths([*complete, missing], expected=2)
        self.assertEqual(self.load("state.json")["phase"], "CONTEXT_FROZEN")
        self.assertFalse((self.run_dir / "candidates.json").exists())

        self.ingest_candidate_paths(complete)
        captured_bundle = self.load("candidates.json")
        captured_state = self.load("state.json")
        captured_authority = authority_bytes()
        captured_ids = [candidate["candidate_id"] for candidate in captured_bundle["candidates"]]
        captured_lenses = [candidate["lens_id"] for candidate in captured_bundle["candidates"]]
        self.assertEqual(captured_ids, ["C001"])
        self.assertEqual(captured_lenses, ["correctness"])

        exact_retry = renamed_reordered_inputs(complete, "exact-retry")
        self.ingest_candidate_paths(exact_retry)
        self.assertEqual(authority_bytes(), captured_authority)
        self.assertEqual(self.load("state.json"), captured_state)
        self.assertEqual(
            self.load("candidates.json")["candidate_bundle_hash"],
            captured_bundle["candidate_bundle_hash"],
        )
        self.assertEqual(
            [candidate["candidate_id"] for candidate in self.load("candidates.json")["candidates"]],
            captured_ids,
        )

        changed_wave = renamed_reordered_inputs(complete, "changed-wave")
        original_correctness = next(
            json.loads(path.read_text(encoding="utf-8"))
            for path in complete
            if json.loads(path.read_text(encoding="utf-8"))["lens_id"] == "correctness"
        )
        changed_correctness_path = next(
            path
            for path in changed_wave
            if json.loads(path.read_text(encoding="utf-8"))["lens_id"] == "correctness"
        )
        changed_correctness = json.loads(
            changed_correctness_path.read_text(encoding="utf-8")
        )
        changed_correctness["findings"][0]["observable_consequence"] = (
            "The same operation now has a substantively different claimed consequence."
        )
        for field in (
            "lens_id",
            "reviewer_id",
            "independence_group",
            "review_mode",
        ):
            self.assertEqual(changed_correctness[field], original_correctness[field])
        self.assertEqual(
            len(changed_correctness["findings"]),
            len(original_correctness["findings"]),
        )
        self.assertEqual(
            changed_correctness["findings"][0]["local_id"],
            original_correctness["findings"][0]["local_id"],
        )
        changed_correctness_path.write_text(
            json.dumps(changed_correctness), encoding="utf-8"
        )
        _, stderr = self.ingest_candidate_paths(changed_wave, expected=2)
        self.assertIn("candidate bundle is already captured", stderr.lower())
        self.assertIn("start a new run", stderr.lower())
        self.assertEqual(authority_bytes(), captured_authority)

        retry_cases: list[tuple[str, list[Path], str]] = []
        retry_cases.append(
            (
                "incomplete",
                [path for path in exact_retry if "reliability" not in json.loads(path.read_text(encoding="utf-8"))["lens_id"]],
                "Missing required review coverage",
            )
        )
        invalid_retry = renamed_reordered_inputs(complete, "post-authority-invalid")
        invalid_retry_correctness = next(
            path
            for path in invalid_retry
            if json.loads(path.read_text(encoding="utf-8"))["lens_id"] == "correctness"
        )
        invalid_retry_payload = json.loads(
            invalid_retry_correctness.read_text(encoding="utf-8")
        )
        invalid_retry_payload["findings"][0]["line_start"] = 0
        invalid_retry_correctness.write_text(
            json.dumps(invalid_retry_payload), encoding="utf-8"
        )
        retry_cases.append(("invalid", invalid_retry, "line_start must be >= 1"))
        retry_cases.append(
            (
                "unavailable",
                [*exact_retry, self.out / "post-authority-unavailable.json"],
                "Expected artifact file is missing",
            )
        )
        for name, retry_paths, expected_error in retry_cases:
            with self.subTest(non_authoritative_retry=name):
                _, stderr = self.ingest_candidate_paths(retry_paths, expected=2)
                self.assertIn(expected_error, stderr)
                self.assertEqual(authority_bytes(), captured_authority)
                self.assertEqual(self.load("state.json"), captured_state)
                failure = self.load("candidate-ingestion-failure.json")
                self.assertTrue(failure["rejections"])

        for name in (
            "missing-bundle",
            "tampered-payload",
            "tampered-embedded-hash",
            "state-hash-mismatch",
        ):
            with self.subTest(existing_authority=name):
                self.run_id = f"test-run-{name}"
                authority_scope_hash = self.init_with_recorded_coverage()
                authority_inputs = self.candidate_paths_for_coverage(
                    authority_scope_hash,
                    primary_candidate=self.candidate_set(
                        authority_scope_hash,
                        include_style=False,
                    ),
                )
                self.ingest_candidate_paths(authority_inputs)
                bundle_path = self.run_dir / "candidates.json"
                state_path = self.run_dir / "state.json"
                if name == "missing-bundle":
                    bundle_path.unlink()
                elif name == "tampered-payload":
                    bundle = self.load("candidates.json")
                    bundle["candidates"][0]["title"] = "Tampered authority"
                    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
                elif name == "tampered-embedded-hash":
                    bundle = self.load("candidates.json")
                    bundle["candidate_bundle_hash"] = "0" * 64
                    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
                else:
                    state = self.load("state.json")
                    state["hashes"]["candidate_bundle_hash"] = "0" * 64
                    state_path.write_text(json.dumps(state), encoding="utf-8")
                corrupted_authority = authority_bytes()

                _, stderr = self.ingest_candidate_paths(
                    renamed_reordered_inputs(authority_inputs, f"{name}-retry"),
                    expected=2,
                )

                self.assertIn("existing normalized candidate authority", stderr.lower())
                self.assertIn("start a new run", stderr.lower())
                self.assertEqual(authority_bytes(), corrupted_authority)
                if name == "missing-bundle":
                    self.assertFalse(bundle_path.exists())

        self.run_id = "test-run-later-phase"
        later_scope_hash = self.init_with_recorded_coverage()
        later_inputs = self.candidate_paths_for_coverage(
            later_scope_hash,
            primary_candidate=self.candidate_set(
                later_scope_hash,
                include_style=False,
            ),
        )
        self.ingest_candidate_paths(later_inputs)
        later_bundle = self.load("candidates.json")
        adjudication_path = self.write_json(
            "later-phase-adjudication.json",
            self.adjudication(
                later_scope_hash,
                later_bundle["candidate_bundle_hash"],
                include_style=False,
            ),
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
        later_authority = authority_bytes()
        _, stderr = self.ingest_candidate_paths(later_inputs, expected=2)
        self.assertIn("Cannot ingest candidates in phase ADJUDICATED", stderr)
        self.assertEqual(authority_bytes(), later_authority)

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

    def test_controller_state_compatibility_matrix(self) -> None:
        self.assertEqual(
            hashlib.sha256(CONTROLLER_1_2_COMPAT.read_bytes()).hexdigest(),
            CONTROLLER_1_2_COMPAT_SHA256,
        )

        scope_hash = self.init()
        initial_state = self.load("state.json")
        state_before_downgrade = (self.run_dir / "state.json").read_bytes()
        v1_candidate = self.write_json(
            "controller-1.2-candidate-v1.json", self.candidate_set(scope_hash)
        )

        v1_control_dir = self.root / "controller-1.2-v1-control"
        shutil.copytree(self.run_dir, v1_control_dir)
        v1_control_state = json.loads(
            (v1_control_dir / "state.json").read_text(encoding="utf-8")
        )
        v1_control_state["schema_version"] = "material-review/state/v1"
        (v1_control_dir / "state.json").write_text(
            json.dumps(v1_control_state, indent=2), encoding="utf-8"
        )
        v1_control_before = (v1_control_dir / "state.json").read_bytes()
        v1_control_sentinel = self.root / "controller-1.2-v1-control.sentinel"
        accepted = self.run_controller_1_2_compat(
            run_dir=v1_control_dir,
            candidate_path=v1_candidate,
            sentinel_path=v1_control_sentinel,
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertTrue(v1_control_sentinel.exists())
        self.assertTrue((v1_control_dir / "candidates.json").exists())
        self.assertNotEqual((v1_control_dir / "state.json").read_bytes(), v1_control_before)

        downgrade_sentinel = self.root / "controller-1.2-v2.sentinel"
        rejected = self.run_controller_1_2_compat(
            run_dir=self.run_dir,
            candidate_path=v1_candidate,
            sentinel_path=downgrade_sentinel,
        )
        self.assertEqual(rejected.returncode, 2, rejected.stderr)
        self.assertIn("Unsupported state schema", rejected.stderr)
        self.assertFalse(downgrade_sentinel.exists())
        self.assertFalse((self.run_dir / "candidates.json").exists())
        self.assertEqual((self.run_dir / "state.json").read_bytes(), state_before_downgrade)
        self.assertEqual(initial_state["schema_version"], "material-review/state/v2")
        self.assertIs(initial_state["coverage_required"], True)
        self.assertEqual(initial_state["workflow_profile"], "material_review")

        coverage_path = self.write_json("post-downgrade-coverage.json", self.coverage_plan(scope_hash))
        self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(coverage_path),
        )
        self.ingest_candidate_paths(self.candidate_paths_for_coverage(scope_hash))
        self.assertEqual(self.load("state.json")["phase"], reviewctl.PHASE_CANDIDATES)

        for marked in (True, False):
            with self.subTest(legacy_review_markers=marked):
                self.run_id = f"legacy-{'marked' if marked else 'unmarked'}"
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
                original_source = (self.repo / "calc.py").read_bytes()
                (self.repo / "calc.py").write_text(
                    "def add(a, b):\n    return 999\n", encoding="utf-8"
                )
                legacy_state = self.load("state.json")
                legacy_state["schema_version"] = "material-review/state/v1"
                if not marked:
                    legacy_state.pop("coverage_required", None)
                    legacy_state.pop("workflow_profile", None)
                state_path = self.run_dir / "state.json"
                state_path.write_text(json.dumps(legacy_state, indent=2), encoding="utf-8")

                self.run_tool(
                    "status",
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    "--json",
                )
                _, stderr = self.run_tool(
                    "check-scope",
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    expected=2,
                )
                self.assertIn(
                    "Original scope freshness is not used after begin-fix", stderr
                )
                state_before_forward = state_path.read_bytes()
                source_before_forward = (self.repo / "calc.py").read_bytes()
                _, stderr = self.run_tool(
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
                    "A legacy run must not advance.",
                    expected=2,
                )
                self.assertIn("Run predates required coverage; start a new run.", stderr)
                self.assertEqual(state_path.read_bytes(), state_before_forward)
                self.assertEqual((self.repo / "calc.py").read_bytes(), source_before_forward)

                self.run_tool(
                    "rollback-finding",
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    "--finding",
                    "F001",
                    "--reason",
                    "Restore a legacy active finding.",
                )
                self.assertEqual((self.repo / "calc.py").read_bytes(), original_source)
                state_after_rollback = state_path.read_bytes()
                self.assertIn(b'"schema_version": "material-review/state/v1"', state_after_rollback)
                self.assertEqual(self.load("state.json")["schema_version"], "material-review/state/v1")

                (self.repo / "calc.py").write_text(
                    "def add(a, b):\n    return 888\n", encoding="utf-8"
                )
                self.run_tool(
                    "abort-fixes",
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    "--reason",
                    "Restore the complete legacy repair layer.",
                )
                self.assertEqual((self.repo / "calc.py").read_bytes(), original_source)
                state_after_abort = state_path.read_bytes()
                self.assertIn(b'"schema_version": "material-review/state/v1"', state_after_abort)
                self.assertEqual(self.load("state.json")["schema_version"], "material-review/state/v1")
                self.assertEqual(self.load("state.json")["phase"], reviewctl.PHASE_ABORTED)

        invalid_state_mutations = (
            (
                "v2-simplification-profile",
                lambda state: state.update({"profile": "material-code-simplification"}),
            ),
            ("v2-null-profile", lambda state: state.update({"profile": None})),
            ("v2-missing-coverage-marker", lambda state: state.pop("coverage_required")),
            ("v2-missing-review-profile", lambda state: state.pop("workflow_profile")),
            (
                "v1-contradictory-simplification",
                lambda state: state.update(
                    {
                        "schema_version": "material-review/state/v1",
                        "profile": "material-code-simplification",
                    }
                ),
            ),
            (
                "unknown-state-schema",
                lambda state: state.update(
                    {"schema_version": "material-review/state/v999"}
                ),
            ),
        )
        for name, mutate in invalid_state_mutations:
            with self.subTest(invalid_state=name):
                self.run_id = f"invalid-{name}"
                self.init()
                state_path = self.run_dir / "state.json"
                invalid_state = self.load("state.json")
                mutate(invalid_state)
                state_path.write_text(json.dumps(invalid_state, indent=2), encoding="utf-8")
                state_before = state_path.read_bytes()
                source_before = (self.repo / "calc.py").read_bytes()
                _, stderr = self.run_tool(
                    "status",
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    "--json",
                    expected=2,
                )
                self.assertIn("Unsupported or contradictory state identity", stderr)
                self.assertEqual(state_path.read_bytes(), state_before)
                self.assertEqual((self.repo / "calc.py").read_bytes(), source_before)

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
            (
                "refresh-finding-test",
                "--finding",
                "F001",
                "--test",
                "unit-regression",
            ),
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
