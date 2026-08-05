from __future__ import annotations

import copy
import json
import re
import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from obligation_contract import (  # noqa: E402
    ASSIGNMENT_KINDS,
    CANDIDATE_LOCAL_ID_MAX_LENGTH,
    CHECK_OUTCOMES,
    CORE_LENS_IDS,
    CONTROLLED_RISK_CODES,
    IDENTIFIER_PATTERN,
    RISK_REQUIREMENTS,
    ObligationContractError,
    canonical_git_path,
    required_assignment_ids,
    validate_assignment_result,
    validate_coverage_contract,
)


CORE_ASSIGNMENTS = (
    ("core-correctness", "correctness"),
    ("core-standards", "standards_alignment"),
    ("core-tests", "test_adequacy"),
)


def reviewer_identity(name: str) -> dict[str, str]:
    return {
        "reviewer_id": name,
        "independence_group": f"independence-{name}",
        "review_mode": "subagent",
    }


def core_assignments() -> list[dict]:
    return [
        {
            "assignment_id": assignment_id,
            "assignment_kind": "core",
            "lens_id": lens_id,
            **reviewer_identity(assignment_id),
        }
        for assignment_id, lens_id in CORE_ASSIGNMENTS
    ]


def make_plan(
    *,
    risk_code: str | None = "machine_contract_semantics",
    primary_paths: tuple[str, ...] = ("validator.py",),
    context_paths: tuple[str, ...] = ("runtime.py",),
) -> dict:
    selected_codes = [] if risk_code is None else [risk_code]
    selected = []
    obligations = []
    assignments = core_assignments()
    if risk_code is not None:
        requirement = RISK_REQUIREMENTS[risk_code]
        selected.append(
            {
                "risk_code": risk_code,
                "rationale": "The changed validator and its runtime consumer define one contract.",
                "evidence_paths": [primary_paths[0]],
            }
        )
        obligation_id = f"obligation-unit-001-{risk_code.replace('_', '-')}"
        obligations.append(
            {
                "obligation_id": obligation_id,
                "unit_id": "unit-001",
                "risk_code": risk_code,
                "canonical_owner": primary_paths[0],
                "affected_consumers": list(context_paths),
                "evidence_paths": [primary_paths[0], *context_paths],
                "required_lens": requirement["required_lens"],
                "required_checks": sorted(requirement["required_checks"]),
            }
        )
        assignments.append(
            {
                "assignment_id": f"assignment-{obligation_id}",
                "assignment_kind": "obligation",
                "obligation_id": obligation_id,
                "unit_id": "unit-001",
                "risk_code": risk_code,
                "lens_id": requirement["required_lens"],
                **reviewer_identity(f"reviewer-{risk_code}"),
            }
        )
        for lens_id in sorted(requirement["supporting_lenses"]):
            assignments.append(
                {
                    "assignment_id": (
                        f"supplemental-unit-001-{risk_code.replace('_', '-')}-{lens_id.replace('_', '-')}"
                    ),
                    "assignment_kind": "supplemental",
                    "unit_id": "unit-001",
                    "risk_code": risk_code,
                    "lens_id": lens_id,
                    **reviewer_identity(f"reviewer-{risk_code}-{lens_id}"),
                }
            )
    rejected = [
        {
            "risk_code": code,
            "rationale": "The change does not alter this controlled contract boundary.",
        }
        for code in sorted(CONTROLLED_RISK_CODES - set(selected_codes))
    ]
    specialist_decisions = [
        {
            "lens_id": lens_id,
            "decision": "rejected",
            "basis": "behavior_evidence",
            "evidence": [f"The fixture behavior does not trigger {lens_id}."],
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
    ]
    unit_paths = sorted({*primary_paths, *context_paths})
    obligations_by_id = {item["obligation_id"]: item for item in obligations}
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
        "scope_hash": "a" * 64,
        "workflow_profile": "material_review",
        "depth": "auto",
        "change_units": [
            {
                "unit_id": "unit-001",
                "purpose": "Keep one coherent validator/runtime contract aligned.",
                "primary_paths": list(primary_paths),
                "context_paths": list(context_paths),
                "canonical_owner": primary_paths[0],
                "affected_consumers": [*primary_paths[1:], *context_paths],
                "risk_codes": selected_codes,
                "selected_risk_rationale": selected,
                "rejected_risk_rationale": rejected,
                "specialist_decisions": specialist_decisions,
            }
        ],
        "review_obligations": obligations,
        "assignments": assignments,
    }


def make_v4_specialist_plan() -> dict:
    plan = make_plan(
        risk_code=None,
        primary_paths=("api.py", "writer.py"),
        context_paths=("contract.md",),
    )
    plan["schema_version"] = "material-review/coverage-plan/v4"
    unit = plan["change_units"][0]
    unit["canonical_owner"] = "api.py"
    unit["affected_consumers"] = ["contract.md", "writer.py"]
    for decision in unit["specialist_decisions"]:
        decision["scenario_checks"] = []
        if decision["lens_id"] == "concurrency":
            decision.update(
                {
                    "decision": "selected",
                    "basis": "ambiguous",
                    "evidence": [
                        "The final writer can observe target replacement after validation."
                    ],
                    "scenario_checks": [
                        {
                            "check_code": "configured-output-concurrency-target-rebind",
                            "claim": "The validated destination identity remains stable through every final mutation.",
                            "evidence_paths": ["api.py", "writer.py", "contract.md"],
                            "countercontrol": "Replace the selected target after preparation and before commit, or prove a rooted descriptor-relative commit prevents redirection.",
                        }
                    ],
                }
            )

    required_review_paths = ["api.py", "contract.md", "writer.py"]
    for assignment in plan["assignments"]:
        assignment["required_review_paths"] = required_review_paths
        assignment["required_checks"] = []
    plan["assignments"].append(
        {
            "assignment_id": "specialist-concurrency",
            "assignment_kind": "specialist",
            "lens_id": "concurrency",
            "reviewer_id": "concurrency-reviewer",
            "independence_group": "concurrency-process",
            "review_mode": "subagent",
            "unit_ids": ["unit-001"],
            "primary_paths": ["api.py", "writer.py"],
            "context_paths": ["contract.md"],
            "required_review_paths": required_review_paths,
            "required_checks": ["configured-output-concurrency-target-rebind"],
        }
    )
    return plan


def specialist_candidate(plan: dict) -> tuple[dict, dict]:
    specialist = next(
        assignment
        for assignment in plan["assignments"]
        if assignment["assignment_kind"] == "specialist"
    )
    result = {
        "schema_version": "material-review/candidate-set/v5",
        "scope_hash": "a" * 64,
        "coverage_plan_hash": "b" * 64,
        "coverage_context_hash": "c" * 64,
        "assignment_id": specialist["assignment_id"],
        "assignment_kind": specialist["assignment_kind"],
        "lens_id": specialist["lens_id"],
        "reviewer_id": specialist["reviewer_id"],
        "independence_group": specialist["independence_group"],
        "review_mode": specialist["review_mode"],
        "unit_ids": specialist["unit_ids"],
        "primary_paths": specialist["primary_paths"],
        "context_paths": specialist["context_paths"],
        "check_results": [
            {
                "check_code": "configured-output-concurrency-target-rebind",
                "outcome": "pass",
                "evidence": [
                    "The frozen writer retains the validated rooted handle through commit."
                ],
                "evidence_paths": ["api.py", "contract.md", "writer.py"],
                "finding_local_ids": [],
            }
        ],
        "findings": [],
        "coverage": {
            "files_reviewed": ["api.py", "contract.md", "writer.py"],
            "areas": ["concurrency"],
            "limitations": [],
        },
    }
    return specialist, result


class ObligationContractTest(unittest.TestCase):
    def test_v4_plan_binds_atomic_specialist_scenario_and_exact_path_authority(self) -> None:
        normalized = validate_coverage_contract(
            make_v4_specialist_plan(),
            changed_paths={"api.py", "writer.py"},
            allowed_context_paths={"contract.md"},
        )

        specialist = next(
            assignment
            for assignment in normalized["assignments"]
            if assignment["assignment_kind"] == "specialist"
        )
        self.assertEqual(
            specialist["required_review_paths"],
            ["api.py", "contract.md", "writer.py"],
        )
        self.assertEqual(
            specialist["required_checks"],
            ["configured-output-concurrency-target-rebind"],
        )
        scenario = next(
            decision
            for decision in normalized["change_units"][0]["specialist_decisions"]
            if decision["lens_id"] == "concurrency"
        )["scenario_checks"][0]
        self.assertEqual(
            scenario["evidence_paths"],
            ["api.py", "contract.md", "writer.py"],
        )

    def test_specialist_scenarios_reject_generic_or_unauthorized_evidence(self) -> None:
        def selected_scenario(plan: dict) -> dict:
            return next(
                decision
                for decision in plan["change_units"][0]["specialist_decisions"]
                if decision["lens_id"] == "concurrency"
            )["scenario_checks"][0]

        cases = (
            (
                "bounded claim",
                lambda plan: selected_scenario(plan).update(claim="full_depth"),
            ),
            (
                "bounded claim",
                lambda plan: selected_scenario(plan).update(claim="review concurrency"),
            ),
            (
                "bounded countercontrol",
                lambda plan: selected_scenario(plan).update(
                    countercontrol="inspect reliability"
                ),
            ),
            (
                "outside the change unit",
                lambda plan: selected_scenario(plan).update(
                    evidence_paths=["outside.py"]
                ),
            ),
        )
        for expected, mutate in cases:
            plan = make_v4_specialist_plan()
            mutate(plan)
            with self.subTest(expected=expected), self.assertRaisesRegex(
                ObligationContractError,
                expected,
            ):
                validate_coverage_contract(
                    plan,
                    changed_paths={"api.py", "writer.py"},
                    allowed_context_paths={"contract.md"},
                )

    def test_v5_specialist_result_requires_exact_checks_and_reviewed_evidence_paths(self) -> None:
        plan = validate_coverage_contract(
            make_v4_specialist_plan(),
            changed_paths={"api.py", "writer.py"},
            allowed_context_paths={"contract.md"},
        )
        specialist, result = specialist_candidate(plan)

        normalized = validate_assignment_result(
            result,
            assignment=specialist,
            obligation=None,
        )

        self.assertEqual(normalized["check_results"], result["check_results"])
        self.assertEqual(
            normalized["coverage"]["files_reviewed"],
            specialist["required_review_paths"],
        )

    def test_v5_result_rejects_incomplete_or_misattributed_scenario_evidence(self) -> None:
        plan = validate_coverage_contract(
            make_v4_specialist_plan(),
            changed_paths={"api.py", "writer.py"},
            allowed_context_paths={"contract.md"},
        )
        specialist, result = specialist_candidate(plan)
        cases = (
            (
                "required checks",
                lambda value: value.update(check_results=[]),
            ),
            (
                "exactly once",
                lambda value: value["check_results"].append(
                    copy.deepcopy(value["check_results"][0])
                ),
            ),
            (
                "review every required_review_path",
                lambda value: value["coverage"].update(
                    files_reviewed=["api.py", "writer.py"]
                ),
            ),
            (
                "outside required_review_paths",
                lambda value: value["check_results"][0].update(
                    evidence_paths=["outside.py"]
                ),
            ),
            (
                "must name blocked results",
                lambda value: value["coverage"].update(
                    limitations=[
                        {
                            "description": "The required interleaving is unavailable.",
                            "related_check_codes": [
                                "configured-output-concurrency-target-rebind"
                            ],
                        }
                    ]
                ),
            ),
        )
        for expected, mutate in cases:
            invalid = copy.deepcopy(result)
            mutate(invalid)
            with self.subTest(expected=expected), self.assertRaisesRegex(
                ObligationContractError,
                expected,
            ):
                validate_assignment_result(
                    invalid,
                    assignment=specialist,
                    obligation=None,
                )

        blocked = copy.deepcopy(result)
        blocked["check_results"][0]["outcome"] = "blocked"
        blocked["coverage"]["limitations"] = [
            {
                "description": "The required interleaving is unavailable.",
                "related_check_codes": [
                    "configured-output-concurrency-target-rebind"
                ],
            }
        ]
        normalized = validate_assignment_result(
            blocked,
            assignment=specialist,
            obligation=None,
        )
        self.assertEqual(normalized["check_results"][0]["outcome"], "blocked")

    def test_controlled_risk_requirements_are_complete(self) -> None:
        self.assertEqual(
            set(RISK_REQUIREMENTS),
            {
                "verification_mechanism_semantics",
                "machine_contract_semantics",
                "distribution_contract_integrity",
                "normative_workflow_coherence",
                "user_selectable_output_paths",
                "persisted_config_semantics",
            },
        )
        self.assertEqual(set(RISK_REQUIREMENTS), set(CONTROLLED_RISK_CODES))
        self.assertEqual(CORE_LENS_IDS, {"correctness", "standards_alignment", "test_adequacy"})
        self.assertEqual(
            ASSIGNMENT_KINDS,
            {"core", "obligation", "supplemental", "specialist"},
        )
        self.assertEqual(CHECK_OUTCOMES, {"pass", "finding_emitted", "blocked"})
        for requirement in RISK_REQUIREMENTS.values():
            self.assertTrue(requirement["required_lens"])
            self.assertTrue(requirement["required_checks"])
        self.assertEqual(
            RISK_REQUIREMENTS["machine_contract_semantics"]["required_checks"],
            frozenset(
                {
                    "schema_runtime_parity",
                    "canonical_git_path_language",
                    "required_value_cardinality",
                    "privileged_field_type_exactness",
                }
            ),
        )
        self.assertEqual(
            RISK_REQUIREMENTS["normative_workflow_coherence"]["required_checks"],
            frozenset(
                {
                    "normative_sequence",
                    "prerequisite_before_dependent_step",
                    "paired_control",
                    "disabled_mode_dependency_boundary",
                }
            ),
        )
        self.assertEqual(
            RISK_REQUIREMENTS["user_selectable_output_paths"]["required_checks"],
            frozenset(
                {
                    "destination_collision",
                    "canonical_filesystem_identity",
                    "runtime_writer_target_inventory",
                    "runtime_target_derivation_parity",
                    "validation_to_mutation_identity_stability",
                    "writer_cleanup_order",
                }
            ),
        )

    def test_canonical_git_path_rejects_non_repository_spellings(self) -> None:
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
            "a/./x.py",
            ".git/config",
            "x.py/",
            " x.py",
            "x.py ",
            "\ufeffx.py",
            "x.py\x00",
            "",
        )
        for value in rejected:
            with self.subTest(value=value), self.assertRaises(ObligationContractError):
                canonical_git_path(value, "path")
        for value in ("x.py", "nested/path.json", "résumé.md", "name:part.txt"):
            with self.subTest(canonical=value):
                self.assertEqual(canonical_git_path(value, "path"), value)

    def test_changed_paths_form_one_exact_primary_partition(self) -> None:
        plan = make_plan(primary_paths=("b.py", "a.py"), context_paths=("owner.py",))
        normalized = validate_coverage_contract(
            plan,
            changed_paths={"a.py", "b.py"},
            allowed_context_paths={"owner.py"},
        )
        self.assertEqual(
            {path for unit in normalized["change_units"] for path in unit["primary_paths"]},
            {"a.py", "b.py"},
        )
        self.assertEqual(normalized["change_units"][0]["primary_paths"], ["a.py", "b.py"])

        for mutation, message in (
            (
                lambda value: value["change_units"][0].update(
                    primary_paths=["a.py"], affected_consumers=["owner.py"]
                ),
                "exact primary partition",
            ),
            (
                lambda value: value["change_units"].append(
                    {
                        **copy.deepcopy(value["change_units"][0]),
                        "unit_id": "unit-002",
                        "primary_paths": ["a.py"],
                        "affected_consumers": ["owner.py"],
                    }
                ),
                "exact primary partition",
            ),
        ):
            invalid = make_plan(primary_paths=("a.py", "b.py"), context_paths=("owner.py",))
            mutation(invalid)
            with self.subTest(message=message), self.assertRaisesRegex(ObligationContractError, message):
                validate_coverage_contract(
                    invalid,
                    changed_paths={"a.py", "b.py"},
                    allowed_context_paths={"owner.py"},
                )

    def test_positive_risk_requires_exactly_one_obligation_and_assignment(self) -> None:
        def remove_obligation(value: dict) -> None:
            value["review_obligations"] = []

        def duplicate_obligation(value: dict) -> None:
            duplicate = copy.deepcopy(value["review_obligations"][0])
            duplicate["obligation_id"] += "-duplicate"
            value["review_obligations"].append(duplicate)

        def remove_assignment(value: dict) -> None:
            value["assignments"] = [
                item for item in value["assignments"] if item["assignment_kind"] != "obligation"
            ]

        def duplicate_assignment(value: dict) -> None:
            duplicate = copy.deepcopy(value["assignments"][-1])
            duplicate["assignment_id"] += "-duplicate"
            value["assignments"].append(duplicate)

        for mutation in (
            remove_obligation,
            duplicate_obligation,
            remove_assignment,
            duplicate_assignment,
        ):
            plan = make_plan()
            mutation(plan)
            with self.subTest(mutation=mutation.__name__), self.assertRaises(ObligationContractError):
                validate_coverage_contract(
                    plan,
                    changed_paths={"validator.py"},
                    allowed_context_paths={"runtime.py"},
                )

    def test_low_risk_plan_has_only_three_core_assignments(self) -> None:
        plan = validate_coverage_contract(
            make_plan(risk_code=None, primary_paths=("readme.md",), context_paths=()),
            changed_paths={"readme.md"},
            allowed_context_paths=set(),
        )
        self.assertEqual(
            [item["assignment_id"] for item in plan["assignments"]],
            ["core-correctness", "core-standards", "core-tests"],
        )
        self.assertEqual(plan["review_obligations"], [])
        self.assertEqual(
            {item["risk_code"] for item in plan["change_units"][0]["rejected_risk_rationale"]},
            set(CONTROLLED_RISK_CODES),
        )

    def test_risk_decisions_lenses_checks_and_context_fail_closed(self) -> None:
        mutations = {
            "unknown risk code": lambda value: value["change_units"][0]["risk_codes"].append("unknown"),
            "exhaustive risk decisions": lambda value: value["change_units"][0]["rejected_risk_rationale"].pop(),
            "required lens": lambda value: value["review_obligations"][0].update(required_lens="correctness"),
            "required checks": lambda value: value["review_obligations"][0][
                "required_checks"
            ].remove("privileged_field_type_exactness"),
            "allowed context paths": lambda value: value["change_units"][0].update(context_paths=["untracked.py"]),
        }
        for expected, mutation in mutations.items():
            plan = make_plan()
            mutation(plan)
            with self.subTest(expected=expected), self.assertRaisesRegex(ObligationContractError, expected):
                validate_coverage_contract(
                    plan,
                    changed_paths={"validator.py"},
                    allowed_context_paths={"runtime.py"},
                )

    def test_atomic_recall_checks_cannot_be_omitted(self) -> None:
        cases = (
            ("normative_workflow_coherence", "disabled_mode_dependency_boundary"),
            ("user_selectable_output_paths", "canonical_filesystem_identity"),
            ("user_selectable_output_paths", "runtime_writer_target_inventory"),
            ("user_selectable_output_paths", "runtime_target_derivation_parity"),
            (
                "user_selectable_output_paths",
                "validation_to_mutation_identity_stability",
            ),
        )
        for risk_code, check_code in cases:
            plan = make_plan(risk_code=risk_code)
            plan["review_obligations"][0]["required_checks"] = [
                item
                for item in plan["review_obligations"][0]["required_checks"]
                if item != check_code
            ]
            with self.subTest(check_code=check_code), self.assertRaisesRegex(
                ObligationContractError,
                "required checks",
            ):
                validate_coverage_contract(
                    plan,
                    changed_paths={"validator.py"},
                    allowed_context_paths={"runtime.py"},
                )

    def test_assignment_results_enforce_identity_and_check_outcomes(self) -> None:
        plan = validate_coverage_contract(
            make_plan(),
            changed_paths={"validator.py"},
            allowed_context_paths={"runtime.py"},
        )
        assignment = next(
            item for item in plan["assignments"] if item["assignment_kind"] == "obligation"
        )
        obligation = plan["review_obligations"][0]
        result = {
            "schema_version": "material-review/candidate-set/v5",
            "scope_hash": "a" * 64,
            "coverage_plan_hash": "b" * 64,
            "coverage_context_hash": "c" * 64,
            "assignment_id": assignment["assignment_id"],
            "assignment_kind": "obligation",
            "obligation_id": obligation["obligation_id"],
            "lens_id": assignment["lens_id"],
            "reviewer_id": assignment["reviewer_id"],
            "independence_group": assignment["independence_group"],
            "review_mode": assignment["review_mode"],
            "check_results": [
                {
                    "check_code": check_code,
                    "outcome": "pass",
                    "evidence": [f"Observed {check_code} against the frozen contract."],
                    "evidence_paths": assignment["required_review_paths"],
                    "finding_local_ids": [],
                }
                for check_code in obligation["required_checks"]
            ],
            "findings": [],
            "coverage": {
                "files_reviewed": ["validator.py", "runtime.py"],
                "areas": [assignment["lens_id"]],
                "limitations": [],
            },
        }
        normalized = validate_assignment_result(
            result,
            assignment=assignment,
            obligation=obligation,
        )
        self.assertEqual(
            [item["check_code"] for item in normalized["check_results"]],
            sorted(obligation["required_checks"]),
        )

        mutations = {
            "assignment identity": lambda value: value.update(reviewer_id="other"),
            "required checks": lambda value: value["check_results"].pop(),
            "pass requires evidence": lambda value: value["check_results"][0].update(evidence=[]),
            "finding_emitted requires finding_local_ids": lambda value: value["check_results"][0].update(
                outcome="finding_emitted", finding_local_ids=[]
            ),
        }
        for expected, mutation in mutations.items():
            invalid = copy.deepcopy(result)
            mutation(invalid)
            with self.subTest(expected=expected), self.assertRaisesRegex(ObligationContractError, expected):
                validate_assignment_result(
                    invalid,
                    assignment=assignment,
                    obligation=obligation,
                )

        reused_finding = copy.deepcopy(result)
        reused_finding["findings"] = [{"local_id": "one-finding"}]
        for check in reused_finding["check_results"][:2]:
            check.update(
                outcome="finding_emitted",
                finding_local_ids=["one-finding"],
            )
        with self.assertRaisesRegex(
            ObligationContractError,
            "one finding_local_id cannot discharge multiple required checks",
        ):
            validate_assignment_result(
                reused_finding,
                assignment=assignment,
                obligation=obligation,
            )

        blocked = copy.deepcopy(result)
        blocked["check_results"][0].update(
            outcome="blocked",
            evidence=["The comparison-tree schema could not be loaded."],
        )
        self.assertEqual(
            validate_assignment_result(
                blocked,
                assignment=assignment,
                obligation=obligation,
            )["check_results"][0]["outcome"],
            "blocked",
        )

    def test_candidate_local_id_length_matches_v5_schema(self) -> None:
        schema = json.loads(
            (SKILL_ROOT / "schemas" / "candidate-set-v5.schema.json").read_text(
                encoding="utf-8"
            )
        )
        schema_limit = schema["$defs"]["finding"]["properties"]["local_id"][
            "maxLength"
        ]
        self.assertEqual(CANDIDATE_LOCAL_ID_MAX_LENGTH, schema_limit)

        plan = validate_coverage_contract(
            make_plan(),
            changed_paths={"validator.py"},
            allowed_context_paths={"runtime.py"},
        )
        assignment = next(
            item for item in plan["assignments"] if item["assignment_kind"] == "obligation"
        )
        obligation = plan["review_obligations"][0]

        def result_with_local_id(local_id: str) -> dict:
            result = {
                "schema_version": "material-review/candidate-set/v5",
                "scope_hash": "a" * 64,
                "coverage_plan_hash": "b" * 64,
                "coverage_context_hash": "c" * 64,
                "assignment_id": assignment["assignment_id"],
                "assignment_kind": "obligation",
                "obligation_id": obligation["obligation_id"],
                "lens_id": assignment["lens_id"],
                "reviewer_id": assignment["reviewer_id"],
                "independence_group": assignment["independence_group"],
                "review_mode": assignment["review_mode"],
                "check_results": [
                    {
                        "check_code": check_code,
                        "outcome": (
                            "finding_emitted" if index == 0 else "pass"
                        ),
                        "evidence": ["The frozen comparison contains a material defect."],
                        "evidence_paths": assignment["required_review_paths"],
                        "finding_local_ids": [local_id] if index == 0 else [],
                    }
                    for index, check_code in enumerate(obligation["required_checks"])
                ],
                "findings": [{"local_id": local_id}],
                "coverage": {
                    "files_reviewed": ["validator.py", "runtime.py"],
                    "areas": [assignment["lens_id"]],
                    "limitations": [],
                },
            }
            return result

        accepted = "a" * CANDIDATE_LOCAL_ID_MAX_LENGTH
        normalized = validate_assignment_result(
            result_with_local_id(accepted), assignment=assignment, obligation=obligation
        )
        self.assertEqual(normalized["findings"][0]["local_id"], accepted)
        self.assertEqual(
            normalized["check_results"][0]["finding_local_ids"], [accepted]
        )

        rejected = "a" * (CANDIDATE_LOCAL_ID_MAX_LENGTH + 1)
        with self.assertRaisesRegex(ObligationContractError, "at most 128 characters"):
            validate_assignment_result(
                result_with_local_id(rejected), assignment=assignment, obligation=obligation
            )

    def test_core_assignment_result_requires_empty_checks_and_no_obligation(self) -> None:
        plan = validate_coverage_contract(
            make_plan(risk_code=None, primary_paths=("readme.md",), context_paths=()),
            changed_paths={"readme.md"},
            allowed_context_paths=set(),
        )
        assignment = plan["assignments"][0]
        result = {
            "schema_version": "material-review/candidate-set/v5",
            "scope_hash": "a" * 64,
            "coverage_plan_hash": "b" * 64,
            "coverage_context_hash": "c" * 64,
            "assignment_id": assignment["assignment_id"],
            "assignment_kind": "core",
            "lens_id": assignment["lens_id"],
            "reviewer_id": assignment["reviewer_id"],
            "independence_group": assignment["independence_group"],
            "review_mode": assignment["review_mode"],
            "check_results": [],
            "findings": [],
            "coverage": {
                "files_reviewed": ["readme.md"],
                "areas": [assignment["lens_id"]],
                "limitations": [],
            },
        }
        normalized = validate_assignment_result(result, assignment=assignment, obligation=None)
        self.assertEqual(normalized["check_results"], [])
        self.assertEqual(required_assignment_ids(plan), {item[0] for item in CORE_ASSIGNMENTS})

        with_obligation = copy.deepcopy(result)
        with_obligation["obligation_id"] = "unexpected"
        with self.assertRaisesRegex(ObligationContractError, "obligation_id"):
            validate_assignment_result(with_obligation, assignment=assignment, obligation=None)

    def test_new_schema_paths_match_runtime_path_language(self) -> None:
        schemas = [
            json.loads((SKILL_ROOT / "schemas" / name).read_text(encoding="utf-8"))
            for name in ("coverage-plan-v4.schema.json", "candidate-set-v5.schema.json")
        ]
        self.assertEqual(
            [schema["$id"] for schema in schemas],
            ["material-review/coverage-plan/v4", "material-review/candidate-set/v5"],
        )
        patterns = [schema["$defs"]["repositoryRelativeGitPath"]["pattern"] for schema in schemas]
        self.assertEqual(patterns[0], patterns[1])
        for value in ("x.py", "nested/path.json", "résumé.md", "name:part.txt"):
            self.assertIsNotNone(re.fullmatch(patterns[0], value), value)
            self.assertEqual(canonical_git_path(value, "path"), value)
        for value in ("../x.py", "./x.py", "C:/x.py", "C:x.py", "a\\x.py", "/x.py", "a//x.py"):
            self.assertIsNone(re.fullmatch(patterns[0], value), value)
            with self.assertRaises(ObligationContractError):
                canonical_git_path(value, "path")

    def test_candidate_v3_preserves_existing_finding_constraints(self) -> None:
        candidate_v2 = json.loads(
            (SKILL_ROOT / "schemas" / "candidate-set-v2.schema.json").read_text(
                encoding="utf-8"
            )
        )
        candidate_v3 = json.loads(
            (SKILL_ROOT / "schemas" / "candidate-set-v3.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            candidate_v3["$defs"]["finding"].get("allOf"),
            candidate_v2["properties"]["findings"]["items"]["allOf"],
        )

    def test_v4_coverage_and_v5_candidate_schemas_publish_specialist_contract(self) -> None:
        coverage = json.loads(
            (SKILL_ROOT / "schemas" / "coverage-plan-v4.schema.json").read_text(
                encoding="utf-8"
            )
        )
        candidate = json.loads(
            (SKILL_ROOT / "schemas" / "candidate-set-v5.schema.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            coverage["properties"]["schema_version"]["const"],
            "material-review/coverage-plan/v4",
        )
        self.assertEqual(
            candidate["properties"]["schema_version"]["const"],
            "material-review/candidate-set/v5",
        )
        self.assertIn("specialist", coverage["$defs"]["assignment"]["properties"]["assignment_kind"]["enum"])
        self.assertIn("specialist", candidate["properties"]["assignment_kind"]["enum"])
        change_unit = coverage["properties"]["change_units"]["items"]
        self.assertTrue(
            {"canonical_owner", "affected_consumers"}.issubset(change_unit["required"])
        )
        self.assertIn(
            "scenario_checks",
            coverage["$defs"]["specialistDecision"]["required"],
        )
        self.assertEqual(
            set(coverage["$defs"]["specialistLens"]["enum"]),
            {
                "security_privacy",
                "reliability",
                "api_contract",
                "migration_deployment",
                "concurrency",
                "performance",
                "documentation",
                "architecture_simplification",
            },
        )
        self.assertEqual(candidate["$defs"]["identifier"], coverage["$defs"]["identifier"])
        identifier_pattern = candidate["$defs"]["identifier"]["pattern"]
        self.assertEqual(identifier_pattern, IDENTIFIER_PATTERN.pattern)
        for value in ("a", "a" * 128, "a-1"):
            self.assertIsNotNone(re.fullmatch(identifier_pattern, value), value)
        for value in ("", "1a", "A", "a_b", "a" * 129):
            self.assertIsNone(re.fullmatch(identifier_pattern, value), value)

        specialist_branch = next(
            branch
            for clause in coverage["properties"]["assignments"]["items"]["allOf"]
            for branch in clause.get("oneOf", [])
            if branch["properties"]["assignment_kind"].get("const") == "specialist"
        )
        unit_ids = specialist_branch["properties"]["unit_ids"]
        self.assertIn("unit_ids", specialist_branch["required"])
        self.assertEqual(unit_ids["minItems"], 1)
        self.assertIs(unit_ids["uniqueItems"], True)
        self.assertEqual(unit_ids["items"]["$ref"], "#/$defs/identifier")

        specialist_condition = next(
            condition
            for condition in candidate["allOf"]
            if condition["if"]["properties"]["assignment_kind"].get("const")
            == "specialist"
        )
        candidate_unit_ids = candidate["properties"]["unit_ids"]
        self.assertIn("unit_ids", specialist_condition["then"]["required"])
        self.assertEqual(
            specialist_condition["then"]["properties"]["check_results"]["minItems"],
            1,
        )
        obligation_condition = next(
            condition
            for condition in candidate["allOf"]
            if condition["if"]["properties"]["assignment_kind"].get("const")
            == "obligation"
        )
        self.assertNotIn("properties", obligation_condition["else"])
        self.assertEqual(candidate_unit_ids["minItems"], 1)
        self.assertIs(candidate_unit_ids["uniqueItems"], True)
        self.assertEqual(candidate_unit_ids["items"]["$ref"], "#/$defs/identifier")
        self.assertEqual(
            set(candidate["$defs"]["limitation"]["required"]),
            {"description", "related_check_codes"},
        )

    def test_obligation_corpus_fixture_uses_complete_versioned_contracts(self) -> None:
        corpus = json.loads(
            (Path(__file__).resolve().parent / "fixtures" / "obligation-corpus.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            corpus["schema_version"], "material-review/obligation-corpus/v1"
        )
        required_candidate_fields = {
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
        }
        for case in corpus["cases"]:
            with self.subTest(case=case["case_id"]):
                self.assertEqual(
                    case["valid_plan"]["schema_version"],
                    "material-review/coverage-plan/v4",
                )
                for candidate in case["valid_candidate_sets"]:
                    expected_fields = set(required_candidate_fields)
                    if candidate["assignment_kind"] == "obligation":
                        expected_fields.add("obligation_id")
                    self.assertEqual(set(candidate), expected_fields)
                    self.assertEqual(
                        candidate["schema_version"],
                        "material-review/candidate-set/v5",
                    )
                    for check in candidate["check_results"]:
                        self.assertTrue(check["evidence_paths"])
                        for evidence in check["evidence"]:
                            self.assertNotIn(case["expected_defect"], evidence)
                self.assertEqual(
                    {item["mutation"] for item in case["negative_mutations"]},
                    {
                        "wrong_lens",
                        "omitted_check",
                        "compound_assignment",
                        "blocked_result",
                        "stale_context",
                        "semantic_bypass",
                    },
                )

    def test_auto_specialists_bind_selected_units_and_exact_primary_path_union(self) -> None:
        plan = make_plan(risk_code=None, primary_paths=("api.py",), context_paths=("contract.md",))
        plan["schema_version"] = "material-review/coverage-plan/v4"
        plan["depth"] = "auto"
        decisions = [
            {
                "lens_id": lens_id,
                "decision": "selected" if lens_id == "security_privacy" else "rejected",
                "basis": "ambiguous" if lens_id == "security_privacy" else "behavior_evidence",
                "evidence": [
                    "The changed request parser has incomplete trust-boundary evidence."
                    if lens_id == "security_privacy"
                    else f"The changed behavior does not trigger the {lens_id} lens."
                ],
                "scenario_checks": (
                    [
                        {
                            "check_code": "request_parser-trust-boundary",
                            "claim": "The request parser preserves the validated trust boundary through dispatch.",
                            "evidence_paths": ["api.py", "contract.md"],
                            "countercontrol": "Supply an input that changes trust classification after parsing and before dispatch.",
                        }
                    ]
                    if lens_id == "security_privacy"
                    else []
                ),
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
        ]
        plan["change_units"][0]["specialist_decisions"] = decisions
        plan["assignments"].append(
            {
                "assignment_id": "specialist-security-privacy",
                "assignment_kind": "specialist",
                "lens_id": "security_privacy",
                "reviewer_id": "security-reviewer",
                "independence_group": "security-process",
                "review_mode": "subagent",
                "unit_ids": ["unit-001"],
                "primary_paths": ["api.py"],
                "context_paths": ["contract.md"],
                "required_review_paths": ["api.py", "contract.md"],
                "required_checks": ["request_parser-trust-boundary"],
            }
        )

        normalized = validate_coverage_contract(
            plan,
            changed_paths={"api.py"},
            allowed_context_paths={"contract.md"},
        )

        specialist = next(
            item for item in normalized["assignments"] if item["assignment_kind"] == "specialist"
        )
        self.assertEqual(specialist["unit_ids"], ["unit-001"])
        self.assertEqual(specialist["primary_paths"], ["api.py"])
        self.assertEqual(specialist["context_paths"], ["contract.md"])

        candidate = {
            "schema_version": "material-review/candidate-set/v5",
            "scope_hash": "a" * 64,
            "coverage_plan_hash": "b" * 64,
            "coverage_context_hash": "c" * 64,
            "assignment_id": specialist["assignment_id"],
            "assignment_kind": "specialist",
            "lens_id": specialist["lens_id"],
            "reviewer_id": specialist["reviewer_id"],
            "independence_group": specialist["independence_group"],
            "review_mode": specialist["review_mode"],
            "unit_ids": specialist["unit_ids"],
            "primary_paths": specialist["primary_paths"],
            "context_paths": specialist["context_paths"],
            "check_results": [
                {
                    "check_code": "request_parser-trust-boundary",
                    "outcome": "pass",
                    "evidence": ["The frozen parser retains the validated trust classification."],
                    "evidence_paths": ["api.py", "contract.md"],
                    "finding_local_ids": [],
                }
            ],
            "findings": [],
            "coverage": {
                "files_reviewed": ["api.py", "contract.md"],
                "areas": ["security_privacy"],
                "limitations": [],
            },
        }
        normalized_candidate = validate_assignment_result(
            candidate,
            assignment=specialist,
            obligation=None,
        )
        self.assertEqual(normalized_candidate["unit_ids"], ["unit-001"])
        self.assertEqual(normalized_candidate["primary_paths"], ["api.py"])
        self.assertEqual(normalized_candidate["context_paths"], ["contract.md"])
        self.assertEqual(
            [item["check_code"] for item in normalized_candidate["check_results"]],
            ["request_parser-trust-boundary"],
        )

        for name, mutate, expected_error in (
            (
                "wrong-unit",
                lambda value: value.update({"unit_ids": ["unit-other"]}),
                "identity mismatch for unit_ids",
            ),
            (
                "wrong-primary-path",
                lambda value: value.update({"primary_paths": ["other.py"]}),
                "identity mismatch for primary_paths",
            ),
            (
                "obligation-substitution",
                lambda value: value.update({"obligation_id": "obligation-unit-001"}),
                "obligation_id",
            ),
            (
                "omitted-check",
                lambda value: value.update({"check_results": []}),
                "required checks",
            ),
        ):
            with self.subTest(name=name):
                invalid = copy.deepcopy(candidate)
                mutate(invalid)
                with self.assertRaisesRegex(ObligationContractError, expected_error):
                    validate_assignment_result(
                        invalid,
                        assignment=specialist,
                        obligation=None,
                    )

    def test_full_depth_requires_every_specialist_for_every_change_unit(self) -> None:
        plan = make_plan(risk_code=None, primary_paths=("api.py",), context_paths=())
        plan["schema_version"] = "material-review/coverage-plan/v4"
        plan["depth"] = "full"
        lenses = (
            "security_privacy",
            "reliability",
            "api_contract",
            "migration_deployment",
            "concurrency",
            "performance",
            "documentation",
            "architecture_simplification",
        )
        plan["change_units"][0]["specialist_decisions"] = [
            {
                "lens_id": lens_id,
                "decision": "selected",
                "basis": "full_depth",
                "evidence": ["Full depth selects every controlled specialist lens."],
                "scenario_checks": [
                    {
                        "check_code": f"full-depth-{lens_id.replace('_', '-')}",
                        "claim": f"The {lens_id} contract remains valid across the changed behavior boundary.",
                        "evidence_paths": ["api.py"],
                        "countercontrol": f"Exercise a {lens_id} boundary case that could falsify the claimed invariant.",
                    }
                ],
            }
            for lens_id in lenses
        ]
        plan["assignments"].extend(
            {
                "assignment_id": f"specialist-{lens_id.replace('_', '-')}",
                "assignment_kind": "specialist",
                "lens_id": lens_id,
                "reviewer_id": f"reviewer-{lens_id.replace('_', '-')}",
                "independence_group": "full-depth-process",
                "review_mode": "subagent",
                "unit_ids": ["unit-001"],
                "primary_paths": ["api.py"],
                "context_paths": [],
                "required_review_paths": ["api.py"],
                "required_checks": [f"full-depth-{lens_id.replace('_', '-')}"],
            }
            for lens_id in lenses
        )

        normalized = validate_coverage_contract(
            plan,
            changed_paths={"api.py"},
            allowed_context_paths=set(),
        )

        self.assertEqual(
            {item["lens_id"] for item in normalized["assignments"] if item["assignment_kind"] == "specialist"},
            set(lenses),
        )


if __name__ == "__main__":
    unittest.main()
