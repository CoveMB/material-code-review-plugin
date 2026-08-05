#!/usr/bin/env python3
"""Pure contracts for material-review change units and review obligations.

This module intentionally performs no filesystem or controller-state access.
The lifecycle controller supplies the frozen changed/context path sets and owns
all persistence, hashes, snapshots, and state transitions.
"""

from __future__ import annotations

import copy
import re
from typing import Any


COVERAGE_PLAN_SCHEMA = "material-review/coverage-plan/v3"
CANDIDATE_SET_SCHEMA = "material-review/candidate-set/v4"
WORKFLOW_PROFILE = "material_review"
CANDIDATE_LOCAL_ID_MAX_LENGTH = 128

CONTROLLED_RISK_CODES = frozenset(
    {
        "verification_mechanism_semantics",
        "machine_contract_semantics",
        "distribution_contract_integrity",
        "normative_workflow_coherence",
        "user_selectable_output_paths",
        "persisted_config_semantics",
    }
)
CORE_LENS_IDS = frozenset({"correctness", "standards_alignment", "test_adequacy"})
SPECIALIST_LENS_IDS = frozenset(
    {
        "security_privacy",
        "reliability",
        "api_contract",
        "migration_deployment",
        "concurrency",
        "performance",
        "documentation",
        "architecture_simplification",
    }
)
CHECK_OUTCOMES = frozenset({"pass", "finding_emitted", "blocked"})
ASSIGNMENT_KINDS = frozenset({"core", "obligation", "supplemental", "specialist"})
REVIEW_MODES = frozenset({"subagent", "controller", "external"})
DEPTHS = frozenset({"auto", "full"})
SPECIALIST_DECISIONS = frozenset({"selected", "rejected"})
SPECIALIST_SELECTION_BASES = frozenset(
    {"behavior_evidence", "ambiguous", "unknown", "high_risk_mandate", "full_depth"}
)

RISK_REQUIREMENTS = {
    "verification_mechanism_semantics": {
        "required_lens": "adversarial_verification",
        "required_checks": frozenset(
            {"authoritative_parsing", "decoy_duplicate_resistance", "paired_control"}
        ),
        "supporting_lenses": frozenset(),
    },
    "machine_contract_semantics": {
        "required_lens": "api_config_compatibility",
        "required_checks": frozenset(
            {
                "schema_runtime_parity",
                "canonical_git_path_language",
                "required_value_cardinality",
                "privileged_field_type_exactness",
            }
        ),
        "supporting_lenses": frozenset(),
    },
    "distribution_contract_integrity": {
        "required_lens": "reliability",
        "required_checks": frozenset(
            {"manifest_reference_closure", "remove_one_required_entry", "paired_control"}
        ),
        "supporting_lenses": frozenset(),
    },
    "normative_workflow_coherence": {
        "required_lens": "standards_alignment",
        "required_checks": frozenset(
            {
                "normative_sequence",
                "prerequisite_before_dependent_step",
                "paired_control",
                "disabled_mode_dependency_boundary",
            }
        ),
        "supporting_lenses": frozenset(),
    },
    "user_selectable_output_paths": {
        "required_lens": "reliability",
        "required_checks": frozenset(
            {
                "destination_collision",
                "canonical_filesystem_identity",
                "runtime_writer_target_inventory",
                "writer_cleanup_order",
            }
        ),
        "supporting_lenses": frozenset(),
    },
    "persisted_config_semantics": {
        "required_lens": "migration_data_safety",
        "required_checks": frozenset({"accepted_shape_and_default", "migration_and_identity"}),
        "supporting_lenses": frozenset({"api_config_compatibility"}),
    },
}

CORE_ASSIGNMENT_LENSES = {
    "core-correctness": "correctness",
    "core-standards": "standards_alignment",
    "core-tests": "test_adequacy",
}

# Keep this language byte-for-byte aligned with the current v3/v4 JSON Schemas.
REPOSITORY_RELATIVE_GIT_PATH_PATTERN = (
    r"^(?![A-Za-z]:)(?!/)(?![^\u0000]*\\)(?![^\u0000]*//)"
    r"(?![^\u0000]*/$)(?!\.git(?:/|$))(?!\.{1,2}(?:/|$))"
    r"(?![^\u0000]*/\.{1,2}(?:/|$))"
    r"(?![\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a"
    r"\u2028\u2029\u202f\u205f\u3000\ufeff])"
    r"(?![^\u0000]*[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a"
    r"\u2028\u2029\u202f\u205f\u3000\ufeff]$)(?![^\u0000]*\u0000)[^\u0000]+$"
)

IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,127}$")
LENS_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
REVIEWER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ObligationContractError(ValueError):
    """A submitted obligation contract is malformed or incomplete."""


def _object(raw: object, context: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ObligationContractError(f"{context} must be a JSON object")
    return raw


def _array(raw: object, context: str) -> list[Any]:
    if not isinstance(raw, list):
        raise ObligationContractError(f"{context} must be an array")
    return raw


def _string(raw: object, context: str) -> str:
    if not isinstance(raw, str):
        raise ObligationContractError(f"{context} must be a string")
    if not raw.strip():
        raise ObligationContractError(f"{context} must not be empty")
    return raw


def _identifier(raw: object, context: str) -> str:
    value = _string(raw, context)
    if IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ObligationContractError(
            f"{context} must start with a lowercase letter and use lowercase letters, digits, or hyphens"
        )
    return value


def _sha256(raw: object, context: str) -> str:
    value = _string(raw, context)
    if SHA256_PATTERN.fullmatch(value) is None:
        raise ObligationContractError(f"{context} must be a lowercase SHA-256 digest")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], context: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing {missing}")
        if extra:
            details.append(f"unexpected {extra}")
        raise ObligationContractError(f"{context} has invalid fields: {'; '.join(details)}")


def _unique_strings(raw: object, context: str, *, allow_empty: bool = True) -> list[str]:
    values = [_string(item, f"{context}[{index}]") for index, item in enumerate(_array(raw, context))]
    if not allow_empty and not values:
        raise ObligationContractError(f"{context} must contain at least one value")
    if len(set(values)) != len(values):
        raise ObligationContractError(f"{context} must contain unique values")
    return sorted(values)


def canonical_git_path(raw: object, context: str) -> str:
    if not isinstance(raw, str) or re.fullmatch(REPOSITORY_RELATIVE_GIT_PATH_PATTERN, raw) is None:
        raise ObligationContractError(
            f"{context} must be a canonical repository-relative forward-slash Git path: {raw!r}"
        )
    return raw


def _path_array(raw: object, context: str, *, allow_empty: bool = True) -> list[str]:
    values = [canonical_git_path(item, f"{context}[{index}]") for index, item in enumerate(_array(raw, context))]
    if not allow_empty and not values:
        raise ObligationContractError(f"{context} must contain at least one path")
    if len(set(values)) != len(values):
        raise ObligationContractError(f"{context} must contain unique paths")
    return sorted(values)


def _risk_rationales(
    raw: object,
    context: str,
    *,
    selected: bool,
    unit_paths: set[str],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    expected_keys = {"risk_code", "rationale", "evidence_paths"} if selected else {"risk_code", "rationale"}
    for index, item_raw in enumerate(_array(raw, context)):
        item_context = f"{context}[{index}]"
        item = _object(item_raw, item_context)
        _exact_keys(item, expected_keys, item_context)
        risk_code = _string(item["risk_code"], f"{item_context}.risk_code")
        if risk_code not in CONTROLLED_RISK_CODES:
            raise ObligationContractError(f"{item_context}.risk_code is an unknown risk code: {risk_code}")
        if risk_code in seen:
            raise ObligationContractError(f"{context} contains duplicate risk code {risk_code}")
        seen.add(risk_code)
        normalized_item: dict[str, Any] = {
            "risk_code": risk_code,
            "rationale": _string(item["rationale"], f"{item_context}.rationale"),
        }
        if selected:
            evidence_paths = _path_array(
                item["evidence_paths"], f"{item_context}.evidence_paths", allow_empty=False
            )
            outside_unit = sorted(set(evidence_paths) - unit_paths)
            if outside_unit:
                raise ObligationContractError(
                    f"{item_context}.evidence_paths are outside the change unit: {', '.join(outside_unit)}"
                )
            normalized_item["evidence_paths"] = evidence_paths
        normalized.append(normalized_item)
    return sorted(normalized, key=lambda item: item["risk_code"])


def _normalize_unit(
    raw: object,
    index: int,
    *,
    allowed_context_paths: set[str],
) -> dict[str, Any]:
    context = f"coverage plan.change_units[{index}]"
    unit = _object(raw, context)
    _exact_keys(
        unit,
        {
            "unit_id",
            "purpose",
            "primary_paths",
            "context_paths",
            "risk_codes",
            "selected_risk_rationale",
            "rejected_risk_rationale",
            "specialist_decisions",
        },
        context,
    )
    unit_id = _identifier(unit["unit_id"], f"{context}.unit_id")
    primary_paths = _path_array(unit["primary_paths"], f"{context}.primary_paths", allow_empty=False)
    context_paths = _path_array(unit["context_paths"], f"{context}.context_paths")
    overlap = sorted(set(primary_paths) & set(context_paths))
    if overlap:
        raise ObligationContractError(
            f"{context} primary_paths and context_paths must not overlap: {', '.join(overlap)}"
        )
    unavailable = sorted(set(context_paths) - allowed_context_paths)
    if unavailable:
        raise ObligationContractError(
            f"{context}.context_paths are not in the allowed context paths: {', '.join(unavailable)}"
        )
    risk_codes = _unique_strings(unit["risk_codes"], f"{context}.risk_codes")
    unknown = sorted(set(risk_codes) - CONTROLLED_RISK_CODES)
    if unknown:
        raise ObligationContractError(f"{context}.risk_codes contains unknown risk code: {', '.join(unknown)}")
    unit_paths = set(primary_paths) | set(context_paths)
    selected = _risk_rationales(
        unit["selected_risk_rationale"],
        f"{context}.selected_risk_rationale",
        selected=True,
        unit_paths=unit_paths,
    )
    rejected = _risk_rationales(
        unit["rejected_risk_rationale"],
        f"{context}.rejected_risk_rationale",
        selected=False,
        unit_paths=unit_paths,
    )
    selected_codes = {item["risk_code"] for item in selected}
    rejected_codes = {item["risk_code"] for item in rejected}
    if selected_codes != set(risk_codes) or selected_codes & rejected_codes or selected_codes | rejected_codes != CONTROLLED_RISK_CODES:
        raise ObligationContractError(
            f"{context} must contain exhaustive risk decisions: selected rationale must equal risk_codes and rejected rationale must cover every other controlled risk"
        )
    specialist_decisions: list[dict[str, Any]] = []
    specialist_lenses: set[str] = set()
    for decision_index, decision_raw in enumerate(
        _array(unit["specialist_decisions"], f"{context}.specialist_decisions")
    ):
        decision_context = f"{context}.specialist_decisions[{decision_index}]"
        decision = _object(decision_raw, decision_context)
        _exact_keys(decision, {"lens_id", "decision", "basis", "evidence"}, decision_context)
        lens_id = _string(decision["lens_id"], f"{decision_context}.lens_id")
        if lens_id not in SPECIALIST_LENS_IDS:
            raise ObligationContractError(
                f"{decision_context}.lens_id must be one of {sorted(SPECIALIST_LENS_IDS)}"
            )
        if lens_id in specialist_lenses:
            raise ObligationContractError(
                f"{context}.specialist_decisions contains duplicate lens {lens_id}"
            )
        specialist_lenses.add(lens_id)
        decision_value = _string(decision["decision"], f"{decision_context}.decision")
        if decision_value not in SPECIALIST_DECISIONS:
            raise ObligationContractError(
                f"{decision_context}.decision must be selected or rejected"
            )
        basis = _string(decision["basis"], f"{decision_context}.basis")
        if basis not in SPECIALIST_SELECTION_BASES:
            raise ObligationContractError(
                f"{decision_context}.basis must be one of {sorted(SPECIALIST_SELECTION_BASES)}"
            )
        if decision_value == "rejected" and basis != "behavior_evidence":
            raise ObligationContractError(
                f"{decision_context} ambiguous, unknown, mandated, or full-depth evidence must select the lens"
            )
        specialist_decisions.append(
            {
                "lens_id": lens_id,
                "decision": decision_value,
                "basis": basis,
                "evidence": _unique_strings(
                    decision["evidence"], f"{decision_context}.evidence", allow_empty=False
                ),
            }
        )
    if specialist_lenses != SPECIALIST_LENS_IDS:
        raise ObligationContractError(
            f"{context}.specialist_decisions must classify exactly {sorted(SPECIALIST_LENS_IDS)}"
        )
    return {
        "unit_id": unit_id,
        "purpose": _string(unit["purpose"], f"{context}.purpose"),
        "primary_paths": primary_paths,
        "context_paths": context_paths,
        "risk_codes": sorted(risk_codes),
        "selected_risk_rationale": selected,
        "rejected_risk_rationale": rejected,
        "specialist_decisions": sorted(
            specialist_decisions, key=lambda item: item["lens_id"]
        ),
    }


def _normalize_obligation(
    raw: object,
    index: int,
    *,
    units_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    context = f"coverage plan.review_obligations[{index}]"
    obligation = _object(raw, context)
    _exact_keys(
        obligation,
        {
            "obligation_id",
            "unit_id",
            "risk_code",
            "canonical_owner",
            "affected_consumers",
            "evidence_paths",
            "required_lens",
            "required_checks",
        },
        context,
    )
    obligation_id = _identifier(obligation["obligation_id"], f"{context}.obligation_id")
    unit_id = _identifier(obligation["unit_id"], f"{context}.unit_id")
    unit = units_by_id.get(unit_id)
    if unit is None:
        raise ObligationContractError(f"{context}.unit_id does not name a change unit: {unit_id}")
    risk_code = _string(obligation["risk_code"], f"{context}.risk_code")
    if risk_code not in CONTROLLED_RISK_CODES:
        raise ObligationContractError(f"{context}.risk_code is an unknown risk code: {risk_code}")
    requirement = RISK_REQUIREMENTS[risk_code]
    required_lens = _string(obligation["required_lens"], f"{context}.required_lens")
    if required_lens != requirement["required_lens"]:
        raise ObligationContractError(
            f"{context} has the wrong required lens for {risk_code}; expected {requirement['required_lens']}"
        )
    required_checks = _unique_strings(
        obligation["required_checks"], f"{context}.required_checks", allow_empty=False
    )
    if set(required_checks) != requirement["required_checks"]:
        raise ObligationContractError(
            f"{context} has the wrong required checks for {risk_code}; expected {sorted(requirement['required_checks'])}"
        )
    unit_paths = set(unit["primary_paths"]) | set(unit["context_paths"])
    canonical_owner = canonical_git_path(
        obligation["canonical_owner"], f"{context}.canonical_owner"
    )
    affected_consumers = _path_array(
        obligation["affected_consumers"], f"{context}.affected_consumers"
    )
    evidence_paths = _path_array(
        obligation["evidence_paths"], f"{context}.evidence_paths", allow_empty=False
    )
    outside_unit = sorted(
        ({canonical_owner} | set(affected_consumers) | set(evidence_paths)) - unit_paths
    )
    if outside_unit:
        raise ObligationContractError(
            f"{context} references paths outside its change unit: {', '.join(outside_unit)}"
        )
    return {
        "obligation_id": obligation_id,
        "unit_id": unit_id,
        "risk_code": risk_code,
        "canonical_owner": canonical_owner,
        "affected_consumers": affected_consumers,
        "evidence_paths": evidence_paths,
        "required_lens": required_lens,
        "required_checks": required_checks,
    }


def _assignment_identity(
    assignment: dict[str, Any], context: str
) -> dict[str, str]:
    lens_id = _string(assignment["lens_id"], f"{context}.lens_id")
    if LENS_PATTERN.fullmatch(lens_id) is None:
        raise ObligationContractError(f"{context}.lens_id has an invalid format")
    reviewer_id = _string(assignment["reviewer_id"], f"{context}.reviewer_id")
    if REVIEWER_PATTERN.fullmatch(reviewer_id) is None:
        raise ObligationContractError(f"{context}.reviewer_id has an invalid format")
    review_mode = _string(assignment["review_mode"], f"{context}.review_mode")
    if review_mode not in REVIEW_MODES:
        raise ObligationContractError(
            f"{context}.review_mode must be one of {sorted(REVIEW_MODES)}"
        )
    return {
        "lens_id": lens_id,
        "reviewer_id": reviewer_id,
        "independence_group": _string(
            assignment["independence_group"], f"{context}.independence_group"
        ),
        "review_mode": review_mode,
    }


def _normalize_assignment(
    raw: object,
    index: int,
    *,
    obligations_by_id: dict[str, dict[str, Any]],
    units_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    context = f"coverage plan.assignments[{index}]"
    assignment = _object(raw, context)
    assignment_kind = _string(assignment.get("assignment_kind"), f"{context}.assignment_kind")
    if assignment_kind not in ASSIGNMENT_KINDS:
        raise ObligationContractError(
            f"{context}.assignment_kind must be one of {sorted(ASSIGNMENT_KINDS)}"
        )
    common_keys = {
        "assignment_id",
        "assignment_kind",
        "lens_id",
        "reviewer_id",
        "independence_group",
        "review_mode",
    }
    expected_keys = set(common_keys)
    if assignment_kind == "obligation":
        expected_keys.update({"obligation_id", "unit_id", "risk_code"})
    elif assignment_kind == "supplemental":
        expected_keys.update({"unit_id", "risk_code"})
    elif assignment_kind == "specialist":
        expected_keys.update({"unit_ids", "primary_paths", "context_paths"})
    _exact_keys(assignment, expected_keys, context)
    normalized: dict[str, Any] = {
        "assignment_id": _identifier(assignment["assignment_id"], f"{context}.assignment_id"),
        "assignment_kind": assignment_kind,
        **_assignment_identity(assignment, context),
    }
    if assignment_kind == "core":
        expected_lens = CORE_ASSIGNMENT_LENSES.get(normalized["assignment_id"])
        if expected_lens is None or normalized["lens_id"] != expected_lens:
            raise ObligationContractError(
                f"{context} is not one of the mandatory core assignments with its exact lens"
            )
        return normalized

    if assignment_kind == "specialist":
        if normalized["lens_id"] not in SPECIALIST_LENS_IDS:
            raise ObligationContractError(
                f"{context}.lens_id must be one of {sorted(SPECIALIST_LENS_IDS)}"
            )
        unit_ids = [
            _identifier(item, f"{context}.unit_ids[{unit_index}]")
            for unit_index, item in enumerate(_array(assignment["unit_ids"], f"{context}.unit_ids"))
        ]
        if not unit_ids or len(set(unit_ids)) != len(unit_ids):
            raise ObligationContractError(f"{context}.unit_ids must contain unique selected units")
        unknown_units = sorted(set(unit_ids) - set(units_by_id))
        if unknown_units:
            raise ObligationContractError(
                f"{context}.unit_ids contains unknown units: {', '.join(unknown_units)}"
            )
        primary_paths = _path_array(
            assignment["primary_paths"], f"{context}.primary_paths", allow_empty=False
        )
        context_paths = _path_array(assignment["context_paths"], f"{context}.context_paths")
        expected_primary = {
            path for unit_id in unit_ids for path in units_by_id[unit_id]["primary_paths"]
        }
        available_context = {
            path for unit_id in unit_ids for path in units_by_id[unit_id]["context_paths"]
        }
        if set(primary_paths) != expected_primary:
            raise ObligationContractError(
                f"{context}.primary_paths must equal the exact union of selected unit primary paths"
            )
        outside_context = sorted(set(context_paths) - available_context)
        if outside_context:
            raise ObligationContractError(
                f"{context}.context_paths are outside selected units: {', '.join(outside_context)}"
            )
        normalized.update(
            {
                "unit_ids": sorted(unit_ids),
                "primary_paths": primary_paths,
                "context_paths": context_paths,
            }
        )
        return normalized

    unit_id = _identifier(assignment["unit_id"], f"{context}.unit_id")
    risk_code = _string(assignment["risk_code"], f"{context}.risk_code")
    if unit_id not in units_by_id or risk_code not in CONTROLLED_RISK_CODES:
        raise ObligationContractError(f"{context} has an unknown unit/risk identity")
    normalized.update({"unit_id": unit_id, "risk_code": risk_code})
    if assignment_kind == "obligation":
        obligation_id = _identifier(
            assignment["obligation_id"], f"{context}.obligation_id"
        )
        obligation = obligations_by_id.get(obligation_id)
        if obligation is None:
            raise ObligationContractError(
                f"{context}.obligation_id does not name one review obligation"
            )
        if (unit_id, risk_code) != (obligation["unit_id"], obligation["risk_code"]):
            raise ObligationContractError(f"{context} does not match its obligation unit/risk identity")
        if normalized["lens_id"] != obligation["required_lens"]:
            raise ObligationContractError(f"{context} does not use the obligation's required lens")
        normalized["obligation_id"] = obligation_id
        return normalized

    requirement = RISK_REQUIREMENTS[risk_code]
    if normalized["lens_id"] not in requirement["supporting_lenses"]:
        raise ObligationContractError(
            f"{context} is not a required supporting lens for {risk_code}"
        )
    return normalized


def validate_coverage_contract(
    raw: object,
    *,
    changed_paths: set[str],
    allowed_context_paths: set[str],
) -> dict[str, Any]:
    plan = _object(raw, "coverage plan")
    _exact_keys(
        plan,
        {
            "schema_version",
            "scope_hash",
            "workflow_profile",
            "depth",
            "change_units",
            "review_obligations",
            "assignments",
        },
        "coverage plan",
    )
    if plan["schema_version"] != COVERAGE_PLAN_SCHEMA:
        raise ObligationContractError("coverage plan has an unsupported schema_version")
    if plan["workflow_profile"] != WORKFLOW_PROFILE:
        raise ObligationContractError("coverage plan workflow_profile must be material_review")
    depth = _string(plan["depth"], "coverage plan.depth")
    if depth not in DEPTHS:
        raise ObligationContractError(f"coverage plan.depth must be one of {sorted(DEPTHS)}")
    normalized_changed = {canonical_git_path(path, "changed path") for path in changed_paths}
    normalized_allowed_context = {
        canonical_git_path(path, "allowed context path") for path in allowed_context_paths
    }
    units = [
        _normalize_unit(item, index, allowed_context_paths=normalized_allowed_context)
        for index, item in enumerate(_array(plan["change_units"], "coverage plan.change_units"))
    ]
    if not units:
        raise ObligationContractError("coverage plan.change_units must contain at least one unit")
    unit_ids = [unit["unit_id"] for unit in units]
    if len(set(unit_ids)) != len(unit_ids):
        raise ObligationContractError("coverage plan change unit IDs must be unique")
    all_primary_paths = [path for unit in units for path in unit["primary_paths"]]
    if len(all_primary_paths) != len(set(all_primary_paths)) or set(all_primary_paths) != normalized_changed:
        raise ObligationContractError(
            "coverage plan change_units must form one exact primary partition of every changed path"
        )
    units = sorted(units, key=lambda item: item["unit_id"])
    units_by_id = {unit["unit_id"]: unit for unit in units}

    obligations = [
        _normalize_obligation(item, index, units_by_id=units_by_id)
        for index, item in enumerate(
            _array(plan["review_obligations"], "coverage plan.review_obligations")
        )
    ]
    obligation_ids = [item["obligation_id"] for item in obligations]
    if len(set(obligation_ids)) != len(obligation_ids):
        raise ObligationContractError("coverage plan obligation IDs must be unique")
    positive_pairs = {
        (unit["unit_id"], risk_code)
        for unit in units
        for risk_code in unit["risk_codes"]
    }
    obligation_pairs = [(item["unit_id"], item["risk_code"]) for item in obligations]
    if set(obligation_pairs) != positive_pairs or len(obligation_pairs) != len(positive_pairs):
        raise ObligationContractError(
            "every positive unit/risk pair requires exactly one review obligation and negative risks require none"
        )
    obligations = sorted(obligations, key=lambda item: item["obligation_id"])
    obligations_by_id = {item["obligation_id"]: item for item in obligations}

    assignments = [
        _normalize_assignment(
            item,
            index,
            obligations_by_id=obligations_by_id,
            units_by_id=units_by_id,
        )
        for index, item in enumerate(_array(plan["assignments"], "coverage plan.assignments"))
    ]
    assignment_ids = [item["assignment_id"] for item in assignments]
    if len(set(assignment_ids)) != len(assignment_ids):
        raise ObligationContractError("coverage plan assignment IDs must be unique")
    core_ids = {
        item["assignment_id"] for item in assignments if item["assignment_kind"] == "core"
    }
    if core_ids != set(CORE_ASSIGNMENT_LENSES):
        raise ObligationContractError("coverage plan must contain exactly the three mandatory core assignments")
    obligation_assignment_ids = [
        item["obligation_id"]
        for item in assignments
        if item["assignment_kind"] == "obligation"
    ]
    if set(obligation_assignment_ids) != set(obligations_by_id) or len(obligation_assignment_ids) != len(obligations_by_id):
        raise ObligationContractError(
            "every review obligation requires exactly one obligation assignment"
        )
    expected_supporting = {
        (unit_id, risk_code, lens_id)
        for unit_id, risk_code in positive_pairs
        for lens_id in RISK_REQUIREMENTS[risk_code]["supporting_lenses"]
    }
    actual_supporting = [
        (item["unit_id"], item["risk_code"], item["lens_id"])
        for item in assignments
        if item["assignment_kind"] == "supplemental"
    ]
    if set(actual_supporting) != expected_supporting or len(actual_supporting) != len(expected_supporting):
        raise ObligationContractError(
            "coverage plan must contain exactly one assignment for every required supporting lens"
        )
    selected_units_by_lens = {
        lens_id: [
            unit["unit_id"]
            for unit in units
            if any(
                decision["lens_id"] == lens_id and decision["decision"] == "selected"
                for decision in unit["specialist_decisions"]
            )
        ]
        for lens_id in SPECIALIST_LENS_IDS
    }
    if depth == "full":
        rejected = [
            f"{unit['unit_id']}:{decision['lens_id']}"
            for unit in units
            for decision in unit["specialist_decisions"]
            if decision["decision"] != "selected" or decision["basis"] != "full_depth"
        ]
        if rejected:
            raise ObligationContractError(
                "full depth must select every specialist lens for every change unit with full_depth basis"
            )
    specialists = [
        item for item in assignments if item["assignment_kind"] == "specialist"
    ]
    specialist_lenses = [item["lens_id"] for item in specialists]
    expected_lenses = {lens_id for lens_id, unit_ids in selected_units_by_lens.items() if unit_ids}
    if set(specialist_lenses) != expected_lenses or len(specialist_lenses) != len(expected_lenses):
        raise ObligationContractError(
            "coverage plan requires exactly one specialist assignment for every selected lens"
        )
    for specialist in specialists:
        expected_units = sorted(selected_units_by_lens[specialist["lens_id"]])
        if specialist["unit_ids"] != expected_units:
            raise ObligationContractError(
                f"specialist assignment {specialist['assignment_id']} must cover the exact selected units for {specialist['lens_id']}"
            )
    assignments = sorted(assignments, key=lambda item: item["assignment_id"])
    return {
        "schema_version": COVERAGE_PLAN_SCHEMA,
        "scope_hash": _sha256(plan["scope_hash"], "coverage plan.scope_hash"),
        "workflow_profile": WORKFLOW_PROFILE,
        "depth": depth,
        "change_units": units,
        "review_obligations": obligations,
        "assignments": assignments,
    }


def required_assignment_ids(plan: dict[str, Any]) -> set[str]:
    assignments = _array(plan.get("assignments"), "coverage plan.assignments")
    result = {
        _identifier(_object(item, f"coverage plan.assignments[{index}]").get("assignment_id"), f"coverage plan.assignments[{index}].assignment_id")
        for index, item in enumerate(assignments)
    }
    if len(result) != len(assignments):
        raise ObligationContractError("coverage plan assignment IDs must be unique")
    return result


def _normalize_coverage(raw: object) -> dict[str, Any]:
    coverage = _object(raw, "assignment result.coverage")
    _exact_keys(coverage, {"files_reviewed", "areas", "limitations"}, "assignment result.coverage")
    return {
        "files_reviewed": _path_array(
            coverage["files_reviewed"], "assignment result.coverage.files_reviewed", allow_empty=False
        ),
        "areas": _unique_strings(coverage["areas"], "assignment result.coverage.areas"),
        "limitations": _unique_strings(
            coverage["limitations"], "assignment result.coverage.limitations"
        ),
    }


def _finding_local_ids(raw_findings: object) -> tuple[list[dict[str, Any]], set[str]]:
    findings: list[dict[str, Any]] = []
    local_ids: set[str] = set()
    for index, finding_raw in enumerate(_array(raw_findings, "assignment result.findings")):
        finding = copy.deepcopy(_object(finding_raw, f"assignment result.findings[{index}]"))
        local_id = _string(finding.get("local_id"), f"assignment result.findings[{index}].local_id")
        if len(local_id) > CANDIDATE_LOCAL_ID_MAX_LENGTH:
            raise ObligationContractError(
                "assignment result.findings"
                f"[{index}].local_id must be at most {CANDIDATE_LOCAL_ID_MAX_LENGTH} characters"
            )
        if local_id in local_ids:
            raise ObligationContractError("assignment result finding local IDs must be unique")
        local_ids.add(local_id)
        findings.append(finding)
    return findings, local_ids


def _normalize_check_results(
    raw: object,
    *,
    obligation: dict[str, Any],
    finding_local_ids: set[str],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, check_raw in enumerate(_array(raw, "assignment result.check_results")):
        context = f"assignment result.check_results[{index}]"
        check = _object(check_raw, context)
        _exact_keys(check, {"check_code", "outcome", "evidence", "finding_local_ids"}, context)
        check_code = _string(check["check_code"], f"{context}.check_code")
        if check_code in seen:
            raise ObligationContractError("assignment result required checks must occur exactly once")
        seen.add(check_code)
        outcome = _string(check["outcome"], f"{context}.outcome")
        if outcome not in CHECK_OUTCOMES:
            raise ObligationContractError(
                f"{context}.outcome must be one of {sorted(CHECK_OUTCOMES)}"
            )
        evidence = _unique_strings(check["evidence"], f"{context}.evidence")
        if not evidence:
            raise ObligationContractError(f"{context} {outcome} requires evidence")
        referenced_ids = _unique_strings(
            check["finding_local_ids"], f"{context}.finding_local_ids"
        )
        if outcome == "pass" and referenced_ids:
            raise ObligationContractError(f"{context} pass must not reference finding_local_ids")
        if outcome == "finding_emitted" and not referenced_ids:
            raise ObligationContractError(
                f"{context} finding_emitted requires finding_local_ids"
            )
        if outcome == "blocked" and referenced_ids:
            raise ObligationContractError(f"{context} blocked must not reference finding_local_ids")
        unknown_ids = sorted(set(referenced_ids) - finding_local_ids)
        if unknown_ids:
            raise ObligationContractError(
                f"{context}.finding_local_ids contains unknown local IDs: {', '.join(unknown_ids)}"
            )
        checks.append(
            {
                "check_code": check_code,
                "outcome": outcome,
                "evidence": evidence,
                "finding_local_ids": referenced_ids,
            }
        )
    required_checks = set(obligation["required_checks"])
    if seen != required_checks or len(checks) != len(required_checks):
        raise ObligationContractError(
            f"assignment result required checks must equal {sorted(required_checks)}"
        )
    return sorted(checks, key=lambda item: item["check_code"])


def validate_assignment_result(
    raw: object,
    *,
    assignment: dict[str, Any],
    obligation: dict[str, Any] | None,
) -> dict[str, Any]:
    result = _object(raw, "assignment result")
    assignment_kind = assignment.get("assignment_kind")
    if assignment_kind not in ASSIGNMENT_KINDS:
        raise ObligationContractError("assignment has an unsupported assignment_kind")
    expected_keys = {
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
    if assignment_kind == "obligation":
        expected_keys.add("obligation_id")
    elif assignment_kind == "specialist":
        expected_keys.update({"unit_ids", "primary_paths", "context_paths"})
    _exact_keys(result, expected_keys, "assignment result")
    if result["schema_version"] != CANDIDATE_SET_SCHEMA:
        raise ObligationContractError("assignment result has an unsupported schema_version")
    identity_fields = [
        "assignment_id",
        "assignment_kind",
        "lens_id",
        "reviewer_id",
        "independence_group",
        "review_mode",
    ]
    if assignment_kind == "specialist":
        identity_fields.extend(["unit_ids", "primary_paths", "context_paths"])
    for field in identity_fields:
        if result[field] != assignment[field]:
            raise ObligationContractError(
                f"assignment identity mismatch for {field}: expected {assignment[field]!r}"
            )
    findings, local_ids = _finding_local_ids(result["findings"])
    if assignment_kind == "obligation":
        if obligation is None or result["obligation_id"] != assignment.get("obligation_id") or result["obligation_id"] != obligation.get("obligation_id"):
            raise ObligationContractError("assignment result obligation_id does not match its assignment")
        check_results = _normalize_check_results(
            result["check_results"], obligation=obligation, finding_local_ids=local_ids
        )
    else:
        if obligation is not None:
            raise ObligationContractError("core and supplemental assignments must not receive an obligation")
        check_results = _array(result["check_results"], "assignment result.check_results")
        if check_results:
            raise ObligationContractError(
                "core, supplemental, and specialist assignment check_results must be empty"
            )
        check_results = []
    normalized = {
        "schema_version": CANDIDATE_SET_SCHEMA,
        "scope_hash": _sha256(result["scope_hash"], "assignment result.scope_hash"),
        "coverage_plan_hash": _sha256(
            result["coverage_plan_hash"], "assignment result.coverage_plan_hash"
        ),
        "coverage_context_hash": _sha256(
            result["coverage_context_hash"], "assignment result.coverage_context_hash"
        ),
        **{field: result[field] for field in identity_fields},
    }
    if assignment_kind == "obligation":
        normalized["obligation_id"] = result["obligation_id"]
    coverage = _normalize_coverage(result["coverage"])
    if assignment_kind == "specialist":
        missing_paths = sorted(set(assignment["primary_paths"]) - set(coverage["files_reviewed"]))
        if missing_paths:
            raise ObligationContractError(
                "specialist assignment result must review every assigned primary path: "
                + ", ".join(missing_paths)
            )
    normalized.update(
        {
            "check_results": check_results,
            "findings": findings,
            "coverage": coverage,
        }
    )
    return normalized
