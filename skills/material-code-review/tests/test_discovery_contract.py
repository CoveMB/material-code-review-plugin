from __future__ import annotations

import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
WORKFLOW_BLOCK_START = "Discovery order is fixed:\n\n```text\n"
WORKFLOW_BLOCK_END = "\n```"
WORKFLOW_DISCOVERY_MARKERS = (
    "init",
    "context record and change-unit inventory (manual; see references/context-checklist.md)",
    'python3 "$SKILL_DIR/scripts/reviewctl.py" check-scope --repo-root .',
    "record-coverage",
    "dispatch assignments",
    "ingest one complete assignment-matched wave",
)


class DiscoveryContractTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (SKILL_DIR / relative).read_text(encoding="utf-8")

    def assert_materiality_rubric_strict_guard_states(self, rubric: str) -> None:
        self.assertRegex(
            rubric,
            r"require\s+affirmative\s+supported-state\s+authority\s+before\s+"
            r"treating\s+it\s+as\s+a\s+defect",
            "affirmative supported-state authority prerequisite",
        )
        self.assertRegex(
            rubric,
            r"Discard\s+an\s+unsupported\s+medium/low\s+claim\s+as\s+"
            r"`CONSEQUENCE_UNSUPPORTED`",
            "unsupported medium/low consequence disposition",
        )
        self.assertRegex(
            rubric,
            r"retain\s+a\s+plausible\s+blocker/high\s+claim\s+with\s+"
            r"genuinely\s+unknown\s+support\s+only\s+as",
            "blocker/high unknown-support risk condition",
        )
        self.assertRegex(
            rubric,
            r'nature="risk"',
            "blocker/high risk classification",
        )
        self.assertRegex(
            rubric,
            r"with\s+a\s+user\s+decision\s+and",
            "blocker/high risk user decision",
        )
        self.assertRegex(
            rubric,
            r"exact\s+pre-fix\s+verification",
            "blocker/high risk exact pre-fix verification",
        )
        self.assertRegex(
            rubric,
            r"does\s+not\s+authorize\s+relaxing\s+the\s+guard\s+until\s+"
            r"support\s+is\s+established",
            "no guard relaxation before support",
        )
        self.assertRegex(
            rubric,
            r"plan\s+is\s+revalidated",
            "no guard relaxation plan revalidation",
        )

    def assert_workflow_discovery_order(self, workflow: str) -> None:
        self.assertEqual(
            workflow.count(WORKFLOW_BLOCK_START),
            1,
            "workflow discovery order block must appear exactly once",
        )
        block = workflow.split(WORKFLOW_BLOCK_START, 1)[1].split(
            WORKFLOW_BLOCK_END,
            1,
        )[0]
        for marker in WORKFLOW_DISCOVERY_MARKERS:
            self.assertEqual(
                block.count(marker),
                1,
                f"workflow discovery order marker must appear exactly once: {marker}",
            )
        positions = [block.index(marker) for marker in WORKFLOW_DISCOVERY_MARKERS]
        self.assertEqual(
            positions,
            sorted(positions),
            "workflow discovery order markers must be in canonical order",
        )

    def test_discovery_contract_requires_change_units_and_obligations(self) -> None:
        text = self.read("SKILL.md")
        for marker in (
            "material-review/state/v6",
            "material-review/coverage-plan/v5",
            "material-review/candidate-set/v6",
            "material-review/candidates-normalized/v6",
            "change_units",
            "canonical_owner",
            "affected_consumers",
            "scenario_checks",
            "required_review_paths",
            "required_checks",
            "review_obligations",
            "assignment_id",
            "check_results",
            "record-coverage",
            "Missing required assignment coverage",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_obligation_guidance_covers_every_controlled_risk(self) -> None:
        guidance = self.read("references/review-obligations.md")
        expectations = {
            "verification_mechanism_semantics": (
                "adversarial_verification",
                "authoritative_parsing",
                "decoy_duplicate_resistance",
                "paired_control",
            ),
            "machine_contract_semantics": (
                "api_config_compatibility",
                "schema_runtime_parity",
                "canonical_git_path_language",
                "required_value_cardinality",
                "privileged_field_type_exactness",
            ),
            "distribution_contract_integrity": (
                "reliability",
                "manifest_reference_closure",
                "remove_one_required_entry",
                "paired_control",
            ),
            "normative_workflow_coherence": (
                "standards_alignment",
                "normative_sequence",
                "prerequisite_before_dependent_step",
                "paired_control",
                "disabled_mode_dependency_boundary",
                "no optional or disabled subsystem boundary",
            ),
            "user_selectable_output_paths": (
                "reliability",
                "destination_collision",
                "canonical_filesystem_identity",
                "runtime_writer_target_inventory",
                "writer_cleanup_order",
                "runtime_target_derivation_parity",
                "validation_to_mutation_identity_stability",
                "local or remote logical target selected at runtime",
                "no local destination is selected",
            ),
            "persisted_config_semantics": (
                "migration_data_safety",
                "accepted_shape_and_default",
                "migration_and_identity",
                "api_config_compatibility",
            ),
        }
        for risk_code, markers in expectations.items():
            with self.subTest(risk_code=risk_code):
                section = guidance.split(f"## `{risk_code}`", 1)[1].split("\n## `", 1)[0]
                for marker in markers:
                    self.assertIn(marker, section)
                self.assertIn("Positive trigger", section)
                self.assertIn("Non-trigger evidence", section)

        self.assertIn("Filenames are discovery hints only", guidance)
        self.assertIn("does not prove reviewer cognition", guidance)

        skill = self.read("SKILL.md")
        reviewer = self.read("references/reviewer-template.md")
        for text in (skill, reviewer):
            self.assertIn("Each outcome accounts only for its named check", text)
            self.assertIn(
                "A `finding_local_id` may appear in only one required check result",
                text,
            )
            self.assertIn("A finding on one check does not complete another required check", text)
            self.assertIn("related_check_codes", text)

    def test_reviewer_template_requires_assignment_matched_v6_output(self) -> None:
        reviewer = self.read("references/reviewer-template.md")
        for marker in (
            "candidate-set-v6.schema.json",
            "coverage_context_hash",
            "assignment_id",
            "assignment_kind",
            "obligation_id",
            "check_results",
            "pass",
            "finding_emitted",
            "blocked",
            "required_review_paths",
            "required_checks",
            "evidence_paths",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, reviewer)

    def test_specialist_selection_is_exhaustive_and_assignment_bound(self) -> None:
        skill = self.read("SKILL.md")
        context = self.read("references/context-checklist.md")
        reviewer = self.read("references/reviewer-template.md")
        workflow = self.read("references/workflow.md")
        roster = (
            "security_privacy",
            "reliability",
            "api_contract",
            "migration_deployment",
            "concurrency",
            "performance",
            "documentation",
            "architecture_simplification",
        )
        for lens_id in roster:
            with self.subTest(lens=lens_id):
                self.assertIn(f"`{lens_id}`", context)
        for marker in (
            "specialist_decisions",
            "selected",
            "rejected",
            "Ambiguous or unknown evidence selects the lens",
            "depth:full",
        ):
            self.assertIn(marker, context)
        for marker in (
            "unit_ids",
            "primary_paths",
            "context_paths",
            "Specialist assignments",
            "atomic check results",
            "scenario_checks",
        ):
            self.assertIn(marker, reviewer if marker != "scenario_checks" else context)
        self.assertIn("Specialists cannot satisfy core assignments or controlled obligations", skill)
        self.assertIn("specialist unit/path/scenario provenance", workflow)

    def test_workflow_discovery_order_requires_scope_check(self) -> None:
        workflow = self.read("references/workflow.md")
        self.assert_workflow_discovery_order(workflow)

        scope_check = WORKFLOW_DISCOVERY_MARKERS[2]
        missing_scope_check = workflow.replace(f"{scope_check}\n", "", 1)
        with self.assertRaisesRegex(
            AssertionError,
            "workflow discovery order marker must appear exactly once",
        ):
            self.assert_workflow_discovery_order(missing_scope_check)

        reordered_scope_check = workflow.replace(
            f"{scope_check}\nrecord-coverage\n",
            f"record-coverage\n{scope_check}\n",
            1,
        )
        with self.assertRaisesRegex(
            AssertionError,
            "workflow discovery order markers must be in canonical order",
        ):
            self.assert_workflow_discovery_order(reordered_scope_check)

    def test_targeted_lenses_define_causal_checks(self) -> None:
        reliability = self.read("references/reliability-output-integrity-lens.md")
        migration = self.read("references/persisted-config-migration-lens.md")
        for marker in (
            "pairwise resolved-destination aliasing",
            "success- and failure-path write ordering",
            "platform-specific path aliases",
            "final-target derivation",
            "last accepted validation",
        ):
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

        rubric = self.read("references/materiality-rubric.md")
        self.assert_materiality_rubric_strict_guard_states(rubric)

        mutations = (
            (
                "affirmative supported-state authority prerequisite",
                "require affirmative supported-state authority before treating it as a defect",
                "require evidence before treating it as a defect",
            ),
            (
                "unsupported medium/low consequence disposition",
                "Discard an unsupported medium/low claim as `CONSEQUENCE_UNSUPPORTED`",
                "Discard an unsupported concern",
            ),
            (
                "blocker/high unknown-support risk condition",
                "retain a plausible blocker/high claim with genuinely unknown support only as",
                "retain a plausible concern with genuinely unknown support only as",
            ),
            (
                "blocker/high risk classification",
                'nature="risk"',
                'nature="observation"',
            ),
            (
                "blocker/high risk user decision",
                "with a user decision and",
                "with an internal note and",
            ),
            (
                "blocker/high risk exact pre-fix verification",
                "exact pre-fix verification",
                "follow-up verification",
            ),
            (
                "no guard relaxation before support",
                "It does not authorize relaxing the guard until support is established",
                "It authorizes relaxing the guard before support is established",
            ),
            (
                "no guard relaxation plan revalidation",
                "plan is revalidated",
                "plan is recorded",
            ),
        )
        for requirement, original, weakened in mutations:
            with self.subTest(requirement=requirement):
                self.assertIn(original, rubric)
                weakened_rubric = rubric.replace(original, weakened, 1)
                with self.assertRaisesRegex(AssertionError, requirement):
                    self.assert_materiality_rubric_strict_guard_states(weakened_rubric)

        unrelated_prose_change = rubric.replace(
            "# Materiality and calibration rubric",
            "# Evidence and calibration rubric",
            1,
        )
        self.assert_materiality_rubric_strict_guard_states(unrelated_prose_change)

    def test_dispatch_binds_assigned_reviewer_identity(self) -> None:
        skill = self.read("SKILL.md")
        reviewer = self.read("references/reviewer-template.md")
        for text in (skill, reviewer):
            self.assertIn("assigned `reviewer_id`, `independence_group`, and `review_mode`", text)
            self.assertIn("echo those assigned values unchanged", text)
        self.assertNotIn("Use a unique `reviewer_id`", reviewer)


if __name__ == "__main__":
    unittest.main()
