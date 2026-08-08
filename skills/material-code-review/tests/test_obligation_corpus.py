from __future__ import annotations

import copy
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "obligation-corpus.json"
sys.path.insert(0, str(SCRIPTS))

from obligation_contract import (  # noqa: E402
    ObligationContractError,
    RISK_REQUIREMENTS,
    check_contracts_for_assignment,
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
    @staticmethod
    def atomic_causal_case(
        source: dict,
        *,
        case_id: str,
        specialist_lens: str,
        check_code: str,
        claim: str,
        countercontrol: str,
        expected_defect: str,
    ) -> dict:
        case = copy.deepcopy(source)
        case["case_id"] = case_id
        case["expected_defect"] = expected_defect
        case["mutation_profile"] = "atomic_specialist"
        unit = case["valid_plan"]["change_units"][0]
        decision = next(
            item
            for item in unit["specialist_decisions"]
            if item["lens_id"] == specialist_lens
        )
        decision.update(
            {
                "decision": "selected",
                "basis": "high_risk_mandate",
                "evidence": [claim],
                "scenario_checks": [
                    {
                        "check_code": check_code,
                        "claim": claim,
                        "evidence_paths": sorted(
                            {*unit["primary_paths"], *unit["context_paths"]}
                        ),
                        "countercontrol": countercontrol,
                    }
                ],
            }
        )
        assignment_id = f"specialist-{specialist_lens.replace('_', '-')}"
        required_paths = sorted({*unit["primary_paths"], *unit["context_paths"]})
        assignment = {
            "assignment_id": assignment_id,
            "assignment_kind": "specialist",
            "lens_id": specialist_lens,
            "reviewer_id": f"reviewer-{specialist_lens.replace('_', '-')}",
            "independence_group": "corpus-specialist-independent",
            "review_mode": "subagent",
            "unit_ids": [unit["unit_id"]],
            "primary_paths": unit["primary_paths"],
            "context_paths": unit["context_paths"],
            "required_review_paths": required_paths,
            "required_checks": [check_code],
        }
        case["valid_plan"]["assignments"].append(assignment)
        template = case["valid_candidate_sets"][0]
        case["valid_candidate_sets"].append(
            {
            "schema_version": "material-review/candidate-set/v6",
                "scope_hash": template["scope_hash"],
                "coverage_plan_hash": template["coverage_plan_hash"],
                "coverage_context_hash": template["coverage_context_hash"],
                "assignment_id": assignment_id,
                "assignment_kind": "specialist",
                "lens_id": specialist_lens,
                "reviewer_id": assignment["reviewer_id"],
                "independence_group": assignment["independence_group"],
                "review_mode": "subagent",
                "unit_ids": assignment["unit_ids"],
                "primary_paths": assignment["primary_paths"],
                "context_paths": assignment["context_paths"],
                "check_results": [
                    {
                        "check_code": check_code,
                        "outcome": "pass",
                        "evidence": [f"The bounded control supports {claim}"],
                        "evidence_paths": required_paths,
                        "finding_local_ids": [],
                    }
                ],
                "findings": [],
                "coverage": {
                    "files_reviewed": required_paths,
                    "areas": [specialist_lens],
                    "limitations": [],
                },
            }
        )
        case["negative_mutations"] = [
            {
                "name": "omit one atomic specialist result",
                "mutation": "omitted_atomic_check",
                "target_assignment_id": assignment_id,
                "check_code": check_code,
                "expected_error": "required checks",
            },
            {
                "name": "omit a dispatched context path",
                "mutation": "unreviewed_context",
                "target_assignment_id": assignment_id,
                "expected_error": "required_review_path",
            },
            {
                "name": "remove the bounded countercontrol",
                "mutation": "missing_countercontrol_evidence",
                "target_assignment_id": assignment_id,
                "check_code": check_code,
                "expected_error": "countercontrol",
            },
            {
                "name": "return empty specialist evidence",
                "mutation": "empty_specialist_evidence",
                "target_assignment_id": assignment_id,
                "check_code": check_code,
                "expected_error": "requires evidence",
            },
            {
                "name": "submit stale coverage hashes",
                "mutation": "stale_hashes",
                "target_assignment_id": assignment_id,
                "expected_error": "coverage_context_hash",
            },
            {
                "name": "let one broad finding mask an omitted scenario",
                "mutation": "broad_finding_saturation",
                "target_assignment_id": assignment_id,
                "check_code": check_code,
                "expected_error": "one finding_local_id cannot discharge multiple required checks",
            },
        ]
        return case

    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.cases = list(cls.corpus["cases"])
        output_case = next(
            case
            for case in cls.cases
            if case["case_id"] == "output-target-identity-and-runtime-ownership"
        )
        cls.cases.extend(
            [
                cls.atomic_causal_case(
                    output_case,
                    case_id="runtime-target-derivation-parity",
                    specialist_lens="api_contract",
                    check_code="configured-target-derivation-authority",
                    claim=(
                        "Validation and execution use the same transformed and "
                        "collision-adjusted final target identity."
                    ),
                    countercontrol=(
                        "Compare equal raw labels that normalize to different final targets "
                        "and distinct raw labels that collide after final derivation."
                    ),
                    expected_defect=(
                        "Validation compares source labels while execution writes to a "
                        "transformed and collision-adjusted target."
                    ),
                ),
                cls.atomic_causal_case(
                    output_case,
                    case_id="validation-to-mutation-identity",
                    specialist_lens="concurrency",
                    check_code="validated-target-rebind-before-mutation",
                    claim=(
                        "The final mutation remains bound to the identity accepted at the "
                        "last validation point."
                    ),
                    countercontrol=(
                        "Replace the selected target or its parent after preflight and before "
                        "the final path-based mutation."
                    ),
                    expected_defect=(
                        "Preflight accepts a target that can be replaced or rebound before "
                        "a path-based final mutation."
                    ),
                ),
            ]
        )

    def normalized_case_wave(self, case: dict, candidate_sets: list[dict]) -> tuple[dict, list[dict]]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=repo, check=True
            )
            for relative_path in [*case["changed_paths"], *case["context_paths"]]:
                path = repo / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("baseline contract boundary\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
            for relative_path in case["changed_paths"]:
                (repo / relative_path).write_text(
                    "observed contract boundary\n", encoding="utf-8"
                )

            run_id = "obligation-corpus"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = reviewctl.main(
                    [
                        "init",
                        "--repo-root",
                        str(repo),
                        "--scope",
                        "uncommitted",
                        "--run-id",
                        run_id,
                    ]
                )
            if result != 0:
                raise reviewctl.ReviewError(stderr.getvalue())
            run_dir = repo / ".git" / "material-code-review" / "runs" / run_id
            state = reviewctl.load_state(run_dir)
            plan_input = copy.deepcopy(case["valid_plan"])
            plan_input["scope_hash"] = state["scope_hash"]
            plan_path = root / "coverage-plan.json"
            plan_path.write_text(json.dumps(plan_input), encoding="utf-8")
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = reviewctl.main(
                    [
                        "record-coverage",
                        "--repo-root",
                        str(repo),
                        "--run-id",
                        run_id,
                        "--input",
                        str(plan_path),
                    ]
                )
            if result != 0:
                raise reviewctl.ReviewError(stderr.getvalue())
            state = reviewctl.load_state(run_dir)
            plan = reviewctl.load_recorded_coverage_plan(run_dir, state)

            normalized = []
            fixture_candidates = {
                candidate["assignment_id"]: candidate
                for candidate in case["valid_candidate_sets"]
            }
            for index, raw_candidate in enumerate(candidate_sets):
                raw = copy.deepcopy(raw_candidate)
                fixture_candidate = fixture_candidates[raw["assignment_id"]]
                live_bindings = {
                    "scope_hash": state["scope_hash"],
                    "coverage_plan_hash": state["hashes"]["coverage_plan_hash"],
                    "coverage_context_hash": state["hashes"]["coverage_context_hash"],
                }
                for field, live_value in live_bindings.items():
                    if raw[field] == fixture_candidate[field]:
                        raw[field] = live_value
                normalized_set, rejections = reviewctl.validate_candidate_set(
                    raw,
                    source_file=root / f"candidate-{index}.json",
                    repo=repo,
                    run_dir=run_dir,
                    state=state,
                    plan=plan,
                )
                if rejections:
                    raise reviewctl.ReviewError(str(rejections[0]))
                normalized.append(normalized_set)
            reviewctl.validate_candidate_wave_against_coverage(plan, normalized)
            return plan, normalized

    def apply_mutation(self, case: dict, candidate_sets: list[dict], mutation: dict) -> None:
        target = next(
            item
            for item in candidate_sets
            if item["assignment_id"] == mutation["target_assignment_id"]
        )
        mutation_type = mutation["mutation"]
        check_code = mutation.get("check_code")

        def selected_check() -> dict:
            if check_code is None:
                return target["check_results"][0]
            return next(
                item
                for item in target["check_results"]
                if item["check_code"] == check_code
            )

        if mutation_type == "wrong_lens":
            target["lens_id"] = "correctness"
        elif mutation_type == "omitted_check":
            if check_code is None:
                target["check_results"].pop()
            else:
                target["check_results"] = [
                    item
                    for item in target["check_results"]
                    if item["check_code"] != check_code
                ]
        elif mutation_type == "compound_assignment":
            target["obligation_id"] = [target["obligation_id"], "another-obligation"]
        elif mutation_type == "blocked_result":
            check = selected_check()
            check["outcome"] = "blocked"
            check["finding_local_ids"] = []
        elif mutation_type == "stale_context":
            target["coverage_context_hash"] = "0" * 64
        elif mutation_type == "semantic_bypass":
            check = selected_check()
            if "evidence_items" in check:
                check["evidence_items"][0]["evidence"] = []
            else:
                check["evidence"] = []
        elif mutation_type == "missing_obligation_evidence_item":
            check = selected_check()
            check["evidence_items"] = [
                item
                for item in check["evidence_items"]
                if item["item_code"] != mutation["item_code"]
            ]
        elif mutation_type == "shallow_obligation_evidence_paths":
            check = selected_check()
            evidence_item = next(
                item
                for item in check["evidence_items"]
                if item["item_code"] == mutation["item_code"]
            )
            if "unassigned_path" in mutation:
                evidence_item["evidence_paths"] = [mutation["unassigned_path"]]
            else:
                evidence_item["evidence_paths"] = evidence_item["evidence_paths"][:1]
        elif mutation_type == "omitted_atomic_check":
            target["check_results"] = [
                item
                for item in target["check_results"]
                if item["check_code"] != check_code
            ]
        elif mutation_type == "unreviewed_context":
            target["coverage"]["files_reviewed"].remove(target["context_paths"][0])
        elif mutation_type == "missing_countercontrol_evidence":
            unit = case["valid_plan"]["change_units"][0]
            decision = next(
                item
                for item in unit["specialist_decisions"]
                if item["lens_id"] == target["lens_id"]
            )
            scenario = next(
                item
                for item in decision["scenario_checks"]
                if item["check_code"] == check_code
            )
            scenario["countercontrol"] = ""
        elif mutation_type == "empty_specialist_evidence":
            selected_check()["evidence"] = []
        elif mutation_type == "stale_hashes":
            target["coverage_context_hash"] = "0" * 64
        elif mutation_type == "broad_finding_saturation":
            unit = case["valid_plan"]["change_units"][0]
            decision = next(
                item
                for item in unit["specialist_decisions"]
                if item["lens_id"] == target["lens_id"]
            )
            second_code = f"{check_code}-second-control"
            decision["scenario_checks"].append(
                {
                    "check_code": second_code,
                    "claim": "A distinct final-boundary control remains independently valid.",
                    "evidence_paths": target["coverage"]["files_reviewed"],
                    "countercontrol": "Break only the second control while preserving the first.",
                }
            )
            assignment = next(
                item
                for item in case["valid_plan"]["assignments"]
                if item["assignment_id"] == target["assignment_id"]
            )
            assignment["required_checks"].append(second_code)
            finding = copy.deepcopy(
                next(
                    finding
                    for candidate in candidate_sets
                    for finding in candidate["findings"]
                )
            )
            target["findings"] = [finding]
            selected_check().update(
                outcome="finding_emitted",
                finding_local_ids=[finding["local_id"]],
            )
            target["check_results"].append(
                {
                    "check_code": second_code,
                    "outcome": "finding_emitted",
                    "evidence": [
                        "The same broad finding is asserted as evidence for a distinct control."
                    ],
                    "evidence_paths": target["coverage"]["files_reviewed"],
                    "finding_local_ids": [finding["local_id"]],
                }
            )
        else:
            self.fail(f"Unknown corpus mutation: {mutation_type}")

    def assert_negative_mutations_fail_for_case(self, case: dict) -> None:
        if case.get("mutation_profile") == "atomic_specialist":
            expected_mutations = {
                "omitted_atomic_check",
                "unreviewed_context",
                "missing_countercontrol_evidence",
                "empty_specialist_evidence",
                "stale_hashes",
                "broad_finding_saturation",
            }
        elif case.get("mutation_profile") == "atomic_obligation":
            expected_mutations = {
                "wrong_lens",
                "omitted_check",
                "compound_assignment",
                "blocked_result",
                "stale_context",
                "semantic_bypass",
                "missing_obligation_evidence_item",
                "shallow_obligation_evidence_paths",
            }
        else:
            expected_mutations = {
                "wrong_lens",
                "omitted_check",
                "compound_assignment",
                "blocked_result",
                "stale_context",
                "semantic_bypass",
            }
        self.assertEqual(
            {mutation["mutation"] for mutation in case["negative_mutations"]},
            expected_mutations,
        )
        for mutation in case["negative_mutations"]:
            with self.subTest(case=case["case_id"], mutation=mutation["name"]):
                mutated_case = copy.deepcopy(case)
                candidate_sets = copy.deepcopy(case["valid_candidate_sets"])
                self.apply_mutation(mutated_case, candidate_sets, mutation)
                with self.assertRaisesRegex(
                    (ObligationContractError, reviewctl.ReviewError),
                    mutation["expected_error"],
                ):
                    self.normalized_case_wave(mutated_case, candidate_sets)

    def test_every_missed_contract_case_requires_its_causal_obligation(self) -> None:
        self.assertEqual(
            {case["case_id"] for case in self.cases},
            {
                "version-decoy",
                "workflow-missing-scope",
                "path-schema-runtime-disagreement",
                "duplicate-required-risk-code",
                "archive-missing-contract",
                "output-target-identity-and-runtime-ownership",
                "persisted-config-shape-migration",
                "runtime-target-derivation-parity",
                "validation-to-mutation-identity",
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

    def test_changed_risk_contracts_have_exact_corpus_coverage(self) -> None:
        cases_by_risk = {
            case["risk_code"]: case
            for case in self.corpus["cases"]
        }
        for risk_code in (
            "normative_workflow_coherence",
            "user_selectable_output_paths",
        ):
            with self.subTest(risk_code=risk_code):
                self.assertIn(risk_code, cases_by_risk)
                self.assertEqual(
                    set(cases_by_risk[risk_code]["expected_checks"]),
                    set(RISK_REQUIREMENTS[risk_code]["required_checks"]),
                )

        persisted_cases = [
            case
            for case in self.corpus["cases"]
            if case["risk_code"] == "persisted_config_semantics"
        ]
        self.assertEqual(len(persisted_cases), 1)

    def test_positive_corpus_uses_complete_v6_candidate_contract(self) -> None:
        schema = json.loads(
            (SKILL_ROOT / "schemas" / "candidate-set-v6.schema.json").read_text(
                encoding="utf-8"
            )
        )
        category_enum = set(
            schema["$defs"]["finding"]["properties"]["category"]["enum"]
        )
        self.assertEqual(category_enum, set(reviewctl.CATEGORIES))
        self.assertIn("api_contract", category_enum)
        self.assertNotIn("contract", category_enum)

        for case in self.cases:
            with self.subTest(case=case["case_id"], category="api_contract"):
                self.normalized_case_wave(
                    case, copy.deepcopy(case["valid_candidate_sets"])
                )
            invalid = copy.deepcopy(case["valid_candidate_sets"])
            emitted = next(
                finding
                for candidate_set in invalid
                for finding in candidate_set["findings"]
            )
            emitted["category"] = "contract"
            with self.subTest(case=case["case_id"], category="contract"):
                with self.assertRaisesRegex(reviewctl.ReviewError, "category"):
                    self.normalized_case_wave(case, invalid)

    def test_persisted_config_contract_has_literal_causal_coverage(self) -> None:
        expected_item_scopes = (
            ("accepted_shapes", "any_required_review_path"),
            ("baseline_identity", "any_required_review_path"),
            ("comparison_identity", "any_required_review_path"),
            ("explicit_value_control", "any_required_review_path"),
            ("migration_control", "any_required_review_path"),
            ("missing_value_default", "any_required_review_path"),
        )
        persisted_cases = [
            case
            for case in self.corpus["cases"]
            if case["risk_code"] == "persisted_config_semantics"
        ]
        self.assertEqual(len(persisted_cases), 1)
        case = persisted_cases[0]
        self.assertEqual(
            tuple(
                sorted(
                    (item["item_code"], item["path_scope"])
                    for item in case["expected_evidence_contract"]
                )
            ),
            expected_item_scopes,
        )

        plan, normalized = self.normalized_case_wave(
            case,
            copy.deepcopy(case["valid_candidate_sets"]),
        )
        obligation_assignment = next(
            assignment
            for assignment in plan["assignments"]
            if assignment["assignment_kind"] == "obligation"
        )
        actual_item_scopes = tuple(
            sorted(
                (item["item_code"], item["path_scope"])
                for contract in check_contracts_for_assignment(
                    plan,
                    obligation_assignment,
                )
                for item in contract["evidence_items"]
            )
        )
        self.assertEqual(actual_item_scopes, expected_item_scopes)
        obligation_result = next(
            result
            for result in normalized
            if result["assignment_kind"] == "obligation"
        )
        self.assertEqual(
            {
                item["item_code"]
                for check in obligation_result["check_results"]
                for item in check["evidence_items"]
            },
            {item_code for item_code, _ in expected_item_scopes},
        )

        for mutation_type, expected_error in (
            ("missing_obligation_evidence_item", "required evidence items"),
            ("shallow_obligation_evidence_paths", "outside required_review_paths"),
        ):
            mutation = next(
                item
                for item in case["negative_mutations"]
                if item["mutation"] == mutation_type
                and (
                    mutation_type != "shallow_obligation_evidence_paths"
                    or "unassigned_path" in item
                )
            )
            mutated_case = copy.deepcopy(case)
            candidate_sets = copy.deepcopy(case["valid_candidate_sets"])
            self.apply_mutation(mutated_case, candidate_sets, mutation)
            with self.subTest(mutation=mutation_type):
                with self.assertRaisesRegex(
                    (ObligationContractError, reviewctl.ReviewError),
                    expected_error,
                ):
                    self.normalized_case_wave(mutated_case, candidate_sets)

    def test_every_negative_mutation_fails_for_declared_reason(self) -> None:
        for case in self.cases:
            self.assert_negative_mutations_fail_for_case(case)

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
