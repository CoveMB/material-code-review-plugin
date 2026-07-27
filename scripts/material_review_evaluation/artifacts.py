from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from .model import (
    EvaluationError,
    atomic_write_json,
    canonical_hash,
    safe_relative_path,
    sha256_file,
)
from .workspace import WorkspaceRecord, _run_checked, attest_clean_target


NATIVE_SCHEMA_PROFILES = {
    (
        "material-review/state/v1",
        "material-review/ledger/v1",
        "material-review/fix-plan/v1",
    ),
    (
        "material-review/state/v1",
        "material-review/ledger/v2",
        "material-review/fix-plan/v1",
    ),
    (
        "material-review/state/v1",
        "material-review/ledger/v3",
        "material-review/fix-plan/v2",
    ),
}

_PROFILE_BY_LEDGER = {profile[1]: profile for profile in NATIVE_SCHEMA_PROFILES}
_FINDINGS_GATE_SCHEMA = "material-review/findings-gate/v1"
_PLAN_GATE_SCHEMA = "material-review/plan-gate/v1"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CONTROLLER_TIMEOUT_SECONDS = 30
_REPAIR_PHASES = {
    "FIXING",
    "VERIFYING",
    "REPAIR_REQUIRED",
    "PLAN_AMENDMENT_REQUIRED",
    "BLOCKED",
}
_GATE_A_APPROVAL = (
    "Evaluation policy approves every retained finding for planning and no others; "
    "repair is not authorized."
)
_EMPTY_LEDGER_APPROVAL = (
    "Evaluation policy accepts the empty material ledger; repair is not authorized."
)
_GATE_B_APPROVAL = (
    "Evaluation policy approves this exact validated plan for comparison evidence only; "
    "no repair or plan command execution is authorized."
)


@dataclass(frozen=True)
class NativeTrialArtifacts:
    run_directory: Path
    controller: Path
    target: WorkspaceRecord
    schema_profile: tuple[str, str, str]
    state: dict[str, Any]
    scope: dict[str, Any]
    adjudication: dict[str, Any]
    ledger: dict[str, Any]
    findings_gate: dict[str, Any] | None
    plan: dict[str, Any] | None
    plan_gate: dict[str, Any] | None
    controller_status: dict[str, Any]
    scope_freshness: dict[str, Any]
    cleanliness_attestation: dict[str, object]
    native_files: tuple[Path, ...]


@dataclass(frozen=True)
class EvaluationGateCommand:
    argv: tuple[str, ...]
    approved_ids: tuple[str, ...]
    plan_hash: str | None = None


def _require_object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvaluationError(f"{context} must be a JSON object")
    return value


def _require_array(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise EvaluationError(f"{context} must be a JSON array")
    return value


def _require_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvaluationError(f"{context} must be a non-empty string")
    return value


def _require_sha256(value: Any, context: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise EvaluationError(f"{context} must be a lowercase SHA-256 digest")
    return value


def _load_json_object(path: Path, context: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise EvaluationError(f"required native artifact is missing: {path.name}")
    try:
        return _require_object(json.loads(path.read_text(encoding="utf-8")), context)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvaluationError(f"native artifact is unreadable: {path.name}") from error


def _embedded_hash(
    artifact: Mapping[str, Any],
    *,
    hash_field: str,
    omitted_fields: Sequence[str],
    context: str,
) -> str:
    expected = _require_sha256(artifact.get(hash_field), f"{context} hash")
    payload = copy.deepcopy(dict(artifact))
    payload.pop(hash_field, None)
    for field in omitted_fields:
        payload.pop(field, None)
    actual = canonical_hash(payload)
    if actual != expected:
        raise EvaluationError(
            f"{context} hash does not match canonical native JSON: "
            f"recorded {expected}, recomputed {actual}"
        )
    return expected


def _scope_identity_hash(scope: Mapping[str, Any]) -> str:
    identity = copy.deepcopy(_require_object(scope.get("identity"), "scope.identity"))
    files = _require_array(identity.get("files"), "scope.identity.files")
    for raw_entry in files:
        entry = _require_object(raw_entry, "scope.identity.files entry")
        for state_key in ("baseline_state", "comparison_state"):
            state = entry.get(state_key)
            if isinstance(state, dict):
                state.pop("snapshot_path", None)
    return canonical_hash(identity)


def _run_root(path: Path) -> Path:
    supplied = Path(path)
    if supplied.is_symlink() or not supplied.is_dir():
        raise EvaluationError("native review run directory is missing or symlinked")
    resolved = supplied.resolve(strict=True)
    if resolved.parent.name != "runs":
        raise EvaluationError("native review run must be an immediate child of a runs directory")
    return resolved


def _controller_path(path: Path) -> Path:
    supplied = Path(path)
    if supplied.is_symlink() or not supplied.is_file():
        raise EvaluationError("materialized native controller is missing or symlinked")
    return supplied.resolve(strict=True)


def _native_inventory(run_directory: Path) -> dict[str, str]:
    inventory: dict[str, str] = {}
    for path in sorted(run_directory.rglob("*")):
        relative = path.relative_to(run_directory).as_posix()
        if path.is_symlink():
            raise EvaluationError(f"native artifact tree contains a symlink: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise EvaluationError(f"native artifact tree contains a special file: {relative}")
        inventory[relative] = sha256_file(path)
    return inventory


def find_native_run(trial_root: Path) -> Path:
    """Find the one controller-native run without guessing from Markdown."""

    supplied = Path(trial_root)
    if supplied.is_symlink() or not supplied.is_dir():
        raise EvaluationError("trial root is missing or symlinked")
    root = supplied.resolve(strict=True)
    candidates: list[Path] = []
    for state_path in root.rglob("state.json"):
        if state_path.parent.parent.name != "runs":
            continue
        if state_path.is_symlink() or state_path.parent.is_symlink():
            raise EvaluationError("native review run contains a symlinked state artifact")
        candidates.append(state_path.parent.resolve(strict=True))
    unique = sorted(set(candidates))
    if not unique:
        raise EvaluationError("no native review run was found")
    if len(unique) != 1:
        raise EvaluationError("multiple native review runs were found; discovery is ambiguous")
    return unique[0]


def _reject_repair_phase(state: Mapping[str, Any]) -> str:
    phase = _require_string(state.get("phase"), "state.phase")
    if phase in _REPAIR_PHASES:
        raise EvaluationError(
            f"native run entered repair phase {phase}; mutation evidence is invalid"
        )
    return phase


def _validate_scope_and_ledger(
    state: dict[str, Any],
    scope: dict[str, Any],
    ledger: dict[str, Any],
) -> tuple[tuple[str, str, str], str, str]:
    state_schema = _require_string(state.get("schema_version"), "state.schema_version")
    scope_hash = _require_sha256(scope.get("scope_hash"), "scope hash")
    recomputed_scope_hash = _scope_identity_hash(scope)
    if scope_hash != recomputed_scope_hash:
        raise EvaluationError("scope hash does not match the embedded frozen identity")
    if state.get("scope_hash") != scope_hash:
        raise EvaluationError("scope hash does not match state.scope_hash")

    ledger_schema = _require_string(
        ledger.get("schema_version"),
        "ledger.schema_version",
    )
    profile = _PROFILE_BY_LEDGER.get(ledger_schema)
    if profile is None or profile[0] != state_schema or profile not in NATIVE_SCHEMA_PROFILES:
        raise EvaluationError(
            f"unsupported native schema profile: {(state_schema, ledger_schema)!r}"
        )
    ledger_hash = _embedded_hash(
        ledger,
        hash_field="ledger_hash",
        omitted_fields=("generated_at",),
        context="ledger",
    )
    hashes = _require_object(state.get("hashes"), "state.hashes")
    if hashes.get("ledger_hash") != ledger_hash:
        raise EvaluationError("ledger hash does not match state.hashes.ledger_hash")
    if ledger.get("scope_hash") != scope_hash:
        raise EvaluationError("ledger scope hash does not match the frozen scope")
    return profile, scope_hash, ledger_hash


def _validate_complete_disposition(
    adjudication: dict[str, Any],
    ledger: dict[str, Any],
) -> tuple[str, ...]:
    raw_groups = _require_array(adjudication.get("groups"), "adjudication.groups")
    adjudicated: dict[str, str] = {}
    for raw_group in raw_groups:
        group = _require_object(raw_group, "adjudication group")
        group_id = _require_string(group.get("group_id"), "adjudication group_id")
        disposition = _require_string(
            group.get("disposition"),
            f"candidate group {group_id} disposition",
        )
        if disposition not in {"keep", "discard"}:
            raise EvaluationError(f"candidate group {group_id} has an invalid disposition")
        if group_id in adjudicated:
            raise EvaluationError(f"candidate group {group_id} is adjudicated more than once")
        adjudicated[group_id] = disposition

    findings = _require_array(ledger.get("findings"), "ledger.findings")
    finding_ids: list[str] = []
    kept_groups: list[str] = []
    for raw_finding in findings:
        finding = _require_object(raw_finding, "ledger finding")
        finding_ids.append(_require_string(finding.get("finding_id"), "finding_id"))
        kept_groups.append(_require_string(finding.get("group_id"), "finding group_id"))
    if len(finding_ids) != len(set(finding_ids)):
        raise EvaluationError("retained finding IDs must be unique")

    discarded_groups = [
        _require_string(
            _require_object(raw_group, "discarded candidate group").get("group_id"),
            "discarded candidate group_id",
        )
        for raw_group in _require_array(ledger.get("discarded"), "ledger.discarded")
    ]
    disposed_groups = [*kept_groups, *discarded_groups]
    if len(disposed_groups) != len(set(disposed_groups)):
        raise EvaluationError("a candidate group is kept or discarded more than once")
    if set(disposed_groups) != set(adjudicated):
        raise EvaluationError("every candidate group must be kept or discarded exactly once")
    for group_id in kept_groups:
        if adjudicated[group_id] != "keep":
            raise EvaluationError(f"candidate group {group_id} disposition conflicts with ledger")
    for group_id in discarded_groups:
        if adjudicated[group_id] != "discard":
            raise EvaluationError(f"candidate group {group_id} disposition conflicts with ledger")
    return tuple(sorted(finding_ids))


def _native_controller_evidence(
    run_directory: Path,
    controller: Path,
    target: WorkspaceRecord,
    state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, object], tuple[Path, ...]]:
    if not isinstance(target, WorkspaceRecord):
        raise EvaluationError("native artifact validation requires a recorded trial target")
    cleanliness = attest_clean_target(target)
    before = _native_inventory(run_directory)
    run_id = _require_string(state.get("run_id"), "state.run_id")
    if run_directory.name != run_id:
        raise EvaluationError("native run directory does not match its recorded run ID")
    artifact_root = run_directory.parent.parent
    common = (
        "--repo-root",
        str(target.path),
        "--artifact-root",
        str(artifact_root),
        "--run-id",
        run_id,
    )
    scope_result = _run_checked(
        (sys.executable, str(controller), "check-scope", *common),
        working_directory=target.path,
        timeout_seconds=_CONTROLLER_TIMEOUT_SECONDS,
        context="native controller check-scope",
    )
    status_result = _run_checked(
        (sys.executable, str(controller), "status", *common, "--json"),
        working_directory=target.path,
        timeout_seconds=_CONTROLLER_TIMEOUT_SECONDS,
        context="native controller status",
    )
    try:
        status = _require_object(json.loads(status_result.stdout), "controller status")
    except json.JSONDecodeError as error:
        raise EvaluationError("native controller status did not return JSON") from error
    expected_status = {
        "run_id": state.get("run_id"),
        "phase": state.get("phase"),
        "scope_hash": state.get("scope_hash"),
        "hashes": state.get("hashes"),
        "gates": state.get("gates"),
        "approved_findings": state.get("approved_findings"),
    }
    for key, expected in expected_status.items():
        if status.get(key) != expected:
            raise EvaluationError(f"native controller status disagrees with state.{key}")
    try:
        status_directory = Path(_require_string(status.get("artifact_directory"), "status artifact_directory")).resolve(strict=True)
    except OSError as error:
        raise EvaluationError("native controller status returned an invalid artifact directory") from error
    if status_directory != run_directory:
        raise EvaluationError("native controller status returned a different artifact directory")
    after = _native_inventory(run_directory)
    if after != before:
        raise EvaluationError("native controller authority checks modified native artifacts")
    freshness = {
        "fresh": True,
        "scope_hash": state["scope_hash"],
        "controller_stdout_sha256": hashlib.sha256(
            scope_result.stdout.encode("utf-8")
        ).hexdigest(),
    }
    native_files = tuple(run_directory / relative for relative in sorted(after))
    return status, freshness, cleanliness, native_files


def _load_core_artifacts(
    run_directory: Path,
    controller: Path,
    target: WorkspaceRecord,
) -> tuple[NativeTrialArtifacts, str, tuple[str, ...]]:
    run = _run_root(run_directory)
    materialized_controller = _controller_path(controller)
    state = _load_json_object(run / "state.json", "state")
    phase = _reject_repair_phase(state)
    scope = _load_json_object(run / "scope.json", "scope")
    ledger = _load_json_object(run / "ledger.json", "ledger")
    adjudication = _load_json_object(
        run / "adjudication.normalized.json",
        "normalized adjudication",
    )
    profile, _, _ = _validate_scope_and_ledger(state, scope, ledger)
    retained_ids = _validate_complete_disposition(adjudication, ledger)
    status, freshness, cleanliness, native_files = _native_controller_evidence(
        run,
        materialized_controller,
        target,
        state,
    )
    artifacts = NativeTrialArtifacts(
        run_directory=run,
        controller=materialized_controller,
        target=target,
        schema_profile=profile,
        state=state,
        scope=scope,
        adjudication=adjudication,
        ledger=ledger,
        findings_gate=None,
        plan=None,
        plan_gate=None,
        controller_status=status,
        scope_freshness=freshness,
        cleanliness_attestation=cleanliness,
        native_files=native_files,
    )
    return artifacts, phase, retained_ids


def _validate_findings_gate(
    artifacts: NativeTrialArtifacts,
    retained_ids: tuple[str, ...],
) -> dict[str, Any]:
    receipt = _load_json_object(
        artifacts.run_directory / "gates" / "findings.json",
        "Gate A receipt",
    )
    if receipt.get("schema_version") != _FINDINGS_GATE_SCHEMA:
        raise EvaluationError("Gate A receipt schema is not supported")
    receipt_hash = _embedded_hash(
        receipt,
        hash_field="receipt_hash",
        omitted_fields=(),
        context="Gate A receipt",
    )
    hashes = _require_object(artifacts.state.get("hashes"), "state.hashes")
    gates = _require_object(artifacts.state.get("gates"), "state.gates")
    if (
        hashes.get("findings_gate_hash") != receipt_hash
        or gates.get("findings") != receipt_hash
    ):
        raise EvaluationError("Gate A receipt hash does not match state gate hashes")
    if receipt.get("run_id") != artifacts.state.get("run_id"):
        raise EvaluationError("Gate A receipt belongs to a different native run")
    if receipt.get("scope_hash") != artifacts.state.get("scope_hash"):
        raise EvaluationError("Gate A receipt scope hash does not match state")
    if receipt.get("ledger_hash") != artifacts.ledger.get("ledger_hash"):
        raise EvaluationError("Gate A receipt ledger hash does not match the native ledger")
    decisions = _require_object(receipt.get("decisions"), "Gate A decisions")
    approved = _require_array(decisions.get("approved"), "Gate A approved IDs")
    rejected = _require_array(decisions.get("rejected"), "Gate A rejected IDs")
    deferred = _require_array(decisions.get("deferred"), "Gate A deferred IDs")
    for values, context in (
        (approved, "approved"),
        (rejected, "rejected"),
        (deferred, "deferred"),
    ):
        if any(not isinstance(value, str) or not value for value in values):
            raise EvaluationError(f"Gate A {context} IDs must be non-empty strings")
        if len(values) != len(set(values)):
            raise EvaluationError(f"Gate A {context} IDs must be unique")
    if retained_ids:
        if (
            tuple(sorted(approved)) != retained_ids
            or rejected
            or deferred
            or decisions.get("accepted_empty") is not False
        ):
            raise EvaluationError("Gate A must approve all and only retained finding IDs")
    elif (
        approved
        or rejected
        or deferred
        or decisions.get("accepted_empty") is not True
    ):
        raise EvaluationError("an empty ledger requires accepted_empty with no finding IDs")
    if artifacts.state.get("approved_findings") != list(sorted(approved)):
        raise EvaluationError("Gate A decisions do not match state.approved_findings")
    return receipt


def validate_gate_a_artifacts(
    run_directory: Path,
    controller: Path,
    target: WorkspaceRecord,
) -> NativeTrialArtifacts:
    """Validate the native ledger and any evaluation-policy Gate A receipt."""

    artifacts, phase, retained_ids = _load_core_artifacts(
        run_directory,
        controller,
        target,
    )
    receipt_path = artifacts.run_directory / "gates" / "findings.json"
    if phase == "ADJUDICATED":
        if receipt_path.exists():
            raise EvaluationError("ADJUDICATED native run has an unexpected Gate A receipt")
        if artifacts.state.get("approved_findings") != []:
            raise EvaluationError("pre-Gate-A state must not contain approved finding IDs")
        return artifacts
    if phase not in {
        "FINDINGS_APPROVED",
        "PLAN_VALIDATED",
        "PLAN_APPROVED",
        "COMPLETE",
    }:
        raise EvaluationError(f"native run is not at a valid Gate A lifecycle phase: {phase}")
    findings_gate = _validate_findings_gate(artifacts, retained_ids)
    if phase == "COMPLETE" and retained_ids:
        raise EvaluationError("evaluation may reach COMPLETE at Gate A only for an empty ledger")
    if phase == "COMPLETE" and artifacts.state.get("approved_findings"):
        raise EvaluationError("empty COMPLETE state cannot approve findings")
    return replace(artifacts, findings_gate=findings_gate)


def _validate_plan(
    artifacts: NativeTrialArtifacts,
    retained_ids: tuple[str, ...],
) -> dict[str, Any]:
    if artifacts.findings_gate is None:
        raise EvaluationError("Gate B requires a validated Gate A receipt")
    plan = _load_json_object(artifacts.run_directory / "fix-plan.json", "fix plan")
    plan_hash = _embedded_hash(
        plan,
        hash_field="plan_hash",
        omitted_fields=("validated_at",),
        context="plan",
    )
    if plan.get("schema_version") != artifacts.schema_profile[2]:
        supplied_profile = (
            artifacts.schema_profile[0],
            artifacts.schema_profile[1],
            plan.get("schema_version"),
        )
        raise EvaluationError(f"unsupported native schema profile: {supplied_profile!r}")
    hashes = _require_object(artifacts.state.get("hashes"), "state.hashes")
    if hashes.get("plan_hash") != plan_hash:
        raise EvaluationError("plan hash does not match state.hashes.plan_hash")
    if plan.get("scope_hash") != artifacts.state.get("scope_hash"):
        raise EvaluationError("plan scope hash does not match the frozen scope")
    if plan.get("findings_gate_hash") != artifacts.findings_gate.get("receipt_hash"):
        raise EvaluationError("plan does not match the validated Gate A receipt")

    items = _require_array(plan.get("items"), "fix plan.items")
    item_ids = [
        _require_string(
            _require_object(raw_item, "fix plan item").get("finding_id"),
            "fix plan finding_id",
        )
        for raw_item in items
    ]
    if len(item_ids) != len(set(item_ids)) or tuple(sorted(item_ids)) != retained_ids:
        raise EvaluationError("every approved finding ID must appear exactly once in the plan")

    scope_paths: set[str] = set()
    identity = _require_object(artifacts.scope.get("identity"), "scope.identity")
    for raw_file in _require_array(identity.get("files"), "scope.identity.files"):
        file_entry = _require_object(raw_file, "scope file")
        scope_paths.add(_require_string(file_entry.get("path"), "scope file path"))
        old_path = file_entry.get("old_path")
        if old_path is not None:
            scope_paths.add(_require_string(old_path, "scope old_path"))
    for index, raw_item in enumerate(items):
        item = _require_object(raw_item, f"fix plan.items[{index}]")
        allowed_paths = _require_array(
            item.get("allowed_paths"),
            f"fix plan.items[{index}].allowed_paths",
        )
        if not allowed_paths:
            raise EvaluationError("fix plan allowed_paths must not be empty")
        for raw_path in allowed_paths:
            path = safe_relative_path(raw_path, "fix plan allowed path")
            if path.as_posix() == "." or path.parts[0] == ".git":
                raise EvaluationError("fix plan path exceeds the native authorization boundary")
            if path.as_posix() not in scope_paths:
                raise EvaluationError(
                    f"fix plan path is outside the frozen scope: {path.as_posix()}"
                )
    return plan


def _validate_plan_gate(
    artifacts: NativeTrialArtifacts,
    plan: dict[str, Any],
) -> dict[str, Any]:
    receipt = _load_json_object(
        artifacts.run_directory / "gates" / "plan.json",
        "Gate B receipt",
    )
    if receipt.get("schema_version") != _PLAN_GATE_SCHEMA:
        raise EvaluationError("Gate B receipt schema is not supported")
    receipt_hash = _embedded_hash(
        receipt,
        hash_field="receipt_hash",
        omitted_fields=(),
        context="Gate B receipt",
    )
    hashes = _require_object(artifacts.state.get("hashes"), "state.hashes")
    gates = _require_object(artifacts.state.get("gates"), "state.gates")
    if hashes.get("plan_gate_hash") != receipt_hash or gates.get("plan") != receipt_hash:
        raise EvaluationError("Gate B receipt hash does not match state gate hashes")
    if receipt.get("run_id") != artifacts.state.get("run_id"):
        raise EvaluationError("Gate B receipt belongs to a different native run")
    if receipt.get("scope_hash") != artifacts.state.get("scope_hash"):
        raise EvaluationError("Gate B receipt scope hash does not match state")
    if receipt.get("findings_gate_hash") != artifacts.findings_gate.get("receipt_hash"):  # type: ignore[union-attr]
        raise EvaluationError("Gate B receipt does not match the validated Gate A receipt")
    if receipt.get("plan_hash") != plan.get("plan_hash"):
        raise EvaluationError("Gate B receipt does not approve the exact validated plan hash")
    if receipt.get("approved") is not True:
        raise EvaluationError("Gate B receipt must approve the exact validated plan")
    return receipt


def validate_gate_b_artifacts(
    run_directory: Path,
    controller: Path,
    target: WorkspaceRecord,
) -> NativeTrialArtifacts:
    """Validate the exact native plan while forbidding all repair-capable states."""

    gate_a_artifacts = validate_gate_a_artifacts(run_directory, controller, target)
    phase = _reject_repair_phase(gate_a_artifacts.state)
    retained_ids = tuple(
        sorted(
            _require_string(
                _require_object(raw_finding, "ledger finding").get("finding_id"),
                "finding_id",
            )
            for raw_finding in _require_array(
                gate_a_artifacts.ledger.get("findings"),
                "ledger.findings",
            )
        )
    )
    if phase == "COMPLETE" and not retained_ids:
        return gate_a_artifacts
    if phase not in {"PLAN_VALIDATED", "PLAN_APPROVED"}:
        raise EvaluationError(f"Gate B requires PLAN_VALIDATED; current phase is {phase}")
    plan = _validate_plan(gate_a_artifacts, retained_ids)
    plan_gate_path = gate_a_artifacts.run_directory / "gates" / "plan.json"
    if phase == "PLAN_VALIDATED":
        if plan_gate_path.exists():
            raise EvaluationError("PLAN_VALIDATED native run has an unexpected Gate B receipt")
        if "plan" in gate_a_artifacts.state.get("gates", {}):
            raise EvaluationError("PLAN_VALIDATED state contains an unexpected Gate B hash")
        return replace(gate_a_artifacts, plan=plan)
    plan_gate = _validate_plan_gate(gate_a_artifacts, plan)
    return replace(gate_a_artifacts, plan=plan, plan_gate=plan_gate)


def _command_prefix(artifacts: NativeTrialArtifacts, command: str) -> tuple[str, ...]:
    return (
        sys.executable,
        str(artifacts.controller),
        command,
        "--repo-root",
        str(artifacts.target.path),
        "--artifact-root",
        str(artifacts.run_directory.parent.parent),
        "--run-id",
        _require_string(artifacts.state.get("run_id"), "state.run_id"),
    )


def gate_a_command(artifacts: NativeTrialArtifacts) -> EvaluationGateCommand:
    """Build the evaluation-only Gate A command with no reject/defer authority."""

    validated = validate_gate_a_artifacts(
        artifacts.run_directory,
        artifacts.controller,
        artifacts.target,
    )
    phase = _require_string(validated.state.get("phase"), "state.phase")
    if phase != "ADJUDICATED":
        raise EvaluationError(f"Gate A command requires ADJUDICATED; current phase is {phase}")
    approved_ids = tuple(
        sorted(
            _require_string(
                _require_object(raw_finding, "ledger finding").get("finding_id"),
                "finding_id",
            )
            for raw_finding in _require_array(validated.ledger.get("findings"), "ledger.findings")
        )
    )
    argv = _command_prefix(validated, "gate-findings")
    if approved_ids:
        argv = (*argv, "--approve", ",".join(approved_ids))
        statement = _GATE_A_APPROVAL
    else:
        argv = (*argv, "--accept-empty")
        statement = _EMPTY_LEDGER_APPROVAL
    return EvaluationGateCommand(
        argv=(*argv, "--user-statement", statement),
        approved_ids=approved_ids,
    )


def gate_b_command(artifacts: NativeTrialArtifacts) -> EvaluationGateCommand:
    """Build an approval command bound to the one validated native plan hash."""

    validated = validate_gate_b_artifacts(
        artifacts.run_directory,
        artifacts.controller,
        artifacts.target,
    )
    phase = _require_string(validated.state.get("phase"), "state.phase")
    if phase != "PLAN_VALIDATED" or validated.plan is None:
        raise EvaluationError(f"Gate B command requires PLAN_VALIDATED; current phase is {phase}")
    approved_ids = tuple(
        sorted(
            _require_string(
                _require_object(raw_item, "fix plan item").get("finding_id"),
                "fix plan finding_id",
            )
            for raw_item in _require_array(validated.plan.get("items"), "fix plan.items")
        )
    )
    plan_hash = _require_sha256(validated.plan.get("plan_hash"), "plan hash")
    return EvaluationGateCommand(
        argv=(
            *_command_prefix(validated, "gate-plan"),
            "--approve",
            "--user-statement",
            _GATE_B_APPROVAL,
        ),
        approved_ids=approved_ids,
        plan_hash=plan_hash,
    )


def _copy_fields(value: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    return {
        field: copy.deepcopy(value[field])
        for field in fields
        if field in value
    }


def _normalize_finding(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _copy_fields(
        value,
        (
            "finding_id",
            "group_id",
            "title",
            "nature",
            "category",
            "severity",
            "confidence",
            "validation",
            "materiality",
            "decision_reason",
            "recommended_action",
            "required_pre_fix_verification",
        ),
    )
    normalized["disposition"] = "keep"
    normalized["evidence"] = _copy_fields(
        value,
        (
            "file",
            "line_start",
            "line_end",
            "evidence_side",
            "evidence_quote",
            "observable_consequence",
            "trigger_conditions",
        ),
    )
    if "repair_direction" in value:
        normalized["repair_direction"] = copy.deepcopy(value["repair_direction"])
    elif "proposed_resolution" in value:
        normalized["repair_direction"] = copy.deepcopy(value["proposed_resolution"])
    return normalized


def _normalize_plan_item(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _copy_fields(
        value,
        (
            "finding_id",
            "root_cause",
            "objective",
            "allowed_paths",
            "risk_controls",
            "rollback_strategy",
        ),
    )
    normalized["tests"] = [
        _copy_fields(
            _require_object(raw_test, "plan test"),
            ("id", "purpose", "command", "working_directory", "required"),
        )
        for raw_test in _require_array(value.get("tests", []), "plan tests")
    ]
    return normalized


def normalize_trial_evidence(
    artifacts: NativeTrialArtifacts,
    *,
    timing_metadata: Mapping[str, Any] | None = None,
    turn_metadata: Mapping[str, Any] | None = None,
    tool_metadata: Mapping[str, Any] | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Copy comparable evidence without rewriting any controller-native artifact."""

    phase = _require_string(artifacts.state.get("phase"), "state.phase")
    if phase == "PLAN_APPROVED":
        validated = validate_gate_b_artifacts(
            artifacts.run_directory,
            artifacts.controller,
            artifacts.target,
        )
    elif phase == "COMPLETE":
        validated = validate_gate_a_artifacts(
            artifacts.run_directory,
            artifacts.controller,
            artifacts.target,
        )
    else:
        raise EvaluationError(
            "normalization requires the evaluation endpoint PLAN_APPROVED or empty COMPLETE"
        )
    before = _native_inventory(validated.run_directory)
    findings_gate = validated.findings_gate
    if findings_gate is None:
        raise EvaluationError("normalization requires a Gate A receipt")

    plan = validated.plan
    plan_gate = validated.plan_gate
    normalized: dict[str, Any] = {
        "native_schema_versions": {
            "state": validated.schema_profile[0],
            "ledger": validated.schema_profile[1],
            "fix_plan": validated.schema_profile[2] if plan is not None else None,
            "findings_gate": findings_gate.get("schema_version"),
            "plan_gate": plan_gate.get("schema_version") if plan_gate is not None else None,
        },
        "hashes": {
            "scope": validated.state.get("scope_hash"),
            "ledger": validated.ledger.get("ledger_hash"),
            "findings_gate": findings_gate.get("receipt_hash"),
            "plan": plan.get("plan_hash") if plan is not None else None,
            "plan_gate": plan_gate.get("receipt_hash") if plan_gate is not None else None,
        },
        "ledger": {
            **_copy_fields(validated.ledger, ("verdict", "summary", "limitations")),
            "findings": [
                _normalize_finding(_require_object(raw_finding, "ledger finding"))
                for raw_finding in _require_array(
                    validated.ledger.get("findings"),
                    "ledger.findings",
                )
            ],
            "discarded": [
                _copy_fields(
                    _require_object(raw_group, "discarded candidate group"),
                    (
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
                        "disposition",
                        "discard_reason",
                        "decision_reason",
                        "validation",
                        "materiality",
                    ),
                )
                for raw_group in _require_array(
                    validated.ledger.get("discarded"),
                    "ledger.discarded",
                )
            ],
        },
        "gate_a": {
            "decisions": copy.deepcopy(findings_gate.get("decisions")),
            "ledger_hash": findings_gate.get("ledger_hash"),
            "receipt_hash": findings_gate.get("receipt_hash"),
        },
        "plan": (
            {
                **_copy_fields(plan, ("plan_summary", "plan_hash")),
                "items": [
                    _normalize_plan_item(_require_object(raw_item, "fix plan item"))
                    for raw_item in _require_array(plan.get("items"), "fix plan.items")
                ],
            }
            if plan is not None
            else None
        ),
        "gate_b": (
            _copy_fields(
                plan_gate,
                (
                    "approved",
                    "findings_gate_hash",
                    "plan_hash",
                    "receipt_hash",
                ),
            )
            if plan_gate is not None
            else None
        ),
        "metadata": {
            "timing": copy.deepcopy(dict(timing_metadata or {})),
            "turns": copy.deepcopy(dict(turn_metadata or {})),
            "tools": copy.deepcopy(dict(tool_metadata or {})),
            "native_controller": {
                "tool_version": validated.state.get("tool_version"),
            },
        },
        "scope_freshness": copy.deepcopy(validated.scope_freshness),
        "cleanliness_attestation": _copy_fields(
            validated.cleanliness_attestation,
            (
                "head",
                "branch",
                "status_sha256",
                "index_flags_sha256",
                "refs_sha256",
                "object_range_sha256",
            ),
        ),
        "native_artifacts": [
            {"path": relative, "sha256": digest}
            for relative, digest in sorted(before.items())
        ],
    }
    after = _native_inventory(validated.run_directory)
    if after != before:
        raise EvaluationError("normalization modified controller-native artifacts")
    if output_path is not None:
        destination = Path(output_path).resolve(strict=False)
        if destination == validated.run_directory or validated.run_directory in destination.parents:
            raise EvaluationError("normalized evidence must be stored outside native artifacts")
        atomic_write_json(destination, normalized)
    return normalized
