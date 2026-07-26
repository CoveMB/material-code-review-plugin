#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / "skills/material-code-review/scripts/reviewctl.py"
text = path.read_text(encoding="utf-8")

old_function = '''

def validate_repair_direction(value: Any, context: str, *, required: bool) -> dict[str, Any] | None:
    if value is None:
        if required: raise ReviewError(f"{context} is required for a kept finding")
        return None
    if not required: raise ReviewError(f"{context} must be null for a discarded finding")
    obj = require_object(value, context)
    keys = {"status", "confidence", "root_cause", "objective", "smallest_safe_change", "constraints_to_preserve", "state_or_exception_cases", "alternatives_checked", "required_test_evidence", "open_user_decisions", "known_limits"}
    require_exact_keys(obj, keys, context)
    status=require_string(obj["status"],f"{context}.status"); confidence=require_string(obj["confidence"],f"{context}.confidence")
    if status not in REPAIR_DIRECTION_STATUSES: raise ReviewError(f"{context}.status is invalid")
    if confidence not in CONFIDENCES: raise ReviewError(f"{context}.confidence is invalid")
    constraints=require_string_array(obj["constraints_to_preserve"],f"{context}.constraints_to_preserve"); evidence=require_string_array(obj["required_test_evidence"],f"{context}.required_test_evidence"); decisions=require_string_array(obj["open_user_decisions"],f"{context}.open_user_decisions")
    if not constraints or not evidence: raise ReviewError(f"{context} needs constraints and causal test evidence")
    if status=="needs_user_decision" and not decisions: raise ReviewError(f"{context} must name the user decision")
    return {"status":status,"confidence":confidence,"root_cause":require_string(obj["root_cause"],f"{context}.root_cause"),"objective":require_string(obj["objective"],f"{context}.objective"),"smallest_safe_change":require_string(obj["smallest_safe_change"],f"{context}.smallest_safe_change"),"constraints_to_preserve":constraints,"state_or_exception_cases":require_string_array(obj["state_or_exception_cases"],f"{context}.state_or_exception_cases"),"alternatives_checked":require_string_array(obj["alternatives_checked"],f"{context}.alternatives_checked"),"required_test_evidence":evidence,"open_user_decisions":decisions,"known_limits":require_string_array(obj["known_limits"],f"{context}.known_limits")}
'''
new_function = '''

def validate_repair_direction(
    value: Any,
    context: str,
    *,
    required: bool,
) -> dict[str, Any] | None:
    if value is None:
        if required:
            raise ReviewError(f"{context} is required for a kept finding")
        return None
    if not required:
        raise ReviewError(f"{context} must be null for a discarded finding")

    obj = require_object(value, context)
    keys = {
        "status",
        "confidence",
        "root_cause",
        "objective",
        "smallest_safe_change",
        "constraints_to_preserve",
        "state_or_exception_cases",
        "alternatives_checked",
        "required_test_evidence",
        "open_user_decisions",
        "known_limits",
    }
    require_exact_keys(obj, keys, context)

    status = require_string(obj["status"], f"{context}.status")
    confidence = require_string(obj["confidence"], f"{context}.confidence")
    if status not in REPAIR_DIRECTION_STATUSES:
        raise ReviewError(f"{context}.status is invalid")
    if confidence not in CONFIDENCES:
        raise ReviewError(f"{context}.confidence is invalid")

    constraints = require_string_array(
        obj["constraints_to_preserve"],
        f"{context}.constraints_to_preserve",
    )
    evidence = require_string_array(
        obj["required_test_evidence"],
        f"{context}.required_test_evidence",
    )
    decisions = require_string_array(
        obj["open_user_decisions"],
        f"{context}.open_user_decisions",
    )
    if not constraints or not evidence:
        raise ReviewError(f"{context} needs constraints and causal test evidence")
    if status == "needs_user_decision" and not decisions:
        raise ReviewError(f"{context} must name the user decision")

    return {
        "status": status,
        "confidence": confidence,
        "root_cause": require_string(obj["root_cause"], f"{context}.root_cause"),
        "objective": require_string(obj["objective"], f"{context}.objective"),
        "smallest_safe_change": require_string(
            obj["smallest_safe_change"],
            f"{context}.smallest_safe_change",
        ),
        "constraints_to_preserve": constraints,
        "state_or_exception_cases": require_string_array(
            obj["state_or_exception_cases"],
            f"{context}.state_or_exception_cases",
        ),
        "alternatives_checked": require_string_array(
            obj["alternatives_checked"],
            f"{context}.alternatives_checked",
        ),
        "required_test_evidence": evidence,
        "open_user_decisions": decisions,
        "known_limits": require_string_array(
            obj["known_limits"],
            f"{context}.known_limits",
        ),
    }
'''
if text.count(old_function) != 1:
    raise RuntimeError(f"expected one compressed repair validator, found {text.count(old_function)}")
text = text.replace(old_function, new_function, 1)

old_render = '''        direction = finding["repair_direction"]
        lines.extend(["- Provisional repair direction:", f"  - Status / confidence: `{direction['status']}` / `{direction['confidence']}`", f"  - Root cause: {direction['root_cause']}", f"  - Objective: {direction['objective']}", f"  - Smallest safe change: {direction['smallest_safe_change']}"])
        for label, key in (("Constraints to preserve", "constraints_to_preserve"), ("States and exceptions", "state_or_exception_cases"), ("Alternatives checked", "alternatives_checked"), ("Required test evidence", "required_test_evidence"), ("Open user decisions", "open_user_decisions"), ("Known limits", "known_limits")):
'''
new_render = '''        direction = finding["repair_direction"]
        lines.extend(
            [
                "- Provisional repair direction:",
                f"  - Status / confidence: `{direction['status']}` / `{direction['confidence']}`",
                f"  - Root cause: {direction['root_cause']}",
                f"  - Objective: {direction['objective']}",
                f"  - Smallest safe change: {direction['smallest_safe_change']}",
            ]
        )
        detail_fields = (
            ("Constraints to preserve", "constraints_to_preserve"),
            ("States and exceptions", "state_or_exception_cases"),
            ("Alternatives checked", "alternatives_checked"),
            ("Required test evidence", "required_test_evidence"),
            ("Open user decisions", "open_user_decisions"),
            ("Known limits", "known_limits"),
        )
        for label, key in detail_fields:
'''
if text.count(old_render) != 1:
    raise RuntimeError(f"expected one compressed ledger rendering block, found {text.count(old_render)}")
text = text.replace(old_render, new_render, 1)

old_decision = '                "requires_user_decision": representative["requires_user_decision"],\n'
new_decision = '                "requires_user_decision": bool(group["repair_direction"]["open_user_decisions"]),\n'
if text.count(old_decision) != 1:
    raise RuntimeError(f"expected one candidate-owned user decision field, found {text.count(old_decision)}")
text = text.replace(old_decision, new_decision, 1)
path.write_text(text, encoding="utf-8")

rubric = root / "skills/material-code-review/references/materiality-rubric.md"
rubric_text = rubric.read_text(encoding="utf-8")
rubric.write_text(rubric_text.replace("\n\n\n## Repair-direction quality", "\n\n## Repair-direction quality"), encoding="utf-8")
