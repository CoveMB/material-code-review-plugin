#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / "skills/material-code-simplification/tests/test_simplifyctl.py"
text = path.read_text(encoding="utf-8")
old_version = '"schema_version": "material-review/adjudication/v1"'
if text.count(old_version) != 1:
    raise RuntimeError(f"expected one simplification adjudication fixture, found {text.count(old_version)}")
text = text.replace(old_version, '"schema_version": "material-review/adjudication/v2"', 1)
anchor = '''                    "recommended_action": "fix_now",
                    "required_pre_fix_verification": None,
                }'''
replacement = '''                    "recommended_action": "fix_now",
                    "required_pre_fix_verification": None,
                    "repair_direction": {
                        "status": "reviewed",
                        "confidence": "high",
                        "root_cause": "The fixture service still owns the obsolete return value.",
                        "objective": "Return the replacement fixture value while preserving the public value() contract.",
                        "smallest_safe_change": "Replace only the obsolete return literal.",
                        "constraints_to_preserve": ["Keep value() callable without arguments."],
                        "state_or_exception_cases": ["The fixture has one deterministic return path."],
                        "alternatives_checked": ["Changing the expected fixture value would redefine the established test contract."],
                        "required_test_evidence": ["A regression check fails while the old literal remains and passes after value() returns 2."],
                        "open_user_decisions": [],
                        "known_limits": []
                    },
                }'''
if text.count(anchor) != 1:
    raise RuntimeError(f"expected one simplification kept-group anchor, found {text.count(anchor)}")
path.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")
