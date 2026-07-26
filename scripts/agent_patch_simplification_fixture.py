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

makefile = root / "Makefile"
make_text = makefile.read_text(encoding="utf-8")
compile_line = "\t$(PYTHON) -m py_compile $(SKILL_DIR)/scripts/reviewctl.py $(SIMPLIFY_SKILL_DIR)/scripts/simplifyctl.py $(SIMPLIFY_SKILL_DIR)/scripts/validate_package.py scripts/validate_package.py scripts/package_plugin.py scripts/package_simplification_skill.py\n"
if make_text.count(compile_line) != 2:
    raise RuntimeError(f"expected compile command in validate and compile targets, found {make_text.count(compile_line)}")
validate_prefix = "validate:\n\t$(MAKE) clean\n\t$(PYTHON) scripts/validate_package.py --package-root .\n\t$(PYTHON) $(SIMPLIFY_SKILL_DIR)/scripts/validate_package.py\n" + compile_line
if make_text.count(validate_prefix) != 1:
    raise RuntimeError("validate target compile anchor is not unique")
make_text = make_text.replace(validate_prefix, validate_prefix + "\t$(MAKE) clean\n", 1)
for old, new in (
    ("\t$(PYTHON) -m unittest discover -s $(SKILL_DIR)/tests -p 'test_*.py' -v\n", "\t$(PYTHON) -B -m unittest discover -s $(SKILL_DIR)/tests -p 'test_*.py' -v\n"),
    ("\t$(PYTHON) -m unittest discover -s $(SIMPLIFY_SKILL_DIR)/tests -p 'test_*.py' -v\n", "\t$(PYTHON) -B -m unittest discover -s $(SIMPLIFY_SKILL_DIR)/tests -p 'test_*.py' -v\n"),
):
    if make_text.count(old) != 2:
        raise RuntimeError(f"expected command in validate and test targets, found {make_text.count(old)}")
    make_text = make_text.replace(old, new)
makefile.write_text(make_text, encoding="utf-8")
