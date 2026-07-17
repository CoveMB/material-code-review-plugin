#!/usr/bin/env python3
"""Validate an extracted standalone material-code-review Agent Skill."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.1.0"
REQUIRED = {
    "SKILL.md",
    "agents/openai.yaml",
    "scripts/reviewctl.py",
    "scripts/validate_package.py",
    "tests/test_reviewctl.py",
    "schemas/candidate-set.schema.json",
    "schemas/adjudication.schema.json",
    "schemas/fix-plan.schema.json",
    "schemas/verification.schema.json",
    "references/context-checklist.md",
    "references/materiality-rubric.md",
    "references/reviewer-template.md",
    "references/validator-template.md",
    "references/adjudicator-template.md",
    "references/planner-template.md",
    "references/fixer-template.md",
    "references/postfix-verifier-template.md",
    "references/output-template.md",
    "references/failure-model.md",
    "references/workflow.md",
}


def main() -> int:
    errors: list[str] = []
    if sys.version_info < (3, 10):
        errors.append("Python 3.10+ is required")
    actual = {path.relative_to(ROOT).as_posix() for path in ROOT.rglob("*") if path.is_file()}
    for rel in sorted(REQUIRED - actual):
        errors.append(f"missing required skill file: {rel}")
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if "__pycache__" in rel.parts or ".pytest_cache" in rel.parts or path.suffix in {".pyc", ".pyo"}:
            errors.append(f"generated file present: {rel.as_posix()}")
    skill = ROOT / "SKILL.md"
    if skill.is_file():
        text = skill.read_text(encoding="utf-8")
        if not text.startswith("---\n") or "name: material-code-review" not in text.split("---", 2)[1]:
            errors.append("SKILL.md frontmatter is missing or has the wrong name")
        for rel in sorted(set(re.findall(r"`((?:references|schemas)/[A-Za-z0-9._/-]+)`", text))):
            if not (ROOT / rel).is_file():
                errors.append(f"SKILL.md references missing file: {rel}")
    controller = ROOT / "scripts/reviewctl.py"
    if controller.is_file():
        if f'TOOL_VERSION = "{VERSION}"' not in controller.read_text(encoding="utf-8"):
            errors.append("reviewctl version mismatch")
        if not sys.platform.startswith("win") and not (controller.stat().st_mode & 0o100):
            errors.append("reviewctl.py is not executable")
    for path in (ROOT / "schemas").glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"invalid JSON in {path.name}: {exc}")
            continue
        if data.get("type") != "object" or data.get("additionalProperties") is not False:
            errors.append(f"schema must be object and fail closed: {path.name}")
    yaml = ROOT / "agents/openai.yaml"
    if yaml.is_file():
        text = yaml.read_text(encoding="utf-8")
        for token in ("interface:", "display_name:", "default_prompt:", "allow_implicit_invocation:"):
            if token not in text:
                errors.append(f"openai.yaml missing {token}")
    if errors:
        print("[FAIL] standalone material-code-review skill validation", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"[OK] standalone material-code-review skill {VERSION} is structurally valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
