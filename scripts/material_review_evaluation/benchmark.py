from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlsplit

from .model import EvaluationError, safe_relative_path, sha256_file


_BENCHMARK_SCHEMA = "material-review-evaluation/benchmark/v1"
_ALLOWED_EXECUTABLES = frozenset({"python3", "npm"})
_SHELL_METACHARACTERS = frozenset("|&;<>()$`\\\"'*?[]{}!")
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_BENCHMARK_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_PROHIBITIONS = frozenset(
    {
        "oracle_lookup",
        "repair",
        "live_spotify_calls",
        "private_discogs_data",
        "publication",
        "source_egress",
        "prior_run_discovery",
    }
)
_MANIFEST_FIELDS = frozenset(
    {
        "schema",
        "benchmark_id",
        "target_repository",
        "baseline_sha",
        "comparison_sha",
        "require_immediate_parent",
        "review_mode",
        "posture",
        "include_untracked",
        "dependency_installation_commands",
        "baseline_validation_commands",
        "required_lenses",
        "prohibitions",
        "trial_policy",
        "gate_policy",
        "required_artifacts",
        "default_timeout_seconds",
        "infrastructure_retry_limit",
        "executor_isolation_policy",
        "file_hashes",
    }
)


@dataclass(frozen=True)
class CommandSpec:
    argv: tuple[str, ...]
    working_directory: PurePosixPath
    timeout_seconds: int


@dataclass(frozen=True)
class Benchmark:
    benchmark_id: str
    root: Path
    target_repository: str
    baseline_sha: str
    comparison_sha: str
    require_immediate_parent: bool
    review_mode: str
    posture: str
    include_untracked: bool
    baseline_validation_commands: tuple[CommandSpec, ...]
    dependency_installation_commands: tuple[CommandSpec, ...]
    initial_trials: int
    conditional_third: bool
    default_timeout_seconds: int
    infrastructure_retry_limit: int
    gate_a_policy: str
    gate_b_policy: str
    required_artifacts: tuple[str, ...]
    required_lenses: tuple[str, ...]
    prohibitions: frozenset[str]
    executor_isolation_modes: tuple[str, ...]
    executor_exposed_roots: tuple[str, ...]
    require_fresh_agent_context: bool
    require_fresh_target_clone: bool
    file_hashes: Mapping[str, str]


def _load_json_object(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvaluationError(f"unable to load {context}: {error}") from error
    if not isinstance(value, dict):
        raise EvaluationError(f"{context} must be a JSON object")
    return value


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: frozenset[str],
    context: str,
) -> None:
    fields = frozenset(value)
    if fields != expected:
        missing = sorted(expected - fields)
        unexpected = sorted(fields - expected)
        raise EvaluationError(
            f"{context} fields do not match contract; "
            f"missing={missing}, unexpected={unexpected}"
        )


def _require_string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvaluationError(f"{context} must be a non-empty string")
    return value


def _require_boolean(value: object, context: str) -> bool:
    if not isinstance(value, bool):
        raise EvaluationError(f"{context} must be a boolean")
    return value


def _require_positive_integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EvaluationError(f"{context} must be a positive integer")
    return value


def _require_string_tuple(value: object, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise EvaluationError(f"{context} must be a non-empty array")
    strings = tuple(
        _require_string(item, f"{context}[{index}]")
        for index, item in enumerate(value)
    )
    if len(strings) != len(set(strings)):
        raise EvaluationError(f"{context} must not contain duplicates")
    return strings


def _validate_repository_url(value: object) -> str:
    repository_url = _require_string(value, "target_repository")
    parsed = urlsplit(repository_url)
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
    except ValueError:
        address = None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        or parsed.hostname.endswith(".local")
        or (address is not None and not address.is_global)
    ):
        raise EvaluationError("target_repository must be a public HTTPS URL")
    return repository_url


def _validate_git_sha(value: object, context: str) -> str:
    sha = _require_string(value, context)
    if not _SHA_PATTERN.fullmatch(sha):
        raise EvaluationError(f"{context} must be a lowercase 40-character Git SHA")
    return sha


def _load_command(value: object, context: str) -> CommandSpec:
    if not isinstance(value, dict):
        raise EvaluationError(f"{context} must be an object")
    _require_exact_fields(
        value,
        frozenset({"argv", "working_directory", "timeout_seconds"}),
        context,
    )

    raw_argv = value["argv"]
    if not isinstance(raw_argv, list) or not raw_argv:
        raise EvaluationError(f"{context}.argv must be a non-empty array")
    argv = tuple(
        _require_string(argument, f"{context}.argv[{index}]")
        for index, argument in enumerate(raw_argv)
    )
    if argv[0] not in _ALLOWED_EXECUTABLES:
        raise EvaluationError(
            f"{context}.argv executable must be one of {sorted(_ALLOWED_EXECUTABLES)}"
        )
    for argument in argv:
        if any(character in argument for character in "\x00\n\r"):
            raise EvaluationError(f"{context}.argv contains a control character")
        if any(character in argument for character in _SHELL_METACHARACTERS):
            raise EvaluationError(f"{context}.argv contains a shell metacharacter")

    return CommandSpec(
        argv=argv,
        working_directory=safe_relative_path(
            value["working_directory"],
            f"{context}.working_directory",
        ),
        timeout_seconds=_require_positive_integer(
            value["timeout_seconds"],
            f"{context}.timeout_seconds",
        ),
    )


def _load_commands(value: object, context: str) -> tuple[CommandSpec, ...]:
    if not isinstance(value, list) or not value:
        raise EvaluationError(f"{context} must be a non-empty array")
    return tuple(
        _load_command(command, f"{context}[{index}]")
        for index, command in enumerate(value)
    )


def _load_file_hashes(
    value: object,
    catalog_root: Path,
    benchmark_root: Path,
) -> Mapping[str, str]:
    if not isinstance(value, dict):
        raise EvaluationError("file_hashes must be an object")
    expected_paths = {
        "review_request_sha256": benchmark_root / "review-request.md",
        "judge_oracle_sha256": benchmark_root / "judge-oracle.json",
        "judge_rubric_sha256": catalog_root / "judge-rubric.md",
    }
    _require_exact_fields(value, frozenset(expected_paths), "file_hashes")

    hashes: dict[str, str] = {}
    for field, path in expected_paths.items():
        declared_hash = _require_string(value[field], f"file_hashes.{field}")
        if not _HASH_PATTERN.fullmatch(declared_hash):
            raise EvaluationError(f"{field} must be a lowercase SHA-256 digest")
        try:
            actual_hash = sha256_file(path)
        except OSError as error:
            raise EvaluationError(f"unable to hash {field}: {error}") from error
        if actual_hash != declared_hash:
            raise EvaluationError(
                f"{field} mismatch: declared {declared_hash}, actual {actual_hash}"
            )
        hashes[field] = declared_hash
    return MappingProxyType(hashes)


def load_benchmark(catalog_root: Path, benchmark_id: str) -> Benchmark:
    """Load and strictly validate one committed evaluation benchmark."""

    if not _BENCHMARK_ID_PATTERN.fullmatch(benchmark_id):
        raise EvaluationError("benchmark_id must be a lowercase stable identifier")
    catalog_root = Path(catalog_root)
    benchmark_root = catalog_root / "benchmarks" / benchmark_id
    manifest = _load_json_object(benchmark_root / "manifest.json", "benchmark manifest")
    _require_exact_fields(manifest, _MANIFEST_FIELDS, "benchmark manifest")

    if manifest["schema"] != _BENCHMARK_SCHEMA:
        raise EvaluationError(f"unsupported benchmark schema: {manifest['schema']!r}")
    if manifest["benchmark_id"] != benchmark_id:
        raise EvaluationError("benchmark_id does not match its catalog directory")

    baseline_sha = _validate_git_sha(manifest["baseline_sha"], "baseline_sha")
    comparison_sha = _validate_git_sha(manifest["comparison_sha"], "comparison_sha")
    if baseline_sha == comparison_sha:
        raise EvaluationError("baseline_sha and comparison_sha must differ")

    require_immediate_parent = _require_boolean(
        manifest["require_immediate_parent"],
        "require_immediate_parent",
    )
    if not require_immediate_parent:
        raise EvaluationError("require_immediate_parent must be true")
    review_mode = _require_string(manifest["review_mode"], "review_mode")
    if review_mode != "range":
        raise EvaluationError("review_mode must be 'range'")
    posture = _require_string(manifest["posture"], "posture")
    if posture != "immutable":
        raise EvaluationError("posture must be 'immutable'")
    include_untracked = _require_boolean(
        manifest["include_untracked"],
        "include_untracked",
    )
    if include_untracked:
        raise EvaluationError("include_untracked must be false")

    trial_policy = manifest["trial_policy"]
    if not isinstance(trial_policy, dict):
        raise EvaluationError("trial_policy must be an object")
    _require_exact_fields(
        trial_policy,
        frozenset({"initial_trials", "conditional_third"}),
        "trial_policy",
    )
    initial_trials = _require_positive_integer(
        trial_policy["initial_trials"],
        "trial_policy.initial_trials",
    )
    conditional_third = _require_boolean(
        trial_policy["conditional_third"],
        "trial_policy.conditional_third",
    )
    if initial_trials != 2 or not conditional_third:
        raise EvaluationError("trial_policy must require two initial and a conditional third trial")

    gate_policy = manifest["gate_policy"]
    if not isinstance(gate_policy, dict):
        raise EvaluationError("gate_policy must be an object")
    _require_exact_fields(
        gate_policy,
        frozenset({"gate_a", "gate_b"}),
        "gate_policy",
    )
    gate_a_policy = _require_string(gate_policy["gate_a"], "gate_policy.gate_a")
    gate_b_policy = _require_string(gate_policy["gate_b"], "gate_policy.gate_b")
    if gate_a_policy != "approve_all_retained_for_planning":
        raise EvaluationError("gate_policy.gate_a is unsupported")
    if gate_b_policy != "approve_validated_plan_no_repair":
        raise EvaluationError("gate_policy.gate_b must prohibit repair")

    prohibitions = frozenset(
        _require_string_tuple(manifest["prohibitions"], "prohibitions")
    )
    if prohibitions != _REQUIRED_PROHIBITIONS:
        missing = sorted(_REQUIRED_PROHIBITIONS - prohibitions)
        unexpected = sorted(prohibitions - _REQUIRED_PROHIBITIONS)
        raise EvaluationError(
            f"prohibitions must preserve repair and safety boundaries; "
            f"missing={missing}, unexpected={unexpected}"
        )

    infrastructure_retry_limit = manifest["infrastructure_retry_limit"]
    if (
        isinstance(infrastructure_retry_limit, bool)
        or infrastructure_retry_limit != 1
    ):
        raise EvaluationError("infrastructure_retry_limit must be 1")

    isolation_policy = manifest["executor_isolation_policy"]
    if not isinstance(isolation_policy, dict):
        raise EvaluationError("executor_isolation_policy must be an object")
    _require_exact_fields(
        isolation_policy,
        frozenset(
            {
                "allowed_modes",
                "exposed_roots",
                "fresh_agent_context",
                "fresh_target_clone",
            }
        ),
        "executor_isolation_policy",
    )
    isolation_modes = _require_string_tuple(
        isolation_policy["allowed_modes"],
        "executor_isolation_policy.allowed_modes",
    )
    if isolation_modes != ("filesystem_blinding", "logical_blinding"):
        raise EvaluationError("executor isolation modes are unsupported")
    exposed_roots = _require_string_tuple(
        isolation_policy["exposed_roots"],
        "executor_isolation_policy.exposed_roots",
    )
    if exposed_roots != ("trial_workflow", "target", "trial_output"):
        raise EvaluationError("executor exposed roots are unsupported")
    require_fresh_agent_context = _require_boolean(
        isolation_policy["fresh_agent_context"],
        "executor_isolation_policy.fresh_agent_context",
    )
    require_fresh_target_clone = _require_boolean(
        isolation_policy["fresh_target_clone"],
        "executor_isolation_policy.fresh_target_clone",
    )
    if not require_fresh_agent_context or not require_fresh_target_clone:
        raise EvaluationError("executor isolation requires a fresh context and target clone")

    return Benchmark(
        benchmark_id=benchmark_id,
        root=benchmark_root,
        target_repository=_validate_repository_url(manifest["target_repository"]),
        baseline_sha=baseline_sha,
        comparison_sha=comparison_sha,
        require_immediate_parent=require_immediate_parent,
        review_mode=review_mode,
        posture=posture,
        include_untracked=include_untracked,
        baseline_validation_commands=_load_commands(
            manifest["baseline_validation_commands"],
            "baseline_validation_commands",
        ),
        dependency_installation_commands=_load_commands(
            manifest["dependency_installation_commands"],
            "dependency_installation_commands",
        ),
        initial_trials=initial_trials,
        conditional_third=conditional_third,
        default_timeout_seconds=_require_positive_integer(
            manifest["default_timeout_seconds"],
            "default_timeout_seconds",
        ),
        infrastructure_retry_limit=infrastructure_retry_limit,
        gate_a_policy=gate_a_policy,
        gate_b_policy=gate_b_policy,
        required_artifacts=_require_string_tuple(
            manifest["required_artifacts"],
            "required_artifacts",
        ),
        required_lenses=_require_string_tuple(
            manifest["required_lenses"],
            "required_lenses",
        ),
        prohibitions=prohibitions,
        executor_isolation_modes=isolation_modes,
        executor_exposed_roots=exposed_roots,
        require_fresh_agent_context=require_fresh_agent_context,
        require_fresh_target_clone=require_fresh_target_clone,
        file_hashes=_load_file_hashes(
            manifest["file_hashes"],
            catalog_root,
            benchmark_root,
        ),
    )
