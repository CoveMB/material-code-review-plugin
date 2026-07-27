import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reviewctl.py"
SPEC = importlib.util.spec_from_file_location("reviewctl_repair_direction_contract", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
reviewctl = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = reviewctl
SPEC.loader.exec_module(reviewctl)


def valid_direction() -> dict:
    return {
        "status": "reviewed",
        "confidence": "high",
        "root_cause": "The changed implementation violates the public contract.",
        "objective": "Restore the contract without broadening the change.",
        "smallest_safe_change": "Change only the incorrect operation.",
        "constraints_to_preserve": ["Preserve the public function signature."],
        "state_or_exception_cases": ["Negative operands retain the documented behavior."],
        "alternatives_checked": ["Changing the test was rejected because it would redefine the contract."],
        "required_test_evidence": ["A focused regression fails before the repair and passes afterward."],
        "open_user_decisions": [],
        "known_limits": [],
    }


def valid_candidate(*, risk: str = "low", related_paths: list[str] | None = None) -> dict:
    return {
        "file": "calc.py",
        "related_changed_files": related_paths or ["calc.py"],
        "estimated_fix_risk": risk,
    }


def valid_audit(*, mode: str = "independent") -> dict:
    direction = valid_direction()
    return {
        "scope_hash": "a" * 64,
        "candidate_ids": ["C001"],
        "repair_direction_hash": reviewctl.canonical_hash(direction),
        "mode": mode,
        "auditor_id": "repair-auditor",
        "independence_group": "model-b",
        "trigger": "retained_group",
        "rationale": "The direction corrects the root cause and preserves the public contract.",
        "evidence_checked": ["calc.py:2", "test_calc.py:2"],
        "counterevidence": ["Changing the test would redefine established behavior."],
    }


class RepairDirectionContractTests(unittest.TestCase):
    def test_kept_finding_requires_a_direction(self) -> None:
        with self.assertRaisesRegex(reviewctl.ReviewError, "required for a kept finding"):
            reviewctl.validate_repair_direction(None, "group.repair_direction", required=True)

    def test_discarded_finding_rejects_a_direction(self) -> None:
        with self.assertRaisesRegex(reviewctl.ReviewError, "must be null for a discarded finding"):
            reviewctl.validate_repair_direction(valid_direction(), "group.repair_direction", required=False)

    def test_direction_requires_constraints_and_causal_evidence(self) -> None:
        value = valid_direction()
        value["required_test_evidence"] = []
        with self.assertRaisesRegex(reviewctl.ReviewError, "constraints and causal test evidence"):
            reviewctl.validate_repair_direction(value, "group.repair_direction", required=True)

    def test_user_decision_status_names_the_decision(self) -> None:
        value = valid_direction()
        value["status"] = "needs_user_decision"
        with self.assertRaisesRegex(reviewctl.ReviewError, "must name the user decision"):
            reviewctl.validate_repair_direction(value, "group.repair_direction", required=True)

    def test_skill_requires_a_bound_audit_for_every_retained_group(self) -> None:
        skill_text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("#### 2.2 Provisional grouping and disposition", skill_text)
        self.assertIn("#### 2.3 Repair-direction audit", skill_text)
        self.assertIn("Require a fresh repair-direction audit for every provisionally kept group", skill_text)
        self.assertIn("canonical direction hash", skill_text)
        self.assertIn("smallest safe root-cause correction", skill_text)

    def test_valid_direction_is_normalized_without_candidate_suggestion(self) -> None:
        expected = valid_direction()
        actual = reviewctl.validate_repair_direction(expected, "group.repair_direction", required=True)
        self.assertEqual(actual, expected)
        self.assertNotIn("proposed_resolution", actual)

    def test_kept_finding_requires_a_bound_repair_audit(self) -> None:
        with self.assertRaisesRegex(reviewctl.ReviewError, "required for a kept finding"):
            reviewctl.validate_repair_audit(
                None, "group.repair_audit", required=True, scope_hash="a" * 64,
                candidate_ids=["C001"], repair_direction=valid_direction(),
                source_independence_groups=["model-a"], source_candidates=[valid_candidate()],
                category="correctness",
            )

    def test_repair_audit_rejects_mismatched_direction_hash(self) -> None:
        audit = valid_audit()
        audit["repair_direction_hash"] = "b" * 64
        with self.assertRaisesRegex(reviewctl.ReviewError, "does not match the normalized repair direction"):
            reviewctl.validate_repair_audit(
                audit, "group.repair_audit", required=True, scope_hash="a" * 64,
                candidate_ids=["C001"], repair_direction=valid_direction(),
                source_independence_groups=["model-a"], source_candidates=[valid_candidate()],
                category="correctness",
            )

    def test_independent_repair_audit_rejects_candidate_source_group(self) -> None:
        audit = valid_audit()
        audit["independence_group"] = "model-a"
        with self.assertRaisesRegex(reviewctl.ReviewError, "not independent from the candidate sources"):
            reviewctl.validate_repair_audit(
                audit, "group.repair_audit", required=True, scope_hash="a" * 64,
                candidate_ids=["C001"], repair_direction=valid_direction(),
                source_independence_groups=["model-a"], source_candidates=[valid_candidate()],
                category="correctness",
            )

    def test_controller_direct_requires_mechanically_entailed_low_risk_local_correction(self) -> None:
        audit = valid_audit(mode="controller_direct")
        with self.assertRaisesRegex(reviewctl.ReviewError, "mechanically entailed low-risk local correction"):
            reviewctl.validate_repair_audit(
                audit, "group.repair_audit", required=True, scope_hash="a" * 64,
                candidate_ids=["C001"], repair_direction=valid_direction(),
                source_independence_groups=["model-a"], source_candidates=[valid_candidate(risk="medium")],
                category="correctness",
            )
        audit["trigger"] = "mechanically_entailed_low_risk"
        actual = reviewctl.validate_repair_audit(
            audit, "group.repair_audit", required=True, scope_hash="a" * 64,
            candidate_ids=["C001"], repair_direction=valid_direction(),
            source_independence_groups=["model-a"], source_candidates=[valid_candidate()],
            category="correctness",
        )
        self.assertEqual(actual["mode"], "controller_direct")

    def test_discarded_finding_rejects_a_repair_audit(self) -> None:
        with self.assertRaisesRegex(reviewctl.ReviewError, "must be null for a discarded finding"):
            reviewctl.validate_repair_audit(
                valid_audit(), "group.repair_audit", required=False, scope_hash="a" * 64,
                candidate_ids=["C001"], repair_direction=None,
                source_independence_groups=["model-a"], source_candidates=[valid_candidate()],
                category="correctness",
            )

    def test_degraded_repair_audit_keeps_its_actual_mode(self) -> None:
        audit = valid_audit(mode="degraded_self_audit")
        actual = reviewctl.validate_repair_audit(
            audit, "group.repair_audit", required=True, scope_hash="a" * 64,
            candidate_ids=["C001"], repair_direction=valid_direction(),
            source_independence_groups=["model-a"],
            source_candidates=[valid_candidate(risk="high", related_paths=["calc.py", "api.py"])],
            category="api_contract",
        )
        self.assertEqual(actual["mode"], "degraded_self_audit")


if __name__ == "__main__":
    unittest.main()
