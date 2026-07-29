from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


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

    def committed_range(self) -> tuple[str, str]:
        base = self.git("rev-parse", "HEAD")
        self.git("add", "calc.py")
        self.git("commit", "-qm", "change operator")
        return base, self.git("rev-parse", "HEAD")

    def coverage_plan(self, scope_hash: str, *, protocol: bool = False) -> dict:
        signals = []
        lenses = [
            {
                "lens_id": "correctness",
                "required": True,
                "reviewer_id": "correctness",
                "independence_group": "model-a",
                "review_mode": "subagent",
                "fallback": "sequential_degraded_self_audit",
            },
            {
                "lens_id": "test_adequacy",
                "required": True,
                "reviewer_id": "test-adequacy",
                "independence_group": "model-a",
                "review_mode": "subagent",
                "fallback": "sequential_degraded_self_audit",
            },
            {
                "lens_id": "standards_alignment",
                "required": True,
                "reviewer_id": "standards",
                "independence_group": "model-a",
                "review_mode": "subagent",
                "fallback": "sequential_degraded_self_audit",
            },
        ]
        if protocol:
            signals.append(
                {
                    "code": "state_dependent_schema",
                    "rationale": "The response shape changes at Gate A.",
                    "evidence_paths": ["calc.py"],
                }
            )
            lenses.append(
                {
                    "lens_id": "protocol_coherence",
                    "required": True,
                    "reviewer_id": "protocol",
                    "independence_group": "model-a",
                    "review_mode": "subagent",
                    "fallback": "sequential_degraded_self_audit",
                }
            )
        return {
            "schema_version": "material-review/coverage-plan/v1",
            "scope_hash": scope_hash,
            "workflow_profile": "material_review",
            "risk_signals": signals,
            "lenses": lenses,
            "max_candidate_corrections": 1,
        }

    def init_with_coverage(self, *, protocol: bool = False) -> str:
        scope_hash = self.init()
        path = self.write_json(
            "coverage-plan.json", self.coverage_plan(scope_hash, protocol=protocol)
        )
        self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(path),
        )
        return scope_hash

    def empty_candidate_set(self, scope_hash: str, reviewer_id: str, area: str) -> dict:
        return {
            "schema_version": "material-review/candidate-set/v1",
            "scope_hash": scope_hash,
            "reviewer_id": reviewer_id,
            "independence_group": "model-a",
            "review_mode": "subagent",
            "findings": [],
            "coverage": {
                "files_reviewed": ["calc.py"],
                "areas": [area],
                "limitations": [],
            },
        }

    def preflight_core_wave(self, scope_hash: str, correctness: dict) -> list[Path]:
        payloads = [
            ("correctness", correctness),
            (
                "test_adequacy",
                self.empty_candidate_set(scope_hash, "test-adequacy", "tests"),
            ),
            (
                "standards_alignment",
                self.empty_candidate_set(scope_hash, "standards", "standards"),
            ),
        ]
        paths = []
        for lens_id, payload in payloads:
            path = self.write_json(f"{lens_id}.json", payload)
            self.run_tool(
                "check-candidates",
                "--repo-root",
                str(self.repo),
                "--run-id",
                self.run_id,
                "--lens",
                lens_id,
                "--input",
                str(path),
            )
            paths.append(path)
        return paths

    def ingest_candidate_paths(self, paths: list[Path], *, expected: int = 0) -> None:
        input_args = [item for path in paths for item in ("--input", str(path))]
        self.run_tool(
            "ingest-candidates",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            *input_args,
            expected=expected,
        )

    def assign_fallback(
        self,
        *,
        lens_id: str = "correctness",
        reviewer_id: str = "fallback-correctness",
        independence_group: str = "model-b",
        review_mode: str = "subagent",
        failure_trigger_kind: str = "candidate_preflight_receipt",
        failure_trigger_hash: str | None = None,
    ) -> dict:
        state = self.load("state.json")
        if failure_trigger_hash is None:
            if failure_trigger_kind == "candidate_preflight_receipt":
                route_state = state["candidate_preflight"][lens_id]
                failure_trigger_hash = route_state["primary"][-1]["receipt_hash"]
            else:
                failure_trigger_hash = state["reviewer_failure_attestations"][lens_id][
                    "primary"
                ]["attestation_hash"]
        self.run_tool(
            "assign-fallback",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--lens",
            lens_id,
            "--failure-trigger-kind",
            failure_trigger_kind,
            "--failure-trigger-hash",
            failure_trigger_hash,
            "--reviewer-id",
            reviewer_id,
            "--independence-group",
            independence_group,
            "--review-mode",
            review_mode,
        )
        return self.load(f"fallback-assignments/{lens_id}.json")

    def record_reviewer_failure(
        self,
        *,
        lens_id: str = "correctness",
        route: str = "primary",
        reason: str = "timeout",
        observer_kind: str = "scheduler",
        observer_id: str = "root-scheduler",
        diagnostics: tuple[str, ...] = ("elapsed_seconds=300",),
        expected: int = 0,
    ) -> dict | None:
        diagnostic_args = [
            item for diagnostic in diagnostics for item in ("--diagnostic", diagnostic)
        ]
        self.run_tool(
            "record-reviewer-failure",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--lens",
            lens_id,
            "--route",
            route,
            "--reason",
            reason,
            "--observer-kind",
            observer_kind,
            "--observer-id",
            observer_id,
            *diagnostic_args,
            expected=expected,
        )
        if expected:
            return None
        return self.load(f"reviewer-failure-attestations/{lens_id}/{route}.json")

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
        scope_hash = self.init_with_coverage()
        candidate_paths = self.preflight_core_wave(
            scope_hash, self.candidate_set(scope_hash, include_style=include_style)
        )
        input_args = [item for path in candidate_paths for item in ("--input", str(path))]
        self.run_tool(
            "ingest-candidates",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            *input_args,
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
        scope_hash, plan = self.retain_fixed_finding()
        self.run_tool(
            "prepare-verification",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
        )
        return scope_hash, plan, self.load("fix-summary.json")

    def retain_fixed_finding(
        self,
        *,
        test_command: str = "grep -Fq 'return a + b' calc.py",
        global_tests: list[dict] | None = None,
    ) -> tuple[str, dict]:
        scope_hash, plan = self.approve_and_plan(
            test_command=test_command,
            global_tests=global_tests,
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

    def test_pull_request_scope_uses_merge_base_while_range_stays_direct(self) -> None:
        merge_base = self.git("rev-parse", "HEAD")
        self.git("switch", "-qc", "feature")
        self.git("add", "calc.py")
        self.git("commit", "-qm", "feature change")
        feature_head = self.git("rev-parse", "HEAD")

        self.git("switch", "-qc", "base", merge_base)
        (self.repo / "calc.py").write_text(
            "def add(a, b):\n    return a * b\n", encoding="utf-8"
        )
        (self.repo / "base_only.py").write_text("BASE_ONLY = True\n", encoding="utf-8")
        self.git("add", "calc.py", "base_only.py")
        self.git("commit", "-qm", "advance base")
        host_base = self.git("rev-parse", "HEAD")

        self.run_tool(
            "init",
            "--repo-root",
            str(self.repo),
            "--scope",
            "pull_request",
            "--base",
            "base",
            "--head",
            "feature",
            "--run-id",
            self.run_id,
            "--review-object-kind",
            "pull_request",
            "--review-object-id",
            "CoveMB/material-code-review-plugin#3",
            "--review-base-sha",
            host_base,
            "--review-head-sha",
            feature_head,
        )
        scope = self.load("scope.json")
        identity = scope["identity"]
        state = self.load("state.json")
        expected_patch = subprocess.run(
            [
                "git",
                "diff",
                "--binary",
                "--full-index",
                "--find-renames",
                f"{merge_base}..{feature_head}",
                "--",
            ],
            cwd=self.repo,
            check=True,
            capture_output=True,
        ).stdout
        direct_patch = subprocess.run(
            [
                "git",
                "diff",
                "--binary",
                "--full-index",
                "--find-renames",
                f"{host_base}..{feature_head}",
                "--",
            ],
            cwd=self.repo,
            check=True,
            capture_output=True,
        ).stdout

        self.assertEqual(identity["actual_scope"], "pull_request")
        self.assertEqual(identity["comparison_kind"], "merge_base_to_head")
        self.assertEqual(identity["effective_merge_base"], merge_base)
        self.assertEqual(identity["baseline_sha"], merge_base)
        self.assertEqual(identity["comparison_sha"], feature_head)
        self.assertEqual(
            identity["review_object"],
            {
                "kind": "pull_request",
                "identifier": "CoveMB/material-code-review-plugin#3",
                "base_sha": host_base,
                "head_sha": feature_head,
                "metadata_source": "read_only_host_lookup",
            },
        )
        self.assertEqual(scope["scope_hash"], reviewctl.scope_identity_hash(identity))
        self.assertEqual(
            state["scope_params"]["review_object"], identity["review_object"]
        )
        self.assertEqual((self.run_dir / "scope.patch").read_bytes(), expected_patch)
        self.assertNotEqual(expected_patch, direct_patch)
        self.assertEqual(
            {entry["path"] for entry in self.load("files.json")}, {"calc.py"}
        )
        self.assertEqual(
            (self.run_dir / "sources" / "baseline" / "calc.py").read_text(
                encoding="utf-8"
            ),
            "def add(a, b):\n    return a + b\n",
        )
        self.assertEqual(
            (self.run_dir / "sources" / "comparison" / "calc.py").read_text(
                encoding="utf-8"
            ),
            "def add(a, b):\n    return a - b\n",
        )
        self.run_tool(
            "check-scope", "--repo-root", str(self.repo), "--run-id", self.run_id
        )

        range_run_id = "range-run"
        self.run_tool(
            "init",
            "--repo-root",
            str(self.repo),
            "--scope",
            "range",
            "--base",
            "base",
            "--head",
            "feature",
            "--run-id",
            range_run_id,
        )
        range_run_dir = self.run_dir.parent / range_run_id
        range_scope = json.loads(
            (range_run_dir / "scope.json").read_text(encoding="utf-8")
        )
        self.assertEqual(range_scope["identity"]["actual_scope"], "range")
        self.assertEqual(range_scope["identity"]["comparison_kind"], "commit")
        self.assertNotIn("effective_merge_base", range_scope["identity"])
        self.assertEqual((range_run_dir / "scope.patch").read_bytes(), direct_patch)
        self.run_tool(
            "check-scope",
            "--repo-root",
            str(self.repo),
            "--run-id",
            range_run_id,
        )

    def test_pull_request_scope_provenance_is_bound_to_scope_hash(self) -> None:
        base, head = self.committed_range()
        self.run_tool(
            "init",
            "--repo-root",
            str(self.repo),
            "--scope",
            "pull_request",
            "--base",
            base,
            "--head",
            head,
            "--run-id",
            self.run_id,
            "--review-object-kind",
            "pull_request",
            "--review-object-id",
            "CoveMB/material-code-review-plugin#3",
            "--review-base-sha",
            base,
            "--review-head-sha",
            head,
        )
        scope = self.load("scope.json")
        self.assertEqual(
            scope["identity"]["review_object"],
            {
                "kind": "pull_request",
                "identifier": "CoveMB/material-code-review-plugin#3",
                "base_sha": base,
                "head_sha": head,
                "metadata_source": "read_only_host_lookup",
            },
        )
        self.assertEqual(scope["scope_hash"], reviewctl.scope_identity_hash(scope["identity"]))
        self.run_tool(
            "check-scope", "--repo-root", str(self.repo), "--run-id", self.run_id
        )

    def test_pull_request_scope_invalid_inputs_fail_before_run_creation(self) -> None:
        base, head = self.committed_range()
        common = [
            "--repo-root",
            str(self.repo),
            "--base",
            base,
            "--head",
            head,
            "--review-object-kind",
            "pull_request",
            "--review-object-id",
            "CoveMB/material-code-review-plugin#3",
            "--review-base-sha",
            base,
            "--review-head-sha",
            head,
        ]
        cases = {
            "absent-provenance": [
                "--repo-root",
                str(self.repo),
                "--base",
                base,
                "--head",
                head,
            ],
            "partial-provenance": common[:-2],
            "unqualified-identity": [
                *common[:9],
                "3",
                *common[10:],
            ],
            "base-mismatch": [
                *common[:11],
                head,
                *common[12:],
            ],
            "missing-base-ref": [
                item
                for index, item in enumerate(common)
                if index not in {2, 3}
            ],
        }
        for label, arguments in cases.items():
            with self.subTest(label=label):
                run_id = f"invalid-{label}"
                self.run_tool(
                    "init",
                    *arguments,
                    "--scope",
                    "pull_request",
                    "--run-id",
                    run_id,
                    expected=2,
                )
                self.assertFalse((self.run_dir.parent / run_id).exists())

        self.run_tool(
            "init",
            *common,
            "--scope",
            "range",
            "--run-id",
            self.run_id,
            expected=2,
        )
        self.assertFalse(self.run_dir.exists())

    def test_pull_request_mutable_scope_guard_rejects_matching_metadata_before_artifacts(
        self,
    ) -> None:
        base, head = self.committed_range()
        (self.repo / "test_calc.py").write_text(
            "from calc import add\nassert add(1, 2) == 3\n# later workspace-only change\n",
            encoding="utf-8",
        )
        run_id = "mutable-pr-branch"

        _, stderr = self.run_tool(
            "init",
            "--repo-root",
            str(self.repo),
            "--scope",
            "branch",
            "--base",
            base,
            "--run-id",
            run_id,
            "--review-object-kind",
            "pull_request",
            "--review-object-id",
            "CoveMB/material-code-review-plugin#3",
            "--review-base-sha",
            base,
            "--review-head-sha",
            head,
            expected=2,
        )

        self.assertIn(
            "PR review provenance is valid only with scope=pull_request", stderr
        )
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertTrue(self.git("diff", "--", "test_calc.py"))
        self.assertFalse((self.run_dir.parent / run_id).exists())

    def test_coverage_plan_is_recorded_and_hash_bound(self) -> None:
        scope_hash = self.init_with_coverage(protocol=True)
        plan = self.load("coverage-plan.json")
        state = self.load("state.json")
        self.assertEqual(plan["scope_hash"], scope_hash)
        self.assertEqual(
            state["hashes"]["coverage_plan_hash"], reviewctl.canonical_hash(plan)
        )
        self.assertTrue(state["coverage_required"])

    def test_coverage_profile_is_root_owned_and_review_defaults_are_preserved(self) -> None:
        scope_hash = self.init()
        state = self.load("state.json")
        self.assertEqual(state.get("workflow_profile"), "material_review")

        mismatched = self.coverage_plan(scope_hash)
        mismatched["workflow_profile"] = "material_simplification"
        mismatched_path = self.write_json("mismatched-profile.json", mismatched)
        self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(mismatched_path),
            expected=2,
        )
        self.assertFalse((self.run_dir / "coverage-plan.json").exists())
        self.assertNotIn("coverage_plan_hash", self.load("state.json")["hashes"])

        plan_path = self.write_json("review-profile.json", self.coverage_plan(scope_hash))
        self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(plan_path),
        )
        recorded = self.load("coverage-plan.json")
        self.assertEqual(recorded["workflow_profile"], "material_review")
        self.assertEqual(
            {lens["lens_id"] for lens in recorded["lenses"]},
            {"correctness", "test_adequacy", "standards_alignment"},
        )

    def test_material_review_core_lens_requiredness_is_fail_closed(self) -> None:
        core_lenses = ("correctness", "test_adequacy", "standards_alignment")
        for mode in ("absent", "not-required"):
            for lens_id in core_lenses:
                with self.subTest(mode=mode, lens_id=lens_id):
                    self.run_id = f"core-{mode}-{lens_id}"
                    scope_hash = self.init()
                    plan = self.coverage_plan(scope_hash)
                    if mode == "absent":
                        plan["lenses"] = [
                            lens for lens in plan["lenses"] if lens["lens_id"] != lens_id
                        ]
                    else:
                        next(
                            lens for lens in plan["lenses"] if lens["lens_id"] == lens_id
                        )["required"] = False
                    plan_path = self.write_json(
                        f"core-{mode}-{lens_id}.json", plan
                    )

                    self.run_tool(
                        "record-coverage",
                        "--repo-root",
                        str(self.repo),
                        "--run-id",
                        self.run_id,
                        "--input",
                        str(plan_path),
                        expected=2,
                    )

                    state = self.load("state.json")
                    self.assertEqual(state["phase"], "CONTEXT_FROZEN")
                    self.assertNotIn("coverage_plan_hash", state["hashes"])
                    self.assertFalse((self.run_dir / "coverage-plan.json").exists())

        self.run_id = "core-valid"
        scope_hash = self.init()
        plan_path = self.write_json(
            "core-valid.json", self.coverage_plan(scope_hash)
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
        recorded = self.load("coverage-plan.json")
        self.assertEqual(
            {
                lens["lens_id"]
                for lens in recorded["lenses"]
                if lens["required"]
            },
            set(core_lenses),
        )

    def test_coverage_plan_rejects_stale_scope_hash(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan(scope_hash)
        plan["scope_hash"] = "0" * 64
        path = self.write_json("stale-coverage-plan.json", plan)
        self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(path),
            expected=2,
        )
        self.assertFalse((self.run_dir / "coverage-plan.json").exists())

    def test_coverage_plan_rejects_duplicate_lens_ids(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan(scope_hash)
        plan["lenses"][1]["lens_id"] = "correctness"
        path = self.write_json("duplicate-lens-coverage-plan.json", plan)
        self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(path),
            expected=2,
        )

    def test_coverage_plan_rejects_duplicate_reviewer_ids(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan(scope_hash)
        plan["lenses"][1]["reviewer_id"] = "correctness"
        path = self.write_json("duplicate-reviewer-coverage-plan.json", plan)
        self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(path),
            expected=2,
        )

    def test_coverage_plan_requires_protocol_lens_for_protocol_risk(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan(scope_hash)
        plan["risk_signals"] = [
            {
                "code": "state_dependent_schema",
                "rationale": "The response shape changes at Gate A.",
                "evidence_paths": ["calc.py"],
            }
        ]
        path = self.write_json("missing-protocol-coverage-plan.json", plan)
        self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(path),
            expected=2,
        )

    def test_valid_candidate_preflight_does_not_advance_phase(self) -> None:
        scope_hash = self.init_with_coverage()
        path = self.write_json(
            "candidate.json", self.candidate_set(scope_hash, include_style=False)
        )
        self.run_tool(
            "check-candidates",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--lens",
            "correctness",
            "--input",
            str(path),
        )
        receipt = self.load("candidate-preflight/correctness/primary/attempt-1.json")
        self.assertEqual(receipt["verdict"], "valid")
        self.assertEqual(self.load("state.json")["phase"], "CONTEXT_FROZEN")

    def test_concurrent_candidate_preflights_preserve_each_lens_receipt(self) -> None:
        scope_hash = self.init_with_coverage()
        candidate_paths = {
            "correctness": self.write_json(
                "concurrent-correctness.json",
                self.empty_candidate_set(scope_hash, "correctness", "correctness"),
            ),
            "test_adequacy": self.write_json(
                "concurrent-test-adequacy.json",
                self.empty_candidate_set(scope_hash, "test-adequacy", "tests"),
            ),
        }
        original_load_state = reviewctl.load_state
        load_condition = threading.Condition()
        load_count = 0

        def synchronized_load_state(run_dir: Path):
            nonlocal load_count
            state = original_load_state(run_dir)
            with load_condition:
                load_count += 1
                if load_count < 2:
                    load_condition.wait_for(lambda: load_count >= 2, timeout=2)
                else:
                    load_condition.notify_all()
            return state

        results: list[int] = []

        def preflight(lens_id: str) -> None:
            results.append(
                reviewctl.main(
                    [
                        "check-candidates",
                        "--repo-root",
                        str(self.repo),
                        "--run-id",
                        self.run_id,
                        "--lens",
                        lens_id,
                        "--input",
                        str(candidate_paths[lens_id]),
                    ]
                )
            )

        with mock.patch.object(reviewctl, "load_state", side_effect=synchronized_load_state):
            threads = [
                threading.Thread(target=preflight, args=(lens_id,))
                for lens_id in candidate_paths
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(sorted(results), [0, 0])
        preflight_state = self.load("state.json")["candidate_preflight"]
        self.assertEqual(set(preflight_state), set(candidate_paths))
        for lens_id in candidate_paths:
            self.assertEqual(set(preflight_state[lens_id]), {"primary", "fallback"})
            self.assertEqual(len(preflight_state[lens_id]["primary"]), 1)
            self.assertEqual(preflight_state[lens_id]["fallback"], [])

    def test_nonverbatim_quote_gets_one_correctable_candidate_preflight_receipt(self) -> None:
        scope_hash = self.init_with_coverage()
        draft = self.candidate_set(scope_hash, include_style=False)
        draft["findings"][0]["evidence_quote"] = "return something else"
        path = self.write_json("bad-quote.json", draft)
        self.run_tool(
            "check-candidates",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--lens",
            "correctness",
            "--input",
            str(path),
            expected=2,
        )
        receipt = self.load("candidate-preflight/correctness/primary/attempt-1.json")
        self.assertEqual(receipt["verdict"], "correctable")
        self.assertEqual(receipt["diagnostics"][0]["code"], "EVIDENCE_NOT_FOUND")

    def test_mechanical_correction_semantic_hash_rejects_substantive_drift(self) -> None:
        scope_hash = self.init_with_coverage()
        draft = self.candidate_set(scope_hash, include_style=False)
        draft["findings"][0]["evidence_quote"] = "return something else"
        first = self.write_json("first.json", draft)
        self.run_tool(
            "check-candidates",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--lens",
            "correctness",
            "--input",
            str(first),
            expected=2,
        )
        prior = self.load("candidate-preflight/correctness/primary/attempt-1.json")
        draft["findings"][0]["evidence_quote"] = "    return a - b"
        draft["findings"][0]["observable_consequence"] = "Changed substance."
        second = self.write_json("second.json", draft)
        self.run_tool(
            "check-candidates",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--lens",
            "correctness",
            "--input",
            str(second),
            "--supersedes",
            prior["receipt_hash"],
            expected=2,
        )
        diagnostics = self.load("candidate-preflight/correctness/primary/attempt-2.json")[
            "diagnostics"
        ]
        self.assertIn("SUBSTANTIVE_DRIFT", {item["code"] for item in diagnostics})

    def test_mechanical_correction_semantic_hash_accepts_local_id_repair(self) -> None:
        scope_hash = self.init_with_coverage()
        draft = self.candidate_set(scope_hash)
        draft["findings"][1]["local_id"] = draft["findings"][0]["local_id"]
        first = self.write_json("duplicate-local-id.json", draft)
        self.run_tool(
            "check-candidates",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--lens",
            "correctness",
            "--input",
            str(first),
            expected=2,
        )
        prior = self.load("candidate-preflight/correctness/primary/attempt-1.json")
        self.assertIn(
            "DUPLICATE_LOCAL_ID", {item["code"] for item in prior["diagnostics"]}
        )

        draft["findings"][1]["local_id"] = "b-rename"
        corrected = self.write_json("corrected-local-id.json", draft)
        self.run_tool(
            "check-candidates",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--lens",
            "correctness",
            "--input",
            str(corrected),
            "--supersedes",
            prior["receipt_hash"],
        )
        receipt = self.load("candidate-preflight/correctness/primary/attempt-2.json")
        self.assertEqual(receipt["verdict"], "valid")
        self.assertEqual(receipt["semantic_hash"], prior["semantic_hash"])

    def test_mechanical_correction_semantic_hash_accepts_unknown_key_removal(self) -> None:
        scope_hash = self.init_with_coverage()
        draft = self.candidate_set(scope_hash, include_style=False)
        draft["findings"][0]["unexpected_key"] = "remove me"
        first = self.write_json("unknown-key.json", draft)
        self.run_tool(
            "check-candidates",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--lens",
            "correctness",
            "--input",
            str(first),
            expected=2,
        )
        prior = self.load("candidate-preflight/correctness/primary/attempt-1.json")
        self.assertIn("UNKNOWN_FIELD", {item["code"] for item in prior["diagnostics"]})

        del draft["findings"][0]["unexpected_key"]
        corrected = self.write_json("removed-unknown-key.json", draft)
        self.run_tool(
            "check-candidates",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--lens",
            "correctness",
            "--input",
            str(corrected),
            "--supersedes",
            prior["receipt_hash"],
        )
        receipt = self.load("candidate-preflight/correctness/primary/attempt-2.json")
        self.assertEqual(receipt["verdict"], "valid")
        self.assertEqual(receipt["semantic_hash"], prior["semantic_hash"])

    def test_evidence_only_candidate_preflight_correction_succeeds(self) -> None:
        scope_hash = self.init_with_coverage()
        draft = self.candidate_set(scope_hash, include_style=False)
        draft["findings"][0]["evidence_quote"] = "return something else"
        first = self.write_json("first-evidence.json", draft)
        self.run_tool(
            "check-candidates",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--lens",
            "correctness",
            "--input",
            str(first),
            expected=2,
        )
        prior = self.load("candidate-preflight/correctness/primary/attempt-1.json")
        draft["findings"][0]["evidence_quote"] = "    return a - b"
        second = self.write_json("second-evidence.json", draft)
        self.run_tool(
            "check-candidates",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--lens",
            "correctness",
            "--input",
            str(second),
            "--supersedes",
            prior["receipt_hash"],
        )
        receipt = self.load("candidate-preflight/correctness/primary/attempt-2.json")
        self.assertEqual(receipt["verdict"], "valid")

    def test_candidate_preflight_route_budget_allows_correction_then_fallback(self) -> None:
        scope_hash = self.init_with_coverage()
        first_draft = self.candidate_set(scope_hash, include_style=False)
        first_draft["findings"][0]["evidence_quote"] = "return something else"
        first_path = self.write_json("route-primary-1.json", first_draft)
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(first_path), expected=2,
        )
        first = self.load(
            "candidate-preflight/correctness/primary/attempt-1.json"
        )

        second_draft = self.candidate_set(scope_hash, include_style=False)
        second_draft["findings"][0]["observable_consequence"] = "Changed substance."
        second_path = self.write_json("route-primary-2.json", second_draft)
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(second_path),
            "--supersedes", first["receipt_hash"], expected=2,
        )
        second = self.load(
            "candidate-preflight/correctness/primary/attempt-2.json"
        )
        self.assertEqual(second["verdict"], "rejected")
        self.assign_fallback(
            reviewer_id="correctness", independence_group="model-a"
        )

        fallback_path = self.write_json(
            "route-fallback-1.json",
            self.candidate_set(scope_hash, include_style=False),
        )
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(fallback_path), "--fallback",
        )
        fallback = self.load(
            "candidate-preflight/correctness/fallback/attempt-1.json"
        )
        self.assertEqual(fallback["route"], "fallback")
        self.assertEqual(fallback["attempt"], 1)
        self.assertIsNone(fallback["supersedes_receipt_hash"])

        route_state = self.load("state.json")["candidate_preflight"]["correctness"]
        self.assertEqual(set(route_state), {"primary", "fallback"})
        self.assertEqual(len(route_state["primary"]), 2)
        self.assertEqual(len(route_state["fallback"]), 1)
        state_before_rejections = copy.deepcopy(route_state)

        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(fallback_path), expected=2,
        )
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(fallback_path), "--fallback",
            expected=2,
        )
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(fallback_path), "--fallback",
            "--supersedes", fallback["receipt_hash"], expected=2,
        )
        self.assertEqual(
            self.load("state.json")["candidate_preflight"]["correctness"],
            state_before_rejections,
        )
        self.assertFalse(
            (self.run_dir / "candidate-preflight/correctness/primary/attempt-3.json").exists()
        )
        self.assertFalse(
            (self.run_dir / "candidate-preflight/correctness/fallback/attempt-2.json").exists()
        )

        paths = [fallback_path]
        for lens_id, reviewer_id, area in (
            ("test_adequacy", "test-adequacy", "tests"),
            ("standards_alignment", "standards", "standards"),
        ):
            path = self.write_json(
                f"route-{lens_id}.json",
                self.empty_candidate_set(scope_hash, reviewer_id, area),
            )
            self.run_tool(
                "check-candidates", "--repo-root", str(self.repo),
                "--run-id", self.run_id, "--lens", lens_id, "--input", str(path),
            )
            paths.append(path)
        self.ingest_candidate_paths(paths)
        correctness = next(
            item for item in self.load("coverage-status.json")["lenses"]
            if item["lens_id"] == "correctness"
        )
        self.assertEqual(correctness["completion_route"], "fallback")

    def test_candidate_preflight_route_budget_rejects_fallback_after_valid_primary(self) -> None:
        scope_hash = self.init_with_coverage()
        path = self.write_json(
            "valid-primary-route.json",
            self.candidate_set(scope_hash, include_style=False),
        )
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(path),
        )
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(path), "--fallback", expected=2,
        )
        route_state = self.load("state.json")["candidate_preflight"]["correctness"]
        self.assertEqual(len(route_state["primary"]), 1)
        self.assertEqual(route_state["fallback"], [])

    def test_third_candidate_preflight_attempt_is_refused(self) -> None:
        scope_hash = self.init_with_coverage()
        draft = self.candidate_set(scope_hash, include_style=False)
        draft["findings"][0]["evidence_quote"] = "return something else"
        first = self.write_json("first-third-attempt.json", draft)
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(first), expected=2,
        )
        prior = self.load("candidate-preflight/correctness/primary/attempt-1.json")
        draft["findings"][0]["evidence_quote"] = "    return a - b"
        second = self.write_json("second-third-attempt.json", draft)
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(second), "--supersedes",
            prior["receipt_hash"],
        )
        corrected = self.load("candidate-preflight/correctness/primary/attempt-2.json")
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(second), "--supersedes",
            corrected["receipt_hash"], expected=2,
        )
        self.assertFalse(
            (self.run_dir / "candidate-preflight/correctness/primary/attempt-3.json").exists()
        )

    def test_stale_scope_refuses_candidate_preflight(self) -> None:
        scope_hash = self.init_with_coverage()
        path = self.write_json(
            "stale-candidate.json", self.candidate_set(scope_hash, include_style=False)
        )
        (self.repo / "calc.py").write_text(
            "def add(a, b):\n    return a * b\n", encoding="utf-8"
        )
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(path), expected=2,
        )
        self.assertFalse((self.run_dir / "candidate-preflight").exists())

    def test_unparseable_candidate_preflight_permits_one_syntax_correction(self) -> None:
        scope_hash = self.init_with_coverage()
        first = self.out / "invalid-candidate.json"
        first.write_text("{not-json", encoding="utf-8")
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(first), expected=2,
        )
        prior = self.load("candidate-preflight/correctness/primary/attempt-1.json")
        self.assertIsNone(prior["semantic_hash"])
        self.assertEqual(prior["diagnostics"][0]["code"], "JSON_SYNTAX")
        corrected = self.write_json(
            "syntax-corrected.json", self.candidate_set(scope_hash, include_style=False)
        )
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(corrected), "--supersedes",
            prior["receipt_hash"],
        )
        self.assertEqual(
            self.load("candidate-preflight/correctness/primary/attempt-2.json")["verdict"], "valid"
        )

    def test_coverage_completion_rejects_input_bytes_not_bound_to_valid_receipt(self) -> None:
        scope_hash = self.init_with_coverage()
        paths = self.preflight_core_wave(
            scope_hash, self.candidate_set(scope_hash, include_style=False)
        )
        paths[0].write_text(paths[0].read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.ingest_candidate_paths(paths, expected=2)
        self.assertEqual(self.load("state.json")["phase"], "CONTEXT_FROZEN")
        self.assertFalse((self.run_dir / "coverage-status.json").exists())
        self.assertFalse((self.run_dir / "candidates.json").exists())

    def test_coverage_completion_preserves_rejected_optional_lens(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan(scope_hash)
        plan["lenses"].append(
            {
                "lens_id": "documentation",
                "required": False,
                "reviewer_id": "docs",
                "independence_group": "model-a",
                "review_mode": "subagent",
                "fallback": "none",
            }
        )
        plan_path = self.write_json("optional-coverage-plan.json", plan)
        self.run_tool(
            "record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--input", str(plan_path),
        )
        paths = self.preflight_core_wave(
            scope_hash, self.candidate_set(scope_hash, include_style=False)
        )
        rejected = self.candidate_set(scope_hash, include_style=False)
        rejected["reviewer_id"] = "docs"
        rejected["findings"][0]["category"] = "not-a-category"
        rejected_path = self.write_json("rejected-optional.json", rejected)
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "documentation", "--input", str(rejected_path), expected=2,
        )
        self.ingest_candidate_paths(paths)
        status = self.load("coverage-status.json")
        optional = next(item for item in status["lenses"] if item["lens_id"] == "documentation")
        self.assertFalse(optional["completed"])
        self.assertIn("CANDIDATE_INVALID", optional["diagnostics"])
        self.assertTrue(any("documentation" in item for item in status["limitations"]))

    def test_valid_optional_receipt_must_be_supplied_explicitly(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan(scope_hash)
        plan["lenses"].append(
            {
                "lens_id": "documentation",
                "required": False,
                "reviewer_id": "docs",
                "independence_group": "model-a",
                "review_mode": "subagent",
                "fallback": "none",
            }
        )
        plan_path = self.write_json("valid-optional-receipt-plan.json", plan)
        self.run_tool(
            "record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--input", str(plan_path),
        )
        required_paths = self.preflight_core_wave(
            scope_hash, self.candidate_set(scope_hash, include_style=False)
        )
        optional = self.candidate_set(scope_hash, include_style=False)
        optional["reviewer_id"] = "docs"
        optional_path = self.write_json("valid-optional-receipt-docs.json", optional)
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "documentation", "--input", str(optional_path),
        )
        state_before = copy.deepcopy(self.load("state.json"))

        self.ingest_candidate_paths(required_paths, expected=2)

        self.assertEqual(self.load("state.json"), state_before)
        self.assertFalse((self.run_dir / "coverage-status.json").exists())
        self.assertFalse((self.run_dir / "candidates.json").exists())

    def test_valid_optional_receipt_is_ingested_exactly_once(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan(scope_hash)
        plan["lenses"].append(
            {
                "lens_id": "documentation",
                "required": False,
                "reviewer_id": "docs",
                "independence_group": "model-a",
                "review_mode": "subagent",
                "fallback": "none",
            }
        )
        plan_path = self.write_json("valid-optional-receipt-success-plan.json", plan)
        self.run_tool(
            "record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--input", str(plan_path),
        )
        paths = self.preflight_core_wave(
            scope_hash, self.candidate_set(scope_hash, include_style=False)
        )
        optional = self.candidate_set(scope_hash, include_style=False)
        optional["reviewer_id"] = "docs"
        optional_path = self.write_json("valid-optional-receipt-success-docs.json", optional)
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "documentation", "--input", str(optional_path),
        )
        paths.append(optional_path)

        self.ingest_candidate_paths(paths)

        bundle = self.load("candidates.json")
        self.assertEqual(
            sum(item["reviewer_id"] == "docs" for item in bundle["reviewer_sets"]), 1
        )
        self.assertEqual(
            sum(item["reviewer_id"] == "docs" for item in bundle["candidates"]), 1
        )
        optional_status = next(
            item for item in bundle["coverage"]["lenses"]
            if item["lens_id"] == "documentation"
        )
        self.assertTrue(optional_status["completed"])

    def test_valid_optional_receipt_absence_remains_nonblocking(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan(scope_hash)
        plan["lenses"].append(
            {
                "lens_id": "documentation",
                "required": False,
                "reviewer_id": "docs",
                "independence_group": "model-a",
                "review_mode": "subagent",
                "fallback": "none",
            }
        )
        plan_path = self.write_json("valid-optional-receipt-absent-plan.json", plan)
        self.run_tool(
            "record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--input", str(plan_path),
        )
        paths = self.preflight_core_wave(
            scope_hash, self.candidate_set(scope_hash, include_style=False)
        )

        self.ingest_candidate_paths(paths)

        status = self.load("coverage-status.json")
        optional = next(
            item for item in status["lenses"] if item["lens_id"] == "documentation"
        )
        self.assertFalse(optional["completed"])
        self.assertTrue(any("documentation" in item for item in status["limitations"]))

    def test_fallback_assignment_binds_actual_identity_through_coverage(self) -> None:
        scope_hash = self.init_with_coverage()
        failed = self.candidate_set(scope_hash, include_style=False)
        failed["findings"][0]["category"] = "not-a-category"
        failed_path = self.write_json("fallback-assignment-primary.json", failed)
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(failed_path), expected=2,
        )
        primary = self.load("candidate-preflight/correctness/primary/attempt-1.json")

        fallback = self.candidate_set(scope_hash, include_style=False)
        fallback["reviewer_id"] = "fallback-correctness"
        fallback["independence_group"] = "model-b"
        fallback_path = self.write_json("fallback-assignment-candidate.json", fallback)
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(fallback_path), "--fallback", expected=2,
        )
        self.assertFalse((self.run_dir / "fallback-assignments/correctness.json").exists())

        assignment = self.assign_fallback()
        self.assertEqual(assignment["failure_trigger_hash"], primary["receipt_hash"])
        self.assertEqual(assignment["reviewer_id"], "fallback-correctness")
        self.assertEqual(assignment["independence_group"], "model-b")
        self.assertTrue(assignment["degraded"])

        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(fallback_path), "--fallback",
        )
        receipt = self.load("candidate-preflight/correctness/fallback/attempt-1.json")
        self.assertEqual(receipt["reviewer_id"], "fallback-correctness")
        self.assertEqual(receipt["independence_group"], "model-b")
        self.assertEqual(receipt["fallback_assignment_hash"], assignment["assignment_hash"])

        paths = [fallback_path]
        for lens_id, reviewer_id, area in (
            ("test_adequacy", "test-adequacy", "tests"),
            ("standards_alignment", "standards", "standards"),
        ):
            path = self.write_json(
                f"fallback-assignment-{lens_id}.json",
                self.empty_candidate_set(scope_hash, reviewer_id, area),
            )
            self.run_tool(
                "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
                "--lens", lens_id, "--input", str(path),
            )
            paths.append(path)
        self.ingest_candidate_paths(paths)

        bundle = self.load("candidates.json")
        correctness_set = next(
            item for item in bundle["reviewer_sets"]
            if item["reviewer_id"] == "fallback-correctness"
        )
        self.assertEqual(correctness_set["independence_group"], "model-b")
        correctness = next(
            item for item in bundle["coverage"]["lenses"]
            if item["lens_id"] == "correctness"
        )
        self.assertEqual(correctness["completion_route"], "fallback")
        self.assertEqual(correctness["reviewer_id"], "fallback-correctness")
        self.assertEqual(correctness["independence_group"], "model-b")
        self.assertEqual(
            correctness["fallback_assignment_hash"], assignment["assignment_hash"]
        )
        self.assertEqual(correctness["fallback_trigger_hash"], primary["receipt_hash"])
        self.assertTrue(correctness["degraded"])

        adjudication = self.adjudication(
            scope_hash, bundle["candidate_bundle_hash"], include_style=False
        )
        adjudication["groups"][0]["source_reviewers"] = ["fallback-correctness"]
        adjudication["groups"][0]["source_independence_groups"] = ["model-b"]
        adjudication["groups"][0]["validation"]["independence_group"] = "model-b"
        adjudication_path = self.write_json(
            "fallback-assignment-same-group-adjudication.json", adjudication
        )
        self.run_tool(
            "compile-ledger", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--input", str(adjudication_path), expected=2,
        )
        self.assertFalse((self.run_dir / "ledger.json").exists())

    def test_fallback_assignment_rejects_identity_drift(self) -> None:
        scope_hash = self.init_with_coverage()
        failed = self.candidate_set(scope_hash, include_style=False)
        failed["findings"][0]["category"] = "not-a-category"
        failed_path = self.write_json("fallback-assignment-drift-primary.json", failed)
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(failed_path), expected=2,
        )
        assignment = self.assign_fallback()

        drifted_path = self.write_json(
            "fallback-assignment-drift.json",
            self.candidate_set(scope_hash, include_style=False),
        )
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(drifted_path), "--fallback", expected=2,
        )
        receipt = self.load("candidate-preflight/correctness/fallback/attempt-1.json")
        self.assertEqual(receipt["fallback_assignment_hash"], assignment["assignment_hash"])
        self.assertEqual(receipt["reviewer_id"], "fallback-correctness")
        self.assertIn("TOP_LEVEL_METADATA", {item["code"] for item in receipt["diagnostics"]})

    def test_fallback_assignment_rejects_unverified_or_duplicate_activation(self) -> None:
        scope_hash = self.init_with_coverage()
        failed = self.candidate_set(scope_hash, include_style=False)
        failed["findings"][0]["category"] = "not-a-category"
        failed_path = self.write_json("fallback-assignment-activation-primary.json", failed)
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(failed_path), expected=2,
        )
        command = (
            "assign-fallback", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--reviewer-id", "fallback-correctness",
            "--independence-group", "model-b", "--review-mode", "subagent",
        )
        self.run_tool(
            *command,
            "--failure-trigger-kind", "candidate_preflight_receipt",
            "--failure-trigger-hash", "0" * 64,
            expected=2,
        )
        self.run_tool(
            *command,
            "--failure-trigger-kind", "reviewer_failure_attestation",
            "--failure-trigger-hash", "0" * 64,
            expected=2,
        )
        self.assertFalse((self.run_dir / "fallback-assignments/correctness.json").exists())

        assignment = self.assign_fallback()
        state_before = copy.deepcopy(self.load("state.json"))
        self.run_tool(
            *command,
            "--failure-trigger-kind", "candidate_preflight_receipt",
            "--failure-trigger-hash", assignment["failure_trigger_hash"],
            expected=2,
        )
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(failed_path), expected=2,
        )
        self.assertEqual(self.load("state.json"), state_before)

        tampered = copy.deepcopy(assignment)
        tampered["reviewer_id"] = "forged-fallback"
        (self.run_dir / "fallback-assignments/correctness.json").write_text(
            json.dumps(tampered, indent=2), encoding="utf-8"
        )
        fallback = self.candidate_set(scope_hash, include_style=False)
        fallback["reviewer_id"] = "fallback-correctness"
        fallback["independence_group"] = "model-b"
        fallback_path = self.write_json("fallback-assignment-tampered.json", fallback)
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(fallback_path), "--fallback", expected=2,
        )
        self.assertFalse(
            (self.run_dir / "candidate-preflight/correctness/fallback/attempt-1.json").exists()
        )

    def test_fallback_assignment_requires_exhausted_correctable_route(self) -> None:
        scope_hash = self.init_with_coverage()
        correctable = self.candidate_set(scope_hash, include_style=False)
        correctable["findings"][0]["evidence_quote"] = "return something else"
        path = self.write_json("fallback-assignment-correctable-primary.json", correctable)
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(path), expected=2,
        )
        receipt_hash = self.load(
            "candidate-preflight/correctness/primary/attempt-1.json"
        )["receipt_hash"]
        self.run_tool(
            "assign-fallback", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness",
            "--failure-trigger-kind", "candidate_preflight_receipt",
            "--failure-trigger-hash", receipt_hash,
            "--reviewer-id", "fallback-correctness",
            "--independence-group", "model-b", "--review-mode", "subagent",
            expected=2,
        )
        self.assertFalse((self.run_dir / "fallback-assignments").exists())

    def test_fallback_assignment_rejects_valid_primary_and_optional_lens(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan(scope_hash)
        plan["lenses"].append(
            {
                "lens_id": "documentation",
                "required": False,
                "reviewer_id": "docs",
                "independence_group": "model-a",
                "review_mode": "subagent",
                "fallback": "none",
            }
        )
        plan_path = self.write_json("fallback-assignment-boundary-plan.json", plan)
        self.run_tool(
            "record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--input", str(plan_path),
        )
        valid_path = self.write_json(
            "fallback-assignment-valid-primary.json",
            self.candidate_set(scope_hash, include_style=False),
        )
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(valid_path),
        )
        primary_hash = self.load(
            "candidate-preflight/correctness/primary/attempt-1.json"
        )["receipt_hash"]
        for lens_id in ("correctness", "documentation"):
            self.run_tool(
                "assign-fallback", "--repo-root", str(self.repo), "--run-id", self.run_id,
                "--lens", lens_id,
                "--failure-trigger-kind", "candidate_preflight_receipt",
                "--failure-trigger-hash", primary_hash,
                "--reviewer-id", f"fallback-{lens_id}",
                "--independence-group", "model-b", "--review-mode", "subagent",
                expected=2,
            )
        self.assertFalse((self.run_dir / "fallback-assignments").exists())

    def test_fallback_none_rejects_replacement_and_finalizes_incomplete(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan(scope_hash)
        correctness = next(
            lens for lens in plan["lenses"] if lens["lens_id"] == "correctness"
        )
        correctness["fallback"] = "none"
        plan_path = self.write_json("fallback-none-plan.json", plan)
        self.run_tool(
            "record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--input", str(plan_path),
        )

        failed_primary = self.candidate_set(scope_hash, include_style=False)
        failed_primary["findings"][0]["category"] = "not-a-category"
        failed_primary_path = self.write_json(
            "fallback-none-primary.json", failed_primary
        )
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(failed_primary_path), expected=2,
        )
        primary_receipt = self.load(
            "candidate-preflight/correctness/primary/attempt-1.json"
        )
        self.assertEqual(primary_receipt["verdict"], "rejected")
        state_before_rejected_fallback = copy.deepcopy(self.load("state.json"))
        self.run_tool(
            "assign-fallback", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness",
            "--failure-trigger-kind", "candidate_preflight_receipt",
            "--failure-trigger-hash", primary_receipt["receipt_hash"],
            "--reviewer-id", "fallback-correctness",
            "--independence-group", "model-b", "--review-mode", "subagent",
            expected=2,
        )

        fallback = self.candidate_set(scope_hash, include_style=False)
        fallback["reviewer_id"] = "fallback-correctness"
        fallback["independence_group"] = "model-b"
        fallback_path = self.write_json("fallback-none-candidate.json", fallback)
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(fallback_path), "--fallback",
            expected=2,
        )
        self.assertEqual(self.load("state.json"), state_before_rejected_fallback)
        self.assertFalse((self.run_dir / "fallback-assignments").exists())
        self.assertFalse(
            (self.run_dir / "candidate-preflight/correctness/fallback").exists()
        )

        for lens_id, reviewer_id, area in (
            ("test_adequacy", "test-adequacy", "tests"),
            ("standards_alignment", "standards", "standards"),
        ):
            path = self.write_json(
                f"fallback-none-{lens_id}.json",
                self.empty_candidate_set(scope_hash, reviewer_id, area),
            )
            self.run_tool(
                "check-candidates", "--repo-root", str(self.repo),
                "--run-id", self.run_id, "--lens", lens_id, "--input", str(path),
            )

        self.run_tool(
            "finalize-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id
        )
        state = self.load("state.json")
        self.assertEqual(state["phase"], "REVIEW_INCOMPLETE")
        status = self.load("coverage-status.json")
        self.assertEqual(status["status"], "incomplete")
        correctness_status = next(
            lens for lens in status["lenses"] if lens["lens_id"] == "correctness"
        )
        self.assertFalse(correctness_status["completed"])
        self.assertEqual(
            correctness_status["primary_receipt_hash"], primary_receipt["receipt_hash"]
        )
        for relative in ("candidates.json", "ledger.json", "gates/findings.json"):
            self.assertFalse((self.run_dir / relative).exists())

    def test_reviewer_failure_attestation_authorizes_bound_fallback(self) -> None:
        scope_hash = self.init_with_coverage()
        primary_failure = self.record_reviewer_failure()
        self.assertIsNotNone(primary_failure)
        assert primary_failure is not None
        self.assertEqual(primary_failure["route"], "primary")
        self.assertEqual(primary_failure["assignment_kind"], "coverage_plan")
        self.assertEqual(primary_failure["reason"], "timeout")
        self.assertNotIn("candidate", primary_failure)
        self.assertNotIn("raw_log", primary_failure)

        assignment = self.assign_fallback(
            failure_trigger_kind="reviewer_failure_attestation",
            failure_trigger_hash=primary_failure["attestation_hash"],
        )
        pending_paths: list[Path] = []
        for lens_id, reviewer_id, area in (
            ("test_adequacy", "test-adequacy", "tests"),
            ("standards_alignment", "standards", "standards"),
        ):
            path = self.write_json(
                f"attestation-pending-{lens_id}.json",
                self.empty_candidate_set(scope_hash, reviewer_id, area),
            )
            self.run_tool(
                "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
                "--lens", lens_id, "--input", str(path),
            )
            pending_paths.append(path)
        state_before_pending_ingest = copy.deepcopy(self.load("state.json"))
        self.ingest_candidate_paths(pending_paths, expected=2)
        self.assertEqual(self.load("state.json"), state_before_pending_ingest)
        self.assertFalse((self.run_dir / "coverage-status.json").exists())
        self.assertFalse((self.run_dir / "candidates.json").exists())

        fallback = self.candidate_set(scope_hash, include_style=False)
        fallback["reviewer_id"] = "fallback-correctness"
        fallback["independence_group"] = "model-b"
        fallback_path = self.write_json("attested-fallback.json", fallback)
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(fallback_path), "--fallback",
        )

        paths = [fallback_path, *pending_paths]
        self.ingest_candidate_paths(paths)

        status = self.load("coverage-status.json")
        correctness = next(
            item for item in status["lenses"] if item["lens_id"] == "correctness"
        )
        self.assertEqual(correctness["completion_route"], "fallback")
        self.assertEqual(
            correctness["primary_attestation_hash"], primary_failure["attestation_hash"]
        )
        self.assertEqual(
            correctness["fallback_assignment_hash"], assignment["assignment_hash"]
        )
        self.assertEqual(
            correctness["fallback_trigger_kind"], "reviewer_failure_attestation"
        )
        self.assertTrue(correctness["degraded"])

    def test_reviewer_failure_attestation_exhausts_fallback_and_finalizes(self) -> None:
        scope_hash = self.init_with_coverage()
        for lens_id, reviewer_id, area in (
            ("test_adequacy", "test-adequacy", "tests"),
            ("standards_alignment", "standards", "standards"),
        ):
            path = self.write_json(
                f"attestation-finalize-{lens_id}.json",
                self.empty_candidate_set(scope_hash, reviewer_id, area),
            )
            self.run_tool(
                "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
                "--lens", lens_id, "--input", str(path),
            )
        primary_failure = self.record_reviewer_failure(
            reason="capacity_unavailable",
            diagnostics=("attempt_number=1",),
        )
        assert primary_failure is not None
        self.assign_fallback(
            failure_trigger_kind="reviewer_failure_attestation",
            failure_trigger_hash=primary_failure["attestation_hash"],
        )
        fallback_failure = self.record_reviewer_failure(
            route="fallback",
            reason="execution_failed",
            observer_kind="controller",
            observer_id="root-controller",
            diagnostics=("exit_code=1",),
        )
        assert fallback_failure is not None

        self.run_tool(
            "finalize-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id
        )
        state = self.load("state.json")
        self.assertEqual(state["phase"], "REVIEW_INCOMPLETE")
        status = self.load("coverage-status.json")
        self.assertEqual(status["status"], "incomplete")
        correctness = next(
            item for item in status["lenses"] if item["lens_id"] == "correctness"
        )
        self.assertEqual(
            correctness["primary_attestation_hash"], primary_failure["attestation_hash"]
        )
        self.assertEqual(
            correctness["fallback_attestation_hash"], fallback_failure["attestation_hash"]
        )
        self.assertIn("capacity_unavailable", correctness["diagnostics"])
        self.assertIn("execution_failed", correctness["diagnostics"])
        for relative in ("candidates.json", "ledger.json", "gates/findings.json"):
            self.assertFalse((self.run_dir / relative).exists())

    def test_reviewer_failure_attestation_rejects_unbound_or_readable_routes(self) -> None:
        scope_hash = self.init_with_coverage()
        state_before = copy.deepcopy(self.load("state.json"))
        self.record_reviewer_failure(route="fallback", expected=2)
        self.run_tool(
            "finalize-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id,
            expected=2,
        )
        self.assertEqual(self.load("state.json"), state_before)
        self.assertFalse((self.run_dir / "reviewer-failure-attestations").exists())
        self.assertFalse((self.run_dir / "coverage-status.json").exists())

        primary_failure = self.record_reviewer_failure()
        assert primary_failure is not None
        state_after_attestation = copy.deepcopy(self.load("state.json"))
        self.record_reviewer_failure(expected=2)
        self.assertEqual(self.load("state.json"), state_after_attestation)

        assignment = self.assign_fallback(
            failure_trigger_kind="reviewer_failure_attestation",
            failure_trigger_hash=primary_failure["attestation_hash"],
        )
        fallback = self.candidate_set(scope_hash, include_style=False)
        fallback["reviewer_id"] = assignment["reviewer_id"]
        fallback["independence_group"] = assignment["independence_group"]
        fallback_path = self.write_json("attestation-readable-fallback.json", fallback)
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(fallback_path), "--fallback",
        )
        self.record_reviewer_failure(route="fallback", expected=2)
        self.assertFalse(
            (self.run_dir / "reviewer-failure-attestations/correctness/fallback.json").exists()
        )

    def test_reviewer_failure_attestation_rejects_optional_and_unbounded_metadata(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan(scope_hash)
        plan["lenses"].append(
            {
                "lens_id": "documentation",
                "required": False,
                "reviewer_id": "docs",
                "independence_group": "model-a",
                "review_mode": "subagent",
                "fallback": "none",
            }
        )
        plan_path = self.write_json("attestation-optional-plan.json", plan)
        self.run_tool(
            "record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--input", str(plan_path),
        )
        self.record_reviewer_failure(lens_id="documentation", expected=2)
        self.record_reviewer_failure(
            diagnostics=("elapsed_seconds=999999",), expected=2
        )
        self.record_reviewer_failure(
            diagnostics=("elapsed_seconds=1", "elapsed_seconds=2"), expected=2
        )
        self.assertFalse((self.run_dir / "reviewer-failure-attestations").exists())

    def test_reviewer_failure_attestation_rejects_tampering(self) -> None:
        self.init_with_coverage()
        attestation = self.record_reviewer_failure()
        assert attestation is not None
        tampered = copy.deepcopy(attestation)
        tampered["reason"] = "execution_failed"
        (self.run_dir / "reviewer-failure-attestations/correctness/primary.json").write_text(
            json.dumps(tampered, indent=2), encoding="utf-8"
        )
        self.run_tool(
            "assign-fallback", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness",
            "--failure-trigger-kind", "reviewer_failure_attestation",
            "--failure-trigger-hash", attestation["attestation_hash"],
            "--reviewer-id", "fallback-correctness",
            "--independence-group", "model-b", "--review-mode", "subagent",
            expected=2,
        )
        self.assertFalse((self.run_dir / "fallback-assignments").exists())

    def test_reviewer_failure_attestation_rejects_complete_finalization(self) -> None:
        scope_hash = self.init_with_coverage()
        paths = self.preflight_core_wave(
            scope_hash, self.candidate_set(scope_hash, include_style=False)
        )
        state_before = copy.deepcopy(self.load("state.json"))
        self.run_tool(
            "finalize-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id,
            expected=2,
        )
        self.assertEqual(self.load("state.json"), state_before)
        self.assertFalse((self.run_dir / "coverage-status.json").exists())
        self.assertEqual(len(paths), 3)

    def test_provisional_v1_restart_rejects_artifacts_without_mutation(self) -> None:
        scope_hash = self.init_with_coverage()
        coverage_path = self.run_dir / "coverage-plan.json"
        current_coverage = self.load("coverage-plan.json")
        provisional_coverage = copy.deepcopy(current_coverage)
        provisional_coverage.pop("workflow_profile")
        coverage_path.write_text(json.dumps(provisional_coverage, indent=2), encoding="utf-8")
        state_before = copy.deepcopy(self.load("state.json"))
        candidate_path = self.write_json(
            "provisional-plan-candidate.json",
            self.candidate_set(scope_hash, include_style=False),
        )
        _, stderr = self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(candidate_path), expected=2,
        )
        self.assertIn("restart this run", stderr)
        self.assertEqual(self.load("state.json"), state_before)
        self.assertFalse((self.run_dir / "candidate-preflight").exists())

        coverage_path.write_text(json.dumps(current_coverage, indent=2), encoding="utf-8")
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(candidate_path),
        )
        receipt_path = self.run_dir / "candidate-preflight/correctness/primary/attempt-1.json"
        provisional_receipt = self.load(
            "candidate-preflight/correctness/primary/attempt-1.json"
        )
        for field in (
            "route", "independence_group", "review_mode", "fallback_assignment_hash", "degraded"
        ):
            provisional_receipt.pop(field)
        provisional_receipt["fallback"] = False
        provisional_receipt["receipt_hash"] = reviewctl.canonical_hash(
            {key: value for key, value in provisional_receipt.items() if key != "receipt_hash"}
        )
        receipt_path.write_text(json.dumps(provisional_receipt, indent=2), encoding="utf-8")
        state = self.load("state.json")
        state["candidate_preflight"]["correctness"]["primary"][0]["receipt_hash"] = (
            provisional_receipt["receipt_hash"]
        )
        (self.run_dir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        state_before = copy.deepcopy(state)
        _, stderr = self.run_tool(
            "ingest-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--input", str(candidate_path), expected=2,
        )
        self.assertIn("restart this run", stderr)
        self.assertEqual(self.load("state.json"), state_before)
        self.assertFalse((self.run_dir / "coverage-status.json").exists())
        self.assertFalse((self.run_dir / "candidates.json").exists())

    def test_provisional_v1_restart_preserves_legacy_absent_coverage_required(self) -> None:
        scope_hash = self.init()
        state = self.load("state.json")
        state.pop("coverage_required")
        state.pop("workflow_profile")
        (self.run_dir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        candidate_path = self.write_json(
            "legacy-unbound-candidate.json",
            self.candidate_set(scope_hash, include_style=False),
        )
        self.run_tool(
            "ingest-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--input", str(candidate_path),
        )
        bundle = self.load("candidates.json")
        self.assertNotIn("coverage", bundle)
        self.assertEqual(self.load("state.json")["phase"], "CANDIDATES_CAPTURED")

    def test_provisional_v1_restart_rejects_status_without_mutation(self) -> None:
        scope_hash = self.init_with_coverage()
        paths = self.preflight_core_wave(
            scope_hash, self.candidate_set(scope_hash, include_style=False)
        )
        self.ingest_candidate_paths(paths)
        bundle = self.load("candidates.json")
        status = self.load("coverage-status.json")
        for lens in status["lenses"]:
            lens.pop("primary_attestation_hash")
            lens.pop("fallback_attestation_hash")
        status["coverage_status_hash"] = reviewctl.canonical_hash(
            {key: value for key, value in status.items() if key != "coverage_status_hash"}
        )
        (self.run_dir / "coverage-status.json").write_text(
            json.dumps(status, indent=2), encoding="utf-8"
        )
        state = self.load("state.json")
        state["hashes"]["coverage_status_hash"] = status["coverage_status_hash"]
        (self.run_dir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        state_before = copy.deepcopy(state)
        adjudication_path = self.write_json(
            "provisional-status-adjudication.json",
            self.adjudication(
                scope_hash, bundle["candidate_bundle_hash"], include_style=False
            ),
        )
        _, stderr = self.run_tool(
            "compile-ledger", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--input", str(adjudication_path), expected=2,
        )
        self.assertIn("restart this run", stderr)
        self.assertEqual(self.load("state.json"), state_before)
        self.assertFalse((self.run_dir / "ledger.json").exists())

    def test_coverage_completion_accepts_one_valid_required_lens_fallback(self) -> None:
        scope_hash = self.init_with_coverage()
        failed = self.candidate_set(scope_hash, include_style=False)
        failed["findings"][0]["category"] = "not-a-category"
        failed_path = self.write_json("failed-primary.json", failed)
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(failed_path), expected=2,
        )
        self.assign_fallback(
            reviewer_id="correctness", independence_group="model-a"
        )
        fallback_path = self.write_json(
            "valid-fallback.json", self.candidate_set(scope_hash, include_style=False)
        )
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(fallback_path), "--fallback",
        )
        paths = [fallback_path]
        for lens_id, reviewer_id, area in (
            ("test_adequacy", "test-adequacy", "tests"),
            ("standards_alignment", "standards", "standards"),
        ):
            path = self.write_json(
                f"fallback-{lens_id}.json",
                self.empty_candidate_set(scope_hash, reviewer_id, area),
            )
            self.run_tool(
                "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
                "--lens", lens_id, "--input", str(path),
            )
            paths.append(path)
        self.ingest_candidate_paths(paths)
        correctness = next(
            item for item in self.load("coverage-status.json")["lenses"]
            if item["lens_id"] == "correctness"
        )
        self.assertTrue(correctness["completed"])
        self.assertIsNotNone(correctness["fallback_receipt_hash"])

    def test_coverage_completion_fails_when_required_primary_and_fallback_fail(self) -> None:
        scope_hash = self.init_with_coverage()
        failed = self.candidate_set(scope_hash, include_style=False)
        failed["findings"][0]["category"] = "not-a-category"
        primary_path = self.write_json("failed-required-primary.json", failed)
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(primary_path), expected=2,
        )
        self.assign_fallback(
            reviewer_id="correctness", independence_group="model-a"
        )
        failed_fallback = copy.deepcopy(failed)
        failed_fallback["findings"][0]["category"] = "still-not-a-category"
        fallback_path = self.write_json("failed-required-fallback.json", failed_fallback)
        self.run_tool(
            "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--lens", "correctness", "--input", str(fallback_path), "--fallback", expected=2,
        )
        for lens_id, reviewer_id, area in (
            ("test_adequacy", "test-adequacy", "tests"),
            ("standards_alignment", "standards", "standards"),
        ):
            path = self.write_json(
                f"failed-required-{lens_id}.json",
                self.empty_candidate_set(scope_hash, reviewer_id, area),
            )
            self.run_tool(
                "check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
                "--lens", lens_id, "--input", str(path),
            )
        self.run_tool(
            "finalize-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id,
        )
        self.assertEqual(self.load("state.json")["phase"], "REVIEW_INCOMPLETE")
        self.assertEqual(self.load("coverage-status.json")["status"], "incomplete")
        self.assertFalse((self.run_dir / "candidates.json").exists())

    def test_coverage_completion_compile_ledger_rejects_missing_status(self) -> None:
        scope_hash = self.init_with_coverage()
        paths = self.preflight_core_wave(
            scope_hash, self.candidate_set(scope_hash, include_style=False)
        )
        self.ingest_candidate_paths(paths)
        candidate_hash = self.load("candidates.json")["candidate_bundle_hash"]
        (self.run_dir / "coverage-status.json").unlink()
        adjudication_path = self.write_json(
            "missing-status-adjudication.json",
            self.adjudication(scope_hash, candidate_hash, include_style=False),
        )
        self.run_tool(
            "compile-ledger", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--input", str(adjudication_path), expected=2,
        )

    def test_coverage_completion_compile_ledger_rejects_stale_status(self) -> None:
        scope_hash = self.init_with_coverage()
        paths = self.preflight_core_wave(
            scope_hash, self.candidate_set(scope_hash, include_style=False)
        )
        self.ingest_candidate_paths(paths)
        candidate_hash = self.load("candidates.json")["candidate_bundle_hash"]
        status = self.load("coverage-status.json")
        status["limitations"].append("tampered")
        (self.run_dir / "coverage-status.json").write_text(
            json.dumps(status, indent=2), encoding="utf-8"
        )
        adjudication_path = self.write_json(
            "stale-status-adjudication.json",
            self.adjudication(scope_hash, candidate_hash, include_style=False),
        )
        self.run_tool(
            "compile-ledger", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--input", str(adjudication_path), expected=2,
        )

    def test_coverage_completion_compile_ledger_rejects_incomplete_status(self) -> None:
        scope_hash = self.init_with_coverage()
        paths = self.preflight_core_wave(
            scope_hash, self.candidate_set(scope_hash, include_style=False)
        )
        self.ingest_candidate_paths(paths)
        status = self.load("coverage-status.json")
        status.pop("coverage_status_hash")
        status["status"] = "incomplete"
        status["limitations"].append("required coverage unavailable")
        status["coverage_status_hash"] = reviewctl.canonical_hash(status)
        (self.run_dir / "coverage-status.json").write_text(
            json.dumps(status, indent=2), encoding="utf-8"
        )
        candidates = self.load("candidates.json")
        candidates["coverage"] = status
        generated_at = candidates.pop("generated_at")
        candidates.pop("candidate_bundle_hash")
        candidate_hash = reviewctl.canonical_hash(candidates)
        candidates["candidate_bundle_hash"] = candidate_hash
        candidates["generated_at"] = generated_at
        (self.run_dir / "candidates.json").write_text(
            json.dumps(candidates, indent=2), encoding="utf-8"
        )
        state = self.load("state.json")
        state["hashes"]["coverage_status_hash"] = status["coverage_status_hash"]
        state["hashes"]["candidate_bundle_hash"] = candidate_hash
        (self.run_dir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        adjudication_path = self.write_json(
            "incomplete-status-adjudication.json",
            self.adjudication(scope_hash, candidate_hash, include_style=False),
        )
        self.run_tool(
            "compile-ledger", "--repo-root", str(self.repo), "--run-id", self.run_id,
            "--input", str(adjudication_path), expected=2,
        )

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
        scope_hash = self.init_with_coverage()
        candidates = self.candidate_set(scope_hash, include_style=False)
        candidates["findings"][0]["proposed_resolution"] = "Unsafe candidate suggestion."
        candidate_paths = self.preflight_core_wave(scope_hash, candidates)
        input_args = [item for path in candidate_paths for item in ("--input", str(path))]
        self.run_tool(
            "ingest-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id,
            *input_args,
        )
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
        scope_hash = self.init_with_coverage()
        candidate_paths = self.preflight_core_wave(scope_hash, self.candidate_set(scope_hash))
        input_args = [item for path in candidate_paths for item in ("--input", str(path))]
        self.run_tool(
            "ingest-candidates",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            *input_args,
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

    def test_pre_verification_recovery_refreshes_exact_stale_required_test(self) -> None:
        self.retain_fixed_finding()
        refresh_args = (
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
        self.run_tool(*refresh_args)
        initial_state = self.load("state.json")
        self.assertEqual(initial_state["finding_status"]["F001"]["attempts"], 1)
        self.assertEqual(initial_state["repair_round"], 0)

        (self.repo / "calc.py").write_text(
            "def add(a, b):\n    return a + b\n\n# retained later approved edit\n",
            encoding="utf-8",
        )
        state = self.load("state.json")
        state["expected_workspace_guard_hash"] = reviewctl.workspace_guard(self.repo)["guard_hash"]
        (self.run_dir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        _, stderr = self.run_tool(
            "prepare-verification",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            expected=2,
        )
        self.assertIn("stale after a later workspace edit", stderr)

        self.run_tool(*refresh_args)
        self.run_tool(
            "prepare-verification",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
        )
        summary = self.load("fix-summary.json")
        refreshes = summary["final_test_refresh_results"]["F001"]["unit-regression"]
        self.assertEqual(len(refreshes), 2)
        self.assertEqual(summary["repair_round"], 0)

    def test_pre_verification_recovery_binds_latest_failed_global_evidence(self) -> None:
        global_test = {
            "id": "global-regression",
            "command": "python3 -c 'import sys; sys.exit(1)'",
            "working_directory": ".",
            "required": True,
            "timeout_seconds": 30,
            "purpose": "Provide deterministic failed global evidence.",
        }
        self.retain_fixed_finding(global_tests=[global_test])
        self.run_tool(
            "run-global-test",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--test",
            "global-regression",
            expected=1,
        )
        state = self.load("state.json")
        result = state["global_test_results"]["global-regression"][-1]
        recovery_args = (
            "begin-pre-verification-repair",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--finding",
            "F001",
            "--evidence-kind",
            "global_test",
            "--evidence-id",
            "global-regression",
            "--reason",
            "The failed global regression is causally owned by F001.",
        )
        self.run_tool(*recovery_args, "--evidence-hash", "0" * 64, expected=2)
        self.assertEqual(self.load("state.json")["repair_round"], 0)
        self.run_tool(*recovery_args, "--evidence-hash", result["result_hash"])
        recovered = self.load("state.json")
        self.assertEqual(recovered["finding_status"]["F001"]["status"], "repair_pending")
        self.assertEqual(recovered["repair_round"], 1)
        self.assertEqual(recovered["repair_targets"], ["F001"])
        history = recovered["pre_verification_recovery_history"]
        self.assertEqual(history[-1]["evidence"]["result_hash"], result["result_hash"])
        self.assertTrue((self.run_dir / "pre-verification-recovery/round-1.json").exists())
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
            "def add(a, b):\n    return a + b\n\n# bounded repair round\n",
            encoding="utf-8",
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
            "Retained the bounded repair-round evidence change.",
        )
        self.run_tool(
            "run-global-test",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--test",
            "global-regression",
            expected=1,
        )
        latest = self.load("state.json")["global_test_results"]["global-regression"][-1]
        _, exhausted_stderr = self.run_tool(
            *recovery_args,
            "--evidence-hash",
            latest["result_hash"],
            expected=2,
        )
        self.assertIn("repair-round budget is exhausted", exhausted_stderr)
        self.assertEqual(self.load("state.json")["repair_round"], 1)

    def test_pre_verification_recovery_rejects_current_passing_evidence(self) -> None:
        global_test = {
            "id": "global-regression",
            "command": "python3 -c 'raise SystemExit(0)'",
            "working_directory": ".",
            "required": True,
            "timeout_seconds": 30,
            "purpose": "Provide deterministic passing global evidence.",
        }
        self.retain_fixed_finding(global_tests=[global_test])
        self.run_tool(
            "run-global-test",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--test",
            "global-regression",
        )
        result = self.load("state.json")["global_test_results"]["global-regression"][-1]
        _, stderr = self.run_tool(
            "begin-pre-verification-repair",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--finding",
            "F001",
            "--evidence-kind",
            "global_test",
            "--evidence-id",
            "global-regression",
            "--evidence-hash",
            result["result_hash"],
            "--reason",
            "This must be rejected because no recovery authority exists.",
            expected=2,
        )
        self.assertIn("current and passing", stderr)
        state = self.load("state.json")
        self.assertEqual(state["finding_status"]["F001"]["status"], "fixed")
        self.assertEqual(state["repair_round"], 0)

    def test_pre_verification_recovery_refresh_restores_test_mutation(self) -> None:
        trigger = self.out / "mutate-refresh"
        command = (
            f"if test -f {trigger}; then "
            "printf 'def add(a, b):\\n    return 999\\n' > calc.py; "
            "else grep -Fq 'return a + b' calc.py; fi"
        )
        self.retain_fixed_finding(test_command=command)
        repaired = (self.repo / "calc.py").read_text(encoding="utf-8")
        trigger.write_text("trigger\n", encoding="utf-8")
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
            expected=2,
        )
        self.assertEqual((self.repo / "calc.py").read_text(encoding="utf-8"), repaired)
        result = self.load("state.json")["final_test_refresh_results"]["F001"]["unit-regression"][-1]
        self.assertTrue(result["restored_after_mutation"])
        self.assertEqual(result["changed_paths_by_test"], ["calc.py"])
        self.run_tool(
            "begin-pre-verification-repair",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--finding",
            "F001",
            "--evidence-kind",
            "finding_test",
            "--evidence-finding",
            "F001",
            "--evidence-id",
            "unit-regression",
            "--evidence-hash",
            result["result_hash"],
            "--reason",
            "The mutating required command requires a bounded F001 repair attempt.",
        )
        recovered = self.load("state.json")
        self.assertEqual(recovered["finding_status"]["F001"]["status"], "repair_pending")
        self.assertEqual(
            recovered["pre_verification_recovery_history"][-1]["evidence"]["source"],
            "final_test_refresh",
        )

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
        scope_hash = self.init_with_coverage()
        candidate_paths = self.preflight_core_wave(
            scope_hash, self.empty_candidate_set(scope_hash, "correctness", "correctness")
        )
        input_args = [item for path in candidate_paths for item in ("--input", str(path))]
        self.run_tool(
            "ingest-candidates",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            *input_args,
        )
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
        scope_hash = self.init_with_coverage()
        candidate_paths = self.preflight_core_wave(scope_hash, self.candidate_set(scope_hash))
        scope = self.load("scope.json")
        calc_entry = next(item for item in scope["identity"]["files"] if item["path"] == "calc.py")
        snapshot_rel = calc_entry["comparison_state"]["snapshot_path"]
        (self.run_dir / snapshot_rel).write_text("def add(a, b):\n    return 999\n", encoding="utf-8")
        input_args = [item for path in candidate_paths for item in ("--input", str(path))]
        self.run_tool(
            "ingest-candidates",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            *input_args,
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
