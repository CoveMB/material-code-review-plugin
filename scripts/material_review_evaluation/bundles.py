from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .model import EvaluationError, atomic_write_json, canonical_hash, sha256_file


_ANONYMOUS_LABEL_PATTERN = re.compile(r"^[A-Z](?:-[1-9][0-9]*)?$")
_GIT_SHA_PATTERN = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{40}(?![0-9A-Fa-f])")
_IDENTITY_LABEL_PATTERNS = (
    re.compile(
        r"\b(?:variant|candidate|workflow|skill|version)\s*[:=_-]?\s*(?:old|new)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:old|new)\s*[:=_-]?\s*(?:variant|candidate|workflow|skill|version)\b",
        re.IGNORECASE,
    ),
)
_CREDENTIAL_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?:"
    r"OPENAI_API_KEY|"
    r"AWS_(?:ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN)|"
    r"GITHUB_TOKEN|GH_TOKEN|"
    r"API_KEY|ACCESS_KEY|TOKEN|SECRET|PASSWORD|PASSWD|"
    r"[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|ACCESS_KEY)"
    r")[\"']?\s*[:=]\s*[\"']?[^\s\"',;}]+"
)
_CREDENTIAL_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
_UNIX_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._<>:/-])/(?!/)(?:[A-Za-z0-9._~+-]+/)*[A-Za-z0-9._~+-]+"
)
_WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:[\\/]|\\\\[A-Za-z0-9._-]+[\\/])"
)
_SENSITIVE_CONFIGURATION_KEY_PATTERN = re.compile(
    r"(?i)(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|ACCESS_KEY|CREDENTIAL)"
)
_IDENTITY_JSON_KEY_TERMS = frozenset(
    {"candidate", "skill", "variant", "version", "workflow"}
)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _regular_file(path: Path, context: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise EvaluationError(f"{context} must be a regular file")
    return candidate.absolute()


def _directory(path: Path, context: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_dir():
        raise EvaluationError(f"{context} must be a directory")
    return candidate.absolute()


def _read_utf8_file(path: Path, context: str) -> str:
    source = _regular_file(path, context)
    try:
        return source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise EvaluationError(f"{context} is not readable UTF-8 text") from error


def _require_json_object(text: str, context: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise EvaluationError(f"{context} must contain valid JSON") from error
    if not isinstance(value, dict):
        raise EvaluationError(f"{context} must contain a JSON object")
    return value


def redact_machine_paths(
    text: str,
    path_prefixes: Mapping[str | Path, str],
) -> str:
    """Replace configured machine-specific prefixes without exposing their values."""

    if not isinstance(text, str):
        raise EvaluationError("machine-path redaction requires text")
    replacements: list[tuple[str, str]] = []
    for raw_prefix, placeholder in path_prefixes.items():
        prefix = os.fspath(raw_prefix)
        if not prefix or not os.path.isabs(prefix):
            raise EvaluationError("machine-path redaction prefixes must be absolute")
        if not isinstance(placeholder, str) or not re.fullmatch(r"<[a-z]+>", placeholder):
            raise EvaluationError("machine-path replacement must be a lowercase placeholder")
        normalized = prefix.rstrip("/\\") or prefix
        replacements.append((normalized, placeholder))
    redacted = text
    for prefix, placeholder in sorted(
        replacements,
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        redacted = redacted.replace(prefix, placeholder)
    return redacted


def _flatten_private_tokens(private_tokens: object) -> tuple[str, ...]:
    collected: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, str):
            if value:
                collected.append(value)
            return
        if isinstance(value, Path):
            collected.append(str(value))
            return
        if isinstance(value, Mapping):
            for item in value.values():
                collect(item)
            return
        if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
            for item in value:
                collect(item)
            return
        if value is not None:
            raise EvaluationError("private identity tokens must be strings or collections")

    collect(private_tokens)
    return tuple(sorted(set(collected), key=len, reverse=True))


def _contains_absolute_path(text: str) -> bool:
    if _WINDOWS_ABSOLUTE_PATH_PATTERN.search(text):
        return True
    if _UNIX_ABSOLUTE_PATH_PATTERN.search(text):
        return True
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return False

    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str):
            if item.startswith(("/", "file:/")):
                return True
            if _WINDOWS_ABSOLUTE_PATH_PATTERN.match(item):
                return True
    return False


def _contains_json_identity(text: str) -> bool:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return False

    def contains_identity(item: object, identity_context: bool = False) -> bool:
        if isinstance(item, str):
            return identity_context and item.casefold() in {"old", "new"}
        if isinstance(item, list):
            return any(contains_identity(child, identity_context) for child in item)
        if isinstance(item, dict):
            for key, child in item.items():
                key_terms = set(
                    part
                    for part in re.split(r"[^a-z0-9]+", key.casefold())
                    if part
                )
                if contains_identity(
                    child,
                    identity_context or bool(key_terms & _IDENTITY_JSON_KEY_TERMS),
                ):
                    return True
        return False

    return contains_identity(value)


def _scan_text(text: str, private_tokens: tuple[str, ...], relative_path: str) -> None:
    for token in private_tokens:
        if token in text:
            raise EvaluationError(f"identity leak in blinded bundle file: {relative_path}")
    if _GIT_SHA_PATTERN.search(text) or any(
        pattern.search(text) for pattern in _IDENTITY_LABEL_PATTERNS
    ) or _contains_json_identity(text):
        raise EvaluationError(f"identity leak in blinded bundle file: {relative_path}")
    if _CREDENTIAL_ASSIGNMENT_PATTERN.search(text) or any(
        pattern.search(text) for pattern in _CREDENTIAL_VALUE_PATTERNS
    ):
        raise EvaluationError(f"credential leak in blinded bundle file: {relative_path}")
    if _contains_absolute_path(text):
        raise EvaluationError(f"absolute path leak in blinded bundle file: {relative_path}")


def scan_blinded_bundle(
    bundle_root: Path,
    private_tokens: object = (),
) -> None:
    """Fail when an allowlisted bundle contains identity or machine-private data."""

    root = Path(bundle_root)
    if root.is_symlink() or not root.is_dir():
        raise EvaluationError("blinded bundle root must be a regular directory")
    root = root.resolve(strict=True)
    tokens = _flatten_private_tokens(private_tokens)
    for current_root, directory_names, file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        current = Path(current_root)
        for name in tuple(directory_names):
            entry = current / name
            relative = entry.relative_to(root).as_posix()
            _scan_text(relative, tokens, relative)
            if entry.is_symlink():
                try:
                    escapes = not entry.resolve(strict=False).is_relative_to(root)
                except OSError:
                    escapes = True
                message = "symlink escape" if escapes else "non-regular file"
                raise EvaluationError(
                    f"{message} in blinded bundle: {relative}"
                )
            if not stat.S_ISDIR(entry.lstat().st_mode):
                raise EvaluationError(
                    f"non-regular file in blinded bundle: {relative}"
                )
        for name in file_names:
            entry = current / name
            relative = entry.relative_to(root).as_posix()
            _scan_text(relative, tokens, relative)
            if entry.is_symlink():
                try:
                    escapes = not entry.resolve(strict=False).is_relative_to(root)
                except OSError:
                    escapes = True
                message = "symlink escape" if escapes else "non-regular file"
                raise EvaluationError(f"{message} in blinded bundle: {relative}")
            if not stat.S_ISREG(entry.lstat().st_mode):
                raise EvaluationError(f"non-regular file in blinded bundle: {relative}")
            try:
                text = entry.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                raise EvaluationError(
                    f"non-UTF-8 file in blinded bundle: {relative}"
                ) from error
            _scan_text(text, tokens, relative)


def _copy_redacted(
    source: Path,
    destination: Path,
    *,
    context: str,
    path_prefixes: Mapping[str | Path, str],
    require_json_object: bool = False,
) -> None:
    text = _read_utf8_file(source, context)
    if require_json_object:
        _require_json_object(text, context)
    _atomic_write_text(destination, redact_machine_paths(text, path_prefixes))


def _create_bundle_root(destination: Path) -> Path:
    root = Path(destination)
    if root.exists() or root.is_symlink():
        raise EvaluationError("blinded bundle destination must not already exist")
    root.mkdir(parents=True, exist_ok=False)
    return root.resolve(strict=True)


def _variant_label(
    value: Mapping[str, Any],
    context: str,
    *,
    allow_variant_alias: bool,
) -> str:
    fields = ("anonymous_variant", "variant") if allow_variant_alias else ("anonymous_variant",)
    labels = [value[field] for field in fields if field in value]
    if not labels:
        raise EvaluationError(f"{context} does not declare an anonymous variant label")
    if any(label not in {"A", "B"} for label in labels):
        raise EvaluationError(f"{context} has an invalid anonymous variant label")
    if len(set(labels)) != 1:
        raise EvaluationError(f"{context} has conflicting anonymous variant labels")
    return labels[0]


def _validate_trial_sources(
    paths: Iterable[Path],
    *,
    expected_variant: str,
) -> tuple[Path, ...]:
    trials = tuple(Path(path) for path in paths)
    if not trials:
        raise EvaluationError("a blinded bundle requires at least one normalized trial")
    if len(trials) > 3:
        raise EvaluationError("a blinded bundle supports at most three normalized trials")
    resolved: list[Path] = []
    for index, trial in enumerate(trials, start=1):
        context = f"normalized trial {index}"
        text = _read_utf8_file(trial, context)
        value = _require_json_object(text, context)
        if _variant_label(value, context, allow_variant_alias=True) != expected_variant:
            raise EvaluationError(
                f"{context} label does not match slot {expected_variant}"
            )
        resolved.append(_regular_file(trial, context))
    return tuple(resolved)


def _validate_agreement_source(path: Path, expected_variant: str) -> Path:
    context = f"Variant {expected_variant} agreement"
    source = _regular_file(path, context)
    value = _require_json_object(_read_utf8_file(source, context), context)
    if _variant_label(value, context, allow_variant_alias=False) != expected_variant:
        raise EvaluationError(
            f"{context} label does not match slot {expected_variant}"
        )
    return source


def build_trial_request(
    request_path: Path,
    record_path: Path,
    *,
    review_request_path: Path,
    materialized_skill_path: Path,
    target_path: Path,
    artifact_root: Path,
    anonymous_trial_label: str,
    isolation_mode: str,
    executor_configuration: Mapping[str, Any],
) -> dict[str, Any]:
    """Write the common trial request plus only its anonymous operational roots."""

    if not _ANONYMOUS_LABEL_PATTERN.fullmatch(anonymous_trial_label):
        raise EvaluationError("anonymous trial label must use A/B-style anonymous notation")
    if isolation_mode not in {"filesystem_blinding", "logical_blinding"}:
        raise EvaluationError("trial isolation mode is not supported")
    common_request = _read_utf8_file(review_request_path, "common review request")
    skill = _regular_file(materialized_skill_path, "materialized skill")
    target = _directory(target_path, "trial target")
    artifacts = _directory(artifact_root, "controller artifact root")
    if any(
        not isinstance(key, str) or _SENSITIVE_CONFIGURATION_KEY_PATTERN.search(key)
        for key in executor_configuration
    ):
        raise EvaluationError("executor configuration contains a credential-bearing field")
    try:
        configuration_hash = canonical_hash(dict(executor_configuration))
    except (TypeError, ValueError) as error:
        raise EvaluationError("executor configuration must be JSON-compatible") from error

    wrapper = (
        f"# Anonymous trial {anonymous_trial_label}\n\n"
        f"Host isolation mode: `{isolation_mode}`\n\n"
        f"Use the exact materialized skill at `{skill}`. "
        "Read that exact skill and no other copy.\n\n"
        f"Frozen target: `{target}`\n\n"
        f"Controller artifact root: `{artifacts}`\n\n"
        f"{common_request}"
    )
    request = Path(request_path)
    record_file = Path(record_path)
    if request == record_file:
        raise EvaluationError("trial request and record paths must differ")
    if (
        request.exists()
        or request.is_symlink()
        or record_file.exists()
        or record_file.is_symlink()
    ):
        raise EvaluationError("trial request outputs must not already exist")
    _atomic_write_text(request, wrapper)
    record = {
        "schema": "material-review-evaluation/trial-request-record/v1",
        "anonymous_trial_label": anonymous_trial_label,
        "request_sha256": sha256_file(request),
        "executor_configuration_sha256": configuration_hash,
    }
    atomic_write_json(record_file, record)
    return record


def build_agreement_bundle(
    destination: Path,
    *,
    anonymous_variant: str,
    normalized_trials: Iterable[Path],
    prompt_path: Path,
    schema_path: Path,
    path_prefixes: Mapping[str | Path, str],
    private_tokens: object = (),
) -> Path:
    """Create a fresh agreement bundle containing one anonymous variant only."""

    if anonymous_variant not in {"A", "B"}:
        raise EvaluationError("agreement variant must be anonymous label A or B")
    trials = _validate_trial_sources(
        normalized_trials,
        expected_variant=anonymous_variant,
    )
    root = _create_bundle_root(destination)
    try:
        _copy_redacted(
            prompt_path,
            root / "prompt.md",
            context="agreement prompt",
            path_prefixes=path_prefixes,
        )
        _copy_redacted(
            schema_path,
            root / "output.schema.json",
            context="agreement output schema",
            path_prefixes=path_prefixes,
            require_json_object=True,
        )
        for index, trial in enumerate(trials, start=1):
            _copy_redacted(
                trial,
                root / "trials" / f"trial-{index}.json",
                context=f"normalized trial {index}",
                path_prefixes=path_prefixes,
                require_json_object=True,
            )
        atomic_write_json(
            root / "bundle.json",
            {
                "schema": "material-review-evaluation/agreement-bundle/v1",
                "anonymous_variant": anonymous_variant,
                "prompt": "prompt.md",
                "output_schema": "output.schema.json",
                "trials": [f"trials/trial-{index}.json" for index in range(1, len(trials) + 1)],
            },
        )
        scan_blinded_bundle(root, private_tokens)
    except BaseException:
        _remove_incomplete_bundle(root)
        raise
    return root


def build_comparison_bundle(
    destination: Path,
    *,
    variant_a_trials: Iterable[Path],
    variant_b_trials: Iterable[Path],
    agreement_a: Path,
    agreement_b: Path,
    rubric_path: Path,
    oracle_path: Path,
    prompt_path: Path,
    schema_path: Path,
    path_prefixes: Mapping[str | Path, str],
    private_tokens: object = (),
) -> Path:
    """Create a fresh A/B judge bundle without copying the evaluator's private map."""

    trials_a = _validate_trial_sources(variant_a_trials, expected_variant="A")
    trials_b = _validate_trial_sources(variant_b_trials, expected_variant="B")
    validated_agreement_a = _validate_agreement_source(agreement_a, "A")
    validated_agreement_b = _validate_agreement_source(agreement_b, "B")
    root = _create_bundle_root(destination)
    try:
        fixed_inputs = (
            (prompt_path, root / "prompt.md", "comparison prompt", False),
            (schema_path, root / "output.schema.json", "judgment output schema", True),
            (rubric_path, root / "judge-rubric.md", "judge rubric", False),
            (oracle_path, root / "judge-oracle.json", "judge oracle", True),
            (
                validated_agreement_a,
                root / "agreements" / "A.json",
                "Variant A agreement",
                True,
            ),
            (
                validated_agreement_b,
                root / "agreements" / "B.json",
                "Variant B agreement",
                True,
            ),
        )
        for source, target, context, require_object in fixed_inputs:
            _copy_redacted(
                source,
                target,
                context=context,
                path_prefixes=path_prefixes,
                require_json_object=require_object,
            )
        for label, trials in (("A", trials_a), ("B", trials_b)):
            for index, trial in enumerate(trials, start=1):
                _copy_redacted(
                    trial,
                    root / "variants" / label / f"trial-{index}.json",
                    context=f"Variant {label} normalized trial {index}",
                    path_prefixes=path_prefixes,
                    require_json_object=True,
                )
        atomic_write_json(
            root / "bundle.json",
            {
                "schema": "material-review-evaluation/comparison-bundle/v1",
                "prompt": "prompt.md",
                "output_schema": "output.schema.json",
                "rubric": "judge-rubric.md",
                "oracle": "judge-oracle.json",
                "variants": {
                    "A": [
                        f"variants/A/trial-{index}.json"
                        for index in range(1, len(trials_a) + 1)
                    ],
                    "B": [
                        f"variants/B/trial-{index}.json"
                        for index in range(1, len(trials_b) + 1)
                    ],
                },
                "agreements": {"A": "agreements/A.json", "B": "agreements/B.json"},
            },
        )
        scan_blinded_bundle(root, private_tokens)
    except BaseException:
        _remove_incomplete_bundle(root)
        raise
    return root


def _remove_incomplete_bundle(root: Path) -> None:
    """Remove only a bundle root created by this invocation after a failed scan."""

    for current_root, directory_names, file_names in os.walk(
        root,
        topdown=False,
        followlinks=False,
    ):
        current = Path(current_root)
        for name in file_names:
            entry = current / name
            if entry.is_symlink() or entry.is_file():
                entry.unlink()
        for name in directory_names:
            entry = current / name
            if entry.is_symlink():
                entry.unlink()
            else:
                entry.rmdir()
    root.rmdir()
