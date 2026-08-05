#!/usr/bin/env python3
"""Validate the dual-host material-code-review source package and ZIP archives."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
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
STATIC_VERSION_HELPER_DIR = ROOT / "skills/material-code-review/scripts"
sys.path.insert(0, str(STATIC_VERSION_HELPER_DIR))
from static_version_contract import (  # noqa: E402
    validate_static_version_declaration,
)
from package_layout_contract import (  # noqa: E402
    is_safe_relative_package_path,
    local_schema_reference_errors,
    normalize_package_path,
    portable_archive_member_key,
    regular_zip_member_metadata_error,
    schema_version_is_supported,
)
VERSION = "1.5.1"
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
    "material-review/state/v4",
    "material-review/coverage-plan/v3",
    "material-review/candidate-set/v4",
    "material-review/candidates-normalized/v4",
    "change_units",
    "review_obligations",
    "assignment_id",
    "check_results",
    "record-coverage",
    "user_selectable_output_paths",
    "persisted_config_semantics",
    "Missing required assignment coverage",
    "CONSEQUENCE_UNSUPPORTED",
    "plausibly blocker/high",
)

LAYOUT_MANIFEST_SOURCE = Path("skills/material-code-review/package-layouts.json")
LAYOUT_NAMES = ("full-plugin", "standalone")
MAINTAINER_SOURCE_REQUIRED = {
    ".agents/skills/material-review-evaluation/SKILL.md",
    "EVALUATION.md",
    "evaluations/material-code-review/README.md",
    "evaluations/material-code-review/cases/discogs-custom-playlists.json",
    "evaluations/material-code-review/cases/missed-contracts.json",
    "evaluations/material-code-review/prompts/reviewer.md",
    "evaluations/material-code-review/prompts/challenger.md",
    "evaluations/material-code-review/prompts/judge.md",
    "evaluations/material-code-review/rubric.md",
    "evaluations/material-code-review/fixtures/missed-contracts/base/AGENTS.md",
    "evaluations/material-code-review/fixtures/missed-contracts/base/scripts/validate_package.py",
    "evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/scripts/validate_package.py",
    "evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/references/workflow.md",
    "evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/schemas/candidate-set.json",
    "evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/schemas/coverage-plan.json",
    "evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/package-layouts.json",
    "evaluations/material-code-review/fixtures/missed-contracts/review/scripts/validate_package.py",
    "evaluations/material-code-review/fixtures/missed-contracts/review/skills/demo/scripts/validate_package.py",
    "evaluations/material-code-review/fixtures/missed-contracts/review/skills/demo/references/workflow.md",
    "evaluations/material-code-review/fixtures/missed-contracts/review/skills/demo/schemas/candidate-set.json",
    "evaluations/material-code-review/fixtures/missed-contracts/review/skills/demo/schemas/coverage-plan.json",
}
EVALUATOR_ASSET_ALLOWLIST = (
    "evaluations/material-code-review/cases/discogs-custom-playlists.json",
    "evaluations/material-code-review/cases/missed-contracts.json",
    "evaluations/material-code-review/prompts/reviewer.md",
    "evaluations/material-code-review/prompts/challenger.md",
    "evaluations/material-code-review/prompts/judge.md",
    "evaluations/material-code-review/rubric.md",
    "evaluations/material-code-review/fixtures/missed-contracts/base/AGENTS.md",
    "evaluations/material-code-review/fixtures/missed-contracts/base/scripts/validate_package.py",
    "evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/scripts/validate_package.py",
    "evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/references/workflow.md",
    "evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/schemas/candidate-set.json",
    "evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/schemas/coverage-plan.json",
    "evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/package-layouts.json",
    "evaluations/material-code-review/fixtures/missed-contracts/review/scripts/validate_package.py",
    "evaluations/material-code-review/fixtures/missed-contracts/review/skills/demo/scripts/validate_package.py",
    "evaluations/material-code-review/fixtures/missed-contracts/review/skills/demo/references/workflow.md",
    "evaluations/material-code-review/fixtures/missed-contracts/review/skills/demo/schemas/candidate-set.json",
    "evaluations/material-code-review/fixtures/missed-contracts/review/skills/demo/schemas/coverage-plan.json",
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
EVALUATOR_FIXTURE_OBJECT_FORMAT_CONTRACT_START = (
    "<!-- evaluator-fixture-object-format-contract:start"
)
EVALUATOR_FIXTURE_OBJECT_FORMAT_CONTRACT_END = (
    "evaluator-fixture-object-format-contract:end -->"
)
EVALUATOR_DISPATCH_CONTRACT_START = "<!-- evaluator-dispatch-contract:start"
EVALUATOR_DISPATCH_CONTRACT_END = "evaluator-dispatch-contract:end -->"
EVALUATOR_CONTAMINATION_CONTRACT_START = (
    "<!-- evaluator-worker-contamination-contract:start"
)
EVALUATOR_CONTAMINATION_CONTRACT_END = (
    "evaluator-worker-contamination-contract:end -->"
)
EVALUATOR_CHALLENGER_CONTRACT_START = (
    "<!-- evaluator-challenger-boundary-contract:start"
)
EVALUATOR_CHALLENGER_CONTRACT_END = (
    "evaluator-challenger-boundary-contract:end -->"
)
EVALUATOR_CONTEXT_FREE_PROMPT_MARKER = (
    "The root dispatcher must provide zero inherited task history."
)
EVALUATOR_PREDISPATCH_REATTESTATION = (
    "Immediately before each reviewer, challenger, or judge dispatch, recapture the active material-review "
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
    "Every reviewer, challenger, and judge dispatch uses a self-contained request with zero inherited task history."
)
EVALUATOR_CONTEXT_FREE_DOCS = (
    "README.md",
    "EVALUATION.md",
    "evaluations/material-code-review/README.md",
)
RETIRED_MAINTAINER_SOURCE_PATHS = frozenset(
    {
        "docs/superpowers/plans/2026-07-27-material-review-version-evaluator.md",
        "docs/superpowers/specs/2026-07-27-material-review-version-evaluation-design.md",
    }
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

MISSED_CONTRACT_BASE_FILES = frozenset(
    {
        "AGENTS.md",
        "scripts/validate_package.py",
        "skills/demo/scripts/validate_package.py",
        "skills/demo/references/workflow.md",
        "skills/demo/schemas/candidate-set.json",
        "skills/demo/schemas/coverage-plan.json",
        "skills/demo/package-layouts.json",
    }
)
MISSED_CONTRACT_REVIEW_FILES = MISSED_CONTRACT_BASE_FILES - {
    "AGENTS.md",
    "skills/demo/package-layouts.json",
}
MISSED_CONTRACT_ROOT_IDS = frozenset(
    {
        "version-decoy",
        "workflow-missing-scope",
        "path-language",
        "risk-cardinality",
        "archive-closure",
    }
)
MISSED_CONTRACT_ROOT_CONTRACTS = {
    "version-decoy": "The validator trusts raw source text instead of one top-level literal assignment.",
    "workflow-missing-scope": "Coverage can be recorded without the required fresh-scope check.",
    "path-language": "The candidate schema accepts path forms rejected by runtime validation.",
    "risk-cardinality": "The coverage schema permits a duplicate required risk while omitting another.",
    "archive-closure": "Archive validation uses an incomplete hand-maintained required-entry set.",
}
MISSED_CONTRACT_RETIRED_GUIDANCE = (
    "release versions are accepted only from one top-level literal assignment parsed as Python syntax;",
    "`check-scope` precedes `record-coverage` in the normative workflow;",
    "schema and runtime path validation accept only canonical repository-relative Git paths, excluding absolute, drive, UNC, backslash, and dot-component forms;",
    "every required risk role occurs exactly once in a coverage plan; and",
    "archive validation derives its complete required-entry closure from the canonical package layout instead of a second hand-maintained subset.",
)
MISSED_CONTRACT_WORKER_GUIDANCE_PATHS = (
    "evaluations/material-code-review/fixtures/missed-contracts/base/AGENTS.md",
    "evaluations/material-code-review/prompts/reviewer.md",
    "evaluations/material-code-review/prompts/challenger.md",
    "evaluations/material-code-review/prompts/judge.md",
    "evaluations/material-code-review/rubric.md",
)
MISSED_CONTRACT_TOP_LEVEL_POLICY = {
    "schema_version": "material-review-evaluation/case/v1",
    "case_id": "missed-contracts",
    "target_type": "git_fixture",
    "review_mode": "range",
    "posture": "immutable",
    "require_immediate_parent": True,
}
MISSED_CONTRACT_TOP_LEVEL_KEYS = frozenset(
    {
        *MISSED_CONTRACT_TOP_LEVEL_POLICY,
        "fixture",
        "required_root_ids",
        "root_contracts",
        "acceptance",
        "attempt_policy",
    }
)
MISSED_CONTRACT_FIXTURE_POLICY = {
    "base_root": "evaluations/material-code-review/fixtures/missed-contracts/base",
    "review_root": "evaluations/material-code-review/fixtures/missed-contracts/review",
    "author_name": "Material Review Fixture",
    "author_email": "fixture@example.invalid",
    "base_timestamp": "2026-07-30T12:00:00+00:00",
    "review_timestamp": "2026-07-30T12:01:00+00:00",
    "base_message": "fixture: establish contract controls",
    "review_message": "fixture: introduce missed contracts",
}
MISSED_CONTRACT_FIXTURE_KEYS = frozenset(
    {
        *MISSED_CONTRACT_FIXTURE_POLICY,
        "base_tree",
        "review_tree",
        "base_commit",
        "review_commit",
    }
)
MISSED_CONTRACT_ACCEPTANCE_POLICY = {
    "candidate_must_support_every_required_root": True,
    "preserve_every_baseline_material_root": True,
    "unsupported_high_severity_additions": 0,
    "require_controller_valid_gate_a_evidence": True,
    "require_no_mutation": True,
    "require_complete_obligations": True,
    "require_no_coverage_gap": True,
}
MISSED_CONTRACT_ATTEMPT_POLICY = {
    "comparisons": 1,
    "repair_confirmations": 1,
    "repair_confirmation_requires_concrete_implementation_defect": True,
    "resampling": False,
}
EVALUATOR_CHALLENGER_CONTRACT = {
    "case": "missed-contracts",
    "challenger_inputs": "frozen-source,change-units,risk-decisions,obligations,assignments,limitations",
    "challenger_forbidden": "candidates,candidate-sets,check-results,adjudication,ledgers,plans,expected-roots,variant-identities,refs,private-mapping,other-variant,prior-output",
    "challenger_claim": "declarative-coverage-only",
    "challenger_outcomes": "NO_COVERAGE_GAP,COVERAGE_GAP",
    "no_coverage_gap_proves": "declarative-coverage-only",
    "native_assignment_validation": "required-independent",
    "native_obligation_validation": "required-independent",
    "native_check_results_fresh": "true",
    "native_check_results_complete": "true",
    "native_check_results_unblocked": "true",
    "native_check_results_unique": "true",
    "native_check_results_resolved": "true",
    "native_gate_a_validation": "required-independent",
    "invalid_empty_or_gap": "blocks-success-no-retry",
    "challenge_response_to_reviewer": "false",
    "default_discogs_challenger": "false",
}

FORBIDDEN_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo"}
MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_MEMBER_SIZE = 100 * 1024 * 1024
MAX_ARCHIVE_CUMULATIVE_SIZE = 500 * 1024 * 1024
MAX_ARCHIVE_COMPRESSION_RATIO = 100
LAYOUT_EXCLUDED_PARTS = FORBIDDEN_PARTS | {".hypothesis", ".tox", ".nox", "dist"}
LAYOUT_EXCLUDED_SUFFIXES = FORBIDDEN_SUFFIXES | {".zip", ".sha256"}
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


def is_maintainer_only_archive_entry(name: str) -> bool:
    return name.startswith(MAINTAINER_ONLY_ARCHIVE_PREFIXES)


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


class ArchiveResourceError(ValueError):
    """Raised when an archive exceeds the bounded validation policy."""


def preflight_archive_resources(
    archive_name: str,
    members: list[zipfile.ZipInfo],
) -> str | None:
    if len(members) > MAX_ARCHIVE_MEMBERS:
        return (
            f"{archive_name}: archive exceeds maximum member count of "
            f"{MAX_ARCHIVE_MEMBERS}"
        )
    cumulative_size = 0
    for member in members:
        if member.file_size > MAX_ARCHIVE_MEMBER_SIZE:
            return (
                f"{archive_name}: member {member.filename} exceeds maximum size of "
                f"{MAX_ARCHIVE_MEMBER_SIZE} bytes"
            )
        cumulative_size += member.file_size
        if cumulative_size > MAX_ARCHIVE_CUMULATIVE_SIZE:
            return (
                f"{archive_name}: cumulative expanded size exceeds maximum of "
                f"{MAX_ARCHIVE_CUMULATIVE_SIZE} bytes"
            )
        if member.file_size > 0 and member.compress_size == 0:
            return (
                f"{archive_name}: nonempty member {member.filename} has zero "
                "compressed size"
            )
        if (
            member.compress_size > 0
            and member.file_size
            > member.compress_size * MAX_ARCHIVE_COMPRESSION_RATIO
        ):
            return (
                f"{archive_name}: member {member.filename} compression ratio "
                f"exceeds maximum of {MAX_ARCHIVE_COMPRESSION_RATIO}"
            )
    return None


def read_bounded_archive_member(
    archive: zipfile.ZipFile,
    member_name: str,
    archive_name: str,
) -> bytes:
    with archive.open(archive.getinfo(member_name), "r") as member:
        payload = member.read(MAX_ARCHIVE_MEMBER_SIZE + 1)
    if len(payload) > MAX_ARCHIVE_MEMBER_SIZE:
        raise ArchiveResourceError(
            f"{archive_name}: member {member_name} exceeds bounded read limit of "
            f"{MAX_ARCHIVE_MEMBER_SIZE} bytes"
        )
    return payload


def normalize_layout_path(value: object, label: str) -> str:
    return normalize_package_path(value, f"layout {label}")


def load_layout_manifest(
    root: Path,
    errors: list[str],
) -> dict[str, dict[str, object]] | None:
    manifest_path = root / LAYOUT_MANIFEST_SOURCE
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(errors, f"missing package layout manifest: {LAYOUT_MANIFEST_SOURCE.as_posix()}")
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(errors, f"invalid package layout manifest: {exc}")
        return None
    if not isinstance(manifest, dict) or not schema_version_is_supported(
        manifest.get("schema_version")
    ):
        fail(errors, "package layout manifest schema_version must be 1")
        return None
    layouts = manifest.get("layouts")
    if not isinstance(layouts, dict) or set(layouts) != set(LAYOUT_NAMES):
        fail(errors, "package layout manifest must define full-plugin and standalone")
        return None

    normalized_layouts: dict[str, dict[str, object]] = {}
    try:
        for layout_name in LAYOUT_NAMES:
            layout = layouts[layout_name]
            if not isinstance(layout, dict):
                raise ValueError(f"layout {layout_name} must be an object")
            canonical_skill = normalize_layout_path(
                layout.get("canonical_skill"),
                f"canonical skill for {layout_name}",
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
                source = normalize_layout_path(mapping["source"], "source")
                destination = normalize_layout_path(
                    mapping["destination"], "destination"
                )
                if source in seen_sources:
                    raise ValueError(f"duplicate layout source: {source}")
                if destination in seen_destinations:
                    raise ValueError(f"duplicate layout destination: {destination}")
                seen_sources.add(source)
                seen_destinations.add(destination)
                source_path = PurePosixPath(source)
                destination_path = PurePosixPath(destination)
                if is_maintainer_only_archive_entry(source) or is_maintainer_only_archive_entry(
                    destination
                ):
                    raise ValueError(
                        f"maintainer-only layout mapping: {source} -> {destination}"
                    )
                if (
                    any(part in LAYOUT_EXCLUDED_PARTS for part in source_path.parts)
                    or any(
                        part in LAYOUT_EXCLUDED_PARTS
                        for part in destination_path.parts
                    )
                    or source_path.suffix in LAYOUT_EXCLUDED_SUFFIXES
                    or destination_path.suffix in LAYOUT_EXCLUDED_SUFFIXES
                ):
                    raise ValueError(
                        f"excluded layout mapping: {source} -> {destination}"
                    )
                normalized_mappings.append(
                    {"source": source, "destination": destination}
                )
            if canonical_skill not in seen_destinations:
                raise ValueError(
                    f"layout {layout_name} canonical skill is not a required destination: "
                    f"{canonical_skill}"
                )
            normalized_layouts[layout_name] = {
                "canonical_skill": canonical_skill,
                "required_mappings": normalized_mappings,
            }
    except ValueError as exc:
        fail(errors, f"invalid package layout manifest: {exc}")
        return None
    return normalized_layouts


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


def validate_retired_maintainer_source_paths(errors: list[str]) -> None:
    active_inventories = (
        MAINTAINER_SOURCE_REQUIRED,
        EVALUATOR_CONTEXT_FREE_DOCS,
    )
    active_paths = set().union(*map(set, active_inventories))
    reactivated_paths = RETIRED_MAINTAINER_SOURCE_PATHS.intersection(active_paths)
    for relative in sorted(reactivated_paths):
        fail(
            errors,
            "retired maintainer-source path reintroduced into active inventory: "
            f"{relative}",
        )


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


def git_object_hash(kind: str, payload: bytes) -> str:
    header = f"{kind} {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def git_tree_hash(files: dict[str, tuple[bytes, int]]) -> str:
    root: dict[str, object] = {}
    for relative, value in files.items():
        node = root
        parts = PurePosixPath(relative).parts
        for part in parts[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                raise ValueError(f"fixture path collision at {relative}")
            node = child
        if parts[-1] in node:
            raise ValueError(f"duplicate fixture path {relative}")
        node[parts[-1]] = value

    def hash_node(node: dict[str, object]) -> str:
        entries: list[tuple[bytes, bytes]] = []
        for name, child in node.items():
            if isinstance(child, dict):
                mode = b"40000"
                object_hash = hash_node(child)
                sort_name = f"{name}/".encode("utf-8")
            else:
                contents, file_mode = child
                mode = b"100755" if file_mode & stat.S_IXUSR else b"100644"
                object_hash = git_object_hash("blob", contents)
                sort_name = name.encode("utf-8")
            entry = mode + b" " + name.encode("utf-8") + b"\0" + bytes.fromhex(object_hash)
            entries.append((sort_name, entry))
        payload = b"".join(entry for _sort_name, entry in sorted(entries))
        return git_object_hash("tree", payload)

    return hash_node(root)


def git_commit_hash(
    *,
    tree_hash: str,
    parent_hash: str | None,
    author_name: str,
    author_email: str,
    timestamp: str,
    message: str,
) -> str:
    moment = datetime.fromisoformat(timestamp)
    if moment.tzinfo is None:
        raise ValueError("fixture timestamp lacks timezone")
    identity = (
        f"{author_name} <{author_email}> {int(moment.timestamp())} "
        f"{moment.strftime('%z')}"
    )
    lines = [f"tree {tree_hash}"]
    if parent_hash is not None:
        lines.append(f"parent {parent_hash}")
    lines.extend((f"author {identity}", f"committer {identity}", "", message))
    return git_object_hash("commit", ("\n".join(lines) + "\n").encode("utf-8"))


def fixture_files(
    root: Path,
    expected: frozenset[str],
    errors: list[str],
    label: str,
) -> dict[str, tuple[bytes, int]] | None:
    if not root.is_dir():
        fail(errors, f"missed-contracts {label} fixture root is missing")
        return None
    actual_paths = {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if set(actual_paths) != expected:
        fail(errors, f"missed-contracts {label} fixture file set has drifted")
        return None
    result: dict[str, tuple[bytes, int]] = {}
    for relative, path in actual_paths.items():
        if path.is_symlink() or not path.is_file():
            fail(errors, f"missed-contracts {label} fixture contains a non-regular file")
            return None
        result[relative] = (path.read_bytes(), path.stat().st_mode)
    return result


def validate_closed_policy_object(
    value: object,
    expected: dict[str, object],
    errors: list[str],
    dimension: str,
) -> dict[str, object] | None:
    if not isinstance(value, dict):
        fail(errors, f"missed-contracts {dimension} policy must be an object")
        return None
    actual_keys = set(value)
    expected_keys = set(expected)
    for key in sorted(expected_keys - actual_keys):
        fail(errors, f"missed-contracts {dimension} policy missing key: {key}")
    for key in sorted(actual_keys - expected_keys):
        fail(errors, f"missed-contracts {dimension} policy has unexpected key: {key}")
    for key in sorted(actual_keys & expected_keys):
        actual_value = value[key]
        expected_value = expected[key]
        if type(actual_value) is not type(expected_value):
            fail(
                errors,
                f"missed-contracts {dimension} policy {key} has wrong type",
            )
        elif actual_value != expected_value:
            fail(
                errors,
                f"missed-contracts {dimension} policy {key} has wrong value",
            )
    return value


def validate_maintainer_evaluator_cases(root: Path, errors: list[str]) -> None:
    discogs_path = root / "evaluations/material-code-review/cases/discogs-custom-playlists.json"
    missed_path = root / "evaluations/material-code-review/cases/missed-contracts.json"
    discogs = load_json(discogs_path, errors) if discogs_path.is_file() else None
    missed = load_json(missed_path, errors) if missed_path.is_file() else None
    if isinstance(discogs, dict) and discogs.get("target_type") != "git_repository":
        fail(errors, "Discogs evaluator case must select target_type git_repository")
    if missed is not None and not isinstance(missed, dict):
        fail(errors, "missed-contracts evaluator case must contain an object")
        return
    if not isinstance(missed, dict):
        return
    actual_top_level_keys = set(missed)
    for key in sorted(MISSED_CONTRACT_TOP_LEVEL_KEYS - actual_top_level_keys):
        fail(errors, f"missed-contracts top-level policy missing key: {key}")
    for key in sorted(actual_top_level_keys - MISSED_CONTRACT_TOP_LEVEL_KEYS):
        fail(errors, f"missed-contracts top-level policy has unexpected key: {key}")
    for key, expected in MISSED_CONTRACT_TOP_LEVEL_POLICY.items():
        if key not in missed:
            continue
        actual = missed[key]
        if type(actual) is not type(expected):
            fail(errors, f"missed-contracts top-level policy {key} has wrong type")
        elif actual != expected:
            fail(errors, f"missed-contracts top-level policy {key} has wrong value")

    required_root_ids = missed.get("required_root_ids")
    if not isinstance(required_root_ids, list):
        fail(errors, "missed-contracts root-oracle required_root_ids must be a list")
    elif any(not isinstance(root_id, str) for root_id in required_root_ids):
        fail(
            errors,
            "missed-contracts root-oracle required_root_ids entries must be strings",
        )
    elif (
        len(required_root_ids) != len(MISSED_CONTRACT_ROOT_IDS)
        or len(set(required_root_ids)) != len(required_root_ids)
    ):
        fail(
            errors,
            "missed-contracts root-oracle required_root_ids must contain exactly five unique IDs",
        )
    elif set(required_root_ids) != MISSED_CONTRACT_ROOT_IDS:
        fail(errors, "missed-contracts root-oracle required_root_ids values have drifted")

    validate_closed_policy_object(
        missed.get("root_contracts"),
        MISSED_CONTRACT_ROOT_CONTRACTS,
        errors,
        "root-oracle root_contracts",
    )
    validate_closed_policy_object(
        missed.get("acceptance"),
        MISSED_CONTRACT_ACCEPTANCE_POLICY,
        errors,
        "acceptance",
    )
    validate_closed_policy_object(
        missed.get("attempt_policy"),
        MISSED_CONTRACT_ATTEMPT_POLICY,
        errors,
        "attempt",
    )

    fixture = missed.get("fixture")
    if not isinstance(fixture, dict):
        fail(errors, "missed-contracts fixture contract is missing")
        return
    fixture_keys = set(fixture)
    for key in sorted(MISSED_CONTRACT_FIXTURE_KEYS - fixture_keys):
        fail(errors, f"missed-contracts fixture policy missing key: {key}")
    for key in sorted(fixture_keys - MISSED_CONTRACT_FIXTURE_KEYS):
        fail(errors, f"missed-contracts fixture policy has unexpected key: {key}")
    for key, expected in MISSED_CONTRACT_FIXTURE_POLICY.items():
        if key not in fixture:
            continue
        actual = fixture[key]
        if type(actual) is not type(expected):
            fail(errors, f"missed-contracts fixture policy {key} has wrong type")
        elif actual != expected:
            fail(errors, f"missed-contracts fixture policy {key} has wrong value")
    for key in ("base_tree", "review_tree", "base_commit", "review_commit"):
        if key in fixture and (
            not isinstance(fixture[key], str)
            or re.fullmatch(r"[0-9a-f]{40}", fixture[key]) is None
        ):
            fail(errors, f"missed-contracts fixture policy {key} has invalid identity")
    base_relative = fixture.get("base_root")
    review_relative = fixture.get("review_root")
    if not isinstance(base_relative, str) or not isinstance(review_relative, str):
        fail(errors, "missed-contracts fixture roots are invalid")
        return
    if base_relative != "evaluations/material-code-review/fixtures/missed-contracts/base" or review_relative != "evaluations/material-code-review/fixtures/missed-contracts/review":
        fail(errors, "missed-contracts fixture roots are outside the fixed allowlist")
        return
    base_files = fixture_files(root / base_relative, MISSED_CONTRACT_BASE_FILES, errors, "base")
    overlay_files = fixture_files(
        root / review_relative,
        MISSED_CONTRACT_REVIEW_FILES,
        errors,
        "review",
    )
    if base_files is None or overlay_files is None:
        return
    review_files = {**base_files, **overlay_files}
    try:
        base_tree = git_tree_hash(base_files)
        review_tree = git_tree_hash(review_files)
        identity_keys = (
            "author_name",
            "author_email",
            "base_timestamp",
            "review_timestamp",
            "base_message",
            "review_message",
        )
        if any(not isinstance(fixture.get(key), str) for key in identity_keys):
            raise ValueError("fixture identity is incomplete")
        base_commit = git_commit_hash(
            tree_hash=base_tree,
            parent_hash=None,
            author_name=fixture["author_name"],
            author_email=fixture["author_email"],
            timestamp=fixture["base_timestamp"],
            message=fixture["base_message"],
        )
        review_commit = git_commit_hash(
            tree_hash=review_tree,
            parent_hash=base_commit,
            author_name=fixture["author_name"],
            author_email=fixture["author_email"],
            timestamp=fixture["review_timestamp"],
            message=fixture["review_message"],
        )
    except (TypeError, ValueError) as exc:
        fail(errors, f"missed-contracts fixture identity is invalid: {exc}")
        return
    expected_hashes = {
        "base_tree": base_tree,
        "review_tree": review_tree,
        "base_commit": base_commit,
        "review_commit": review_commit,
    }
    for key, expected in expected_hashes.items():
        if fixture.get(key) != expected:
            fail(errors, f"missed-contracts fixture {key} has drifted")


def validate_missed_contracts_worker_guidance(root: Path, errors: list[str]) -> None:
    denied_values = (
        *sorted(MISSED_CONTRACT_ROOT_IDS),
        *MISSED_CONTRACT_ROOT_CONTRACTS.values(),
        *MISSED_CONTRACT_RETIRED_GUIDANCE,
    )
    for relative in MISSED_CONTRACT_WORKER_GUIDANCE_PATHS:
        path = root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").casefold()
        for denied in denied_values:
            if denied.casefold() in text:
                fail(
                    errors,
                    f"missed-contracts worker guidance is contaminated: {relative}",
                )
                break


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

    object_format_contract = parse_evaluator_contract(
        text,
        EVALUATOR_FIXTURE_OBJECT_FORMAT_CONTRACT_START,
        EVALUATOR_FIXTURE_OBJECT_FORMAT_CONTRACT_END,
        errors,
        "fixture object-format contract",
    )
    if object_format_contract is None:
        return
    if object_format_contract.get("initialization") != "git init --object-format=sha1":
        fail(
            errors,
            "maintainer evaluator must initialize fixture repositories as SHA-1",
        )
    if object_format_contract.get("attestation") != "git rev-parse --show-object-format":
        fail(errors, "maintainer evaluator must attest the fixture object format")
    if (
        object_format_contract.get("required_format") != "sha1"
        or object_format_contract.get("attestation_timing")
        != "before-add-commit-or-dispatch"
    ):
        fail(
            errors,
            "maintainer evaluator must attest SHA-1 before fixture mutation or dispatch",
        )
    if (
        object_format_contract.get("case") != "missed-contracts"
        or object_format_contract.get("failure") != "hard-stop-no-fallback"
    ):
        fail(errors, "maintainer evaluator fixture object-format failure must fail closed")


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

    contamination_contract = parse_evaluator_contract(
        skill_text,
        EVALUATOR_CONTAMINATION_CONTRACT_START,
        EVALUATOR_CONTAMINATION_CONTRACT_END,
        errors,
        "worker contamination contract",
    )
    expected_contamination_contract = {
        "case": "missed-contracts",
        "check_timing": "before-any-worker-dispatch",
        "worker_visible_guidance": ",".join(MISSED_CONTRACT_WORKER_GUIDANCE_PATHS),
        "deny": "root-ids,root-contract-definitions,retired-one-to-one-guidance",
        "frozen_source_evidence_scan": "false",
        "private_oracle_timing": "after-durable-judgment-and-identity-reveal",
        "contamination_dispatch": "false",
    }
    if contamination_contract != expected_contamination_contract:
        fail(errors, "maintainer evaluator worker contamination contract is incomplete")
    validate_missed_contracts_worker_guidance(root, errors)

    required_values = (
        ("reviewer_history", "none", "maintainer evaluator dispatch contract must require empty history for reviewers"),
        ("challenger_history", "none", "maintainer evaluator dispatch contract must require empty history for challengers"),
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
        "challengers": "case:missed-contracts-only",
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
        ("evaluations/material-code-review/prompts/challenger.md", "challenger"),
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


def validate_maintainer_evaluator_challenger(root: Path, errors: list[str]) -> None:
    skill_path = root / ".agents/skills/material-review-evaluation/SKILL.md"
    if not skill_path.is_file():
        return
    contract = parse_evaluator_contract(
        skill_path.read_text(encoding="utf-8"),
        EVALUATOR_CHALLENGER_CONTRACT_START,
        EVALUATOR_CHALLENGER_CONTRACT_END,
        errors,
        "challenger boundary contract",
    )
    if contract != EVALUATOR_CHALLENGER_CONTRACT:
        fail(errors, "maintainer evaluator challenger boundary contract is incomplete")

    controlled_markers = {
        "evaluations/material-code-review/prompts/challenger.md": (
            "Candidate findings and check results are forbidden as inputs.",
            "`NO_COVERAGE_GAP` means only that the supplied declarative coverage is coherent",
            "The evaluator root and native controller validate those later result properties independently.",
        ),
        "evaluations/material-code-review/prompts/reviewer.md": (
            "before candidate ingestion and Gate A",
            "without candidate findings or check results",
            "never replaces later native controller and evaluator-root validation",
        ),
        "evaluations/material-code-review/prompts/judge.md": (
            "required only for the bounded declarative coverage claim",
            "remains an independent prerequisite",
        ),
        "evaluations/material-code-review/rubric.md": (
            "audits only the declarative change-unit, risk, obligation, assignment, and limitation bundle",
            "independently of the challenger",
        ),
        "EVALUATION.md": (
            "before candidate ingestion or Gate A",
            "remains mandatory and independent",
        ),
        "evaluations/material-code-review/README.md": (
            "before candidate ingestion",
            "remains mandatory and independent",
        ),
    }
    for relative, markers in controlled_markers.items():
        path = root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in text:
                fail(
                    errors,
                    f"{relative} lacks the declarative challenger boundary marker",
                )
                break

    challenger_path = root / "evaluations/material-code-review/prompts/challenger.md"
    if challenger_path.is_file():
        challenger_text = challenger_path.read_text(encoding="utf-8")
        if "stale, incomplete, blocked, or unsafe check evidence" in challenger_text:
            fail(
                errors,
                "challenger prompt must not claim authority over unseen check-result evidence",
            )


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
    validate_retired_maintainer_source_paths(errors)
    if sys.version_info < (3, 10):
        return ["package validation requires Python 3.10+"]
    if not root.is_dir():
        return [f"package root is not a directory: {root}"]

    actual = {path.relative_to(root).as_posix() for path in iter_files(root)}
    layouts = load_layout_manifest(root, errors)
    required: set[str] = set()
    if layouts is not None:
        mapping_key = "destination" if distribution_layout else "source"
        required.update(
            mapping[mapping_key]
            for mapping in layouts["full-plugin"]["required_mappings"]
        )
    if not distribution_layout:
        required.update(MAINTAINER_SOURCE_REQUIRED)
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

    evaluator_skill = root / ".agents/skills/material-review-evaluation/SKILL.md"
    if not distribution_layout and evaluator_skill.is_file():
        frontmatter = parse_frontmatter(evaluator_skill, errors)
        if frontmatter.get("name") != "material-review-evaluation":
            fail(errors, "maintainer evaluator skill has wrong name")
        if not frontmatter.get("description", "").startswith("Use when "):
            fail(errors, "maintainer evaluator skill description must start with 'Use when '")
        if (
            frontmatter.get("argument-hint")
            != "[case:<case-id>] base:<skill-ref> candidate:<skill-ref>"
        ):
            fail(errors, "maintainer evaluator skill has wrong argument hint")
        validate_maintainer_evaluator_cases(root, errors)
        validate_maintainer_evaluator_assets(root, errors)
        validate_maintainer_evaluator_dispatch(root, errors)
        validate_maintainer_evaluator_challenger(root, errors)
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
        for marker in CONTROLLED_WORKFLOW_MARKERS:
            if marker not in text:
                fail(errors, f"canonical skill controlled workflow marker missing: {marker}")

    workflow = root / "skills/material-code-review/references/workflow.md"
    if workflow.is_file():
        workflow_error = validate_workflow_discovery_order(
            workflow.read_bytes(),
            workflow.relative_to(root).as_posix(),
        )
        if workflow_error is not None:
            fail(errors, workflow_error)

    for path in sorted((root / "skills/material-code-review/schemas").glob("*.json")):
        data = load_json(path, errors)
        if isinstance(data, dict):
            if data.get("type") != "object":
                fail(errors, f"{path.relative_to(root)} schema root must be object")
            if data.get("additionalProperties") is not False:
                fail(errors, f"{path.relative_to(root)} must set additionalProperties=false")
            for reference_error in local_schema_reference_errors(
                data,
                path.relative_to(root).as_posix(),
            ):
                fail(errors, reference_error)

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
    obligation_contract = root / "skills/material-code-review/scripts/obligation_contract.py"
    if not obligation_contract.is_file():
        fail(errors, "missing shared obligation contract")
    if controller.is_file():
        if "from obligation_contract import" not in controller.read_text(encoding="utf-8"):
            fail(errors, "reviewctl.py does not import obligation_contract")
        declaration_error = validate_static_version_declaration(
            controller.read_bytes(),
            "TOOL_VERSION",
            VERSION,
            controller.relative_to(root).as_posix(),
        )
        if declaration_error is not None:
            fail(errors, declaration_error)
        if os.name != "nt" and not (controller.stat().st_mode & stat.S_IXUSR):
            fail(errors, "reviewctl.py is not executable")

    packager = root / "scripts/package_plugin.py"
    if packager.is_file():
        declaration_error = validate_static_version_declaration(
            packager.read_bytes(),
            "VERSION",
            VERSION,
            packager.relative_to(root).as_posix(),
        )
        if declaration_error is not None:
            fail(errors, declaration_error)

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


def check_zip(
    path: Path,
    *,
    standalone: bool,
    manifest_root: Path,
) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        return [f"archive not found: {path}"]
    layouts = load_layout_manifest(manifest_root, errors)
    layout = None if layouts is None else layouts[
        "standalone" if standalone else "full-plugin"
    ]
    try:
        with zipfile.ZipFile(path) as zf:
            members = zf.infolist()
            resource_error = preflight_archive_resources(path.name, members)
            if resource_error is not None:
                fail(errors, resource_error)
                return errors
            archive_entries = []
            archive_paths_safe = True
            for member in members:
                raw_name = member.filename
                canonical_name = PurePosixPath(raw_name.replace("\\", "/")).as_posix()
                archive_entries.append((member, raw_name, canonical_name))
                if raw_name != canonical_name:
                    archive_paths_safe = False
                    fail(errors, f"{path.name}: noncanonical archive path {raw_name}")

            canonical_names = [canonical for _, _, canonical in archive_entries]
            if len(canonical_names) != len(set(canonical_names)):
                archive_paths_safe = False
                fail(errors, f"{path.name}: duplicate archive entries")
            portable_names: dict[str, str] = {}
            for member, raw_name, canonical_name in archive_entries:
                rel = PurePosixPath(canonical_name)
                if not is_safe_relative_package_path(raw_name):
                    archive_paths_safe = False
                    fail(errors, f"{path.name}: unsafe archive path {raw_name}")
                metadata_error = regular_zip_member_metadata_error(
                    member.create_system,
                    member.external_attr,
                )
                if metadata_error is not None:
                    archive_paths_safe = False
                    fail(
                        errors,
                        f"{path.name}: archive member {raw_name}: {metadata_error}",
                    )
                portable_key = portable_archive_member_key(canonical_name)
                prior_name = portable_names.get(portable_key)
                if prior_name is not None and prior_name != canonical_name:
                    archive_paths_safe = False
                    fail(
                        errors,
                        f"{path.name}: portable archive member collision: "
                        f"{prior_name} and {canonical_name}",
                    )
                else:
                    portable_names[portable_key] = canonical_name
                if any(part in FORBIDDEN_PARTS for part in rel.parts) or rel.suffix in FORBIDDEN_SUFFIXES:
                    archive_paths_safe = False
                    fail(errors, f"{path.name}: forbidden archive entry {raw_name}")
                if is_maintainer_only_archive_entry(canonical_name):
                    archive_paths_safe = False
                    fail(
                        errors,
                        f"{path.name}: forbidden maintainer-only archive entry {raw_name}",
                    )
            names = {
                canonical_name
                for _, raw_name, canonical_name in archive_entries
                if raw_name == canonical_name
            }
            required = (
                set()
                if layout is None
                else {
                    mapping["destination"]
                    for mapping in layout["required_mappings"]
                }
            )
            for rel in sorted(required - names):
                fail(errors, f"{path.name}: missing archive entry {rel}")
            archive_manifest_trusted = False
            if layout is not None and archive_paths_safe:
                manifest_destination = next(
                    (
                        mapping["destination"]
                        for mapping in layout["required_mappings"]
                        if mapping["source"] == LAYOUT_MANIFEST_SOURCE.as_posix()
                    ),
                    None,
                )
                if manifest_destination is not None and manifest_destination in names:
                    archived_manifest = read_bounded_archive_member(
                        zf,
                        manifest_destination,
                        path.name,
                    )
                    try:
                        json.loads(archived_manifest)
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        fail(
                            errors,
                            f"{path.name}: archived package layout manifest has invalid JSON",
                        )
                    else:
                        trusted_manifest = (
                            manifest_root / LAYOUT_MANIFEST_SOURCE
                        ).read_bytes()
                        if archived_manifest != trusted_manifest:
                            fail(
                                errors,
                                f"{path.name}: archived package layout manifest differs "
                                "from trusted source contract",
                            )
                        else:
                            archive_manifest_trusted = True
            if layout is not None and archive_manifest_trusted:
                canonical_skill = layout["canonical_skill"]
                if canonical_skill in names:
                    try:
                        archived_skill = read_bounded_archive_member(
                            zf,
                            canonical_skill,
                            path.name,
                        ).decode("utf-8")
                    except UnicodeDecodeError:
                        fail(
                            errors,
                            f"{path.name}:{canonical_skill}: archived SKILL has invalid UTF-8",
                        )
                    else:
                        skill_parent = PurePosixPath(canonical_skill).parent
                        references = set(
                            re.findall(
                                r"`((?:references|schemas)/[A-Za-z0-9._/-]+)`",
                                archived_skill,
                            )
                        )
                        for reference in sorted(references):
                            archive_reference = (
                                PurePosixPath(reference)
                                if skill_parent == PurePosixPath(".")
                                else skill_parent / PurePosixPath(reference)
                            ).as_posix()
                            if archive_reference not in names:
                                fail(
                                    errors,
                                    f"{path.name}: archived SKILL references missing entry "
                                    f"{archive_reference}",
                                )
            workflow_entry = (
                "references/workflow.md"
                if standalone
                else "skills/material-code-review/references/workflow.md"
            )
            if archive_manifest_trusted and workflow_entry in names:
                workflow_error = validate_workflow_discovery_order(
                    read_bounded_archive_member(zf, workflow_entry, path.name),
                    f"{path.name}:{workflow_entry}",
                )
                if workflow_error is not None:
                    fail(errors, workflow_error)
            if layout is not None and archive_paths_safe:
                schema_destinations = sorted(
                    mapping["destination"]
                    for mapping in layout["required_mappings"]
                    if mapping["source"].startswith(
                        "skills/material-code-review/schemas/"
                    )
                    and mapping["source"].endswith(".json")
                )
                for schema_destination in schema_destinations:
                    if schema_destination not in names:
                        continue
                    try:
                        schema_document = json.loads(
                            read_bounded_archive_member(
                                zf,
                                schema_destination,
                                path.name,
                            )
                        )
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        fail(
                            errors,
                            f"{path.name}:{schema_destination}: invalid schema JSON",
                        )
                        continue
                    for reference_error in local_schema_reference_errors(
                        schema_document,
                        f"{path.name}:{schema_destination}",
                    ):
                        fail(errors, reference_error)
            bad_prefixes = {name.split("/", 1)[0] for name in names if name.startswith("material-code-review-plugin/")}
            if bad_prefixes:
                fail(errors, f"{path.name}: archive has an unwanted wrapper directory")
            if (
                not standalone
                and archive_paths_safe
                and ".codex-plugin/plugin.json" in names
            ):
                manifest = json.loads(
                    read_bounded_archive_member(
                        zf,
                        ".codex-plugin/plugin.json",
                        path.name,
                    )
                )
                if manifest.get("version") != VERSION or manifest.get("name") != "material-code-review":
                    fail(errors, f"{path.name}: embedded Codex manifest identity/version mismatch")
    except ArchiveResourceError as exc:
        fail(errors, str(exc))
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
    package_root = Path(args.package_root).resolve()
    errors = check_source_package(
        package_root,
        distribution_layout=args.distribution_layout,
    )
    for raw in args.full_archive:
        errors.extend(
            check_zip(
                Path(raw).resolve(),
                standalone=False,
                manifest_root=package_root,
            )
        )
    for raw in args.standalone_archive:
        errors.extend(
            check_zip(
                Path(raw).resolve(),
                standalone=True,
                manifest_root=package_root,
            )
        )
    if errors:
        print("[FAIL] material-code-review package validation", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"[OK] material-code-review package {VERSION} is structurally valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
