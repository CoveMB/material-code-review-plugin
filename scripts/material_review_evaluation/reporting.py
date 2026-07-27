from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .bundles import redact_machine_paths
from .model import EvaluationError, atomic_write_json, safe_relative_path, sha256_file


_DIMENSION_ORDER = (
    "finding_validity_and_coverage",
    "validation_quality",
    "repair_safety",
    "scope_and_gate_integrity",
    "traceability",
    "machine_validation_and_artifact_completeness",
    "consistency_across_trials",
    "report_clarity_and_copyability",
    "efficiency_and_cost",
)
_DIMENSION_LABELS = {
    "finding_validity_and_coverage": "Finding validity and coverage",
    "validation_quality": "Validation quality",
    "repair_safety": "Repair safety",
    "scope_and_gate_integrity": "Scope and gate integrity",
    "traceability": "Traceability",
    "machine_validation_and_artifact_completeness": (
        "Machine validation and artifact completeness"
    ),
    "consistency_across_trials": "Consistency across trials",
    "report_clarity_and_copyability": "Report clarity and copyability",
    "efficiency_and_cost": "Efficiency and cost",
}
_DIMENSION_DECISIONS = frozenset({"A_STRONGER", "B_STRONGER", "TIE", "UNKNOWN"})
_OVERALL_DECISIONS = frozenset(
    {
        "VARIANT_A_STRONGER",
        "VARIANT_B_STRONGER",
        "MATERIAL_TIE",
        "INSUFFICIENT_EVIDENCE",
    }
)
_CONFIDENCE_VALUES = frozenset({"high", "medium", "low"})
_SHA40_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CREDENTIAL_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?:"
    r"OPENAI_API_KEY|AWS_(?:ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN)|"
    r"GITHUB_TOKEN|GH_TOKEN|API_KEY|ACCESS_KEY|TOKEN|SECRET|PASSWORD|PASSWD|"
    r"[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|ACCESS_KEY)"
    r")[\"']?\s*[:=]\s*(?:"
    r'"[^"\r\n]*"|'
    r"'[^'\r\n]*'|"
    r"[^\s\"',;}]+)"
)
_CREDENTIAL_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
_UNIX_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._<>/-])/(?!/)(?:[A-Za-z0-9._~+-]+/)*[A-Za-z0-9._~+-]+"
)
_WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:[\\/]|\\\\[A-Za-z0-9._-]+[\\/])"
)


def _load_json_object(path: Path, context: str) -> dict[str, Any]:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise EvaluationError(f"{context} is missing or symlinked")
    try:
        value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvaluationError(f"{context} is unreadable") from error
    if not isinstance(value, dict):
        raise EvaluationError(f"{context} must be a JSON object")
    return value


def _require_text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationError(f"{context} must be a non-empty string")
    return " ".join(value.split())


def _require_sha256(value: object, context: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise EvaluationError(f"{context} must be a lowercase SHA-256 digest")
    return value


def _require_string_list(value: object, context: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise EvaluationError(f"{context} must be an array")
    return tuple(
        _require_text(item, f"{context}[{index}]")
        for index, item in enumerate(value)
    )


def _parse_timestamp(value: object, context: str) -> datetime:
    text = _require_text(value, context)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvaluationError(f"{context} must be an RFC 3339 timestamp") from error
    if parsed.tzinfo is None:
        raise EvaluationError(f"{context} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _utc_after(value: object) -> str:
    predecessor = _parse_timestamp(value, "run updated_at")
    now = datetime.now(timezone.utc)
    if now <= predecessor:
        now = predecessor + timedelta(microseconds=1)
    return now.isoformat().replace("+00:00", "Z")


def _atomic_write_text(path: Path, text: str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
    except BaseException:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _markdown_text(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    for character in ("`", "*", "[", "]", "<", ">", "#"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def _render_list(values: Sequence[str]) -> list[str]:
    if not values:
        return ["- None reported."]
    return [f"- {_markdown_text(value)}" for value in values]


def _sanitize_report(
    text: str,
    path_prefixes: Mapping[str | Path, str],
) -> str:
    sanitized = redact_machine_paths(text, path_prefixes)
    sanitized = _CREDENTIAL_ASSIGNMENT_PATTERN.sub(
        "<redacted-credential>",
        sanitized,
    )
    for pattern in _CREDENTIAL_VALUE_PATTERNS:
        sanitized = pattern.sub("<redacted-credential>", sanitized)
    if _UNIX_ABSOLUTE_PATH_PATTERN.search(sanitized) is not None:
        raise EvaluationError("sanitized report still contains an absolute machine path")
    if _WINDOWS_ABSOLUTE_PATH_PATTERN.search(sanitized) is not None:
        raise EvaluationError("sanitized report still contains an absolute machine path")
    if _CREDENTIAL_ASSIGNMENT_PATTERN.search(sanitized) is not None or any(
        pattern.search(sanitized) is not None
        for pattern in _CREDENTIAL_VALUE_PATTERNS
    ):
        raise EvaluationError("sanitized report still contains a credential pattern")
    return sanitized


def _default_path_prefixes(
    run_root: Path,
    private_request: Mapping[str, Any],
) -> dict[Path, str]:
    prefixes = {
        run_root: "<run>",
        run_root.parent: "<runs>",
        Path.home().absolute(): "<home>",
    }
    repository_value = private_request.get("repository_root")
    if isinstance(repository_value, str) and os.path.isabs(repository_value):
        prefixes[Path(repository_value).absolute()] = "<repository>"
    target_value = private_request.get("target_repository")
    if isinstance(target_value, str) and os.path.isabs(target_value):
        prefixes[Path(target_value).absolute()] = "<target>"
    return prefixes


def _resolved_run_root(run_root: Path) -> Path:
    supplied = Path(run_root)
    if supplied.is_symlink() or not supplied.is_dir():
        raise EvaluationError("evaluation run does not exist or is symlinked")
    return supplied.resolve(strict=True)


def select_run_root(runs_root: Path, run_id: str | None = None) -> Path:
    """Select one exact run, or the newest durable run by its updated timestamp."""

    root = Path(runs_root)
    if root.is_symlink() or not root.is_dir():
        raise EvaluationError("evaluation runs root does not exist or is symlinked")
    root = root.resolve(strict=True)
    if run_id is not None:
        identifier = safe_relative_path(run_id, "run ID")
        if len(identifier.parts) != 1 or identifier.as_posix() in {".", ".."}:
            raise EvaluationError("run ID must be one safe path component")
        return _resolved_run_root(root / identifier.as_posix())

    candidates: list[tuple[datetime, str, Path]] = []
    for run_json in root.glob("*/run.json"):
        if run_json.is_symlink() or not run_json.is_file() or run_json.parent.is_symlink():
            continue
        try:
            state = _load_json_object(run_json, "evaluation run")
            updated_at = _parse_timestamp(state.get("updated_at"), "run updated_at")
            persisted_run_id = _require_text(state.get("run_id"), "run ID")
        except EvaluationError:
            continue
        if persisted_run_id != run_json.parent.name:
            continue
        candidates.append((updated_at, persisted_run_id, run_json.parent))
    if not candidates:
        raise EvaluationError("no evaluation runs were found")
    return _resolved_run_root(max(candidates, key=lambda item: (item[0], item[1]))[2])


def load_run_state(run_root: Path) -> dict[str, Any]:
    root = _resolved_run_root(run_root)
    state = _load_json_object(root / "run.json", "evaluation run")
    if state.get("run_id") != root.name:
        raise EvaluationError("run ID does not match its directory")
    return state


def _locked_inputs(
    run_root: Path,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    state = load_run_state(run_root)
    if state.get("phase") != "COMPLETE":
        raise EvaluationError("sanitized report requires a COMPLETE evaluation run")
    judgment_path = run_root / "judge/judgment.json"
    judgment_hash = sha256_file(judgment_path)
    if _require_sha256(state.get("judgment_sha256"), "locked judgment hash") != judgment_hash:
        raise EvaluationError("locked judgment hash does not match run state")
    judgment = _load_json_object(judgment_path, "locked judgment")
    locked_at = _parse_timestamp(judgment.get("locked_at"), "judgment locked_at")
    reveal = _load_json_object(run_root / "judge/reveal.json", "identity reveal")
    if reveal.get("judgment_sha256") != judgment_hash:
        raise EvaluationError("identity reveal is not bound to the locked judgment")
    if _parse_timestamp(reveal.get("revealed_at"), "identity reveal timestamp") <= locked_at:
        raise EvaluationError("identity reveal must follow judgment locking")
    variant_map = reveal.get("variant_map")
    if (
        not isinstance(variant_map, dict)
        or set(variant_map) != {"A", "B"}
        or sorted(variant_map.values()) != ["baseline", "candidate"]
    ):
        raise EvaluationError("identity reveal has an invalid private variant map")
    private_request = _load_json_object(
        run_root / "private/request.json",
        "private evaluation request",
    )
    resolved_variants = _load_json_object(
        run_root / "private/resolved-variants.json",
        "resolved variants",
    )
    return state, judgment, reveal, private_request, resolved_variants


def _render_report_text(
    run_root: Path,
    judgment: Mapping[str, Any],
    reveal: Mapping[str, Any],
    private_request: Mapping[str, Any],
    resolved_variants: Mapping[str, Any],
) -> str:
    decision = _require_text(judgment.get("overall_decision"), "overall decision")
    if decision not in _OVERALL_DECISIONS:
        raise EvaluationError("locked judgment contains an unsupported overall decision")
    rationale = _require_text(judgment.get("overall_rationale"), "overall rationale")
    dimensions = judgment.get("dimensions")
    if not isinstance(dimensions, dict) or set(dimensions) != set(_DIMENSION_ORDER):
        raise EvaluationError("locked judgment dimensions do not match the report contract")

    judgment_hash = sha256_file(run_root / "judge/judgment.json")
    lines = [
        "# Material Review Version Comparison",
        "",
        f"Run: `{run_root.name}`",
        f"Locked judgment SHA-256: `{judgment_hash}`",
        "",
        "## Locked blinded decision",
        "",
        f"`{decision}`",
        "",
        _markdown_text(rationale),
        "",
        "## Per-dimension evidence",
        "",
    ]
    for name in _DIMENSION_ORDER:
        value = dimensions[name]
        if not isinstance(value, dict):
            raise EvaluationError(f"judgment dimension {name} must be an object")
        dimension_decision = _require_text(
            value.get("decision"),
            f"judgment dimension {name} decision",
        )
        if dimension_decision not in _DIMENSION_DECISIONS:
            raise EvaluationError(f"judgment dimension {name} has an invalid decision")
        dimension_rationale = _require_text(
            value.get("rationale"),
            f"judgment dimension {name} rationale",
        )
        citations = _require_string_list(
            value.get("artifact_citations"),
            f"judgment dimension {name} artifact citations",
        )
        lines.extend(
            (
                f"### {_DIMENSION_LABELS[name]} — `{dimension_decision}`",
                "",
                _markdown_text(dimension_rationale),
                "",
                "Artifact citations:",
                "",
                *_render_list(citations),
                "",
            )
        )

    confidence = _require_text(judgment.get("confidence"), "judgment confidence")
    if confidence not in _CONFIDENCE_VALUES:
        raise EvaluationError("locked judgment contains an unsupported confidence")
    ordered_sections = (
        (
            "Trial stability",
            [_markdown_text(_require_text(judgment.get("trial_stability"), "trial stability"))],
        ),
        (
            "Known failures found or missed",
            _render_list(_require_string_list(judgment.get("known_failures"), "known failures")),
        ),
        (
            "Unsupported findings",
            _render_list(
                _require_string_list(judgment.get("unsupported_findings"), "unsupported findings")
            ),
        ),
        (
            "Plan-boundary comparison",
            [
                _markdown_text(
                    _require_text(
                        judgment.get("plan_boundary_comparison"),
                        "plan-boundary comparison",
                    )
                )
            ],
        ),
        (
            "Workflow failures",
            _render_list(
                _require_string_list(
                    judgment.get("workflow_failures"),
                    "workflow failures",
                )
            ),
        ),
        (
            "Cost observations",
            _render_list(
                _require_string_list(
                    judgment.get("cost_observations"),
                    "cost observations",
                )
            ),
        ),
        ("Confidence", [_markdown_text(confidence)]),
        (
            "Limitations",
            _render_list(_require_string_list(judgment.get("limitations"), "limitations")),
        ),
    )
    for heading, content in ordered_sections:
        lines.extend((f"## {heading}", "", *content, ""))

    variant_map = reveal["variant_map"]
    lines.extend(
        (
            "## Post-lock identity reveal",
            "",
            "The following identities were added only after the blinded judgment was locked:",
            "",
        )
    )
    for anonymous_variant in ("A", "B"):
        identity = variant_map[anonymous_variant]
        resolved = resolved_variants.get(identity)
        if not isinstance(resolved, dict):
            raise EvaluationError(f"resolved {identity} variant is missing")
        commit_sha = resolved.get("commit_sha")
        if not isinstance(commit_sha, str) or _SHA40_PATTERN.fullmatch(commit_sha) is None:
            raise EvaluationError(f"resolved {identity} commit SHA is invalid")
        expected_ref_field = "base_ref" if identity == "baseline" else "candidate_ref"
        supplied_ref = _require_text(
            resolved.get("supplied_ref"),
            f"resolved {identity} ref",
        )
        if private_request.get(expected_ref_field) != supplied_ref:
            raise EvaluationError(f"resolved {identity} ref does not match the private request")
        lines.append(
            f"- Variant {anonymous_variant}: {identity}; ref "
            f"{_markdown_text(supplied_ref)}; commit `{commit_sha}`"
        )
    lines.append("")
    return "\n".join(lines)


def render_comparison_report(
    run_root: Path,
    *,
    path_prefixes: Mapping[str | Path, str] | None = None,
) -> Path:
    """Render and hash-bind the sanitized report after locked identity reveal."""

    root = _resolved_run_root(run_root)
    state, judgment, reveal, private_request, resolved_variants = _locked_inputs(root)
    prefixes: dict[str | Path, str] = _default_path_prefixes(root, private_request)
    if path_prefixes is not None:
        prefixes.update(path_prefixes)
    report_text = _sanitize_report(
        _render_report_text(
            root,
            judgment,
            reveal,
            private_request,
            resolved_variants,
        ),
        prefixes,
    )
    report_path = root / "comparison-report.md"
    if report_path.is_symlink():
        raise EvaluationError("sanitized report path must not be a symlink")
    _atomic_write_text(report_path, report_text)
    report_hash = sha256_file(report_path)

    current = load_run_state(root)
    if (
        current.get("phase") != "COMPLETE"
        or current.get("judgment_sha256") != state.get("judgment_sha256")
    ):
        raise EvaluationError("evaluation state changed while rendering the report")
    current["report_sha256"] = report_hash
    if "updated_at" in current:
        current["updated_at"] = _utc_after(current["updated_at"])
    atomic_write_json(root / "run.json", current)
    return report_path


def read_sanitized_report(run_root: Path) -> str:
    """Read only a COMPLETE run's hash-bound sanitized report."""

    root = _resolved_run_root(run_root)
    state, _, _, private_request, _ = _locked_inputs(root)
    report_path = root / "comparison-report.md"
    if report_path.is_symlink() or not report_path.is_file():
        raise EvaluationError("sanitized comparison report is missing")
    expected_hash = _require_sha256(state.get("report_sha256"), "report hash")
    if sha256_file(report_path) != expected_hash:
        raise EvaluationError("sanitized comparison report hash does not match run state")
    try:
        text = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise EvaluationError("sanitized comparison report is unreadable") from error
    prefixes = _default_path_prefixes(root, private_request)
    if _sanitize_report(text, prefixes) != text:
        raise EvaluationError("sanitized comparison report no longer passes redaction checks")
    return text


def copy_sanitized_report(report_text: str, output: Path) -> Path:
    """Atomically copy already-sanitized report text to one local destination."""

    destination = Path(output).expanduser().absolute()
    if destination.is_symlink() or destination.is_dir():
        raise EvaluationError("report output must be a regular file path")
    _atomic_write_text(destination, report_text)
    return destination
