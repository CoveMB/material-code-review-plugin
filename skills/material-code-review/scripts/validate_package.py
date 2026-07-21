#!/usr/bin/env python3
"""Validate an extracted standalone material-code-review Agent Skill."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.1.0"
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


def parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration:
        return {}
    result: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip("'\"")
    return result


def yaml_block_entries(text: str, block_name: str, key: str) -> list[str] | None:
    lines = text.splitlines()
    block_indices = [index for index, line in enumerate(lines) if line == f"{block_name}:"]
    if len(block_indices) != 1:
        return None
    entries: list[str] = []
    for line in lines[block_indices[0] + 1 :]:
        if line and not line[0].isspace():
            break
        if line.lstrip().startswith(f"{key}:"):
            entries.append(line)
    return entries


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
        frontmatter = parse_frontmatter(text)
        if frontmatter.get("name") != "material-code-review":
            errors.append("SKILL.md frontmatter is missing or has the wrong name")
        if frontmatter.get("description") != ACTIVATION_DISCOVERY_DESCRIPTION:
            errors.append("SKILL.md description does not match the Git-change activation contract")
        for marker in ACTIVATION_PREFLIGHT_MARKERS:
            if marker not in text:
                errors.append(f"SKILL.md activation preflight missing marker: {marker}")
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
        for token in ("interface:", "display_name:", "short_description:", "default_prompt:", "policy:"):
            if token not in text:
                errors.append(f"openai.yaml missing {token}")
        implicit_policy = yaml_block_entries(text, "policy", "allow_implicit_invocation")
        if implicit_policy != ["  allow_implicit_invocation: true"]:
            errors.append("openai.yaml must set policy.allow_implicit_invocation exactly to true")
        short_description = yaml_block_entries(text, "interface", "short_description")
        expected_short_description = f'  short_description: "{ACTIVATION_SHORT_DESCRIPTION}"'
        if short_description != [expected_short_description]:
            errors.append("openai.yaml short_description does not match the Git-change activation contract")
    if errors:
        print("[FAIL] standalone material-code-review skill validation", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"[OK] standalone material-code-review skill {VERSION} is structurally valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
