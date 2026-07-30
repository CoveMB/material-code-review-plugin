from __future__ import annotations

import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]


class DiscoveryContractTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (SKILL_DIR / relative).read_text(encoding="utf-8")

    def test_skill_requires_exhaustive_coverage_before_dispatch(self) -> None:
        text = self.read("SKILL.md")
        for marker in (
            "risk_assessments", "user_selectable_output_paths", "persisted_config_semantics",
            "record-coverage", "material-review/candidate-set/v2", "Missing required review coverage",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_targeted_lenses_define_causal_checks(self) -> None:
        reliability = self.read("references/reliability-output-integrity-lens.md")
        migration = self.read("references/persisted-config-migration-lens.md")
        for marker in ("pairwise resolved-destination aliasing", "success- and failure-path write ordering", "platform-specific path aliases"):
            self.assertIn(marker, reliability)
        for marker in ("new-file default", "missing-key fallback", "explicit empty value", "external target identity"):
            self.assertIn(marker, migration)

    def test_strict_guard_rule_preserves_high_impact_uncertainty(self) -> None:
        skill = self.read("SKILL.md")
        adjudicator = self.read("references/adjudicator-template.md")
        for text in (skill, adjudicator):
            self.assertIn("A stricter guard is a defect only with affirmative supported-state evidence.", text)
            self.assertIn("CONSEQUENCE_UNSUPPORTED", text)
            self.assertIn('nature="risk"', text)
            self.assertIn("do not authorize relaxing the guard", text)


if __name__ == "__main__":
    unittest.main()
