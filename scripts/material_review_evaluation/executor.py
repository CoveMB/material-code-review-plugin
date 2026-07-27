from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Literal, Mapping, Protocol, Sequence

from .model import EvaluationError


SessionStatus = Literal["running", "waiting", "complete", "failed"]
FailureKind = Literal[
    "launch_error",
    "timeout",
    "nonzero_exit",
    "malformed_jsonl",
    "missing_thread_id",
    "session_mismatch",
    "missing_final_output",
    "schema_invalid_output",
]


@dataclass(frozen=True)
class SessionSpec:
    role: str
    working_directory: Path
    readable_workflow: Path | None
    output_directory: Path
    prompt_path: Path
    output_schema: Path | None
    model: str
    reasoning_effort: str
    sandbox_mode: str
    timeout_seconds: int


@dataclass(frozen=True)
class InfrastructureFailure:
    kind: FailureKind
    message: str
    returncode: int | None = None


@dataclass(frozen=True)
class SessionResult:
    session_id: str | None
    status: SessionStatus
    final_output: str | None
    usage: Mapping[str, int]
    tool_events: tuple[dict[str, Any], ...]
    stdout_path: Path
    stderr_path: Path
    failure: InfrastructureFailure | None = None


class AgentExecutor(Protocol):
    def start(self, session_spec: SessionSpec) -> SessionResult: ...

    def resume(
        self,
        session_id: str,
        statement: str,
        session_spec: SessionSpec,
    ) -> SessionResult: ...

    def status(self, session_id: str) -> SessionStatus: ...


Runner = Callable[..., subprocess.CompletedProcess[str]]
_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SENSITIVE_ENVIRONMENT_NAME = re.compile(
    r"(?i)(?:TOKEN|SECRET|PASSWORD|PASSWD|KEY|CREDENTIAL)"
)
_SUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "$defs",
        "$id",
        "$ref",
        "$schema",
        "additionalProperties",
        "allOf",
        "anyOf",
        "const",
        "description",
        "else",
        "enum",
        "format",
        "if",
        "items",
        "maximum",
        "maxItems",
        "maxLength",
        "minimum",
        "minItems",
        "minLength",
        "not",
        "oneOf",
        "pattern",
        "properties",
        "required",
        "then",
        "title",
        "type",
        "uniqueItems",
    }
)
_SUPPORTED_SCHEMA_TYPES = frozenset(
    {"array", "boolean", "integer", "null", "number", "object", "string"}
)


def _popen_runner(
    argv: Sequence[str],
    *,
    cwd: Path,
    input: str,
    env: Mapping[str, str],
    timeout: int,
    shell: bool,
    capture_output: bool,
    text: bool,
) -> subprocess.CompletedProcess[str]:
    if shell is not False or capture_output is not True or text is not True:
        raise EvaluationError("Codex runner requires shell=False and captured text output")
    process = subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )
    try:
        stdout, stderr = process.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
    return subprocess.CompletedProcess(
        list(argv),
        process.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _narrow_environment(source: Mapping[str, str]) -> dict[str, str]:
    exact_names = {
        "PATH",
        "HOME",
        "CODEX_HOME",
        "LANG",
        "LANGUAGE",
        "TMPDIR",
        "TMP",
        "TEMP",
        "OPENAI_API_KEY",
    }
    return {
        name: value
        for name, value in source.items()
        if (name in exact_names or name.startswith("LC_"))
        and (
            name == "OPENAI_API_KEY"
            or _SENSITIVE_ENVIRONMENT_NAME.search(name) is None
        )
    }


def _sensitive_environment_values(source: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                value
                for name, value in source.items()
                if _SENSITIVE_ENVIRONMENT_NAME.search(name) is not None and value
            },
            key=len,
            reverse=True,
        )
    )


def _redact_sensitive_values(text: str, sensitive_values: Sequence[str]) -> str:
    redacted = text
    for value in sensitive_values:
        redacted = redacted.replace(value, "<redacted-credential>")
    return redacted


def _require_regular_file(path: Path, context: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise EvaluationError(f"{context} must be a regular file")
    return candidate.absolute()


def _require_directory(path: Path, context: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_dir():
        raise EvaluationError(f"{context} must be a directory")
    return candidate.absolute()


def _validated_spec(spec: SessionSpec) -> SessionSpec:
    if spec.role not in {"trial", "agreement", "judge"}:
        raise EvaluationError("session role must be trial, agreement, or judge")
    if not isinstance(spec.model, str) or not spec.model.strip():
        raise EvaluationError("session model must be a non-empty string")
    if any(character in spec.model for character in "\x00\n\r"):
        raise EvaluationError("session model must be a single-line value")
    if not isinstance(spec.reasoning_effort, str) or not spec.reasoning_effort.strip():
        raise EvaluationError("reasoning effort must be a non-empty string")
    if any(character in spec.reasoning_effort for character in "\x00\n\r"):
        raise EvaluationError("reasoning effort must be a single-line value")
    if isinstance(spec.timeout_seconds, bool) or not isinstance(spec.timeout_seconds, int):
        raise EvaluationError("session timeout must be a positive integer")
    if spec.timeout_seconds <= 0:
        raise EvaluationError("session timeout must be a positive integer")

    working_directory = _require_directory(
        spec.working_directory,
        "session working directory",
    )
    output_directory = _require_directory(
        spec.output_directory,
        "session output directory",
    )
    prompt_path = _require_regular_file(spec.prompt_path, "session prompt")

    if spec.role == "trial":
        if spec.sandbox_mode != "workspace-write":
            raise EvaluationError("trial sessions require workspace-write sandboxing")
        if spec.readable_workflow is None:
            raise EvaluationError("trial sessions require one materialized workflow")
        readable_workflow = _require_directory(
            spec.readable_workflow,
            "materialized workflow",
        )
        if spec.output_schema is not None:
            raise EvaluationError("trial sessions must not use a judge output schema")
        output_schema = None
    else:
        if spec.sandbox_mode != "read-only":
            raise EvaluationError("agreement and judge sessions require read-only sandboxing")
        if spec.readable_workflow is not None:
            raise EvaluationError("agreement and judge sessions cannot expose a workflow")
        if spec.output_schema is None:
            raise EvaluationError("agreement and judge sessions require an output schema")
        readable_workflow = None
        output_schema = _require_regular_file(
            spec.output_schema,
            "session output schema",
        )

    return SessionSpec(
        role=spec.role,
        working_directory=working_directory,
        readable_workflow=readable_workflow,
        output_directory=output_directory,
        prompt_path=prompt_path,
        output_schema=output_schema,
        model=spec.model,
        reasoning_effort=spec.reasoning_effort,
        sandbox_mode=spec.sandbox_mode,
        timeout_seconds=spec.timeout_seconds,
    )


def _base_argv(spec: SessionSpec) -> list[str]:
    return [
        "codex",
        "exec",
        "--json",
        "--ignore-user-config",
        "--model",
        spec.model,
        "-c",
        f"model_reasoning_effort={spec.reasoning_effort}",
        "--sandbox",
        spec.sandbox_mode,
        "--cd",
        str(spec.working_directory),
    ]


def _start_argv(spec: SessionSpec) -> list[str]:
    argv = _base_argv(spec)
    if spec.role == "trial":
        if spec.readable_workflow is None:
            raise EvaluationError("validated trial spec lost its workflow")
        argv.extend(
            (
                "--add-dir",
                str(spec.readable_workflow),
                "--add-dir",
                str(spec.output_directory),
            )
        )
    else:
        if spec.output_schema is None:
            raise EvaluationError("validated judge spec lost its output schema")
        argv.extend(
            (
                "--skip-git-repo-check",
                "--ephemeral",
                "--output-schema",
                str(spec.output_schema),
            )
        )
    argv.append("-")
    return argv


def _resume_argv(session_id: str, spec: SessionSpec) -> list[str]:
    return [
        "codex",
        "exec",
        "resume",
        "--json",
        "--ignore-user-config",
        "--model",
        spec.model,
        "-c",
        f"model_reasoning_effort={spec.reasoning_effort}",
        "-c",
        f'sandbox_mode="{spec.sandbox_mode}"',
        session_id,
        "-",
    ]


def _text_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _parse_jsonl(
    stdout: str,
) -> tuple[str | None, str | None, dict[str, int], tuple[dict[str, Any], ...]]:
    thread_id: str | None = None
    final_output: str | None = None
    usage: dict[str, int] = {}
    tool_events: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(stdout.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise ValueError(f"JSONL line {line_number} is malformed") from error
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise ValueError(f"JSONL line {line_number} is not an event object")
        event_type = event["type"]
        if event_type == "thread.started":
            candidate = event.get("thread_id")
            if (
                not isinstance(candidate, str)
                or _SESSION_ID_PATTERN.fullmatch(candidate) is None
            ):
                raise ValueError("thread.started contains an invalid thread ID")
            if thread_id is not None and thread_id != candidate:
                raise ValueError("JSONL contains multiple thread IDs")
            thread_id = candidate
        raw_usage = event.get("usage")
        if isinstance(raw_usage, dict):
            usage = {
                key: value
                for key, value in raw_usage.items()
                if isinstance(key, str)
                and isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
            }
        item = event.get("item")
        if isinstance(item, dict):
            item_type = item.get("type")
            if (
                event_type == "item.completed"
                and item_type == "agent_message"
                and isinstance(item.get("text"), str)
            ):
                final_output = item["text"]
            elif item_type not in {None, "agent_message", "reasoning"}:
                tool_events.append(event)
    return thread_id, final_output, usage, tuple(tool_events)


def _resolve_schema_reference(reference: str, root_schema: Mapping[str, Any]) -> Any:
    if not reference.startswith("#/"):
        raise ValueError("only local JSON Schema references are supported")
    value: Any = root_schema
    for encoded_part in reference[2:].split("/"):
        part = encoded_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or part not in value:
            raise ValueError("JSON Schema contains an unresolved reference")
        value = value[part]
    return value


def _validate_schema_definition(
    schema: Any,
    root_schema: Mapping[str, Any],
    *,
    visited: set[int] | None = None,
) -> None:
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        raise ValueError("output schema contains a non-object subschema")
    unexpected = set(schema) - _SUPPORTED_SCHEMA_KEYWORDS
    if unexpected:
        raise ValueError("output schema contains an unsupported keyword")
    seen = set() if visited is None else visited
    identity = id(schema)
    if identity in seen:
        return
    seen.add(identity)

    expected_type = schema.get("type")
    if expected_type is not None:
        if isinstance(expected_type, str):
            types = (expected_type,)
        elif (
            isinstance(expected_type, list)
            and expected_type
            and all(isinstance(item, str) for item in expected_type)
            and len(expected_type) == len(set(expected_type))
        ):
            types = tuple(expected_type)
        else:
            raise ValueError("output schema contains an invalid type declaration")
        if any(item not in _SUPPORTED_SCHEMA_TYPES for item in types):
            raise ValueError("output schema contains an unsupported JSON type")

    for keyword in ("$schema", "$id", "title", "description"):
        if keyword in schema and not isinstance(schema[keyword], str):
            raise ValueError(f"output schema {keyword} must be a string")
    for keyword in ("minItems", "maxItems", "minLength", "maxLength"):
        if keyword in schema and (
            isinstance(schema[keyword], bool)
            or not isinstance(schema[keyword], int)
            or schema[keyword] < 0
        ):
            raise ValueError(f"output schema {keyword} must be a non-negative integer")
    for keyword in ("minimum", "maximum"):
        if keyword in schema and (
            isinstance(schema[keyword], bool)
            or not isinstance(schema[keyword], (int, float))
        ):
            raise ValueError(f"output schema {keyword} must be a number")
    if "uniqueItems" in schema and not isinstance(schema["uniqueItems"], bool):
        raise ValueError("output schema uniqueItems must be a boolean")

    if "$ref" in schema:
        reference = schema["$ref"]
        if not isinstance(reference, str):
            raise ValueError("output schema contains a non-string reference")
        _resolve_schema_reference(reference, root_schema)
    if "pattern" in schema:
        pattern = schema["pattern"]
        if not isinstance(pattern, str):
            raise ValueError("output schema pattern must be a string")
        try:
            re.compile(pattern)
        except re.error as error:
            raise ValueError("output schema contains an invalid pattern") from error
    if "format" in schema and schema["format"] != "date-time":
        raise ValueError("output schema contains an unsupported format")
    if "required" in schema:
        required = schema["required"]
        if (
            not isinstance(required, list)
            or any(not isinstance(item, str) for item in required)
            or len(required) != len(set(required))
        ):
            raise ValueError("output schema contains an invalid required list")
    if "enum" in schema and (
        not isinstance(schema["enum"], list) or not schema["enum"]
    ):
        raise ValueError("output schema enum must be a non-empty array")
    if "additionalProperties" in schema and not isinstance(
        schema["additionalProperties"],
        (bool, dict),
    ):
        raise ValueError("output schema additionalProperties is invalid")
    if ("then" in schema or "else" in schema) and "if" not in schema:
        raise ValueError("output schema then/else requires if")
    for keyword in ("items", "not", "if", "then", "else"):
        if keyword in schema and not isinstance(schema[keyword], (bool, dict)):
            raise ValueError(f"output schema {keyword} must be a schema")

    for container_name in ("properties", "$defs"):
        container = schema.get(container_name, {})
        if not isinstance(container, dict):
            raise ValueError(f"output schema {container_name} must be an object")
        for name, child in container.items():
            if not isinstance(name, str):
                raise ValueError(f"output schema {container_name} has a non-string key")
            _validate_schema_definition(child, root_schema, visited=seen)
    for keyword in ("allOf", "anyOf", "oneOf"):
        children = schema.get(keyword, [])
        if not isinstance(children, list) or (keyword in schema and not children):
            raise ValueError(f"output schema {keyword} must be a non-empty array")
        for child in children:
            _validate_schema_definition(child, root_schema, visited=seen)
    for keyword in ("items", "not", "if", "then", "else", "additionalProperties"):
        child = schema.get(keyword)
        if isinstance(child, (bool, dict)):
            _validate_schema_definition(child, root_schema, visited=seen)


def _schema_matches(value: Any, schema: Any, root_schema: Mapping[str, Any]) -> bool:
    try:
        _validate_json_value(value, schema, root_schema)
    except ValueError:
        return False
    return True


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise ValueError(f"unsupported JSON Schema type: {expected}")


def _matches_declared_type(value: Any, expected: object) -> bool:
    if isinstance(expected, str):
        return _matches_type(value, expected)
    if isinstance(expected, list):
        return any(_matches_type(value, item) for item in expected)
    raise ValueError("output schema contains an invalid type declaration")


def _is_valid_datetime(value: str) -> bool:
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _validate_json_value(
    value: Any,
    schema: Any,
    root_schema: Mapping[str, Any],
    context: str = "$",
) -> None:
    if isinstance(schema, bool):
        if not schema:
            raise ValueError(f"{context} is forbidden by the output schema")
        return
    if not isinstance(schema, dict):
        raise ValueError("output schema contains a non-object subschema")
    if "$ref" in schema:
        reference = schema["$ref"]
        if not isinstance(reference, str):
            raise ValueError("output schema contains a non-string reference")
        _validate_json_value(
            value,
            _resolve_schema_reference(reference, root_schema),
            root_schema,
            context,
        )
    for child in schema.get("allOf", []):
        _validate_json_value(value, child, root_schema, context)
    if "anyOf" in schema and not any(
        _schema_matches(value, child, root_schema)
        for child in schema["anyOf"]
    ):
        raise ValueError(f"{context} does not match any allowed schema")
    if "oneOf" in schema and sum(
        _schema_matches(value, child, root_schema)
        for child in schema["oneOf"]
    ) != 1:
        raise ValueError(f"{context} does not match exactly one allowed schema")
    if "not" in schema and _schema_matches(value, schema["not"], root_schema):
        raise ValueError(f"{context} matches a forbidden schema")
    if "if" in schema:
        branch = "then" if _schema_matches(value, schema["if"], root_schema) else "else"
        if branch in schema:
            _validate_json_value(value, schema[branch], root_schema, context)
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"{context} does not match its required constant")
    if "enum" in schema:
        options = schema["enum"]
        if not isinstance(options, list) or value not in options:
            raise ValueError(f"{context} is not an allowed value")
    expected_type = schema.get("type")
    if expected_type is not None and not _matches_declared_type(value, expected_type):
        raise ValueError(f"{context} has the wrong JSON type")

    if isinstance(value, dict):
        required = schema.get("required", [])
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            raise ValueError("output schema contains an invalid required list")
        missing = [name for name in required if name not in value]
        if missing:
            raise ValueError(f"{context} is missing required properties")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise ValueError("output schema properties must be an object")
        for name, item in value.items():
            if name in properties:
                _validate_json_value(
                    item,
                    properties[name],
                    root_schema,
                    f"{context}.{name}",
                )
            elif schema.get("additionalProperties") is False:
                raise ValueError(f"{context} contains an unexpected property")
            elif isinstance(schema.get("additionalProperties"), dict):
                _validate_json_value(
                    item,
                    schema["additionalProperties"],
                    root_schema,
                    f"{context}.{name}",
                )
    elif isinstance(value, list):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            raise ValueError(f"{context} has too few items")
        if isinstance(maximum, int) and len(value) > maximum:
            raise ValueError(f"{context} has too many items")
        if schema.get("uniqueItems") is True:
            encoded = [
                json.dumps(item, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                for item in value
            ]
            if len(encoded) != len(set(encoded)):
                raise ValueError(f"{context} contains duplicate items")
        if "items" in schema:
            for index, item in enumerate(value):
                _validate_json_value(
                    item,
                    schema["items"],
                    root_schema,
                    f"{context}[{index}]",
                )
    elif isinstance(value, str):
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if isinstance(minimum, int) and len(value) < minimum:
            raise ValueError(f"{context} is too short")
        if isinstance(maximum, int) and len(value) > maximum:
            raise ValueError(f"{context} is too long")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            raise ValueError(f"{context} does not match its required pattern")
        if schema.get("format") == "date-time" and not _is_valid_datetime(value):
            raise ValueError(f"{context} is not a valid date-time")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            raise ValueError(f"{context} is below its minimum")
        if isinstance(maximum, (int, float)) and value > maximum:
            raise ValueError(f"{context} is above its maximum")


def _validate_final_output(output: str, schema_path: Path) -> None:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        value = json.loads(output)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("final output or output schema is not valid JSON") from error
    if not isinstance(schema, dict):
        raise ValueError("output schema must be a JSON object")
    _validate_schema_definition(schema, schema)
    _validate_json_value(value, schema, schema)


class CodexExecutor:
    def __init__(
        self,
        *,
        runner: Runner | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._runner = runner or _popen_runner
        source_environment = os.environ if environment is None else environment
        self._environment = _narrow_environment(source_environment)
        self._sensitive_values = _sensitive_environment_values(source_environment)
        self._specs: dict[str, SessionSpec] = {}
        self._statuses: dict[str, SessionStatus] = {}

    def start(self, session_spec: SessionSpec) -> SessionResult:
        spec = _validated_spec(session_spec)
        return self._execute(_start_argv(spec), spec.prompt_path.read_text(encoding="utf-8"), spec)

    def resume(
        self,
        session_id: str,
        statement: str,
        session_spec: SessionSpec,
    ) -> SessionResult:
        if session_id not in self._specs:
            raise EvaluationError("cannot resume an unrecorded Codex session")
        recorded = self._specs[session_id]
        supplied = _validated_spec(session_spec)
        if supplied != recorded:
            raise EvaluationError("resume configuration differs from the recorded session")
        if recorded.role != "trial":
            raise EvaluationError("ephemeral agreement and judge sessions cannot be resumed")
        if not isinstance(statement, str) or not statement.strip():
            raise EvaluationError("resume statement must be a non-empty string")
        return self._execute(
            _resume_argv(session_id, recorded),
            statement,
            recorded,
            expected_session_id=session_id,
        )

    def status(self, session_id: str) -> SessionStatus:
        return self._statuses.get(session_id, "failed")

    def _execute(
        self,
        argv: list[str],
        prompt: str,
        spec: SessionSpec,
        *,
        expected_session_id: str | None = None,
    ) -> SessionResult:
        invocation_id = uuid.uuid4().hex
        logs_root = spec.output_directory / "session-logs"
        logs_root.mkdir(parents=True, exist_ok=True)
        stdout_path = logs_root / f"{invocation_id}.stdout.jsonl"
        stderr_path = logs_root / f"{invocation_id}.stderr.log"
        if expected_session_id is not None:
            self._statuses[expected_session_id] = "running"
        try:
            completed = self._runner(
                argv,
                cwd=spec.working_directory,
                input=prompt,
                env=dict(self._environment),
                timeout=spec.timeout_seconds,
                shell=False,
                capture_output=True,
                text=True,
            )
            stdout = _text_output(completed.stdout)
            stderr = _text_output(completed.stderr)
        except subprocess.TimeoutExpired as error:
            stdout = _text_output(error.stdout)
            stderr = _text_output(error.stderr)
            stdout_path.write_text(
                _redact_sensitive_values(stdout, self._sensitive_values),
                encoding="utf-8",
            )
            stderr_path.write_text(
                _redact_sensitive_values(stderr, self._sensitive_values),
                encoding="utf-8",
            )
            return self._failed_result(
                expected_session_id,
                "timeout",
                "Codex process exceeded its exact session timeout",
                stdout_path,
                stderr_path,
            )
        except (OSError, subprocess.SubprocessError) as error:
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            return self._failed_result(
                expected_session_id,
                "launch_error",
                f"Codex process could not run: {type(error).__name__}",
                stdout_path,
                stderr_path,
            )

        stdout_path.write_text(
            _redact_sensitive_values(stdout, self._sensitive_values),
            encoding="utf-8",
        )
        stderr_path.write_text(
            _redact_sensitive_values(stderr, self._sensitive_values),
            encoding="utf-8",
        )
        if completed.returncode != 0:
            return self._failed_result(
                expected_session_id,
                "nonzero_exit",
                f"Codex process exited with code {completed.returncode}",
                stdout_path,
                stderr_path,
                returncode=completed.returncode,
            )
        try:
            session_id, final_output, usage, tool_events = _parse_jsonl(stdout)
        except ValueError:
            return self._failed_result(
                expected_session_id,
                "malformed_jsonl",
                "Codex process returned malformed JSONL events",
                stdout_path,
                stderr_path,
            )
        if session_id is None:
            return self._failed_result(
                expected_session_id,
                "missing_thread_id",
                "Codex JSONL did not contain a thread.started ID",
                stdout_path,
                stderr_path,
            )
        if expected_session_id is not None and session_id != expected_session_id:
            return self._failed_result(
                expected_session_id,
                "session_mismatch",
                "resumed Codex process returned a different session ID",
                stdout_path,
                stderr_path,
            )
        if final_output is None:
            return self._failed_result(
                session_id,
                "missing_final_output",
                "Codex JSONL did not contain a completed final agent message",
                stdout_path,
                stderr_path,
            )
        if spec.output_schema is not None:
            try:
                _validate_final_output(final_output, spec.output_schema)
            except ValueError:
                return self._failed_result(
                    session_id,
                    "schema_invalid_output",
                    "Codex final output does not conform to the configured schema",
                    stdout_path,
                    stderr_path,
                )

        self._specs[session_id] = spec
        self._statuses[session_id] = "complete"
        return SessionResult(
            session_id=session_id,
            status="complete",
            final_output=final_output,
            usage=MappingProxyType(usage),
            tool_events=tool_events,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

    def _failed_result(
        self,
        session_id: str | None,
        kind: FailureKind,
        message: str,
        stdout_path: Path,
        stderr_path: Path,
        *,
        returncode: int | None = None,
    ) -> SessionResult:
        if session_id is not None:
            self._statuses[session_id] = "failed"
        return SessionResult(
            session_id=session_id,
            status="failed",
            final_output=None,
            usage=MappingProxyType({}),
            tool_events=(),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            failure=InfrastructureFailure(kind, message, returncode),
        )
