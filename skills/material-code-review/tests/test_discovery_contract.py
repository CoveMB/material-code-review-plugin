from __future__ import annotations

import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SKILL_DIR.parents[1]


class DiscoveryContractTests(unittest.TestCase):
    def test_skill_names_every_discovery_control(self) -> None:
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        required = {
            "record-coverage",
            "check-candidates",
            "protocol_coherence",
            "REVIEW_INCOMPLETE",
            "one correction attempt",
            "actual pull-request base and head",
        }
        self.assertEqual(required - set(item for item in required if item in text), set())

    def test_protocol_coherence_lens_defines_required_checks(self) -> None:
        path = SKILL_DIR / "references" / "protocol-coherence-lens.md"
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        for heading in (
            "## Ordering",
            "## Information availability",
            "## State completeness",
            "## Phase-specific schemas",
            "## Non-vacuous validation",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, text)

    def test_protocol_reviewer_is_read_only_independent_and_material(self) -> None:
        path = REPOSITORY_ROOT / "agents" / "protocol-reviewer.md"
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertIn("protocol-coherence-lens.md", text)
        self.assertIn("Do not edit", text)
        self.assertIn("Do not read another reviewer's candidates", text)
        self.assertIn("low-value", text)


if __name__ == "__main__":
    unittest.main()
