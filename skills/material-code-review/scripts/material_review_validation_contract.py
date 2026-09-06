#!/usr/bin/env python3
"""Shared material-review packaging and workflow validation mechanics."""

from __future__ import annotations

from collections.abc import Callable

from package_layout_contract import normalize_package_path


ACTIVATION_DISCOVERY_DESCRIPTION = (
    "Evidence-gated review and bounded repair of a concrete Git change scope. "
    "Implicitly use only to assess uncommitted changes, a branch or diff, a local ref range, or a PR "
    "for material defects, regressions, test gaps protecting changed behavior, or merge readiness. "
    "Do not implicitly use for document or generated-output review, output diagnosis, general skill, "
    "plugin, or repository analysis, architecture exploration, or planning-only work."
)
ACTIVATION_SHORT_DESCRIPTION = "Material-defect review of Git changes"
ACTIVATION_PREFLIGHT_MARKERS = (
    "## Activation eligibility preflight",
    "**Implicit eligibility requires both conditions in the prompt itself.**",
    "**Context cannot create eligibility.**",
    "**Fail closed before initialization.**",
)
CONTROLLED_WORKFLOW_MARKERS = (
    "material-review/state/v6",
    "material-review/coverage-plan/v5",
    "material-review/candidate-set/v6",
    "material-review/candidates-normalized/v6",
    "canonical_owner",
    "affected_consumers",
    "scenario_checks",
    "required_review_paths",
    "required_checks",
    "change_units",
    "review_obligations",
    "assignment_id",
    "check_results",
    "record-coverage",
    "user_selectable_output_paths",
    "persisted_config_semantics",
    "runtime_target_derivation_parity",
    "validation_to_mutation_identity_stability",
    "Missing required assignment coverage",
    "CONSEQUENCE_UNSUPPORTED",
    "plausibly blocker/high",
)
OBLIGATION_WORKFLOW_BLOCK_START = (
    "<!-- material-review-obligation-workflow-contract:start -->"
)
OBLIGATION_WORKFLOW_BLOCK_END = (
    "<!-- material-review-obligation-workflow-contract:end -->"
)
OBLIGATION_WORKFLOW_CONTRACT_LINES = (
    "check_contracts=controller-derived",
    "obligation_check_results=evidence_items",
    "obligation_evidence_paths=all_required_review_paths",
)
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
LAYOUT_NAMES = ("full-plugin", "standalone")


def normalize_review_layout(
    layout_name: str,
    layout: object,
    *,
    path_label: str,
    validate_mapping: Callable[[str, str], None] | None = None,
    enforce_unique_mappings: bool = True,
    require_canonical_destination: bool = True,
) -> dict[str, object]:
    """Normalize one review layout while preserving consumer policy ordering."""

    if not isinstance(layout, dict):
        raise ValueError(f"layout {layout_name} must be an object")
    canonical_skill = normalize_package_path(
        layout.get("canonical_skill"),
        f"{path_label} canonical skill for {layout_name}",
    )
    mappings = layout.get("required_mappings")
    if not isinstance(mappings, list) or not mappings:
        raise ValueError(
            f"layout {layout_name} required_mappings must be a non-empty array"
        )

    seen_sources: set[str] = set()
    seen_destinations: set[str] = set()
    normalized_mappings: list[dict[str, str]] = []
    for index, mapping in enumerate(mappings):
        if not isinstance(mapping, dict) or set(mapping) != {
            "source",
            "destination",
        }:
            raise ValueError(
                f"layout {layout_name} mapping {index} must contain source and destination"
            )
        source = normalize_package_path(mapping["source"], f"{path_label} source")
        destination = normalize_package_path(
            mapping["destination"],
            f"{path_label} destination",
        )
        if enforce_unique_mappings:
            if source in seen_sources:
                raise ValueError(f"duplicate {path_label} source: {source}")
            if destination in seen_destinations:
                raise ValueError(f"duplicate {path_label} destination: {destination}")
        seen_sources.add(source)
        seen_destinations.add(destination)
        if validate_mapping is not None:
            validate_mapping(source, destination)
        normalized_mappings.append(
            {"source": source, "destination": destination}
        )

    if require_canonical_destination and canonical_skill not in seen_destinations:
        raise ValueError(
            f"layout {layout_name} canonical skill is not a required destination: "
            f"{canonical_skill}"
        )
    return {
        "canonical_skill": canonical_skill,
        "required_mappings": normalized_mappings,
    }


def validate_workflow_discovery_order(
    source: str | bytes,
    inspected_path: str,
) -> str | None:
    if isinstance(source, bytes):
        try:
            source = source.decode("utf-8")
        except UnicodeDecodeError:
            return f"{inspected_path}: workflow discovery order has invalid UTF-8"
    if source.count(WORKFLOW_BLOCK_START) != 1:
        return f"{inspected_path}: workflow discovery order block missing or duplicate"
    block, separator, _ = source.split(WORKFLOW_BLOCK_START, 1)[1].partition(
        WORKFLOW_BLOCK_END
    )
    if not separator:
        return f"{inspected_path}: workflow discovery order block is unterminated"
    lines = block.splitlines()
    for marker in WORKFLOW_DISCOVERY_MARKERS:
        if lines.count(marker) != 1:
            return (
                f"{inspected_path}: workflow discovery order marker missing or "
                f"duplicate: {marker}"
            )
    positions = [lines.index(marker) for marker in WORKFLOW_DISCOVERY_MARKERS]
    if positions != sorted(positions):
        return f"{inspected_path}: workflow discovery order markers out of order"
    return None


def validate_obligation_workflow_contract(
    source: str | bytes,
    inspected_path: str,
) -> str | None:
    if isinstance(source, bytes):
        try:
            source = source.decode("utf-8")
        except UnicodeDecodeError:
            return f"{inspected_path}: obligation workflow contract has invalid UTF-8"
    if (
        source.count(OBLIGATION_WORKFLOW_BLOCK_START) != 1
        or source.count(OBLIGATION_WORKFLOW_BLOCK_END) != 1
    ):
        return f"{inspected_path}: obligation workflow contract block missing or duplicate"
    block, separator, _ = source.split(
        OBLIGATION_WORKFLOW_BLOCK_START,
        1,
    )[1].partition(OBLIGATION_WORKFLOW_BLOCK_END)
    if not separator:
        return f"{inspected_path}: obligation workflow contract block is unterminated"
    expected = "\n" + "\n".join(OBLIGATION_WORKFLOW_CONTRACT_LINES) + "\n"
    if block != expected:
        return f"{inspected_path}: obligation workflow contract entries are malformed"
    return None
