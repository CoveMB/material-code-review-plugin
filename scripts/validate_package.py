#!/usr/bin/env python3
"""Validate the dual-host material-code-review source package and ZIP archives."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import zipfile

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 fallback: use conservative key checks below.
    tomllib = None
from pathlib import Path, PurePosixPath
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.2.0"
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
DISCOVERY_CONTROL_MARKERS = (
    "record-coverage",
    "check-candidates",
    "assign-fallback",
    "record-reviewer-failure",
    "finalize-coverage",
    "protocol_coherence",
    "REVIEW_INCOMPLETE",
)
RECOVERY_CONTROL_MARKERS = (
    "refresh-finding-test",
    "begin-pre-verification-repair",
    "latest failed or stale required test evidence",
)

DISTRIBUTABLE_REQUIRED = {
    ".codex-plugin/plugin.json",
    ".agents/plugins/marketplace.json",
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    "SKILL.md",
    "AGENTS.md",
    "README.md",
    "CODEX.md",
    "LICENSE",
    "THIRD_PARTY.md",
    "CHANGELOG.md",
    "Makefile",
    "commands/material-review.md",
    "bin/material-reviewctl",
    "bin/material-reviewctl.cmd",
    "bin/material-reviewctl.ps1",
    "scripts/package_plugin.py",
    "scripts/validate_package.py",
    "skills/material-code-review/SKILL.md",
    "skills/material-code-review/agents/openai.yaml",
    "skills/material-code-review/scripts/reviewctl.py",
    "skills/material-code-review/tests/test_reviewctl.py",
    "skills/material-code-review/schemas/candidate-set.schema.json",
    "skills/material-code-review/schemas/candidate-preflight.schema.json",
    "skills/material-code-review/schemas/fallback-assignment.schema.json",
    "skills/material-code-review/schemas/reviewer-failure-attestation.schema.json",
    "skills/material-code-review/schemas/coverage-plan.schema.json",
    "skills/material-code-review/schemas/coverage-status.schema.json",
    "skills/material-code-review/schemas/adjudication.schema.json",
    "skills/material-code-review/schemas/fix-plan.schema.json",
    "skills/material-code-review/schemas/verification.schema.json",
    "skills/material-code-review/references/remediation-rubric.md",
    "skills/material-code-review/references/test-evidence-rubric.md",
    "skills/material-code-review/references/remediation-auditor-template.md",
    "skills/material-code-review/references/protocol-coherence-lens.md",
    "agents/protocol-reviewer.md",
    "examples/codex-project-config/.codex/config.toml",
    "examples/codex-project-config/.codex/agents/material_candidate.toml",
    "examples/codex-project-config/.codex/agents/material_validator.toml",
    "examples/codex-project-config/.codex/agents/material_adjudicator.toml",
    "examples/codex-project-config/.codex/agents/material_postfix.toml",
}
MAINTAINER_SOURCE_REQUIRED = {
    ".agents/skills/material-review-evaluation/SKILL.md",
    "EVALUATION.md",
    "docs/superpowers/plans/2026-07-27-material-review-version-evaluator.md",
    "docs/superpowers/specs/2026-07-27-material-review-version-evaluation-design.md",
    "evaluations/material-code-review/README.md",
    "evaluations/material-code-review/cases/discogs-custom-playlists.json",
    "evaluations/material-code-review/cases/pr-3-discovery-recall.json",
    "evaluations/material-code-review/prompts/reviewer.md",
    "evaluations/material-code-review/prompts/judge.md",
    "evaluations/material-code-review/rubric.md",
}
EVALUATOR_ASSET_ALLOWLIST = (
    "evaluations/material-code-review/cases/discogs-custom-playlists.json",
    "evaluations/material-code-review/prompts/reviewer.md",
    "evaluations/material-code-review/prompts/judge.md",
    "evaluations/material-code-review/rubric.md",
)
EVALUATOR_ROOT_ANCHOR = (
    "Locate the repository root and confirm the invocation is running in a source checkout"
)
EVALUATOR_INITIAL_CLEAN_ATTESTATION = (
    "Immediately capture the active material-review repository's `HEAD` and porcelain status. "
    "Require an empty status."
)
EVALUATOR_ASSET_ALLOWLIST_START = "<!-- evaluator-asset-allowlist:start -->"
EVALUATOR_ASSET_ALLOWLIST_END = "<!-- evaluator-asset-allowlist:end -->"
EVALUATOR_NO_FALLBACK = (
    "Do not search alternate directories, fall back to skill-relative resolution, "
    "or use parent traversal from the skill directory."
)
EVALUATOR_DISPATCH_CONTRACT_START = "<!-- evaluator-dispatch-contract:start"
EVALUATOR_DISPATCH_CONTRACT_END = "evaluator-dispatch-contract:end -->"
EVALUATOR_CONTEXT_FREE_PROMPT_MARKER = (
    "The root dispatcher must provide zero inherited task history."
)
EVALUATOR_PREDISPATCH_REATTESTATION = (
    "Immediately before each reviewer or judge dispatch, recapture the active material-review "
    "repository's `HEAD` and porcelain status and require an exact match to the initial clean "
    "attestation."
)
EVALUATOR_ROOT_DISPATCH_AUTHORITY = "Root-side verification is authoritative;"
EVALUATOR_PROMPT_ROOT_DISPATCH_AUTHORITY = (
    "Root-side verification of the empty-history host primitive and supplied allowlist is "
    "authoritative; no private dispatch receipt or other private orchestration data is "
    "worker-visible."
)
EVALUATOR_PRIVATE_RECEIPT_REQUIREMENT = "Do not proceed if the dispatch receipt"
EVALUATOR_CONTEXT_FREE_DOC_MARKER = (
    "Every reviewer and judge dispatch uses a self-contained request with zero inherited task history."
)
EVALUATOR_CONTEXT_FREE_DOCS = (
    "README.md",
    "EVALUATION.md",
    "docs/superpowers/plans/2026-07-27-material-review-version-evaluator.md",
    "docs/superpowers/specs/2026-07-27-material-review-version-evaluation-design.md",
    "evaluations/material-code-review/README.md",
)
EVALUATOR_GATE_DISPOSITION_CONTRACT_START = (
    "<!-- evaluator-gate-disposition-contract:start"
)
EVALUATOR_GATE_DISPOSITION_CONTRACT_END = (
    "evaluator-gate-disposition-contract:end -->"
)
EVALUATOR_DISPOSITION_STATES = (
    "ALL_APPROVED_PLAN",
    "MIXED_DISPOSITIONS_NONCOMPARABLE",
    "NO_APPROVED_FINDINGS",
    "ACCEPTED_EMPTY_LEDGER",
    "INVALID_OR_MISSING_EVIDENCE",
)
EVALUATOR_DISPOSITION_DOC_MARKER = (
    "Any rejection or deferral in either non-empty variant makes the comparison non-comparable."
)
EVALUATOR_REVIEWER_GATE_A_RETURN_HEADING = "### Gate-A pre-disposition return"
EVALUATOR_REVIEWER_FINAL_RETURN_HEADING = "### Final return after dispositions"
EVALUATOR_REVIEWER_HARD_BOUNDARIES_HEADING = "## Hard boundaries"
EVALUATOR_REVIEWER_GATE_A_SECTIONS = (
    "1. `Findings`",
    "2. `Artifacts and hashes`",
    "3. `Limitations`",
    "4. `No-mutation attestation`",
)
EVALUATOR_REVIEWER_FINAL_SECTIONS = (
    "1. `Findings`",
    "2. `Disposition result`",
    "3. `Limitations`",
    "4. `No-mutation attestation`",
)
EVALUATOR_REVIEWER_FINAL_PLAN_RULE = (
    "For `ALL_APPROVED_PLAN` only, also return `Plan`"
)
EVALUATOR_JUDGE_PROTOCOL_START = "<!-- evaluator-judge-protocol:start"
EVALUATOR_JUDGE_PROTOCOL_END = "evaluator-judge-protocol:end -->"
EVALUATOR_JUDGE_PROMPT_MARKER = (
    "The root accepts a response only after validating the complete judge protocol."
)
EVALUATOR_JUDGE_DOC_MARKER = (
    "Judge responses are accepted only after root-side protocol validation."
)

FORBIDDEN_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo"}
MAINTAINER_ONLY_ARCHIVE_PREFIXES = (
    ".agents/skills/material-review-evaluation/",
    ".evaluation-runs/",
    ".superpowers/",
    "docs/superpowers/",
    "evaluations/",
)
LOCAL_RUNTIME_JSON_PREFIXES = (
    ".evaluation-runs/",
    ".superpowers/",
)


def is_maintainer_only_archive_entry(name: str) -> bool:
    return name.startswith(MAINTAINER_ONLY_ARCHIVE_PREFIXES)


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def parse_frontmatter(path: Path, errors: list[str]) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        fail(errors, f"{path.relative_to(ROOT)} lacks YAML frontmatter")
        return {}
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration:
        fail(errors, f"{path.relative_to(ROOT)} has unterminated YAML frontmatter")
        return {}
    result: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip("'\"")
    return result


def load_json(path: Path, errors: list[str]) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(errors, f"invalid JSON in {path.relative_to(ROOT)}: {exc}")
        return None


def load_toml(path: Path, errors: list[str]) -> dict[str, object] | None:
    text = path.read_text(encoding="utf-8")
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
        except Exception as exc:
            fail(errors, f"invalid TOML in {path.relative_to(ROOT)}: {exc}")
            return None
        return data if isinstance(data, dict) else None

    # Python 3.10 has no tomllib. This fallback is deliberately narrow: it checks
    # the required top-level keys while keeping package validation dependency-free.
    result: dict[str, object] = {}
    for key in ("name", "description", "developer_instructions", "sandbox_mode"):
        if re.search(rf"(?m)^{re.escape(key)}\s*=", text):
            result[key] = True
    if re.search(r"(?m)^\[agents\]\s*$", text):
        result["agents"] = True
    return result


def yaml_block_entries(text: str, block_name: str, key: str) -> list[str] | None:
    """Return matching scalar lines from one top-level YAML block.

    The OpenAI metadata shape used here is deliberately small. Keeping this
    parser narrow preserves the standard-library-only validation contract.
    """
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


def validate_openai_activation_metadata(text: str, errors: list[str]) -> None:
    implicit_policy = yaml_block_entries(text, "policy", "allow_implicit_invocation")
    if implicit_policy != ["  allow_implicit_invocation: true"]:
        fail(errors, "openai.yaml must set policy.allow_implicit_invocation exactly to true")

    short_description = yaml_block_entries(text, "interface", "short_description")
    expected_short_description = f'  short_description: "{ACTIVATION_SHORT_DESCRIPTION}"'
    if short_description != [expected_short_description]:
        fail(errors, "openai.yaml short_description does not match the Git-change activation contract")


def validate_maintainer_evaluator_assets(root: Path, errors: list[str]) -> None:
    skill_path = root / ".agents/skills/material-review-evaluation/SKILL.md"
    if not skill_path.is_file():
        return

    text = skill_path.read_text(encoding="utf-8")
    anchor_index = text.find(EVALUATOR_ROOT_ANCHOR)
    clean_attestation_index = text.find(EVALUATOR_INITIAL_CLEAN_ATTESTATION)
    start_index = text.find(EVALUATOR_ASSET_ALLOWLIST_START)
    end_index = text.find(EVALUATOR_ASSET_ALLOWLIST_END)
    if anchor_index < 0:
        fail(errors, "maintainer evaluator lacks repository root attestation")
        return
    if start_index < 0 or end_index < start_index:
        fail(errors, "maintainer evaluator asset allowlist markers are incomplete")
        return
    if clean_attestation_index < 0:
        fail(errors, "maintainer evaluator lacks initial clean checkout attestation")
    elif not anchor_index < clean_attestation_index < start_index:
        fail(
            errors,
            "maintainer evaluator clean checkout attestation must precede asset resolution",
        )
    if anchor_index > start_index:
        fail(errors, "maintainer evaluator asset allowlist precedes repository root attestation")
    if EVALUATOR_NO_FALLBACK not in text[start_index:]:
        fail(errors, "maintainer evaluator asset contract lacks the no-fallback rule")

    block = text[start_index + len(EVALUATOR_ASSET_ALLOWLIST_START) : end_index]
    entries = tuple(re.findall(r"(?m)^\s*- `([^`]+)`\s*$", block))
    for entry in entries:
        pure_path = PurePosixPath(entry)
        if pure_path.is_absolute() or ".." in pure_path.parts:
            fail(errors, "maintainer evaluator asset path escapes the repository root")
    if entries != EVALUATOR_ASSET_ALLOWLIST:
        fail(errors, "maintainer evaluator asset allowlist must match the repository-root contract")

    resolved_root = root.resolve()
    for relative in EVALUATOR_ASSET_ALLOWLIST:
        reference_index = text.find(f"`{relative}`")
        if 0 <= reference_index < anchor_index:
            fail(errors, "maintainer evaluator asset referenced before repository root attestation")
        asset_path = root / relative
        if not asset_path.exists():
            fail(errors, f"maintainer evaluator asset is missing: {relative}")
            continue
        if asset_path.is_symlink() or not asset_path.is_file():
            fail(errors, f"maintainer evaluator asset is not a regular file: {relative}")
            continue
        resolved_asset = asset_path.resolve()
        if resolved_asset != resolved_root and resolved_root not in resolved_asset.parents:
            fail(errors, "maintainer evaluator asset path escapes the repository root")


def parse_evaluator_contract(
    text: str,
    start_marker: str,
    end_marker: str,
    errors: list[str],
    contract_name: str,
) -> dict[str, str] | None:
    start_index = text.find(start_marker)
    end_index = text.find(end_marker)
    if start_index < 0 or end_index < start_index:
        fail(errors, f"maintainer evaluator {contract_name} markers are incomplete")
        return None

    contract: dict[str, str] = {}
    block = text[start_index + len(start_marker) : end_index]
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "=" not in line:
            fail(errors, f"maintainer evaluator {contract_name} contains a malformed entry")
            continue
        key, value = line.split("=", 1)
        if not key or key in contract:
            fail(errors, f"maintainer evaluator {contract_name} contains a duplicate entry")
            continue
        contract[key] = value
    return contract


def validate_maintainer_evaluator_dispatch(root: Path, errors: list[str]) -> None:
    skill_path = root / ".agents/skills/material-review-evaluation/SKILL.md"
    if not skill_path.is_file():
        return
    skill_text = skill_path.read_text(encoding="utf-8")
    contract = parse_evaluator_contract(
        skill_text,
        EVALUATOR_DISPATCH_CONTRACT_START,
        EVALUATOR_DISPATCH_CONTRACT_END,
        errors,
        "dispatch contract",
    )
    if contract is None:
        return

    required_values = (
        ("reviewer_history", "none", "maintainer evaluator dispatch contract must require empty history for reviewers"),
        ("initial_judge_history", "none", "maintainer evaluator dispatch contract must require empty history for the initial judge"),
        ("replacement_judge_history", "none", "maintainer evaluator dispatch contract must require empty history for the replacement judge"),
        ("isolation_unavailable_dispatch", "false", "maintainer evaluator isolation failure must not dispatch a worker"),
        ("isolation_unverifiable_dispatch", "false", "maintainer evaluator unverifiable isolation must not dispatch a worker"),
        ("bounded_nonempty_dispatch", "false", "maintainer evaluator bounded non-empty history must not dispatch a worker"),
        ("isolation_failure_outcome", "INSUFFICIENT_EVIDENCE", "maintainer evaluator isolation failure must produce INSUFFICIENT_EVIDENCE"),
        ("isolation_failure_winner", "none", "maintainer evaluator isolation failure must produce no winner"),
        ("isolation_failure_gate_progression", "false", "maintainer evaluator isolation failure must not progress a user gate"),
        ("isolation_failure_repair_publication_egress", "false", "maintainer evaluator isolation failure must not repair, publish, or egress source"),
    )
    for key, expected, error in required_values:
        if contract.get(key) != expected:
            fail(errors, error)

    fixed_values = {
        "reviewers": "2",
        "codex_fork_turns": "none",
        "worker_message": "self-contained-allowlist",
        "private_dispatch_receipt": "true",
        "recursive_fanout": "false",
    }
    if any(contract.get(key) != value for key, value in fixed_values.items()):
        fail(errors, "maintainer evaluator dispatch contract is incomplete")
    if EVALUATOR_PREDISPATCH_REATTESTATION not in skill_text:
        fail(
            errors,
            "maintainer evaluator must re-attest the active checkout before every dispatch",
        )
    if EVALUATOR_ROOT_DISPATCH_AUTHORITY not in skill_text:
        fail(
            errors,
            "maintainer evaluator dispatch verification must remain root-authoritative",
        )

    for relative, label in (
        ("evaluations/material-code-review/prompts/reviewer.md", "reviewer"),
        ("evaluations/material-code-review/prompts/judge.md", "judge"),
    ):
        prompt_path = root / relative
        if not prompt_path.is_file():
            continue
        prompt_text = prompt_path.read_text(encoding="utf-8")
        if EVALUATOR_CONTEXT_FREE_PROMPT_MARKER not in prompt_text:
            fail(errors, f"{label} prompt must require zero inherited task history")
        if EVALUATOR_PROMPT_ROOT_DISPATCH_AUTHORITY not in prompt_text:
            fail(errors, f"{label} prompt must keep dispatch verification root-side")
        if EVALUATOR_PRIVATE_RECEIPT_REQUIREMENT in prompt_text:
            fail(errors, f"{label} prompt must not require a private dispatch receipt")

    for relative in EVALUATOR_CONTEXT_FREE_DOCS:
        path = root / relative
        if path.is_file() and EVALUATOR_CONTEXT_FREE_DOC_MARKER not in path.read_text(encoding="utf-8"):
            fail(errors, f"{relative} must reference the context-free evaluator dispatch contract")


def validate_maintainer_evaluator_dispositions(root: Path, errors: list[str]) -> None:
    skill_path = root / ".agents/skills/material-review-evaluation/SKILL.md"
    if not skill_path.is_file():
        return
    contract = parse_evaluator_contract(
        skill_path.read_text(encoding="utf-8"),
        EVALUATOR_GATE_DISPOSITION_CONTRACT_START,
        EVALUATOR_GATE_DISPOSITION_CONTRACT_END,
        errors,
        "Gate-A disposition contract",
    )
    if contract is None:
        return

    required_values = (
        ("all_approved", "ALL_APPROVED_PLAN", "maintainer evaluator all-approved state must retain Gate-B plan capture"),
        ("mixed_reject_or_defer", "MIXED_DISPOSITIONS_NONCOMPARABLE", "maintainer evaluator mixed dispositions must be non-comparable"),
        ("zero_approved", "NO_APPROVED_FINDINGS", "maintainer evaluator zero-approved state must preserve native no-approved-findings completion"),
        ("accepted_empty", "ACCEPTED_EMPTY_LEDGER", "maintainer evaluator accepted-empty state must remain distinct"),
        ("invalid_or_missing", "INVALID_OR_MISSING_EVIDENCE", "maintainer evaluator invalid or missing evidence must remain distinct"),
        ("reject_or_defer_policy", "DISPOSITION_NONCOMPARABLE", "maintainer evaluator rejection or deferral policy must fail closed"),
        ("reject_or_defer_outcome", "INSUFFICIENT_EVIDENCE", "maintainer evaluator rejection or deferral must produce INSUFFICIENT_EVIDENCE"),
        ("reject_or_defer_plan", "false", "maintainer evaluator rejection or deferral must not fabricate a plan"),
        ("native_controller_change", "false", "maintainer evaluator disposition policy must not change the native controller"),
    )
    for key, expected, error in required_values:
        if contract.get(key) != expected:
            fail(errors, error)
    fixed_values = {
        "reject_or_defer_winner": "none",
        "reject_or_defer_gate_b": "false",
        "disposition_evidence": "ledger-hash,gate-receipt-hash,anonymous-dispositions,native-state",
    }
    if any(contract.get(key) != value for key, value in fixed_values.items()):
        fail(errors, "maintainer evaluator Gate-A disposition contract is incomplete")

    for relative in (
        ".agents/skills/material-review-evaluation/SKILL.md",
        "evaluations/material-code-review/prompts/reviewer.md",
        "evaluations/material-code-review/prompts/judge.md",
        "evaluations/material-code-review/rubric.md",
    ):
        path = root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if any(state not in text for state in EVALUATOR_DISPOSITION_STATES) or "DISPOSITION_NONCOMPARABLE" not in text:
            fail(errors, f"{relative} must define every evaluator disposition state")

    for relative in EVALUATOR_CONTEXT_FREE_DOCS:
        path = root / relative
        if path.is_file() and EVALUATOR_DISPOSITION_DOC_MARKER not in path.read_text(encoding="utf-8"):
            fail(errors, f"{relative} must state the evaluator rejection and deferral policy")


def validate_maintainer_evaluator_reviewer_returns(
    root: Path,
    errors: list[str],
) -> None:
    reviewer_path = root / "evaluations/material-code-review/prompts/reviewer.md"
    if not reviewer_path.is_file():
        return

    text = reviewer_path.read_text(encoding="utf-8")
    gate_a_index = text.find(EVALUATOR_REVIEWER_GATE_A_RETURN_HEADING)
    final_index = text.find(EVALUATOR_REVIEWER_FINAL_RETURN_HEADING)
    hard_boundaries_index = text.find(EVALUATOR_REVIEWER_HARD_BOUNDARIES_HEADING)
    if gate_a_index < 0:
        fail(errors, "reviewer prompt must define the Gate-A pre-disposition return")
        return
    if final_index < 0:
        fail(errors, "reviewer prompt must define the final return after dispositions")
        return
    if hard_boundaries_index < final_index or final_index < gate_a_index:
        fail(errors, "reviewer prompt return schemas are out of order")
        return

    gate_a_block = text[gate_a_index:final_index]
    final_block = text[final_index:hard_boundaries_index]
    if any(section not in gate_a_block for section in EVALUATOR_REVIEWER_GATE_A_SECTIONS):
        fail(errors, "reviewer Gate-A pre-disposition return is incomplete")
    if re.search(r"(?m)^\d+\. `Plan(?: hash)?`", gate_a_block):
        fail(errors, "reviewer Gate-A pre-disposition return must not require a plan")
    if any(section not in final_block for section in EVALUATOR_REVIEWER_FINAL_SECTIONS):
        fail(errors, "reviewer final return after dispositions is incomplete")
    if EVALUATOR_REVIEWER_FINAL_PLAN_RULE not in final_block:
        fail(errors, "reviewer prompt must limit plan evidence to ALL_APPROVED_PLAN")


def validate_maintainer_evaluator_judge_protocol(root: Path, errors: list[str]) -> None:
    skill_path = root / ".agents/skills/material-review-evaluation/SKILL.md"
    if not skill_path.is_file():
        return
    contract = parse_evaluator_contract(
        skill_path.read_text(encoding="utf-8"),
        EVALUATOR_JUDGE_PROTOCOL_START,
        EVALUATOR_JUDGE_PROTOCOL_END,
        errors,
        "judge protocol",
    )
    if contract is None:
        return

    required_values = (
        ("public_outcomes", "VARIANT_A_STRONGER,VARIANT_B_STRONGER,MATERIAL_TIE,INSUFFICIENT_EVIDENCE", "maintainer evaluator judge protocol must preserve the four public outcomes"),
        ("valid_outcome_count", "1", "maintainer evaluator must accept exactly one judge outcome"),
        ("required_sections", "Outcome,Finding comparison,Repair-plan comparison,Limitations and uncertainty,Citations", "maintainer evaluator must validate every ordered judge section"),
        ("citations", "anonymous-artifacts,frozen-source", "maintainer evaluator must validate anonymous artifact and frozen-source citations"),
        ("identity_data", "forbidden", "maintainer evaluator must reject identity-bearing judgment data"),
        ("judgment_before_mapping", "true", "maintainer evaluator must write judgment before revealing the private mapping"),
        ("max_attempts", "2", "maintainer evaluator judge protocol must allow at most two attempts"),
        ("attempt_2_trigger", "first-identity-leak-only", "maintainer evaluator second judge attempt must be limited to a first identity leak"),
        ("other_invalid_first_replacement", "false", "maintainer evaluator must not retry other invalid first judgments"),
        ("second_leak_replacement", "false", "maintainer evaluator must not retry a second identity leak"),
        ("terminal_outcome", "INSUFFICIENT_EVIDENCE", "maintainer evaluator invalid judge terminal must produce INSUFFICIENT_EVIDENCE"),
        ("terminal_winner", "none", "maintainer evaluator invalid judge terminal must produce no winner"),
        ("private_terminal_reason", "judge-invalid", "maintainer evaluator judge-invalid reason must remain private"),
        ("raw_attempts", "private-local", "maintainer evaluator raw judge attempts must remain private local evidence"),
        ("interrupted_run", "preserve-and-new-invocation", "maintainer evaluator interrupted runs must not become judge retries"),
        ("repair_publication_egress_resume", "false", "maintainer evaluator invalid judge terminal must not repair, publish, egress, or resume"),
    )
    for key, expected, error in required_values:
        if contract.get(key) != expected:
            fail(errors, error)

    judge_prompt = root / "evaluations/material-code-review/prompts/judge.md"
    if judge_prompt.is_file() and EVALUATOR_JUDGE_PROMPT_MARKER not in judge_prompt.read_text(encoding="utf-8"):
        fail(errors, "judge prompt must require root-side protocol validation")
    rubric = root / "evaluations/material-code-review/rubric.md"
    if rubric.is_file():
        rubric_text = rubric.read_text(encoding="utf-8")
        if "private `judge-invalid` reason" not in rubric_text or "fifth public outcome" not in rubric_text:
            fail(errors, "evaluator rubric must preserve bounded judge-invalid semantics")

    for relative in EVALUATOR_CONTEXT_FREE_DOCS:
        path = root / relative
        if path.is_file() and EVALUATOR_JUDGE_DOC_MARKER not in path.read_text(encoding="utf-8"):
            fail(errors, f"{relative} must state the bounded judge-validation protocol")


def iter_files(root: Path) -> Iterable[Path]:
    """Yield package files while excluding this checkout's own Git metadata.

    Only the root-level `.git` entry is ignored. Nested `.git` entries remain
    visible so accidental vendored repository metadata is still rejected by
    the existing forbidden-path checks.
    """
    for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        base = Path(directory)
        if base == root:
            dirnames[:] = [name for name in dirnames if name != ".git"]
            filenames[:] = [name for name in filenames if name != ".git"]

        symlink_directories = [name for name in dirnames if (base / name).is_symlink()]
        dirnames[:] = sorted(name for name in dirnames if name not in symlink_directories)

        for name in sorted(symlink_directories):
            yield base / name
        for name in sorted(filenames):
            path = base / name
            if path.is_file() or path.is_symlink():
                yield path


def check_source_package(
    root: Path,
    *,
    distribution_layout: bool = False,
) -> list[str]:
    errors: list[str] = []
    if sys.version_info < (3, 10):
        return ["package validation requires Python 3.10+"]
    if not root.is_dir():
        return [f"package root is not a directory: {root}"]

    actual = {path.relative_to(root).as_posix() for path in iter_files(root)}
    required = DISTRIBUTABLE_REQUIRED
    if not distribution_layout:
        required = required | MAINTAINER_SOURCE_REQUIRED
    for rel in sorted(required - actual):
        fail(errors, f"missing required file: {rel}")

    for rel in sorted(actual):
        path = Path(rel)
        if any(part in FORBIDDEN_PARTS for part in path.parts) or path.suffix in FORBIDDEN_SUFFIXES:
            fail(errors, f"forbidden generated/VCS path in source package: {rel}")

    codex = load_json(root / ".codex-plugin/plugin.json", errors)
    if isinstance(codex, dict):
        for key in ("name", "version", "description", "skills"):
            if key not in codex:
                fail(errors, f"Codex manifest missing {key}")
        if codex.get("name") != "material-code-review":
            fail(errors, "Codex plugin name must be material-code-review")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", str(codex.get("name", ""))):
            fail(errors, "Codex plugin name is not kebab-case")
        if codex.get("version") != VERSION:
            fail(errors, f"Codex manifest version must be {VERSION}")
        if codex.get("description") != ACTIVATION_DISCOVERY_DESCRIPTION:
            fail(errors, "Codex manifest description does not match the Git-change activation contract")
        interface = codex.get("interface")
        if not isinstance(interface, dict):
            fail(errors, "Codex manifest interface must be an object")
        else:
            if interface.get("shortDescription") != ACTIVATION_SHORT_DESCRIPTION:
                fail(errors, "Codex manifest shortDescription does not match the Git-change activation contract")
            if interface.get("longDescription") != ACTIVATION_DISCOVERY_DESCRIPTION:
                fail(errors, "Codex manifest longDescription does not match the Git-change activation contract")
        skills_value = codex.get("skills")
        if isinstance(skills_value, str):
            if not skills_value.startswith("./"):
                fail(errors, "Codex skills path must start with ./")
            skills_path = (root / skills_value).resolve()
            try:
                skills_path.relative_to(root.resolve())
            except ValueError:
                fail(errors, "Codex skills path escapes plugin root")
            if not skills_path.is_dir():
                fail(errors, "Codex skills path does not exist")
        else:
            fail(errors, "Codex skills path must be a string")

    marketplace = load_json(root / ".agents/plugins/marketplace.json", errors)
    if isinstance(marketplace, dict):
        plugins = marketplace.get("plugins")
        if not isinstance(plugins, list) or len(plugins) != 1:
            fail(errors, "Codex marketplace must expose exactly this plugin")
        else:
            entry = plugins[0]
            if not isinstance(entry, dict) or entry.get("name") != "material-code-review":
                fail(errors, "Codex marketplace plugin name mismatch")
            else:
                source = entry.get("source")
                if not isinstance(source, dict) or source.get("source") != "local" or source.get("path") != "./":
                    fail(errors, "Codex marketplace local source must be {source: local, path: ./}")
                policy = entry.get("policy")
                if not isinstance(policy, dict) or policy.get("installation") != "AVAILABLE" or policy.get("authentication") != "ON_INSTALL":
                    fail(errors, "Codex marketplace policy is incomplete")
                if not entry.get("category"):
                    fail(errors, "Codex marketplace category is required")

    claude = load_json(root / ".claude-plugin/plugin.json", errors)
    claude_market = load_json(root / ".claude-plugin/marketplace.json", errors)
    if isinstance(claude, dict):
        if claude.get("name") != "material-code-review" or claude.get("version") != VERSION:
            fail(errors, "Claude and Codex manifest identity/version differ")
        if claude.get("description") != ACTIVATION_DISCOVERY_DESCRIPTION:
            fail(errors, "Claude manifest description does not match the Git-change activation contract")
    if isinstance(claude_market, dict) and claude_market.get("version") != VERSION:
        fail(errors, f"Claude marketplace version must be {VERSION}")
    if isinstance(claude_market, dict):
        plugins = claude_market.get("plugins")
        if not isinstance(plugins, list) or len(plugins) != 1 or not isinstance(plugins[0], dict):
            fail(errors, "Claude marketplace must expose exactly this plugin")
        elif plugins[0].get("description") != ACTIVATION_DISCOVERY_DESCRIPTION:
            fail(errors, "Claude marketplace description does not match the Git-change activation contract")

    for rel in ("SKILL.md", "skills/material-code-review/SKILL.md"):
        path = root / rel
        if not path.is_file():
            continue
        frontmatter = parse_frontmatter(path, errors)
        if frontmatter.get("name") != "material-code-review":
            fail(errors, f"{rel} has wrong skill name")
        if frontmatter.get("description") != ACTIVATION_DISCOVERY_DESCRIPTION:
            fail(errors, f"{rel} description does not match the Git-change activation contract")

    canonical_review_skill = root / "skills/material-code-review/SKILL.md"
    material_review_command = root / "commands/material-review.md"
    if canonical_review_skill.is_file() and material_review_command.is_file():
        canonical_frontmatter = parse_frontmatter(canonical_review_skill, errors)
        command_frontmatter = parse_frontmatter(material_review_command, errors)
        if command_frontmatter.get("argument-hint") != canonical_frontmatter.get(
            "argument-hint"
        ):
            fail(errors, "command argument hint does not match canonical review skill")

    evaluator_skill = root / ".agents/skills/material-review-evaluation/SKILL.md"
    if not distribution_layout and evaluator_skill.is_file():
        frontmatter = parse_frontmatter(evaluator_skill, errors)
        if frontmatter.get("name") != "material-review-evaluation":
            fail(errors, "maintainer evaluator skill has wrong name")
        if not frontmatter.get("description", "").startswith("Use when "):
            fail(errors, "maintainer evaluator skill description must start with 'Use when '")
        if (
            frontmatter.get("argument-hint")
            != "base:<skill-ref> candidate:<skill-ref>"
        ):
            fail(errors, "maintainer evaluator skill has wrong argument hint")
        validate_maintainer_evaluator_assets(root, errors)
        validate_maintainer_evaluator_dispatch(root, errors)
        validate_maintainer_evaluator_dispositions(root, errors)
        validate_maintainer_evaluator_reviewer_returns(root, errors)
        validate_maintainer_evaluator_judge_protocol(root, errors)

    openai_yaml = root / "skills/material-code-review/agents/openai.yaml"
    if openai_yaml.is_file():
        text = openai_yaml.read_text(encoding="utf-8")
        for token in ("interface:", "display_name:", "short_description:", "default_prompt:", "policy:"):
            if token not in text:
                fail(errors, f"openai.yaml missing {token}")
        validate_openai_activation_metadata(text, errors)

    custom_agents = sorted((root / "examples/codex-project-config/.codex/agents").glob("*.toml"))
    for path in custom_agents:
        data = load_toml(path, errors)
        if not isinstance(data, dict):
            continue
        for key in ("name", "description", "developer_instructions"):
            value = data.get(key)
            if tomllib is not None:
                if not isinstance(value, str) or not value.strip():
                    fail(errors, f"{path.relative_to(root)} missing non-empty {key}")
            elif not value:
                fail(errors, f"{path.relative_to(root)} missing {key}")
        if tomllib is not None and data.get("sandbox_mode") != "read-only":
            fail(errors, f"{path.relative_to(root)} must be read-only")

    project_config = root / "examples/codex-project-config/.codex/config.toml"
    if project_config.is_file():
        data = load_toml(project_config, errors)
        if isinstance(data, dict):
            agents = data.get("agents")
            if tomllib is not None:
                if not isinstance(agents, dict) or agents.get("max_depth") != 1:
                    fail(errors, "example Codex config must keep agents.max_depth=1")
            elif not agents:
                fail(errors, "example Codex config lacks [agents]")

    canonical = root / "skills/material-code-review/SKILL.md"
    if canonical.is_file():
        text = canonical.read_text(encoding="utf-8")
        refs = set(re.findall(r"`((?:references|schemas)/[A-Za-z0-9._/-]+)`", text))
        for rel in sorted(refs):
            if not (canonical.parent / rel).is_file():
                fail(errors, f"canonical skill references missing file: {rel}")
        if "No mutation before Gate B" not in text:
            fail(errors, "canonical skill no longer states the pre-Gate-B mutation invariant")
        if "No improvement recursion" not in text:
            fail(errors, "canonical skill must preserve the post-fix no-improvement-loop rule")
        for marker in ACTIVATION_PREFLIGHT_MARKERS:
            if marker not in text:
                fail(errors, f"canonical skill activation preflight missing marker: {marker}")
        for marker in DISCOVERY_CONTROL_MARKERS:
            if marker not in text:
                fail(errors, f"canonical skill discovery contract missing marker: {marker}")
        for marker in RECOVERY_CONTROL_MARKERS:
            if marker not in text:
                fail(errors, f"canonical skill recovery contract missing marker: {marker}")

    for path in sorted((root / "skills/material-code-review/schemas").glob("*.json")):
        data = load_json(path, errors)
        if isinstance(data, dict):
            if data.get("type") != "object":
                fail(errors, f"{path.relative_to(root)} schema root must be object")
            if data.get("additionalProperties") is not False:
                fail(errors, f"{path.relative_to(root)} must set additionalProperties=false")

    for path in iter_files(root):
        relative_path = path.relative_to(root).as_posix()
        if (
            path.suffix.lower() == ".json"
            and path.is_file()
            and not relative_path.startswith(LOCAL_RUNTIME_JSON_PREFIXES)
        ):
            load_json(path, errors)

    for relative_wrapper in ("bin/material-reviewctl",):
        wrapper = root / relative_wrapper
        if (
            wrapper.exists()
            and os.name != "nt"
            and not (wrapper.stat().st_mode & stat.S_IXUSR)
        ):
            fail(errors, f"{relative_wrapper} is not executable")

    controller = root / "skills/material-code-review/scripts/reviewctl.py"
    if controller.is_file():
        text = controller.read_text(encoding="utf-8")
        if f'TOOL_VERSION = "{VERSION}"' not in text:
            fail(errors, "controller version does not match package version")
        for marker in RECOVERY_CONTROL_MARKERS[:2]:
            if marker not in text:
                fail(errors, f"controller recovery surface missing marker: {marker}")
        if os.name != "nt" and not (controller.stat().st_mode & stat.S_IXUSR):
            fail(errors, "reviewctl.py is not executable")

    packager = root / "scripts/package_plugin.py"
    if packager.is_file():
        text = packager.read_text(encoding="utf-8")
        if f'VERSION = "{VERSION}"' not in text:
            fail(errors, "archive builder version does not match package version")

    readme = root / "README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        for token in (
            ".codex-plugin/plugin.json",
            "codex plugin marketplace add",
            "lifecycle, boundary, restoration, direction-audit, plan-handoff, simplification, and artifact-integrity tests",
            "## Invocation and activation boundary",
            "implicit selection remains model-mediated",
            "no behavioral skill-selection evaluation harness",
        ):
            if token not in text:
                fail(errors, f"README lacks required Codex or validation text: {token}")

    return errors


def check_zip(path: Path, *, standalone: bool) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        return [f"archive not found: {path}"]
    try:
        with zipfile.ZipFile(path) as zf:
            raw_names = [name for name in zf.namelist() if not name.endswith("/")]
            archive_entries = []
            for raw_name in raw_names:
                canonical_name = PurePosixPath(raw_name.replace("\\", "/")).as_posix()
                archive_entries.append((raw_name, canonical_name))
                if raw_name != canonical_name:
                    fail(errors, f"{path.name}: noncanonical archive path {raw_name}")

            canonical_names = [canonical for _, canonical in archive_entries]
            if len(canonical_names) != len(set(canonical_names)):
                fail(errors, f"{path.name}: duplicate archive entries")
            for raw_name, canonical_name in archive_entries:
                rel = PurePosixPath(canonical_name)
                if rel.is_absolute() or ".." in rel.parts:
                    fail(errors, f"{path.name}: unsafe archive path {raw_name}")
                if any(part in FORBIDDEN_PARTS for part in rel.parts) or rel.suffix in FORBIDDEN_SUFFIXES:
                    fail(errors, f"{path.name}: forbidden archive entry {raw_name}")
                if is_maintainer_only_archive_entry(canonical_name):
                    fail(
                        errors,
                        f"{path.name}: forbidden maintainer-only archive entry {raw_name}",
                    )
            names = {
                canonical_name
                for raw_name, canonical_name in archive_entries
                if raw_name == canonical_name
            }
            required = (
                {
                    "SKILL.md",
                    "agents/openai.yaml",
                    "scripts/reviewctl.py",
                    "schemas/candidate-set.schema.json",
                    "schemas/candidate-preflight.schema.json",
                    "schemas/fallback-assignment.schema.json",
                    "schemas/reviewer-failure-attestation.schema.json",
                    "schemas/coverage-plan.schema.json",
                    "schemas/coverage-status.schema.json",
                    "references/protocol-coherence-lens.md",
                }
                if standalone
                else {
                    "SKILL.md",
                    ".codex-plugin/plugin.json",
                    ".agents/plugins/marketplace.json",
                    "skills/material-code-review/SKILL.md",
                    "skills/material-code-review/agents/openai.yaml",
                    "skills/material-code-review/schemas/candidate-preflight.schema.json",
                    "skills/material-code-review/schemas/fallback-assignment.schema.json",
                    "skills/material-code-review/schemas/reviewer-failure-attestation.schema.json",
                    "skills/material-code-review/schemas/coverage-plan.schema.json",
                    "skills/material-code-review/schemas/coverage-status.schema.json",
                    "skills/material-code-review/references/protocol-coherence-lens.md",
                    "agents/protocol-reviewer.md",
                    "scripts/package_plugin.py",
                }
            )
            for rel in sorted(required - names):
                fail(errors, f"{path.name}: missing archive entry {rel}")
            bad_prefixes = {name.split("/", 1)[0] for name in names if name.startswith("material-code-review-plugin/")}
            if bad_prefixes:
                fail(errors, f"{path.name}: archive has an unwanted wrapper directory")
            if not standalone and ".codex-plugin/plugin.json" in names:
                manifest = json.loads(zf.read(".codex-plugin/plugin.json"))
                if manifest.get("version") != VERSION or manifest.get("name") != "material-code-review":
                    fail(errors, f"{path.name}: embedded Codex manifest identity/version mismatch")
    except (zipfile.BadZipFile, json.JSONDecodeError) as exc:
        fail(errors, f"{path.name}: invalid ZIP or embedded JSON: {exc}")
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", default=str(ROOT), help="Source package root")
    parser.add_argument(
        "--distribution-layout",
        action="store_true",
        help="Validate an extracted distributable that intentionally omits maintainer-only files",
    )
    parser.add_argument("--full-archive", action="append", default=[], help="Full package ZIP to validate")
    parser.add_argument("--standalone-archive", action="append", default=[], help="Standalone Codex skill ZIP to validate")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    errors = check_source_package(
        Path(args.package_root).resolve(),
        distribution_layout=args.distribution_layout,
    )
    for raw in args.full_archive:
        errors.extend(check_zip(Path(raw).resolve(), standalone=False))
    for raw in args.standalone_archive:
        errors.extend(check_zip(Path(raw).resolve(), standalone=True))
    if errors:
        print("[FAIL] material-code-review package validation", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"[OK] material-code-review package {VERSION} is structurally valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
