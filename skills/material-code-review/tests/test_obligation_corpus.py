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
                raise AssertionError(stderr.getvalue())
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
                raise AssertionError(stderr.getvalue())
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

    def apply_mutation(self, candidate_sets: list[dict], mutation: dict) -> None:
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
            selected_check()["evidence"] = []
        else:
            self.fail(f"Unknown corpus mutation: {mutation_type}")

    def assert_negative_mutations_fail_for_case(self, case: dict) -> None:
        self.assertEqual(
            {mutation["mutation"] for mutation in case["negative_mutations"]},
            {
                "wrong_lens",
                "omitted_check",
                "compound_assignment",
                "blocked_result",
                "stale_context",
                "semantic_bypass",
            },
        )
        for mutation in case["negative_mutations"]:
            with self.subTest(case=case["case_id"], mutation=mutation["name"]):
                candidate_sets = copy.deepcopy(case["valid_candidate_sets"])
                self.apply_mutation(candidate_sets, mutation)
                with self.assertRaisesRegex(
                    (ObligationContractError, reviewctl.ReviewError),
                    mutation["expected_error"],
                ):
                    self.normalized_case_wave(case, candidate_sets)

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

    def test_positive_corpus_uses_complete_v4_candidate_contract(self) -> None:
        schema = json.loads(
            (SKILL_ROOT / "schemas" / "candidate-set-v4.schema.json").read_text(
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
            self.assert_negative_mutations_fail_for_case(case)

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
