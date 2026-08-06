from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import inspect
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reviewctl.py"
CONTROLLER_1_2_COMPAT = Path(__file__).resolve().parent / "fixtures" / "reviewctl_1_2_compat.py"
CONTROLLER_1_2_COMPAT_SHA256 = "67460c72d04a23758dc94d6d336a6c0884b8b5e3cf4dd4d1d8d544c153abdac2"
CONTROLLER_1_3_COMPAT = Path(__file__).resolve().parent / "fixtures" / "reviewctl_1_3_compat.py"
CONTROLLER_1_3_COMPAT_SHA256 = "9e80034e8dcbfbe31cc576f03ed855f04ce3007d97ac0dbfbc66ad71c47cf28f"
CONTROLLER_1_4_COMPAT = Path(__file__).resolve().parent / "fixtures" / "reviewctl_1_4_compat.py"
CONTROLLER_1_4_COMPAT_SHA256 = "93ddef8c5c712a7426acf4ab0307a4f62824f68a924cc76ad9ddd2f3245b7280"
CONTROLLER_1_5_COMPAT = Path(__file__).resolve().parent / "fixtures" / "reviewctl_1_5_compat.py"
CONTROLLER_1_5_COMPAT_SHA256 = "0e1b9c87c10e990f8d3eb11f747a84504a4b13bbb31a4db159ecf847910c8245"
SPEC = importlib.util.spec_from_file_location("material_reviewctl", SCRIPT)
assert SPEC and SPEC.loader
reviewctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reviewctl)

from obligation_contract import RISK_REQUIREMENTS  # noqa: E402

SIMULTANEOUS_INGEST_HARNESS = r"""
import importlib.util
import sys
import time
from pathlib import Path

script = Path(sys.argv[1])
barrier_directory = Path(sys.argv[2])
worker_id = sys.argv[3]
controller_arguments = sys.argv[4:]
spec = importlib.util.spec_from_file_location(
    f"simultaneous_reviewctl_{worker_id}", script
)
if spec is None or spec.loader is None:
    raise RuntimeError(f"unable to load controller: {script}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original_load_state = module.load_state
load_count = 0

def barrier_load_state(run_dir):
    global load_count
    state = original_load_state(run_dir)
    load_count += 1
    if load_count == 2 and state.get("phase") == module.PHASE_CONTEXT:
        (barrier_directory / f"ready-{worker_id}").write_text("ready\n", encoding="utf-8")
        release = barrier_directory / "release"
        deadline = time.monotonic() + 15.0
        while not release.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("simultaneous ingestion barrier was not released")
            time.sleep(0.005)
    return state

module.load_state = barrier_load_state
raise SystemExit(module.main(controller_arguments))
"""


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

    def make_run_state_v2_with_frozen_1_3_fixture(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(CONTROLLER_1_3_COMPAT),
                "--run-dir",
                str(self.run_dir),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def make_run_state_v3_with_frozen_1_4_fixture(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(CONTROLLER_1_4_COMPAT),
                "--run-dir",
                str(self.run_dir),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def make_run_state_v4_with_frozen_1_5_fixture(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(CONTROLLER_1_5_COMPAT),
                "--run-dir",
                str(self.run_dir),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

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
        risk_codes = {
            code
            for code, present in (
                ("user_selectable_output_paths", output_paths_present),
                ("persisted_config_semantics", persisted_config_present),
            )
            if present
        }
        primary_paths = ["calc.py"]
        scope_path = self.run_dir / "scope.json"
        if scope_path.is_file():
            primary_paths = [
                item["path"] for item in self.load("scope.json")["identity"]["files"]
            ]
        return self._coverage_plan_for_risks(
            scope_hash,
            risk_codes=risk_codes,
            primary_paths=primary_paths,
            context_paths=[],
            omit_lens=omit_lens,
        )

    def coverage_plan_v2(
        self,
        scope_hash: str,
        *,
        primary_paths: list[str] | None = None,
        context_paths: list[str] | None = None,
        risk_code: str | None = "machine_contract_semantics",
    ) -> dict:
        primary_paths = primary_paths or ["calc.py"]
        context_paths = context_paths or []
        return self._coverage_plan_for_risks(
            scope_hash,
            risk_codes=set() if risk_code is None else {risk_code},
            primary_paths=primary_paths,
            context_paths=context_paths,
        )

    def _coverage_plan_for_risks(
        self,
        scope_hash: str,
        *,
        risk_codes: set[str],
        primary_paths: list[str],
        context_paths: list[str],
        omit_lens: str | None = None,
    ) -> dict:
        controlled_risks = {
            "verification_mechanism_semantics",
            "machine_contract_semantics",
            "distribution_contract_integrity",
            "normative_workflow_coherence",
            "user_selectable_output_paths",
            "persisted_config_semantics",
        }
        requirements = {
            "verification_mechanism_semantics": (
                "adversarial_verification",
                {"authoritative_parsing", "decoy_duplicate_resistance", "paired_control"},
                set(),
            ),
            "machine_contract_semantics": (
                "api_config_compatibility",
                {
                    "schema_runtime_parity",
                    "canonical_git_path_language",
                    "required_value_cardinality",
                    "privileged_field_type_exactness",
                },
                set(),
            ),
            "distribution_contract_integrity": (
                "reliability",
                {"manifest_reference_closure", "remove_one_required_entry", "paired_control"},
                set(),
            ),
            "normative_workflow_coherence": (
                "standards_alignment",
                {
                    "normative_sequence",
                    "prerequisite_before_dependent_step",
                    "paired_control",
                    "disabled_mode_dependency_boundary",
                },
                set(),
            ),
            "user_selectable_output_paths": (
                "reliability",
                {
                    "destination_collision",
                    "canonical_filesystem_identity",
                    "runtime_writer_target_inventory",
                    "runtime_target_derivation_parity",
                    "validation_to_mutation_identity_stability",
                    "writer_cleanup_order",
                },
                set(),
            ),
            "persisted_config_semantics": (
                "migration_data_safety",
                {"accepted_shape_and_default", "migration_and_identity"},
                {"api_config_compatibility"},
            ),
        }
        selected = [
            {
                "risk_code": code,
                "rationale": "The changed implementation defines this controlled contract.",
                "evidence_paths": [primary_paths[0]],
            }
            for code in sorted(risk_codes)
        ]
        obligations = []
        assignments = [
            {
                "assignment_id": assignment_id,
                "assignment_kind": "core",
                "lens_id": lens_id,
                "reviewer_id": lens_id,
                "independence_group": "model-a",
                "review_mode": "subagent",
            }
            for assignment_id, lens_id in (
                ("core-correctness", "correctness"),
                ("core-standards", "standards_alignment"),
                ("core-tests", "test_adequacy"),
            )
            if lens_id != omit_lens
        ]
        for risk_code in sorted(risk_codes):
            required_lens, required_checks, supporting_lenses = requirements[risk_code]
            obligation_id = f"obligation-unit-001-{risk_code.replace('_', '-')}"
            obligations.append(
                {
                    "obligation_id": obligation_id,
                    "unit_id": "unit-001",
                    "risk_code": risk_code,
                    "canonical_owner": primary_paths[0],
                    "affected_consumers": context_paths,
                    "evidence_paths": sorted({primary_paths[0], *context_paths}),
                    "required_lens": required_lens,
                    "required_checks": sorted(required_checks),
                }
            )
            if required_lens != omit_lens:
                assignments.append(
                    {
                        "assignment_id": f"assignment-{obligation_id}",
                        "assignment_kind": "obligation",
                        "obligation_id": obligation_id,
                        "unit_id": "unit-001",
                        "risk_code": risk_code,
                        "lens_id": required_lens,
                        "reviewer_id": (
                            "shared-reviewer"
                            if required_lens in {"migration_data_safety", "api_config_compatibility"}
                            else required_lens
                        ),
                        "independence_group": "model-b",
                        "review_mode": "subagent",
                    }
                )
            for lens_id in sorted(supporting_lenses):
                if lens_id == omit_lens:
                    continue
                assignments.append(
                    {
                        "assignment_id": (
                            f"supplemental-unit-001-{risk_code.replace('_', '-')}-{lens_id.replace('_', '-')}"
                        ),
                        "assignment_kind": "supplemental",
                        "unit_id": "unit-001",
                        "risk_code": risk_code,
                        "lens_id": lens_id,
                        "reviewer_id": "shared-reviewer",
                        "independence_group": "model-b",
                        "review_mode": "subagent",
                    }
                )
        unit_paths = sorted({*primary_paths, *context_paths})
        obligations_by_id = {
            item["obligation_id"]: item for item in obligations
        }
        for assignment in assignments:
            if assignment["assignment_kind"] == "obligation":
                obligation = obligations_by_id[assignment["obligation_id"]]
                assignment["required_review_paths"] = sorted(
                    {
                        obligation["canonical_owner"],
                        *obligation["affected_consumers"],
                        *obligation["evidence_paths"],
                    }
                )
                assignment["required_checks"] = obligation["required_checks"]
            else:
                assignment["required_review_paths"] = unit_paths
                assignment["required_checks"] = []
        return {
            "schema_version": "material-review/coverage-plan/v4",
            "scope_hash": scope_hash,
            "workflow_profile": "material_review",
            "depth": "auto",
            "change_units": [
                {
                    "unit_id": "unit-001",
                    "purpose": "Review one coherent changed contract.",
                    "primary_paths": primary_paths,
                    "context_paths": context_paths,
                    "canonical_owner": primary_paths[0],
                    "affected_consumers": [*primary_paths[1:], *context_paths],
                    "risk_codes": sorted(risk_codes),
                    "selected_risk_rationale": selected,
                    "rejected_risk_rationale": [
                        {
                            "risk_code": code,
                            "rationale": "This unit does not alter that controlled boundary.",
                        }
                        for code in sorted(controlled_risks - risk_codes)
                    ],
                    "specialist_decisions": [
                        {
                            "lens_id": lens_id,
                            "decision": "rejected",
                            "basis": "behavior_evidence",
                            "evidence": [
                                f"The fixture behavior does not trigger {lens_id}."
                            ],
                            "scenario_checks": [],
                        }
                        for lens_id in (
                            "security_privacy",
                            "reliability",
                            "api_contract",
                            "migration_deployment",
                            "concurrency",
                            "performance",
                            "documentation",
                            "architecture_simplification",
                        )
                    ],
                }
            ],
            "review_obligations": obligations,
            "assignments": assignments,
        }

    def commit_context_files(self, files: dict[str, bytes]) -> None:
        for relative, data in files.items():
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self.git("add", "--", relative)
        self.git("commit", "-qm", "add context fixtures")

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

    def candidate_set_v3(
        self,
        scope_hash: str,
        coverage_plan_hash: str,
        coverage_context_hash: str,
        assignment: dict,
        *,
        obligation: dict | None = None,
        findings: list[dict] | None = None,
    ) -> dict:
        payload = {
            "schema_version": "material-review/candidate-set/v5",
            "scope_hash": scope_hash,
            "coverage_plan_hash": coverage_plan_hash,
            "coverage_context_hash": coverage_context_hash,
            "assignment_id": assignment["assignment_id"],
            "assignment_kind": assignment["assignment_kind"],
            "lens_id": assignment["lens_id"],
            "reviewer_id": assignment["reviewer_id"],
            "independence_group": assignment["independence_group"],
            "review_mode": assignment["review_mode"],
            "check_results": [],
            "findings": findings or [],
            "coverage": {
                "files_reviewed": assignment["required_review_paths"],
                "areas": [assignment["lens_id"]],
                "limitations": [],
            },
        }
        if assignment["assignment_kind"] == "obligation":
            assert obligation is not None
            payload["obligation_id"] = obligation["obligation_id"]
            payload["coverage"]["files_reviewed"] = sorted(
                set(obligation["evidence_paths"])
            )
            payload["check_results"] = [
                {
                    "check_code": check_code,
                    "outcome": "pass",
                    "evidence_items": [
                        {
                            "item_code": item["item_code"],
                            "evidence": [
                                f"Observed {item['item_code']} against frozen evidence."
                            ],
                            "evidence_paths": assignment["required_review_paths"],
                        }
                        for item in sorted(
                            RISK_REQUIREMENTS[obligation["risk_code"]][
                                "check_contracts"
                            ][check_code]["evidence_items"],
                            key=lambda item: item["item_code"],
                        )
                    ],
                    "finding_local_ids": [],
                }
                for check_code in obligation["required_checks"]
            ]
        elif assignment["assignment_kind"] == "specialist":
            for field in ("unit_ids", "primary_paths", "context_paths"):
                payload[field] = assignment[field]
            payload["coverage"]["files_reviewed"] = assignment[
                "required_review_paths"
            ]
            payload["check_results"] = [
                {
                    "check_code": check_code,
                    "outcome": "pass",
                    "evidence": [
                        f"Observed {check_code} against frozen specialist evidence."
                    ],
                    "evidence_paths": assignment["required_review_paths"],
                    "finding_local_ids": [],
                }
                for check_code in assignment["required_checks"]
            ]
        return payload

    def candidate_paths_for_coverage_v3(
        self,
        scope_hash: str,
        *,
        primary_candidate: dict | None = None,
        omit_lens: str | None = None,
    ) -> list[Path]:
        plan = self.load("coverage-plan.json")
        obligations = {
            item["obligation_id"]: item for item in plan["review_obligations"]
        }
        paths = []
        for assignment in plan["assignments"]:
            if assignment["lens_id"] == omit_lens:
                continue
            obligation = obligations.get(assignment.get("obligation_id"))
            findings = []
            if assignment["assignment_id"] == "core-correctness":
                findings = copy.deepcopy(
                    (primary_candidate or self.candidate_set(scope_hash))["findings"]
                )
            payload = self.candidate_set_v3(
                scope_hash,
                plan["coverage_plan_hash"],
                plan["coverage_context_hash"],
                assignment,
                obligation=obligation,
                findings=findings,
            )
            if assignment["assignment_kind"] == "core":
                payload["coverage"]["files_reviewed"] = assignment[
                    "required_review_paths"
                ]
            paths.append(
                self.write_json(f"candidate-{assignment['assignment_id']}.json", payload)
            )
        return paths

    def init_with_recorded_coverage(self) -> str:
        scope_hash = self.init()
        plan_path = self.write_json("coverage-input.json", self.coverage_plan(scope_hash))
        self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(plan_path))
        return scope_hash

    def init_with_recorded_coverage_v2(self, plan: dict | None = None) -> str:
        scope_hash = self.init()
        plan = plan or self.coverage_plan_v2(scope_hash)
        plan_path = self.write_json(f"coverage-v2-{self.run_id}.json", plan)
        self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(plan_path),
        )
        return scope_hash

    def candidate_paths_for_coverage(
        self,
        scope_hash: str,
        *,
        primary_candidate: dict | None = None,
        omit_lens: str | None = None,
    ) -> list[Path]:
        return self.candidate_paths_for_coverage_v3(
            scope_hash,
            primary_candidate=primary_candidate,
            omit_lens=omit_lens,
        )

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
        test_timeout_seconds: int = 30,
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
                            "timeout_seconds": test_timeout_seconds,
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
        test_timeout_seconds: int = 30,
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
            test_timeout_seconds=test_timeout_seconds,
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
        test_timeout_seconds: int = 30,
    ) -> tuple[str, dict]:
        scope_hash, plan = self.approve_and_plan(
            test_command=test_command,
            test_timeout_seconds=test_timeout_seconds,
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

    def test_boundary_violation_is_rejected_and_manual_rollback_preserves_it(self) -> None:
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
        attempted_fix = "def add(a, b):\n    return a + b\n"
        unapproved_change = "raise RuntimeError('unapproved')\n"
        (self.repo / "calc.py").write_text(attempted_fix, encoding="utf-8")
        (self.repo / "test_calc.py").write_text(
            unapproved_change, encoding="utf-8"
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
            "Bad attempt.",
            expected=2,
        )
        _, stderr = self.run_tool(
            "rollback-finding",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--finding",
            "F001",
            "--reason",
            "Unapproved test file changed.",
            expected=2,
        )
        self.assertIn("not authorized for automatic recovery", stderr)
        self.assertEqual(
            (self.repo / "calc.py").read_text(encoding="utf-8"), attempted_fix
        )
        self.assertEqual(
            (self.repo / "test_calc.py").read_text(encoding="utf-8"),
            unapproved_change,
        )
        active = self.load("state.json")["active_finding"]
        self.assertEqual(active["finding_id"], "F001")
        checkpoint_dir = self.run_dir / active["checkpoint"]
        self.assertTrue((checkpoint_dir / "recovery-conflict.json").is_file())

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
        self.assertEqual(
            (self.repo / "calc.py").read_text(encoding="utf-8"),
            "def add(a, b):\n    return 999\n",
        )
        checkpoint = (
            self.run_dir
            / "checkpoints/tests/F001/unit-regression/run-1/recovery-conflict.json"
        )
        self.assertTrue(checkpoint.is_file())
        self.assertNotIn(
            "unit-regression",
            self.load("state.json")["active_finding"]["test_results"],
        )

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
        self.assertEqual(
            (self.repo / "calc.py").read_text(encoding="utf-8"),
            "def add(a, b):\n    return 999\n",
        )
        checkpoint = (
            self.run_dir
            / "checkpoints/global-tests/global-regression/run-1/recovery-conflict.json"
        )
        self.assertTrue(checkpoint.is_file())
        self.assertEqual(self.load("state.json")["global_test_results"], {})

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

        self.assertIn("human recovery is required", stderr)
        self.assertNotEqual((self.repo / "calc.py").read_bytes(), final_source)
        state_after = self.load("state.json")
        self.assertEqual(state_after["finding_status"]["F001"]["history"], history_before)
        self.assertEqual(
            state_after["finding_status"]["F001"]["attempts"],
            state_before["finding_status"]["F001"]["attempts"],
        )
        result = state_after["finding_test_refresh_results"]["F001"]["unit-regression"][-1]
        self.assertFalse(result["restored_after_mutation"])
        self.assertFalse(result["recovery_completed"])
        self.assertTrue(result["human_recovery_required"])
        self.assertEqual(result["changed_paths_by_test"], ["calc.py"])

    def test_final_refresh_recovers_captured_head_refs_index_and_workspace_only(self) -> None:
        commit_command = (
            "if grep -Fq '# later shared repair' calc.py; then "
            "git add calc.py && git commit -qm refresh-created-commit; "
            "else grep -Fq 'return a + b' calc.py; fi"
        )
        self.reach_fixed_stale_final_state(test_command=commit_command)
        attachment_before = reviewctl.current_head_attachment(self.repo)
        refs_before = reviewctl.local_head_refs(self.repo)
        guard_before = reviewctl.workspace_guard(self.repo)
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
        self.assertIn("mutated the workspace and was restored", stderr)
        self.assertEqual(reviewctl.current_head_attachment(self.repo), attachment_before)
        self.assertEqual(reviewctl.local_head_refs(self.repo), refs_before)
        self.assertEqual(reviewctl.workspace_guard(self.repo), guard_before)
        state = self.load("state.json")
        result = state["finding_test_refresh_results"]["F001"]["unit-regression"][-1]
        self.assertTrue(result["recovery_attempted"])
        self.assertTrue(result["recovery_completed"])
        self.assertTrue(result["restored_after_mutation"])
        self.assertFalse(result["human_recovery_required"])
        self.assertIsNone(result["recovery_error"])
        self.assertIn("HEAD", result["control_mutations_by_test"])
        self.assertIn("refs namespace", result["control_mutations_by_test"])
        self.assertEqual(state["finding_status"]["F001"]["history"], history_before)
        self.assertEqual(
            state["finding_status"]["F001"]["attempts"],
            state_before["finding_status"]["F001"]["attempts"],
        )
        self.assertIsNone(state["active_finding"])

        self.tearDown()
        self.setUp()
        for mutation in ("branch-switch", "detached-switch", "index-only"):
            with self.subTest(mutation=mutation):
                checkpoint_dir = self.root / f"checkpoint-{mutation}"
                checkpoint = reviewctl.create_checkpoint(
                    self.repo, checkpoint_dir, ["calc.py"]
                )
                if mutation == "branch-switch":
                    self.git("switch", "-qc", "refresh-created-branch")
                elif mutation == "detached-switch":
                    self.git("switch", "-q", "--detach", "HEAD")
                else:
                    self.git("add", "calc.py")
                expected_post = reviewctl.repository_authority(self.repo)
                restored_authority = reviewctl.restore_checkpoint(
                    self.repo,
                    checkpoint_dir,
                    expected_post=expected_post,
                )
                restored = restored_authority["identity"]["workspace_guard"]
                self.assertEqual(
                    reviewctl.current_head_attachment(self.repo),
                    checkpoint["head_attachment"],
                )
                self.assertEqual(
                    reviewctl.local_head_refs(self.repo), checkpoint["local_head_refs"]
                )
                self.assertEqual(
                    restored["guard_hash"], checkpoint["workspace_guard"]["guard_hash"]
                )
                self.tearDown()
                self.setUp()

        saved_branch = reviewctl.current_branch(self.repo)
        self.git("switch", "-q", "--detach", "HEAD")
        detached_checkpoint_dir = self.root / "checkpoint-saved-detached"
        detached_checkpoint = reviewctl.create_checkpoint(
            self.repo, detached_checkpoint_dir, ["calc.py"]
        )
        self.git("switch", "-q", saved_branch)
        reviewctl.restore_checkpoint(
            self.repo,
            detached_checkpoint_dir,
            expected_post=reviewctl.repository_authority(self.repo),
        )
        self.assertIsNone(reviewctl.current_head_attachment(self.repo))
        self.assertEqual(
            reviewctl.resolve_commit(self.repo, "HEAD"), detached_checkpoint["head_sha"]
        )

        self.tearDown()
        self.setUp()
        corrupted_dir = self.root / "checkpoint-corrupt"
        reviewctl.create_checkpoint(self.repo, corrupted_dir, ["calc.py"])
        corrupted_path = corrupted_dir / "checkpoint.json"
        corrupted = json.loads(corrupted_path.read_text(encoding="utf-8"))
        corrupted["head_attachment"] = "refs/heads/forged"
        corrupted_path.write_text(json.dumps(corrupted), encoding="utf-8")
        with self.assertRaisesRegex(reviewctl.ReviewError, "embedded hash"):
            reviewctl.restore_checkpoint(
                self.repo,
                corrupted_dir,
                expected_post=reviewctl.repository_authority(self.repo),
            )

        self.tearDown()
        self.setUp()
        conflict_dir = self.root / "checkpoint-conflict"
        reviewctl.create_checkpoint(self.repo, conflict_dir, ["calc.py"])
        original_run_process = reviewctl.run_process
        self.git("add", "calc.py")
        self.git("commit", "-qm", "test mutation")
        expected_post = reviewctl.repository_authority(self.repo)
        injected = False

        def inject_ref_conflict(arguments, **kwargs):
            nonlocal injected
            if list(arguments[:3]) == ["git", "update-ref", "--stdin"] and not injected:
                injected = True
                original_run_process(
                    ["git", "commit", "--allow-empty", "-qm", "concurrent mutation"],
                    cwd=self.repo,
                )
            return original_run_process(arguments, **kwargs)

        with mock.patch.object(reviewctl, "run_process", side_effect=inject_ref_conflict):
            with self.assertRaises(reviewctl.ReviewError):
                reviewctl.restore_checkpoint(
                    self.repo,
                    conflict_dir,
                    expected_post=expected_post,
                )
        self.assertTrue(injected)

        self.tearDown()
        self.setUp()
        self.reach_fixed_stale_final_state(test_command=commit_command)
        with mock.patch.object(
            reviewctl,
            "restore_checkpoint_v4",
            side_effect=reviewctl.ReviewError("compare-and-swap conflict"),
        ):
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
        self.assertIn("human recovery is required", stderr)
        state = self.load("state.json")
        incomplete = state["finding_test_refresh_results"]["F001"]["unit-regression"][-1]
        self.assertTrue(incomplete["recovery_attempted"])
        self.assertFalse(incomplete["recovery_completed"])
        self.assertFalse(incomplete["restored_after_mutation"])
        self.assertTrue(incomplete["human_recovery_required"])
        self.assertEqual(incomplete["recovery_error"], "compare-and-swap conflict")

    def test_final_refresh_nonzero_timeout_and_ordered_success_are_causal(self) -> None:
        sentinel = self.out / "refresh-pass"
        sentinel.write_text("pass\n", encoding="utf-8")
        command = f"test -f {shlex.quote(str(sentinel))}"
        self.reach_fixed_stale_final_state(test_command=command)
        state_before = self.load("state.json")
        history_before = copy.deepcopy(state_before["finding_status"]["F001"]["history"])
        sentinel.unlink()

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
            expected=1,
        )
        self.assertEqual(stderr, "")
        state = self.load("state.json")
        failed = state["finding_test_refresh_results"]["F001"]["unit-regression"][-1]
        self.assertEqual(failed["exit_code"], 1)
        self.assertFalse(failed["timed_out"])
        self.assertEqual(failed["changed_paths_by_test"], [])
        self.assertEqual(failed["control_mutations_by_test"], [])
        self.assertFalse(failed["restored_after_mutation"])
        self.assertEqual(state["finding_status"]["F001"]["history"], history_before)
        self.assertEqual(
            state["finding_status"]["F001"]["attempts"],
            state_before["finding_status"]["F001"]["attempts"],
        )
        self.assertIsNone(state["active_finding"])
        _, prepare_error = self.run_tool(
            "prepare-verification",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            expected=2,
        )
        self.assertIn("F001:unit-regression failed", prepare_error)

        sentinel.write_text("pass\n", encoding="utf-8")
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
        state = self.load("state.json")
        attempt = state["finding_status"]["F001"]["history"][-1]
        latest = reviewctl.latest_finding_test_evidence(
            state,
            finding_id="F001",
            test_id="unit-regression",
            fixed_attempt=attempt,
        )
        self.assertIsNotNone(latest)
        self.assertEqual(latest["exit_code"], 0)

        sentinel.unlink()
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
            expected=1,
        )
        state = self.load("state.json")
        latest = reviewctl.latest_finding_test_evidence(
            state,
            finding_id="F001",
            test_id="unit-regression",
            fixed_attempt=state["finding_status"]["F001"]["history"][-1],
        )
        self.assertIsNotNone(latest)
        self.assertEqual(latest["exit_code"], 1)

        self.tearDown()
        self.setUp()
        timeout_sentinel = self.out / "refresh-timeout-pass"
        timeout_sentinel.write_text("pass\n", encoding="utf-8")
        timeout_command = (
            f"if test -f {shlex.quote(str(timeout_sentinel))}; "
            "then true; else sleep 5; fi"
        )
        self.reach_fixed_stale_final_state(
            test_command=timeout_command,
            test_timeout_seconds=1,
        )
        timeout_sentinel.unlink()
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
            expected=1,
        )
        self.assertEqual(stderr, "")
        state = self.load("state.json")
        timed_out = state["finding_test_refresh_results"]["F001"]["unit-regression"][-1]
        self.assertTrue(timed_out["timed_out"])
        self.assertIsNone(timed_out["exit_code"])
        self.assertEqual(timed_out["changed_paths_by_test"], [])
        self.assertEqual(timed_out["control_mutations_by_test"], [])
        self.assertFalse(timed_out["restored_after_mutation"])
        _, prepare_error = self.run_tool(
            "prepare-verification",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            expected=2,
        )
        self.assertIn("F001:unit-regression failed", prepare_error)

    def test_final_test_evidence_is_bound_to_newest_retained_attempt(self) -> None:
        attempt_n = {
            "attempt_hash": "a" * 64,
            "tests": {"unit-regression": [{"exit_code": 0, "source": "attempt-n"}]},
        }
        attempt_n_plus_one = {
            "attempt_hash": "b" * 64,
            "tests": {
                "unit-regression": [
                    {"exit_code": 0, "source": "attempt-n-plus-one"}
                ]
            },
        }
        state = {
            "finding_test_refresh_results": {
                "F001": {
                    "unit-regression": [
                        {
                            "fixed_attempt_hash": attempt_n["attempt_hash"],
                            "exit_code": 0,
                            "source": "stale-refresh",
                        }
                    ]
                }
            }
        }
        selected = reviewctl.latest_finding_test_evidence(
            state,
            finding_id="F001",
            test_id="unit-regression",
            fixed_attempt=attempt_n_plus_one,
        )
        self.assertEqual(selected["source"], "attempt-n-plus-one")

        state["finding_test_refresh_results"]["F001"]["unit-regression"].extend(
            [
                {
                    "fixed_attempt_hash": attempt_n_plus_one["attempt_hash"],
                    "exit_code": 0,
                    "source": "current-refresh-pass",
                },
                {
                    "fixed_attempt_hash": attempt_n["attempt_hash"],
                    "exit_code": 0,
                    "source": "later-stale-refresh",
                },
            ]
        )
        selected = reviewctl.latest_finding_test_evidence(
            state,
            finding_id="F001",
            test_id="unit-regression",
            fixed_attempt=attempt_n_plus_one,
        )
        self.assertEqual(selected["source"], "current-refresh-pass")

        state["finding_test_refresh_results"]["F001"]["unit-regression"].append(
            {
                "fixed_attempt_hash": attempt_n_plus_one["attempt_hash"],
                "exit_code": 1,
                "source": "current-refresh-fail",
            }
        )
        selected = reviewctl.latest_finding_test_evidence(
            state,
            finding_id="F001",
            test_id="unit-regression",
            fixed_attempt=attempt_n_plus_one,
        )
        self.assertEqual(selected["source"], "current-refresh-fail")
        self.assertEqual(selected["exit_code"], 1)

        no_current_evidence = {
            "attempt_hash": "c" * 64,
            "tests": {"unit-regression": []},
        }
        self.assertIsNone(
            reviewctl.latest_finding_test_evidence(
                state,
                finding_id="F001",
                test_id="unit-regression",
                fixed_attempt=no_current_evidence,
            )
        )

        malformed = {"finding_test_refresh_results": {"F001": []}}
        with self.assertRaisesRegex(reviewctl.ReviewError, "must be an object"):
            reviewctl.latest_finding_test_evidence(
                malformed,
                finding_id="F001",
                test_id="unit-regression",
                fixed_attempt=attempt_n_plus_one,
            )

    def test_marked_state_v1_run_is_restart_only_without_migration(self) -> None:
        self.reach_fixed_stale_final_state()
        state_path = self.run_dir / "state.json"
        state = self.load("state.json")
        state["schema_version"] = "material-review/state/v1"
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        state_before = state_path.read_bytes()

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
        self.assertIn("Run predates required coverage; start a new run.", stderr)
        self.assertEqual(state_path.read_bytes(), state_before)

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
        authority_with_replacement = reviewctl.repository_authority(self.repo)
        with self.assertRaisesRegex(
            reviewctl.ReviewError, "existing-path replacement or deletion"
        ):
            reviewctl.restore_checkpoint(
                self.repo,
                checkpoint,
                expected_post=authority_with_replacement,
            )
        self.assertEqual(reviewctl.repository_authority(self.repo), authority_with_replacement)
        self.assertFalse(link.is_symlink())

        link.unlink()
        reviewctl.restore_checkpoint(
            self.repo,
            checkpoint,
            expected_post=reviewctl.repository_authority(self.repo),
        )
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
        candidate_set = {"findings": []}
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
            for assignment in plan["assignments"]:
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
            obligations = {
                item["obligation_id"]: item
                for item in recorded_plan["review_obligations"]
            }
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
            for assignment in recorded_plan["assignments"]:
                payload = self.candidate_set_v3(
                    scope_hash,
                    recorded_plan["coverage_plan_hash"],
                    recorded_plan["coverage_context_hash"],
                    assignment,
                    obligation=obligations.get(assignment.get("obligation_id")),
                )
                if assignment["assignment_kind"] == "core":
                    payload["coverage"]["files_reviewed"] = assignment[
                        "required_review_paths"
                    ]
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
                        f"{order_name}-{assignment['assignment_id']}.json",
                        payload,
                    )
                )
            if reverse_inputs:
                candidate_paths.reverse()

            self.ingest_candidate_paths(candidate_paths)

            bundle = self.load("candidates.json")
            self.assertEqual(
                bundle["schema_version"],
                "material-review/candidates-normalized/v5",
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
                {reviewer_set["assignment_id"] for reviewer_set in bundle["reviewer_sets"]},
                {assignment["assignment_id"] for assignment in recorded_plan["assignments"]},
            )
            self.assertEqual(len(bundle["reviewer_sets"]), len(recorded_plan["assignments"]))
            rendered_candidates = (self.run_dir / "candidates.md").read_text(encoding="utf-8")
            self.assertIn("candidate_records: `9`", rendered_candidates)
            completed_atomic_checks = sum(
                len(reviewer_set["check_results"])
                for reviewer_set in bundle["reviewer_sets"]
            )
            self.assertIn(
                f"completed_atomic_checks: `{completed_atomic_checks}`",
                rendered_candidates,
            )
            self.assertNotIn("Candidates accepted", rendered_candidates)
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
                    "workflow profile: expected material-review/candidates-normalized/v5, "
                    "got material-review/candidates-normalized/v1"
                    if name == "old-normalized-version"
                    else "normalized candidates.candidates[0] identity does not match its validated assignment source"
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

    def test_artifact_identity_stable_default_and_custom_roots(self) -> None:
        scope_hash = self.init()
        self.assertEqual(self.load("state.json")["scope_hash"], scope_hash)
        authority = reviewctl.RunArtifactAuthority(self.run_dir)
        with reviewctl.active_artifact_authority(authority):
            reviewctl.atomic_write_bytes(self.run_dir / "identity.bin", b"bytes")
            reviewctl.atomic_write_text(
                self.run_dir / "nested" / "identity.txt",
                "line\r\n",
            )
            reviewctl.atomic_write_json(
                self.run_dir / "nested" / "identity.json",
                {"value": 1},
            )
            self.assertEqual(
                reviewctl.artifact_read_bytes(self.run_dir / "identity.bin"),
                b"bytes",
            )
            self.assertEqual(
                reviewctl.artifact_read_text(
                    self.run_dir / "nested" / "identity.txt"
                ),
                "line\n",
            )
            self.assertEqual(
                reviewctl.load_json(self.run_dir / "nested" / "identity.json"),
                {"value": 1},
            )

        custom_root = self.out / "custom-artifacts"
        custom_run_id = "custom-identity-run"
        self.run_tool(
            "init",
            "--repo-root",
            str(self.repo),
            "--scope",
            "uncommitted",
            "--run-id",
            custom_run_id,
            "--artifact-root",
            str(custom_root),
        )
        custom_state = json.loads(
            (custom_root / "runs" / custom_run_id / "state.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(custom_state["phase"], "CONTEXT_FROZEN")
        self.run_tool(
            "check-scope",
            "--repo-root",
            str(self.repo),
            "--run-id",
            custom_run_id,
            "--artifact-root",
            str(custom_root),
        )

    def test_artifact_identity_rebind_never_writes_replacement_target(self) -> None:
        def exercise(label: str, artifact_root: Path | None) -> None:
            self.run_id = f"identity-rebind-{label}"
            init_arguments = [
                "init",
                "--repo-root",
                str(self.repo),
                "--scope",
                "uncommitted",
                "--run-id",
                self.run_id,
            ]
            if artifact_root is not None:
                init_arguments.extend(["--artifact-root", str(artifact_root)])
            self.run_tool(*init_arguments)
            runs_root = (
                artifact_root / "runs"
                if artifact_root is not None
                else self.repo / ".git" / "material-code-review" / "runs"
            )
            run_dir = runs_root / self.run_id
            state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            plan_path = self.write_json(
                f"coverage-rebind-{label}.json",
                self.coverage_plan(state["scope_hash"]),
            )
            moved = runs_root / f"{self.run_id}-moved"
            replacement = self.out / f"replacement-{label}"
            replacement.mkdir()
            sentinel = replacement / "coverage-context.json"
            sentinel.write_bytes(b"replacement sentinel")
            triggered = False

            def rebind_after_temp(stage, _authority, path):
                nonlocal triggered
                if (
                    stage == "after_temp_created"
                    and path.name == "coverage-context.json"
                    and not triggered
                ):
                    triggered = True
                    os.rename(run_dir, moved)
                    run_dir.symlink_to(replacement, target_is_directory=True)

            reviewctl._ARTIFACT_TEST_HOOK = rebind_after_temp
            try:
                command = [
                    "record-coverage",
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    "--input",
                    str(plan_path),
                ]
                if artifact_root is not None:
                    command.extend(["--artifact-root", str(artifact_root)])
                _, stderr = self.run_tool(*command, expected=2)
            finally:
                reviewctl._ARTIFACT_TEST_HOOK = None

            self.assertTrue(triggered)
            self.assertIn("retained directory identity", stderr)
            self.assertEqual(sentinel.read_bytes(), b"replacement sentinel")
            self.assertEqual(sorted(path.name for path in replacement.iterdir()), [sentinel.name])
            moved_state = json.loads((moved / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(moved_state["phase"], "CONTEXT_FROZEN")
            self.assertFalse((moved / "coverage-context.json").exists())

        exercise("default", None)
        exercise("custom", self.out / "custom-rebind-artifacts")

    def test_artifact_identity_boundaries_cover_temp_and_nested_rebinds(self) -> None:
        for stage in ("before_temp_created", "after_temp_created"):
            with self.subTest(stage=stage):
                root = self.out / f"authority-{stage}"
                moved = self.out / f"authority-{stage}-moved"
                replacement = self.out / f"authority-{stage}-replacement"
                replacement.mkdir()
                sentinel = replacement / "state.json"
                sentinel.write_bytes(b"sentinel")
                authority = reviewctl.RunArtifactAuthority(root, create=True)
                triggered = False

                def rebind(boundary, _authority, _path):
                    nonlocal triggered
                    if boundary == stage and not triggered:
                        triggered = True
                        os.rename(root, moved)
                        root.symlink_to(replacement, target_is_directory=True)

                reviewctl._ARTIFACT_TEST_HOOK = rebind
                try:
                    with reviewctl.active_artifact_authority(authority):
                        with self.assertRaisesRegex(
                            reviewctl.ReviewError,
                            "retained directory identity|rebound",
                        ):
                            reviewctl.atomic_write_json(
                                root / "state.json", {"phase": "changed"}
                            )
                finally:
                    reviewctl._ARTIFACT_TEST_HOOK = None
                self.assertTrue(triggered)
                self.assertEqual(sentinel.read_bytes(), b"sentinel")
                self.assertFalse(any(path.name.endswith(".tmp") for path in moved.iterdir()))

        root = self.out / "nested-authority"
        replacement = self.out / "nested-replacement"
        replacement.mkdir()
        sentinel = replacement / "gate.json"
        sentinel.write_bytes(b"nested sentinel")
        moved = root / "gates-moved"
        authority = reviewctl.RunArtifactAuthority(root, create=True)
        with reviewctl.active_artifact_authority(authority):
            reviewctl.atomic_write_json(root / "gates" / "gate.json", {"value": 1})

            def rebind_nested(stage, _authority, path):
                if stage == "after_temp_created" and path.name == "gate.json":
                    os.rename(root / "gates", moved)
                    (root / "gates").symlink_to(
                        replacement, target_is_directory=True
                    )

            reviewctl._ARTIFACT_TEST_HOOK = rebind_nested
            try:
                with self.assertRaisesRegex(
                    reviewctl.ReviewError,
                    "descendant|rebound",
                ):
                    reviewctl.atomic_write_json(
                        root / "gates" / "gate.json", {"value": 2}
                    )
            finally:
                reviewctl._ARTIFACT_TEST_HOOK = None
        self.assertEqual(sentinel.read_bytes(), b"nested sentinel")
        self.assertEqual(
            json.loads((moved / "gate.json").read_text(encoding="utf-8")),
            {"value": 1},
        )

    def test_artifact_identity_rejects_initial_symlink_and_missing_capability(self) -> None:
        artifact_root = self.out / "initial-symlink-artifacts"
        runs_root = artifact_root / "runs"
        runs_root.mkdir(parents=True)
        replacement = self.out / "initial-symlink-target"
        replacement.mkdir()
        run_id = "initial-symlink-run"
        (runs_root / run_id).symlink_to(replacement, target_is_directory=True)
        self.run_tool(
            "init",
            "--repo-root",
            str(self.repo),
            "--scope",
            "uncommitted",
            "--run-id",
            run_id,
            "--artifact-root",
            str(artifact_root),
            expected=2,
        )
        self.assertEqual(list(replacement.iterdir()), [])

        unavailable_root = self.out / "unavailable-artifacts"
        backend_class = (
            reviewctl._WindowsArtifactBackend
            if os.name == "nt"
            else reviewctl._PosixArtifactBackend
        )
        with mock.patch.object(
            backend_class,
            "__init__",
            side_effect=reviewctl.ReviewError("forced capability absence"),
        ):
            _, stderr = self.run_tool(
                "init",
                "--repo-root",
                str(self.repo),
                "--scope",
                "uncommitted",
                "--run-id",
                "unavailable-run",
                "--artifact-root",
                str(unavailable_root),
                expected=2,
            )
        self.assertIn("forced capability absence", stderr)
        self.assertFalse(unavailable_root.exists())

    def test_artifact_identity_windows_api_contract_uses_relative_handles(self) -> None:
        import ctypes

        class FakeFunction:
            def __init__(self, callback=None, return_value=1):
                self.callback = callback
                self.return_value = return_value
                self.calls = []
                self.argtypes = None
                self.restype = None

            def __call__(self, *arguments):
                self.calls.append(arguments)
                if self.callback is not None:
                    return self.callback(*arguments)
                return self.return_value

        def create_file(handle_pointer, *_arguments):
            handle_pointer._obj.value = 321
            return 0

        def file_information(_handle, _information_class, info_pointer, _size):
            info_pointer._obj.FileAttributes = 0
            return 1

        ntcreate = FakeFunction(create_file)
        rtl_status = FakeFunction(return_value=2)
        query_directory = FakeFunction(return_value=reviewctl._WindowsArtifactBackend.STATUS_NO_MORE_FILES)
        ntdll = mock.Mock(
            NtCreateFile=ntcreate,
            RtlNtStatusToDosError=rtl_status,
            NtQueryDirectoryFile=query_directory,
        )
        get_information = FakeFunction(file_information)
        set_information = FakeFunction(return_value=1)
        kernel32 = mock.Mock(
            CreateFileW=FakeFunction(return_value=321),
            GetFileInformationByHandleEx=get_information,
            SetFileInformationByHandle=set_information,
            CloseHandle=FakeFunction(return_value=1),
            FlushFileBuffers=FakeFunction(return_value=1),
        )

        def load_library(name, **_keywords):
            return ntdll if name == "ntdll" else kernel32

        with mock.patch.object(reviewctl.os, "name", "nt"), mock.patch.object(
            ctypes, "WinDLL", create=True, side_effect=load_library
        ):
            backend = reviewctl._WindowsArtifactBackend()
            handle = backend._open_relative(
                456,
                "child.json",
                directory=False,
                disposition=backend.FILE_OPEN,
                access=backend.FILE_READ_DATA,
            )
        self.assertEqual(handle, 321)
        object_attributes = ntcreate.calls[-1][2]._obj
        self.assertEqual(object_attributes.RootDirectory, 456)
        self.assertTrue(ntcreate.calls[-1][8] & backend.FILE_OPEN_REPARSE_POINT)

        fake_msvcrt = mock.Mock()
        fake_msvcrt.get_osfhandle.return_value = 789
        with mock.patch.dict(sys.modules, {"msvcrt": fake_msvcrt}):
            backend.replace_temporary(
                456,
                reviewctl._ArtifactTemporary("temporary", 99),
                "state.json",
            )
        rename_arguments = set_information.calls[-1]
        rename_buffer = rename_arguments[2]
        header = backend.FileRenameHeader.from_buffer(rename_buffer)
        self.assertEqual(header.ReplaceIfExists, 1)
        self.assertEqual(header.RootDirectory, 456)
        name_offset = ctypes.sizeof(backend.FileRenameHeader)
        encoded_name = bytes(rename_buffer)[
            name_offset : name_offset + header.FileNameLength
        ]
        self.assertEqual(encoded_name.decode("utf-16-le"), "state.json")
        with self.assertRaises(FileNotFoundError):
            backend._raise_status(-1, "injected missing entry")

    def test_artifact_identity_preserves_candidate_write_once_contract(self) -> None:
        self.test_candidate_ingestion_is_write_once_and_idempotent()

    def test_artifact_identity_preserves_gate_checkpoint_completion_contract(self) -> None:
        self.test_empty_material_set_requires_explicit_gate_and_completes()

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
            reviewctl.restore_checkpoint(
                self.repo,
                checkpoint,
                expected_post=reviewctl.repository_authority(self.repo),
            )
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

    def test_coverage_plan_records_exhaustive_unit_risk_decisions(self) -> None:
        scope_hash = self.init()
        path = self.write_json("coverage-input.json", self.coverage_plan(scope_hash))
        self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path))
        state = self.load("state.json")
        artifact = self.load("coverage-plan.json")
        self.assertEqual(state["phase"], "CONTEXT_FROZEN")
        self.assertEqual(state["hashes"]["coverage_plan_hash"], artifact["coverage_plan_hash"])
        unit = artifact["change_units"][0]
        selected = {item["risk_code"] for item in unit["selected_risk_rationale"]}
        rejected = {item["risk_code"] for item in unit["rejected_risk_rationale"]}
        self.assertEqual(selected, set(unit["risk_codes"]))
        self.assertEqual(
            selected | rejected,
            {
                "verification_mechanism_semantics",
                "machine_contract_semantics",
                "distribution_contract_integrity",
                "normative_workflow_coherence",
                "user_selectable_output_paths",
                "persisted_config_semantics",
            },
        )
        self.assertFalse(selected & rejected)
        self.assertEqual(
            state["hashes"]["coverage_context_hash"],
            artifact["coverage_context_hash"],
        )

    def test_record_coverage_snapshots_unchanged_tracked_context(self) -> None:
        self.commit_context_files({"owner.py": b"OWNER = 'canonical'\n"})
        scope_hash = self.init()
        plan = self.coverage_plan_v2(scope_hash, context_paths=["owner.py"])
        plan_path = self.write_json("coverage-v2-with-context.json", plan)

        self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(plan_path),
        )

        context = self.load("coverage-context.json")
        self.assertEqual(context["schema_version"], "material-review/coverage-context/v1")
        self.assertEqual(context["sources"][0]["path"], "owner.py")
        self.assertEqual(
            context["sources"][0]["sha256"],
            hashlib.sha256(b"OWNER = 'canonical'\n").hexdigest(),
        )
        self.assertTrue((self.run_dir / context["sources"][0]["snapshot_path"]).is_file())
        state = self.load("state.json")
        self.assertEqual(
            state["hashes"]["coverage_context_hash"],
            context["coverage_context_hash"],
        )

    def test_changed_paths_must_form_exact_unit_partition(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan_v2(scope_hash, primary_paths=["test_calc.py"])
        plan_path = self.write_json("coverage-v2-wrong-partition.json", plan)
        _, stderr = self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(plan_path),
            expected=2,
        )
        self.assertIn("exact primary partition", stderr)
        self.assertFalse((self.run_dir / "coverage-plan.json").exists())
        self.assertFalse((self.run_dir / "coverage-context.json").exists())

    def test_context_snapshot_limits_fail_closed(self) -> None:
        context_files = {f"context/{index:02d}.txt": b"x\n" for index in range(33)}
        context_files["oversized.txt"] = b"x" * (2 * 1024 * 1024 + 1)
        self.commit_context_files(context_files)
        scope_hash = self.init()

        too_many = self.coverage_plan_v2(
            scope_hash,
            context_paths=sorted(path for path in context_files if path.startswith("context/")),
        )
        _, stderr = self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(self.write_json("coverage-v2-too-many-context.json", too_many)),
            expected=2,
        )
        self.assertIn("at most 32", stderr)

        oversized = self.coverage_plan_v2(scope_hash, context_paths=["oversized.txt"])
        _, stderr = self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(self.write_json("coverage-v2-oversized-context.json", oversized)),
            expected=2,
        )
        self.assertIn("2 MiB", stderr)
        self.assertFalse((self.run_dir / "coverage-plan.json").exists())
        self.assertFalse((self.run_dir / "coverage-context.json").exists())

    def test_context_snapshot_rejects_symlinks_and_total_size_overflow(self) -> None:
        self.commit_context_files(
            {
                "context-a.txt": b"aa",
                "context-b.txt": b"bb",
                "owner.py": b"OWNER = 'canonical'\n",
            }
        )
        (self.repo / "owner-link.py").symlink_to("owner.py")
        self.git("add", "--", "owner-link.py")
        self.git("commit", "-qm", "add context symlink")
        scope_hash = self.init()

        symlink_plan = self.coverage_plan_v2(
            scope_hash,
            context_paths=["owner-link.py"],
        )
        _, stderr = self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(self.write_json("symlink-context.json", symlink_plan)),
            expected=2,
        )
        self.assertIn("allowed context paths", stderr)

        scope_identity = self.load("scope.json")["identity"]
        with self.assertRaises(reviewctl.ReviewError) as raised:
            reviewctl.snapshot_coverage_context(
                self.repo,
                self.run_dir,
                scope_identity,
                {"context-a.txt", "context-b.txt"},
                max_total_bytes=3,
            )
        self.assertIn("total limit", str(raised.exception))
        self.assertFalse((self.run_dir / "coverage-context").exists())

    def test_context_changed_or_deleted_after_initialization_fails_closed(self) -> None:
        owner = self.repo / "owner.py"
        self.commit_context_files({"owner.py": b"OWNER = 'canonical'\n"})
        for name, mutate in (
            (
                "changed",
                lambda: owner.write_text("OWNER = 'changed'\n", encoding="utf-8"),
            ),
            ("deleted", owner.unlink),
        ):
            with self.subTest(name=name):
                owner.write_text("OWNER = 'canonical'\n", encoding="utf-8")
                self.run_id = f"test-run-context-{name}"
                scope_hash = self.init()
                mutate()
                plan = self.coverage_plan_v2(
                    scope_hash,
                    context_paths=["owner.py"],
                )
                _, stderr = self.run_tool(
                    "record-coverage",
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    "--input",
                    str(self.write_json(f"{name}-context.json", plan)),
                    expected=2,
                )
                self.assertIn("Frozen review scope is stale", stderr)
                self.assertFalse((self.run_dir / "coverage-plan.json").exists())
                self.assertFalse((self.run_dir / "coverage-context.json").exists())

    def test_declared_frozen_context_can_supply_comparison_evidence_only(self) -> None:
        for mode in ("working-tree", "commit"):
            with self.subTest(mode=mode):
                self.commit_context_files({"owner.py": b"OWNER = 'canonical'\n"})
                if mode == "commit":
                    base_sha = self.git("rev-parse", "HEAD")
                    self.git("add", "calc.py")
                    self.git("commit", "-qm", "comparison")
                    head_sha = self.git("rev-parse", "HEAD")
                    self.run_tool(
                        "init",
                        "--repo-root",
                        str(self.repo),
                        "--scope",
                        "range",
                        "--base",
                        base_sha,
                        "--head",
                        head_sha,
                        "--run-id",
                        self.run_id,
                    )
                    scope_hash = self.load("state.json")["scope_hash"]
                else:
                    scope_hash = self.init()
                plan = self.coverage_plan_v2(
                    scope_hash, context_paths=["owner.py"]
                )
                self.run_tool(
                    "record-coverage",
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    "--input",
                    str(self.write_json(f"{mode}-context-plan.json", plan)),
                )
                paths = self.candidate_paths_for_coverage_v3(scope_hash)
                candidate_path = next(
                    path for path in paths if "core-correctness" in path.name
                )
                candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
                candidate["findings"][0].update(
                    file="owner.py",
                    line_start=1,
                    line_end=1,
                    evidence_side="comparison",
                    evidence_quote="OWNER = 'canonical'",
                    scope_relation="secondary",
                    related_changed_files=["calc.py"],
                    direct_dependency=True,
                )
                state = reviewctl.load_state(self.run_dir)
                recorded_plan = reviewctl.load_recorded_coverage_plan(
                    self.run_dir, state
                )

                normalized, rejections = reviewctl.validate_candidate_set(
                    candidate,
                    source_file=candidate_path,
                    repo=self.repo,
                    run_dir=self.run_dir,
                    state=state,
                    plan=recorded_plan,
                )
                self.assertEqual(rejections, [])
                self.assertEqual(normalized["findings"][0]["file"], "owner.py")

                baseline = copy.deepcopy(candidate)
                baseline["findings"][0]["evidence_side"] = "baseline"
                with self.assertRaisesRegex(reviewctl.ReviewError, "Evidence source is missing"):
                    reviewctl.validate_candidate_set(
                        baseline,
                        source_file=candidate_path,
                        repo=self.repo,
                        run_dir=self.run_dir,
                        state=state,
                        plan=recorded_plan,
                    )

                undeclared = copy.deepcopy(candidate)
                undeclared["findings"][0].update(
                    file="test_calc.py",
                    evidence_quote="assert add(1, 2) == 3",
                )
                with self.assertRaisesRegex(reviewctl.ReviewError, "Evidence source is missing"):
                    reviewctl.validate_candidate_set(
                        undeclared,
                        source_file=candidate_path,
                        repo=self.repo,
                        run_dir=self.run_dir,
                        state=state,
                        plan=recorded_plan,
                    )

                (self.repo / "owner.py").write_text(
                    "OWNER = 'later live edit'\n", encoding="utf-8"
                )
                normalized, rejections = reviewctl.validate_candidate_set(
                    candidate,
                    source_file=candidate_path,
                    repo=self.repo,
                    run_dir=self.run_dir,
                    state=state,
                    plan=recorded_plan,
                )
                self.assertEqual(rejections, [])
                self.assertEqual(
                    normalized["findings"][0]["evidence_quote"],
                    "OWNER = 'canonical'",
                )

                snapshot = self.run_dir / "coverage-context/sources/owner.py"
                snapshot.write_text("OWNER = 'tampered'\n", encoding="utf-8")
                with self.assertRaisesRegex(
                    reviewctl.ReviewError, "failed integrity validation"
                ):
                    reviewctl.validate_candidate_set(
                        candidate,
                        source_file=candidate_path,
                        repo=self.repo,
                        run_dir=self.run_dir,
                        state=state,
                        plan=recorded_plan,
                    )

                self.tearDown()
                self.setUp()

    def test_v4_coverage_and_v5_candidate_schemas_share_canonical_paths(self) -> None:
        schema_root = Path(__file__).resolve().parents[1] / "schemas"
        coverage_schema = json.loads(
            (schema_root / "coverage-plan-v4.schema.json").read_text(encoding="utf-8")
        )
        candidate_schema = json.loads(
            (schema_root / "candidate-set-v5.schema.json").read_text(encoding="utf-8")
        )
        path_definition = coverage_schema["$defs"]["repositoryRelativeGitPath"]
        self.assertEqual(
            path_definition,
            candidate_schema["$defs"]["repositoryRelativeGitPath"],
        )
        self.assertEqual(
            set(coverage_schema["$defs"]["riskCode"]["enum"]),
            {
                "verification_mechanism_semantics",
                "machine_contract_semantics",
                "distribution_contract_integrity",
                "normative_workflow_coherence",
                "user_selectable_output_paths",
                "persisted_config_semantics",
            },
        )
        self.assertEqual(
            coverage_schema["properties"]["schema_version"]["const"],
            "material-review/coverage-plan/v4",
        )
        self.assertEqual(
            candidate_schema["properties"]["schema_version"]["const"],
            "material-review/candidate-set/v5",
        )

        accepted = (
            "directory with space/name.py",
            "src/name.with.dots.py",
            ".config/tool.py",
            "src/name:with-colon.py",
        )
        rejected = (
            "../x.py",
            "a/../x.py",
            "./x.py",
            "C:/x.py",
            "C:x.py",
            "\\\\server\\x.py",
            "a\\x.py",
            "/x.py",
            "a//x.py",
            ".git/config",
            "x.py/",
            "",
        )
        for path in accepted:
            with self.subTest(path=path, accepted=True):
                self.assertEqual(reviewctl.canonical_git_path(path, "path"), path)
                self.assertEqual(reviewctl.require_canonical_repo_path(path, "path"), path)
        for path in rejected:
            with self.subTest(path=path, accepted=False):
                with self.assertRaises(reviewctl.ObligationContractError):
                    reviewctl.canonical_git_path(path, "path")
                with self.assertRaises(reviewctl.ReviewError):
                    reviewctl.require_canonical_repo_path(path, "path")

    def test_candidate_v5_array_uniqueness_matches_runtime(self) -> None:
        schema_root = Path(__file__).resolve().parents[1] / "schemas"
        candidate_schema = json.loads(
            (schema_root / "candidate-set-v5.schema.json").read_text(
                encoding="utf-8"
            )
        )
        finding_properties = candidate_schema["$defs"]["finding"]["properties"]
        for field in ("counterevidence_checked", "assumptions"):
            with self.subTest(field=field, contract="schema"):
                self.assertIs(finding_properties[field]["uniqueItems"], True)

        def candidate_wave(run_id: str) -> tuple[list[Path], Path]:
            self.run_id = run_id
            scope_hash = self.init_with_recorded_coverage()
            paths = self.candidate_paths_for_coverage(
                scope_hash,
                primary_candidate=self.candidate_set(
                    scope_hash,
                    include_style=False,
                ),
            )
            correctness_path = next(
                path
                for path in paths
                if json.loads(path.read_text(encoding="utf-8"))["assignment_id"]
                == "core-correctness"
            )
            return paths, correctness_path

        for field in ("counterevidence_checked", "assumptions"):
            with self.subTest(field=field, contract="runtime-duplicate"):
                paths, correctness_path = candidate_wave(f"duplicate-{field}")
                payload = json.loads(correctness_path.read_text(encoding="utf-8"))
                payload["findings"][0][field] = ["duplicate", "duplicate"]
                correctness_path.write_text(json.dumps(payload), encoding="utf-8")
                _, stderr = self.ingest_candidate_paths(paths, expected=2)
                self.assertIn(f".{field} must contain unique values", stderr)
                self.assertEqual(self.load("state.json")["phase"], "CONTEXT_FROZEN")
                self.assertFalse((self.run_dir / "candidates.json").exists())
                self.assertTrue(self.load("candidate-ingestion-failure.json")["rejections"])

        paths, correctness_path = candidate_wave("unique-array-controls")
        payload = json.loads(correctness_path.read_text(encoding="utf-8"))
        payload["findings"][0]["counterevidence_checked"] = ["first", "second"]
        payload["findings"][0]["assumptions"] = ["first", "second"]
        correctness_path.write_text(json.dumps(payload), encoding="utf-8")
        self.ingest_candidate_paths(paths)
        self.assertEqual(self.load("state.json")["phase"], "CANDIDATES_CAPTURED")

        paths, correctness_path = candidate_wave("empty-assumptions-control")
        payload = json.loads(correctness_path.read_text(encoding="utf-8"))
        payload["findings"][0]["assumptions"] = []
        correctness_path.write_text(json.dumps(payload), encoding="utf-8")
        self.ingest_candidate_paths(paths)
        self.assertEqual(self.load("state.json")["phase"], "CANDIDATES_CAPTURED")

        paths, correctness_path = candidate_wave("empty-counterevidence-control")
        payload = json.loads(correctness_path.read_text(encoding="utf-8"))
        payload["findings"][0]["counterevidence_checked"] = []
        correctness_path.write_text(json.dumps(payload), encoding="utf-8")
        _, stderr = self.ingest_candidate_paths(paths, expected=2)
        self.assertIn(
            "high/certain confidence requires checked counterevidence",
            stderr,
        )
        self.assertFalse((self.run_dir / "candidates.json").exists())

    def test_adjudication_v4_schema_and_runtime_share_canonical_path_language(self) -> None:
        schema_root = Path(__file__).resolve().parents[1] / "schemas"
        adjudication_schema = json.loads(
            (schema_root / "adjudication-v4.schema.json").read_text(encoding="utf-8")
        )
        candidate_schema = json.loads(
            (schema_root / "candidate-set-v3.schema.json").read_text(encoding="utf-8")
        )
        path_definition = adjudication_schema["$defs"]["repositoryRelativeGitPath"]
        self.assertEqual(
            path_definition,
            candidate_schema["$defs"]["repositoryRelativeGitPath"],
        )
        self.assertEqual(
            adjudication_schema["properties"]["groups"]["items"]["properties"]["file"],
            {"$ref": "#/$defs/repositoryRelativeGitPath"},
        )

        accepted = (
            "directory with space/name.py",
            "src/name.with.dots.py",
            ".config/tool.py",
            "src/name:with-colon.py",
            "résumé.md",
        )
        rejected = (
            "../x.py",
            "a/../x.py",
            "./x.py",
            "C:/x.py",
            "C:x.py",
            "\\\\server\\x.py",
            "a\\x.py",
            "/x.py",
            "a//x.py",
            ".git/config",
            "x.py/",
            " x.py",
            "x.py ",
            "\ufeffx.py",
            "x.py\x00",
            "",
        )
        compiled = re.compile(path_definition["pattern"])
        for path in accepted:
            with self.subTest(path=path, accepted=True):
                self.assertIsNotNone(compiled.fullmatch(path))
                self.assertEqual(reviewctl.require_canonical_repo_path(path, "path"), path)
        for path in rejected:
            with self.subTest(path=path, accepted=False):
                self.assertIsNone(compiled.fullmatch(path))
                with self.assertRaises(reviewctl.ReviewError):
                    reviewctl.require_canonical_repo_path(path, "path")

        scope_hash = self.init_with_recorded_coverage()
        paths = self.candidate_paths_for_coverage(scope_hash)
        self.ingest_candidate_paths(paths)
        state = self.load("state.json")
        candidates = self.load("candidates.json")
        adjudication = self.adjudication(
            scope_hash, candidates["candidate_bundle_hash"]
        )
        normalized = reviewctl.validate_adjudication(
            adjudication, candidates_bundle=candidates, state=state
        )
        self.assertEqual(normalized["groups"][0]["file"], "calc.py")

        for alias in ("./calc.py", "directory/../calc.py", "calc.py/", ".git/config"):
            invalid = copy.deepcopy(adjudication)
            invalid["groups"][0]["file"] = alias
            with self.subTest(alias=alias), self.assertRaises(reviewctl.ReviewError):
                reviewctl.validate_adjudication(
                    invalid, candidates_bundle=candidates, state=state
                )

    def test_historical_discovery_contracts_cannot_enter_state_v3(self) -> None:
        scope_hash = self.init()
        legacy_coverage = self.write_json(
            "legacy-coverage-v1.json",
            {
                "schema_version": "material-review/coverage-plan/v1",
                "scope_hash": scope_hash,
            },
        )
        _, stderr = self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(legacy_coverage),
            expected=2,
        )
        self.assertIn("coverage plan has invalid fields", stderr)
        self.assertFalse((self.run_dir / "coverage-plan.json").exists())

        current_plan = self.write_json(
            "current-coverage-v2.json",
            self.coverage_plan(scope_hash),
        )
        self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(current_plan),
        )
        recorded = self.load("coverage-plan.json")
        assignment = recorded["assignments"][0]
        legacy_candidate = self.write_json(
            "legacy-candidate-v2.json",
            self.empty_candidate_set_v2(
                scope_hash,
                recorded["coverage_plan_hash"],
                assignment,
            ),
        )
        _, stderr = self.ingest_candidate_paths([legacy_candidate], expected=2)
        self.assertIn("unsupported schema_version", stderr)
        self.assertFalse((self.run_dir / "candidates.json").exists())

    def test_coverage_plan_requires_each_positive_risk_lens(self) -> None:
        scope_hash = self.init()
        for missing in ("reliability", "migration_data_safety", "api_config_compatibility"):
            path = self.write_json(f"missing-{missing}.json", self.coverage_plan(scope_hash, omit_lens=missing))
            _, stderr = self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path), expected=2)
            self.assertIn("exactly one", stderr)

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
        original["change_units"][0]["purpose"] = "Replacement attempt."
        replacement = self.write_json("replacement.json", original)
        _, stderr = self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(replacement), expected=2)
        self.assertIn("Coverage plan is already recorded", stderr)

    def test_ingest_refuses_missing_required_lens_without_authoritative_artifacts(self) -> None:
        scope_hash = self.init_with_recorded_coverage()
        paths = self.candidate_paths_for_coverage(scope_hash, omit_lens="migration_data_safety")
        _, stderr = self.ingest_candidate_paths(paths, expected=2)
        self.assertIn("Missing required assignment coverage", stderr)
        self.assertIn("persisted-config-semantics", stderr)
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
        migration = next(path for path in paths if "persisted-config-semantics" in path.name)
        payload = json.loads(migration.read_text(encoding="utf-8"))
        payload["coverage"]["files_reviewed"] = ["test_calc.py"]
        migration.write_text(json.dumps(payload), encoding="utf-8")
        _, stderr = self.ingest_candidate_paths(paths, expected=2)
        self.assertIn("must review every required_review_path: calc.py", stderr)

    def test_conditional_risk_lenses_cover_four_state_matrix(self) -> None:
        output_path = "generated_output.py"
        config_path = "persisted_config.py"

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
            evidence_by_risk = {
                "user_selectable_output_paths": output_path,
                "persisted_config_semantics": config_path,
            }
            for rationale in plan["change_units"][0]["selected_risk_rationale"]:
                rationale["evidence_paths"] = [evidence_by_risk[rationale["risk_code"]]]
            for obligation in plan["review_obligations"]:
                evidence_path = evidence_by_risk[obligation["risk_code"]]
                obligation["canonical_owner"] = evidence_path
                obligation["evidence_paths"] = [evidence_path]
            obligations = {
                obligation["obligation_id"]: obligation
                for obligation in plan["review_obligations"]
            }
            for assignment in plan["assignments"]:
                if assignment["assignment_kind"] != "obligation":
                    continue
                obligation = obligations[assignment["obligation_id"]]
                assignment["required_review_paths"] = sorted(
                    {
                        obligation["canonical_owner"],
                        *obligation["affected_consumers"],
                        *obligation["evidence_paths"],
                    }
                )
                assignment["required_checks"] = obligation["required_checks"]
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
            recorded = self.load("coverage-plan.json")
            obligations = {
                item["obligation_id"]: item for item in recorded["review_obligations"]
            }
            primary_paths = sorted(
                path for unit in recorded["change_units"] for path in unit["primary_paths"]
            )
            paths: list[Path] = []
            for assignment in recorded["assignments"]:
                lens_id = assignment["lens_id"]
                if lens_id == omit_lens:
                    continue
                payload = self.candidate_set_v3(
                    scope_hash,
                    recorded["coverage_plan_hash"],
                    recorded["coverage_context_hash"],
                    assignment,
                    obligation=obligations.get(assignment.get("obligation_id")),
                )
                default_paths = (
                    primary_paths
                    if assignment["assignment_kind"] == "core"
                    else payload["coverage"]["files_reviewed"]
                )
                payload["coverage"]["files_reviewed"] = (reviewed_paths or {}).get(
                    lens_id, default_paths
                )
                paths.append(
                    self.write_json(
                        f"risk-matrix-{name}-{assignment['assignment_id']}.json",
                        payload,
                    )
                )
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
                selected = {
                    item["risk_code"]: item
                    for item in recorded["change_units"][0]["selected_risk_rationale"]
                }
                self.assertEqual(
                    set(selected),
                    {
                        code
                        for code, present in (
                            ("user_selectable_output_paths", output_present),
                            ("persisted_config_semantics", config_present),
                        )
                        if present
                    },
                )
                if output_present:
                    self.assertEqual(selected["user_selectable_output_paths"]["evidence_paths"], [output_path])
                if config_present:
                    self.assertEqual(selected["persisted_config_semantics"]["evidence_paths"], [config_path])
                self.assertEqual(
                    {item["lens_id"] for item in recorded["assignments"]},
                    minimum_required,
                )

                paths = candidate_paths(name, scope_hash, plan)
                self.ingest_candidate_paths(paths)
                state = self.load("state.json")
                self.assertEqual(state["phase"], "CANDIDATES_CAPTURED")
                candidates = self.load("candidates.json")
                self.assertEqual(candidates["coverage_plan_hash"], recorded["coverage_plan_hash"])
                self.assertEqual(
                    {item["assignment_id"] for item in candidates["reviewer_sets"]},
                    {item["assignment_id"] for item in recorded["assignments"]},
                )
                for assignment in recorded["assignments"]:
                    reviewer_set = next(
                        item for item in candidates["reviewer_sets"]
                        if item["assignment_id"] == assignment["assignment_id"]
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
                assignment_id = {
                    "correctness": "core-correctness",
                    "test_adequacy": "core-tests",
                    "standards_alignment": "core-standards",
                }[lens_id]
                self.assertEqual(
                    stderr,
                    f"[FAIL] Missing required assignment coverage: {assignment_id}\n",
                )
                assert_non_authoritative_failure(state_before)

        specialists = (
            (
                "reliability",
                "assignment-obligation-unit-001-user-selectable-output-paths",
                output_path,
                config_path,
            ),
            (
                "migration_data_safety",
                "assignment-obligation-unit-001-persisted-config-semantics",
                config_path,
                output_path,
            ),
            (
                "api_config_compatibility",
                "supplemental-unit-001-persisted-config-semantics-api-config-compatibility",
                config_path,
                output_path,
            ),
        )
        for lens_id, assignment_id, own_path, other_path in specialists:
            for control, omitted_lens, lens_paths, expected_cause in (
                (
                    "missing-lens",
                    lens_id,
                    None,
                    f"Missing required assignment coverage: {assignment_id}",
                ),
                (
                    "missing-own-risk-path",
                    None,
                    {lens_id: ["calc.py"]},
                    "must review every required_review_path",
                ),
                (
                    "substituted-other-risk-path",
                    None,
                    {lens_id: [other_path]},
                    "must review every required_review_path",
                ),
            ):
                with self.subTest(lens=lens_id, control=control):
                    name = f"{lens_id}-{control}"
                    scope_hash, plan = prepare_run(name, output_present=True, config_present=True)
                    reviewed_paths = lens_paths or {}
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
                    self.assertIn(expected_cause, stderr)
                    if lens_paths:
                        self.assertIn(own_path, stderr)
                    assert_non_authoritative_failure(state_before)

    def test_required_assignments_cannot_have_empty_file_coverage(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan_v2(scope_hash, risk_code=None)
        self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(self.write_json("low-risk-coverage.json", plan)),
        )
        paths = self.candidate_paths_for_coverage_v3(scope_hash)
        self.ingest_candidate_paths(paths)
        candidates_before = (self.run_dir / "candidates.json").read_bytes()
        state_before = (self.run_dir / "state.json").read_bytes()

        core_path = next(path for path in paths if "core-correctness" in path.name)
        payload = json.loads(core_path.read_text(encoding="utf-8"))
        payload["coverage"]["files_reviewed"] = []
        core_path.write_text(json.dumps(payload), encoding="utf-8")

        _, stderr = self.ingest_candidate_paths(paths, expected=2)

        self.assertIn("coverage.files_reviewed must contain at least one path", stderr)
        self.assertEqual((self.run_dir / "candidates.json").read_bytes(), candidates_before)
        self.assertEqual((self.run_dir / "state.json").read_bytes(), state_before)
        self.assertTrue((self.run_dir / "candidate-ingestion-failure.json").exists())

    def test_one_candidate_result_cannot_satisfy_two_obligations(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan_v2(scope_hash)
        unit = plan["change_units"][0]
        unit["risk_codes"].append("normative_workflow_coherence")
        unit["selected_risk_rationale"].append(
            {
                "risk_code": "normative_workflow_coherence",
                "rationale": "The changed file also defines an ordered workflow.",
                "evidence_paths": ["calc.py"],
            }
        )
        unit["rejected_risk_rationale"] = [
            item
            for item in unit["rejected_risk_rationale"]
            if item["risk_code"] != "normative_workflow_coherence"
        ]
        obligation_id = "obligation-unit-001-normative-workflow-coherence"
        plan["review_obligations"].append(
            {
                "obligation_id": obligation_id,
                "unit_id": "unit-001",
                "risk_code": "normative_workflow_coherence",
                "canonical_owner": "calc.py",
                "affected_consumers": [],
                "evidence_paths": ["calc.py"],
                "required_lens": "standards_alignment",
                "required_checks": [
                    "disabled_mode_dependency_boundary",
                    "normative_sequence",
                    "paired_control",
                    "prerequisite_before_dependent_step",
                ],
            }
        )
        plan["assignments"].append(
            {
                "assignment_id": f"assignment-{obligation_id}",
                "assignment_kind": "obligation",
                "obligation_id": obligation_id,
                "unit_id": "unit-001",
                "risk_code": "normative_workflow_coherence",
                "lens_id": "standards_alignment",
                "reviewer_id": "workflow-reviewer",
                "independence_group": "model-c",
                "review_mode": "subagent",
                "required_review_paths": ["calc.py"],
                "required_checks": [
                    "disabled_mode_dependency_boundary",
                    "normative_sequence",
                    "paired_control",
                    "prerequisite_before_dependent_step",
                ],
            }
        )
        self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(self.write_json("two-obligation-plan.json", plan)),
        )
        paths = self.candidate_paths_for_coverage_v3(scope_hash)
        compound_path = next(path for path in paths if "machine-contract" in path.name)
        compound = json.loads(compound_path.read_text(encoding="utf-8"))
        compound["obligation_id"] = [
            item["obligation_id"] for item in plan["review_obligations"]
        ]
        compound_path.write_text(json.dumps(compound), encoding="utf-8")

        _, stderr = self.ingest_candidate_paths(paths, expected=2)

        self.assertIn("obligation_id", stderr)
        self.assertFalse((self.run_dir / "candidates.json").exists())

    def test_obligation_checks_fail_closed(self) -> None:
        scope_hash = self.init_with_recorded_coverage_v2()
        valid_paths = self.candidate_paths_for_coverage_v3(scope_hash)
        obligation_index = next(
            index for index, path in enumerate(valid_paths) if "obligation" in path.name
        )

        def missing(payload: dict) -> None:
            payload["check_results"].pop()

        def duplicate(payload: dict) -> None:
            payload["check_results"].append(copy.deepcopy(payload["check_results"][0]))

        def pass_without_evidence(payload: dict) -> None:
            payload["check_results"][0]["evidence_items"][0]["evidence"] = []

        def finding_without_local_id(payload: dict) -> None:
            payload["check_results"][0].update(
                outcome="finding_emitted", finding_local_ids=[]
            )

        def unknown_local_id(payload: dict) -> None:
            payload["check_results"][0].update(
                outcome="finding_emitted", finding_local_ids=["unknown-local-id"]
            )

        def blocked(payload: dict) -> None:
            payload["check_results"][0].update(
                outcome="blocked",
            )

        mutations = {
            "required checks": missing,
            "exactly once": duplicate,
            "pass requires evidence": pass_without_evidence,
            "finding_emitted requires finding_local_ids": finding_without_local_id,
            "unknown local IDs": unknown_local_id,
            "blocked": blocked,
        }
        for index, (expected, mutate) in enumerate(mutations.items()):
            paths: list[Path] = []
            for path_index, source in enumerate(valid_paths):
                payload = json.loads(source.read_text(encoding="utf-8"))
                if path_index == obligation_index:
                    mutate(payload)
                paths.append(
                    self.write_json(f"invalid-check-{index}-{path_index}.json", payload)
                )
            with self.subTest(expected=expected):
                _, stderr = self.ingest_candidate_paths(paths, expected=2)
                self.assertIn(expected, stderr)
                self.assertFalse((self.run_dir / "candidates.json").exists())

    def test_one_collision_finding_cannot_mask_atomic_output_checks(self) -> None:
        scope_hash = self.init_with_recorded_coverage()
        paths = self.candidate_paths_for_coverage(scope_hash)
        core_path = next(path for path in paths if "core-correctness" in path.name)
        obligation_path = next(
            path for path in paths if "user-selectable-output-paths" in path.name
        )
        core_payload = json.loads(core_path.read_text(encoding="utf-8"))
        obligation_payload = json.loads(obligation_path.read_text(encoding="utf-8"))
        finding = copy.deepcopy(core_payload["findings"][0])
        obligation_payload["findings"] = [finding]
        collision = next(
            result
            for result in obligation_payload["check_results"]
            if result["check_code"] == "destination_collision"
        )
        collision.update(
            outcome="finding_emitted",
            finding_local_ids=[finding["local_id"]],
        )
        collision["evidence_items"][0]["evidence"] = [
            "The configured report path aliases the authoritative output."
        ]
        obligation_payload["check_results"] = [
            result
            for result in obligation_payload["check_results"]
            if result["check_code"]
            not in {
                "canonical_filesystem_identity",
                "runtime_writer_target_inventory",
            }
        ]
        obligation_path.write_text(
            json.dumps(obligation_payload), encoding="utf-8"
        )
        state_path = self.run_dir / "state.json"
        state_before = state_path.read_bytes()

        _, stderr = self.ingest_candidate_paths(paths, expected=2)

        self.assertIn("required checks", stderr)
        self.assertEqual(state_path.read_bytes(), state_before)
        self.assertFalse((self.run_dir / "candidates.json").exists())

    def test_overlength_v3_local_id_rejects_complete_wave_atomically(self) -> None:
        scope_hash = self.init_with_recorded_coverage_v2()
        valid_paths = self.candidate_paths_for_coverage_v3(scope_hash)
        candidate_path = next(path for path in valid_paths if "core-correctness" in path.name)
        payload = json.loads(candidate_path.read_text(encoding="utf-8"))
        accepted_local_id = "a" * 128
        payload["findings"][0]["local_id"] = accepted_local_id
        candidate_path.write_text(json.dumps(payload), encoding="utf-8")
        self.ingest_candidate_paths(valid_paths)
        self.assertTrue((self.run_dir / "candidates.json").exists())

        self.tearDown()
        self.setUp()
        scope_hash = self.init_with_recorded_coverage_v2()
        invalid_paths = self.candidate_paths_for_coverage_v3(scope_hash)
        candidate_path = next(path for path in invalid_paths if "core-correctness" in path.name)
        payload = json.loads(candidate_path.read_text(encoding="utf-8"))
        rejected_local_id = "a" * 129
        payload["findings"][0]["local_id"] = rejected_local_id
        candidate_path.write_text(json.dumps(payload), encoding="utf-8")

        state_before = (self.run_dir / "state.json").read_bytes()
        _, stderr = self.ingest_candidate_paths(invalid_paths, expected=2)
        self.assertIn("at most 128 characters", stderr)
        self.assertEqual((self.run_dir / "state.json").read_bytes(), state_before)
        self.assertFalse((self.run_dir / "candidates.json").exists())
        self.assertTrue((self.run_dir / "candidate-ingestion-failure.json").exists())

    def test_candidate_v3_documents_and_enforces_evidence_range_order(self) -> None:
        schema = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "schemas"
                / "candidate-set-v3.schema.json"
            ).read_text(encoding="utf-8")
        )
        finding_schema = schema["$defs"]["finding"]
        self.assertIn(
            "line_end must be greater than or equal to line_start",
            finding_schema["$comment"],
        )
        self.assertIn(
            "material-review controller",
            finding_schema["properties"]["line_end"]["description"],
        )

        scope_hash = self.init_with_recorded_coverage_v2()
        paths = self.candidate_paths_for_coverage_v3(scope_hash)
        correctness_path = next(path for path in paths if "core-correctness" in path.name)
        payload = json.loads(correctness_path.read_text(encoding="utf-8"))
        payload["findings"][0].update(
            line_start=1,
            line_end=2,
            evidence_quote="def add(a, b):\n    return a - b",
        )
        correctness_path.write_text(json.dumps(payload), encoding="utf-8")
        self.ingest_candidate_paths(paths)
        self.assertTrue((self.run_dir / "candidates.json").exists())

        self.tearDown()
        self.setUp()
        scope_hash = self.init_with_recorded_coverage_v2()
        paths = self.candidate_paths_for_coverage_v3(scope_hash)
        correctness_path = next(path for path in paths if "core-correctness" in path.name)
        payload = json.loads(correctness_path.read_text(encoding="utf-8"))
        payload["findings"][0].update(line_start=2, line_end=1)
        correctness_path.write_text(json.dumps(payload), encoding="utf-8")
        state_before = (self.run_dir / "state.json").read_bytes()

        _, stderr = self.ingest_candidate_paths(paths, expected=2)

        self.assertIn("line_end must be >= line_start", stderr)
        self.assertEqual((self.run_dir / "state.json").read_bytes(), state_before)
        self.assertFalse((self.run_dir / "candidates.json").exists())
        self.assertTrue((self.run_dir / "candidate-ingestion-failure.json").exists())

    def test_exact_v3_candidate_retry_is_no_write(self) -> None:
        scope_hash = self.init_with_recorded_coverage_v2()
        paths = self.candidate_paths_for_coverage_v3(scope_hash)
        self.ingest_candidate_paths(paths)
        authoritative_paths = [
            self.run_dir / name
            for name in ("state.json", "candidates.json", "candidate-rejections.json", "candidates.md")
        ]
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in authoritative_paths}

        self.ingest_candidate_paths(paths)

        after = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in authoritative_paths}
        self.assertEqual(after, before)

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

    def test_candidate_set_v3_binding_fields_are_strict_and_atomic(self) -> None:
        """Reject incomplete or malformed review bindings before authority capture."""
        authoritative_artifacts = (
            "candidates.json",
            "candidate-rejections.json",
            "candidates.md",
        )

        self.run_id = "test-run-v3-binding-complete"
        scope_hash = self.init_with_recorded_coverage()
        complete_paths = self.candidate_paths_for_coverage(scope_hash)
        recorded_coverage_hash = self.load("coverage-plan.json")["coverage_plan_hash"]
        recorded_context_hash = self.load("coverage-plan.json")["coverage_context_hash"]
        self.ingest_candidate_paths(complete_paths)
        complete_state = self.load("state.json")
        complete_candidates = self.load("candidates.json")
        self.assertEqual(complete_state["phase"], "CANDIDATES_CAPTURED")
        self.assertEqual(complete_state["hashes"]["coverage_plan_hash"], recorded_coverage_hash)
        self.assertEqual(complete_state["hashes"]["coverage_context_hash"], recorded_context_hash)
        self.assertEqual(complete_candidates["coverage_plan_hash"], recorded_coverage_hash)
        self.assertEqual(complete_candidates["coverage_context_hash"], recorded_context_hash)

        def assert_rejected_binding(
            name: str, mutate, expected_error: str
        ) -> None:
            self.run_id = f"test-run-v3-binding-{name}"
            bound_scope_hash = self.init_with_recorded_coverage()
            paths = self.candidate_paths_for_coverage(bound_scope_hash)
            candidate_path = next(path for path in paths if "correctness" in path.name)
            payload = json.loads(candidate_path.read_text(encoding="utf-8"))
            mutate(payload)
            candidate_path.write_text(json.dumps(payload), encoding="utf-8")
            state_before = (self.run_dir / "state.json").read_bytes()

            _, stderr = self.ingest_candidate_paths(paths, expected=2)

            self.assertIn(expected_error, stderr)
            self.assertEqual((self.run_dir / "state.json").read_bytes(), state_before)
            for artifact in authoritative_artifacts:
                self.assertFalse((self.run_dir / artifact).exists(), artifact)

        for field in (
            "schema_version",
            "coverage_plan_hash",
            "coverage_context_hash",
            "assignment_id",
            "assignment_kind",
            "lens_id",
            "reviewer_id",
            "independence_group",
            "review_mode",
            "check_results",
        ):
            with self.subTest(binding="missing", field=field):
                assert_rejected_binding(
                    f"missing-{field}",
                    lambda payload, field=field: payload.pop(field),
                    field,
                )

        for name, mutate, expected_error in (
            (
                "schema-version-wrong-type",
                lambda payload: payload.update({"schema_version": 2}),
                "schema_version must be a string",
            ),
            (
                "schema-version-invalid",
                lambda payload: payload.update({"schema_version": "material-review/candidate-set/v1"}),
                "unsupported schema_version",
            ),
            (
                "coverage-hash-wrong-type",
                lambda payload: payload.update({"coverage_plan_hash": 2}),
                "coverage_plan_hash must be a string",
            ),
            (
                "coverage-hash-invalid-pattern",
                lambda payload: payload.update({"coverage_plan_hash": "A" * 64}),
                "coverage_plan_hash must be a lowercase SHA-256 digest",
            ),
            (
                "lens-wrong-type",
                lambda payload: payload.update({"lens_id": 2}),
                "lens_id",
            ),
            (
                "lens-invalid-pattern",
                lambda payload: payload.update({"lens_id": "invalid-lens"}),
                "lens_id",
            ),
            (
                "reviewer-wrong-type",
                lambda payload: payload.update({"reviewer_id": 2}),
                "reviewer_id",
            ),
            (
                "reviewer-empty",
                lambda payload: payload.update({"reviewer_id": ""}),
                "reviewer_id",
            ),
            (
                "independence-wrong-type",
                lambda payload: payload.update({"independence_group": 2}),
                "independence_group",
            ),
            (
                "independence-empty",
                lambda payload: payload.update({"independence_group": ""}),
                "independence_group",
            ),
            (
                "review-mode-wrong-type",
                lambda payload: payload.update({"review_mode": 2}),
                "review_mode",
            ),
            (
                "review-mode-unsupported",
                lambda payload: payload.update({"review_mode": "unsupported"}),
                "review_mode",
            ),
        ):
            with self.subTest(binding="malformed", case=name):
                assert_rejected_binding(name, mutate, expected_error)

        schema_path = (
            Path(__file__).resolve().parents[1]
            / "schemas"
            / "candidate-set-v5.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(
            schema["required"],
            [
                "schema_version",
                "scope_hash",
                "coverage_plan_hash",
                "coverage_context_hash",
                "assignment_id",
                "assignment_kind",
                "lens_id",
                "reviewer_id",
                "independence_group",
                "review_mode",
                "check_results",
                "findings",
                "coverage",
            ],
        )
        self.assertEqual(
            reviewctl.CANDIDATE_SCHEMA_REVIEW,
            "material-review/candidate-set/v5",
        )
        self.assertEqual(
            schema["properties"]["schema_version"]["const"],
            "material-review/candidate-set/v5",
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
            {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$"},
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

        incomplete = [
            path
            for path in complete
            if "user-selectable-output-paths" not in path.name
        ]
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
                [
                    path
                    for path in exact_retry
                    if "user-selectable-output-paths"
                    not in json.loads(path.read_text(encoding="utf-8"))["assignment_id"]
                ],
                "Missing required assignment coverage",
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

    def test_simultaneous_candidate_ingestion_has_one_coherent_winner(self) -> None:
        scope_hash = self.init_with_recorded_coverage()
        primary_a = self.candidate_set(scope_hash, include_style=False)
        consequence_a = primary_a["findings"][0]["observable_consequence"]
        title_a = primary_a["findings"][0]["title"]
        wave_a = self.candidate_paths_for_coverage(
            scope_hash,
            primary_candidate=primary_a,
        )
        wave_b: list[Path] = []
        consequence_b = "The simultaneous alternate wave has distinct evidence."
        title_b = "Alternate simultaneous candidate title"
        for index, path in enumerate(wave_a):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload["assignment_id"] == "core-correctness":
                payload["findings"][0]["observable_consequence"] = consequence_b
                payload["findings"][0]["title"] = title_b
            wave_b.append(self.write_json(f"simultaneous-b-{index}.json", payload))

        barrier_directory = self.root / "simultaneous-ingest-barrier"
        barrier_directory.mkdir()

        def command(worker_id: str, paths: list[Path]) -> list[str]:
            inputs = [value for path in paths for value in ("--input", str(path))]
            return [
                sys.executable,
                "-B",
                "-c",
                SIMULTANEOUS_INGEST_HARNESS,
                str(SCRIPT),
                str(barrier_directory),
                worker_id,
                "ingest-candidates",
                "--repo-root",
                str(self.repo),
                "--run-id",
                self.run_id,
                *inputs,
            ]

        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        processes = [
            subprocess.Popen(
                command("a", wave_a),
                cwd=self.repo,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ),
            subprocess.Popen(
                command("b", wave_b),
                cwd=self.repo,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ),
        ]
        completed: list[tuple[int, str, str]] = []
        try:
            ready_paths = [
                barrier_directory / "ready-a",
                barrier_directory / "ready-b",
            ]
            deadline = time.monotonic() + 15.0
            while not all(path.exists() for path in ready_paths):
                exited = [
                    process.returncode
                    for process in processes
                    if process.poll() is not None
                ]
                if exited:
                    self.fail(f"ingestion worker exited before the barrier: {exited}")
                if time.monotonic() >= deadline:
                    self.fail("ingestion workers did not reach the semantic barrier")
                time.sleep(0.005)
            (barrier_directory / "release").write_text("go\n", encoding="utf-8")
            for process in processes:
                stdout, stderr = process.communicate(timeout=30.0)
                completed.append((process.returncode, stdout, stderr))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

        self.assertEqual(sorted(result[0] for result in completed), [0, 2])
        winner = next(result for result in completed if result[0] == 0)
        loser = next(result for result in completed if result[0] == 2)
        self.assertIn("Candidate bundle written", winner[1])
        self.assertIn("candidate bundle is already captured", loser[2].lower())

        bundle = self.load("candidates.json")
        state = self.load("state.json")
        rejections = self.load("candidate-rejections.json")
        markdown = (self.run_dir / "candidates.md").read_text(encoding="utf-8")
        bundle_hash = reviewctl.verify_embedded_hash(
            bundle,
            hash_field="candidate_bundle_hash",
            context="simultaneous normalized candidates",
            unhashed_fields={"generated_at"},
        )
        observed_consequence = bundle["candidates"][0]["observable_consequence"]
        self.assertIn(observed_consequence, {consequence_a, consequence_b})
        observed_title = bundle["candidates"][0]["title"]
        self.assertIn(observed_title, {title_a, title_b})
        losing_title = title_b if observed_title == title_a else title_a
        self.assertIn(observed_title, markdown)
        self.assertNotIn(losing_title, markdown)
        self.assertEqual(rejections, [])
        self.assertEqual(state["phase"], "CANDIDATES_CAPTURED")
        self.assertEqual(state["hashes"]["candidate_bundle_hash"], bundle_hash)
        ingestion_events = [
            event
            for event in state["events"]
            if event["event"] == "candidates_ingested"
        ]
        self.assertEqual(len(ingestion_events), 1)
        self.assertEqual(
            ingestion_events[0]["candidate_bundle_hash"],
            bundle_hash,
        )

    def test_ingest_rejects_duplicate_or_unassigned_assignment_without_authoritative_write(self) -> None:
        self.run_id = "test-run-duplicate-assignment"
        scope_hash = self.init_with_recorded_coverage()
        paths = self.candidate_paths_for_coverage(scope_hash)
        _, stderr = self.ingest_candidate_paths([*paths, paths[0]], expected=2)
        self.assertIn("Duplicate candidate assignment_id", stderr)
        self.assertFalse((self.run_dir / "candidates.json").exists())

        self.run_id = "test-run-unassigned-assignment"
        scope_hash = self.init_with_recorded_coverage()
        paths = self.candidate_paths_for_coverage(scope_hash)
        payload = json.loads(paths[0].read_text(encoding="utf-8"))
        payload["assignment_id"] = "unassigned"
        paths[0].write_text(json.dumps(payload), encoding="utf-8")
        _, stderr = self.ingest_candidate_paths(paths, expected=2)
        self.assertIn("assignment_id is absent from the coverage plan", stderr)
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
                self.assertIn(f"assignment identity mismatch for {field}", stderr)

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

    def test_material_review_rejects_a_v3_set_with_any_invalid_finding(self) -> None:
        scope_hash = self.init_with_recorded_coverage()
        paths = self.candidate_paths_for_coverage(scope_hash)
        candidate_path = next(
            path
            for path in paths
            if json.loads(path.read_text(encoding="utf-8"))["findings"]
        )
        payload = json.loads(candidate_path.read_text(encoding="utf-8"))
        payload["findings"][0]["line_start"] = 0
        candidate_path.write_text(json.dumps(payload), encoding="utf-8")
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
        candidate_path = next(
            path
            for path in paths
            if json.loads(path.read_text(encoding="utf-8"))["findings"]
        )
        payload = json.loads(candidate_path.read_text(encoding="utf-8"))
        payload["findings"][0]["line_start"] = 0
        candidate_path.write_text(json.dumps(payload), encoding="utf-8")
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
                    artifact["change_units"][0]["purpose"] = "Tampered."
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

    def test_coverage_plan_rejects_incomplete_or_duplicate_risk_decisions(self) -> None:
        scope_hash = self.init()
        cases = []

        incomplete = self.coverage_plan(scope_hash)
        incomplete["change_units"][0]["rejected_risk_rationale"].pop()
        cases.append(("incomplete", incomplete, "controlled risk"))

        duplicate = self.coverage_plan(scope_hash)
        duplicate["change_units"][0]["selected_risk_rationale"].append(
            copy.deepcopy(duplicate["change_units"][0]["selected_risk_rationale"][0])
        )
        cases.append(("duplicate", duplicate, "duplicate risk code"))

        for name, plan, expected_error in cases:
            with self.subTest(name=name):
                path = self.write_json(f"{name}-risk-decisions.json", plan)
                _, stderr = self.run_tool(
                    "record-coverage",
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    "--input",
                    str(path),
                    expected=2,
                )
                self.assertIn(expected_error, stderr)
                self.assertFalse((self.run_dir / "coverage-plan.json").exists())

    def test_coverage_plan_rejects_invalid_fields_assignments_and_modes(self) -> None:
        scope_hash = self.init()
        cases = (
            (
                "extra-top-level",
                lambda plan: plan.update({"unexpected": True}),
                "invalid fields",
            ),
            (
                "extra-unit-field",
                lambda plan: plan["change_units"][0].update({"unexpected": True}),
                "invalid fields",
            ),
            (
                "duplicate-assignment",
                lambda plan: plan["assignments"].append(
                    copy.deepcopy(plan["assignments"][0])
                ),
                "unique",
            ),
            (
                "missing-core-assignment",
                lambda plan: plan["assignments"].pop(0),
                "three mandatory core assignments",
            ),
            (
                "unsupported-review-mode",
                lambda plan: plan["assignments"][0].update({"review_mode": "peer"}),
                "review_mode",
            ),
        )
        for name, mutate, expected_error in cases:
            with self.subTest(name=name):
                plan = self.coverage_plan(scope_hash)
                mutate(plan)
                _, stderr = self.run_tool(
                    "record-coverage",
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    "--input",
                    str(self.write_json(f"{name}.json", plan)),
                    expected=2,
                )
                self.assertIn(expected_error, stderr)
                self.assertFalse((self.run_dir / "coverage-plan.json").exists())

    def test_coverage_plan_rejects_unsafe_or_untracked_context_paths(self) -> None:
        exclude = self.repo / ".git" / "info" / "exclude"
        exclude.write_text("untracked.py\n", encoding="utf-8")
        (self.repo / "untracked.py").write_text("VALUE = 1\n", encoding="utf-8")
        scope_hash = self.init()
        for name, context_path, expected_error in (
            ("unsafe", "../owner.py", "canonical repository-relative"),
            ("untracked", "untracked.py", "allowed context paths"),
        ):
            with self.subTest(name=name):
                plan = self.coverage_plan_v2(scope_hash, context_paths=[context_path])
                _, stderr = self.run_tool(
                    "record-coverage",
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    "--input",
                    str(self.write_json(f"{name}-context.json", plan)),
                    expected=2,
                )
                self.assertIn(expected_error, stderr)
                self.assertFalse((self.run_dir / "coverage-plan.json").exists())
                self.assertFalse((self.run_dir / "coverage-context.json").exists())

    def test_coverage_plan_rejects_pre_contract_state(self) -> None:
        scope_hash = self.init()
        self.make_run_legacy()
        path = self.write_json("pre-contract-state.json", self.coverage_plan(scope_hash))
        _, stderr = self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path), expected=2)
        self.assertIn("Run predates required coverage", stderr)

    def test_state_v2_review_is_legacy_after_state_v3_release(self) -> None:
        self.assertEqual(
            hashlib.sha256(CONTROLLER_1_3_COMPAT.read_bytes()).hexdigest(),
            CONTROLLER_1_3_COMPAT_SHA256,
        )
        scope_hash = self.init()
        self.make_run_state_v2_with_frozen_1_3_fixture()
        state = self.load("state.json")
        self.assertEqual(state["schema_version"], "material-review/state/v2")
        self.assertEqual(
            reviewctl.classify_state_contract(state),
            "finalizable_material_review_v2",
        )

        self.run_tool(
            "status",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--json",
        )
        self.run_tool(
            "check-scope",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
        )

        coverage = self.write_json("state-v2-coverage.json", self.coverage_plan(scope_hash))
        candidate = self.candidate_set(scope_hash)
        candidate["schema_version"] = "material-review/candidate-set/v2"
        candidate["coverage_plan_hash"] = "0" * 64
        candidate["lens_id"] = "correctness"
        candidate_path = self.write_json("state-v2-candidate.json", candidate)
        adjudication_path = self.write_json("state-v2-adjudication.json", {})
        forward_commands = (
            ("record-coverage", "--input", str(coverage)),
            ("ingest-candidates", "--input", str(candidate_path)),
            ("compile-ledger", "--input", str(adjudication_path)),
            ("gate-findings", "--approve", "F001", "--user-statement", "Do not advance."),
        )
        for command in forward_commands:
            with self.subTest(command=command[0]):
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

        bounded_restoration_commands = (
            ("rollback-finding", "--finding", "F001", "--reason", "Bounded legacy check."),
            ("abort-fixes", "--reason", "Bounded legacy check."),
        )
        for command in bounded_restoration_commands:
            with self.subTest(command=command[0]):
                _, stderr = self.run_tool(
                    command[0],
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    *command[1:],
                    expected=2,
                )
                self.assertNotIn("Run predates required coverage", stderr)

    def test_new_review_run_uses_state_v5(self) -> None:
        self.init()
        state = self.load("state.json")
        self.assertEqual(state["schema_version"], "material-review/state/v5")
        self.assertEqual(state["workflow_profile"], "material_review")
        self.assertIs(state["coverage_required"], True)

    def test_state_v4_review_is_restart_only_after_state_v5_release(self) -> None:
        self.assertEqual(
            hashlib.sha256(CONTROLLER_1_5_COMPAT.read_bytes()).hexdigest(),
            CONTROLLER_1_5_COMPAT_SHA256,
        )
        scope_hash = self.init()
        self.make_run_state_v4_with_frozen_1_5_fixture()
        state = self.load("state.json")
        self.assertEqual(state["schema_version"], "material-review/state/v4")
        self.assertEqual(
            reviewctl.classify_state_contract(state),
            "legacy_material_review_v4",
        )

        self.run_tool(
            "status", "--repo-root", str(self.repo), "--run-id", self.run_id, "--json"
        )
        self.run_tool(
            "check-scope", "--repo-root", str(self.repo), "--run-id", self.run_id
        )
        coverage = self.write_json("state-v4-coverage.json", self.coverage_plan(scope_hash))
        _, stderr = self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(coverage),
            expected=2,
        )
        self.assertIn("Run predates required coverage; start a new run.", stderr)

        for command in (
            ("rollback-finding", "--finding", "F001", "--reason", "Bounded legacy check."),
            ("abort-fixes", "--reason", "Bounded legacy check."),
        ):
            with self.subTest(command=command[0]):
                _, stderr = self.run_tool(
                    command[0],
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    *command[1:],
                    expected=2,
                )
                self.assertNotIn("Run predates required coverage", stderr)

    def test_state_v3_review_is_restart_only_after_state_v4_release(self) -> None:
        self.assertEqual(
            hashlib.sha256(CONTROLLER_1_4_COMPAT.read_bytes()).hexdigest(),
            CONTROLLER_1_4_COMPAT_SHA256,
        )
        scope_hash = self.init()
        self.make_run_state_v3_with_frozen_1_4_fixture()
        state = self.load("state.json")
        self.assertEqual(state["schema_version"], "material-review/state/v3")
        self.assertEqual(
            reviewctl.classify_state_contract(state),
            "legacy_material_review_v3",
        )

        self.run_tool(
            "status", "--repo-root", str(self.repo), "--run-id", self.run_id, "--json"
        )
        self.run_tool(
            "check-scope", "--repo-root", str(self.repo), "--run-id", self.run_id
        )
        coverage = self.write_json("state-v3-coverage.json", self.coverage_plan(scope_hash))
        _, stderr = self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(coverage),
            expected=2,
        )
        self.assertIn("Run predates required coverage; start a new run.", stderr)

        for command in (
            ("rollback-finding", "--finding", "F001", "--reason", "Bounded legacy check."),
            ("abort-fixes", "--reason", "Bounded legacy check."),
        ):
            with self.subTest(command=command[0]):
                _, stderr = self.run_tool(
                    command[0],
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    *command[1:],
                    expected=2,
                )
                self.assertNotIn("Run predates required coverage", stderr)

    def test_specialist_provenance_survives_normalization(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan_v2(scope_hash, risk_code=None)
        unit = plan["change_units"][0]
        specialist_decision = next(
            item
            for item in unit["specialist_decisions"]
            if item["lens_id"] == "security_privacy"
        )
        specialist_decision.update(
            {
                "decision": "selected",
                "basis": "ambiguous",
                "evidence": ["The trust boundary is ambiguous in the changed behavior."],
                "scenario_checks": [
                    {
                        "check_code": "trust-boundary-dispatch-stability",
                        "claim": "The validated trust classification remains stable through dispatch.",
                        "evidence_paths": unit["primary_paths"],
                        "countercontrol": "Change the trust classification after validation and before dispatch.",
                    }
                ],
            }
        )
        plan["assignments"].append(
            {
                "assignment_id": "specialist-security-privacy",
                "assignment_kind": "specialist",
                "lens_id": "security_privacy",
                "reviewer_id": "security-reviewer",
                "independence_group": "model-b",
                "review_mode": "subagent",
                "unit_ids": ["unit-001"],
                "primary_paths": unit["primary_paths"],
                "context_paths": unit["context_paths"],
                "required_review_paths": sorted(
                    {*unit["primary_paths"], *unit["context_paths"]}
                ),
                "required_checks": ["trust-boundary-dispatch-stability"],
            }
        )
        self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(self.write_json("specialist-coverage.json", plan)),
        )
        self.ingest_candidate_paths(self.candidate_paths_for_coverage_v3(scope_hash))
        bundle = self.load("candidates.json")
        reviewer_set = next(
            item
            for item in bundle["reviewer_sets"]
            if item["assignment_id"] == "specialist-security-privacy"
        )
        self.assertEqual(reviewer_set["unit_ids"], ["unit-001"])
        self.assertEqual(reviewer_set["primary_paths"], ["calc.py"])
        self.assertEqual(reviewer_set["context_paths"], [])
        self.assertEqual(reviewer_set["required_review_paths"], ["calc.py"])
        self.assertEqual(
            reviewer_set["required_checks"],
            ["trust-boundary-dispatch-stability"],
        )
        self.assertEqual(
            [item["check_code"] for item in reviewer_set["scenario_checks"]],
            ["trust-boundary-dispatch-stability"],
        )

    def test_obligation_check_contracts_survive_normalization(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan_v2(
            scope_hash,
            risk_code="user_selectable_output_paths",
        )
        self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(self.write_json("output-path-coverage.json", plan)),
        )

        self.ingest_candidate_paths(self.candidate_paths_for_coverage_v3(scope_hash))

        bundle = self.load("candidates.json")
        reviewer_set = next(
            item
            for item in bundle["reviewer_sets"]
            if item["assignment_kind"] == "obligation"
        )
        self.assertEqual(
            [item["check_code"] for item in reviewer_set["check_contracts"]],
            sorted(
                RISK_REQUIREMENTS["user_selectable_output_paths"][
                    "required_checks"
                ]
            ),
        )
        destination_collision = next(
            item
            for item in reviewer_set["check_contracts"]
            if item["check_code"] == "destination_collision"
        )
        resolved_matrix = next(
            item
            for item in destination_collision["evidence_items"]
            if item["item_code"] == "resolved_identity_matrix"
        )
        self.assertEqual(
            resolved_matrix["path_scope"],
            "all_required_review_paths",
        )

        tampered = copy.deepcopy(bundle)
        tampered_reviewer_set = next(
            item
            for item in tampered["reviewer_sets"]
            if item["assignment_kind"] == "obligation"
        )
        tampered_reviewer_set["check_contracts"][0]["claim"] = "Weakened claim."
        with self.assertRaisesRegex(
            reviewctl.ReviewError,
            "do not match the machine-owned obligation contracts",
        ):
            reviewctl.validate_normalized_candidates_profile(
                tampered,
                state=self.load("state.json"),
                plan=self.load("coverage-plan.json"),
            )

    def test_blocked_specialist_result_prevents_candidate_wave_write(self) -> None:
        scope_hash = self.init()
        plan = self.coverage_plan_v2(scope_hash, risk_code=None)
        unit = plan["change_units"][0]
        decision = next(
            item
            for item in unit["specialist_decisions"]
            if item["lens_id"] == "concurrency"
        )
        check_code = "validated-target-rebind-before-mutation"
        decision.update(
            {
                "decision": "selected",
                "basis": "high_risk_mandate",
                "evidence": [
                    "The changed writer has a validation-to-mutation identity interval."
                ],
                "scenario_checks": [
                    {
                        "check_code": check_code,
                        "claim": (
                            "The final mutation remains bound to the target identity "
                            "accepted at validation."
                        ),
                        "evidence_paths": unit["primary_paths"],
                        "countercontrol": (
                            "Replace the target after validation and before the final mutation."
                        ),
                    }
                ],
            }
        )
        plan["assignments"].append(
            {
                "assignment_id": "specialist-concurrency",
                "assignment_kind": "specialist",
                "lens_id": "concurrency",
                "reviewer_id": "concurrency-reviewer",
                "independence_group": "model-b",
                "review_mode": "subagent",
                "unit_ids": [unit["unit_id"]],
                "primary_paths": unit["primary_paths"],
                "context_paths": unit["context_paths"],
                "required_review_paths": sorted(
                    {*unit["primary_paths"], *unit["context_paths"]}
                ),
                "required_checks": [check_code],
            }
        )
        self.run_tool(
            "record-coverage",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--input",
            str(self.write_json("blocked-specialist-plan.json", plan)),
        )
        paths = self.candidate_paths_for_coverage_v3(scope_hash)
        specialist_path = next(path for path in paths if "specialist-concurrency" in path.name)
        specialist = json.loads(specialist_path.read_text(encoding="utf-8"))
        specialist["check_results"][0].update(
            outcome="blocked",
            evidence=["The required replacement interleaving is unavailable."],
            finding_local_ids=[],
        )
        specialist["coverage"]["limitations"] = [
            {
                "description": "The target replacement interleaving is unavailable.",
                "related_check_codes": [check_code],
            }
        ]
        specialist_path.write_text(json.dumps(specialist), encoding="utf-8")

        _, stderr = self.ingest_candidate_paths(paths, expected=2)

        self.assertIn("blocked", stderr)
        self.assertFalse((self.run_dir / "candidates.json").exists())
        self.assertFalse((self.run_dir / "candidate-rejections.json").exists())
        self.assertFalse((self.run_dir / "candidates.md").exists())

    def test_side_aware_snapshot_evidence_resolution(self) -> None:
        source_root = self.root / "snapshot-evidence"

        def frozen_state(relative: str, data: bytes) -> dict:
            destination = source_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            return {
                "type": "file",
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "binary": False,
                "snapshot_path": relative,
            }

        def entry(
            *,
            status: str,
            path: str,
            old_path: str | None,
            baseline: bytes | None,
            comparison: bytes | None,
        ) -> dict:
            baseline_state = (
                {"type": "missing"}
                if baseline is None
                else frozen_state(f"sources/baseline/{old_path or path}", baseline)
            )
            comparison_state = (
                {"type": "missing"}
                if comparison is None
                else frozen_state(f"sources/comparison/{path}", comparison)
            )
            return {
                "status": status,
                "path": path,
                "old_path": old_path,
                "tracked": True,
                "baseline_state": baseline_state,
                "comparison_state": comparison_state,
            }

        common_identity = {
            "baseline_sha": self.git("rev-parse", "HEAD"),
            "comparison_kind": "working-tree",
        }

        rename_identity = {
            **common_identity,
            "files": [
                entry(
                    status="R100",
                    path="new.py",
                    old_path="old.py",
                    baseline=b"original\n",
                    comparison=b"original\n",
                )
            ],
        }
        self.assertEqual(
            reviewctl.read_snapshot_source(
                source_root, rename_identity, "baseline", "old.py", self.repo
            ),
            (reviewctl.SNAPSHOT_MATCHED_BYTES, b"original\n"),
        )
        self.assertEqual(
            reviewctl.read_snapshot_source(
                source_root, rename_identity, "comparison", "new.py", self.repo
            ),
            (reviewctl.SNAPSHOT_MATCHED_BYTES, b"original\n"),
        )
        self.assertEqual(
            reviewctl.read_snapshot_source(
                source_root, rename_identity, "comparison", "old.py", self.repo
            ),
            (reviewctl.SNAPSHOT_NO_MATCH, None),
        )

        edited_copy_identity = {
            **common_identity,
            "files": [
                entry(
                    status="R087",
                    path="renamed.py",
                    old_path="before.py",
                    baseline=b"before\n",
                    comparison=b"after\n",
                ),
                entry(
                    status="C100",
                    path="copy.py",
                    old_path="source.py",
                    baseline=b"copied\n",
                    comparison=b"copied\n",
                ),
            ],
        }
        for side, path, expected in (
            ("baseline", "before.py", b"before\n"),
            ("comparison", "renamed.py", b"after\n"),
            ("baseline", "source.py", b"copied\n"),
            ("comparison", "copy.py", b"copied\n"),
        ):
            with self.subTest(side=side, path=path):
                self.assertEqual(
                    reviewctl.read_snapshot_source(
                        source_root, edited_copy_identity, side, path, self.repo
                    ),
                    (reviewctl.SNAPSHOT_MATCHED_BYTES, expected),
                )

        recreated_identity = {
            **common_identity,
            "files": [
                entry(
                    status="R100",
                    path="renamed.py",
                    old_path="old.py",
                    baseline=b"historical\n",
                    comparison=b"historical\n",
                ),
                entry(
                    status="A",
                    path="old.py",
                    old_path=None,
                    baseline=None,
                    comparison=b"recreated\n",
                ),
            ],
        }
        self.assertEqual(
            reviewctl.read_snapshot_source(
                source_root, recreated_identity, "baseline", "old.py", self.repo
            ),
            (reviewctl.SNAPSHOT_MATCHED_BYTES, b"historical\n"),
        )
        self.assertEqual(
            reviewctl.read_snapshot_source(
                source_root, recreated_identity, "comparison", "old.py", self.repo
            ),
            (reviewctl.SNAPSHOT_MATCHED_BYTES, b"recreated\n"),
        )

        deletion_identity = {
            **common_identity,
            "files": [
                entry(
                    status="D",
                    path="deleted.py",
                    old_path=None,
                    baseline=b"deleted evidence\n",
                    comparison=None,
                )
            ],
        }
        self.assertEqual(
            reviewctl.read_snapshot_source(
                source_root, deletion_identity, "comparison", "deleted.py", self.repo
            ),
            (reviewctl.SNAPSHOT_MATCHED_MISSING, None),
        )
        context_data = b"context evidence\n"
        context_path = source_root / "coverage-context" / "sources" / "context.py"
        context_path.parent.mkdir(parents=True, exist_ok=True)
        context_path.write_bytes(context_data)
        coverage_context = {
            "sources": [
                {
                    "path": "context.py",
                    "sha256": hashlib.sha256(context_data).hexdigest(),
                    "size": len(context_data),
                    "snapshot_path": "coverage-context/sources/context.py",
                },
                {
                    "path": "deleted.py",
                    "sha256": hashlib.sha256(context_data).hexdigest(),
                    "size": len(context_data),
                    "snapshot_path": "coverage-context/sources/context.py",
                },
            ]
        }
        reviewctl.verify_evidence_quote(
            repo=self.repo,
            run_dir=source_root,
            scope_identity=deletion_identity,
            file="context.py",
            line_start=1,
            line_end=1,
            side="comparison",
            quote="context evidence",
            coverage_context=coverage_context,
        )
        with self.assertRaisesRegex(
            reviewctl.ReviewError,
            "Evidence source is missing for comparison:deleted.py",
        ):
            reviewctl.verify_evidence_quote(
                repo=self.repo,
                run_dir=source_root,
                scope_identity=deletion_identity,
                file="deleted.py",
                line_start=1,
                line_end=1,
                side="comparison",
                quote="context evidence",
                coverage_context=coverage_context,
            )

        tampered_path = source_root / rename_identity["files"][0]["baseline_state"]["snapshot_path"]
        tampered_path.write_bytes(b"tampered\n")
        with self.assertRaisesRegex(reviewctl.ReviewError, "content hash check"):
            reviewctl.read_snapshot_source(
                source_root, rename_identity, "baseline", "old.py", self.repo
            )

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_v4_restore_uses_component_conditional_boundaries(self) -> None:
        checkpoint_dir = self.root / "v4-exclusive-create"
        recovered_file = self.repo / "recovered.txt"
        recovered_directory = self.repo / "recovered-directory"
        recovered_link = self.repo / "recovered-link"
        recovered_file.write_text("checkpoint bytes\n", encoding="utf-8")
        recovered_directory.mkdir()
        recovered_link.symlink_to("calc.py")
        checkpoint = reviewctl.create_checkpoint(
            self.repo,
            checkpoint_dir,
            ["recovered.txt", "recovered-directory", "recovered-link"],
        )
        recovered_file.unlink()
        recovered_directory.rmdir()
        recovered_link.unlink()
        restored = reviewctl.restore_checkpoint(
            self.repo,
            checkpoint_dir,
            expected_post=reviewctl.repository_authority(self.repo),
        )
        self.assertEqual(restored, checkpoint["repository_authority"])
        self.assertEqual(recovered_file.read_text(encoding="utf-8"), "checkpoint bytes\n")
        self.assertTrue(recovered_directory.is_dir())
        self.assertEqual(recovered_link.readlink(), Path("calc.py"))

        self.tearDown()
        self.setUp()
        for transition in ("replace", "delete"):
            with self.subTest(worktree_transition=transition):
                path = self.repo / ("calc.py" if transition == "replace" else "new.txt")
                checkpoint_dir = self.root / f"v4-worktree-{transition}"
                checkpoint = reviewctl.create_checkpoint(
                    self.repo,
                    checkpoint_dir,
                    [path.relative_to(self.repo).as_posix()],
                )
                path.write_text("concurrent bytes\n", encoding="utf-8")
                authority_before = reviewctl.repository_authority(self.repo)
                with self.assertRaisesRegex(
                    reviewctl.ReviewError, "existing-path replacement or deletion"
                ):
                    reviewctl.restore_checkpoint(
                        self.repo,
                        checkpoint_dir,
                        expected_post=authority_before,
                    )
                self.assertEqual(reviewctl.repository_authority(self.repo), authority_before)
                self.assertEqual(path.read_text(encoding="utf-8"), "concurrent bytes\n")
                self.assertTrue((checkpoint_dir / "recovery-conflict.json").is_file())
                self.tearDown()
                self.setUp()

        checkpoint_dir = self.root / "v4-attached-head"
        checkpoint = reviewctl.create_checkpoint(self.repo, checkpoint_dir, ["calc.py"])
        self.git("switch", "-qc", "temporary-attached")
        restored = reviewctl.restore_checkpoint(
            self.repo,
            checkpoint_dir,
            expected_post=reviewctl.repository_authority(self.repo),
        )
        self.assertEqual(restored, checkpoint["repository_authority"])

        self.tearDown()
        self.setUp()
        checkpoint_dir = self.root / "v4-index-lock"
        checkpoint = reviewctl.create_checkpoint(self.repo, checkpoint_dir, ["calc.py"])
        self.git("add", "calc.py")
        restored = reviewctl.restore_checkpoint(
            self.repo,
            checkpoint_dir,
            expected_post=reviewctl.repository_authority(self.repo),
        )
        self.assertEqual(restored, checkpoint["repository_authority"])

        self.tearDown()
        self.setUp()
        checkpoint_dir = self.root / "v4-index-contention"
        reviewctl.create_checkpoint(self.repo, checkpoint_dir, ["calc.py"])
        expected_post = reviewctl.repository_authority(self.repo)
        index_path = Path(expected_post["identity"]["index"]["path"])
        index_lock = index_path.with_name(f"{index_path.name}.lock")
        index_lock.write_bytes(b"owned elsewhere")
        with self.assertRaisesRegex(reviewctl.ReviewError, "index lock is already held"):
            reviewctl.restore_checkpoint(
                self.repo,
                checkpoint_dir,
                expected_post=expected_post,
            )
        self.assertEqual(index_lock.read_bytes(), b"owned elsewhere")
        index_lock.unlink()

        self.tearDown()
        self.setUp()
        checkpoint_dir = self.root / "v4-capability"
        reviewctl.create_checkpoint(self.repo, checkpoint_dir, ["calc.py"])
        expected_post = reviewctl.repository_authority(self.repo)
        with mock.patch.object(
            reviewctl,
            "probe_v4_symbolic_ref_transactions",
            side_effect=reviewctl.ReviewError("unsupported symbolic transaction"),
        ):
            with self.assertRaisesRegex(reviewctl.ReviewError, "unsupported symbolic transaction"):
                reviewctl.restore_checkpoint(
                    self.repo,
                    checkpoint_dir,
                    expected_post=expected_post,
                )
        self.assertEqual(reviewctl.repository_authority(self.repo), expected_post)
        self.assertTrue((checkpoint_dir / "recovery-conflict.json").is_file())

    def test_v4_restore_fails_closed_on_concurrent_repository_authority_drift(self) -> None:
        for drift in ("ref", "index", "worktree"):
            with self.subTest(drift=drift):
                checkpoint_dir = self.root / f"v4-cas-{drift}"
                reviewctl.create_checkpoint(self.repo, checkpoint_dir, ["calc.py"])
                (self.repo / "calc.py").write_text(
                    "def add(a, b):\n    return 777\n", encoding="utf-8"
                )
                expected_post = reviewctl.repository_authority(self.repo)
                if drift == "ref":
                    self.git("branch", "concurrent-ref")
                elif drift == "index":
                    self.git("add", "calc.py")
                else:
                    (self.repo / "calc.py").write_text(
                        "def add(a, b):\n    return 888\n", encoding="utf-8"
                    )
                authority_after_drift = reviewctl.repository_authority(self.repo)
                source_after_drift = (self.repo / "calc.py").read_bytes()

                with self.assertRaisesRegex(
                    reviewctl.ReviewError,
                    "Repository authority changed after the recovery observation",
                ):
                    reviewctl.restore_checkpoint(
                        self.repo,
                        checkpoint_dir,
                        expected_post=expected_post,
                    )

                self.assertEqual(
                    reviewctl.repository_authority(self.repo), authority_after_drift
                )
                self.assertEqual(
                    (self.repo / "calc.py").read_bytes(), source_after_drift
                )
                conflict = json.loads(
                    (checkpoint_dir / "recovery-conflict.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(conflict["expected_post"], expected_post)
                self.assertEqual(conflict["observed_current"], authority_after_drift)
                self.tearDown()
                self.setUp()

    def test_manual_recovery_observation_rejects_every_unauthorized_drift_kind(self) -> None:
        for drift in ("branch", "ref", "index", "worktree"):
            with self.subTest(drift=drift):
                checkpoint_dir = self.root / f"manual-recovery-{drift}"
                reviewctl.create_checkpoint(self.repo, checkpoint_dir, ["calc.py"])
                (self.repo / "calc.py").write_text(
                    "def add(a, b):\n    return 777\n", encoding="utf-8"
                )
                if drift == "branch":
                    self.git("switch", "-qc", "concurrent-branch")
                elif drift == "ref":
                    self.git("branch", "concurrent-ref")
                elif drift == "index":
                    self.git("add", "calc.py")
                else:
                    (self.repo / "test_calc.py").write_text(
                        "# concurrent user edit\n", encoding="utf-8"
                    )
                authority_before = reviewctl.repository_authority(self.repo)

                with self.assertRaisesRegex(
                    reviewctl.ReviewError, "not authorized for automatic recovery"
                ):
                    reviewctl.manual_recovery_observation(
                        self.repo,
                        checkpoint_dir,
                        allowed_paths=["calc.py"],
                        context="The repair layer",
                    )

                self.assertEqual(
                    reviewctl.repository_authority(self.repo), authority_before
                )
                conflict = json.loads(
                    (checkpoint_dir / "recovery-conflict.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(conflict["observed_current"], authority_before)
                self.tearDown()
                self.setUp()

    def test_manual_recovery_callers_preserve_preexisting_unauthorized_drift(self) -> None:
        for command in ("rollback-finding", "abort-fixes"):
            with self.subTest(command=command):
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
                (self.repo / "calc.py").write_text(
                    "def add(a, b):\n    return a + b\n", encoding="utf-8"
                )
                (self.repo / "test_calc.py").write_text(
                    "# concurrent user edit\n", encoding="utf-8"
                )

                authority_before = reviewctl.repository_authority(self.repo)
                state_before = (self.run_dir / "state.json").read_bytes()
                state = self.load("state.json")
                if command == "rollback-finding":
                    checkpoint_dir = self.run_dir / state["active_finding"]["checkpoint"]
                    arguments = (
                        command,
                        "--finding",
                        "F001",
                        "--reason",
                        "Reject the attempt.",
                    )
                else:
                    checkpoint_dir = self.run_dir / state["pre_fix_checkpoint"]
                    arguments = (command, "--reason", "Abort the repair layer.")

                _, stderr = self.run_tool(
                    *arguments,
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    expected=2,
                )

                self.assertIn("not authorized for automatic recovery", stderr)
                self.assertEqual(
                    reviewctl.repository_authority(self.repo), authority_before
                )
                self.assertEqual(
                    (self.run_dir / "state.json").read_bytes(), state_before
                )
                self.assertTrue((checkpoint_dir / "recovery-conflict.json").is_file())
                self.tearDown()
                self.setUp()

    def test_manual_recovery_callers_fail_closed_on_existing_approved_path_deltas(self) -> None:
        for command in ("rollback-finding", "abort-fixes"):
            with self.subTest(command=command):
                original = (self.repo / "calc.py").read_bytes()
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
                (self.repo / "calc.py").write_text(
                    "def add(a, b):\n    return 777\n", encoding="utf-8"
                )
                if command == "rollback-finding":
                    arguments = (
                        command,
                        "--finding",
                        "F001",
                        "--reason",
                        "Reject the approved-path attempt.",
                    )
                else:
                    arguments = (command, "--reason", "Abort the repair layer.")

                authority_before = reviewctl.repository_authority(self.repo)
                state_before = (self.run_dir / "state.json").read_bytes()
                _, stderr = self.run_tool(
                    *arguments,
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    expected=2,
                )

                self.assertIn("existing-path replacement or deletion", stderr)
                self.assertNotEqual((self.repo / "calc.py").read_bytes(), original)
                self.assertEqual(reviewctl.repository_authority(self.repo), authority_before)
                self.assertEqual((self.run_dir / "state.json").read_bytes(), state_before)
                state = self.load("state.json")
                checkpoint_dir = self.run_dir / (
                    state["active_finding"]["checkpoint"]
                    if command == "rollback-finding"
                    else state["pre_fix_checkpoint"]
                )
                self.assertTrue((checkpoint_dir / "recovery-conflict.json").is_file())
                self.tearDown()
                self.setUp()

    def test_v4_restore_records_failure_after_reattaching_to_missing_branch(self) -> None:
        checkpoint_dir = self.root / "v4-unborn-head-failure"
        checkpoint = reviewctl.create_checkpoint(self.repo, checkpoint_dir, ["calc.py"])
        saved_attachment = checkpoint["repository_authority"]["identity"][
            "head_attachment"
        ]
        self.assertIsNotNone(saved_attachment)
        saved_branch = str(saved_attachment).removeprefix("refs/heads/")
        self.git("switch", "-qc", "recovery-other")
        self.git("branch", "-D", saved_branch)
        expected_post = reviewctl.repository_authority(self.repo)
        original_run_process = reviewctl.run_process

        def fail_ref_transaction(args, **kwargs):
            if (
                list(args) == ["git", "update-ref", "--stdin"]
                and b"commit\n" in kwargs.get("input_bytes", b"")
            ):
                raise reviewctl.ReviewError("injected ref transaction failure")
            return original_run_process(args, **kwargs)

        with mock.patch.object(
            reviewctl, "run_process", side_effect=fail_ref_transaction
        ):
            with self.assertRaisesRegex(
                reviewctl.ReviewError, "Checkpoint recovery was incomplete"
            ):
                reviewctl.restore_checkpoint(
                    self.repo,
                    checkpoint_dir,
                    expected_post=expected_post,
                )

        evidence = json.loads(
            (checkpoint_dir / "recovery-failure.json").read_text(encoding="utf-8")
        )
        self.assertIn("injected ref transaction failure", evidence["reason"])
        self.assertEqual(
            evidence["observed_current"], expected_post
        )

    def test_v4_restore_covers_all_recovery_callers_and_legacy_boundary(self) -> None:
        checkpoint_dir = self.root / "v4-complete-authority"
        checkpoint = reviewctl.create_checkpoint(
            self.repo, checkpoint_dir, ["calc.py", "test_calc.py"]
        )
        self.assertEqual(
            checkpoint["schema_version"], "material-review/checkpoint/v4"
        )
        self.git("branch", "temporary-created")
        self.git("branch", "temporary-moved")
        self.git("branch", "-m", "temporary-moved", "temporary-renamed")
        self.git("switch", "-qc", "temporary-attached")
        (self.repo / "calc.py").write_text(
            "def add(a, b):\n    return 999\n", encoding="utf-8"
        )
        self.git("add", "calc.py")
        self.git("commit", "-qm", "temporary recovery mutation")
        (self.repo / "test_calc.py").write_text("mutated\n", encoding="utf-8")
        expected_post = reviewctl.repository_authority(self.repo)
        with self.assertRaisesRegex(
            reviewctl.ReviewError, "existing-path replacement or deletion"
        ):
            reviewctl.restore_checkpoint(
                self.repo,
                checkpoint_dir,
                expected_post=expected_post,
            )
        self.assertEqual(reviewctl.repository_authority(self.repo), expected_post)
        self.assertTrue((checkpoint_dir / "recovery-conflict.json").is_file())

        self.tearDown()
        self.setUp()
        saved_branch = reviewctl.current_branch(self.repo)
        self.git("switch", "-q", "--detach", "HEAD")
        detached_dir = self.root / "v4-detached-authority"
        detached = reviewctl.create_checkpoint(self.repo, detached_dir, ["calc.py"])
        self.git("switch", "-q", saved_branch)
        detached_post = reviewctl.repository_authority(self.repo)
        reviewctl.restore_checkpoint(
            self.repo,
            detached_dir,
            expected_post=detached_post,
        )
        self.assertIsNone(reviewctl.current_head_attachment(self.repo))
        self.assertEqual(
            reviewctl.resolve_commit(self.repo, "HEAD"), detached["head_sha"]
        )

        self.tearDown()
        self.setUp()
        legacy_dir = self.root / "legacy-checkpoint"
        reviewctl.create_checkpoint(self.repo, legacy_dir, ["calc.py"])
        legacy_path = legacy_dir / "checkpoint.json"
        legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
        for field in (
            "schema_version",
            "repository_authority",
            "refs",
            "head_attachment",
            "local_head_refs",
        ):
            legacy.pop(field, None)
        legacy["checkpoint_hash"] = reviewctl.canonical_hash(
            {
                key: value
                for key, value in legacy.items()
                if key not in {"created_at", "checkpoint_hash"}
            }
        )
        legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
        (self.repo / "calc.py").write_text(
            "def add(a, b):\n    return 333\n", encoding="utf-8"
        )
        restored_legacy = reviewctl.restore_checkpoint(self.repo, legacy_dir)
        self.assertEqual(
            restored_legacy["guard_hash"], legacy["workspace_guard"]["guard_hash"]
        )

        recovery_callers = (
            reviewctl.command_run_test,
            reviewctl.command_run_global_test,
            reviewctl.command_refresh_finding_test,
            reviewctl.command_rollback_finding,
            reviewctl.command_abort_fixes,
        )
        for caller in recovery_callers:
            with self.subTest(caller=caller.__name__):
                source = inspect.getsource(caller)
                self.assertIn("expected_post=", source)
                self.assertNotIn("restore_refresh_checkpoint", source)

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
        self.assertEqual(initial_state["schema_version"], "material-review/state/v5")
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

                authority_before_recovery = reviewctl.repository_authority(self.repo)
                state_before_recovery = state_path.read_bytes()
                _, stderr = self.run_tool(
                    "rollback-finding",
                    "--repo-root",
                    str(self.repo),
                    "--run-id",
                    self.run_id,
                    "--finding",
                    "F001",
                    "--reason",
                    "Restore a legacy active finding.",
                    expected=2,
                )
                self.assertIn("existing-path replacement or deletion", stderr)
                self.assertNotEqual((self.repo / "calc.py").read_bytes(), original_source)
                self.assertEqual(
                    reviewctl.repository_authority(self.repo), authority_before_recovery
                )
                self.assertEqual(state_path.read_bytes(), state_before_recovery)
                checkpoint = self.run_dir / self.load("state.json")["active_finding"]["checkpoint"]
                self.assertTrue((checkpoint / "recovery-conflict.json").is_file())
                self.tearDown()
                self.setUp()

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

    def test_legacy_fixing_run_abort_preserves_existing_path_for_reconciliation(self) -> None:
        self.reach_fixing()
        original = (self.repo / "calc.py").read_text(encoding="utf-8")
        (self.repo / "calc.py").write_text("def add(a, b):\n    return 999\n", encoding="utf-8")
        self.make_run_legacy()
        state_before = (self.run_dir / "state.json").read_bytes()
        authority_before = reviewctl.repository_authority(self.repo)
        _, stderr = self.run_tool(
            "abort-fixes",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--reason",
            "Retire legacy run safely.",
            expected=2,
        )
        self.assertIn("existing-path replacement or deletion", stderr)
        self.assertNotEqual((self.repo / "calc.py").read_text(encoding="utf-8"), original)
        self.assertEqual(reviewctl.repository_authority(self.repo), authority_before)
        self.assertEqual((self.run_dir / "state.json").read_bytes(), state_before)
        checkpoint = self.run_dir / self.load("state.json")["pre_fix_checkpoint"]
        self.assertTrue((checkpoint / "recovery-conflict.json").is_file())

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

    def test_legacy_active_fixing_rollback_preserves_existing_path_for_reconciliation(self) -> None:
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
        state_before = (self.run_dir / "state.json").read_bytes()
        authority_before = reviewctl.repository_authority(self.repo)
        checkpoint = self.run_dir / self.load("state.json")["active_finding"]["checkpoint"]
        _, stderr = self.run_tool(
            "rollback-finding",
            "--repo-root",
            str(self.repo),
            "--run-id",
            self.run_id,
            "--finding",
            "F001",
            "--reason",
            "Retire the legacy active finding safely.",
            expected=2,
        )
        self.assertIn("existing-path replacement or deletion", stderr)
        self.assertNotEqual((self.repo / "calc.py").read_text(encoding="utf-8"), original)
        self.assertEqual(reviewctl.repository_authority(self.repo), authority_before)
        self.assertEqual((self.run_dir / "state.json").read_bytes(), state_before)
        self.assertTrue((checkpoint / "recovery-conflict.json").is_file())

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
