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

    def test_valid_direction_is_normalized_without_candidate_suggestion(self) -> None:
        expected = valid_direction()
        actual = reviewctl.validate_repair_direction(expected, "group.repair_direction", required=True)
        self.assertEqual(actual, expected)
        self.assertNotIn("proposed_resolution", actual)


if __name__ == "__main__":
    unittest.main()
