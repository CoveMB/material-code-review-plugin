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
    return {
        "schema_version": "material-review/coverage-plan/v2",
        "scope_hash": "a" * 64,
        "workflow_profile": "material_review",
        "change_units": [
            {
                "unit_id": "unit-001",
                "purpose": "Keep one coherent validator/runtime contract aligned.",
                "primary_paths": list(primary_paths),
                "context_paths": list(context_paths),
                "risk_codes": selected_codes,
                "selected_risk_rationale": selected,
                "rejected_risk_rationale": rejected,
            }
        ],
        "review_obligations": obligations,
        "assignments": assignments,
    }


class ObligationContractTest(unittest.TestCase):
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
        self.assertEqual(ASSIGNMENT_KINDS, {"core", "obligation", "supplemental"})
        self.assertEqual(CHECK_OUTCOMES, {"pass", "finding_emitted", "blocked"})
        for requirement in RISK_REQUIREMENTS.values():
            self.assertTrue(requirement["required_lens"])
            self.assertTrue(requirement["required_checks"])

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
            (lambda value: value["change_units"][0].update(primary_paths=["a.py"]), "exact primary partition"),
            (
                lambda value: value["change_units"].append(
                    {
                        **copy.deepcopy(value["change_units"][0]),
                        "unit_id": "unit-002",
                        "primary_paths": ["a.py"],
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
            "required checks": lambda value: value["review_obligations"][0]["required_checks"].pop(),
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
            "schema_version": "material-review/candidate-set/v3",
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

    def test_candidate_local_id_length_matches_v3_schema(self) -> None:
        schema = json.loads(
            (SKILL_ROOT / "schemas" / "candidate-set-v3.schema.json").read_text(
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
                "schema_version": "material-review/candidate-set/v3",
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
                        "outcome": "finding_emitted",
                        "evidence": ["The frozen comparison contains a material defect."],
                        "finding_local_ids": [local_id],
                    }
                    for check_code in obligation["required_checks"]
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
            "schema_version": "material-review/candidate-set/v3",
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
            for name in ("coverage-plan-v2.schema.json", "candidate-set-v3.schema.json")
        ]
        self.assertEqual(
            [schema["$id"] for schema in schemas],
            ["material-review/coverage-plan/v2", "material-review/candidate-set/v3"],
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
                    "material-review/coverage-plan/v2",
                )
                for candidate in case["valid_candidate_sets"]:
                    expected_fields = set(required_candidate_fields)
                    if candidate["assignment_kind"] == "obligation":
                        expected_fields.add("obligation_id")
                    self.assertEqual(set(candidate), expected_fields)
                    self.assertEqual(
                        candidate["schema_version"],
                        "material-review/candidate-set/v3",
                    )
                    for check in candidate["check_results"]:
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


if __name__ == "__main__":
    unittest.main()
