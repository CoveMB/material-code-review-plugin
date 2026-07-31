from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "obligation-corpus.json"
sys.path.insert(0, str(SCRIPTS))

from obligation_contract import (  # noqa: E402
    ObligationContractError,
    validate_assignment_result,
    validate_coverage_contract,
)


REVIEWCTL_SPEC = importlib.util.spec_from_file_location(
    "obligation_corpus_reviewctl", SCRIPTS / "reviewctl.py"
)
assert REVIEWCTL_SPEC and REVIEWCTL_SPEC.loader
reviewctl = importlib.util.module_from_spec(REVIEWCTL_SPEC)
REVIEWCTL_SPEC.loader.exec_module(reviewctl)


class ObligationCorpusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.cases = cls.corpus["cases"]

    def normalized_case_wave(self, case: dict, candidate_sets: list[dict]) -> tuple[dict, list[dict]]:
        plan = validate_coverage_contract(
            case["valid_plan"],
            changed_paths=set(case["changed_paths"]),
            allowed_context_paths=set(case["context_paths"]),
        )
        assignments = {item["assignment_id"]: item for item in plan["assignments"]}
        obligations = {
            item["obligation_id"]: item for item in plan["review_obligations"]
        }
        normalized = []
        for raw in candidate_sets:
            if raw["scope_hash"] != plan["scope_hash"]:
                raise reviewctl.ReviewError("scope_hash does not match the corpus plan")
            if raw["coverage_plan_hash"] != case["coverage_plan_hash"]:
                raise reviewctl.ReviewError("coverage_plan_hash does not match the corpus plan")
            if raw["coverage_context_hash"] != case["coverage_context_hash"]:
                raise reviewctl.ReviewError(
                    "coverage_context_hash does not match the corpus context"
                )
            assignment = assignments.get(raw["assignment_id"])
            if assignment is None:
                raise reviewctl.ReviewError("assignment_id is absent from the coverage plan")
            obligation = obligations.get(assignment.get("obligation_id"))
            normalized.append(
                validate_assignment_result(
                    raw,
                    assignment=assignment,
                    obligation=obligation,
                )
            )
        reviewctl.validate_candidate_wave_against_coverage(plan, normalized)
        return plan, normalized

    def apply_mutation(self, candidate_sets: list[dict], mutation: dict) -> None:
        target = next(
            item
            for item in candidate_sets
            if item["assignment_id"] == mutation["target_assignment_id"]
        )
        mutation_type = mutation["mutation"]
        if mutation_type == "wrong_lens":
            target["lens_id"] = "correctness"
        elif mutation_type == "omitted_check":
            target["check_results"].pop()
        elif mutation_type == "compound_assignment":
            target["obligation_id"] = [target["obligation_id"], "another-obligation"]
        elif mutation_type == "blocked_result":
            target["check_results"][0]["outcome"] = "blocked"
            target["check_results"][0]["finding_local_ids"] = []
        elif mutation_type == "stale_context":
            target["coverage_context_hash"] = "0" * 64
        elif mutation_type == "semantic_bypass":
            target["check_results"][0]["evidence"] = []
        else:
            self.fail(f"Unknown corpus mutation: {mutation_type}")

    def test_every_missed_contract_case_requires_its_causal_obligation(self) -> None:
        self.assertEqual(
            {case["case_id"] for case in self.cases},
            {
                "version-decoy",
                "workflow-missing-scope",
                "path-schema-runtime-disagreement",
                "duplicate-required-risk-code",
                "archive-missing-contract",
            },
        )
        for case in self.cases:
            with self.subTest(case=case["case_id"]):
                plan, normalized = self.normalized_case_wave(
                    case, copy.deepcopy(case["valid_candidate_sets"])
                )
                self.assertEqual(len(plan["review_obligations"]), 1)
                obligation = plan["review_obligations"][0]
                self.assertEqual(obligation["risk_code"], case["risk_code"])
                self.assertEqual(
                    set(obligation["required_checks"]), set(case["expected_checks"])
                )
                obligation_result = next(
                    item for item in normalized if item["assignment_kind"] == "obligation"
                )
                self.assertEqual(
                    {item["check_code"] for item in obligation_result["check_results"]},
                    set(case["expected_checks"]),
                )
                self.assertTrue(case["expected_defect"])

    def test_every_negative_mutation_fails_for_declared_reason(self) -> None:
        for case in self.cases:
            for mutation in case["negative_mutations"]:
                with self.subTest(case=case["case_id"], mutation=mutation["name"]):
                    candidate_sets = copy.deepcopy(case["valid_candidate_sets"])
                    self.apply_mutation(candidate_sets, mutation)
                    with self.assertRaisesRegex(
                        (ObligationContractError, reviewctl.ReviewError),
                        mutation["expected_error"],
                    ):
                        self.normalized_case_wave(case, candidate_sets)

    def test_low_risk_control_has_only_three_core_assignments(self) -> None:
        case = self.corpus["low_risk_case"]
        plan = validate_coverage_contract(
            case["valid_plan"],
            changed_paths=set(case["changed_paths"]),
            allowed_context_paths=set(),
        )
        self.assertEqual(plan["review_obligations"], [])
        self.assertEqual(
            [item["assignment_id"] for item in plan["assignments"]],
            ["core-correctness", "core-standards", "core-tests"],
        )


if __name__ == "__main__":
    unittest.main()
