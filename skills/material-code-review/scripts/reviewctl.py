#!/usr/bin/env python3
"""State and evidence controller for the material-code-review skill.

The tool intentionally uses only the Python standard library. It enforces
scope freshness, schema-critical fields, user-gate receipts, exact repair
boundaries, test logging, local checkpoints, and bounded post-fix repair.
It does not attempt to replace human or model judgment about code semantics.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import difflib
import hashlib
import json
import os
import re
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence


TOOL_VERSION = "1.2.0"
STATE_SCHEMA = "material-review/state/v1"
SCOPE_SCHEMA = "material-review/scope/v1"
CANDIDATE_SCHEMA = "material-review/candidate-set/v1"
COVERAGE_PLAN_SCHEMA = "material-review/coverage-plan/v1"
CANDIDATE_PREFLIGHT_SCHEMA = "material-review/candidate-preflight/v1"
FALLBACK_ASSIGNMENT_SCHEMA = "material-review/fallback-assignment/v1"
REVIEWER_FAILURE_ATTESTATION_SCHEMA = "material-review/reviewer-failure-attestation/v1"
COVERAGE_STATUS_SCHEMA = "material-review/coverage-status/v1"
NORMALIZED_CANDIDATES_SCHEMA = "material-review/candidates-normalized/v1"
ADJUDICATION_SCHEMA = "material-review/adjudication/v3"
LEDGER_SCHEMA = "material-review/ledger/v3"
FINDINGS_GATE_SCHEMA = "material-review/findings-gate/v1"
FIX_PLAN_SCHEMA = "material-review/fix-plan/v2"
PLAN_GATE_SCHEMA = "material-review/plan-gate/v1"
FIX_SUMMARY_SCHEMA = "material-review/fix-summary/v1"
VERIFICATION_SCHEMA = "material-review/verification/v1"

PHASE_CONTEXT = "CONTEXT_FROZEN"
PHASE_REVIEW_INCOMPLETE = "REVIEW_INCOMPLETE"
PHASE_CANDIDATES = "CANDIDATES_CAPTURED"
PHASE_ADJUDICATED = "ADJUDICATED"
PHASE_FINDINGS_APPROVED = "FINDINGS_APPROVED"
PHASE_PLAN_VALIDATED = "PLAN_VALIDATED"
PHASE_PLAN_APPROVED = "PLAN_APPROVED"
PHASE_FIXING = "FIXING"
PHASE_VERIFYING = "VERIFYING"
PHASE_REPAIR_REQUIRED = "REPAIR_REQUIRED"
PHASE_PLAN_AMENDMENT = "PLAN_AMENDMENT_REQUIRED"
PHASE_COMPLETE = "COMPLETE"
PHASE_ABORTED = "ABORTED"
PHASE_BLOCKED = "BLOCKED"

MUTATION_PHASES = {
    PHASE_FIXING,
    PHASE_VERIFYING,
    PHASE_REPAIR_REQUIRED,
    PHASE_PLAN_AMENDMENT,
    PHASE_BLOCKED,
}

NATURES = {"defect", "coverage_gap", "documentation_gap", "improvement", "risk"}
CATEGORIES = {
    "correctness",
    "security",
    "privacy",
    "reliability",
    "tests",
    "docs",
    "performance",
    "api_contract",
    "migration",
    "concurrency",
    "simplification",
    "dry",
    "architecture",
    "standards",
}
SEVERITIES = {"blocker", "high", "medium", "low"}
CONFIDENCES = {"certain", "high", "medium", "low"}
EVIDENCE_SIDES = {"comparison", "baseline", "diff"}
SCOPE_RELATIONS = {"primary", "secondary", "pre_existing"}
FIX_RISKS = {"low", "medium", "high", "unknown"}
REVIEW_MODES = {"subagent", "controller", "external"}
COVERAGE_FALLBACKS = {"sequential_degraded_self_audit", "none"}
EVIDENCE_HANDLING_VALUES = {"standard", "unparseable_origin_degraded"}
PREFLIGHT_ROUTES = {"primary", "fallback"}
FALLBACK_TRIGGER_KINDS = {
    "candidate_preflight_receipt",
    "reviewer_failure_attestation",
}
REVIEWER_FAILURE_REASONS = {
    "dispatch_failed",
    "timeout",
    "capacity_unavailable",
    "execution_failed",
    "external_route_failed",
}
FAILURE_OBSERVER_KINDS = {"controller", "scheduler"}
FAILURE_DIAGNOSTIC_CODES = {
    "attempt_number",
    "elapsed_seconds",
    "status_code",
    "exit_code",
    "signal_number",
}
FAILURE_DIAGNOSTIC_BOUNDS = {
    "attempt_number": (1, 2),
    "elapsed_seconds": (0, 86_400),
    "status_code": (100, 599),
    "exit_code": (-255, 255),
    "signal_number": (1, 255),
}
MAX_FAILURE_DIAGNOSTICS = 8
WORKFLOW_PROFILE_REVIEW = "material_review"
WORKFLOW_PROFILE_SIMPLIFICATION = "material_simplification"
WORKFLOW_PROFILES = {WORKFLOW_PROFILE_REVIEW, WORKFLOW_PROFILE_SIMPLIFICATION}
CORE_LENSES = {"correctness", "test_adequacy", "standards_alignment"}
SIMPLIFICATION_CORE_LENSES = {"architecture_structural", "code_test"}
PROTOCOL_RISK_SIGNALS = {
    "multi_stage_lifecycle",
    "cross_boundary_data",
    "prompt_contract",
    "conditional_validation",
    "state_dependent_schema",
    "trust_ordering",
    "shared_schema",
}
EVIDENCE_ANCHOR_FIELDS = {
    "file",
    "line_start",
    "line_end",
    "evidence_side",
    "evidence_quote",
}
CANDIDATE_FINDING_FIELDS = (
    "local_id",
    "title",
    "nature",
    "category",
    "severity",
    "confidence",
    "file",
    "line_start",
    "line_end",
    "evidence_side",
    "evidence_quote",
    "scope_relation",
    "related_changed_files",
    "direct_dependency",
    "observable_consequence",
    "trigger_conditions",
    "counterevidence_checked",
    "why_not_preference",
    "proposed_resolution",
    "estimated_fix_risk",
    "requires_user_decision",
    "assumptions",
)
CANDIDATE_MECHANICAL_FIELDS = EVIDENCE_ANCHOR_FIELDS | {"local_id"}
CANDIDATE_SUBSTANTIVE_FIELDS = tuple(
    field
    for field in CANDIDATE_FINDING_FIELDS
    if field not in CANDIDATE_MECHANICAL_FIELDS
)
CORRECTABLE_DIAGNOSTIC_CODES = {
    "JSON_SYNTAX",
    "TOP_LEVEL_METADATA",
    "UNKNOWN_FIELD",
    "EVIDENCE_NOT_FOUND",
    "EVIDENCE_OUTSIDE_RANGE",
    "DUPLICATE_LOCAL_ID",
}
VALIDATION_MODES = {"independent", "controller_direct", "degraded_self_audit"}
VALIDATION_VERDICTS = {"confirmed", "rejected", "uncertain"}
CAUSALITIES = {"introduced", "exposed", "pre_existing", "uncertain"}
DISPOSITIONS = {"keep", "discard"}
RECOMMENDATIONS = {"fix_now", "defer", "monitor", "none"}
REPAIR_DIRECTION_STATUSES = {"reviewed", "needs_refinement", "needs_user_decision", "unsafe_to_apply", "insufficient_evidence"}
MERGE_VERDICTS = {
    "READY",
    "READY WITH OPTIONAL FOLLOW-UPS",
    "SHOULD FIX BEFORE MERGE",
    "NOT READY",
}
DISCARD_REASONS = {
    "DUPLICATE",
    "NOT_IN_SCOPE",
    "PRE_EXISTING_UNRELATED",
    "HANDLED_ELSEWHERE",
    "EVIDENCE_MISMATCH",
    "CONSEQUENCE_UNSUPPORTED",
    "VALIDATOR_REJECTED",
    "UNCERTAIN_BELOW_HIGH_IMPACT",
    "STYLE_OR_LINTER",
    "SPECULATIVE_FUTURE",
    "HARMLESS_DUPLICATION",
    "ABSTRACTION_COST_EXCEEDS_VALUE",
    "SIMPLIFICATION_NOT_MATERIAL",
    "TEST_GAP_NOT_FRAGILE",
    "DOC_MISMATCH_NOT_OPERATIONAL",
    "SETTLED_PREFERENCE",
    "OUTSIDE_REVIEWER_CONTRACT",
}

SEVERITY_ORDER = {"blocker": 0, "high": 1, "medium": 2, "low": 3}
CONFIDENCE_ORDER = {"certain": 0, "high": 1, "medium": 2, "low": 3}

TRANSIENT_RUNTIME_DIR_MARKERS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hypothesis",
    ".tox",
    ".nox",
    ".nyc_output",
}
TRANSIENT_RUNTIME_FILE_NAMES = {".ds_store", "thumbs.db", ".coverage"}
TRANSIENT_RUNTIME_SUFFIXES = (".pyc", ".pyo", ".pyd")


def is_transient_runtime_path(path: str) -> bool:
    normalized = path.replace("\\", "/").strip().lstrip("/")
    parts = [part for part in normalized.split("/") if part]
    if any(part in TRANSIENT_RUNTIME_DIR_MARKERS for part in parts):
        return True
    name = parts[-1].lower() if parts else ""
    return name in TRANSIENT_RUNTIME_FILE_NAMES or name.endswith(TRANSIENT_RUNTIME_SUFFIXES)


class ReviewError(RuntimeError):
    """Expected control failure with an actionable message."""


def provisional_v1_restart(context: str) -> ReviewError:
    return ReviewError(
        f"Provisional branch-local v1 {context} is incompatible with the final v1 contract; "
        "restart this run"
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except FileNotFoundError as exc:
        raise ReviewError(f"Expected artifact file is missing: {path}") from exc
    except OSError as exc:
        raise ReviewError(f"Could not read artifact file {path}: {exc}") from exc
    return digest.hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


@contextlib.contextmanager
def exclusive_run_state_lock(run_dir: Path) -> Iterator[None]:
    lock_path = run_dir / ".state.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReviewError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReviewError(f"Invalid JSON in {path}: {exc}") from exc


def verify_embedded_hash(
    obj: dict[str, Any],
    *,
    hash_field: str,
    context: str,
    unhashed_fields: Iterable[str] = (),
) -> str:
    """Recompute a persisted artifact hash after removing metadata added later."""
    expected = require_string(obj.get(hash_field), f"{context}.{hash_field}")
    payload = copy.deepcopy(obj)
    payload.pop(hash_field, None)
    for field in unhashed_fields:
        payload.pop(field, None)
    actual = canonical_hash(payload)
    if actual != expected:
        raise ReviewError(
            f"{context} failed its embedded hash check: expected {expected}, recomputed {actual}"
        )
    return expected


def require_state_hash(state: dict[str, Any], key: str, actual: str, context: str) -> None:
    expected = state.get("hashes", {}).get(key)
    if expected != actual:
        raise ReviewError(
            f"{context} does not match state.{key}: state has {expected!r}, artifact has {actual!r}"
        )


def require_state_gate(state: dict[str, Any], key: str, actual: str, context: str) -> None:
    expected = state.get("gates", {}).get(key)
    if expected != actual:
        raise ReviewError(
            f"{context} does not match the recorded {key} gate: state has {expected!r}, artifact has {actual!r}"
        )


def scope_identity_hash(identity: dict[str, Any]) -> str:
    """Hash only review identity, excluding local snapshot storage pointers."""
    payload = copy.deepcopy(identity)
    for entry in payload.get("files", []):
        if not isinstance(entry, dict):
            continue
        for key in ("baseline_state", "comparison_state"):
            state_info = entry.get(key)
            if isinstance(state_info, dict):
                state_info.pop("snapshot_path", None)
    return canonical_hash(payload)


def run_process(
    args: Sequence[str],
    *,
    cwd: Path,
    check: bool = True,
    timeout: int | None = None,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            list(args),
            cwd=str(cwd),
            input=input_bytes,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ReviewError(f"Executable not found: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ReviewError(f"Command timed out after {timeout}s: {' '.join(args)}") from exc
    if check and result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        stdout = result.stdout.decode("utf-8", errors="replace").strip()
        detail = stderr or stdout or f"exit {result.returncode}"
        raise ReviewError(f"Command failed ({' '.join(args)}): {detail}")
    return result


def git_bytes(repo: Path, *args: str, check: bool = True) -> bytes:
    return run_process(["git", *args], cwd=repo, check=check).stdout


def git_text(repo: Path, *args: str, check: bool = True) -> str:
    return git_bytes(repo, *args, check=check).decode("utf-8", errors="surrogateescape").strip()


def resolve_repo_root(raw: str | Path) -> Path:
    candidate = Path(raw).expanduser().resolve()
    result = run_process(["git", "rev-parse", "--show-toplevel"], cwd=candidate, check=True)
    return Path(result.stdout.decode("utf-8", errors="replace").strip()).resolve()


def default_artifact_root(repo: Path) -> Path:
    raw = git_text(repo, "rev-parse", "--git-path", "material-code-review")
    path = Path(raw)
    if not path.is_absolute():
        path = repo / path
    return path.resolve()


def resolve_artifact_root(repo: Path, raw: str | None) -> Path:
    artifact_root = Path(raw).expanduser().resolve() if raw else default_artifact_root(repo)
    git_dir = Path(git_text(repo, "rev-parse", "--absolute-git-dir")).resolve()
    if artifact_root.is_relative_to(repo) and not artifact_root.is_relative_to(git_dir):
        raise ReviewError(
            "Artifact storage may not be inside the working tree. Use the default Git-path storage or an external path."
        )
    return artifact_root


def normalize_run_id(raw: str) -> str:
    value = require_string(raw, "run ID")
    if value in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
        raise ReviewError(
            "Run ID must be 1-128 characters using letters, digits, dot, underscore, or hyphen, and may not traverse paths"
        )
    return value


def normalize_repo_path(raw: str, *, allow_dot: bool = False) -> str:
    value = raw.replace("\\", "/").strip()
    if allow_dot and value in {"", ".", "./"}:
        return "."
    while value.startswith("./"):
        value = value[2:]
    if not value or value.startswith("/") or re.match(r"^[A-Za-z]:/", value):
        raise ReviewError(f"Path must be repository-relative: {raw!r}")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ReviewError(f"Path contains an unsafe component: {raw!r}")
    if parts[0] == ".git":
        raise ReviewError(f"Path may not target .git: {raw!r}")
    return "/".join(parts)


def repo_path(repo: Path, relative: str) -> Path:
    normalized = normalize_repo_path(relative)
    # Canonicalize the repository root before containment checks. On macOS,
    # temporary paths may be exposed as /var/... while resolving a parent
    # produces /private/var/.... Comparing those aliases directly causes a
    # valid in-repository path to be rejected as an escape.
    canonical_repo = repo.resolve(strict=True)
    target = canonical_repo / normalized
    # Resolve the parent, not the final component. Resolving the final
    # component would follow a repository symlink and make checkpoint logic
    # operate on its target rather than on the symlink itself.
    resolved_parent = target.parent.resolve(strict=False)
    try:
        resolved_parent.relative_to(canonical_repo)
    except ValueError as exc:
        raise ReviewError(f"Path escapes repository through a parent symlink: {relative}") from exc
    return target


def require_object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReviewError(f"{context} must be a JSON object")
    return value


def require_array(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ReviewError(f"{context} must be an array")
    return value


def require_string(value: Any, context: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str):
        raise ReviewError(f"{context} must be a string")
    if nonempty and not value.strip():
        raise ReviewError(f"{context} must not be empty")
    return value


def require_sha256(value: Any, context: str) -> str:
    digest = require_string(value, context)
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ReviewError(f"{context} must be a lowercase SHA-256 digest")
    return digest


def require_bool(value: Any, context: str) -> bool:
    if not isinstance(value, bool):
        raise ReviewError(f"{context} must be a boolean")
    return value


def require_int(value: Any, context: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReviewError(f"{context} must be an integer")
    if minimum is not None and value < minimum:
        raise ReviewError(f"{context} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ReviewError(f"{context} must be <= {maximum}")
    return value


def require_exact_keys(obj: dict[str, Any], expected: set[str], context: str) -> None:
    actual = set(obj)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unexpected {', '.join(extra)}")
        raise ReviewError(f"{context} has invalid fields: {'; '.join(details)}")


def require_string_array(value: Any, context: str, *, unique: bool = True) -> list[str]:
    values = require_array(value, context)
    result = [require_string(item, f"{context}[{index}]") for index, item in enumerate(values)]
    if unique and len(set(result)) != len(result):
        raise ReviewError(f"{context} must contain unique values")
    return result


def require_control_id(value: Any, context: str) -> str:
    identifier = require_string(value, context)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", identifier) is None:
        raise ReviewError(
            f"{context} must be 1-128 characters using letters, digits, dot, underscore, or hyphen"
        )
    return identifier


def validate_coverage_plan(raw: Any, state: dict[str, Any]) -> dict[str, Any]:
    context = "coverage plan"
    obj = require_object(raw, context)
    if state.get("coverage_required", False) and "workflow_profile" not in obj:
        raise provisional_v1_restart("coverage plan")
    require_exact_keys(
        obj,
        {
            "schema_version",
            "scope_hash",
            "workflow_profile",
            "risk_signals",
            "lenses",
            "max_candidate_corrections",
        },
        context,
    )
    if obj["schema_version"] != COVERAGE_PLAN_SCHEMA:
        raise ReviewError("Unsupported coverage-plan schema_version")
    scope_hash = require_sha256(obj["scope_hash"], "coverage plan.scope_hash")
    if scope_hash != state["scope_hash"]:
        raise ReviewError("coverage plan.scope_hash does not match the active frozen scope")
    workflow_profile = require_string(
        obj["workflow_profile"], "coverage plan.workflow_profile"
    )
    if workflow_profile not in WORKFLOW_PROFILES:
        raise ReviewError(
            f"coverage plan.workflow_profile must be one of {sorted(WORKFLOW_PROFILES)}"
        )
    state_profile = require_string(
        state.get("workflow_profile"), "state.workflow_profile"
    )
    if workflow_profile != state_profile:
        raise ReviewError("coverage plan.workflow_profile does not match the root-owned run profile")

    risk_signals: list[dict[str, Any]] = []
    for index, raw_signal in enumerate(require_array(obj["risk_signals"], "coverage plan.risk_signals")):
        signal_context = f"coverage plan.risk_signals[{index}]"
        signal = require_object(raw_signal, signal_context)
        require_exact_keys(signal, {"code", "rationale", "evidence_paths"}, signal_context)
        code = require_string(signal["code"], f"{signal_context}.code")
        if code not in PROTOCOL_RISK_SIGNALS:
            raise ReviewError(
                f"{signal_context}.code must be one of {sorted(PROTOCOL_RISK_SIGNALS)}"
            )
        risk_signals.append(
            {
                "code": code,
                "rationale": require_string(signal["rationale"], f"{signal_context}.rationale"),
                "evidence_paths": [
                    normalize_repo_path(path)
                    for path in require_string_array(
                        signal["evidence_paths"], f"{signal_context}.evidence_paths"
                    )
                ],
            }
        )

    lenses: list[dict[str, Any]] = []
    lens_ids: set[str] = set()
    reviewer_ids: set[str] = set()
    for index, raw_lens in enumerate(require_array(obj["lenses"], "coverage plan.lenses")):
        lens_context = f"coverage plan.lenses[{index}]"
        lens = require_object(raw_lens, lens_context)
        require_exact_keys(
            lens,
            {
                "lens_id",
                "required",
                "reviewer_id",
                "independence_group",
                "review_mode",
                "fallback",
            },
            lens_context,
        )
        lens_id = require_control_id(lens["lens_id"], f"{lens_context}.lens_id")
        reviewer_id = require_control_id(lens["reviewer_id"], f"{lens_context}.reviewer_id")
        if lens_id in lens_ids:
            raise ReviewError(f"coverage plan has duplicate lens_id: {lens_id}")
        if reviewer_id in reviewer_ids:
            raise ReviewError(f"coverage plan has duplicate reviewer_id: {reviewer_id}")
        lens_ids.add(lens_id)
        reviewer_ids.add(reviewer_id)
        review_mode = require_string(lens["review_mode"], f"{lens_context}.review_mode")
        if review_mode not in REVIEW_MODES:
            raise ReviewError(f"{lens_context}.review_mode must be one of {sorted(REVIEW_MODES)}")
        fallback = require_string(lens["fallback"], f"{lens_context}.fallback")
        if fallback not in COVERAGE_FALLBACKS:
            raise ReviewError(f"{lens_context}.fallback must be one of {sorted(COVERAGE_FALLBACKS)}")
        lenses.append(
            {
                "lens_id": lens_id,
                "required": require_bool(lens["required"], f"{lens_context}.required"),
                "reviewer_id": reviewer_id,
                "independence_group": require_string(
                    lens["independence_group"], f"{lens_context}.independence_group"
                ),
                "review_mode": review_mode,
                "fallback": fallback,
            }
        )

    lens_by_id = {lens["lens_id"]: lens for lens in lenses}
    required_lenses = (
        CORE_LENSES
        if workflow_profile == WORKFLOW_PROFILE_REVIEW
        else SIMPLIFICATION_CORE_LENSES
    )
    missing_core = sorted(
        lens_id
        for lens_id in required_lenses
        if lens_id not in lens_by_id or not lens_by_id[lens_id]["required"]
    )
    if missing_core:
        raise ReviewError(
            f"{workflow_profile} coverage plan must require every core lens: "
            + ", ".join(missing_core)
        )
    if workflow_profile == WORKFLOW_PROFILE_REVIEW and risk_signals and (
        "protocol_coherence" not in lens_by_id
        or not lens_by_id["protocol_coherence"]["required"]
    ):
        raise ReviewError(
            "coverage plan must require protocol_coherence when protocol risk signals are present"
        )
    if workflow_profile == WORKFLOW_PROFILE_SIMPLIFICATION:
        required_extras = sorted(
            lens["lens_id"]
            for lens in lenses
            if lens["required"] and lens["lens_id"] not in SIMPLIFICATION_CORE_LENSES
        )
        if required_extras:
            raise ReviewError(
                "material_simplification additional lenses must be optional: "
                + ", ".join(required_extras)
            )
        invalid_fallbacks = sorted(
            lens["lens_id"]
            for lens in lenses
            if (
                lens["required"]
                and lens["fallback"] != "sequential_degraded_self_audit"
            )
            or (not lens["required"] and lens["fallback"] != "none")
        )
        if invalid_fallbacks:
            raise ReviewError(
                "material_simplification requires one declared sequential fallback for each "
                "required lens and fallback=none for optional lenses: "
                + ", ".join(invalid_fallbacks)
            )
    max_corrections = require_int(
        obj["max_candidate_corrections"],
        "coverage plan.max_candidate_corrections",
        minimum=1,
        maximum=1,
    )
    return {
        "schema_version": COVERAGE_PLAN_SCHEMA,
        "scope_hash": scope_hash,
        "workflow_profile": workflow_profile,
        "risk_signals": risk_signals,
        "lenses": lenses,
        "max_candidate_corrections": max_corrections,
    }


def candidate_semantic_hash(findings: list[dict[str, Any]]) -> str | None:
    if not all(isinstance(item, dict) for item in findings):
        return None
    payload = [
        {
            field: item[field]
            for field in CANDIDATE_SUBSTANTIVE_FIELDS
            if field in item
        }
        for item in findings
    ]
    return canonical_hash(payload)


def parse_csv_ids(values: Sequence[str] | None) -> set[str]:
    result: set[str] = set()
    for raw in values or []:
        for item in raw.split(","):
            item = item.strip()
            if item:
                result.add(item)
    return result


def path_state(path: Path) -> dict[str, Any]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"type": "missing"}
    mode = stat.S_IMODE(info.st_mode)
    if stat.S_ISLNK(info.st_mode):
        target = os.readlink(path)
        data = os.fsencode(target)
        return {"type": "symlink", "target": target, "mode": mode, "sha256": sha256_bytes(data), "size": len(data)}
    if stat.S_ISREG(info.st_mode):
        return {"type": "file", "mode": mode, "sha256": sha256_file(path), "size": info.st_size}
    if stat.S_ISDIR(info.st_mode):
        return {"type": "directory", "mode": mode}
    return {"type": "other", "mode": mode, "size": info.st_size}


def bytes_are_binary(data: bytes) -> bool:
    if b"\x00" in data[:8192]:
        return True
    try:
        data.decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


def git_object_bytes(repo: Path, commit: str, path: str) -> bytes | None:
    result = run_process(["git", "show", f"{commit}:{path}"], cwd=repo, check=False)
    if result.returncode != 0:
        return None
    return result.stdout


def source_state_from_bytes(data: bytes | None) -> dict[str, Any]:
    if data is None:
        return {"type": "missing"}
    return {
        "type": "file",
        "sha256": sha256_bytes(data),
        "size": len(data),
        "binary": bytes_are_binary(data),
    }


def parse_name_status_z(data: bytes) -> list[dict[str, Any]]:
    tokens = data.split(b"\0")
    entries: list[dict[str, Any]] = []
    index = 0
    while index < len(tokens):
        status_raw = tokens[index]
        index += 1
        if not status_raw:
            continue
        status = status_raw.decode("ascii", errors="replace")
        if index >= len(tokens):
            raise ReviewError("Malformed git --name-status -z output")
        first = os.fsdecode(tokens[index])
        index += 1
        code = status[:1]
        if code in {"R", "C"}:
            if index >= len(tokens):
                raise ReviewError("Malformed rename/copy record in git diff")
            second = os.fsdecode(tokens[index])
            index += 1
            entries.append({"status": status, "old_path": first, "path": second, "tracked": True})
        else:
            entries.append({"status": status, "old_path": None, "path": first, "tracked": True})
    return entries


def parse_status_paths_z(data: bytes) -> set[str]:
    tokens = data.split(b"\0")
    paths: set[str] = set()
    index = 0
    while index < len(tokens):
        record = tokens[index]
        index += 1
        if not record:
            continue
        if len(record) < 3:
            raise ReviewError("Malformed git status --porcelain -z output")
        xy = record[:2].decode("ascii", errors="replace")
        path = os.fsdecode(record[3:])
        paths.add(normalize_repo_path(path))
        if "R" in xy or "C" in xy:
            if index >= len(tokens):
                raise ReviewError("Malformed rename/copy record in git status")
            other = os.fsdecode(tokens[index])
            index += 1
            if other:
                paths.add(normalize_repo_path(other))
    return paths


def current_branch(repo: Path) -> str:
    result = run_process(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=repo, check=False)
    if result.returncode != 0:
        return "DETACHED"
    return result.stdout.decode("utf-8", errors="replace").strip()


def resolve_commit(repo: Path, ref: str) -> str:
    return git_text(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
GITHUB_PULL_REQUEST_ID_RE = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*$"
)
REVIEW_OBJECT_KINDS = {"pull_request"}
COMMIT_COMPARISON_KINDS = {"commit", "merge_base_to_head"}


def normalize_review_object(
    *, kind: str, identifier: str, base_sha: str, head_sha: str, requested_scope: str
) -> dict[str, str] | None:
    values = (kind, identifier, base_sha, head_sha)
    if requested_scope != "pull_request":
        if any(values):
            raise ReviewError(
                "PR review provenance is valid only with scope=pull_request; "
                "restart provisional PR-as-range runs"
            )
        return None
    if not all(values):
        raise ReviewError(
            "scope=pull_request requires kind, repository-qualified identifier, "
            "base SHA, and head SHA"
        )
    if kind not in REVIEW_OBJECT_KINDS:
        raise ReviewError(f"Unsupported review-object kind: {kind}")
    if not GITHUB_PULL_REQUEST_ID_RE.fullmatch(identifier):
        raise ReviewError(
            "Pull-request identity must use repository-qualified GitHub form owner/repository#number"
        )
    if not FULL_SHA_RE.fullmatch(base_sha) or not FULL_SHA_RE.fullmatch(head_sha):
        raise ReviewError("PR review provenance requires exact lowercase 40-character SHAs")
    return {
        "kind": kind,
        "identifier": identifier,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "metadata_source": "read_only_host_lookup",
    }


def detect_default_base(repo: Path) -> str:
    candidates: list[str] = []
    symbolic = run_process(
        ["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
        cwd=repo,
        check=False,
    )
    if symbolic.returncode == 0:
        value = symbolic.stdout.decode("utf-8", errors="replace").strip()
        if value:
            candidates.append(value)
    candidates.extend(["origin/main", "origin/master", "main", "master"])
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        result = run_process(["git", "rev-parse", "--verify", f"{candidate}^{{commit}}"], cwd=repo, check=False)
        if result.returncode == 0:
            return candidate
    raise ReviewError("Could not resolve a default base branch. Pass --base <ref> explicitly.")


def workspace_has_changes(repo: Path, *, include_untracked: bool) -> bool:
    tracked = git_bytes(repo, "status", "--porcelain=v1", "-z", "--untracked-files=no")
    if tracked:
        return True
    if include_untracked:
        return bool(git_bytes(repo, "ls-files", "--others", "--exclude-standard", "-z"))
    return False


def diff_args_for_scope(scope: dict[str, Any], *, name_status: bool = False) -> list[str]:
    base = scope["baseline_sha"]
    if name_status:
        prefix = ["diff", "--name-status", "-z", "--find-renames"]
    else:
        prefix = ["diff", "--binary", "--full-index", "--find-renames"]
    comparison_kind = scope["comparison_kind"]
    if comparison_kind == "working-tree":
        return [*prefix, base, "--"]
    if comparison_kind in COMMIT_COMPARISON_KINDS:
        return [*prefix, f"{base}..{scope['comparison_sha']}", "--"]
    raise ReviewError(f"Unsupported comparison kind: {comparison_kind}")


def comparison_uses_commit_tree(comparison_kind: str) -> bool:
    if comparison_kind in COMMIT_COMPARISON_KINDS:
        return True
    if comparison_kind == "working-tree":
        return False
    raise ReviewError(f"Unsupported comparison kind: {comparison_kind}")


def build_scope(
    repo: Path,
    *,
    requested_scope: str,
    base_ref: str | None,
    head_ref: str | None,
    include_untracked: bool,
    review_object: dict[str, str] | None = None,
) -> dict[str, Any]:
    head_sha = resolve_commit(repo, "HEAD")
    branch = current_branch(repo)
    actual_scope = requested_scope
    effective_merge_base: str | None = None
    if requested_scope == "auto":
        actual_scope = "uncommitted" if workspace_has_changes(repo, include_untracked=include_untracked) else "branch"

    if actual_scope == "uncommitted":
        baseline_reference = "HEAD"
        baseline_sha = head_sha
        comparison_kind = "working-tree"
        comparison_reference = "working-tree"
        comparison_sha = head_sha
        mutable = True
    elif actual_scope == "branch":
        baseline_reference = base_ref or detect_default_base(repo)
        resolve_commit(repo, baseline_reference)
        baseline_sha = git_text(repo, "merge-base", "HEAD", baseline_reference)
        comparison_kind = "working-tree"
        comparison_reference = "working-tree"
        comparison_sha = head_sha
        mutable = True
    elif actual_scope == "range":
        if not base_ref or not head_ref:
            raise ReviewError("scope=range requires both --base and --head")
        baseline_reference = base_ref
        comparison_reference = head_ref
        baseline_sha = resolve_commit(repo, base_ref)
        comparison_sha = resolve_commit(repo, head_ref)
        comparison_kind = "commit"
        mutable = False
    elif actual_scope == "pull_request":
        if not base_ref or not head_ref:
            raise ReviewError("scope=pull_request requires both --base and --head")
        if review_object is None:
            raise ReviewError("scope=pull_request requires complete PR review provenance")
        host_base_sha = resolve_commit(repo, base_ref)
        host_head_sha = resolve_commit(repo, head_ref)
        if host_base_sha != review_object["base_sha"]:
            raise ReviewError(
                "PR review base SHA mismatch: "
                f"expected {review_object['base_sha']}, actual {host_base_sha}"
            )
        if host_head_sha != review_object["head_sha"]:
            raise ReviewError(
                "PR review head SHA mismatch: "
                f"expected {review_object['head_sha']}, actual {host_head_sha}"
            )
        baseline_reference = base_ref
        comparison_reference = head_ref
        effective_merge_base = git_text(repo, "merge-base", host_base_sha, host_head_sha)
        baseline_sha = effective_merge_base
        comparison_sha = host_head_sha
        comparison_kind = "merge_base_to_head"
        mutable = False
    else:
        raise ReviewError(f"Unsupported scope: {actual_scope}")

    if review_object is not None and actual_scope != "pull_request":
        raise ReviewError(
            "PR review provenance requires scope=pull_request; "
            "restart provisional PR-as-range runs"
        )

    scope_base: dict[str, Any] = {
        "requested_scope": requested_scope,
        "actual_scope": actual_scope,
        "base_reference": baseline_reference,
        "head_reference": head_ref,
        "baseline_sha": baseline_sha,
        "comparison_kind": comparison_kind,
        "comparison_reference": comparison_reference,
        "comparison_sha": comparison_sha,
        "include_untracked": include_untracked,
        "mutable": mutable,
        "branch": branch if mutable else None,
        "workspace_head_sha": head_sha if mutable else None,
    }
    if effective_merge_base is not None:
        scope_base["effective_merge_base"] = effective_merge_base

    patch = git_bytes(repo, *diff_args_for_scope(scope_base, name_status=False))
    status_data = git_bytes(repo, *diff_args_for_scope(scope_base, name_status=True))
    entries = parse_name_status_z(status_data)

    if include_untracked and comparison_kind == "working-tree":
        untracked = git_bytes(repo, "ls-files", "--others", "--exclude-standard", "-z")
        for raw in untracked.split(b"\0"):
            if not raw:
                continue
            untracked_path = normalize_repo_path(os.fsdecode(raw))
            if is_transient_runtime_path(untracked_path):
                continue
            entries.append({"status": "U", "old_path": None, "path": untracked_path, "tracked": False})

    normalized_entries: list[dict[str, Any]] = []
    for entry in entries:
        path = normalize_repo_path(entry["path"])
        old_path = normalize_repo_path(entry["old_path"]) if entry.get("old_path") else None
        baseline_path = old_path if old_path is not None else path
        baseline_data = git_object_bytes(repo, baseline_sha, baseline_path)
        if comparison_uses_commit_tree(comparison_kind):
            comparison_data = git_object_bytes(repo, comparison_sha, path)
        else:
            target = repo_path(repo, path)
            if target.is_file() and not target.is_symlink():
                comparison_data = target.read_bytes()
            elif target.is_symlink():
                comparison_data = os.fsencode(os.readlink(target))
            else:
                comparison_data = None
        normalized_entries.append(
            {
                "status": entry["status"],
                "path": path,
                "old_path": old_path,
                "tracked": bool(entry["tracked"]),
                "baseline_state": source_state_from_bytes(baseline_data),
                "comparison_state": source_state_from_bytes(comparison_data),
            }
        )

    normalized_entries.sort(key=lambda item: (item["path"], item.get("old_path") or "", item["status"]))

    if comparison_kind == "working-tree":
        staged_patch = git_bytes(repo, "diff", "--cached", "--binary", "--full-index", baseline_sha, "--")
        unstaged_patch = git_bytes(repo, "diff", "--binary", "--full-index", "--")
    else:
        staged_patch = b""
        unstaged_patch = b""

    identity = {
        "schema_version": SCOPE_SCHEMA,
        "actual_scope": actual_scope,
        "base_reference": baseline_reference,
        "head_reference": head_ref,
        "baseline_sha": baseline_sha,
        "comparison_kind": comparison_kind,
        "comparison_reference": comparison_reference,
        "comparison_sha": comparison_sha,
        "include_untracked": include_untracked,
        "mutable": mutable,
        "branch": branch if mutable else None,
        "workspace_head_sha": head_sha if mutable else None,
        "patch_sha256": sha256_bytes(patch),
        "staged_patch_sha256": sha256_bytes(staged_patch),
        "unstaged_patch_sha256": sha256_bytes(unstaged_patch),
        "files": normalized_entries,
    }
    if effective_merge_base is not None:
        identity["effective_merge_base"] = effective_merge_base
    if review_object is not None:
        identity["review_object"] = copy.deepcopy(review_object)
    if not normalized_entries:
        raise ReviewError("The resolved review scope contains no changed files")

    return {
        "identity": identity,
        "scope_hash": scope_identity_hash(identity),
        "patch": patch,
        "staged_patch": staged_patch,
        "unstaged_patch": unstaged_patch,
    }


def all_scope_paths(scope_identity: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for entry in scope_identity["files"]:
        result.add(entry["path"])
        if entry.get("old_path"):
            result.add(entry["old_path"])
    return result


def snapshot_sources(
    repo: Path,
    run_dir: Path,
    scope: dict[str, Any],
    *,
    max_file_bytes: int,
    max_total_bytes: int,
) -> list[str]:
    total = 0
    limitations: list[str] = []
    identity = scope["identity"]
    for entry in identity["files"]:
        for side in ("baseline", "comparison"):
            source_path = entry.get("old_path") if side == "baseline" and entry.get("old_path") else entry["path"]
            state_key = f"{side}_state"
            state_info = entry[state_key]
            if state_info.get("type") == "missing":
                continue
            if side == "baseline":
                data = git_object_bytes(repo, identity["baseline_sha"], source_path)
            elif comparison_uses_commit_tree(identity["comparison_kind"]):
                data = git_object_bytes(repo, identity["comparison_sha"], source_path)
            else:
                target = repo_path(repo, source_path)
                if target.is_file() and not target.is_symlink():
                    data = target.read_bytes()
                elif target.is_symlink():
                    data = os.fsencode(os.readlink(target))
                else:
                    data = None
            if data is None:
                continue
            if len(data) > max_file_bytes:
                limitations.append(f"{side}:{source_path} not snapshotted ({len(data)} bytes exceeds per-file limit)")
                continue
            if total + len(data) > max_total_bytes:
                limitations.append(f"{side}:{source_path} not snapshotted (total snapshot limit reached)")
                continue
            destination = run_dir / "sources" / side / source_path
            atomic_write_bytes(destination, data)
            state_info["snapshot_path"] = str(destination.relative_to(run_dir)).replace("\\", "/")
            total += len(data)
    return limitations


def make_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def state_path(run_dir: Path) -> Path:
    return run_dir / "state.json"


def load_state(run_dir: Path) -> dict[str, Any]:
    state = require_object(load_json(state_path(run_dir)), "state")
    if state.get("schema_version") != STATE_SCHEMA:
        raise ReviewError(f"Unsupported state schema in {run_dir}")
    return state


def save_state(run_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    atomic_write_json(state_path(run_dir), state)


def load_verified_scope(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    scope = require_object(load_json(run_dir / "scope.json"), "frozen scope")
    identity = require_object(scope.get("identity"), "frozen scope.identity")
    embedded = require_string(scope.get("scope_hash"), "frozen scope.scope_hash")
    recomputed = scope_identity_hash(identity)
    if embedded != recomputed or embedded != state.get("scope_hash"):
        raise ReviewError(
            "Frozen scope metadata failed integrity validation against its identity and state"
        )
    patch_checks = (
        ("scope.patch", "patch_sha256"),
        ("staged.patch", "staged_patch_sha256"),
        ("unstaged.patch", "unstaged_patch_sha256"),
    )
    for filename, identity_key in patch_checks:
        if sha256_file(run_dir / filename) != identity.get(identity_key):
            raise ReviewError(f"{filename} does not match the frozen scope identity")
    files_copy = load_json(run_dir / "files.json")
    if files_copy != identity.get("files"):
        raise ReviewError("files.json does not match scope.json identity.files")
    return scope


def load_verified_findings_gate(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    receipt = require_object(load_json(run_dir / "gates" / "findings.json"), "Gate A receipt")
    receipt_hash = verify_embedded_hash(
        receipt,
        hash_field="receipt_hash",
        context="Gate A receipt",
    )
    require_state_gate(state, "findings", receipt_hash, "Gate A receipt")
    require_state_hash(state, "findings_gate_hash", receipt_hash, "Gate A receipt")
    return receipt


def load_verified_ledger(
    run_dir: Path,
    state: dict[str, Any],
    *,
    findings_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ledger = require_object(load_json(run_dir / "ledger.json"), "ledger")
    ledger_hash = verify_embedded_hash(
        ledger,
        hash_field="ledger_hash",
        context="ledger",
        unhashed_fields={"generated_at"},
    )
    require_state_hash(state, "ledger_hash", ledger_hash, "ledger")
    if findings_gate is not None and findings_gate.get("ledger_hash") != ledger_hash:
        raise ReviewError("Ledger does not match the hash recorded by Gate A")
    return ledger


def load_verified_plan(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    plan = require_object(load_json(run_dir / "fix-plan.json"), "fix plan")
    plan_hash = verify_embedded_hash(
        plan,
        hash_field="plan_hash",
        context="fix plan",
        unhashed_fields={"validated_at"},
    )
    require_state_hash(state, "plan_hash", plan_hash, "fix plan")
    return plan


def load_verified_plan_gate(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    receipt = require_object(load_json(run_dir / "gates" / "plan.json"), "Gate B receipt")
    receipt_hash = verify_embedded_hash(
        receipt,
        hash_field="receipt_hash",
        context="Gate B receipt",
    )
    require_state_gate(state, "plan", receipt_hash, "Gate B receipt")
    require_state_hash(state, "plan_gate_hash", receipt_hash, "Gate B receipt")
    return receipt


def load_verified_fix_summary(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    summary = require_object(load_json(run_dir / "fix-summary.json"), "fix summary")
    summary_hash = verify_embedded_hash(
        summary,
        hash_field="fix_summary_hash",
        context="fix summary",
    )
    require_state_hash(state, "fix_summary_hash", summary_hash, "fix summary")
    patch_path = run_dir / "fix-summary.patch"
    if sha256_file(patch_path) != summary.get("fix_patch_sha256"):
        raise ReviewError("fix-summary.patch does not match fix-summary.json")
    return summary


def resolve_run_dir(args: argparse.Namespace, repo: Path) -> tuple[Path, Path]:
    artifact_root = resolve_artifact_root(repo, getattr(args, "artifact_root", None))
    runs_root = artifact_root / "runs"
    raw_run_id = getattr(args, "run_id", None) or os.environ.get("MATERIAL_REVIEW_RUN_ID")
    run_id = normalize_run_id(raw_run_id) if raw_run_id else None
    if run_id:
        run_dir = runs_root / run_id
        if not state_path(run_dir).exists():
            raise ReviewError(f"Run not found: {run_id} under {runs_root}")
        state = load_state(run_dir)
        if Path(state.get("repo_root", "")).resolve() != repo:
            raise ReviewError(
                f"Run {run_id} belongs to {state.get('repo_root')}, not the requested repository {repo}"
            )
        return artifact_root, run_dir

    if not runs_root.exists():
        raise ReviewError("No material-code-review runs exist; run init first or pass --run-id")
    candidates: list[Path] = []
    for path in sorted(runs_root.iterdir()):
        if not state_path(path).exists():
            continue
        try:
            state = load_state(path)
        except ReviewError:
            continue
        if Path(state.get("repo_root", "")).resolve() != repo:
            continue
        if state.get("phase") not in {
            PHASE_COMPLETE,
            PHASE_ABORTED,
            PHASE_REVIEW_INCOMPLETE,
        }:
            candidates.append(path)
    if len(candidates) == 1:
        return artifact_root, candidates[0]
    if not candidates:
        all_repo_runs = [
            path
            for path in sorted(runs_root.iterdir())
            if state_path(path).exists()
            and Path(load_state(path).get("repo_root", "")).resolve() == repo
        ]
        if len(all_repo_runs) == 1:
            return artifact_root, all_repo_runs[0]
        raise ReviewError("No unique active run found; pass --run-id or set MATERIAL_REVIEW_RUN_ID")
    raise ReviewError(
        "Multiple active runs found: " + ", ".join(path.name for path in candidates) + ". Pass --run-id."
    )


def write_source_bundle_files(run_dir: Path, scope: dict[str, Any], limitations: list[str]) -> None:
    atomic_write_bytes(run_dir / "scope.patch", scope["patch"])
    atomic_write_bytes(run_dir / "staged.patch", scope["staged_patch"])
    atomic_write_bytes(run_dir / "unstaged.patch", scope["unstaged_patch"])
    identity = copy.deepcopy(scope["identity"])
    atomic_write_json(
        run_dir / "scope.json",
        {
            "schema_version": SCOPE_SCHEMA,
            "scope_hash": scope["scope_hash"],
            "identity": identity,
            "snapshot_limitations": limitations,
            "captured_at": utc_now(),
        },
    )
    atomic_write_json(run_dir / "files.json", identity["files"])
    lines = [
        "# Frozen review scope",
        "",
        f"- Scope hash: `{scope['scope_hash']}`",
        f"- Mode: `{identity['actual_scope']}`",
    ]
    if identity.get("review_object"):
        review_object = identity["review_object"]
        lines.extend(
            [
                f"- Review object: `{review_object['kind']}` `{review_object['identifier']}`",
                f"- Host base: `{identity['base_reference']}` -> `{review_object['base_sha']}`",
                f"- Host head: `{identity['head_reference']}` -> `{review_object['head_sha']}`",
                f"- Effective merge base: `{identity['effective_merge_base']}`",
                f"- Review metadata source: `{review_object['metadata_source']}`",
            ]
        )
    else:
        lines.append(
            f"- Baseline: `{identity['base_reference']}` -> `{identity['baseline_sha']}`"
        )
    lines.extend(
        [
            f"- Comparison kind: `{identity['comparison_kind']}`",
            f"- Comparison: `{identity['comparison_reference']}` -> `{identity['comparison_sha']}`",
            f"- Mutable/aligned: `{str(identity['mutable']).lower()}`",
            f"- Include untracked: `{str(identity['include_untracked']).lower()}`",
        ]
    )
    lines.extend(["", "## Files", ""])
    for entry in identity["files"]:
        rename = f" (from `{entry['old_path']}`)" if entry.get("old_path") else ""
        lines.append(f"- `{entry['status']}` `{entry['path']}`{rename}")
    if limitations:
        lines.extend(["", "## Snapshot limitations", ""])
        lines.extend(f"- {item}" for item in limitations)
    atomic_write_text(run_dir / "scope.md", "\n".join(lines) + "\n")


def recompute_scope_from_state(repo: Path, state: dict[str, Any]) -> dict[str, Any]:
    params = state["scope_params"]
    if params["actual_scope"] == "range" and params.get("review_object"):
        raise ReviewError(
            "Provisional PR-as-range scope is no longer supported; "
            "restart the run with scope=pull_request"
        )
    return build_scope(
        repo,
        requested_scope=params["actual_scope"],
        base_ref=params.get("base_reference"),
        head_ref=params.get("head_reference"),
        include_untracked=bool(params["include_untracked"]),
        review_object=params.get("review_object"),
    )


def check_scope_fresh(repo: Path, run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    if state["phase"] in MUTATION_PHASES:
        raise ReviewError("Original scope freshness is not used after begin-fix; use checkpoint/workspace controls")
    current = recompute_scope_from_state(repo, state)
    if current["scope_hash"] != state["scope_hash"]:
        report = {
            "expected_scope_hash": state["scope_hash"],
            "current_scope_hash": current["scope_hash"],
            "checked_at": utc_now(),
            "expected_identity": load_json(run_dir / "scope.json")["identity"],
            "current_identity": current["identity"],
        }
        atomic_write_json(run_dir / "scope-staleness.json", report)
        raise ReviewError(
            "Frozen review scope is stale. See scope-staleness.json; reinitialize or regenerate downstream artifacts."
        )
    return current


def workspace_status_paths(repo: Path) -> set[str]:
    data = git_bytes(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    paths = parse_status_paths_z(data)
    tracked_raw = git_bytes(repo, "ls-files", "-z")
    tracked = {normalize_repo_path(os.fsdecode(raw)) for raw in tracked_raw.split(b"\0") if raw}
    return {path for path in paths if path in tracked or not is_transient_runtime_path(path)}


def workspace_guard(repo: Path) -> dict[str, Any]:
    paths = sorted(workspace_status_paths(repo))
    states = {path: path_state(repo_path(repo, path)) for path in paths}
    staged = git_bytes(repo, "diff", "--cached", "--binary", "--full-index", "HEAD", "--")
    unstaged = git_bytes(repo, "diff", "--binary", "--full-index", "--")
    identity = {
        "head_sha": resolve_commit(repo, "HEAD"),
        "branch": current_branch(repo),
        "staged_patch_sha256": sha256_bytes(staged),
        "unstaged_patch_sha256": sha256_bytes(unstaged),
        "path_states": states,
    }
    return {"identity": identity, "guard_hash": canonical_hash(identity)}


def diff_guard_paths(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    before_states = before["identity"]["path_states"]
    after_states = after["identity"]["path_states"]
    paths = set(before_states) | set(after_states)
    return {path for path in paths if before_states.get(path, {"type": "clean"}) != after_states.get(path, {"type": "clean"})}


def ensure_expected_workspace(repo: Path, state: dict[str, Any]) -> dict[str, Any]:
    current = workspace_guard(repo)
    expected = state.get("expected_workspace_guard_hash")
    if expected and current["guard_hash"] != expected:
        raise ReviewError(
            "Workspace drifted outside the controlled repair sequence. Reconcile user/tool changes before proceeding."
        )
    return current


def snapshot_copy_path(repo: Path, snapshot_root: Path, path: str, state_info: dict[str, Any]) -> None:
    source = repo_path(repo, path)
    destination = snapshot_root / "content" / path
    if state_info["type"] == "file":
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    elif state_info["type"] == "symlink":
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(destination.with_suffix(destination.suffix + ".symlink"), state_info["target"])


def create_checkpoint(repo: Path, checkpoint_dir: Path, extra_paths: Iterable[str]) -> dict[str, Any]:
    if checkpoint_dir.exists():
        raise ReviewError(f"Checkpoint already exists: {checkpoint_dir}")
    checkpoint_dir.mkdir(parents=True, exist_ok=False)
    guard = workspace_guard(repo)
    paths = set(guard["identity"]["path_states"])
    paths.update(normalize_repo_path(path) for path in extra_paths)
    path_states: dict[str, Any] = {}
    for path in sorted(paths):
        info = path_state(repo_path(repo, path))
        path_states[path] = info
        snapshot_copy_path(repo, checkpoint_dir, path, info)

    index_raw = git_text(repo, "rev-parse", "--git-path", "index")
    index_path = Path(index_raw)
    if not index_path.is_absolute():
        index_path = repo / index_path
    index_backup = checkpoint_dir / "index.backup"
    if index_path.exists():
        shutil.copyfile(index_path, index_backup)
        index_present = True
        index_sha256 = sha256_file(index_backup)
    else:
        index_present = False
        index_sha256 = None

    metadata = {
        "created_at": utc_now(),
        "head_sha": guard["identity"]["head_sha"],
        "branch": guard["identity"]["branch"],
        "workspace_guard": guard,
        "path_states": path_states,
        "index_path": str(index_path),
        "index_present": index_present,
        "index_sha256": index_sha256,
    }
    metadata["checkpoint_hash"] = canonical_hash({key: value for key, value in metadata.items() if key != "created_at"})
    atomic_write_json(checkpoint_dir / "checkpoint.json", metadata)
    return metadata


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def restore_one_snapshot_path(repo: Path, checkpoint_dir: Path, path: str, info: dict[str, Any]) -> None:
    target = repo_path(repo, path)
    kind = info["type"]
    if kind == "missing":
        remove_path(target)
        return
    if kind == "directory":
        if target.exists() and not target.is_dir():
            remove_path(target)
        target.mkdir(parents=True, exist_ok=True)
        os.chmod(target, info.get("mode", 0o755))
        return
    if kind == "file":
        if target.exists() or target.is_symlink():
            remove_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        source = checkpoint_dir / "content" / path
        shutil.copyfile(source, target)
        os.chmod(target, info.get("mode", 0o644))
        return
    if kind == "symlink":
        if target.exists() or target.is_symlink():
            remove_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        link_target = (checkpoint_dir / "content" / path).with_suffix((checkpoint_dir / "content" / path).suffix + ".symlink").read_text(encoding="utf-8")
        os.symlink(link_target, target)
        return
    raise ReviewError(f"Cannot restore unsupported file type for {path}: {kind}")


def path_exists_in_head(repo: Path, path: str) -> bool:
    result = run_process(["git", "cat-file", "-e", f"HEAD:{path}"], cwd=repo, check=False)
    return result.returncode == 0


def verify_checkpoint_integrity(
    repo: Path,
    checkpoint_dir: Path,
    *,
    require_current_ref: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Validate checkpoint metadata, snapshots, and Git-index backup before use.

    Checkpoints are used both for restoration and as the authoritative repair
    baseline.  Verifying them only during restore would let a corrupted baseline
    influence path authorization or rendered diffs before corruption is noticed.
    """
    metadata = require_object(load_json(checkpoint_dir / "checkpoint.json"), "checkpoint")
    verify_embedded_hash(
        metadata,
        hash_field="checkpoint_hash",
        context="checkpoint",
        unhashed_fields={"created_at"},
    )
    guard = require_object(metadata.get("workspace_guard"), "checkpoint.workspace_guard")
    guard_identity = require_object(guard.get("identity"), "checkpoint.workspace_guard.identity")
    if guard.get("guard_hash") != canonical_hash(guard_identity):
        raise ReviewError("Checkpoint workspace guard failed its embedded hash check")
    checkpoint_head = require_string(metadata.get("head_sha"), "checkpoint.head_sha")
    checkpoint_branch = require_string(metadata.get("branch"), "checkpoint.branch")
    if guard_identity.get("head_sha") != checkpoint_head or guard_identity.get("branch") != checkpoint_branch:
        raise ReviewError("Checkpoint top-level Git identity does not match its workspace guard")
    if require_current_ref and (
        resolve_commit(repo, "HEAD") != checkpoint_head or current_branch(repo) != checkpoint_branch
    ):
        raise ReviewError("Cannot restore automatically because HEAD or branch changed after the checkpoint")

    current_index_raw = git_text(repo, "rev-parse", "--git-path", "index")
    current_index_path = Path(current_index_raw)
    if not current_index_path.is_absolute():
        current_index_path = repo / current_index_path
    current_index_path = current_index_path.resolve(strict=False)
    recorded_index_path = Path(require_string(metadata.get("index_path"), "checkpoint.index_path")).resolve(strict=False)
    if current_index_path != recorded_index_path:
        raise ReviewError("Checkpoint index path does not match the repository's current Git index")

    raw_path_states = require_object(metadata.get("path_states"), "checkpoint.path_states")
    path_states: dict[str, Any] = {}
    for raw_path, raw_info in raw_path_states.items():
        path = normalize_repo_path(require_string(raw_path, "checkpoint path"))
        if path in path_states:
            raise ReviewError(f"Checkpoint contains duplicate normalized path: {path}")
        info = require_object(raw_info, f"checkpoint.path_states.{path}")
        path_states[path] = info
        kind = require_string(info.get("type"), f"checkpoint.path_states.{path}.type")
        if kind == "file":
            source = checkpoint_dir / "content" / path
            if not source.is_file() or source.is_symlink():
                raise ReviewError(f"Checkpoint file snapshot is missing or invalid: {path}")
            if info.get("sha256") and sha256_file(source) != info["sha256"]:
                raise ReviewError(f"Checkpoint file snapshot failed its hash check: {path}")
            if info.get("size") is not None and source.stat().st_size != info["size"]:
                raise ReviewError(f"Checkpoint file snapshot failed its size check: {path}")
        elif kind == "symlink":
            source = (checkpoint_dir / "content" / path).with_suffix(
                (checkpoint_dir / "content" / path).suffix + ".symlink"
            )
            if not source.is_file():
                raise ReviewError(f"Checkpoint symlink snapshot is missing: {path}")
            if source.read_text(encoding="utf-8") != info.get("target"):
                raise ReviewError(f"Checkpoint symlink snapshot failed its target check: {path}")
        elif kind not in {"missing", "directory"}:
            raise ReviewError(f"Checkpoint contains unsupported file type for {path}: {kind}")

    if require_bool(metadata.get("index_present"), "checkpoint.index_present"):
        backup = checkpoint_dir / "index.backup"
        if not backup.is_file():
            raise ReviewError("Checkpoint Git index backup is missing")
        if sha256_file(backup) != metadata.get("index_sha256"):
            raise ReviewError("Checkpoint Git index backup failed its hash check")
    elif metadata.get("index_sha256") is not None:
        raise ReviewError("Checkpoint records an index hash although no index was present")

    return metadata, path_states, current_index_path


def restore_checkpoint(repo: Path, checkpoint_dir: Path) -> dict[str, Any]:
    metadata, path_states, current_index_path = verify_checkpoint_integrity(
        repo,
        checkpoint_dir,
        require_current_ref=True,
    )

    current_paths = workspace_status_paths(repo)
    snap_paths = set(path_states)
    for path in sorted(current_paths - snap_paths):
        target = repo_path(repo, path)
        if path_exists_in_head(repo, path):
            run_process(["git", "restore", "--source=HEAD", "--worktree", "--", path], cwd=repo, check=True)
        else:
            remove_path(target)

    index_path = current_index_path
    if metadata["index_present"]:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        temp_index = index_path.with_name(f".{index_path.name}.material-review.tmp")
        shutil.copyfile(checkpoint_dir / "index.backup", temp_index)
        os.replace(temp_index, index_path)
    else:
        index_path.unlink(missing_ok=True)

    for path, info in path_states.items():
        restore_one_snapshot_path(repo, checkpoint_dir, normalize_repo_path(path), info)

    current = workspace_guard(repo)
    expected_hash = metadata["workspace_guard"]["guard_hash"]
    if current["guard_hash"] != expected_hash:
        atomic_write_json(
            checkpoint_dir / "restore-mismatch.json",
            {
                "expected": metadata["workspace_guard"],
                "current": current,
                "checked_at": utc_now(),
            },
        )
        raise ReviewError("Checkpoint restoration did not reproduce the original workspace; human recovery is required")
    return current


def verify_frozen_source_bytes(
    data: bytes | None, state_info: dict[str, Any], *, label: str
) -> bytes | None:
    if data is None:
        if state_info.get("type") != "missing":
            raise ReviewError(f"Frozen source {label} is missing but scope metadata expected content")
        return None
    expected = state_info.get("sha256")
    if expected and sha256_bytes(data) != expected:
        raise ReviewError(f"Frozen source {label} failed its content hash check")
    if state_info.get("size") is not None and len(data) != state_info["size"]:
        raise ReviewError(f"Frozen source {label} failed its size check")
    return data


def read_snapshot_source(run_dir: Path, scope_identity: dict[str, Any], side: str, path: str, repo: Path) -> bytes | None:
    for entry in scope_identity["files"]:
        candidates = [entry["path"]]
        if entry.get("old_path"):
            candidates.append(entry["old_path"])
        if path not in candidates:
            continue
        state_key = f"{side}_state"
        state_info = entry[state_key]
        snapshot_path = state_info.get("snapshot_path")
        if snapshot_path:
            data = (run_dir / snapshot_path).read_bytes()
            return verify_frozen_source_bytes(data, state_info, label=f"{side}:{path}")
        if side == "baseline":
            source_path = entry.get("old_path") if entry.get("old_path") and path == entry.get("old_path") else path
            data = git_object_bytes(repo, scope_identity["baseline_sha"], source_path)
            return verify_frozen_source_bytes(data, state_info, label=f"{side}:{path}")
        if comparison_uses_commit_tree(scope_identity["comparison_kind"]):
            data = git_object_bytes(repo, scope_identity["comparison_sha"], path)
            return verify_frozen_source_bytes(data, state_info, label=f"{side}:{path}")
        target = repo_path(repo, path)
        if target.is_file() and not target.is_symlink():
            data = target.read_bytes()
        elif target.is_symlink():
            data = os.fsencode(os.readlink(target))
        else:
            data = None
        return verify_frozen_source_bytes(data, state_info, label=f"{side}:{path}")
    return None

def verify_evidence_quote(
    *,
    repo: Path,
    run_dir: Path,
    scope_identity: dict[str, Any],
    file: str,
    line_start: int,
    line_end: int,
    side: str,
    quote: str,
) -> None:
    if side == "diff":
        patch = (run_dir / "scope.patch").read_text(encoding="utf-8", errors="replace")
        stripped = "\n".join(line[1:] if line[:1] in {"+", "-", " "} else line for line in patch.splitlines())
        if quote not in patch and quote not in stripped:
            raise ReviewError(f"Evidence quote for {file}:{line_start} was not found in the frozen diff")
        return

    data = read_snapshot_source(run_dir, scope_identity, side, file, repo)
    if data is None:
        raise ReviewError(f"Evidence source is missing for {side}:{file}")
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if line_start > len(lines):
        raise ReviewError(f"Evidence line {line_start} exceeds {side}:{file} length {len(lines)}")
    line_end = min(line_end, len(lines))
    region = "\n".join(lines[line_start - 1 : line_end])
    if quote not in region:
        if quote in text:
            raise ReviewError(f"Evidence quote exists in {side}:{file} but not at lines {line_start}-{line_end}")
        raise ReviewError(f"Evidence quote was not found in {side}:{file}")


def render_path_diff(checkpoint_dir: Path, repo: Path, path: str, before: dict[str, Any], after: dict[str, Any]) -> str:
    header = f"# {path}\n"
    if before == after:
        return ""
    if before.get("type") == "file":
        before_bytes = (checkpoint_dir / "content" / path).read_bytes()
    elif before.get("type") == "symlink":
        before_bytes = before.get("target", "").encode("utf-8")
    else:
        before_bytes = b""
    target = repo_path(repo, path)
    if after.get("type") == "file":
        after_bytes = target.read_bytes()
    elif after.get("type") == "symlink":
        after_bytes = os.fsencode(os.readlink(target))
    else:
        after_bytes = b""
    if bytes_are_binary(before_bytes) or bytes_are_binary(after_bytes):
        return (
            header
            + f"Binary/state change: {before.get('type')} {before.get('sha256', '-')} -> "
            + f"{after.get('type')} {after.get('sha256', '-')}\n"
        )
    before_text = before_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)
    after_text = after_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(before_text, after_text, fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="\n")
    )


def render_checkpoint_diff(checkpoint_dir: Path, repo: Path, changed_paths: Iterable[str]) -> str:
    _, path_states, _ = verify_checkpoint_integrity(repo, checkpoint_dir)
    chunks: list[str] = []
    for path in sorted(changed_paths):
        before = path_states.get(path, {"type": "missing"})
        after = path_state(repo_path(repo, path))
        chunk = render_path_diff(checkpoint_dir, repo, path, before, after)
        if chunk:
            chunks.append(chunk)
    return "\n".join(chunks)


def _normalize_candidate_set(
    raw: Any,
    *,
    source_file: Path,
    repo: Path,
    run_dir: Path,
    state: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    obj = require_object(raw, f"candidate set {source_file}")
    expected_top = {
        "schema_version",
        "scope_hash",
        "reviewer_id",
        "independence_group",
        "review_mode",
        "findings",
        "coverage",
    }
    require_exact_keys(obj, expected_top, f"candidate set {source_file}")
    if obj["schema_version"] != CANDIDATE_SCHEMA:
        raise ReviewError(f"{source_file}: unsupported schema_version")
    if obj["scope_hash"] != state["scope_hash"]:
        raise ReviewError(f"{source_file}: scope_hash does not match the active frozen scope")
    reviewer_id = require_string(obj["reviewer_id"], f"{source_file}.reviewer_id")
    independence_group = require_string(obj["independence_group"], f"{source_file}.independence_group")
    review_mode = require_string(obj["review_mode"], f"{source_file}.review_mode")
    if review_mode not in REVIEW_MODES:
        raise ReviewError(f"{source_file}.review_mode must be one of {sorted(REVIEW_MODES)}")

    coverage = require_object(obj["coverage"], f"{source_file}.coverage")
    require_exact_keys(coverage, {"files_reviewed", "areas", "limitations"}, f"{source_file}.coverage")
    coverage_files = [normalize_repo_path(item) for item in require_string_array(coverage["files_reviewed"], f"{source_file}.coverage.files_reviewed")]
    coverage_areas = require_string_array(coverage["areas"], f"{source_file}.coverage.areas")
    coverage_limitations = require_string_array(coverage["limitations"], f"{source_file}.coverage.limitations")

    scope_info = load_verified_scope(run_dir, state)
    scope_identity = scope_info["identity"]
    scope_paths = all_scope_paths(scope_identity)
    findings_raw = require_array(obj["findings"], f"{source_file}.findings")
    valid_findings: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    local_ids: set[str] = set()
    finding_keys = set(CANDIDATE_FINDING_FIELDS)

    for index, raw_finding in enumerate(findings_raw):
        context = f"{source_file}.findings[{index}]"
        try:
            finding = require_object(raw_finding, context)
            require_exact_keys(finding, finding_keys, context)
            local_id = require_string(finding["local_id"], f"{context}.local_id")
            if local_id in local_ids:
                raise ReviewError(f"{context}.local_id is duplicated: {local_id}")
            local_ids.add(local_id)
            title = require_string(finding["title"], f"{context}.title")
            if len(title) > 140:
                raise ReviewError(f"{context}.title exceeds 140 characters")
            nature = require_string(finding["nature"], f"{context}.nature")
            category = require_string(finding["category"], f"{context}.category")
            severity = require_string(finding["severity"], f"{context}.severity")
            confidence = require_string(finding["confidence"], f"{context}.confidence")
            if nature not in NATURES:
                raise ReviewError(f"{context}.nature must be one of {sorted(NATURES)}")
            if category not in CATEGORIES:
                raise ReviewError(f"{context}.category must be one of {sorted(CATEGORIES)}")
            if severity not in SEVERITIES:
                raise ReviewError(f"{context}.severity must be one of {sorted(SEVERITIES)}")
            if confidence not in CONFIDENCES:
                raise ReviewError(f"{context}.confidence must be one of {sorted(CONFIDENCES)}")
            if confidence == "low" and severity != "blocker":
                raise ReviewError(f"{context}: low-confidence non-blocker candidates must be suppressed")

            file = normalize_repo_path(require_string(finding["file"], f"{context}.file"))
            line_start = require_int(finding["line_start"], f"{context}.line_start", minimum=1)
            line_end = require_int(finding["line_end"], f"{context}.line_end", minimum=1)
            if line_end < line_start:
                raise ReviewError(f"{context}.line_end must be >= line_start")
            evidence_side = require_string(finding["evidence_side"], f"{context}.evidence_side")
            if evidence_side not in EVIDENCE_SIDES:
                raise ReviewError(f"{context}.evidence_side must be one of {sorted(EVIDENCE_SIDES)}")
            evidence_quote = require_string(finding["evidence_quote"], f"{context}.evidence_quote")
            scope_relation = require_string(finding["scope_relation"], f"{context}.scope_relation")
            if scope_relation not in SCOPE_RELATIONS:
                raise ReviewError(f"{context}.scope_relation must be one of {sorted(SCOPE_RELATIONS)}")
            related = [normalize_repo_path(item) for item in require_string_array(finding["related_changed_files"], f"{context}.related_changed_files")]
            direct_dependency = require_bool(finding["direct_dependency"], f"{context}.direct_dependency")
            if scope_relation == "primary" and file not in scope_paths:
                raise ReviewError(f"{context}: primary file is not part of the frozen changed-file set")
            if scope_relation == "secondary":
                if not related or not any(path in scope_paths for path in related):
                    raise ReviewError(f"{context}: secondary finding must name at least one frozen changed file")
            if scope_relation == "pre_existing" and file not in scope_paths and not direct_dependency:
                # It may be captured for visible rejection, but require an explicit changed-file relation.
                if not related or not any(path in scope_paths for path in related):
                    raise ReviewError(f"{context}: pre-existing candidate must name its changed-file relation")

            counterevidence = require_string_array(finding["counterevidence_checked"], f"{context}.counterevidence_checked")
            if confidence in {"certain", "high"} and not counterevidence:
                raise ReviewError(f"{context}: high/certain confidence requires checked counterevidence")
            estimated_fix_risk = require_string(finding["estimated_fix_risk"], f"{context}.estimated_fix_risk")
            if estimated_fix_risk not in FIX_RISKS:
                raise ReviewError(f"{context}.estimated_fix_risk must be one of {sorted(FIX_RISKS)}")

            verify_evidence_quote(
                repo=repo,
                run_dir=run_dir,
                scope_identity=scope_identity,
                file=file,
                line_start=line_start,
                line_end=line_end,
                side=evidence_side,
                quote=evidence_quote,
            )

            normalized = {
                "candidate_id": None,
                "reviewer_id": reviewer_id,
                "independence_group": independence_group,
                "review_mode": review_mode,
                "source_file": str(source_file),
                "local_id": local_id,
                "title": title,
                "nature": nature,
                "category": category,
                "severity": severity,
                "confidence": confidence,
                "file": file,
                "line_start": line_start,
                "line_end": line_end,
                "evidence_side": evidence_side,
                "evidence_quote": evidence_quote,
                "scope_relation": scope_relation,
                "related_changed_files": related,
                "direct_dependency": direct_dependency,
                "observable_consequence": require_string(finding["observable_consequence"], f"{context}.observable_consequence"),
                "trigger_conditions": require_string(finding["trigger_conditions"], f"{context}.trigger_conditions"),
                "counterevidence_checked": counterevidence,
                "why_not_preference": require_string(finding["why_not_preference"], f"{context}.why_not_preference"),
                "proposed_resolution": require_string(finding["proposed_resolution"], f"{context}.proposed_resolution"),
                "estimated_fix_risk": estimated_fix_risk,
                "requires_user_decision": require_bool(finding["requires_user_decision"], f"{context}.requires_user_decision"),
                "assumptions": require_string_array(finding["assumptions"], f"{context}.assumptions"),
            }
            valid_findings.append(normalized)
        except ReviewError as exc:
            rejections.append({"source_file": str(source_file), "index": index, "reason": str(exc)})

    if findings_raw and not valid_findings:
        reasons = "; ".join(item["reason"] for item in rejections[:3])
        suffix = f": {reasons}" if reasons else ""
        raise ReviewError(f"{source_file}: every submitted finding failed validation{suffix}")

    normalized_set = {
        "reviewer_id": reviewer_id,
        "independence_group": independence_group,
        "review_mode": review_mode,
        "coverage": {
            "files_reviewed": coverage_files,
            "areas": coverage_areas,
            "limitations": coverage_limitations,
        },
        "findings": valid_findings,
    }
    return normalized_set, rejections


def candidate_diagnostic(message: str, *, path: str = "$") -> dict[str, Any]:
    lowered = message.lower()
    finding_match = re.search(r"\.findings\[(\d+)\]", message)
    diagnostic_path = f"findings[{finding_match.group(1)}]" if finding_match else path
    if "invalid json" in lowered:
        code = "JSON_SYNTAX"
    elif "duplicated" in lowered and "local_id" in lowered:
        code = "DUPLICATE_LOCAL_ID"
    elif "not at lines" in lowered or "evidence line" in lowered:
        code = "EVIDENCE_OUTSIDE_RANGE"
    elif "evidence quote" in lowered and "not found" in lowered:
        code = "EVIDENCE_NOT_FOUND"
    elif "evidence source is missing" in lowered:
        code = "EVIDENCE_NOT_FOUND"
    elif "unexpected" in lowered:
        code = "UNKNOWN_FIELD"
    elif diagnostic_path == "$" and any(
        marker in lowered
        for marker in ("schema_version", "scope_hash", "reviewer_id", "review_mode", "coverage")
    ):
        code = "TOP_LEVEL_METADATA"
    else:
        code = "CANDIDATE_INVALID"
    return {
        "code": code,
        "path": diagnostic_path,
        "message": message,
        "correctable": code in CORRECTABLE_DIAGNOSTIC_CODES,
    }


def inspect_candidate_set(
    raw: Any,
    *,
    source_file: Path,
    repo: Path,
    run_dir: Path,
    state: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    try:
        normalized_set, rejections = _normalize_candidate_set(
            raw,
            source_file=source_file,
            repo=repo,
            run_dir=run_dir,
            state=state,
        )
    except ReviewError as exc:
        return None, [candidate_diagnostic(str(exc))]
    diagnostics = [candidate_diagnostic(item["reason"]) for item in rejections]
    return normalized_set, diagnostics


def validate_candidate_set(
    raw: Any,
    *,
    source_file: Path,
    repo: Path,
    run_dir: Path,
    state: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return _normalize_candidate_set(
        raw,
        source_file=source_file,
        repo=repo,
        run_dir=run_dir,
        state=state,
    )


def validate_validation_object(value: Any, context: str) -> dict[str, Any]:
    obj = require_object(value, context)
    keys = {
        "mode",
        "validator_id",
        "independence_group",
        "verdict",
        "reason",
        "evidence_checked",
        "counterevidence",
        "causality",
        "root_cause_supported",
    }
    require_exact_keys(obj, keys, context)
    mode = require_string(obj["mode"], f"{context}.mode")
    verdict = require_string(obj["verdict"], f"{context}.verdict")
    causality = require_string(obj["causality"], f"{context}.causality")
    if mode not in VALIDATION_MODES:
        raise ReviewError(f"{context}.mode must be one of {sorted(VALIDATION_MODES)}")
    if verdict not in VALIDATION_VERDICTS:
        raise ReviewError(f"{context}.verdict must be one of {sorted(VALIDATION_VERDICTS)}")
    if causality not in CAUSALITIES:
        raise ReviewError(f"{context}.causality must be one of {sorted(CAUSALITIES)}")
    return {
        "mode": mode,
        "validator_id": require_string(obj["validator_id"], f"{context}.validator_id"),
        "independence_group": require_string(obj["independence_group"], f"{context}.independence_group"),
        "verdict": verdict,
        "reason": require_string(obj["reason"], f"{context}.reason"),
        "evidence_checked": require_string_array(obj["evidence_checked"], f"{context}.evidence_checked"),
        "counterevidence": require_string_array(obj["counterevidence"], f"{context}.counterevidence"),
        "causality": causality,
        "root_cause_supported": require_bool(obj["root_cause_supported"], f"{context}.root_cause_supported"),
    }


def validate_materiality_object(value: Any, context: str) -> dict[str, Any]:
    obj = require_object(value, context)
    keys = {
        "concrete_evidence",
        "plausible_negative_consequence",
        "beyond_preference",
        "current_scope_relevance",
        "improvement_current_cost",
        "improvement_benefit_exceeds_churn",
        "coverage_targets_fragile_behavior",
    }
    require_exact_keys(obj, keys, context)
    result: dict[str, Any] = {}
    for key in keys:
        raw = obj[key]
        if key in {
            "improvement_current_cost",
            "improvement_benefit_exceeds_churn",
            "coverage_targets_fragile_behavior",
        }:
            if raw is not None and not isinstance(raw, bool):
                raise ReviewError(f"{context}.{key} must be boolean or null")
            result[key] = raw
        else:
            result[key] = require_bool(raw, f"{context}.{key}")
    return result



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


def validate_repair_audit(
    value: Any,
    context: str,
    *,
    required: bool,
    scope_hash: str,
    candidate_ids: list[str],
    repair_direction: dict[str, Any] | None,
    source_independence_groups: list[str],
    source_candidates: list[dict[str, Any]],
    category: str,
) -> dict[str, Any] | None:
    if value is None:
        if required:
            raise ReviewError(f"{context} is required for a kept finding")
        return None
    if not required:
        raise ReviewError(f"{context} must be null for a discarded finding")
    if repair_direction is None:
        raise ReviewError(f"{context} cannot be validated without a repair direction")

    obj = require_object(value, context)
    keys = {
        "scope_hash",
        "candidate_ids",
        "repair_direction_hash",
        "mode",
        "auditor_id",
        "independence_group",
        "trigger",
        "rationale",
        "evidence_checked",
        "counterevidence",
    }
    require_exact_keys(obj, keys, context)

    audit_scope_hash = require_sha256(obj["scope_hash"], f"{context}.scope_hash")
    if audit_scope_hash != scope_hash:
        raise ReviewError(f"{context}.scope_hash does not match the run")
    audit_candidate_ids = require_string_array(obj["candidate_ids"], f"{context}.candidate_ids")
    if audit_candidate_ids != candidate_ids:
        raise ReviewError(f"{context}.candidate_ids must exactly match the retained group")
    direction_hash = canonical_hash(repair_direction)
    audit_direction_hash = require_sha256(
        obj["repair_direction_hash"],
        f"{context}.repair_direction_hash",
    )
    if audit_direction_hash != direction_hash:
        raise ReviewError(f"{context}.repair_direction_hash does not match the normalized repair direction")

    mode = require_string(obj["mode"], f"{context}.mode")
    if mode not in VALIDATION_MODES:
        raise ReviewError(f"{context}.mode must be one of {sorted(VALIDATION_MODES)}")
    independence_group = require_string(
        obj["independence_group"],
        f"{context}.independence_group",
    )
    if mode == "independent" and independence_group in source_independence_groups:
        raise ReviewError(f"{context}: auditor is not independent from the candidate sources")

    trigger = require_string(obj["trigger"], f"{context}.trigger")
    if mode == "controller_direct":
        sensitive_categories = {"security", "privacy", "api_contract", "migration", "concurrency"}
        affected_paths = {
            path
            for candidate in source_candidates
            for path in [candidate["file"], *candidate["related_changed_files"]]
        }
        eligible = (
            trigger == "mechanically_entailed_low_risk"
            and category not in sensitive_categories
            and all(candidate["estimated_fix_risk"] == "low" for candidate in source_candidates)
            and len(affected_paths) == 1
            and repair_direction["status"] == "reviewed"
            and not repair_direction["open_user_decisions"]
        )
        if not eligible:
            raise ReviewError(
                f"{context}: controller_direct is allowed only for a mechanically entailed low-risk local correction"
            )

    return {
        "scope_hash": audit_scope_hash,
        "candidate_ids": audit_candidate_ids,
        "repair_direction_hash": audit_direction_hash,
        "mode": mode,
        "auditor_id": require_string(obj["auditor_id"], f"{context}.auditor_id"),
        "independence_group": independence_group,
        "trigger": trigger,
        "rationale": require_string(obj["rationale"], f"{context}.rationale"),
        "evidence_checked": require_string_array(
            obj["evidence_checked"],
            f"{context}.evidence_checked",
        ),
        "counterevidence": require_string_array(
            obj["counterevidence"],
            f"{context}.counterevidence",
        ),
    }

def validate_adjudication(raw: Any, *, candidates_bundle: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    obj = require_object(raw, "adjudication")
    top_keys = {
        "schema_version",
        "scope_hash",
        "candidate_bundle_hash",
        "adjudicator_id",
        "groups",
        "verdict",
        "summary",
        "limitations",
    }
    require_exact_keys(obj, top_keys, "adjudication")
    if obj["schema_version"] != ADJUDICATION_SCHEMA:
        raise ReviewError("Unsupported adjudication schema_version")
    if obj["scope_hash"] != state["scope_hash"]:
        raise ReviewError("Adjudication scope_hash does not match the run")
    if obj["candidate_bundle_hash"] != candidates_bundle["candidate_bundle_hash"]:
        raise ReviewError("Adjudication candidate_bundle_hash does not match normalized candidates")
    verdict = require_string(obj["verdict"], "adjudication.verdict")
    if verdict not in MERGE_VERDICTS:
        raise ReviewError(f"adjudication.verdict must be one of {sorted(MERGE_VERDICTS)}")
    candidates_by_id = {item["candidate_id"]: item for item in candidates_bundle["candidates"]}
    groups_raw = require_array(obj["groups"], "adjudication.groups")
    groups: list[dict[str, Any]] = []
    seen_group_ids: set[str] = set()
    seen_candidate_ids: set[str] = set()
    group_keys = {
        "group_id",
        "candidate_ids",
        "canonical_title",
        "nature",
        "category",
        "severity",
        "confidence",
        "file",
        "line_start",
        "line_end",
        "evidence_side",
        "evidence_quote",
        "source_reviewers",
        "source_independence_groups",
        "validation",
        "materiality",
        "disposition",
        "decision_reason",
        "discard_reason_code",
        "recommended_action",
        "required_pre_fix_verification",
        "repair_direction",
        "repair_audit",
    }

    for index, raw_group in enumerate(groups_raw):
        context = f"adjudication.groups[{index}]"
        group = require_object(raw_group, context)
        require_exact_keys(group, group_keys, context)
        group_id = require_string(group["group_id"], f"{context}.group_id")
        if group_id in seen_group_ids:
            raise ReviewError(f"Duplicate adjudication group_id: {group_id}")
        seen_group_ids.add(group_id)
        candidate_ids = require_string_array(group["candidate_ids"], f"{context}.candidate_ids")
        if not candidate_ids:
            raise ReviewError(f"{context}.candidate_ids must not be empty")
        unknown = sorted(set(candidate_ids) - set(candidates_by_id))
        if unknown:
            raise ReviewError(f"{context} references unknown candidate IDs: {', '.join(unknown)}")
        overlap = sorted(set(candidate_ids) & seen_candidate_ids)
        if overlap:
            raise ReviewError(f"Candidate IDs appear in more than one group: {', '.join(overlap)}")
        seen_candidate_ids.update(candidate_ids)
        source_candidates = [candidates_by_id[item] for item in candidate_ids]

        nature = require_string(group["nature"], f"{context}.nature")
        category = require_string(group["category"], f"{context}.category")
        severity = require_string(group["severity"], f"{context}.severity")
        confidence = require_string(group["confidence"], f"{context}.confidence")
        if nature not in NATURES or category not in CATEGORIES or severity not in SEVERITIES or confidence not in CONFIDENCES:
            raise ReviewError(f"{context} contains an invalid nature/category/severity/confidence")
        file = normalize_repo_path(require_string(group["file"], f"{context}.file"))
        line_start = require_int(group["line_start"], f"{context}.line_start", minimum=1)
        line_end = require_int(group["line_end"], f"{context}.line_end", minimum=1)
        if line_end < line_start:
            raise ReviewError(f"{context}.line_end must be >= line_start")
        evidence_side = require_string(group["evidence_side"], f"{context}.evidence_side")
        if evidence_side not in EVIDENCE_SIDES:
            raise ReviewError(f"{context}.evidence_side is invalid")
        evidence_quote = require_string(group["evidence_quote"], f"{context}.evidence_quote")

        if not any(
            candidate["file"] == file
            and candidate["line_start"] == line_start
            and candidate["line_end"] == line_end
            and candidate["evidence_side"] == evidence_side
            and candidate["evidence_quote"] == evidence_quote
            and candidate["nature"] == nature
            and candidate["category"] == category
            for candidate in source_candidates
        ):
            raise ReviewError(f"{context}: canonical evidence/nature/category must be inherited from a source candidate")

        expected_reviewers = sorted({candidate["reviewer_id"] for candidate in source_candidates})
        expected_groups = sorted({candidate["independence_group"] for candidate in source_candidates})
        source_reviewers = sorted(require_string_array(group["source_reviewers"], f"{context}.source_reviewers"))
        source_independence = sorted(
            require_string_array(group["source_independence_groups"], f"{context}.source_independence_groups")
        )
        if source_reviewers != expected_reviewers:
            raise ReviewError(f"{context}.source_reviewers must exactly match candidate sources")
        if source_independence != expected_groups:
            raise ReviewError(f"{context}.source_independence_groups must exactly match candidate sources")

        validation = validate_validation_object(group["validation"], f"{context}.validation")
        if validation["mode"] == "independent" and validation["independence_group"] in expected_groups:
            raise ReviewError(f"{context}: validator is not independent from the candidate sources")
        materiality = validate_materiality_object(group["materiality"], f"{context}.materiality")
        disposition = require_string(group["disposition"], f"{context}.disposition")
        if disposition not in DISPOSITIONS:
            raise ReviewError(f"{context}.disposition must be keep or discard")
        discard_reason = group["discard_reason_code"]
        if discard_reason is not None:
            discard_reason = require_string(discard_reason, f"{context}.discard_reason_code")
            if discard_reason not in DISCARD_REASONS:
                raise ReviewError(f"{context}.discard_reason_code is invalid")
        recommendation = require_string(group["recommended_action"], f"{context}.recommended_action")
        if recommendation not in RECOMMENDATIONS:
            raise ReviewError(f"{context}.recommended_action is invalid")
        required_pre_fix = group["required_pre_fix_verification"]
        if required_pre_fix is not None:
            required_pre_fix = require_string(required_pre_fix, f"{context}.required_pre_fix_verification")
        repair_direction = validate_repair_direction(
            group["repair_direction"],
            f"{context}.repair_direction",
            required=disposition == "keep",
        )
        repair_audit = validate_repair_audit(
            group["repair_audit"],
            f"{context}.repair_audit",
            required=disposition == "keep",
            scope_hash=state["scope_hash"],
            candidate_ids=candidate_ids,
            repair_direction=repair_direction,
            source_independence_groups=source_independence,
            source_candidates=source_candidates,
            category=category,
        )

        if disposition == "keep":
            if discard_reason is not None:
                raise ReviewError(f"{context}: kept group must have null discard_reason_code")
            for key in (
                "concrete_evidence",
                "plausible_negative_consequence",
                "beyond_preference",
                "current_scope_relevance",
            ):
                if materiality[key] is not True:
                    raise ReviewError(f"{context}: kept group failed materiality gate {key}")
            if not validation["root_cause_supported"]:
                raise ReviewError(f"{context}: kept group lacks root-cause support")
            if validation["verdict"] == "rejected":
                raise ReviewError(f"{context}: validator-rejected group cannot be kept")
            if validation["verdict"] == "uncertain":
                if severity not in {"blocker", "high"} or not required_pre_fix:
                    raise ReviewError(
                        f"{context}: uncertain findings may be kept only at blocker/high with required_pre_fix_verification"
                    )
            if validation["causality"] == "pre_existing" and not any(c["direct_dependency"] for c in source_candidates):
                raise ReviewError(f"{context}: unrelated pre-existing group cannot be kept")
            if nature == "improvement":
                if materiality["improvement_current_cost"] is not True:
                    raise ReviewError(f"{context}: improvement lacks demonstrated current cost")
                if materiality["improvement_benefit_exceeds_churn"] is not True:
                    raise ReviewError(f"{context}: improvement benefit does not exceed churn")
            if nature == "coverage_gap" and materiality["coverage_targets_fragile_behavior"] is not True:
                raise ReviewError(f"{context}: coverage gap does not target fragile material behavior")
            if recommendation == "none":
                raise ReviewError(f"{context}: kept group must have an actionable recommendation")
        else:
            if discard_reason is None:
                raise ReviewError(f"{context}: discarded group requires discard_reason_code")

        normalized_group = {
            "group_id": group_id,
            "candidate_ids": candidate_ids,
            "canonical_title": require_string(group["canonical_title"], f"{context}.canonical_title"),
            "nature": nature,
            "category": category,
            "severity": severity,
            "confidence": confidence,
            "file": file,
            "line_start": line_start,
            "line_end": line_end,
            "evidence_side": evidence_side,
            "evidence_quote": evidence_quote,
            "source_reviewers": source_reviewers,
            "source_independence_groups": source_independence,
            "validation": validation,
            "materiality": materiality,
            "disposition": disposition,
            "decision_reason": require_string(group["decision_reason"], f"{context}.decision_reason"),
            "discard_reason_code": discard_reason,
            "recommended_action": recommendation,
            "required_pre_fix_verification": required_pre_fix,
            "repair_direction": repair_direction,
            "repair_direction_hash": canonical_hash(repair_direction) if repair_direction is not None else None,
            "repair_audit": repair_audit,
        }
        groups.append(normalized_group)

    missing = sorted(set(candidates_by_id) - seen_candidate_ids)
    if missing:
        raise ReviewError(f"Adjudication omitted candidate IDs: {', '.join(missing)}")

    kept = [group for group in groups if group["disposition"] == "keep"]
    if not kept and verdict != "READY":
        raise ReviewError("A ledger with no kept findings must use verdict READY")
    if kept and verdict == "READY":
        raise ReviewError("READY is valid only when the ledger has no kept findings")
    if verdict == "READY WITH OPTIONAL FOLLOW-UPS" and (
        any(group["severity"] in {"blocker", "high"} for group in kept)
        or any(group["recommended_action"] == "fix_now" for group in kept)
    ):
        raise ReviewError("READY WITH OPTIONAL FOLLOW-UPS cannot contain blocker/high or fix-now findings")
    if any(group["severity"] == "blocker" for group in kept) and verdict != "NOT READY":
        raise ReviewError("A kept blocker finding requires verdict NOT READY")
    if any(group["severity"] == "high" or group["recommended_action"] == "fix_now" for group in kept):
        if verdict not in {"SHOULD FIX BEFORE MERGE", "NOT READY"}:
            raise ReviewError("High/fix-now findings require SHOULD FIX BEFORE MERGE or NOT READY")

    return {
        "schema_version": ADJUDICATION_SCHEMA,
        "scope_hash": state["scope_hash"],
        "candidate_bundle_hash": candidates_bundle["candidate_bundle_hash"],
        "adjudicator_id": require_string(obj["adjudicator_id"], "adjudication.adjudicator_id"),
        "groups": groups,
        "verdict": verdict,
        "summary": require_string(obj["summary"], "adjudication.summary"),
        "limitations": require_string_array(obj["limitations"], "adjudication.limitations"),
    }


def validate_test_spec(value: Any, context: str, repo: Path) -> dict[str, Any]:
    obj = require_object(value, context)
    keys = {"id", "command", "working_directory", "required", "timeout_seconds", "purpose"}
    require_exact_keys(obj, keys, context)
    working_directory = normalize_repo_path(
        require_string(obj["working_directory"], f"{context}.working_directory", nonempty=False), allow_dot=True
    )
    workdir_path = repo if working_directory == "." else repo_path(repo, working_directory)
    if not workdir_path.exists() or not workdir_path.is_dir():
        raise ReviewError(f"{context}.working_directory does not exist as a directory: {working_directory}")
    test_id = require_string(obj["id"], f"{context}.id")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", test_id):
        raise ReviewError(f"{context}.id must be a safe artifact identifier without slashes or traversal")
    return {
        "id": test_id,
        "command": require_string(obj["command"], f"{context}.command"),
        "working_directory": working_directory,
        "required": require_bool(obj["required"], f"{context}.required"),
        "timeout_seconds": require_int(obj["timeout_seconds"], f"{context}.timeout_seconds", minimum=1, maximum=3600),
        "purpose": require_string(obj["purpose"], f"{context}.purpose"),
    }


def validate_direction_handling(
    value: Any,
    context: str,
    *,
    expected_sources: list[str],
) -> list[dict[str, str]]:
    entries = require_array(value, context)
    normalized: list[dict[str, str]] = []
    sources: list[str] = []
    for index, raw_entry in enumerate(entries):
        entry_context = f"{context}[{index}]"
        entry = require_object(raw_entry, entry_context)
        require_exact_keys(entry, {"source", "handling"}, entry_context)
        source = require_string(entry["source"], f"{entry_context}.source")
        sources.append(source)
        normalized.append(
            {
                "source": source,
                "handling": require_string(entry["handling"], f"{entry_context}.handling"),
            }
        )
    if sources != expected_sources:
        raise ReviewError(f"{context} must cover each approved direction entry exactly and in order")
    return normalized


def validate_repair_direction_assessment(
    value: Any,
    context: str,
    *,
    finding: dict[str, Any],
) -> dict[str, Any]:
    obj = require_object(value, context)
    keys = {
        "repair_direction_hash",
        "constraint_handling",
        "state_or_exception_handling",
        "open_user_decision_handling",
        "alternatives_considered",
        "diverges",
        "divergence_rationale",
    }
    require_exact_keys(obj, keys, context)
    direction = require_object(finding.get("repair_direction"), f"ledger {finding['finding_id']}.repair_direction")
    expected_hash = require_sha256(
        finding.get("repair_direction_hash"),
        f"ledger {finding['finding_id']}.repair_direction_hash",
    )
    if expected_hash != canonical_hash(direction):
        raise ReviewError(f"Ledger direction hash is invalid for {finding['finding_id']}")
    direction_hash = require_sha256(obj["repair_direction_hash"], f"{context}.repair_direction_hash")
    if direction_hash != expected_hash:
        raise ReviewError(f"{context}.repair_direction_hash does not match the approved ledger direction")

    alternatives = require_string_array(
        obj["alternatives_considered"],
        f"{context}.alternatives_considered",
    )
    if not alternatives:
        raise ReviewError(f"{context}.alternatives_considered must not be empty")
    diverges = require_bool(obj["diverges"], f"{context}.diverges")
    rationale = obj["divergence_rationale"]
    if diverges:
        rationale = require_string(rationale, f"{context}.divergence_rationale")
    elif rationale is not None:
        raise ReviewError(f"{context}.divergence_rationale must be null when diverges is false")

    return {
        "repair_direction_hash": direction_hash,
        "constraint_handling": validate_direction_handling(
            obj["constraint_handling"],
            f"{context}.constraint_handling",
            expected_sources=direction["constraints_to_preserve"],
        ),
        "state_or_exception_handling": validate_direction_handling(
            obj["state_or_exception_handling"],
            f"{context}.state_or_exception_handling",
            expected_sources=direction["state_or_exception_cases"],
        ),
        "open_user_decision_handling": validate_direction_handling(
            obj["open_user_decision_handling"],
            f"{context}.open_user_decision_handling",
            expected_sources=direction["open_user_decisions"],
        ),
        "alternatives_considered": alternatives,
        "diverges": diverges,
        "divergence_rationale": rationale,
    }


def validate_fix_plan(
    raw: Any,
    *,
    repo: Path,
    state: dict[str, Any],
    findings_gate: dict[str, Any],
    ledger: dict[str, Any],
) -> dict[str, Any]:
    obj = require_object(raw, "fix plan")
    top_keys = {
        "schema_version",
        "scope_hash",
        "findings_gate_hash",
        "plan_summary",
        "items",
        "global_tests",
        "no_unrelated_cleanup",
        "no_new_improvements_during_fix",
        "post_fix_review_scope",
        "scope_expansion_policy",
        "max_repair_rounds",
    }
    require_exact_keys(obj, top_keys, "fix plan")
    if obj["schema_version"] != FIX_PLAN_SCHEMA:
        raise ReviewError("Unsupported fix-plan schema_version")
    if obj["scope_hash"] != state["scope_hash"]:
        raise ReviewError("Fix plan scope_hash does not match the run")
    if obj["findings_gate_hash"] != findings_gate["receipt_hash"]:
        raise ReviewError("Fix plan findings_gate_hash does not match Gate A")
    if obj["no_unrelated_cleanup"] is not True:
        raise ReviewError("Fix plan must set no_unrelated_cleanup=true")
    if obj["no_new_improvements_during_fix"] is not True:
        raise ReviewError("Fix plan must set no_new_improvements_during_fix=true")
    if obj["post_fix_review_scope"] != "approved_findings_and_fix_introduced_regressions_only":
        raise ReviewError("Fix plan has an invalid post_fix_review_scope")
    if obj["scope_expansion_policy"] != "restore_and_reapprove":
        raise ReviewError("Fix plan must require restore_and_reapprove for scope expansion")
    max_repair_rounds = require_int(obj["max_repair_rounds"], "fix plan.max_repair_rounds", minimum=0, maximum=2)

    approved_ids = set(findings_gate["decisions"]["approved"])
    if not approved_ids:
        raise ReviewError("Gate A approved no findings; no fix plan is permitted")
    items_raw = require_array(obj["items"], "fix plan.items")
    items: list[dict[str, Any]] = []
    item_ids: set[str] = set()
    findings_by_id = {finding["finding_id"]: finding for finding in ledger["findings"]}
    item_keys = {
        "finding_id",
        "root_cause",
        "objective",
        "repair_direction_assessment",
        "depends_on",
        "steps",
        "allowed_paths",
        "tests",
        "manual_verification",
        "rollback_strategy",
        "risk_controls",
        "success_evidence",
        "max_attempts",
    }
    for index, raw_item in enumerate(items_raw):
        context = f"fix plan.items[{index}]"
        item = require_object(raw_item, context)
        require_exact_keys(item, item_keys, context)
        finding_id = require_string(item["finding_id"], f"{context}.finding_id")
        if finding_id in item_ids:
            raise ReviewError(f"Duplicate plan item for {finding_id}")
        item_ids.add(finding_id)
        finding = findings_by_id.get(finding_id)
        if finding is None:
            raise ReviewError(f"{context}.finding_id does not exist in the Gate-A ledger")
        direction_assessment = validate_repair_direction_assessment(
            item["repair_direction_assessment"],
            f"{context}.repair_direction_assessment",
            finding=finding,
        )
        depends_on = require_string_array(item["depends_on"], f"{context}.depends_on")
        if finding_id in depends_on:
            raise ReviewError(f"{context}: finding cannot depend on itself")
        steps = require_string_array(item["steps"], f"{context}.steps", unique=False)
        if not steps:
            raise ReviewError(f"{context}.steps must not be empty")
        allowed_paths = [normalize_repo_path(path) for path in require_string_array(item["allowed_paths"], f"{context}.allowed_paths")]
        if not allowed_paths:
            raise ReviewError(f"{context}.allowed_paths must not be empty")
        for allowed_path in allowed_paths:
            target = repo_path(repo, allowed_path)
            if target.exists() and target.is_dir() and not target.is_symlink():
                raise ReviewError(
                    f"{context}.allowed_paths must name exact files or symlinks, not directories: {allowed_path}"
                )
        tests = [validate_test_spec(value, f"{context}.tests[{test_index}]", repo) for test_index, value in enumerate(require_array(item["tests"], f"{context}.tests"))]
        test_ids = [test["id"] for test in tests]
        if len(test_ids) != len(set(test_ids)):
            raise ReviewError(f"{context}.tests contains duplicate IDs")
        manual_verification = require_string_array(item["manual_verification"], f"{context}.manual_verification")
        if not any(test["required"] for test in tests) and not manual_verification:
            raise ReviewError(f"{context} needs a required automated test or manual verification evidence")
        items.append(
            {
                "finding_id": finding_id,
                "root_cause": require_string(item["root_cause"], f"{context}.root_cause"),
                "objective": require_string(item["objective"], f"{context}.objective"),
                "repair_direction_assessment": direction_assessment,
                "depends_on": depends_on,
                "steps": steps,
                "allowed_paths": allowed_paths,
                "tests": tests,
                "manual_verification": manual_verification,
                "rollback_strategy": require_string(item["rollback_strategy"], f"{context}.rollback_strategy"),
                "risk_controls": require_string_array(item["risk_controls"], f"{context}.risk_controls"),
                "success_evidence": require_string_array(item["success_evidence"], f"{context}.success_evidence"),
                "max_attempts": require_int(item["max_attempts"], f"{context}.max_attempts", minimum=1, maximum=3),
            }
        )

    if item_ids != approved_ids:
        missing = sorted(approved_ids - item_ids)
        extra = sorted(item_ids - approved_ids)
        details: list[str] = []
        if missing:
            details.append(f"missing approved IDs {', '.join(missing)}")
        if extra:
            details.append(f"contains unapproved IDs {', '.join(extra)}")
        raise ReviewError("Fix plan item set is not exact: " + "; ".join(details))
    for item in items:
        invalid_dependencies = sorted(set(item["depends_on"]) - approved_ids)
        if invalid_dependencies:
            raise ReviewError(
                f"Plan item {item['finding_id']} depends on unapproved IDs: {', '.join(invalid_dependencies)}"
            )

    graph = {item["finding_id"]: set(item["depends_on"]) for item in items}
    temporary: set[str] = set()
    permanent: set[str] = set()

    def visit(node: str) -> None:
        if node in permanent:
            return
        if node in temporary:
            raise ReviewError("Fix plan dependency graph contains a cycle")
        temporary.add(node)
        for dependency in graph[node]:
            visit(dependency)
        temporary.remove(node)
        permanent.add(node)

    for node in graph:
        visit(node)

    global_tests = [
        validate_test_spec(value, f"fix plan.global_tests[{index}]", repo)
        for index, value in enumerate(require_array(obj["global_tests"], "fix plan.global_tests"))
    ]
    global_ids = [test["id"] for test in global_tests]
    if len(global_ids) != len(set(global_ids)):
        raise ReviewError("fix plan.global_tests contains duplicate IDs")

    return {
        "schema_version": FIX_PLAN_SCHEMA,
        "scope_hash": state["scope_hash"],
        "findings_gate_hash": findings_gate["receipt_hash"],
        "plan_summary": require_string(obj["plan_summary"], "fix plan.plan_summary"),
        "items": items,
        "global_tests": global_tests,
        "no_unrelated_cleanup": True,
        "no_new_improvements_during_fix": True,
        "post_fix_review_scope": "approved_findings_and_fix_introduced_regressions_only",
        "scope_expansion_policy": "restore_and_reapprove",
        "max_repair_rounds": max_repair_rounds,
    }


def render_candidates_markdown(bundle: dict[str, Any], rejections: list[dict[str, Any]]) -> str:
    lines = [
        "# Candidate ingestion",
        "",
        f"- Scope hash: `{bundle['scope_hash']}`",
        f"- Candidate bundle hash: `{bundle['candidate_bundle_hash']}`",
        f"- Reviewer sets accepted: `{len(bundle['reviewer_sets'])}`",
        f"- Candidates accepted: `{len(bundle['candidates'])}`",
        f"- Candidate/input rejections: `{len(rejections)}`",
        "",
        "## Accepted candidates",
        "",
    ]
    if not bundle["candidates"]:
        lines.append("- none")
    for candidate in bundle["candidates"]:
        evidence_suffix = (
            f", evidence handling `{candidate['evidence_handling']}`"
            if candidate.get("evidence_handling") not in {None, "standard"}
            else ""
        )
        lines.append(
            f"- **{candidate['candidate_id']}** [{candidate['severity']}/{candidate['confidence']}] "
            f"`{candidate['file']}:{candidate['line_start']}` — {candidate['title']} "
            f"(reviewer `{candidate['reviewer_id']}`, group `{candidate['independence_group']}`"
            f"{evidence_suffix})"
        )
    lines.extend(["", "## Rejected reviewer output", ""])
    if not rejections:
        lines.append("- none")
    for item in rejections:
        location = f" index {item['index']}" if "index" in item else ""
        lines.append(f"- `{item['source_file']}`{location}: {item['reason']}")
    return "\n".join(lines) + "\n"


def representative_candidate(group: dict[str, Any], candidates_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    for candidate_id in group["candidate_ids"]:
        candidate = candidates_by_id[candidate_id]
        if (
            candidate["file"] == group["file"]
            and candidate["line_start"] == group["line_start"]
            and candidate["evidence_quote"] == group["evidence_quote"]
        ):
            return candidate
    return candidates_by_id[group["candidate_ids"][0]]


def render_ledger_markdown(ledger: dict[str, Any]) -> str:
    lines = [
        "# Material review ledger",
        "",
        "## Merge-readiness decision",
        "",
        ledger["verdict"],
        "",
        "## Frozen scope",
        "",
        f"- Scope hash: `{ledger['scope_hash']}`",
        f"- Candidate bundle hash: `{ledger['candidate_bundle_hash']}`",
        f"- Ledger hash: `{ledger['ledger_hash']}`",
        "",
        "## Summary",
        "",
        ledger["summary"],
        "",
        "## Kept material findings",
        "",
        "Gate A approves findings for repair planning only. It does not approve the provisional repair direction or authorize edits.",
        "",
    ]
    if not ledger["findings"]:
        lines.append("No material findings survived adjudication.")
    for finding in ledger["findings"]:
        lines.extend(
            [
                f"### {finding['finding_id']} — {finding['title']}",
                "",
                f"- Category / nature: `{finding['category']}` / `{finding['nature']}`",
                f"- Severity / confidence: `{finding['severity']}` / `{finding['confidence']}`",
                f"- Evidence: `{finding['file']}:{finding['line_start']}-{finding['line_end']}` "
                f"({finding['evidence_side']}) — `{finding['evidence_quote']}`",
                f"- Consequence: {finding['observable_consequence']}",
                f"- Trigger: {finding['trigger_conditions']}",
                f"- Validation: `{finding['validation']['mode']}` / `{finding['validation']['verdict']}` — "
                f"{finding['validation']['reason']}",
                f"- Why material: {finding['decision_reason']}",
                f"- Fix risk: `{finding['estimated_fix_risk']}`",
                f"- Recommendation: `{finding['recommended_action']}`",
                f"- Candidate sources: {', '.join(finding['candidate_ids'])}",
            ]
        )
        direction = finding["repair_direction"]
        lines.extend(
            [
                "- Provisional repair direction:",
                f"  - Direction hash: `{finding['repair_direction_hash']}`",
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
            if direction[key]:
                lines.append(f"  - {label}:")
                lines.extend(f"    - {value}" for value in direction[key])
        audit = finding["repair_audit"]
        lines.extend(
            [
                "- Repair-direction audit:",
                f"  - Mode / auditor / independence group: `{audit['mode']}` / "
                f"`{audit['auditor_id']}` / `{audit['independence_group']}`",
                f"  - Trigger: `{audit['trigger']}`",
                f"  - Rationale: {audit['rationale']}",
            ]
        )
        if audit["evidence_checked"]:
            lines.append("  - Evidence checked:")
            lines.extend(f"    - {value}" for value in audit["evidence_checked"])
        if audit["counterevidence"]:
            lines.append("  - Counterevidence:")
            lines.extend(f"    - {value}" for value in audit["counterevidence"])
        if finding["required_pre_fix_verification"]:
            lines.append(f"- Required pre-fix verification: {finding['required_pre_fix_verification']}")
        lines.append("")
    lines.extend(["## Discarded candidates", ""])
    if not ledger["discarded"]:
        lines.append("- none")
    for group in ledger["discarded"]:
        lines.append(
            f"- **{group['group_id']}** ({', '.join(group['candidate_ids'])}) — {group['canonical_title']} "
            f"-> `{group['discard_reason_code']}`: {group['decision_reason']}"
        )
    if ledger["limitations"]:
        lines.extend(["", "## Coverage limitations", ""])
        lines.extend(f"- {item}" for item in ledger["limitations"])
    return "\n".join(lines) + "\n"


def render_plan_markdown(plan: dict[str, Any]) -> str:
    lines = [
        "# Gate-B repair plan",
        "",
        f"- Scope hash: `{plan['scope_hash']}`",
        f"- Findings gate hash: `{plan['findings_gate_hash']}`",
        f"- Plan hash: `{plan['plan_hash']}`",
        f"- Max repair rounds: `{plan['max_repair_rounds']}`",
        "",
        "## Summary",
        "",
        plan["plan_summary"],
        "",
        "## Finding plans",
        "",
    ]
    for item in plan["items"]:
        lines.extend(
            [
                f"### {item['finding_id']}",
                "",
                f"- Root cause: {item['root_cause']}",
                f"- Objective: {item['objective']}",
                f"- Approved direction hash: `{item['repair_direction_assessment']['repair_direction_hash']}`",
                f"- Dependencies: {', '.join(item['depends_on']) if item['depends_on'] else 'none'}",
                f"- Allowed paths: {', '.join(f'`{path}`' for path in item['allowed_paths'])}",
                f"- Max attempts: `{item['max_attempts']}`",
            ]
        )
        assessment = item["repair_direction_assessment"]
        lines.append("- Repair-direction assessment:")
        handling_fields = (
            ("Constraints", "constraint_handling"),
            ("States and exceptions", "state_or_exception_handling"),
            ("Open user decisions", "open_user_decision_handling"),
        )
        for label, key in handling_fields:
            lines.append(f"  - {label}:")
            if not assessment[key]:
                lines.append("    - none")
            for entry in assessment[key]:
                lines.append(f"    - {entry['source']} -> {entry['handling']}")
        lines.append("  - Alternatives considered:")
        lines.extend(f"    - {entry}" for entry in assessment["alternatives_considered"])
        lines.append(f"  - Diverges from approved direction: `{str(assessment['diverges']).lower()}`")
        if assessment["divergence_rationale"]:
            lines.append(f"  - Divergence rationale: {assessment['divergence_rationale']}")
        lines.append("- Steps:")
        lines.extend(f"  {index}. {step}" for index, step in enumerate(item["steps"], start=1))
        lines.append("- Tests:")
        if not item["tests"]:
            lines.append("  - none")
        for test in item["tests"]:
            lines.append(
                f"  - `{test['id']}` ({'required' if test['required'] else 'optional'}, {test['timeout_seconds']}s) "
                f"from `{test['working_directory']}`: `{test['command']}` — {test['purpose']}"
            )
        if item["manual_verification"]:
            lines.append("- Manual verification:")
            lines.extend(f"  - {entry}" for entry in item["manual_verification"])
        lines.append(f"- Rollback: {item['rollback_strategy']}")
        if item["risk_controls"]:
            lines.append("- Risk controls:")
            lines.extend(f"  - {entry}" for entry in item["risk_controls"])
        lines.append("")
    lines.extend(["## Global tests", ""])
    if not plan["global_tests"]:
        lines.append("- none")
    for test in plan["global_tests"]:
        lines.append(
            f"- `{test['id']}` ({'required' if test['required'] else 'optional'}, {test['timeout_seconds']}s) "
            f"from `{test['working_directory']}`: `{test['command']}` — {test['purpose']}"
        )
    lines.extend(
        [
            "",
            "## Loop and scope controls",
            "",
            "- Unrelated cleanup: prohibited",
            "- New improvements during repair: prohibited",
            "- Post-fix review: approved findings and fix-introduced regressions only",
            "- Scope expansion: restore and obtain a new Gate B approval",
        ]
    )
    return "\n".join(lines) + "\n"


def command_init(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    artifact_root = resolve_artifact_root(repo, args.artifact_root)
    run_id = normalize_run_id(args.run_id) if args.run_id else make_run_id()
    runs_root = artifact_root / "runs"
    run_dir = runs_root / run_id
    if run_dir.exists():
        raise ReviewError(f"Run already exists: {run_dir}")

    # Freeze the Git scope before creating any artifact directory. This avoids
    # contaminating the scope when a caller supplies an invalid in-worktree
    # location and leaves no half-initialized run when scope resolution fails.
    review_object = normalize_review_object(
        kind=args.review_object_kind,
        identifier=args.review_object_id,
        base_sha=args.review_base_sha,
        head_sha=args.review_head_sha,
        requested_scope=args.scope,
    )
    scope = build_scope(
        repo,
        requested_scope=args.scope,
        base_ref=args.base,
        head_ref=args.head,
        include_untracked=not args.exclude_untracked,
        review_object=review_object,
    )
    runs_root.mkdir(parents=True, exist_ok=True)
    temp_run_dir = runs_root / f".{run_id}.initializing-{uuid.uuid4().hex[:8]}"
    temp_run_dir.mkdir(parents=False, exist_ok=False)
    try:
        limitations = snapshot_sources(
            repo,
            temp_run_dir,
            scope,
            max_file_bytes=args.max_snapshot_file_bytes,
            max_total_bytes=args.max_snapshot_total_bytes,
        )
        write_source_bundle_files(temp_run_dir, scope, limitations)
        identity = scope["identity"]
        state = {
            "schema_version": STATE_SCHEMA,
            "tool_version": TOOL_VERSION,
            "run_id": run_id,
            "repo_root": str(repo),
            "artifact_root": str(artifact_root),
            "phase": PHASE_CONTEXT,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "scope_hash": scope["scope_hash"],
            "scope_params": {
                "actual_scope": identity["actual_scope"],
                "base_reference": identity["base_reference"],
                "head_reference": identity.get("head_reference"),
                "include_untracked": identity["include_untracked"],
                "review_object": identity.get("review_object"),
            },
            "workflow_profile": args.workflow_profile,
            "coverage_required": True,
            "candidate_preflight": {},
            "mutation_allowed": identity["mutable"],
            "hashes": {},
            "gates": {},
            "approved_findings": [],
            "finding_status": {},
            "global_test_results": {},
            "final_test_refresh_results": {},
            "pre_verification_recovery_history": [],
            "active_finding": None,
            "repair_round": 0,
            "repair_targets": [],
            "expected_workspace_guard_hash": None,
            "pre_fix_checkpoint": None,
            "events": [
                {
                    "at": utc_now(),
                    "event": "scope_frozen",
                    "scope_hash": scope["scope_hash"],
                }
            ],
        }
        save_state(temp_run_dir, state)
        os.replace(temp_run_dir, run_dir)
    except Exception:
        shutil.rmtree(temp_run_dir, ignore_errors=True)
        raise

    print(f"[OK] Frozen review scope: {scope['scope_hash']}")
    print(f"Run ID: {run_id}")
    print(f"Artifact directory: {run_dir}")
    print(f"Mode: {identity['actual_scope']}")
    print(f"Changed files: {len(identity['files'])}")
    print(f"Mutation aligned: {str(identity['mutable']).lower()}")
    return 0

def command_check_scope(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    current = check_scope_fresh(repo, run_dir, state)
    print(f"[OK] Scope is fresh: {current['scope_hash']}")
    print(f"Run ID: {state['run_id']}")
    return 0


def command_record_coverage(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_CONTEXT:
        raise ReviewError(f"Cannot record coverage in phase {state['phase']}")
    check_scope_fresh(repo, run_dir, state)
    if state.get("hashes", {}).get("coverage_plan_hash"):
        raise ReviewError("A coverage plan is already recorded for this run")
    source = Path(args.input).expanduser().resolve()
    plan = validate_coverage_plan(load_json(source), state)
    plan_hash = canonical_hash(plan)
    atomic_write_json(run_dir / "coverage-plan.json", plan)
    state["hashes"]["coverage_plan_hash"] = plan_hash
    state["events"].append(
        {
            "at": utc_now(),
            "event": "coverage_plan_recorded",
            "coverage_plan_hash": plan_hash,
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Coverage plan recorded: {plan_hash}")
    return 0


def load_verified_coverage_plan(
    run_dir: Path, state: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    plan = validate_coverage_plan(load_json(run_dir / "coverage-plan.json"), state)
    plan_hash = canonical_hash(plan)
    require_state_hash(state, "coverage_plan_hash", plan_hash, "coverage plan")
    return plan, plan_hash


def load_fallback_assignments(
    run_dir: Path,
    state: dict[str, Any],
    coverage_plan: dict[str, Any],
    coverage_plan_hash: str,
) -> dict[str, dict[str, Any]]:
    plan_lenses = {item["lens_id"]: item for item in coverage_plan["lenses"]}
    raw_state = require_object(
        state.get("fallback_assignments", {}), "state.fallback_assignments"
    )
    assignments: dict[str, dict[str, Any]] = {}
    for lens_id, raw_record in raw_state.items():
        require_control_id(lens_id, "state.fallback_assignments lens ID")
        if lens_id not in plan_lenses:
            raise ReviewError(f"Fallback assignment references unplanned lens {lens_id}")
        lens = plan_lenses[lens_id]
        if not lens["required"] or lens["fallback"] != "sequential_degraded_self_audit":
            raise ReviewError(f"Fallback assignment is not permitted for lens {lens_id}")
        record = require_object(
            raw_record, f"state.fallback_assignments.{lens_id}"
        )
        require_exact_keys(
            record,
            {"path", "assignment_hash"},
            f"state.fallback_assignments.{lens_id}",
        )
        relative_path = require_string(
            record["path"], f"state.fallback_assignments.{lens_id}.path"
        )
        if relative_path != f"fallback-assignments/{lens_id}.json":
            raise ReviewError(
                f"Fallback assignment path does not match lens {lens_id}"
            )
        assignment = require_object(
            load_json(run_dir / relative_path), f"fallback assignment {relative_path}"
        )
        require_exact_keys(
            assignment,
            {
                "schema_version",
                "scope_hash",
                "coverage_plan_hash",
                "workflow_profile",
                "lens_id",
                "route",
                "failure_trigger_kind",
                "failure_trigger_hash",
                "reviewer_id",
                "independence_group",
                "review_mode",
                "degraded",
                "assignment_hash",
            },
            f"fallback assignment {relative_path}",
        )
        if assignment["schema_version"] != FALLBACK_ASSIGNMENT_SCHEMA:
            raise ReviewError(f"Unsupported fallback assignment schema in {relative_path}")
        if require_sha256(
            assignment["scope_hash"], f"{relative_path}.scope_hash"
        ) != state["scope_hash"]:
            raise ReviewError("Fallback assignment has a stale scope hash")
        if require_sha256(
            assignment["coverage_plan_hash"], f"{relative_path}.coverage_plan_hash"
        ) != coverage_plan_hash:
            raise ReviewError("Fallback assignment has a stale coverage-plan hash")
        if require_string(
            assignment["workflow_profile"], f"{relative_path}.workflow_profile"
        ) != coverage_plan["workflow_profile"]:
            raise ReviewError("Fallback assignment has a stale workflow profile")
        if require_control_id(
            assignment["lens_id"], f"{relative_path}.lens_id"
        ) != lens_id:
            raise ReviewError("Fallback assignment lens does not match its state key")
        if require_string(assignment["route"], f"{relative_path}.route") != "fallback":
            raise ReviewError("Fallback assignment route must be fallback")
        trigger_kind = require_string(
            assignment["failure_trigger_kind"],
            f"{relative_path}.failure_trigger_kind",
        )
        if trigger_kind not in FALLBACK_TRIGGER_KINDS:
            raise ReviewError(f"{relative_path}.failure_trigger_kind is invalid")
        require_sha256(
            assignment["failure_trigger_hash"],
            f"{relative_path}.failure_trigger_hash",
        )
        require_control_id(assignment["reviewer_id"], f"{relative_path}.reviewer_id")
        require_string(
            assignment["independence_group"], f"{relative_path}.independence_group"
        )
        review_mode = require_string(
            assignment["review_mode"], f"{relative_path}.review_mode"
        )
        if review_mode not in REVIEW_MODES:
            raise ReviewError(f"{relative_path}.review_mode is invalid")
        if require_bool(assignment["degraded"], f"{relative_path}.degraded") is not True:
            raise ReviewError("Fallback assignments must be marked degraded")
        assignment_hash = verify_embedded_hash(
            assignment,
            hash_field="assignment_hash",
            context=f"fallback assignment {relative_path}",
        )
        if assignment_hash != require_sha256(
            record["assignment_hash"],
            f"state.fallback_assignments.{lens_id}.assignment_hash",
        ):
            raise ReviewError("Fallback assignment does not match its state hash")
        assignments[lens_id] = assignment
    return assignments


def primary_candidate_route_failed(receipts: list[dict[str, Any]]) -> bool:
    if not receipts or any(item["verdict"] == "valid" for item in receipts):
        return False
    latest = max(receipts, key=lambda item: item["attempt"])
    return latest["verdict"] == "rejected" or latest["attempt"] == 2


def load_candidate_preflight_receipt(
    run_dir: Path, record: dict[str, Any]
) -> dict[str, Any]:
    require_exact_keys(record, {"path", "receipt_hash"}, "candidate preflight state record")
    relative_path = require_string(record.get("path"), "candidate preflight state path")
    path_match = re.fullmatch(
        r"candidate-preflight/([A-Za-z0-9][A-Za-z0-9._-]{0,127})/"
        r"(primary|fallback)/attempt-([12])\.json",
        relative_path,
    )
    if path_match is None:
        raise ReviewError("Candidate preflight state path is invalid")
    receipt = require_object(
        load_json(run_dir / relative_path), f"candidate preflight receipt {relative_path}"
    )
    final_v1_fields = {
        "route",
        "independence_group",
        "review_mode",
        "fallback_assignment_hash",
        "degraded",
        "evidence_handling",
    }
    if not final_v1_fields.issubset(receipt) or "fallback" in receipt:
        raise provisional_v1_restart("candidate-preflight receipt")
    require_exact_keys(
        receipt,
        {
            "schema_version",
            "scope_hash",
            "coverage_plan_hash",
            "lens_id",
            "route",
            "attempt",
            "draft_hash",
            "semantic_hash",
            "supersedes_receipt_hash",
            "verdict",
            "diagnostics",
            "reviewer_id",
            "independence_group",
            "review_mode",
            "fallback_assignment_hash",
            "degraded",
            "evidence_handling",
            "source_file",
            "receipt_hash",
        },
        f"candidate preflight receipt {relative_path}",
    )
    if receipt["schema_version"] != CANDIDATE_PREFLIGHT_SCHEMA:
        raise ReviewError(f"Unsupported candidate preflight schema in {relative_path}")
    require_sha256(receipt["scope_hash"], f"{relative_path}.scope_hash")
    require_sha256(receipt["coverage_plan_hash"], f"{relative_path}.coverage_plan_hash")
    lens_id = require_control_id(receipt["lens_id"], f"{relative_path}.lens_id")
    route = require_string(receipt["route"], f"{relative_path}.route")
    if route not in PREFLIGHT_ROUTES:
        raise ReviewError(f"{relative_path}.route is invalid")
    attempt = require_int(receipt["attempt"], f"{relative_path}.attempt", minimum=1, maximum=2)
    if route == "fallback" and attempt != 1:
        raise ReviewError("Fallback candidate preflight permits only route-local attempt 1")
    if relative_path != f"candidate-preflight/{lens_id}/{route}/attempt-{attempt}.json":
        raise ReviewError(
            "Candidate preflight receipt path does not match its lens, route, and attempt"
        )
    require_sha256(receipt["draft_hash"], f"{relative_path}.draft_hash")
    for field in ("semantic_hash", "supersedes_receipt_hash"):
        if receipt[field] is not None:
            require_sha256(receipt[field], f"{relative_path}.{field}")
    verdict = require_string(receipt["verdict"], f"{relative_path}.verdict")
    if verdict not in {"valid", "correctable", "rejected"}:
        raise ReviewError(f"{relative_path}.verdict is invalid")
    diagnostics = require_array(receipt["diagnostics"], f"{relative_path}.diagnostics")
    for index, raw_diagnostic in enumerate(diagnostics):
        context = f"{relative_path}.diagnostics[{index}]"
        diagnostic = require_object(raw_diagnostic, context)
        require_exact_keys(diagnostic, {"code", "path", "message", "correctable"}, context)
        require_string(diagnostic["code"], f"{context}.code")
        require_string(diagnostic["path"], f"{context}.path")
        require_string(diagnostic["message"], f"{context}.message")
        require_bool(diagnostic["correctable"], f"{context}.correctable")
    if verdict == "valid" and diagnostics:
        raise ReviewError(f"{relative_path}: valid receipt may not contain diagnostics")
    if verdict != "valid" and not diagnostics:
        raise ReviewError(f"{relative_path}: non-valid receipt requires diagnostics")
    require_control_id(receipt["reviewer_id"], f"{relative_path}.reviewer_id")
    require_string(receipt["independence_group"], f"{relative_path}.independence_group")
    review_mode = require_string(receipt["review_mode"], f"{relative_path}.review_mode")
    if review_mode not in REVIEW_MODES:
        raise ReviewError(f"{relative_path}.review_mode is invalid")
    if receipt["fallback_assignment_hash"] is not None:
        require_sha256(
            receipt["fallback_assignment_hash"],
            f"{relative_path}.fallback_assignment_hash",
        )
    require_bool(receipt["degraded"], f"{relative_path}.degraded")
    evidence_handling = require_string(
        receipt["evidence_handling"], f"{relative_path}.evidence_handling"
    )
    if evidence_handling not in EVIDENCE_HANDLING_VALUES:
        raise ReviewError(f"{relative_path}.evidence_handling is invalid")
    require_string(receipt["source_file"], f"{relative_path}.source_file")
    receipt_hash = verify_embedded_hash(
        receipt,
        hash_field="receipt_hash",
        context=f"candidate preflight receipt {relative_path}",
    )
    expected_hash = require_sha256(
        record.get("receipt_hash"), "candidate preflight state receipt_hash"
    )
    if receipt_hash != expected_hash:
        raise ReviewError("Candidate preflight receipt does not match its state hash")
    return receipt


def load_all_candidate_preflight_receipts(
    run_dir: Path,
    state: dict[str, Any],
    coverage_plan: dict[str, Any],
    coverage_plan_hash: str,
    *,
    fallback_assignments: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    plan_lenses = {item["lens_id"]: item for item in coverage_plan["lenses"]}
    if fallback_assignments is None:
        fallback_assignments = load_fallback_assignments(
            run_dir, state, coverage_plan, coverage_plan_hash
        )
    raw_state = require_object(state.get("candidate_preflight", {}), "state.candidate_preflight")
    receipts: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for lens_id, raw_routes in raw_state.items():
        require_control_id(lens_id, "state.candidate_preflight lens ID")
        if lens_id not in plan_lenses:
            raise ReviewError(f"Candidate preflight state references unplanned lens {lens_id}")
        routes = require_object(
            raw_routes, f"state.candidate_preflight.{lens_id} routes"
        )
        require_exact_keys(
            routes,
            PREFLIGHT_ROUTES,
            f"state.candidate_preflight.{lens_id} routes",
        )
        plan_lens = plan_lenses[lens_id]
        for route in ("primary", "fallback"):
            records = require_array(
                routes[route], f"state.candidate_preflight.{lens_id}.{route}"
            )
            route_limit = 2 if route == "primary" else 1
            if len(records) > route_limit:
                raise ReviewError(
                    f"Candidate preflight {route} route attempt limit exceeded for lens {lens_id}"
                )
            route_receipts: list[dict[str, Any]] = []
            for index, raw_record in enumerate(records, start=1):
                record = require_object(
                    raw_record,
                    f"state.candidate_preflight.{lens_id}.{route} record",
                )
                receipt = load_candidate_preflight_receipt(run_dir, record)
                if receipt["lens_id"] != lens_id or receipt["route"] != route:
                    raise ReviewError(
                        "Candidate preflight receipt lens or route does not match state"
                    )
                if receipt["attempt"] != index:
                    raise ReviewError(
                        "Candidate preflight route attempts are not contiguous"
                    )
                if receipt["scope_hash"] != state["scope_hash"]:
                    raise ReviewError("Candidate preflight receipt has a stale scope hash")
                if receipt["coverage_plan_hash"] != coverage_plan_hash:
                    raise ReviewError("Candidate preflight receipt has a stale coverage-plan hash")
                if route == "primary":
                    expected_identity = plan_lens
                    if receipt["fallback_assignment_hash"] is not None:
                        raise ReviewError(
                            "Primary candidate preflight may not reference a fallback assignment"
                        )
                    if receipt["degraded"]:
                        raise ReviewError("Primary candidate preflight may not be degraded")
                else:
                    assignment = fallback_assignments.get(lens_id)
                    if assignment is None:
                        raise ReviewError(
                            f"Candidate preflight fallback lacks a root-owned assignment for lens {lens_id}"
                        )
                    expected_identity = assignment
                    if receipt["fallback_assignment_hash"] != assignment["assignment_hash"]:
                        raise ReviewError(
                            "Candidate preflight fallback assignment hash does not match state"
                        )
                    if not receipt["degraded"]:
                        raise ReviewError("Fallback candidate preflight must be degraded")
                for field in ("reviewer_id", "independence_group", "review_mode"):
                    if receipt[field] != expected_identity[field]:
                        raise ReviewError(
                            f"Candidate preflight {field} does not match its active assignment"
                        )
                expected_evidence_handling = (
                    "unparseable_origin_degraded"
                    if route == "primary"
                    and index == 2
                    and route_receipts[0]["semantic_hash"] is None
                    else "standard"
                )
                if receipt["evidence_handling"] != expected_evidence_handling:
                    raise ReviewError(
                        "Candidate preflight evidence handling does not match its "
                        f"controller-derived origin for lens {lens_id}"
                    )
                if receipt["receipt_hash"] in seen_hashes:
                    raise ReviewError(
                        "Candidate preflight state contains a duplicate receipt hash"
                    )
                seen_hashes.add(receipt["receipt_hash"])
                route_receipts.append(receipt)
                receipts.append(receipt)
            if route == "primary" and route_receipts:
                if route_receipts[0]["supersedes_receipt_hash"] is not None:
                    raise ReviewError("Primary attempt 1 may not supersede a receipt")
                if len(route_receipts) == 2 and route_receipts[1][
                    "supersedes_receipt_hash"
                ] != route_receipts[0]["receipt_hash"]:
                    raise ReviewError(
                        "Primary attempt 2 must supersede primary attempt 1"
                    )
            if route == "fallback" and route_receipts and route_receipts[0][
                "supersedes_receipt_hash"
            ] is not None:
                raise ReviewError("Fallback route may not supersede a primary receipt")
        primary = [item for item in receipts if item["lens_id"] == lens_id and item["route"] == "primary"]
        fallback = [item for item in receipts if item["lens_id"] == lens_id and item["route"] == "fallback"]
        if fallback:
            assignment = fallback_assignments.get(lens_id)
            if assignment is None:
                raise ReviewError(
                    f"Fallback route for lens {lens_id} lacks an assignment"
                )
            if assignment["failure_trigger_kind"] == "candidate_preflight_receipt" and (
                not primary or any(item["verdict"] == "valid" for item in primary)
            ):
                raise ReviewError(
                    f"Fallback route for lens {lens_id} requires a primary route with no valid receipt"
                )
    for lens_id, assignment in fallback_assignments.items():
        primary = [
            item
            for item in receipts
            if item["lens_id"] == lens_id and item["route"] == "primary"
        ]
        if assignment["failure_trigger_kind"] == "candidate_preflight_receipt":
            if not primary_candidate_route_failed(primary):
                raise ReviewError(
                    f"Fallback assignment for lens {lens_id} requires a failed primary route"
                )
            latest_primary = max(primary, key=lambda item: item["attempt"])
            if assignment["failure_trigger_hash"] != latest_primary["receipt_hash"]:
                raise ReviewError(
                    f"Fallback assignment for lens {lens_id} does not bind the latest primary receipt"
                )
    return receipts


def load_reviewer_failure_attestations(
    run_dir: Path,
    state: dict[str, Any],
    coverage_plan: dict[str, Any],
    coverage_plan_hash: str,
    fallback_assignments: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    plan_lenses = {item["lens_id"]: item for item in coverage_plan["lenses"]}
    raw_state = require_object(
        state.get("reviewer_failure_attestations", {}),
        "state.reviewer_failure_attestations",
    )
    attestations: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for lens_id, raw_routes in raw_state.items():
        require_control_id(lens_id, "state.reviewer_failure_attestations lens ID")
        if lens_id not in plan_lenses:
            raise ReviewError(f"Reviewer failure references unplanned lens {lens_id}")
        plan_lens = plan_lenses[lens_id]
        if not plan_lens["required"]:
            raise ReviewError(f"Reviewer failure is not permitted for lens {lens_id}")
        routes = require_object(
            raw_routes, f"state.reviewer_failure_attestations.{lens_id} routes"
        )
        require_exact_keys(
            routes,
            PREFLIGHT_ROUTES,
            f"state.reviewer_failure_attestations.{lens_id} routes",
        )
        for route in ("primary", "fallback"):
            raw_record = routes[route]
            if raw_record is None:
                continue
            if (
                route == "fallback"
                and plan_lens["fallback"] != "sequential_degraded_self_audit"
            ):
                raise ReviewError(
                    f"Reviewer failure fallback is not permitted for lens {lens_id}"
                )
            record = require_object(
                raw_record,
                f"state.reviewer_failure_attestations.{lens_id}.{route}",
            )
            require_exact_keys(
                record,
                {"path", "attestation_hash"},
                f"state.reviewer_failure_attestations.{lens_id}.{route}",
            )
            relative_path = require_string(
                record["path"],
                f"state.reviewer_failure_attestations.{lens_id}.{route}.path",
            )
            expected_path = f"reviewer-failure-attestations/{lens_id}/{route}.json"
            if relative_path != expected_path:
                raise ReviewError(
                    "Reviewer-failure attestation path does not match its lens and route"
                )
            attestation = require_object(
                load_json(run_dir / relative_path),
                f"reviewer-failure attestation {relative_path}",
            )
            require_exact_keys(
                attestation,
                {
                    "schema_version",
                    "scope_hash",
                    "coverage_plan_hash",
                    "workflow_profile",
                    "lens_id",
                    "route",
                    "assignment_kind",
                    "assignment_hash",
                    "reviewer_id",
                    "independence_group",
                    "review_mode",
                    "reason",
                    "diagnostics",
                    "observer_kind",
                    "observer_id",
                    "no_readable_draft",
                    "observed_at",
                    "attestation_hash",
                },
                f"reviewer-failure attestation {relative_path}",
            )
            if attestation["schema_version"] != REVIEWER_FAILURE_ATTESTATION_SCHEMA:
                raise ReviewError(
                    f"Unsupported reviewer-failure attestation schema in {relative_path}"
                )
            if require_sha256(
                attestation["scope_hash"], f"{relative_path}.scope_hash"
            ) != state["scope_hash"]:
                raise ReviewError("Reviewer-failure attestation has a stale scope hash")
            if require_sha256(
                attestation["coverage_plan_hash"],
                f"{relative_path}.coverage_plan_hash",
            ) != coverage_plan_hash:
                raise ReviewError(
                    "Reviewer-failure attestation has a stale coverage-plan hash"
                )
            if require_string(
                attestation["workflow_profile"], f"{relative_path}.workflow_profile"
            ) != coverage_plan["workflow_profile"]:
                raise ReviewError("Reviewer-failure attestation has a stale workflow profile")
            if require_control_id(
                attestation["lens_id"], f"{relative_path}.lens_id"
            ) != lens_id:
                raise ReviewError("Reviewer-failure attestation lens does not match state")
            if require_string(attestation["route"], f"{relative_path}.route") != route:
                raise ReviewError("Reviewer-failure attestation route does not match state")
            if route == "primary":
                expected_assignment_kind = "coverage_plan"
                expected_assignment_hash = coverage_plan_hash
                expected_identity = plan_lens
            else:
                assignment = fallback_assignments.get(lens_id)
                if assignment is None:
                    raise ReviewError(
                        f"Fallback reviewer failure lacks an assignment for lens {lens_id}"
                    )
                expected_assignment_kind = "fallback_assignment"
                expected_assignment_hash = assignment["assignment_hash"]
                expected_identity = assignment
            if require_string(
                attestation["assignment_kind"], f"{relative_path}.assignment_kind"
            ) != expected_assignment_kind:
                raise ReviewError("Reviewer-failure attestation assignment kind is stale")
            if require_sha256(
                attestation["assignment_hash"], f"{relative_path}.assignment_hash"
            ) != expected_assignment_hash:
                raise ReviewError("Reviewer-failure attestation assignment hash is stale")
            for field in ("reviewer_id", "independence_group", "review_mode"):
                value = require_string(attestation[field], f"{relative_path}.{field}")
                if value != expected_identity[field]:
                    raise ReviewError(
                        f"Reviewer-failure attestation {field} differs from its assignment"
                    )
            if attestation["review_mode"] not in REVIEW_MODES:
                raise ReviewError(f"{relative_path}.review_mode is invalid")
            reason = require_string(attestation["reason"], f"{relative_path}.reason")
            if reason not in REVIEWER_FAILURE_REASONS:
                raise ReviewError(f"{relative_path}.reason is invalid")
            diagnostics = require_array(
                attestation["diagnostics"], f"{relative_path}.diagnostics"
            )
            if len(diagnostics) > MAX_FAILURE_DIAGNOSTICS:
                raise ReviewError("Reviewer-failure attestation has too many diagnostics")
            seen_diagnostic_codes: set[str] = set()
            for index, raw_diagnostic in enumerate(diagnostics):
                context = f"{relative_path}.diagnostics[{index}]"
                diagnostic = require_object(raw_diagnostic, context)
                require_exact_keys(diagnostic, {"code", "value"}, context)
                code = require_string(diagnostic["code"], f"{context}.code")
                if code not in FAILURE_DIAGNOSTIC_CODES:
                    raise ReviewError(f"{context}.code is invalid")
                if code in seen_diagnostic_codes:
                    raise ReviewError(
                        f"Reviewer-failure attestation duplicates diagnostic code {code}"
                    )
                seen_diagnostic_codes.add(code)
                minimum, maximum = FAILURE_DIAGNOSTIC_BOUNDS[code]
                require_int(
                    diagnostic["value"],
                    f"{context}.value",
                    minimum=minimum,
                    maximum=maximum,
                )
            observer_kind = require_string(
                attestation["observer_kind"], f"{relative_path}.observer_kind"
            )
            if observer_kind not in FAILURE_OBSERVER_KINDS:
                raise ReviewError(f"{relative_path}.observer_kind is invalid")
            require_control_id(attestation["observer_id"], f"{relative_path}.observer_id")
            if require_bool(
                attestation["no_readable_draft"], f"{relative_path}.no_readable_draft"
            ) is not True:
                raise ReviewError("Reviewer-failure attestation must confirm no readable draft")
            observed_at = require_string(
                attestation["observed_at"], f"{relative_path}.observed_at"
            )
            try:
                datetime.strptime(observed_at, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError as exc:
                raise ReviewError(f"{relative_path}.observed_at is invalid") from exc
            attestation_hash = verify_embedded_hash(
                attestation,
                hash_field="attestation_hash",
                context=f"reviewer-failure attestation {relative_path}",
            )
            if attestation_hash != require_sha256(
                record["attestation_hash"],
                f"state.reviewer_failure_attestations.{lens_id}.{route}.attestation_hash",
            ):
                raise ReviewError("Reviewer-failure attestation does not match state")
            if attestation_hash in seen_hashes:
                raise ReviewError("Reviewer-failure state contains a duplicate hash")
            seen_hashes.add(attestation_hash)
            attestations.append(attestation)
    return attestations


def load_review_evidence(
    run_dir: Path,
    state: dict[str, Any],
    coverage_plan: dict[str, Any],
    coverage_plan_hash: str,
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
]:
    fallback_assignments = load_fallback_assignments(
        run_dir, state, coverage_plan, coverage_plan_hash
    )
    receipts = load_all_candidate_preflight_receipts(
        run_dir,
        state,
        coverage_plan,
        coverage_plan_hash,
        fallback_assignments=fallback_assignments,
    )
    attestations = load_reviewer_failure_attestations(
        run_dir,
        state,
        coverage_plan,
        coverage_plan_hash,
        fallback_assignments,
    )
    receipt_routes = {(item["lens_id"], item["route"]) for item in receipts}
    attestation_routes = {(item["lens_id"], item["route"]) for item in attestations}
    overlap = sorted(receipt_routes & attestation_routes)
    if overlap:
        raise ReviewError(
            "A review route may contain candidate receipts or a no-output attestation, not both: "
            + ", ".join(f"{lens}/{route}" for lens, route in overlap)
        )
    for lens_id, assignment in fallback_assignments.items():
        if assignment["failure_trigger_kind"] != "reviewer_failure_attestation":
            continue
        primary_attestations = [
            item
            for item in attestations
            if item["lens_id"] == lens_id and item["route"] == "primary"
        ]
        if len(primary_attestations) != 1:
            raise ReviewError(
                f"Fallback assignment for lens {lens_id} requires one primary failure attestation"
            )
        if assignment["failure_trigger_hash"] != primary_attestations[0]["attestation_hash"]:
            raise ReviewError(
                f"Fallback assignment for lens {lens_id} does not bind its primary attestation"
            )
    return receipts, fallback_assignments, attestations


def latest_candidate_preflight_receipts(
    receipts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for receipt in receipts:
        key = (receipt["lens_id"], receipt["route"])
        if key not in latest or receipt["attempt"] > latest[key]["attempt"]:
            latest[key] = receipt
    return list(latest.values())


def build_coverage_status(
    *,
    state: dict[str, Any],
    coverage_plan: dict[str, Any],
    receipts: list[dict[str, Any]],
    fallback_assignments: dict[str, dict[str, Any]],
    attestations: list[dict[str, Any]],
) -> dict[str, Any]:
    lens_results: list[dict[str, Any]] = []
    limitations: list[str] = []
    for lens in coverage_plan["lenses"]:
        matching = [item for item in receipts if item["lens_id"] == lens["lens_id"]]
        primary = max(
            (item for item in matching if item["route"] == "primary"),
            key=lambda item: item["attempt"],
            default=None,
        )
        fallback = max(
            (item for item in matching if item["route"] == "fallback"),
            key=lambda item: item["attempt"],
            default=None,
        )
        primary_attestation = next(
            (
                item
                for item in attestations
                if item["lens_id"] == lens["lens_id"] and item["route"] == "primary"
            ),
            None,
        )
        fallback_attestation = next(
            (
                item
                for item in attestations
                if item["lens_id"] == lens["lens_id"] and item["route"] == "fallback"
            ),
            None,
        )
        completion_route = next(
            (
                route
                for route, item in (("primary", primary), ("fallback", fallback))
                if item is not None and item["verdict"] == "valid"
            ),
            None,
        )
        completed = completion_route is not None
        assignment = fallback_assignments.get(lens["lens_id"])
        active_identity = assignment or lens
        if not completed:
            availability = "required" if lens["required"] else "optional"
            limitations.append(
                f"{lens['lens_id']}: {availability} review evidence is unavailable"
            )
        evidence_handling = (
            "unparseable_origin_degraded"
            if any(
                item["evidence_handling"] == "unparseable_origin_degraded"
                for item in matching
            )
            else "standard"
        )
        if evidence_handling == "unparseable_origin_degraded":
            limitations.append(
                f"{lens['lens_id']}: primary evidence handling originated from an "
                "unparseable draft and was syntax-corrected by the same reviewer"
            )
        lens_results.append(
            {
                "lens_id": lens["lens_id"],
                "required": lens["required"],
                "completed": completed,
                "completion_route": completion_route,
                "primary_receipt_hash": primary["receipt_hash"] if primary else None,
                "fallback_receipt_hash": fallback["receipt_hash"] if fallback else None,
                "primary_attestation_hash": (
                    primary_attestation["attestation_hash"]
                    if primary_attestation
                    else None
                ),
                "fallback_attestation_hash": (
                    fallback_attestation["attestation_hash"]
                    if fallback_attestation
                    else None
                ),
                "fallback_assignment_hash": (
                    assignment["assignment_hash"] if assignment else None
                ),
                "fallback_trigger_kind": (
                    assignment["failure_trigger_kind"] if assignment else None
                ),
                "fallback_trigger_hash": (
                    assignment["failure_trigger_hash"] if assignment else None
                ),
                "degraded": assignment is not None,
                "evidence_handling": evidence_handling,
                "reviewer_id": active_identity["reviewer_id"],
                "independence_group": active_identity["independence_group"],
                "review_mode": active_identity["review_mode"],
                "diagnostics": [
                    diagnostic["code"]
                    for item in matching
                    for diagnostic in item["diagnostics"]
                ]
                + [
                    value
                    for attestation in (primary_attestation, fallback_attestation)
                    if attestation is not None
                    for value in (
                        attestation["reason"],
                        *(item["code"] for item in attestation["diagnostics"]),
                    )
                ],
            }
        )
    complete = all(item["completed"] for item in lens_results if item["required"])
    payload = {
        "schema_version": COVERAGE_STATUS_SCHEMA,
        "scope_hash": state["scope_hash"],
        "coverage_plan_hash": state["hashes"]["coverage_plan_hash"],
        "workflow_profile": coverage_plan["workflow_profile"],
        "status": "complete" if complete else "incomplete",
        "lenses": lens_results,
        "limitations": limitations,
    }
    payload["coverage_status_hash"] = canonical_hash(payload)
    return payload


def require_exhausted_incomplete_required_routes(
    *,
    coverage_plan: dict[str, Any],
    coverage_status: dict[str, Any],
    receipts: list[dict[str, Any]],
    fallback_assignments: dict[str, dict[str, Any]],
    attestations: list[dict[str, Any]],
) -> None:
    latest_receipts = latest_candidate_preflight_receipts(receipts)
    attestation_routes = {
        (item["lens_id"], item["route"]): item for item in attestations
    }
    status_lenses = {item["lens_id"]: item for item in coverage_status["lenses"]}
    for lens in coverage_plan["lenses"]:
        status_lens = status_lenses[lens["lens_id"]]
        if not lens["required"] or status_lens["completed"]:
            continue
        lens_receipts = [
            item for item in latest_receipts if item["lens_id"] == lens["lens_id"]
        ]
        if any(item["verdict"] == "valid" for item in lens_receipts):
            raise ReviewError(
                f"Required lens {lens['lens_id']} has valid candidate bytes that must be ingested"
            )
        primary_failed = primary_candidate_route_failed(
            [item for item in lens_receipts if item["route"] == "primary"]
        ) or ((lens["lens_id"], "primary") in attestation_routes)
        if not primary_failed:
            raise ReviewError(
                f"Required lens {lens['lens_id']} has no terminal primary evidence"
            )
        if lens["fallback"] == "none":
            continue
        if lens["lens_id"] not in fallback_assignments:
            raise ReviewError(
                f"Required lens {lens['lens_id']} still has unused fallback authority"
            )
        fallback_receipt = next(
            (item for item in lens_receipts if item["route"] == "fallback"),
            None,
        )
        fallback_failed = (
            fallback_receipt is not None and fallback_receipt["verdict"] != "valid"
        ) or ((lens["lens_id"], "fallback") in attestation_routes)
        if not fallback_failed:
            raise ReviewError(
                f"Required lens {lens['lens_id']} fallback route is not exhausted"
            )


def validate_coverage_status(
    raw: Any,
    *,
    state: dict[str, Any],
    coverage_plan: dict[str, Any],
    receipts: list[dict[str, Any]],
    fallback_assignments: dict[str, dict[str, Any]],
    attestations: list[dict[str, Any]],
) -> dict[str, Any]:
    status = require_object(raw, "coverage status")
    if any(
        not {
            "primary_attestation_hash",
            "fallback_attestation_hash",
            "fallback_assignment_hash",
            "fallback_trigger_kind",
            "fallback_trigger_hash",
            "degraded",
            "evidence_handling",
        }.issubset(item)
        for item in status.get("lenses", [])
        if isinstance(item, dict)
    ):
        raise provisional_v1_restart("coverage status")
    require_exact_keys(
        status,
        {
            "schema_version",
            "scope_hash",
            "coverage_plan_hash",
            "workflow_profile",
            "status",
            "lenses",
            "limitations",
            "coverage_status_hash",
        },
        "coverage status",
    )
    if status["schema_version"] != COVERAGE_STATUS_SCHEMA:
        raise ReviewError("Unsupported coverage-status schema_version")
    if require_sha256(status["scope_hash"], "coverage status.scope_hash") != state["scope_hash"]:
        raise ReviewError("Coverage status has a stale scope hash")
    if require_sha256(
        status["coverage_plan_hash"], "coverage status.coverage_plan_hash"
    ) != state["hashes"]["coverage_plan_hash"]:
        raise ReviewError("Coverage status has a stale coverage-plan hash")
    workflow_profile = require_string(
        status["workflow_profile"], "coverage status.workflow_profile"
    )
    if workflow_profile != coverage_plan["workflow_profile"]:
        raise ReviewError("Coverage status workflow profile differs from the coverage plan")
    status_value = require_string(status["status"], "coverage status.status")
    if status_value not in {"complete", "incomplete"}:
        raise ReviewError("coverage status.status must be complete or incomplete")
    plan_lenses = {item["lens_id"]: item for item in coverage_plan["lenses"]}
    seen_lenses: set[str] = set()
    completed_required = True
    for index, raw_lens in enumerate(require_array(status["lenses"], "coverage status.lenses")):
        context = f"coverage status.lenses[{index}]"
        lens = require_object(raw_lens, context)
        require_exact_keys(
            lens,
            {
                "lens_id",
                "required",
                "completed",
                "completion_route",
                "primary_receipt_hash",
                "fallback_receipt_hash",
                "primary_attestation_hash",
                "fallback_attestation_hash",
                "fallback_assignment_hash",
                "fallback_trigger_kind",
                "fallback_trigger_hash",
                "degraded",
                "evidence_handling",
                "reviewer_id",
                "independence_group",
                "review_mode",
                "diagnostics",
            },
            context,
        )
        lens_id = require_control_id(lens["lens_id"], f"{context}.lens_id")
        if lens_id in seen_lenses or lens_id not in plan_lenses:
            raise ReviewError(f"Coverage status has duplicate or unplanned lens {lens_id}")
        seen_lenses.add(lens_id)
        planned = plan_lenses[lens_id]
        required = require_bool(lens["required"], f"{context}.required")
        completed = require_bool(lens["completed"], f"{context}.completed")
        completion_route = lens["completion_route"]
        if completion_route is not None:
            completion_route = require_string(
                completion_route, f"{context}.completion_route"
            )
            if completion_route not in PREFLIGHT_ROUTES:
                raise ReviewError(f"{context}.completion_route is invalid")
        if completed != (completion_route is not None):
            raise ReviewError(
                f"Coverage status completion route disagrees for lens {lens_id}"
            )
        if required != planned["required"]:
            raise ReviewError(f"Coverage status required flag differs for lens {lens_id}")
        for field in (
            "primary_receipt_hash",
            "fallback_receipt_hash",
            "primary_attestation_hash",
            "fallback_attestation_hash",
        ):
            if lens[field] is not None:
                require_sha256(lens[field], f"{context}.{field}")
        expected_primary_attestation = next(
            (
                item["attestation_hash"]
                for item in attestations
                if item["lens_id"] == lens_id and item["route"] == "primary"
            ),
            None,
        )
        expected_fallback_attestation = next(
            (
                item["attestation_hash"]
                for item in attestations
                if item["lens_id"] == lens_id and item["route"] == "fallback"
            ),
            None,
        )
        if lens["primary_attestation_hash"] != expected_primary_attestation:
            raise ReviewError(
                f"Coverage status primary attestation differs for lens {lens_id}"
            )
        if lens["fallback_attestation_hash"] != expected_fallback_attestation:
            raise ReviewError(
                f"Coverage status fallback attestation differs for lens {lens_id}"
            )
        if completion_route == "primary" and lens["primary_receipt_hash"] is None:
            raise ReviewError(
                f"Coverage status primary completion lacks a receipt for lens {lens_id}"
            )
        if completion_route == "fallback" and lens["fallback_receipt_hash"] is None:
            raise ReviewError(
                f"Coverage status fallback completion lacks a receipt for lens {lens_id}"
            )
        assignment = fallback_assignments.get(lens_id)
        expected_identity = assignment or planned
        for field in (
            "fallback_assignment_hash",
            "fallback_trigger_kind",
            "fallback_trigger_hash",
        ):
            if lens[field] is not None:
                if field.endswith("_hash"):
                    require_sha256(lens[field], f"{context}.{field}")
                else:
                    require_string(lens[field], f"{context}.{field}")
        if assignment is None:
            if any(
                lens[field] is not None
                for field in (
                    "fallback_assignment_hash",
                    "fallback_trigger_kind",
                    "fallback_trigger_hash",
                )
            ):
                raise ReviewError(
                    f"Coverage status references an unassigned fallback for lens {lens_id}"
                )
        else:
            expected_fallback = {
                "fallback_assignment_hash": assignment["assignment_hash"],
                "fallback_trigger_kind": assignment["failure_trigger_kind"],
                "fallback_trigger_hash": assignment["failure_trigger_hash"],
            }
            for field, expected in expected_fallback.items():
                if lens[field] != expected:
                    raise ReviewError(
                        f"Coverage status {field} differs for lens {lens_id}"
                    )
            trigger_field = (
                "primary_receipt_hash"
                if assignment["failure_trigger_kind"] == "candidate_preflight_receipt"
                else "primary_attestation_hash"
            )
            if lens[trigger_field] != assignment["failure_trigger_hash"]:
                raise ReviewError(
                    f"Coverage status does not expose the failed primary trigger for lens {lens_id}"
                )
        if require_bool(lens["degraded"], f"{context}.degraded") != (assignment is not None):
            raise ReviewError(f"Coverage status degraded marker differs for lens {lens_id}")
        evidence_handling = require_string(
            lens["evidence_handling"], f"{context}.evidence_handling"
        )
        if evidence_handling not in EVIDENCE_HANDLING_VALUES:
            raise ReviewError(f"{context}.evidence_handling is invalid")
        expected_evidence_handling = (
            "unparseable_origin_degraded"
            if any(
                item["lens_id"] == lens_id
                and item["evidence_handling"] == "unparseable_origin_degraded"
                for item in receipts
            )
            else "standard"
        )
        if evidence_handling != expected_evidence_handling:
            raise ReviewError(
                f"Coverage status evidence handling differs for lens {lens_id}"
            )
        if completion_route == "fallback" and assignment is None:
            raise ReviewError(
                f"Coverage status fallback completion lacks an assignment for lens {lens_id}"
            )
        for field in ("reviewer_id", "independence_group", "review_mode"):
            if require_string(lens[field], f"{context}.{field}") != expected_identity[field]:
                raise ReviewError(f"Coverage status {field} differs for lens {lens_id}")
        require_string_array(lens["diagnostics"], f"{context}.diagnostics", unique=False)
        if required and not completed:
            completed_required = False
    if seen_lenses != set(plan_lenses):
        raise ReviewError("Coverage status does not account for every planned lens")
    expected_status = "complete" if completed_required else "incomplete"
    if status_value != expected_status:
        raise ReviewError("Coverage status summary disagrees with required lens completion")
    require_string_array(status["limitations"], "coverage status.limitations", unique=False)
    require_sha256(status["coverage_status_hash"], "coverage status.coverage_status_hash")
    return status


def load_verified_coverage_status(
    run_dir: Path, state: dict[str, Any], coverage_plan: dict[str, Any]
) -> dict[str, Any]:
    raw = require_object(load_json(run_dir / "coverage-status.json"), "coverage status")
    status_hash = verify_embedded_hash(
        raw, hash_field="coverage_status_hash", context="coverage status"
    )
    coverage_plan_hash = require_sha256(
        state["hashes"]["coverage_plan_hash"], "state coverage-plan hash"
    )
    receipts, fallback_assignments, attestations = load_review_evidence(
        run_dir, state, coverage_plan, coverage_plan_hash
    )
    status = validate_coverage_status(
        raw,
        state=state,
        coverage_plan=coverage_plan,
        receipts=receipts,
        fallback_assignments=fallback_assignments,
        attestations=attestations,
    )
    require_state_hash(state, "coverage_status_hash", status_hash, "coverage status")
    return status


def parse_failure_diagnostics(values: list[str]) -> list[dict[str, Any]]:
    if len(values) > MAX_FAILURE_DIAGNOSTICS:
        raise ReviewError(
            f"Reviewer failure permits at most {MAX_FAILURE_DIAGNOSTICS} diagnostics"
        )
    diagnostics: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for index, raw in enumerate(values):
        if "=" not in raw:
            raise ReviewError(
                f"Reviewer failure diagnostic {index + 1} must use controlled CODE=INTEGER form"
            )
        code, raw_value = raw.split("=", 1)
        if code not in FAILURE_DIAGNOSTIC_CODES:
            raise ReviewError(
                f"Reviewer failure diagnostic code must be one of {sorted(FAILURE_DIAGNOSTIC_CODES)}"
            )
        if code in seen_codes:
            raise ReviewError(f"Reviewer failure diagnostic code is duplicated: {code}")
        seen_codes.add(code)
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise ReviewError(
                f"Reviewer failure diagnostic {code} must contain an integer"
            ) from exc
        minimum, maximum = FAILURE_DIAGNOSTIC_BOUNDS[code]
        require_int(
            value,
            f"reviewer failure diagnostic {code}",
            minimum=minimum,
            maximum=maximum,
        )
        diagnostics.append({"code": code, "value": value})
    return diagnostics


def command_record_reviewer_failure(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    with exclusive_run_state_lock(run_dir):
        state = load_state(run_dir)
        if state["phase"] != PHASE_CONTEXT:
            raise ReviewError(
                f"Cannot record reviewer failure in phase {state['phase']}"
            )
        check_scope_fresh(repo, run_dir, state)
        coverage_plan, coverage_plan_hash = load_verified_coverage_plan(run_dir, state)
        lens = next(
            (item for item in coverage_plan["lenses"] if item["lens_id"] == args.lens),
            None,
        )
        if lens is None:
            raise ReviewError(f"Lens is not assigned by the coverage plan: {args.lens}")
        if not lens["required"]:
            raise ReviewError(
                f"Lens {args.lens} does not permit reviewer-failure evidence"
            )
        if (
            args.route == "fallback"
            and lens["fallback"] != "sequential_degraded_self_audit"
        ):
            raise ReviewError(
                f"Lens {args.lens} does not permit reviewer-failure fallback evidence"
            )
        receipts, assignments, attestations = load_review_evidence(
            run_dir, state, coverage_plan, coverage_plan_hash
        )
        route_receipts = [
            item
            for item in receipts
            if item["lens_id"] == args.lens and item["route"] == args.route
        ]
        route_attestations = [
            item
            for item in attestations
            if item["lens_id"] == args.lens and item["route"] == args.route
        ]
        if route_receipts:
            raise ReviewError(
                f"Lens {args.lens} {args.route} route has readable candidate receipt evidence"
            )
        if route_attestations:
            raise ReviewError(
                f"Lens {args.lens} {args.route} failure is already attested"
            )
        if args.route == "primary":
            if args.lens in assignments:
                raise ReviewError(
                    f"Lens {args.lens} primary route is closed by its fallback assignment"
                )
            assignment_kind = "coverage_plan"
            assignment_hash = coverage_plan_hash
            active_identity = lens
        else:
            assignment = assignments.get(args.lens)
            if assignment is None:
                raise ReviewError(
                    f"Lens {args.lens} fallback failure requires a fallback assignment"
                )
            assignment_kind = "fallback_assignment"
            assignment_hash = assignment["assignment_hash"]
            active_identity = assignment
        diagnostics = parse_failure_diagnostics(args.diagnostic)
        reason = require_string(args.reason, "reviewer failure reason")
        if reason not in REVIEWER_FAILURE_REASONS:
            raise ReviewError(
                f"reviewer failure reason must be one of {sorted(REVIEWER_FAILURE_REASONS)}"
            )
        observer_kind = require_string(args.observer_kind, "reviewer failure observer kind")
        if observer_kind not in FAILURE_OBSERVER_KINDS:
            raise ReviewError(
                f"reviewer failure observer kind must be one of {sorted(FAILURE_OBSERVER_KINDS)}"
            )
        observer_id = require_control_id(args.observer_id, "reviewer failure observer ID")
        attestation = {
            "schema_version": REVIEWER_FAILURE_ATTESTATION_SCHEMA,
            "scope_hash": state["scope_hash"],
            "coverage_plan_hash": coverage_plan_hash,
            "workflow_profile": coverage_plan["workflow_profile"],
            "lens_id": args.lens,
            "route": args.route,
            "assignment_kind": assignment_kind,
            "assignment_hash": assignment_hash,
            "reviewer_id": active_identity["reviewer_id"],
            "independence_group": active_identity["independence_group"],
            "review_mode": active_identity["review_mode"],
            "reason": reason,
            "diagnostics": diagnostics,
            "observer_kind": observer_kind,
            "observer_id": observer_id,
            "no_readable_draft": True,
            "observed_at": utc_now(),
        }
        attestation_hash = canonical_hash(attestation)
        attestation["attestation_hash"] = attestation_hash
        relative_path = (
            f"reviewer-failure-attestations/{args.lens}/{args.route}.json"
        )
        atomic_write_json(run_dir / relative_path, attestation)
        failure_state = state.setdefault("reviewer_failure_attestations", {})
        if args.lens not in failure_state:
            failure_state[args.lens] = {"primary": None, "fallback": None}
        routes = require_object(
            failure_state[args.lens],
            f"state.reviewer_failure_attestations.{args.lens} routes",
        )
        require_exact_keys(
            routes,
            PREFLIGHT_ROUTES,
            f"state.reviewer_failure_attestations.{args.lens} routes",
        )
        routes[args.route] = {
            "path": relative_path,
            "attestation_hash": attestation_hash,
        }
        state["events"].append(
            {
                "at": utc_now(),
                "event": "reviewer_failure_attested",
                "lens_id": args.lens,
                "route": args.route,
                "reason": reason,
                "observer_kind": observer_kind,
                "observer_id": observer_id,
                "attestation_hash": attestation_hash,
            }
        )
        save_state(run_dir, state)
        print(f"[OK] Reviewer failure attested: {attestation_hash}")
        print(f"Artifact: {run_dir / relative_path}")
        return 0


def command_assign_fallback(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    with exclusive_run_state_lock(run_dir):
        state = load_state(run_dir)
        if state["phase"] != PHASE_CONTEXT:
            raise ReviewError(f"Cannot assign a fallback in phase {state['phase']}")
        check_scope_fresh(repo, run_dir, state)
        coverage_plan, coverage_plan_hash = load_verified_coverage_plan(run_dir, state)
        lens = next(
            (item for item in coverage_plan["lenses"] if item["lens_id"] == args.lens),
            None,
        )
        if lens is None:
            raise ReviewError(f"Lens is not assigned by the coverage plan: {args.lens}")
        if not lens["required"] or lens["fallback"] != "sequential_degraded_self_audit":
            raise ReviewError(f"Lens {args.lens} does not permit a required-lens fallback")
        all_receipts, assignments, attestations = load_review_evidence(
            run_dir, state, coverage_plan, coverage_plan_hash
        )
        if args.lens in assignments:
            raise ReviewError(f"Lens {args.lens} already has a fallback assignment")
        primary = [
            item
            for item in all_receipts
            if item["lens_id"] == args.lens and item["route"] == "primary"
        ]
        fallback = [
            item
            for item in all_receipts
            if item["lens_id"] == args.lens and item["route"] == "fallback"
        ]
        if fallback:
            raise ReviewError(
                f"Lens {args.lens} cannot be assigned after a fallback preflight"
            )
        trigger_hash = require_sha256(
            args.failure_trigger_hash, "fallback assignment failure trigger hash"
        )
        if args.failure_trigger_kind == "candidate_preflight_receipt":
            if not primary_candidate_route_failed(primary):
                raise ReviewError(
                    f"Lens {args.lens} fallback assignment requires a failed primary route"
                )
            latest_primary = max(primary, key=lambda item: item["attempt"])
            if trigger_hash != latest_primary["receipt_hash"]:
                raise ReviewError(
                    "Fallback assignment must bind the exact latest failed primary receipt"
                )
        else:
            primary_attestations = [
                item
                for item in attestations
                if item["lens_id"] == args.lens and item["route"] == "primary"
            ]
            if len(primary_attestations) != 1:
                raise ReviewError(
                    "Fallback assignment requires one verified primary failure attestation"
                )
            if trigger_hash != primary_attestations[0]["attestation_hash"]:
                raise ReviewError(
                    "Fallback assignment must bind the exact primary failure attestation"
                )
        reviewer_id = require_control_id(args.reviewer_id, "fallback reviewer_id")
        independence_group = require_string(
            args.independence_group, "fallback independence_group"
        )
        review_mode = require_string(args.review_mode, "fallback review_mode")
        if review_mode not in REVIEW_MODES:
            raise ReviewError(f"fallback review_mode must be one of {sorted(REVIEW_MODES)}")

        assignment = {
            "schema_version": FALLBACK_ASSIGNMENT_SCHEMA,
            "scope_hash": state["scope_hash"],
            "coverage_plan_hash": coverage_plan_hash,
            "workflow_profile": coverage_plan["workflow_profile"],
            "lens_id": args.lens,
            "route": "fallback",
            "failure_trigger_kind": args.failure_trigger_kind,
            "failure_trigger_hash": trigger_hash,
            "reviewer_id": reviewer_id,
            "independence_group": independence_group,
            "review_mode": review_mode,
            "degraded": True,
        }
        assignment_hash = canonical_hash(assignment)
        assignment["assignment_hash"] = assignment_hash
        relative_path = f"fallback-assignments/{args.lens}.json"
        atomic_write_json(run_dir / relative_path, assignment)
        fallback_state = state.setdefault("fallback_assignments", {})
        fallback_state[args.lens] = {
            "path": relative_path,
            "assignment_hash": assignment_hash,
        }
        state["events"].append(
            {
                "at": utc_now(),
                "event": "fallback_assigned",
                "lens_id": args.lens,
                "failure_trigger_kind": args.failure_trigger_kind,
                "failure_trigger_hash": trigger_hash,
                "reviewer_id": reviewer_id,
                "independence_group": independence_group,
                "review_mode": review_mode,
                "assignment_hash": assignment_hash,
            }
        )
        save_state(run_dir, state)
        print(f"[OK] Fallback assignment recorded: {assignment_hash}")
        print(f"Artifact: {run_dir / relative_path}")
        return 0


def command_check_candidates(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    with exclusive_run_state_lock(run_dir):
        return command_check_candidates_locked(args, repo=repo, run_dir=run_dir)


def command_check_candidates_locked(
    args: argparse.Namespace, *, repo: Path, run_dir: Path
) -> int:
    state = load_state(run_dir)
    if state["phase"] != PHASE_CONTEXT:
        raise ReviewError(f"Cannot preflight candidates in phase {state['phase']}")
    check_scope_fresh(repo, run_dir, state)
    coverage_plan, coverage_plan_hash = load_verified_coverage_plan(run_dir, state)
    lens = next(
        (item for item in coverage_plan["lenses"] if item["lens_id"] == args.lens),
        None,
    )
    if lens is None:
        raise ReviewError(f"Lens is not assigned by the coverage plan: {args.lens}")

    preflight_state = state.setdefault("candidate_preflight", {})
    if args.lens not in preflight_state:
        preflight_state[args.lens] = {"primary": [], "fallback": []}
    routes = require_object(
        preflight_state[args.lens],
        f"state.candidate_preflight.{args.lens} routes; restart provisional v1 runs",
    )
    require_exact_keys(
        routes,
        PREFLIGHT_ROUTES,
        f"state.candidate_preflight.{args.lens} routes; restart provisional v1 runs",
    )
    primary_records = require_array(
        routes["primary"], f"state.candidate_preflight.{args.lens}.primary"
    )
    fallback_records = require_array(
        routes["fallback"], f"state.candidate_preflight.{args.lens}.fallback"
    )
    all_receipts, fallback_assignments, attestations = load_review_evidence(
        run_dir, state, coverage_plan, coverage_plan_hash
    )
    primary_receipts = [
        item
        for item in all_receipts
        if item["lens_id"] == args.lens and item["route"] == "primary"
    ]
    fallback_receipts = [
        item
        for item in all_receipts
        if item["lens_id"] == args.lens and item["route"] == "fallback"
    ]
    primary_attestation = next(
        (
            item
            for item in attestations
            if item["lens_id"] == args.lens and item["route"] == "primary"
        ),
        None,
    )
    fallback_attestation = next(
        (
            item
            for item in attestations
            if item["lens_id"] == args.lens and item["route"] == "fallback"
        ),
        None,
    )
    route = "fallback" if args.fallback else "primary"
    records = fallback_records if args.fallback else primary_records

    previous: dict[str, Any] | None = None
    if args.fallback:
        if not lens["required"] or lens["fallback"] != "sequential_degraded_self_audit":
            raise ReviewError(f"Lens {args.lens} does not permit a required-lens fallback")
        assignment = fallback_assignments.get(args.lens)
        if assignment is None:
            raise ReviewError(
                f"Lens {args.lens} fallback requires a root-owned fallback assignment"
            )
        if fallback_receipts:
            raise ReviewError(f"Lens {args.lens} already has a fallback preflight")
        if fallback_attestation is not None:
            raise ReviewError(f"Lens {args.lens} fallback route is already attested unavailable")
        if assignment["failure_trigger_kind"] == "candidate_preflight_receipt":
            if not primary_candidate_route_failed(primary_receipts):
                raise ReviewError(
                    f"Lens {args.lens} fallback requires a failed primary route"
                )
        elif primary_attestation is None:
            raise ReviewError(
                f"Lens {args.lens} fallback requires its primary failure attestation"
            )
        if args.supersedes:
            raise ReviewError("A fallback is a separate review and may not supersede a primary receipt")
        active_identity = assignment
    elif primary_receipts:
        if args.lens in fallback_assignments:
            raise ReviewError(f"Lens {args.lens} cannot resume primary review after fallback assignment")
        if len(primary_receipts) >= 2:
            raise ReviewError(
                f"Candidate preflight primary-route attempt limit reached for lens {args.lens}"
            )
        if fallback_receipts:
            raise ReviewError(f"Lens {args.lens} cannot resume primary review after fallback")
        previous = primary_receipts[-1]
        if previous["verdict"] != "correctable":
            raise ReviewError(
                f"Lens {args.lens} has no correctable primary receipt to supersede"
            )
        if args.supersedes != previous["receipt_hash"]:
            raise ReviewError("Second candidate attempt must supersede the exact prior receipt hash")
    elif args.supersedes:
        raise ReviewError("First candidate attempt may not supersede another receipt")
    else:
        if primary_attestation is not None:
            raise ReviewError(
                f"Lens {args.lens} primary route is already attested unavailable"
            )
        if args.lens in fallback_assignments:
            raise ReviewError(f"Lens {args.lens} cannot start primary review after fallback assignment")
    if not args.fallback:
        active_identity = lens

    source = Path(args.input).expanduser().resolve()
    try:
        draft_bytes = source.read_bytes()
    except FileNotFoundError as exc:
        raise ReviewError(f"File not found: {source}") from exc
    draft_hash = sha256_bytes(draft_bytes)
    diagnostics: list[dict[str, Any]] = []
    parsed: Any = None
    try:
        parsed = json.loads(draft_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        diagnostics.append(candidate_diagnostic(f"Invalid JSON in {source}: {exc}"))

    semantic_hash: str | None = None
    if parsed is not None:
        findings = parsed.get("findings") if isinstance(parsed, dict) else None
        if isinstance(findings, list):
            semantic_hash = candidate_semantic_hash(findings)
        _, inspection_diagnostics = inspect_candidate_set(
            parsed,
            source_file=source,
            repo=repo,
            run_dir=run_dir,
            state=state,
        )
        diagnostics.extend(inspection_diagnostics)
        if isinstance(parsed, dict):
            assignments = {
                "reviewer_id": active_identity["reviewer_id"],
                "independence_group": active_identity["independence_group"],
                "review_mode": active_identity["review_mode"],
            }
            for field, expected in assignments.items():
                if parsed.get(field) != expected:
                    diagnostics.append(
                        {
                            "code": "TOP_LEVEL_METADATA",
                            "path": field,
                            "message": f"{field} must match active route assignment {expected!r}",
                            "correctable": True,
                        }
                    )

    if previous is not None and previous["semantic_hash"] is not None:
        if semantic_hash != previous["semantic_hash"]:
            diagnostics.append(
                {
                    "code": "SUBSTANTIVE_DRIFT",
                    "path": "findings",
                    "message": "Second candidate attempt changed substantive finding fields",
                    "correctable": False,
                }
            )

    if diagnostics:
        verdict = (
            "correctable"
            if all(item["code"] in CORRECTABLE_DIAGNOSTIC_CODES for item in diagnostics)
            else "rejected"
        )
    else:
        verdict = "valid"
    attempt = len(records) + 1
    receipt = {
        "schema_version": CANDIDATE_PREFLIGHT_SCHEMA,
        "scope_hash": state["scope_hash"],
        "coverage_plan_hash": coverage_plan_hash,
        "lens_id": args.lens,
        "route": route,
        "attempt": attempt,
        "draft_hash": draft_hash,
        "semantic_hash": semantic_hash,
        "supersedes_receipt_hash": args.supersedes,
        "verdict": verdict,
        "diagnostics": diagnostics,
        "reviewer_id": active_identity["reviewer_id"],
        "independence_group": active_identity["independence_group"],
        "review_mode": active_identity["review_mode"],
        "fallback_assignment_hash": (
            active_identity["assignment_hash"] if args.fallback else None
        ),
        "degraded": args.fallback,
        "evidence_handling": (
            "unparseable_origin_degraded"
            if previous is not None and previous["semantic_hash"] is None
            else "standard"
        ),
        "source_file": str(source),
    }
    receipt_hash = canonical_hash(receipt)
    receipt["receipt_hash"] = receipt_hash
    relative_path = (
        f"candidate-preflight/{args.lens}/{route}/attempt-{attempt}.json"
    )
    atomic_write_json(run_dir / relative_path, receipt)
    records.append(
        {
            "path": relative_path,
            "receipt_hash": receipt_hash,
        }
    )
    state["events"].append(
        {
            "at": utc_now(),
            "event": "candidate_preflight_recorded",
            "lens_id": args.lens,
            "route": route,
            "attempt": attempt,
            "verdict": verdict,
            "receipt_hash": receipt_hash,
        }
    )
    save_state(run_dir, state)
    print(f"[{'OK' if verdict == 'valid' else 'FAIL'}] Candidate preflight: {verdict}")
    print(f"Receipt: {run_dir / relative_path}")
    return 0 if verdict == "valid" else 2


def command_ingest_candidates(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] not in {PHASE_CONTEXT, PHASE_CANDIDATES}:
        raise ReviewError(f"Cannot ingest candidates in phase {state['phase']}")
    check_scope_fresh(repo, run_dir, state)
    if not args.input:
        raise ReviewError("At least one --input candidate JSON file is required")

    reviewer_sets: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    coverage_status: dict[str, Any] | None = None
    coverage_required = bool(state.get("coverage_required", False))
    unmatched_inputs = False
    if coverage_required:
        coverage_plan, coverage_plan_hash = load_verified_coverage_plan(run_dir, state)
        all_receipts, fallback_assignments, attestations = load_review_evidence(
            run_dir, state, coverage_plan, coverage_plan_hash
        )
        latest_receipts = latest_candidate_preflight_receipts(all_receipts)
        coverage_receipts = [
            receipt for receipt in latest_receipts if receipt["verdict"] != "valid"
        ]
        used_receipt_hashes: set[str] = set()
        for raw_path in args.input:
            source = Path(raw_path).expanduser().resolve()
            try:
                draft_bytes = source.read_bytes()
            except OSError as exc:
                rejections.append({"source_file": str(source), "reason": str(exc)})
                unmatched_inputs = True
                continue
            draft_hash = sha256_bytes(draft_bytes)
            matches = [
                receipt
                for receipt in latest_receipts
                if receipt["verdict"] == "valid"
                and receipt["receipt_hash"] not in used_receipt_hashes
                and receipt["draft_hash"] == draft_hash
                and Path(receipt["source_file"]).expanduser().resolve() == source
            ]
            if len(matches) != 1:
                rejections.append(
                    {
                        "source_file": str(source),
                        "reason": "Input bytes do not match exactly one latest valid candidate-preflight receipt",
                    }
                )
                unmatched_inputs = True
                continue
            receipt = matches[0]
            try:
                normalized_set, finding_rejections = validate_candidate_set(
                    json.loads(draft_bytes.decode("utf-8")),
                    source_file=source,
                    repo=repo,
                    run_dir=run_dir,
                    state=state,
                )
                if any(
                    normalized_set[field] != receipt[field]
                    for field in ("reviewer_id", "independence_group", "review_mode")
                ):
                    raise ReviewError(
                        f"{source}: candidate identity no longer matches its verified {receipt['route']} receipt"
                    )
                provenance = {
                    "lens_id": receipt["lens_id"],
                    "review_route": receipt["route"],
                    "fallback_assignment_hash": receipt["fallback_assignment_hash"],
                    "degraded": receipt["degraded"],
                    "evidence_handling": receipt["evidence_handling"],
                }
                normalized_set.update(provenance)
                for finding in normalized_set["findings"]:
                    finding.update(provenance)
                reviewer_sets.append(normalized_set)
                rejections.extend(finding_rejections)
                coverage_receipts.append(receipt)
                used_receipt_hashes.add(receipt["receipt_hash"])
            except (ReviewError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                rejections.append({"source_file": str(source), "reason": str(exc)})
                unmatched_inputs = True

        unused_valid_receipts = [
            receipt
            for receipt in latest_receipts
            if receipt["verdict"] == "valid"
            and receipt["receipt_hash"] not in used_receipt_hashes
        ]
        for receipt in unused_valid_receipts:
            rejections.append(
                {
                    "source_file": receipt["source_file"],
                    "reason": (
                        "Latest valid candidate-preflight receipt was not matched by exactly "
                        f"one explicit --input for {receipt['lens_id']}/{receipt['route']}"
                    ),
                }
            )
        if unused_valid_receipts:
            unmatched_inputs = True
        if unmatched_inputs:
            atomic_write_json(run_dir / "candidate-rejections.json", rejections)
            print(
                "[FAIL] Every latest valid candidate receipt must match exactly one explicit --input"
            )
            return 2

        coverage_status = build_coverage_status(
            state=state,
            coverage_plan=coverage_plan,
            receipts=coverage_receipts,
            fallback_assignments=fallback_assignments,
            attestations=attestations,
        )
        if coverage_status["status"] == "incomplete":
            require_exhausted_incomplete_required_routes(
                coverage_plan=coverage_plan,
                coverage_status=coverage_status,
                receipts=all_receipts,
                fallback_assignments=fallback_assignments,
                attestations=attestations,
            )
        atomic_write_json(run_dir / "coverage-status.json", coverage_status)
        state["hashes"]["coverage_status_hash"] = coverage_status["coverage_status_hash"]
        state["events"].append(
            {
                "at": utc_now(),
                "event": "coverage_status_recorded",
                "status": coverage_status["status"],
                "coverage_status_hash": coverage_status["coverage_status_hash"],
            }
        )
        atomic_write_json(run_dir / "candidate-rejections.json", rejections)
        if coverage_status["status"] != "complete":
            (run_dir / "candidates.json").unlink(missing_ok=True)
            (run_dir / "candidates.md").unlink(missing_ok=True)
            state["hashes"].pop("candidate_bundle_hash", None)
            state["phase"] = PHASE_REVIEW_INCOMPLETE
            state["events"].append(
                {
                    "at": utc_now(),
                    "event": "review_incomplete",
                    "coverage_status_hash": coverage_status["coverage_status_hash"],
                }
            )
            save_state(run_dir, state)
            print("[FAIL] Required review coverage is incomplete")
            print(f"Artifact: {run_dir / 'coverage-status.json'}")
            return 2
    else:
        for raw_path in args.input:
            source = Path(raw_path).expanduser().resolve()
            try:
                normalized_set, finding_rejections = validate_candidate_set(
                    load_json(source),
                    source_file=source,
                    repo=repo,
                    run_dir=run_dir,
                    state=state,
                )
                reviewer_sets.append(normalized_set)
                rejections.extend(finding_rejections)
            except ReviewError as exc:
                rejections.append({"source_file": str(source), "reason": str(exc)})
    if not reviewer_sets:
        atomic_write_json(run_dir / "candidate-rejections.json", rejections)
        raise ReviewError("All candidate-set inputs were rejected; review coverage is not valid")

    candidates: list[dict[str, Any]] = []
    for reviewer_set in reviewer_sets:
        candidates.extend(reviewer_set.pop("findings"))
    candidates.sort(
        key=lambda item: (
            item["reviewer_id"],
            item["independence_group"],
            item["local_id"],
            item["file"],
            item["line_start"],
        )
    )
    for index, candidate in enumerate(candidates, start=1):
        candidate["candidate_id"] = f"C{index:03d}"

    payload = {
        "schema_version": NORMALIZED_CANDIDATES_SCHEMA,
        "scope_hash": state["scope_hash"],
        "reviewer_sets": reviewer_sets,
        "candidates": candidates,
        "rejections": rejections,
    }
    if coverage_status is not None:
        payload["coverage"] = coverage_status
    bundle_hash = canonical_hash(payload)
    payload["candidate_bundle_hash"] = bundle_hash
    payload["generated_at"] = utc_now()
    atomic_write_json(run_dir / "candidates.json", payload)
    atomic_write_json(run_dir / "candidate-rejections.json", rejections)
    atomic_write_text(run_dir / "candidates.md", render_candidates_markdown(payload, rejections))

    state["phase"] = PHASE_CANDIDATES
    state["hashes"]["candidate_bundle_hash"] = bundle_hash
    state["events"].append(
        {
            "at": utc_now(),
            "event": "candidates_ingested",
            "reviewer_sets": len(reviewer_sets),
            "candidates": len(candidates),
            "rejections": len(rejections),
            "candidate_bundle_hash": bundle_hash,
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Candidate bundle written: {bundle_hash}")
    print(f"Accepted reviewer sets: {len(reviewer_sets)}")
    print(f"Accepted candidates: {len(candidates)}")
    print(f"Rejected candidate/input records: {len(rejections)}")
    print(f"Artifact: {run_dir / 'candidates.md'}")
    return 0


def command_finalize_coverage(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    with exclusive_run_state_lock(run_dir):
        state = load_state(run_dir)
        if state["phase"] != PHASE_CONTEXT:
            raise ReviewError(f"Cannot finalize coverage in phase {state['phase']}")
        if not state.get("coverage_required", False):
            raise ReviewError("Legacy runs without required coverage cannot be finalized here")
        check_scope_fresh(repo, run_dir, state)
        coverage_plan, coverage_plan_hash = load_verified_coverage_plan(run_dir, state)
        receipts, assignments, attestations = load_review_evidence(
            run_dir, state, coverage_plan, coverage_plan_hash
        )
        latest_receipts = latest_candidate_preflight_receipts(receipts)
        coverage_status = build_coverage_status(
            state=state,
            coverage_plan=coverage_plan,
            receipts=latest_receipts,
            fallback_assignments=assignments,
            attestations=attestations,
        )
        if coverage_status["status"] != "incomplete":
            raise ReviewError(
                "Coverage is complete; ingest the exact valid candidate inputs instead"
            )
        require_exhausted_incomplete_required_routes(
            coverage_plan=coverage_plan,
            coverage_status=coverage_status,
            receipts=receipts,
            fallback_assignments=assignments,
            attestations=attestations,
        )
        forbidden_artifacts = (
            "candidates.json",
            "ledger.json",
            "gates/findings.json",
            "fix-plan.json",
        )
        existing = [relative for relative in forbidden_artifacts if (run_dir / relative).exists()]
        if existing:
            raise ReviewError(
                "Coverage finalization found unexpected downstream artifacts: "
                + ", ".join(existing)
            )
        atomic_write_json(run_dir / "coverage-status.json", coverage_status)
        state["hashes"]["coverage_status_hash"] = coverage_status[
            "coverage_status_hash"
        ]
        state["phase"] = PHASE_REVIEW_INCOMPLETE
        state["events"].append(
            {
                "at": utc_now(),
                "event": "coverage_finalized_incomplete",
                "coverage_status_hash": coverage_status["coverage_status_hash"],
            }
        )
        save_state(run_dir, state)
        print("[OK] Required review coverage finalized as REVIEW_INCOMPLETE")
        print(f"Artifact: {run_dir / 'coverage-status.json'}")
        return 0


def validate_normalized_evidence_handling(candidates_bundle: dict[str, Any]) -> None:
    collections: list[tuple[str, list[Any]]] = []
    for name in ("reviewer_sets", "candidates"):
        values = require_array(candidates_bundle.get(name), f"normalized candidates.{name}")
        collections.append((name, values))
        if any(
            not isinstance(value, dict) or "evidence_handling" not in value
            for value in values
        ):
            raise provisional_v1_restart("normalized candidates")
        for index, value in enumerate(values):
            evidence_handling = require_string(
                value["evidence_handling"],
                f"normalized candidates.{name}[{index}].evidence_handling",
            )
            if evidence_handling not in EVIDENCE_HANDLING_VALUES:
                raise ReviewError(
                    f"normalized candidates.{name}[{index}].evidence_handling is invalid"
                )

    reviewer_sets = collections[0][1]
    for index, candidate in enumerate(collections[1][1]):
        matching_sets = [
            reviewer_set
            for reviewer_set in reviewer_sets
            if all(
                candidate.get(field) == reviewer_set.get(field)
                for field in (
                    "reviewer_id",
                    "independence_group",
                    "lens_id",
                    "review_route",
                    "fallback_assignment_hash",
                    "degraded",
                )
            )
        ]
        if not matching_sets or any(
            reviewer_set["evidence_handling"] != candidate["evidence_handling"]
            for reviewer_set in matching_sets
        ):
            raise ReviewError(
                "Normalized candidate evidence handling differs from its reviewer set "
                f"at index {index}"
            )


def command_compile_ledger(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] not in {PHASE_CANDIDATES, PHASE_ADJUDICATED}:
        raise ReviewError(f"Cannot compile ledger in phase {state['phase']}")
    check_scope_fresh(repo, run_dir, state)
    candidates_bundle = require_object(load_json(run_dir / "candidates.json"), "normalized candidates")
    candidate_hash = verify_embedded_hash(
        candidates_bundle,
        hash_field="candidate_bundle_hash",
        context="normalized candidates",
        unhashed_fields={"generated_at"},
    )
    require_state_hash(state, "candidate_bundle_hash", candidate_hash, "normalized candidates")
    if state.get("coverage_required", False):
        coverage_plan, _ = load_verified_coverage_plan(run_dir, state)
        coverage_status = load_verified_coverage_status(run_dir, state, coverage_plan)
        validate_normalized_evidence_handling(candidates_bundle)
        if coverage_status["status"] != "complete":
            raise ReviewError("Cannot compile ledger with incomplete required review coverage")
        if candidates_bundle.get("coverage") != coverage_status:
            raise ReviewError("Normalized candidates do not contain the hash-bound coverage status")
    adjudication = validate_adjudication(load_json(Path(args.input).expanduser().resolve()), candidates_bundle=candidates_bundle, state=state)
    candidates_by_id = {item["candidate_id"]: item for item in candidates_bundle["candidates"]}
    kept_groups = [group for group in adjudication["groups"] if group["disposition"] == "keep"]
    kept_groups.sort(
        key=lambda group: (
            SEVERITY_ORDER[group["severity"]],
            CONFIDENCE_ORDER[group["confidence"]],
            group["file"],
            group["line_start"],
            group["canonical_title"],
        )
    )
    findings: list[dict[str, Any]] = []
    for index, group in enumerate(kept_groups, start=1):
        representative = representative_candidate(group, candidates_by_id)
        findings.append(
            {
                "finding_id": f"F{index:03d}",
                "group_id": group["group_id"],
                "candidate_ids": group["candidate_ids"],
                "title": group["canonical_title"],
                "nature": group["nature"],
                "category": group["category"],
                "severity": group["severity"],
                "confidence": group["confidence"],
                "file": group["file"],
                "line_start": group["line_start"],
                "line_end": group["line_end"],
                "evidence_side": group["evidence_side"],
                "evidence_quote": group["evidence_quote"],
                "observable_consequence": representative["observable_consequence"],
                "trigger_conditions": representative["trigger_conditions"],
                "repair_direction": group["repair_direction"],
                "repair_direction_hash": group["repair_direction_hash"],
                "repair_audit": group["repair_audit"],
                "estimated_fix_risk": representative["estimated_fix_risk"],
                "requires_user_decision": bool(group["repair_direction"]["open_user_decisions"]),
                "assumptions": representative["assumptions"],
                "source_reviewers": group["source_reviewers"],
                "source_independence_groups": group["source_independence_groups"],
                "validation": group["validation"],
                "materiality": group["materiality"],
                "decision_reason": group["decision_reason"],
                "recommended_action": group["recommended_action"],
                "required_pre_fix_verification": group["required_pre_fix_verification"],
            }
        )
    discarded = [group for group in adjudication["groups"] if group["disposition"] == "discard"]
    payload = {
        "schema_version": LEDGER_SCHEMA,
        "scope_hash": state["scope_hash"],
        "candidate_bundle_hash": candidates_bundle["candidate_bundle_hash"],
        "adjudicator_id": adjudication["adjudicator_id"],
        "verdict": adjudication["verdict"],
        "summary": adjudication["summary"],
        "findings": findings,
        "discarded": discarded,
        "limitations": adjudication["limitations"],
    }
    ledger_hash = canonical_hash(payload)
    payload["ledger_hash"] = ledger_hash
    payload["generated_at"] = utc_now()
    atomic_write_json(run_dir / "ledger.json", payload)
    atomic_write_text(run_dir / "ledger.md", render_ledger_markdown(payload))
    atomic_write_json(run_dir / "adjudication.normalized.json", adjudication)

    state["phase"] = PHASE_ADJUDICATED
    state["hashes"]["ledger_hash"] = ledger_hash
    state["events"].append(
        {
            "at": utc_now(),
            "event": "ledger_compiled",
            "ledger_hash": ledger_hash,
            "kept": len(findings),
            "discarded": len(discarded),
            "verdict": payload["verdict"],
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Ledger compiled: {ledger_hash}")
    print(f"Kept findings: {len(findings)}")
    print(f"Discarded candidate groups: {len(discarded)}")
    print(f"Verdict: {payload['verdict']}")
    print(f"Gate A artifact: {run_dir / 'ledger.md'}")
    return 0


def command_gate_findings(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_ADJUDICATED:
        raise ReviewError(f"Gate A requires phase {PHASE_ADJUDICATED}; current phase is {state['phase']}")
    check_scope_fresh(repo, run_dir, state)
    ledger = require_object(load_json(run_dir / "ledger.json"), "ledger")
    ledger_hash = verify_embedded_hash(
        ledger,
        hash_field="ledger_hash",
        context="ledger",
        unhashed_fields={"generated_at"},
    )
    require_state_hash(state, "ledger_hash", ledger_hash, "ledger")
    finding_ids = {item["finding_id"] for item in ledger["findings"]}
    approved = parse_csv_ids(args.approve)
    rejected = parse_csv_ids(args.reject)
    deferred = parse_csv_ids(args.defer)
    if approved & rejected or approved & deferred or rejected & deferred:
        raise ReviewError("Gate A approve/reject/defer sets must be disjoint")
    user_statement = require_string(args.user_statement, "--user-statement")
    if finding_ids:
        if args.accept_empty:
            raise ReviewError("--accept-empty is valid only when the ledger kept no findings")
        disposition_ids = approved | rejected | deferred
        if disposition_ids != finding_ids:
            missing = sorted(finding_ids - disposition_ids)
            extra = sorted(disposition_ids - finding_ids)
            details: list[str] = []
            if missing:
                details.append(f"missing dispositions for {', '.join(missing)}")
            if extra:
                details.append(f"unknown IDs {', '.join(extra)}")
            raise ReviewError("Gate A must dispose every kept finding exactly once: " + "; ".join(details))
    else:
        if not args.accept_empty:
            raise ReviewError("The empty material set still requires --accept-empty and a user statement")
        if approved or rejected or deferred:
            raise ReviewError("No finding IDs may be supplied when accepting an empty material set")

    receipt_payload = {
        "schema_version": FINDINGS_GATE_SCHEMA,
        "run_id": state["run_id"],
        "scope_hash": state["scope_hash"],
        "ledger_hash": ledger["ledger_hash"],
        "decisions": {
            "approved": sorted(approved),
            "rejected": sorted(rejected),
            "deferred": sorted(deferred),
            "accepted_empty": bool(args.accept_empty),
        },
        "user_statement": user_statement,
        "recorded_at": utc_now(),
    }
    receipt_hash = canonical_hash(receipt_payload)
    receipt_payload["receipt_hash"] = receipt_hash
    gates_dir = run_dir / "gates"
    atomic_write_json(gates_dir / "findings.json", receipt_payload)
    state["gates"]["findings"] = receipt_hash
    state["approved_findings"] = sorted(approved)
    state["hashes"]["findings_gate_hash"] = receipt_hash
    state["events"].append(
        {
            "at": utc_now(),
            "event": "gate_a_recorded",
            "receipt_hash": receipt_hash,
            "approved": sorted(approved),
            "rejected": sorted(rejected),
            "deferred": sorted(deferred),
        }
    )
    if approved:
        state["phase"] = PHASE_FINDINGS_APPROVED
    else:
        state["phase"] = PHASE_COMPLETE
        if not finding_ids:
            completion_message = "No material improvements recommended."
        else:
            completion_message = (
                "No findings were approved for repair. The material findings and merge-readiness "
                "decision remain recorded in the ledger."
            )
        atomic_write_text(
            run_dir / "completion.md",
            "# Review complete\n\n"
            f"{completion_message}\n\n"
            f"- Gate A receipt: `{receipt_hash}`\n"
            f"- Ledger: `{ledger['ledger_hash']}`\n"
            f"- Ledger verdict: `{ledger['verdict']}`\n"
            f"- Rejected by user: `{', '.join(sorted(rejected)) if rejected else 'none'}`\n"
            f"- Deferred by user: `{', '.join(sorted(deferred)) if deferred else 'none'}`\n",
        )
    save_state(run_dir, state)
    print(f"[OK] Gate A recorded: {receipt_hash}")
    print(f"Approved: {', '.join(sorted(approved)) if approved else 'none'}")
    print(f"Rejected: {', '.join(sorted(rejected)) if rejected else 'none'}")
    print(f"Deferred: {', '.join(sorted(deferred)) if deferred else 'none'}")
    print(f"Next phase: {state['phase']}")
    return 0


def command_validate_plan(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] not in {PHASE_FINDINGS_APPROVED, PHASE_PLAN_VALIDATED}:
        raise ReviewError(f"Cannot validate a plan in phase {state['phase']}")
    check_scope_fresh(repo, run_dir, state)
    findings_gate = load_verified_findings_gate(run_dir, state)
    ledger = load_verified_ledger(run_dir, state, findings_gate=findings_gate)
    plan = validate_fix_plan(
        load_json(Path(args.input).expanduser().resolve()),
        repo=repo,
        state=state,
        findings_gate=findings_gate,
        ledger=ledger,
    )
    plan_hash = canonical_hash(plan)
    plan["plan_hash"] = plan_hash
    plan["validated_at"] = utc_now()
    atomic_write_json(run_dir / "fix-plan.json", plan)
    atomic_write_text(run_dir / "fix-plan.md", render_plan_markdown(plan))
    old_gate = run_dir / "gates" / "plan.json"
    if old_gate.exists():
        archive = run_dir / "gates" / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_gate), str(archive / f"plan-{utc_now().replace(':', '')}.json"))
    state["phase"] = PHASE_PLAN_VALIDATED
    state["hashes"]["plan_hash"] = plan_hash
    state["gates"].pop("plan", None)
    state["events"].append(
        {
            "at": utc_now(),
            "event": "plan_validated",
            "plan_hash": plan_hash,
            "items": len(plan["items"]),
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Repair plan validated: {plan_hash}")
    print(f"Plan items: {len(plan['items'])}")
    print(f"Gate B artifact: {run_dir / 'fix-plan.md'}")
    return 0


def command_gate_plan(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_PLAN_VALIDATED:
        raise ReviewError(f"Gate B requires phase {PHASE_PLAN_VALIDATED}; current phase is {state['phase']}")
    check_scope_fresh(repo, run_dir, state)
    if args.approve == args.reject:
        raise ReviewError("Specify exactly one of --approve or --reject")
    user_statement = require_string(args.user_statement, "--user-statement")
    plan = load_verified_plan(run_dir, state)
    findings_gate = load_verified_findings_gate(run_dir, state)
    receipt_payload = {
        "schema_version": PLAN_GATE_SCHEMA,
        "run_id": state["run_id"],
        "scope_hash": state["scope_hash"],
        "findings_gate_hash": findings_gate["receipt_hash"],
        "plan_hash": plan["plan_hash"],
        "approved": bool(args.approve),
        "user_statement": user_statement,
        "recorded_at": utc_now(),
    }
    receipt_hash = canonical_hash(receipt_payload)
    receipt_payload["receipt_hash"] = receipt_hash
    atomic_write_json(run_dir / "gates" / "plan.json", receipt_payload)
    state["events"].append(
        {
            "at": utc_now(),
            "event": "gate_b_recorded",
            "receipt_hash": receipt_hash,
            "plan_hash": plan["plan_hash"],
            "approved": bool(args.approve),
        }
    )
    if args.approve:
        state["phase"] = PHASE_PLAN_APPROVED
        state["gates"]["plan"] = receipt_hash
        state["hashes"]["plan_gate_hash"] = receipt_hash
    else:
        state["phase"] = PHASE_FINDINGS_APPROVED
        state["gates"].pop("plan", None)
        state["hashes"].pop("plan_gate_hash", None)
    save_state(run_dir, state)
    print(f"[OK] Gate B recorded: {receipt_hash}")
    print(f"Decision: {'approved' if args.approve else 'rejected'}")
    print(f"Next phase: {state['phase']}")
    return 0


def plan_item_by_id(plan: dict[str, Any], finding_id: str) -> dict[str, Any]:
    for item in plan["items"]:
        if item["finding_id"] == finding_id:
            return item
    raise ReviewError(f"Finding {finding_id} is not present in the approved plan")


def test_by_id(tests: list[dict[str, Any]], test_id: str, context: str) -> dict[str, Any]:
    for test in tests:
        if test["id"] == test_id:
            return test
    raise ReviewError(f"Unknown {context} test ID: {test_id}")


def command_begin_fix(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_PLAN_APPROVED:
        raise ReviewError(f"begin-fix requires phase {PHASE_PLAN_APPROVED}; current phase is {state['phase']}")
    check_scope_fresh(repo, run_dir, state)
    if not state["mutation_allowed"]:
        raise ReviewError("The reviewed scope is not aligned with the working tree; reinitialize a mutable local scope before repair")
    plan = load_verified_plan(run_dir, state)
    plan_gate = load_verified_plan_gate(run_dir, state)
    if not plan_gate["approved"] or plan_gate["plan_hash"] != plan["plan_hash"]:
        raise ReviewError("Gate B receipt does not authorize the current plan")
    allowed_paths = sorted({path for item in plan["items"] for path in item["allowed_paths"]})
    checkpoint_dir = run_dir / "checkpoints" / "pre-fix"
    metadata = create_checkpoint(repo, checkpoint_dir, allowed_paths)
    finding_status = {
        item["finding_id"]: {
            "status": "pending",
            "attempts": 0,
            "max_attempts": item["max_attempts"],
            "history": [],
        }
        for item in plan["items"]
    }
    state["phase"] = PHASE_FIXING
    state["pre_fix_checkpoint"] = str(checkpoint_dir.relative_to(run_dir)).replace("\\", "/")
    state["hashes"]["pre_fix_snapshot_hash"] = metadata["checkpoint_hash"]
    state["finding_status"] = finding_status
    state["active_finding"] = None
    state["global_test_results"] = {}
    state["final_test_refresh_results"] = {}
    state["pre_verification_recovery_history"] = []
    state["repair_round"] = 0
    state["repair_targets"] = []
    state["expected_workspace_guard_hash"] = metadata["workspace_guard"]["guard_hash"]
    state["events"].append(
        {
            "at": utc_now(),
            "event": "fix_layer_started",
            "pre_fix_snapshot_hash": metadata["checkpoint_hash"],
            "allowed_paths": allowed_paths,
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Repair layer started from checkpoint {metadata['checkpoint_hash']}")
    print(f"Approved findings: {', '.join(state['approved_findings'])}")
    print("No staging, commits, branch changes, or unapproved paths are authorized.")
    return 0


def validate_finding_start(state: dict[str, Any], plan: dict[str, Any], finding_id: str) -> dict[str, Any]:
    if finding_id not in state["approved_findings"]:
        raise ReviewError(f"Finding {finding_id} was not approved at Gate A")
    item = plan_item_by_id(plan, finding_id)
    status = state["finding_status"].get(finding_id)
    if not status:
        raise ReviewError(f"Missing internal status for {finding_id}")
    if status["status"] not in {"pending", "repair_pending"}:
        raise ReviewError(f"Finding {finding_id} is not pending (status {status['status']})")
    if status["attempts"] >= status["max_attempts"]:
        raise ReviewError(f"Finding {finding_id} exhausted its approved attempt budget")
    for dependency in item["depends_on"]:
        if state["finding_status"][dependency]["status"] != "fixed":
            raise ReviewError(f"Finding {finding_id} depends on {dependency}, which is not fixed")
    return item


def command_start_finding(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_FIXING:
        raise ReviewError(f"start-finding requires phase {PHASE_FIXING}; current phase is {state['phase']}")
    if state["active_finding"] is not None:
        raise ReviewError(f"Another finding is active: {state['active_finding']['finding_id']}")
    plan = load_verified_plan(run_dir, state)
    item = validate_finding_start(state, plan, args.finding)
    current = ensure_expected_workspace(repo, state)
    status = state["finding_status"][args.finding]
    attempt = status["attempts"] + 1
    checkpoint_dir = run_dir / "checkpoints" / args.finding / f"attempt-{attempt}"
    metadata = create_checkpoint(repo, checkpoint_dir, item["allowed_paths"])
    status["attempts"] = attempt
    status["status"] = "active"
    state["active_finding"] = {
        "finding_id": args.finding,
        "attempt": attempt,
        "checkpoint": str(checkpoint_dir.relative_to(run_dir)).replace("\\", "/"),
        "before_guard": current,
        "allowed_paths": item["allowed_paths"],
        "test_results": {},
        "manual_evidence": [],
        "started_at": utc_now(),
    }
    state["events"].append(
        {
            "at": utc_now(),
            "event": "finding_attempt_started",
            "finding_id": args.finding,
            "attempt": attempt,
            "checkpoint_hash": metadata["checkpoint_hash"],
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Started {args.finding} attempt {attempt}")
    print(f"Allowed paths: {', '.join(item['allowed_paths'])}")
    print(f"Checkpoint: {checkpoint_dir}")
    return 0


def active_boundary_audit(repo: Path, state: dict[str, Any]) -> tuple[dict[str, Any], set[str], set[str]]:
    active = state.get("active_finding")
    if not active:
        raise ReviewError("No active finding checkpoint")
    before = active["before_guard"]
    current = workspace_guard(repo)
    before_identity = before["identity"]
    current_identity = current["identity"]
    if current_identity["head_sha"] != before_identity["head_sha"]:
        raise ReviewError("HEAD changed during the finding attempt; commits/rebases are not authorized")
    if current_identity["branch"] != before_identity["branch"]:
        raise ReviewError("Branch changed during the finding attempt")
    if current_identity["staged_patch_sha256"] != before_identity["staged_patch_sha256"]:
        raise ReviewError("Git index changed during the finding attempt; staging is not authorized")
    changed_paths = diff_guard_paths(before, current)
    allowed = set(active["allowed_paths"])
    outside = changed_paths - allowed
    return current, changed_paths, outside


def terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    """Terminate a timed-out shell and its descendants as safely as the host permits."""
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=2)
            return
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif os.name == "nt":
        # /T includes descendants. Fall back to killing the direct shell if
        # taskkill is unavailable or denied.
        try:
            run_process(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                cwd=Path.cwd(),
                check=False,
            )
        except ReviewError:
            pass
        if process.poll() is None:
            process.kill()
    else:
        process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def execute_test_command(
    *,
    repo: Path,
    run_dir: Path,
    command: str,
    working_directory: str,
    timeout_seconds: int,
    log_relative: Path,
) -> dict[str, Any]:
    cwd = repo if working_directory == "." else repo_path(repo, working_directory)
    started_at = utc_now()
    timed_out = False
    exit_code: int | None
    popen_options: dict[str, Any] = {}
    if os.name == "posix":
        popen_options["start_new_session"] = True
    elif os.name == "nt":
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    with tempfile.TemporaryFile(mode="w+b") as stdout_handle, tempfile.TemporaryFile(mode="w+b") as stderr_handle:
        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                shell=True,
                stdout=stdout_handle,
                stderr=stderr_handle,
                env={
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": os.environ.get("PYTHONDONTWRITEBYTECODE", "1"),
                },
                **popen_options,
            )
        except OSError as exc:
            raise ReviewError(f"Could not start approved test command: {exc}") from exc

        try:
            process.wait(timeout=timeout_seconds)
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate_process_tree(process)
            exit_code = None

        finished_at = utc_now()
        log_path = run_dir / log_relative
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{log_path.name}.", dir=str(log_path.parent))
        try:
            with os.fdopen(fd, "wb") as log_handle:
                header = (
                    f"Command: {command}\n"
                    f"Working directory: {working_directory}\n"
                    f"Timeout seconds: {timeout_seconds}\n"
                    f"Started: {started_at}\n"
                    f"Finished: {finished_at}\n"
                    f"Timed out: {str(timed_out).lower()}\n"
                    f"Exit code: {exit_code if exit_code is not None else 'timeout'}\n"
                    "\n--- STDOUT ---\n"
                ).encode("utf-8")
                log_handle.write(header)
                stdout_handle.seek(0)
                shutil.copyfileobj(stdout_handle, log_handle, length=1024 * 1024)
                log_handle.write(b"\n--- STDERR ---\n")
                stderr_handle.seek(0)
                shutil.copyfileobj(stderr_handle, log_handle, length=1024 * 1024)
                log_handle.flush()
                os.fsync(log_handle.fileno())
            os.replace(temp_name, log_path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    return {
        "command": command,
        "working_directory": working_directory,
        "timeout_seconds": timeout_seconds,
        "started_at": started_at,
        "finished_at": finished_at,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "log_path": str(log_path.relative_to(run_dir)).replace("\\", "/"),
        "log_sha256": sha256_file(log_path),
    }


def evidence_result_hash(result: dict[str, Any]) -> str:
    """Return the stable identity of one recorded test result.

    Older runs do not carry an embedded result hash, so their complete stored
    record remains the hash input. New records exclude the embedded field.
    """
    payload = {key: value for key, value in result.items() if key != "result_hash"}
    computed = canonical_hash(payload)
    embedded = result.get("result_hash")
    if embedded is not None and embedded != computed:
        raise ReviewError("Recorded test evidence failed result-hash integrity validation")
    return computed

def command_run_test(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_FIXING or not state.get("active_finding"):
        raise ReviewError("run-test requires an active finding in FIXING phase")
    active = state["active_finding"]
    if active["finding_id"] != args.finding:
        raise ReviewError(f"Active finding is {active['finding_id']}, not {args.finding}")
    plan = load_verified_plan(run_dir, state)
    item = plan_item_by_id(plan, args.finding)
    test = test_by_id(item["tests"], args.test, f"{args.finding}")
    _, _, outside_before = active_boundary_audit(repo, state)
    if outside_before:
        raise ReviewError("Unapproved paths changed before test execution: " + ", ".join(sorted(outside_before)))

    prior_runs = active["test_results"].get(args.test, [])
    run_number = len(prior_runs) + 1
    test_checkpoint_dir = (
        run_dir
        / "checkpoints"
        / "tests"
        / args.finding
        / f"attempt-{active['attempt']}"
        / args.test
        / f"run-{run_number}"
    )
    test_checkpoint = create_checkpoint(repo, test_checkpoint_dir, active["allowed_paths"])
    result = execute_test_command(
        repo=repo,
        run_dir=run_dir,
        command=test["command"],
        working_directory=test["working_directory"],
        timeout_seconds=test["timeout_seconds"],
        log_relative=(
            Path("tests")
            / args.finding
            / f"attempt-{active['attempt']}"
            / args.test
            / f"run-{run_number}.log"
        ),
    )

    after_test = workspace_guard(repo)
    before_test = test_checkpoint["workspace_guard"]
    changed_by_test = diff_guard_paths(before_test, after_test)
    control_mutations: list[str] = []
    for key, label in (
        ("head_sha", "HEAD"),
        ("branch", "branch"),
        ("staged_patch_sha256", "Git index"),
    ):
        if after_test["identity"][key] != before_test["identity"][key]:
            control_mutations.append(label)

    result["changed_paths_by_test"] = sorted(changed_by_test)
    result["control_mutations_by_test"] = control_mutations
    result["restored_after_mutation"] = False
    if changed_by_test or control_mutations:
        # A test is evidence, not an implicit edit step. Restore the exact
        # pre-test state even when the mutation stayed within approved paths.
        restored = restore_checkpoint(repo, test_checkpoint_dir)
        result["restored_after_mutation"] = True
        after_test = restored

    current, changed_paths, outside_after = active_boundary_audit(repo, state)
    result["workspace_guard_hash"] = current["guard_hash"]
    result["allowed_paths_hash"] = path_subset_hash(repo, active["allowed_paths"])
    result["changed_paths_at_completion"] = sorted(changed_paths)
    result["boundary_violations"] = sorted(outside_after)
    result["result_hash"] = evidence_result_hash(result)
    active["test_results"].setdefault(args.test, []).append(result)
    state["events"].append(
        {
            "at": utc_now(),
            "event": "finding_test_run",
            "finding_id": args.finding,
            "test_id": args.test,
            "exit_code": result["exit_code"],
            "timed_out": result["timed_out"],
            "changed_paths_by_test": result["changed_paths_by_test"],
            "control_mutations_by_test": result["control_mutations_by_test"],
            "boundary_violations": result["boundary_violations"],
        }
    )
    save_state(run_dir, state)
    passed = (
        result["exit_code"] == 0
        and not result["timed_out"]
        and not outside_after
        and not changed_by_test
        and not control_mutations
    )
    print(f"[{'OK' if passed else 'FAIL'}] Test {args.test}")
    print(f"Exit code: {result['exit_code'] if result['exit_code'] is not None else 'timeout'}")
    print(f"Evidence hash: {result['result_hash']}")
    print(f"Log: {run_dir / result['log_path']}")
    if changed_by_test or control_mutations:
        details = []
        if changed_by_test:
            details.append("paths: " + ", ".join(sorted(changed_by_test)))
        if control_mutations:
            details.append("controls: " + ", ".join(control_mutations))
        raise ReviewError("Approved test mutated the workspace and was restored (" + "; ".join(details) + ")")
    if outside_after:
        raise ReviewError("Test or active attempt changed unapproved paths: " + ", ".join(sorted(outside_after)))
    if result["timed_out"] or result["exit_code"] != 0:
        return 1
    return 0

def command_finish_finding(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_FIXING or not state.get("active_finding"):
        raise ReviewError("finish-finding requires an active finding in FIXING phase")
    active = state["active_finding"]
    if active["finding_id"] != args.finding:
        raise ReviewError(f"Active finding is {active['finding_id']}, not {args.finding}")
    if args.status not in {"fixed", "blocked"}:
        raise ReviewError("--status must be fixed or blocked")
    note = require_string(args.note, "--note")
    plan = load_verified_plan(run_dir, state)
    item = plan_item_by_id(plan, args.finding)
    current, changed_paths, outside = active_boundary_audit(repo, state)
    if outside:
        raise ReviewError("Cannot retain attempt; unapproved paths changed: " + ", ".join(sorted(outside)))

    checkpoint_dir = run_dir / active["checkpoint"]
    status_record = state["finding_status"][args.finding]
    if args.status == "blocked":
        if changed_paths:
            raise ReviewError("A blocked finding must first be restored with rollback-finding")
        status_record["status"] = "blocked"
        status_record["history"].append(
            {
                "attempt": active["attempt"],
                "outcome": "blocked",
                "note": note,
                "at": utc_now(),
            }
        )
        state["active_finding"] = None
        state["phase"] = PHASE_BLOCKED
        state["expected_workspace_guard_hash"] = current["guard_hash"]
        save_state(run_dir, state)
        print(f"[BLOCKED] {args.finding}: {note}")
        return 0

    if not changed_paths and not args.allow_no_change:
        raise ReviewError("A fixed finding must have a repair delta; use --allow-no-change only with explicit evidence")

    missing_or_stale_tests: list[str] = []
    for test in item["tests"]:
        if not test["required"]:
            continue
        runs = active["test_results"].get(test["id"], [])
        if not runs:
            missing_or_stale_tests.append(f"{test['id']} (not run)")
            continue
        latest = runs[-1]
        if latest["timed_out"] or latest["exit_code"] != 0:
            missing_or_stale_tests.append(f"{test['id']} (failed)")
        elif latest.get("allowed_paths_hash") != path_subset_hash(repo, item["allowed_paths"]):
            missing_or_stale_tests.append(f"{test['id']} (stale after later edits to approved paths)")
        elif latest["boundary_violations"]:
            missing_or_stale_tests.append(f"{test['id']} (boundary violation)")
    if missing_or_stale_tests:
        raise ReviewError("Required tests are not current and passing: " + ", ".join(missing_or_stale_tests))
    manual_evidence = [item.strip() for item in (args.manual_evidence or []) if item.strip()]
    if item["manual_verification"] and not manual_evidence:
        raise ReviewError("The approved plan requires --manual-evidence before this finding can be retained")

    patch_text = render_checkpoint_diff(checkpoint_dir, repo, changed_paths)
    fix_dir = run_dir / "fixes" / args.finding / f"attempt-{active['attempt']}"
    atomic_write_text(fix_dir / "fix.patch", patch_text)
    attempt_payload = {
        "finding_id": args.finding,
        "attempt": active["attempt"],
        "outcome": "fixed",
        "changed_paths": sorted(changed_paths),
        "tests": active["test_results"],
        "manual_evidence": manual_evidence,
        "note": note,
        "workspace_guard_hash": current["guard_hash"],
        "fix_patch": str((fix_dir / "fix.patch").relative_to(run_dir)).replace("\\", "/"),
        "completed_at": utc_now(),
    }
    attempt_payload["attempt_hash"] = canonical_hash(attempt_payload)
    atomic_write_json(fix_dir / "result.json", attempt_payload)
    status_record["status"] = "fixed"
    status_record["history"].append(attempt_payload)
    state["active_finding"] = None
    state["expected_workspace_guard_hash"] = current["guard_hash"]
    state["events"].append(
        {
            "at": utc_now(),
            "event": "finding_fixed",
            "finding_id": args.finding,
            "attempt": active["attempt"],
            "changed_paths": sorted(changed_paths),
            "attempt_hash": attempt_payload["attempt_hash"],
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Retained fix for {args.finding}")
    print(f"Changed paths: {', '.join(sorted(changed_paths)) if changed_paths else 'none (explicitly allowed)'}")
    print(f"Attempt artifact: {fix_dir / 'result.json'}")
    return 0


def command_rollback_finding(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_FIXING or not state.get("active_finding"):
        raise ReviewError("rollback-finding requires an active finding in FIXING phase")
    active = state["active_finding"]
    if active["finding_id"] != args.finding:
        raise ReviewError(f"Active finding is {active['finding_id']}, not {args.finding}")
    reason = require_string(args.reason, "--reason")
    checkpoint_dir = run_dir / active["checkpoint"]
    restored_guard = restore_checkpoint(repo, checkpoint_dir)
    status_record = state["finding_status"][args.finding]
    outcome = {
        "attempt": active["attempt"],
        "outcome": "rolled_back",
        "reason": reason,
        "tests": active["test_results"],
        "at": utc_now(),
    }
    status_record["history"].append(outcome)
    if status_record["attempts"] >= status_record["max_attempts"]:
        status_record["status"] = "blocked"
        state["phase"] = PHASE_BLOCKED
    else:
        status_record["status"] = "repair_pending" if state["repair_round"] > 0 else "pending"
    state["active_finding"] = None
    state["expected_workspace_guard_hash"] = restored_guard["guard_hash"]
    state["events"].append(
        {
            "at": utc_now(),
            "event": "finding_attempt_rolled_back",
            "finding_id": args.finding,
            "attempt": active["attempt"],
            "reason": reason,
            "next_status": status_record["status"],
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Restored checkpoint for {args.finding} attempt {active['attempt']}")
    print(f"Next status: {status_record['status']}")
    return 0


def command_abort_fixes(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] not in MUTATION_PHASES:
        raise ReviewError(f"No active repair layer to abort in phase {state['phase']}")
    reason = require_string(args.reason, "--reason")
    pre_fix = state.get("pre_fix_checkpoint")
    if not pre_fix:
        raise ReviewError("Pre-fix checkpoint is missing")
    restored = restore_checkpoint(repo, run_dir / pre_fix)
    state["phase"] = PHASE_ABORTED
    state["active_finding"] = None
    state["expected_workspace_guard_hash"] = restored["guard_hash"]
    state["events"].append({"at": utc_now(), "event": "fix_layer_aborted", "reason": reason})
    atomic_write_text(
        run_dir / "abort.md",
        f"# Repair layer aborted\n\n- Reason: {reason}\n- Restored at: {utc_now()}\n- Workspace guard: `{restored['guard_hash']}`\n",
    )
    save_state(run_dir, state)
    print("[OK] Restored the complete pre-fix checkpoint")
    print(f"State: {PHASE_ABORTED}")
    return 0


def path_subset_hash(repo: Path, paths: Iterable[str]) -> str:
    payload = {path: path_state(repo_path(repo, path)) for path in sorted(set(paths))}
    return canonical_hash(payload)


def all_findings_fixed(state: dict[str, Any]) -> bool:
    return bool(state["approved_findings"]) and all(
        state["finding_status"].get(finding_id, {}).get("status") == "fixed"
        for finding_id in state["approved_findings"]
    )


def overall_repair_boundary(repo: Path, run_dir: Path, state: dict[str, Any], plan: dict[str, Any]) -> tuple[dict[str, Any], set[str], set[str]]:
    current = ensure_expected_workspace(repo, state)
    pre_fix_dir = run_dir / state["pre_fix_checkpoint"]
    pre_fix, _, _ = verify_checkpoint_integrity(repo, pre_fix_dir)
    before = pre_fix["workspace_guard"]
    before_identity = before["identity"]
    current_identity = current["identity"]
    if current_identity["head_sha"] != before_identity["head_sha"]:
        raise ReviewError("HEAD changed after begin-fix")
    if current_identity["branch"] != before_identity["branch"]:
        raise ReviewError("Branch changed after begin-fix")
    if current_identity["staged_patch_sha256"] != before_identity["staged_patch_sha256"]:
        raise ReviewError("Git index changed after begin-fix")
    changed_paths = diff_guard_paths(before, current)
    allowed = {path for item in plan["items"] for path in item["allowed_paths"]}
    outside = changed_paths - allowed
    return current, changed_paths, outside


def command_run_global_test(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_FIXING or state.get("active_finding") is not None:
        raise ReviewError("run-global-test requires FIXING phase with no active finding")
    if not all_findings_fixed(state):
        raise ReviewError("Run global tests only after every approved finding is fixed")
    plan = load_verified_plan(run_dir, state)
    test = test_by_id(plan["global_tests"], args.test, "global")
    current, _, outside = overall_repair_boundary(repo, run_dir, state, plan)
    if outside:
        raise ReviewError("Repair layer already contains unapproved paths: " + ", ".join(sorted(outside)))
    prior_runs = state["global_test_results"].get(args.test, [])
    run_number = len(prior_runs) + 1
    checkpoint_dir = run_dir / "checkpoints" / "global-tests" / args.test / f"run-{run_number}"
    create_checkpoint(repo, checkpoint_dir, {path for item in plan["items"] for path in item["allowed_paths"]})
    result = execute_test_command(
        repo=repo,
        run_dir=run_dir,
        command=test["command"],
        working_directory=test["working_directory"],
        timeout_seconds=test["timeout_seconds"],
        log_relative=Path("tests") / "global" / args.test / f"run-{run_number}.log",
    )
    after = workspace_guard(repo)
    changed_by_test = diff_guard_paths(current, after)
    control_mutations_by_test: list[str] = []
    for field, label in (
        ("head_sha", "HEAD"),
        ("branch", "branch"),
        ("staged_patch_sha256", "Git index"),
    ):
        if after["identity"][field] != current["identity"][field]:
            control_mutations_by_test.append(label)
    result["workspace_guard_hash"] = after["guard_hash"]
    result["changed_paths_by_test"] = sorted(changed_by_test)
    result["control_mutations_by_test"] = control_mutations_by_test
    if changed_by_test or control_mutations_by_test:
        restore_checkpoint(repo, checkpoint_dir)
        result["restored_after_mutation"] = True
        result["workspace_guard_hash"] = current["guard_hash"]
    else:
        result["restored_after_mutation"] = False
    result["result_hash"] = evidence_result_hash(result)
    state["global_test_results"].setdefault(args.test, []).append(result)
    state["events"].append(
        {
            "at": utc_now(),
            "event": "global_test_run",
            "test_id": args.test,
            "exit_code": result["exit_code"],
            "timed_out": result["timed_out"],
            "changed_paths_by_test": result["changed_paths_by_test"],
            "control_mutations_by_test": result["control_mutations_by_test"],
        }
    )
    save_state(run_dir, state)
    print(
        f"[{'OK' if result['exit_code'] == 0 and not result['timed_out'] and not changed_by_test and not control_mutations_by_test else 'FAIL'}] "
        f"Global test {args.test}"
    )
    print(f"Exit code: {result['exit_code'] if result['exit_code'] is not None else 'timeout'}")
    print(f"Evidence hash: {result['result_hash']}")
    print(f"Log: {run_dir / result['log_path']}")
    if changed_by_test:
        raise ReviewError("Global test mutated tracked/untracked workspace paths and was restored: " + ", ".join(sorted(changed_by_test)))
    if control_mutations_by_test:
        raise ReviewError(
            "Global test mutated repository control state and was restored: "
            + ", ".join(control_mutations_by_test)
        )
    if result["timed_out"] or result["exit_code"] != 0:
        return 1
    return 0


def latest_fixed_attempt(state: dict[str, Any], finding_id: str) -> dict[str, Any]:
    history = state["finding_status"][finding_id]["history"]
    for entry in reversed(history):
        if entry.get("outcome") == "fixed":
            return entry
    raise ReviewError(f"No retained fixed attempt exists for {finding_id}")


def aggregate_allowed_paths(plan: dict[str, Any]) -> set[str]:
    return {path for item in plan["items"] for path in item["allowed_paths"]}


def latest_finding_test_evidence(
    state: dict[str, Any],
    *,
    finding_id: str,
    test_id: str,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    attempt = latest_fixed_attempt(state, finding_id)
    attempt_hash = attempt["attempt_hash"]
    refreshes = (
        state.get("final_test_refresh_results", {})
        .get(finding_id, {})
        .get(test_id, [])
    )
    matching_refreshes = [
        result
        for result in refreshes
        if result.get("retained_attempt_hash") == attempt_hash
    ]
    if matching_refreshes:
        return "final_test_refresh", matching_refreshes[-1], attempt
    runs = attempt["tests"].get(test_id, [])
    if not runs:
        raise ReviewError(f"No retained required-test evidence exists for {finding_id}:{test_id}")
    return "retained_attempt", runs[-1], attempt


def finding_test_evidence_issues(
    *,
    repo: Path,
    current: dict[str, Any],
    item: dict[str, Any],
    test: dict[str, Any],
    source: str,
    result: dict[str, Any],
    attempt: dict[str, Any],
) -> list[str]:
    evidence_result_hash(result)
    issues: list[str] = []
    if result.get("timed_out"):
        issues.append("timed out")
    elif result.get("exit_code") != 0:
        issues.append("failed")
    if result.get("changed_paths_by_test"):
        issues.append("mutated workspace paths")
    if result.get("control_mutations_by_test"):
        issues.append("mutated repository control state")
    if result.get("boundary_violations"):
        issues.append("crossed the approved path boundary")
    if result.get("command") != test["command"]:
        issues.append("does not match the approved command")
    if result.get("working_directory") != test["working_directory"]:
        issues.append("does not match the approved working directory")
    if result.get("timeout_seconds") != test["timeout_seconds"]:
        issues.append("does not match the approved timeout")
    if result.get("allowed_paths_hash") != path_subset_hash(repo, item["allowed_paths"]):
        issues.append("is stale for approved paths")
    if source == "final_test_refresh":
        if result.get("retained_attempt_hash") != attempt["attempt_hash"]:
            issues.append("is bound to a superseded retained attempt")
        if result.get("test_definition_hash") != canonical_hash(test):
            issues.append("is bound to a different approved test definition")
        if result.get("workspace_guard_hash") != current["guard_hash"]:
            issues.append("is stale after a later workspace edit")
    return issues


def command_refresh_finding_test(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_FIXING or state.get("active_finding") is not None:
        raise ReviewError("refresh-finding-test requires FIXING phase with no active finding")
    if not all_findings_fixed(state):
        raise ReviewError("Refresh finding tests only after every approved finding is fixed")
    if args.finding not in state["approved_findings"]:
        raise ReviewError(f"Finding {args.finding} was not approved at Gate A")

    plan = load_verified_plan(run_dir, state)
    item = plan_item_by_id(plan, args.finding)
    test = test_by_id(item["tests"], args.test, args.finding)
    if not test["required"]:
        raise ReviewError("Only a required Gate-B-approved finding test may be refreshed")
    current, _, outside = overall_repair_boundary(repo, run_dir, state, plan)
    if outside:
        raise ReviewError("Repair layer already contains unapproved paths: " + ", ".join(sorted(outside)))

    attempt = latest_fixed_attempt(state, args.finding)
    refresh_results = state.setdefault("final_test_refresh_results", {})
    finding_results = refresh_results.setdefault(args.finding, {})
    prior_runs = finding_results.get(args.test, [])
    run_number = len(prior_runs) + 1
    checkpoint_dir = (
        run_dir
        / "checkpoints"
        / "final-test-refresh"
        / args.finding
        / args.test
        / f"run-{run_number}"
    )
    create_checkpoint(repo, checkpoint_dir, aggregate_allowed_paths(plan))
    result = execute_test_command(
        repo=repo,
        run_dir=run_dir,
        command=test["command"],
        working_directory=test["working_directory"],
        timeout_seconds=test["timeout_seconds"],
        log_relative=(
            Path("tests")
            / "final-refresh"
            / args.finding
            / args.test
            / f"run-{run_number}.log"
        ),
    )
    after = workspace_guard(repo)
    changed_by_test = diff_guard_paths(current, after)
    control_mutations: list[str] = []
    for field, label in (
        ("head_sha", "HEAD"),
        ("branch", "branch"),
        ("staged_patch_sha256", "Git index"),
    ):
        if after["identity"][field] != current["identity"][field]:
            control_mutations.append(label)

    result["changed_paths_by_test"] = sorted(changed_by_test)
    result["control_mutations_by_test"] = control_mutations
    result["boundary_violations"] = sorted(changed_by_test - aggregate_allowed_paths(plan))
    result["restored_after_mutation"] = False
    final_guard = after
    if changed_by_test or control_mutations:
        final_guard = restore_checkpoint(repo, checkpoint_dir)
        result["restored_after_mutation"] = True
    result["workspace_guard_hash"] = final_guard["guard_hash"]
    result["allowed_paths_hash"] = path_subset_hash(repo, item["allowed_paths"])
    result["retained_attempt_hash"] = attempt["attempt_hash"]
    result["test_definition_hash"] = canonical_hash(test)
    result["result_hash"] = evidence_result_hash(result)
    finding_results.setdefault(args.test, []).append(result)
    state["events"].append(
        {
            "at": utc_now(),
            "event": "final_finding_test_refreshed",
            "finding_id": args.finding,
            "test_id": args.test,
            "retained_attempt_hash": attempt["attempt_hash"],
            "result_hash": result["result_hash"],
            "exit_code": result["exit_code"],
            "timed_out": result["timed_out"],
            "changed_paths_by_test": result["changed_paths_by_test"],
            "control_mutations_by_test": result["control_mutations_by_test"],
        }
    )
    save_state(run_dir, state)
    passed = (
        result["exit_code"] == 0
        and not result["timed_out"]
        and not changed_by_test
        and not control_mutations
    )
    print(f"[{'OK' if passed else 'FAIL'}] Refreshed {args.finding}:{args.test}")
    print(f"Exit code: {result['exit_code'] if result['exit_code'] is not None else 'timeout'}")
    print(f"Evidence hash: {result['result_hash']}")
    print(f"Log: {run_dir / result['log_path']}")
    if changed_by_test or control_mutations:
        details = []
        if changed_by_test:
            details.append("paths: " + ", ".join(sorted(changed_by_test)))
        if control_mutations:
            details.append("controls: " + ", ".join(control_mutations))
        raise ReviewError("Approved refresh test mutated the workspace and was restored (" + "; ".join(details) + ")")
    if result["timed_out"] or result["exit_code"] != 0:
        return 1
    return 0


def command_prepare_verification(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_FIXING or state.get("active_finding") is not None:
        raise ReviewError("prepare-verification requires FIXING phase with no active finding")
    if not all_findings_fixed(state):
        unresolved = [
            f"{finding_id}:{state['finding_status'].get(finding_id, {}).get('status', 'missing')}"
            for finding_id in state["approved_findings"]
            if state["finding_status"].get(finding_id, {}).get("status") != "fixed"
        ]
        raise ReviewError("Not all approved findings are fixed: " + ", ".join(unresolved))
    plan = load_verified_plan(run_dir, state)
    current, changed_paths, outside = overall_repair_boundary(repo, run_dir, state, plan)
    if outside:
        raise ReviewError("Aggregate repair delta contains unapproved paths: " + ", ".join(sorted(outside)))

    stale_finding_tests: list[str] = []
    for item in plan["items"]:
        for test in item["tests"]:
            if not test["required"]:
                continue
            try:
                source, latest, attempt = latest_finding_test_evidence(
                    state,
                    finding_id=item["finding_id"],
                    test_id=test["id"],
                )
            except ReviewError:
                stale_finding_tests.append(f"{item['finding_id']}:{test['id']} not run")
                continue
            issues = finding_test_evidence_issues(
                repo=repo,
                current=current,
                item=item,
                test=test,
                source=source,
                result=latest,
                attempt=attempt,
            )
            if issues:
                stale_finding_tests.append(
                    f"{item['finding_id']}:{test['id']} " + "; ".join(issues)
                )
    if stale_finding_tests:
        raise ReviewError(
            "Finding tests are stale or failing at final repair state; refresh exact tests or use evidence-bound pre-verification recovery: "
            + ", ".join(stale_finding_tests)
        )

    stale_global: list[str] = []
    for test in plan["global_tests"]:
        if not test["required"]:
            continue
        runs = state["global_test_results"].get(test["id"], [])
        if not runs:
            stale_global.append(f"{test['id']} not run")
            continue
        latest = runs[-1]
        evidence_result_hash(latest)
        if latest["timed_out"] or latest["exit_code"] != 0:
            stale_global.append(f"{test['id']} failed")
        elif latest["workspace_guard_hash"] != current["guard_hash"]:
            stale_global.append(f"{test['id']} stale after later edits")
        elif latest.get("changed_paths_by_test"):
            stale_global.append(f"{test['id']} mutated workspace")
        elif latest.get("control_mutations_by_test"):
            stale_global.append(f"{test['id']} mutated repository control state")
    if stale_global:
        raise ReviewError("Required global tests are stale or failing: " + ", ".join(stale_global))

    pre_fix_dir = run_dir / state["pre_fix_checkpoint"]
    fix_patch = render_checkpoint_diff(pre_fix_dir, repo, changed_paths)
    atomic_write_text(run_dir / "fix-summary.patch", fix_patch)
    finding_results = {
        finding_id: {
            "status": state["finding_status"][finding_id]["status"],
            "attempts": state["finding_status"][finding_id]["attempts"],
            "history": state["finding_status"][finding_id]["history"],
        }
        for finding_id in state["approved_findings"]
    }
    summary = {
        "schema_version": FIX_SUMMARY_SCHEMA,
        "scope_hash": state["scope_hash"],
        "plan_hash": plan["plan_hash"],
        "approved_findings": state["approved_findings"],
        "changed_paths": sorted(changed_paths),
        "finding_results": finding_results,
        "final_test_refresh_results": state.get("final_test_refresh_results", {}),
        "global_test_results": state["global_test_results"],
        "pre_verification_recovery_history": state.get(
            "pre_verification_recovery_history", []
        ),
        "repair_round": state["repair_round"],
        "prepared_at": utc_now(),
        "fix_patch_sha256": sha256_file(run_dir / "fix-summary.patch"),
    }
    fix_summary_hash = canonical_hash(summary)
    summary["fix_summary_hash"] = fix_summary_hash
    atomic_write_json(run_dir / "fix-summary.json", summary)
    state["phase"] = PHASE_VERIFYING
    state["hashes"]["fix_summary_hash"] = fix_summary_hash
    state["events"].append(
        {
            "at": utc_now(),
            "event": "verification_prepared",
            "fix_summary_hash": fix_summary_hash,
            "changed_paths": sorted(changed_paths),
            "repair_round": state["repair_round"],
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Post-fix verification bundle prepared: {fix_summary_hash}")
    print(f"Changed paths: {', '.join(sorted(changed_paths))}")
    print(f"Bundle: {run_dir / 'fix-summary.json'}")
    return 0


def verify_current_quote(repo: Path, file: str, line_start: int, quote: str) -> None:
    target = repo_path(repo, file)
    if not target.exists() or not target.is_file():
        raise ReviewError(f"Verification evidence file is missing: {file}")
    text = target.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if line_start > len(lines):
        raise ReviewError(f"Verification evidence line exceeds file length: {file}:{line_start}")
    window = "\n".join(lines[max(0, line_start - 2) : min(len(lines), line_start + 4)])
    if quote not in window and quote not in text:
        raise ReviewError(f"Verification evidence quote was not found in current file {file}")


def validate_verification(raw: Any, *, repo: Path, state: dict[str, Any], plan: dict[str, Any], fix_summary: dict[str, Any]) -> dict[str, Any]:
    obj = require_object(raw, "post-fix verification")
    top_keys = {
        "schema_version",
        "scope_hash",
        "plan_hash",
        "fix_summary_hash",
        "verifier_id",
        "independence_group",
        "mode",
        "finding_results",
        "regressions",
        "record_only_observations",
        "verdict",
        "summary",
        "limitations",
    }
    require_exact_keys(obj, top_keys, "post-fix verification")
    if obj["schema_version"] != VERIFICATION_SCHEMA:
        raise ReviewError("Unsupported verification schema_version")
    if obj["scope_hash"] != state["scope_hash"]:
        raise ReviewError("Verification scope_hash does not match the run")
    if obj["plan_hash"] != plan["plan_hash"]:
        raise ReviewError("Verification plan_hash does not match the approved plan")
    if obj["fix_summary_hash"] != fix_summary["fix_summary_hash"]:
        raise ReviewError("Verification fix_summary_hash does not match the prepared fix bundle")
    mode = require_string(obj["mode"], "verification.mode")
    if mode not in VALIDATION_MODES:
        raise ReviewError(f"verification.mode must be one of {sorted(VALIDATION_MODES)}")

    finding_keys = {
        "finding_id",
        "status",
        "root_cause_resolved",
        "reason",
        "evidence_checked",
        "tests_checked",
    }
    finding_results: list[dict[str, Any]] = []
    seen_findings: set[str] = set()
    for index, raw_result in enumerate(require_array(obj["finding_results"], "verification.finding_results")):
        context = f"verification.finding_results[{index}]"
        result = require_object(raw_result, context)
        require_exact_keys(result, finding_keys, context)
        finding_id = require_string(result["finding_id"], f"{context}.finding_id")
        if finding_id in seen_findings:
            raise ReviewError(f"Duplicate verification result for {finding_id}")
        seen_findings.add(finding_id)
        status_value = require_string(result["status"], f"{context}.status")
        if status_value not in {"resolved", "unresolved", "uncertain"}:
            raise ReviewError(f"{context}.status is invalid")
        root_resolved = require_bool(result["root_cause_resolved"], f"{context}.root_cause_resolved")
        if status_value == "resolved" and not root_resolved:
            raise ReviewError(f"{context}: resolved requires root_cause_resolved=true")
        if status_value != "resolved" and root_resolved:
            raise ReviewError(f"{context}: unresolved/uncertain requires root_cause_resolved=false")
        finding_results.append(
            {
                "finding_id": finding_id,
                "status": status_value,
                "root_cause_resolved": root_resolved,
                "reason": require_string(result["reason"], f"{context}.reason"),
                "evidence_checked": require_string_array(result["evidence_checked"], f"{context}.evidence_checked"),
                "tests_checked": require_string_array(result["tests_checked"], f"{context}.tests_checked"),
            }
        )
    approved = set(state["approved_findings"])
    if seen_findings != approved:
        missing = sorted(approved - seen_findings)
        extra = sorted(seen_findings - approved)
        raise ReviewError(
            "Verification must cover every approved finding exactly once"
            + (f"; missing {', '.join(missing)}" if missing else "")
            + (f"; unknown {', '.join(extra)}" if extra else "")
        )

    regression_keys = {
        "regression_id",
        "title",
        "severity",
        "file",
        "line_start",
        "evidence_quote",
        "caused_by_fix",
        "repair_owner_finding_id",
        "repair_paths",
        "reason",
    }
    regressions: list[dict[str, Any]] = []
    regression_ids: set[str] = set()
    for index, raw_regression in enumerate(require_array(obj["regressions"], "verification.regressions")):
        context = f"verification.regressions[{index}]"
        regression = require_object(raw_regression, context)
        require_exact_keys(regression, regression_keys, context)
        regression_id = require_string(regression["regression_id"], f"{context}.regression_id")
        if regression_id in regression_ids or not re.fullmatch(r"R[0-9]{3,}", regression_id):
            raise ReviewError(f"{context}.regression_id must be unique and match R###")
        regression_ids.add(regression_id)
        severity = require_string(regression["severity"], f"{context}.severity")
        if severity not in SEVERITIES:
            raise ReviewError(f"{context}.severity is invalid")
        if require_bool(regression["caused_by_fix"], f"{context}.caused_by_fix") is not True:
            raise ReviewError(f"{context}: only fix-caused regressions belong in regressions")
        owner = require_string(regression["repair_owner_finding_id"], f"{context}.repair_owner_finding_id")
        if owner not in approved:
            raise ReviewError(f"{context}: repair owner {owner} is not an approved finding")
        file = normalize_repo_path(require_string(regression["file"], f"{context}.file"))
        line_start = require_int(regression["line_start"], f"{context}.line_start", minimum=1)
        quote = require_string(regression["evidence_quote"], f"{context}.evidence_quote")
        verify_current_quote(repo, file, line_start, quote)
        repair_paths = [normalize_repo_path(path) for path in require_string_array(regression["repair_paths"], f"{context}.repair_paths")]
        if not repair_paths:
            raise ReviewError(f"{context}.repair_paths must not be empty")
        regressions.append(
            {
                "regression_id": regression_id,
                "title": require_string(regression["title"], f"{context}.title"),
                "severity": severity,
                "file": file,
                "line_start": line_start,
                "evidence_quote": quote,
                "caused_by_fix": True,
                "repair_owner_finding_id": owner,
                "repair_paths": repair_paths,
                "reason": require_string(regression["reason"], f"{context}.reason"),
            }
        )

    observation_keys = {"title", "file", "line_start", "reason"}
    observations: list[dict[str, Any]] = []
    for index, raw_observation in enumerate(
        require_array(obj["record_only_observations"], "verification.record_only_observations")
    ):
        context = f"verification.record_only_observations[{index}]"
        observation = require_object(raw_observation, context)
        require_exact_keys(observation, observation_keys, context)
        observations.append(
            {
                "title": require_string(observation["title"], f"{context}.title"),
                "file": normalize_repo_path(require_string(observation["file"], f"{context}.file")),
                "line_start": require_int(observation["line_start"], f"{context}.line_start", minimum=1),
                "reason": require_string(observation["reason"], f"{context}.reason"),
            }
        )

    verdict = require_string(obj["verdict"], "verification.verdict")
    if verdict not in {"pass", "repair_required", "blocked"}:
        raise ReviewError("verification.verdict must be pass, repair_required, or blocked")
    unresolved = [result for result in finding_results if result["status"] == "unresolved"]
    uncertain = [result for result in finding_results if result["status"] == "uncertain"]
    if verdict == "pass" and (unresolved or uncertain or regressions):
        raise ReviewError("verification.verdict=pass requires all findings resolved and no regressions")
    if verdict == "repair_required" and not (unresolved or regressions):
        raise ReviewError("verification.verdict=repair_required requires an unresolved finding or fix-caused regression")
    if uncertain and verdict != "blocked":
        raise ReviewError("An uncertain post-fix result requires verdict=blocked")

    return {
        "schema_version": VERIFICATION_SCHEMA,
        "scope_hash": state["scope_hash"],
        "plan_hash": plan["plan_hash"],
        "fix_summary_hash": fix_summary["fix_summary_hash"],
        "verifier_id": require_string(obj["verifier_id"], "verification.verifier_id"),
        "independence_group": require_string(obj["independence_group"], "verification.independence_group"),
        "mode": mode,
        "finding_results": finding_results,
        "regressions": regressions,
        "record_only_observations": observations,
        "verdict": verdict,
        "summary": require_string(obj["summary"], "verification.summary"),
        "limitations": require_string_array(obj["limitations"], "verification.limitations"),
    }


def render_verification_markdown(verification: dict[str, Any], final_phase: str, verification_hash: str) -> str:
    lines = [
        "# Post-fix verification",
        "",
        f"- Recorded verdict: `{verification['verdict']}`",
        f"- Controller state: `{final_phase}`",
        f"- Verification hash: `{verification_hash}`",
        f"- Mode: `{verification['mode']}`",
        f"- Verifier: `{verification['verifier_id']}` / `{verification['independence_group']}`",
        "",
        "## Summary",
        "",
        verification["summary"],
        "",
        "## Approved finding results",
        "",
    ]
    for result in verification["finding_results"]:
        lines.extend(
            [
                f"### {result['finding_id']} — {result['status']}",
                "",
                f"- Root cause resolved: `{str(result['root_cause_resolved']).lower()}`",
                f"- Reason: {result['reason']}",
                f"- Evidence checked: {', '.join(result['evidence_checked']) if result['evidence_checked'] else 'none'}",
                f"- Tests checked: {', '.join(result['tests_checked']) if result['tests_checked'] else 'none'}",
                "",
            ]
        )
    lines.extend(["## Fix-caused regressions", ""])
    if not verification["regressions"]:
        lines.append("- none")
    for regression in verification["regressions"]:
        lines.append(
            f"- **{regression['regression_id']}** [{regression['severity']}] `{regression['file']}:{regression['line_start']}` "
            f"owned by `{regression['repair_owner_finding_id']}` — {regression['title']}: {regression['reason']}"
        )
    lines.extend(["", "## Record-only observations", ""])
    if not verification["record_only_observations"]:
        lines.append("- none")
    for observation in verification["record_only_observations"]:
        lines.append(
            f"- `{observation['file']}:{observation['line_start']}` — {observation['title']}: {observation['reason']}"
        )
    if verification["limitations"]:
        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {item}" for item in verification["limitations"])
    return "\n".join(lines) + "\n"


def command_record_verification(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_VERIFYING:
        raise ReviewError(f"record-verification requires phase {PHASE_VERIFYING}; current phase is {state['phase']}")
    ensure_expected_workspace(repo, state)
    plan = load_verified_plan(run_dir, state)
    fix_summary = load_verified_fix_summary(run_dir, state)
    verification = validate_verification(
        load_json(Path(args.input).expanduser().resolve()),
        repo=repo,
        state=state,
        plan=plan,
        fix_summary=fix_summary,
    )
    payload_for_hash = copy.deepcopy(verification)
    verification_hash = canonical_hash(payload_for_hash)
    verification["verification_hash"] = verification_hash
    verification["recorded_at"] = utc_now()
    atomic_write_json(run_dir / "verification.json", verification)
    state["hashes"]["verification_hash"] = verification_hash

    repair_targets = {
        result["finding_id"]
        for result in verification["finding_results"]
        if result["status"] == "unresolved"
    }
    repair_targets.update(regression["repair_owner_finding_id"] for regression in verification["regressions"])
    out_of_plan: list[dict[str, Any]] = []
    exhausted: list[str] = []
    for regression in verification["regressions"]:
        item = plan_item_by_id(plan, regression["repair_owner_finding_id"])
        outside = sorted(set(regression["repair_paths"]) - set(item["allowed_paths"]))
        if outside:
            out_of_plan.append(
                {
                    "regression_id": regression["regression_id"],
                    "repair_owner_finding_id": regression["repair_owner_finding_id"],
                    "outside_paths": outside,
                }
            )
    for finding_id in sorted(repair_targets):
        status = state["finding_status"][finding_id]
        if status["attempts"] >= status["max_attempts"]:
            exhausted.append(finding_id)

    if verification["verdict"] == "pass":
        state["phase"] = PHASE_COMPLETE
        state["repair_targets"] = []
    elif verification["verdict"] == "blocked":
        state["phase"] = PHASE_BLOCKED
        state["repair_targets"] = []
    elif out_of_plan:
        state["phase"] = PHASE_PLAN_AMENDMENT
        state["repair_targets"] = sorted(repair_targets)
    elif exhausted or state["repair_round"] >= plan["max_repair_rounds"]:
        state["phase"] = PHASE_BLOCKED
        state["repair_targets"] = sorted(repair_targets)
    else:
        state["phase"] = PHASE_REPAIR_REQUIRED
        state["repair_targets"] = sorted(repair_targets)

    repair_evaluation = {
        "verification_hash": verification_hash,
        "requested_targets": sorted(repair_targets),
        "out_of_plan": out_of_plan,
        "attempts_exhausted": exhausted,
        "repair_round": state["repair_round"],
        "max_repair_rounds": plan["max_repair_rounds"],
        "next_phase": state["phase"],
        "evaluated_at": utc_now(),
    }
    atomic_write_json(run_dir / "repair-evaluation.json", repair_evaluation)
    atomic_write_text(run_dir / "verification.md", render_verification_markdown(verification, state["phase"], verification_hash))
    state["events"].append(
        {
            "at": utc_now(),
            "event": "verification_recorded",
            "verification_hash": verification_hash,
            "verdict": verification["verdict"],
            "next_phase": state["phase"],
            "repair_targets": sorted(repair_targets),
            "out_of_plan": out_of_plan,
            "attempts_exhausted": exhausted,
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Verification recorded: {verification_hash}")
    print(f"Verifier verdict: {verification['verdict']}")
    print(f"Controller state: {state['phase']}")
    if out_of_plan:
        print("Plan amendment required for paths: " + ", ".join(sorted({path for item in out_of_plan for path in item['outside_paths']})))
    if exhausted:
        print("Attempt budget exhausted: " + ", ".join(exhausted))
    return 0


def resolve_pre_verification_recovery_evidence(
    *,
    repo: Path,
    state: dict[str, Any],
    plan: dict[str, Any],
    current: dict[str, Any],
    evidence_kind: str,
    evidence_id: str,
    evidence_finding: str | None,
    expected_evidence_hash: str,
) -> tuple[dict[str, Any], list[str]]:
    if evidence_kind == "global_test":
        if evidence_finding:
            raise ReviewError("--evidence-finding is not valid for global-test evidence")
        test = test_by_id(plan["global_tests"], evidence_id, "global")
        if not test["required"]:
            raise ReviewError("Pre-verification recovery requires evidence from a required global test")
        runs = state.get("global_test_results", {}).get(evidence_id, [])
        if not runs:
            raise ReviewError(f"No global-test evidence exists for {evidence_id}")
        result = runs[-1]
        result_hash = evidence_result_hash(result)
        if result_hash != expected_evidence_hash:
            raise ReviewError("--evidence-hash does not identify the latest global-test result")
        for key in ("command", "working_directory", "timeout_seconds"):
            if result.get(key) != test[key]:
                raise ReviewError("Latest global-test evidence does not match the Gate-B-approved test definition")
        recoverable_issues: list[str] = []
        if result.get("timed_out"):
            recoverable_issues.append("timed out")
        elif result.get("exit_code") != 0:
            recoverable_issues.append("failed")
        invalid_issues: list[str] = []
        if result.get("changed_paths_by_test"):
            invalid_issues.append("mutated workspace paths")
        if result.get("control_mutations_by_test"):
            invalid_issues.append("mutated repository control state")
        if result.get("boundary_violations"):
            invalid_issues.append("crossed the approved path boundary")
        if invalid_issues:
            raise ReviewError(
                "Latest global-test evidence is not valid recovery evidence: "
                + "; ".join(invalid_issues)
            )
        if result.get("workspace_guard_hash") != current["guard_hash"]:
            recoverable_issues.append("stale after a later workspace edit")
        if not recoverable_issues:
            raise ReviewError("Latest global-test evidence is current and passing; recovery authority is absent")
        return (
            {
                "kind": evidence_kind,
                "test_id": evidence_id,
                "finding_id": None,
                "source": "global_test_results",
                "result_hash": result_hash,
            },
            recoverable_issues,
        )

    if evidence_kind != "finding_test":
        raise ReviewError("--evidence-kind must be finding_test or global_test")
    if not evidence_finding:
        raise ReviewError("--evidence-finding is required for finding-test evidence")
    if evidence_finding not in state["approved_findings"]:
        raise ReviewError(f"Evidence finding {evidence_finding} was not approved at Gate A")
    item = plan_item_by_id(plan, evidence_finding)
    test = test_by_id(item["tests"], evidence_id, evidence_finding)
    if not test["required"]:
        raise ReviewError("Pre-verification recovery requires evidence from a required finding test")
    source, result, attempt = latest_finding_test_evidence(
        state,
        finding_id=evidence_finding,
        test_id=evidence_id,
    )
    result_hash = evidence_result_hash(result)
    if result_hash != expected_evidence_hash:
        raise ReviewError("--evidence-hash does not identify the latest finding-test result")
    issues = finding_test_evidence_issues(
        repo=repo,
        current=current,
        item=item,
        test=test,
        source=source,
        result=result,
        attempt=attempt,
    )
    invalid_evidence = [
        issue
        for issue in issues
        if issue
        in {
            "mutated workspace paths",
            "mutated repository control state",
            "crossed the approved path boundary",
        }
        or "does not match the approved" in issue
        or "different approved test definition" in issue
        or "superseded retained attempt" in issue
    ]
    if invalid_evidence:
        raise ReviewError(
            "Latest finding-test evidence is not valid recovery evidence: "
            + "; ".join(invalid_evidence)
        )
    if not issues:
        raise ReviewError("Latest finding-test evidence is current and passing; recovery authority is absent")
    return (
        {
            "kind": evidence_kind,
            "test_id": evidence_id,
            "finding_id": evidence_finding,
            "source": source,
            "result_hash": result_hash,
            "retained_attempt_hash": attempt["attempt_hash"],
        },
        issues,
    )


def command_begin_pre_verification_repair(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_FIXING or state.get("active_finding") is not None:
        raise ReviewError(
            "begin-pre-verification-repair requires FIXING phase with no active finding"
        )
    if not all_findings_fixed(state):
        raise ReviewError("Pre-verification recovery requires every approved finding to be fixed")
    reason = require_string(args.reason, "--reason")
    evidence_id = require_string(args.evidence_id, "--evidence-id")
    evidence_hash = require_string(args.evidence_hash, "--evidence-hash")
    targets = [require_string(value, "--finding") for value in args.finding]
    if len(set(targets)) != len(targets):
        raise ReviewError("Pre-verification recovery target IDs must be unique")

    plan = load_verified_plan(run_dir, state)
    current, _, outside = overall_repair_boundary(repo, run_dir, state, plan)
    if outside:
        raise ReviewError("Aggregate repair delta contains unapproved paths: " + ", ".join(sorted(outside)))
    if state["repair_round"] >= plan["max_repair_rounds"]:
        raise ReviewError("Post-fix repair-round budget is exhausted")
    for finding_id in targets:
        if finding_id not in state["approved_findings"]:
            raise ReviewError(f"Finding {finding_id} was not approved at Gate A")
        plan_item_by_id(plan, finding_id)
        status = state["finding_status"].get(finding_id)
        if not status or status["status"] != "fixed":
            raise ReviewError(f"Recovery target {finding_id} is not currently fixed")
        if status["attempts"] >= status["max_attempts"]:
            raise ReviewError(f"Finding {finding_id} has no remaining approved attempts")

    evidence, evidence_issues = resolve_pre_verification_recovery_evidence(
        repo=repo,
        state=state,
        plan=plan,
        current=current,
        evidence_kind=args.evidence_kind,
        evidence_id=evidence_id,
        evidence_finding=args.evidence_finding,
        expected_evidence_hash=evidence_hash,
    )
    if evidence["kind"] == "finding_test" and evidence["finding_id"] not in targets:
        raise ReviewError("A finding-test recovery must include its evidence owner as a repair target")

    next_round = state["repair_round"] + 1
    recovery = {
        "schema_version": "material-review/pre-verification-recovery/v1",
        "scope_hash": state["scope_hash"],
        "plan_hash": plan["plan_hash"],
        "repair_round": next_round,
        "evidence": evidence,
        "evidence_issues": evidence_issues,
        "targets": targets,
        "reason": reason,
        "workspace_guard_hash": current["guard_hash"],
        "recorded_at": utc_now(),
    }
    recovery["recovery_hash"] = canonical_hash(recovery)
    history = state.setdefault("pre_verification_recovery_history", [])
    history.append(recovery)
    recovery_dir = run_dir / "pre-verification-recovery"
    atomic_write_json(recovery_dir / f"round-{next_round}.json", recovery)
    for finding_id in targets:
        state["finding_status"][finding_id]["status"] = "repair_pending"
    state["repair_round"] = next_round
    state["repair_targets"] = targets
    state["expected_workspace_guard_hash"] = current["guard_hash"]
    state["events"].append(
        {
            "at": utc_now(),
            "event": "pre_verification_repair_started",
            "repair_round": next_round,
            "targets": targets,
            "evidence": evidence,
            "evidence_issues": evidence_issues,
            "recovery_hash": recovery["recovery_hash"],
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Began evidence-bound pre-verification repair round {next_round}")
    print("Targets: " + ", ".join(targets))
    print(f"Evidence hash: {evidence['result_hash']}")
    print(f"Recovery artifact: {recovery_dir / f'round-{next_round}.json'}")
    return 0


def command_begin_repair(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_REPAIR_REQUIRED:
        raise ReviewError(f"begin-repair requires phase {PHASE_REPAIR_REQUIRED}; current phase is {state['phase']}")
    current = ensure_expected_workspace(repo, state)
    plan = load_verified_plan(run_dir, state)
    if state["repair_round"] >= plan["max_repair_rounds"]:
        state["phase"] = PHASE_BLOCKED
        save_state(run_dir, state)
        raise ReviewError("Post-fix repair-round budget is exhausted")
    targets = state.get("repair_targets", [])
    if not targets:
        raise ReviewError("No repair targets were recorded")
    next_round = state["repair_round"] + 1
    history_dir = run_dir / "verification-history" / f"round-{state['repair_round']}"
    history_dir.mkdir(parents=True, exist_ok=True)
    for name in ("fix-summary.json", "fix-summary.patch", "verification.json", "verification.md", "repair-evaluation.json"):
        source = run_dir / name
        if source.exists():
            shutil.copy2(source, history_dir / name)
    for finding_id in targets:
        status = state["finding_status"][finding_id]
        if status["attempts"] >= status["max_attempts"]:
            state["phase"] = PHASE_BLOCKED
            save_state(run_dir, state)
            raise ReviewError(f"Finding {finding_id} has no remaining approved attempts")
        status["status"] = "repair_pending"
    state["repair_round"] = next_round
    state["phase"] = PHASE_FIXING
    state["active_finding"] = None
    state["expected_workspace_guard_hash"] = current["guard_hash"]
    state["events"].append(
        {
            "at": utc_now(),
            "event": "repair_round_started",
            "repair_round": next_round,
            "targets": targets,
        }
    )
    save_state(run_dir, state)
    print(f"[OK] Began bounded repair round {next_round}")
    print("Targets: " + ", ".join(targets))
    return 0


def state_summary(state: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    return {
        "run_id": state["run_id"],
        "phase": state["phase"],
        "repo_root": state["repo_root"],
        "artifact_directory": str(run_dir),
        "scope_hash": state["scope_hash"],
        "hashes": state["hashes"],
        "gates": state["gates"],
        "approved_findings": state["approved_findings"],
        "finding_status": {
            finding_id: {
                "status": record["status"],
                "attempts": record["attempts"],
                "max_attempts": record["max_attempts"],
            }
            for finding_id, record in state.get("finding_status", {}).items()
        },
        "active_finding": state.get("active_finding"),
        "final_test_refresh_results": state.get("final_test_refresh_results", {}),
        "repair_round": state.get("repair_round", 0),
        "repair_targets": state.get("repair_targets", []),
        "pre_verification_recovery_history": state.get(
            "pre_verification_recovery_history", []
        ),
        "updated_at": state["updated_at"],
    }


def command_status(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    summary = state_summary(state, run_dir)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    print(f"Run ID: {summary['run_id']}")
    print(f"Phase: {summary['phase']}")
    print(f"Scope hash: {summary['scope_hash']}")
    print(f"Artifact directory: {summary['artifact_directory']}")
    print(f"Approved findings: {', '.join(summary['approved_findings']) if summary['approved_findings'] else 'none'}")
    if summary["finding_status"]:
        print("Finding status:")
        for finding_id, record in sorted(summary["finding_status"].items()):
            print(
                f"  - {finding_id}: {record['status']} "
                f"(attempts {record['attempts']}/{record['max_attempts']})"
            )
    if summary["repair_targets"]:
        print("Repair targets: " + ", ".join(summary["repair_targets"]))
    return 0


def add_common_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", default=".", help="Path inside the Git repository (default: current directory).")
    parser.add_argument("--artifact-root", default="", help="Override the local artifact root. Default: git rev-parse --git-path material-code-review.")
    parser.add_argument("--run-id", default="", help="Run ID. May also be supplied through MATERIAL_REVIEW_RUN_ID.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evidence and state controller for the material-code-review skill.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {TOOL_VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Resolve, freeze, hash, and snapshot the review scope.")
    init_parser.add_argument("--repo-root", default=".")
    init_parser.add_argument("--artifact-root", default="")
    init_parser.add_argument("--run-id", default="")
    init_parser.add_argument(
        "--scope",
        choices=["auto", "uncommitted", "branch", "pull_request", "range"],
        default="auto",
    )
    init_parser.add_argument("--base", default="", help="Base ref for branch/range scope.")
    init_parser.add_argument("--head", default="", help="Head ref for range scope.")
    init_parser.add_argument("--review-object-kind", choices=["pull_request"], default="")
    init_parser.add_argument("--review-object-id", default="")
    init_parser.add_argument("--review-base-sha", default="")
    init_parser.add_argument("--review-head-sha", default="")
    init_parser.add_argument("--exclude-untracked", action="store_true", help="Explicitly exclude untracked files from working-tree scope.")
    init_parser.add_argument("--max-snapshot-file-bytes", type=int, default=2 * 1024 * 1024)
    init_parser.add_argument("--max-snapshot-total-bytes", type=int, default=25 * 1024 * 1024)
    init_parser.set_defaults(func=command_init)

    check_parser = subparsers.add_parser("check-scope", help="Recompute and compare the frozen scope hash.")
    add_common_run_options(check_parser)
    check_parser.set_defaults(func=command_check_scope)

    coverage_parser = subparsers.add_parser(
        "record-coverage", help="Validate and record the root-owned review coverage plan."
    )
    add_common_run_options(coverage_parser)
    coverage_parser.add_argument("--input", required=True, help="Coverage-plan JSON path.")
    coverage_parser.set_defaults(func=command_record_coverage)

    failure_parser = subparsers.add_parser(
        "record-reviewer-failure",
        help="Attest root-observed no-output failure for one assigned review route.",
    )
    add_common_run_options(failure_parser)
    failure_parser.add_argument("--lens", required=True, help="Coverage-plan lens ID.")
    failure_parser.add_argument("--route", choices=sorted(PREFLIGHT_ROUTES), required=True)
    failure_parser.add_argument(
        "--reason", choices=sorted(REVIEWER_FAILURE_REASONS), required=True
    )
    failure_parser.add_argument(
        "--diagnostic",
        action="append",
        default=[],
        help="Controlled CODE=INTEGER metadata; repeat at most eight times.",
    )
    failure_parser.add_argument(
        "--observer-kind", choices=sorted(FAILURE_OBSERVER_KINDS), required=True
    )
    failure_parser.add_argument("--observer-id", required=True)
    failure_parser.set_defaults(func=command_record_reviewer_failure)

    fallback_parser = subparsers.add_parser(
        "assign-fallback",
        help="Record the root-owned actual reviewer assignment for a failed required lens.",
    )
    add_common_run_options(fallback_parser)
    fallback_parser.add_argument("--lens", required=True, help="Coverage-plan lens ID.")
    fallback_parser.add_argument(
        "--failure-trigger-kind",
        choices=sorted(FALLBACK_TRIGGER_KINDS),
        required=True,
    )
    fallback_parser.add_argument("--failure-trigger-hash", required=True)
    fallback_parser.add_argument("--reviewer-id", required=True)
    fallback_parser.add_argument("--independence-group", required=True)
    fallback_parser.add_argument("--review-mode", choices=sorted(REVIEW_MODES), required=True)
    fallback_parser.set_defaults(func=command_assign_fallback)

    preflight_parser = subparsers.add_parser(
        "check-candidates", help="Preflight one assigned candidate draft."
    )
    add_common_run_options(preflight_parser)
    preflight_parser.add_argument("--lens", required=True, help="Coverage-plan lens ID.")
    preflight_parser.add_argument("--input", required=True, help="Candidate-set JSON path.")
    preflight_parser.add_argument("--fallback", action="store_true")
    preflight_parser.add_argument("--supersedes", default=None, help="Exact prior receipt hash.")
    preflight_parser.set_defaults(func=command_check_candidates)

    ingest_parser = subparsers.add_parser("ingest-candidates", help="Validate and normalize candidate reviewer JSON outputs.")
    add_common_run_options(ingest_parser)
    ingest_parser.add_argument("--input", action="append", required=True, help="Candidate-set JSON path. Repeat for each reviewer.")
    ingest_parser.set_defaults(func=command_ingest_candidates)

    finalize_coverage_parser = subparsers.add_parser(
        "finalize-coverage",
        help="Finalize fully exhausted required review routes as REVIEW_INCOMPLETE.",
    )
    add_common_run_options(finalize_coverage_parser)
    finalize_coverage_parser.set_defaults(func=command_finalize_coverage)

    ledger_parser = subparsers.add_parser("compile-ledger", help="Validate adjudication and create the kept/discarded ledger.")
    add_common_run_options(ledger_parser)
    ledger_parser.add_argument("--input", required=True, help="Adjudication JSON path.")
    ledger_parser.set_defaults(func=command_compile_ledger)

    findings_gate_parser = subparsers.add_parser("gate-findings", help="Record the mandatory Gate A user decisions.")
    add_common_run_options(findings_gate_parser)
    findings_gate_parser.add_argument("--approve", action="append", default=[], help="Comma-separated kept finding IDs to approve.")
    findings_gate_parser.add_argument("--reject", action="append", default=[], help="Comma-separated kept finding IDs to reject.")
    findings_gate_parser.add_argument("--defer", action="append", default=[], help="Comma-separated kept finding IDs to defer.")
    findings_gate_parser.add_argument("--accept-empty", action="store_true", help="Accept a ledger with no kept findings.")
    findings_gate_parser.add_argument("--user-statement", required=True, help="Exact or faithful user decision statement.")
    findings_gate_parser.set_defaults(func=command_gate_findings)

    plan_parser = subparsers.add_parser("validate-plan", help="Validate an exact repair plan for Gate-A-approved findings.")
    add_common_run_options(plan_parser)
    plan_parser.add_argument("--input", required=True, help="Fix-plan JSON path.")
    plan_parser.set_defaults(func=command_validate_plan)

    plan_gate_parser = subparsers.add_parser("gate-plan", help="Record the mandatory Gate B decision for the exact plan hash.")
    add_common_run_options(plan_gate_parser)
    decision_group = plan_gate_parser.add_mutually_exclusive_group(required=True)
    decision_group.add_argument("--approve", action="store_true")
    decision_group.add_argument("--reject", action="store_true")
    plan_gate_parser.add_argument("--user-statement", required=True)
    plan_gate_parser.set_defaults(func=command_gate_plan)

    begin_fix_parser = subparsers.add_parser("begin-fix", help="Capture the pre-fix checkpoint after Gate B.")
    add_common_run_options(begin_fix_parser)
    begin_fix_parser.set_defaults(func=command_begin_fix)

    start_parser = subparsers.add_parser("start-finding", help="Start a checkpointed attempt for one approved finding.")
    add_common_run_options(start_parser)
    start_parser.add_argument("--finding", required=True)
    start_parser.set_defaults(func=command_start_finding)

    run_test_parser = subparsers.add_parser("run-test", help="Run one Gate-B-approved finding test and log it.")
    add_common_run_options(run_test_parser)
    run_test_parser.add_argument("--finding", required=True)
    run_test_parser.add_argument("--test", required=True)
    run_test_parser.set_defaults(func=command_run_test)

    finish_parser = subparsers.add_parser("finish-finding", help="Retain a verified attempt or mark a restored finding blocked.")
    add_common_run_options(finish_parser)
    finish_parser.add_argument("--finding", required=True)
    finish_parser.add_argument("--status", choices=["fixed", "blocked"], required=True)
    finish_parser.add_argument("--note", required=True)
    finish_parser.add_argument("--manual-evidence", action="append", default=[])
    finish_parser.add_argument("--allow-no-change", action="store_true")
    finish_parser.set_defaults(func=command_finish_finding)

    rollback_parser = subparsers.add_parser("rollback-finding", help="Restore the active finding checkpoint.")
    add_common_run_options(rollback_parser)
    rollback_parser.add_argument("--finding", required=True)
    rollback_parser.add_argument("--reason", required=True)
    rollback_parser.set_defaults(func=command_rollback_finding)

    global_test_parser = subparsers.add_parser("run-global-test", help="Run a Gate-B-approved global validation command.")
    add_common_run_options(global_test_parser)
    global_test_parser.add_argument("--test", required=True)
    global_test_parser.set_defaults(func=command_run_global_test)

    refresh_parser = subparsers.add_parser(
        "refresh-finding-test",
        help="Refresh one required Gate-B-approved finding test at the final repair state.",
    )
    add_common_run_options(refresh_parser)
    refresh_parser.add_argument("--finding", required=True)
    refresh_parser.add_argument("--test", required=True)
    refresh_parser.set_defaults(func=command_refresh_finding_test)

    prepare_parser = subparsers.add_parser("prepare-verification", help="Create the bounded fix-only verification bundle.")
    add_common_run_options(prepare_parser)
    prepare_parser.set_defaults(func=command_prepare_verification)

    record_parser = subparsers.add_parser("record-verification", help="Validate and record bounded post-fix verification.")
    add_common_run_options(record_parser)
    record_parser.add_argument("--input", required=True, help="Verification JSON path.")
    record_parser.set_defaults(func=command_record_verification)

    repair_parser = subparsers.add_parser("begin-repair", help="Begin one bounded in-plan post-fix repair round.")
    add_common_run_options(repair_parser)
    repair_parser.set_defaults(func=command_begin_repair)

    pre_verification_repair_parser = subparsers.add_parser(
        "begin-pre-verification-repair",
        help="Begin one evidence-bound in-plan repair round before verification.",
    )
    add_common_run_options(pre_verification_repair_parser)
    pre_verification_repair_parser.add_argument(
        "--finding", action="append", required=True, help="Exact approved repair target; repeat as needed."
    )
    pre_verification_repair_parser.add_argument(
        "--evidence-kind", choices=["finding_test", "global_test"], required=True
    )
    pre_verification_repair_parser.add_argument("--evidence-id", required=True)
    pre_verification_repair_parser.add_argument("--evidence-finding", default=None)
    pre_verification_repair_parser.add_argument("--evidence-hash", required=True)
    pre_verification_repair_parser.add_argument("--reason", required=True)
    pre_verification_repair_parser.set_defaults(func=command_begin_pre_verification_repair)

    abort_parser = subparsers.add_parser("abort-fixes", help="Restore the complete pre-fix checkpoint and stop.")
    add_common_run_options(abort_parser)
    abort_parser.add_argument("--reason", required=True)
    abort_parser.set_defaults(func=command_abort_fixes)

    status_parser = subparsers.add_parser("status", help="Show the active run state.")
    add_common_run_options(status_parser)
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(func=command_status)

    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    workflow_profile: str = WORKFLOW_PROFILE_REVIEW,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "base") and args.base == "":
        args.base = None
    if hasattr(args, "head") and args.head == "":
        args.head = None
    if hasattr(args, "artifact_root") and args.artifact_root == "":
        args.artifact_root = None
    if hasattr(args, "run_id") and args.run_id == "":
        args.run_id = None
    try:
        if workflow_profile not in WORKFLOW_PROFILES:
            raise ReviewError(f"Unsupported root-owned workflow profile: {workflow_profile}")
        args.workflow_profile = workflow_profile
        return int(args.func(args))
    except ReviewError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("[FAIL] Interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
