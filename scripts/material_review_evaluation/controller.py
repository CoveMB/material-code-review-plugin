from __future__ import annotations

import copy
import json
import secrets
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence

from .artifacts import (
    NativeTrialArtifacts,
    find_native_run,
    gate_a_command,
    gate_b_command,
    normalize_trial_evidence,
    validate_gate_a_artifacts,
    validate_gate_b_artifacts,
)
from .benchmark import Benchmark, CommandSpec
from .bundles import (
    build_agreement_bundle,
    build_comparison_bundle,
    build_trial_request,
    scan_blinded_bundle,
)
from .executor import AgentExecutor, SessionResult, SessionSpec, _validate_final_output
from .model import (
    EvaluationError,
    atomic_write_json,
    canonical_hash,
    safe_relative_path,
    sha256_file,
)
from .workspace import (
    CommandResult,
    ResolvedVariant,
    WorkspaceRecord,
    clean_owned_workspaces,
    create_trial_target,
    materialize_variant,
    prepare_target_mirror,
    resolve_variant,
    run_benchmark_commands,
    verify_benchmark_range,
)


RUN_SCHEMA = "material-review-evaluation/run/v1"
PHASES = (
    "PREFLIGHT",
    "PREPARED",
    "INITIAL_TRIALS",
    "CONSISTENCY_CHECK",
    "OPTIONAL_THIRD_TRIAL",
    "BLINDED_JUDGMENT",
    "IDENTITY_REVEAL",
    "COMPLETE",
)
TERMINAL_PHASES = frozenset({"COMPLETE", "INCOMPLETE", "ABORTED"})
GATE_A_FINDINGS_STATEMENT = (
    "Evaluation policy approves every retained finding for planning and no others; "
    "repair is not authorized."
)
GATE_A_EMPTY_STATEMENT = (
    "Evaluation policy accepts the empty material ledger; repair is not authorized."
)
GATE_B_STATEMENT = (
    "Evaluation policy approves this exact validated plan for comparison evidence only; "
    "no repair or plan command execution is authorized."
)


class RandomSource(Protocol):
    def sample(self, population: Sequence[str], count: int) -> list[str]: ...


@dataclass(frozen=True)
class EvaluationRequest:
    repository_root: Path
    benchmark: Benchmark
    base_ref: str
    candidate_ref: str
    executor_adapter: str
    adapter_version: str
    model: str
    reasoning_effort: str
    permission_profile: str
    isolation_mode: str
    target_repository: Path | str | None = None
    new_run: bool = False


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    run_root: Path
    phase: str
    terminal_reason: str | None
    semantic_trial_counts: Mapping[str, int]
    judgment_sha256: str | None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_after(value: str) -> str:
    now = datetime.now(timezone.utc)
    try:
        predecessor = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvaluationError("persisted timestamp is not RFC 3339") from error
    if now <= predecessor:
        now = predecessor + timedelta(microseconds=1)
    return now.isoformat().replace("+00:00", "Z")


def _require_text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationError(f"{context} must be a non-empty string")
    if any(character in value for character in "\x00\n\r"):
        raise EvaluationError(f"{context} must be a single-line string")
    return value


def _command_payload(command: CommandSpec) -> dict[str, Any]:
    return {
        "argv": list(command.argv),
        "working_directory": command.working_directory.as_posix(),
        "timeout_seconds": command.timeout_seconds,
    }


def _workspace_payload(record: WorkspaceRecord) -> dict[str, Any]:
    return {
        **asdict(record),
        "path": str(record.path),
    }


def _workspace_from_payload(value: Mapping[str, Any]) -> WorkspaceRecord:
    return WorkspaceRecord(
        kind=str(value["kind"]),
        path=Path(str(value["path"])),
        owner_run_id=str(value["owner_run_id"]),
        expected_head=(
            str(value["expected_head"])
            if value.get("expected_head") is not None
            else None
        ),
        initial_status_sha256=str(value["initial_status_sha256"]),
    )


class EvaluationController:
    """Drive one blinded material-review comparison through durable checkpoints."""

    def __init__(
        self,
        *,
        runs_root: Path,
        executor: AgentExecutor,
        random_source: RandomSource | None = None,
    ) -> None:
        self.runs_root = Path(runs_root).resolve(strict=False)
        self.runs_root.mkdir(parents=True, exist_ok=True)
        if self.runs_root.is_symlink() or not self.runs_root.is_dir():
            raise EvaluationError("evaluation runs root must be a regular directory")
        self.executor = executor
        self.random_source = random_source or secrets.SystemRandom()

    def compare(self, request: EvaluationRequest) -> RunSummary:
        validated = self._validated_request(request)
        benchmark_hashes = self._benchmark_hashes(validated.benchmark)
        fingerprint = self._request_fingerprint(validated, benchmark_hashes)
        run_root = None if validated.new_run else self._matching_run(fingerprint)
        if run_root is None:
            run_root = self._create_run(validated, benchmark_hashes, fingerprint)
        state = self._load_run(run_root)
        if state["phase"] in TERMINAL_PHASES:
            return self._summary(run_root, state)
        if state["executor_configuration"] != self._executor_configuration(validated):
            state = self._terminal(
                run_root,
                str(state["phase"]),
                "ABORTED",
                "executor, model, reasoning, or permission configuration differs from the resumable run",
            )
            return self._summary(run_root, state)
        try:
            state = self._drive(run_root, validated)
        except EvaluationError as error:
            current = self._load_run(run_root)
            if current["phase"] in TERMINAL_PHASES:
                state = current
            else:
                state = self._terminal(
                    run_root,
                    str(current["phase"]),
                    "INCOMPLETE",
                    str(error),
                )
        return self._summary(run_root, state)

    def status(self, run_id: str) -> RunSummary:
        run_root = self._run_root(run_id)
        return self._summary(run_root, self._load_run(run_root))

    def clean(self, run_id: str) -> tuple[Path, ...]:
        run_root = self._run_root(run_id)
        state = self._load_run(run_root)
        if state["phase"] not in TERMINAL_PHASES:
            raise EvaluationError("cleanup requires a terminal evaluation run")
        private_request = self._read_json(run_root / "private/request.json", "private request")
        repository_root = Path(str(private_request["repository_root"]))
        records = self._load_workspace_records(run_root)
        removable = tuple(record for record in records if record.path.exists())
        removed = clean_owned_workspaces(repository_root, removable)

        removed_strings = {str(path) for path in removed}

        def mark_cleaned(value: dict[str, Any]) -> None:
            for workspace in value["workspaces"]:
                if workspace["path"] in removed_strings:
                    workspace["cleaned"] = True

        self._update_run(run_root, mark_cleaned)
        return removed

    def _validated_request(self, request: EvaluationRequest) -> EvaluationRequest:
        if not isinstance(request, EvaluationRequest):
            raise EvaluationError("compare requires an EvaluationRequest")
        repository_root = Path(request.repository_root).resolve(strict=True)
        benchmark = request.benchmark
        if not isinstance(benchmark, Benchmark):
            raise EvaluationError("evaluation request requires a validated Benchmark")
        for value, context in (
            (request.base_ref, "base ref"),
            (request.candidate_ref, "candidate ref"),
            (request.executor_adapter, "executor adapter"),
            (request.adapter_version, "executor adapter version"),
            (request.model, "model"),
            (request.reasoning_effort, "reasoning effort"),
            (request.permission_profile, "permission profile"),
            (request.isolation_mode, "isolation mode"),
        ):
            _require_text(value, context)
        if request.isolation_mode not in benchmark.executor_isolation_modes:
            raise EvaluationError("requested isolation mode is not allowed by the benchmark")
        if (
            benchmark.initial_trials != 2
            or not benchmark.conditional_third
            or benchmark.infrastructure_retry_limit != 1
            or not benchmark.require_fresh_agent_context
            or not benchmark.require_fresh_target_clone
            or "repair" not in benchmark.prohibitions
        ):
            raise EvaluationError("benchmark does not preserve the evaluator trial and safety policy")
        if not isinstance(request.new_run, bool):
            raise EvaluationError("new_run must be a boolean")
        target: Path | str | None = request.target_repository
        if isinstance(target, Path):
            target = target.resolve(strict=True)
        elif target is not None:
            target = _require_text(target, "target repository")
        return EvaluationRequest(
            repository_root=repository_root,
            benchmark=benchmark,
            base_ref=request.base_ref,
            candidate_ref=request.candidate_ref,
            target_repository=target,
            executor_adapter=request.executor_adapter,
            adapter_version=request.adapter_version,
            model=request.model,
            reasoning_effort=request.reasoning_effort,
            permission_profile=request.permission_profile,
            isolation_mode=request.isolation_mode,
            new_run=request.new_run,
        )

    def _benchmark_hashes(self, benchmark: Benchmark) -> dict[str, str]:
        root = benchmark.root
        evaluation_root = root.parents[1]
        paths = {
            "manifest_sha256": root / "manifest.json",
            "review_request_sha256": root / "review-request.md",
            "judge_oracle_sha256": root / "judge-oracle.json",
            "judge_rubric_sha256": evaluation_root / "judge-rubric.md",
        }
        hashes: dict[str, str] = {}
        for field, path in paths.items():
            if path.is_symlink() or not path.is_file():
                raise EvaluationError(f"required benchmark artifact is missing: {path}")
            hashes[field] = sha256_file(path)
        declared = benchmark.file_hashes
        for field in (
            "review_request_sha256",
            "judge_oracle_sha256",
            "judge_rubric_sha256",
        ):
            if declared.get(field) != hashes[field]:
                raise EvaluationError(f"benchmark artifact hash changed: {field}")
        return hashes

    def _request_fingerprint(
        self,
        request: EvaluationRequest,
        benchmark_hashes: Mapping[str, str],
    ) -> str:
        target = request.target_repository or request.benchmark.target_repository
        return canonical_hash(
            {
                "repository_root": str(request.repository_root),
                "base_ref": request.base_ref,
                "candidate_ref": request.candidate_ref,
                "benchmark_id": request.benchmark.benchmark_id,
                "benchmark_hashes": dict(benchmark_hashes),
                "benchmark_range": {
                    "baseline": request.benchmark.baseline_sha,
                    "comparison": request.benchmark.comparison_sha,
                },
                "target_repository": str(target),
                "dependency_installation_commands": [
                    _command_payload(command)
                    for command in request.benchmark.dependency_installation_commands
                ],
                "baseline_validation_commands": [
                    _command_payload(command)
                    for command in request.benchmark.baseline_validation_commands
                ],
                "trial_policy": {
                    "initial_trials": request.benchmark.initial_trials,
                    "conditional_third": request.benchmark.conditional_third,
                    "infrastructure_retry_limit": request.benchmark.infrastructure_retry_limit,
                },
                "gate_policy": {
                    "gate_a": request.benchmark.gate_a_policy,
                    "gate_b": request.benchmark.gate_b_policy,
                },
                "required_lenses": list(request.benchmark.required_lenses),
                "prohibitions": sorted(request.benchmark.prohibitions),
                "executor_isolation": {
                    "modes": list(request.benchmark.executor_isolation_modes),
                    "exposed_roots": list(request.benchmark.executor_exposed_roots),
                    "fresh_agent_context": request.benchmark.require_fresh_agent_context,
                    "fresh_target_clone": request.benchmark.require_fresh_target_clone,
                },
                "default_timeout_seconds": request.benchmark.default_timeout_seconds,
            }
        )

    def _executor_configuration(self, request: EvaluationRequest) -> dict[str, str]:
        return {
            "adapter": request.executor_adapter,
            "adapter_version": request.adapter_version,
            "model": request.model,
            "reasoning_effort": request.reasoning_effort,
            "permission_profile": request.permission_profile,
            "isolation_mode": request.isolation_mode,
        }

    def _matching_run(self, fingerprint: str) -> Path | None:
        matches: list[tuple[str, Path]] = []
        for run_json in self.runs_root.glob("*/run.json"):
            if run_json.is_symlink() or not run_json.is_file():
                continue
            try:
                value = json.loads(run_json.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if (
                isinstance(value, dict)
                and value.get("request_fingerprint") == fingerprint
                and value.get("phase") not in TERMINAL_PHASES
            ):
                matches.append((str(value.get("updated_at", "")), run_json.parent))
        return max(matches, key=lambda item: item[0])[1] if matches else None

    def _create_run(
        self,
        request: EvaluationRequest,
        benchmark_hashes: Mapping[str, str],
        fingerprint: str,
    ) -> Path:
        if request.permission_profile != "workspace-write":
            raise EvaluationError("trial permission profile must be workspace-write")
        baseline = resolve_variant(request.repository_root, request.base_ref)
        candidate = resolve_variant(request.repository_root, request.candidate_ref)
        if baseline.commit_sha == candidate.commit_sha:
            raise EvaluationError("baseline and candidate skill refs resolve to the same commit")
        run_id = f"evaluation-{uuid.uuid4().hex}"
        run_root = self.runs_root / run_id
        run_root.mkdir(parents=False, exist_ok=False)
        (run_root / "private").mkdir()
        (run_root / "state" / "checkpoints").mkdir(parents=True)
        created_at = _utc_now()
        identity_order = self.random_source.sample(["baseline", "candidate"], 2)
        if sorted(identity_order) != ["baseline", "candidate"]:
            raise EvaluationError("private variant randomization did not return a permutation")
        private_map = {
            "schema": "material-review-evaluation/private-variant-map/v1",
            "variants": {"A": identity_order[0], "B": identity_order[1]},
            "created_at": created_at,
        }
        private_map_path = run_root / "private/variant-map.json"
        atomic_write_json(private_map_path, private_map)
        atomic_write_json(
            run_root / "private/resolved-variants.json",
            {
                "schema": "material-review-evaluation/resolved-variants/v1",
                "baseline": asdict(baseline),
                "candidate": asdict(candidate),
            },
        )
        target = request.target_repository or request.benchmark.target_repository
        atomic_write_json(
            run_root / "private/request.json",
            {
                "schema": "material-review-evaluation/private-request/v1",
                "request_fingerprint": fingerprint,
                "repository_root": str(request.repository_root),
                "base_ref": request.base_ref,
                "candidate_ref": request.candidate_ref,
                "target_repository": str(target),
            },
        )
        run_schema_source = self._evaluation_root(request.benchmark) / "schemas/evaluation-run.schema.json"
        run_schema = self._read_json(run_schema_source, "evaluation run schema")
        atomic_write_json(run_root / "private/run-schema.json", run_schema)
        state: dict[str, Any] = {
            "schema": RUN_SCHEMA,
            "run_id": run_id,
            "request_fingerprint": fingerprint,
            "benchmark_id": request.benchmark.benchmark_id,
            "benchmark_hashes": dict(benchmark_hashes),
            "executor_configuration": self._executor_configuration(request),
            "resolved_skill_shas": {
                "baseline": baseline.commit_sha,
                "candidate": candidate.commit_sha,
            },
            "private_variant_map_sha256": sha256_file(private_map_path),
            "phase": "PREFLIGHT",
            "validated_predecessor_hashes": [],
            "trials": [],
            "infrastructure_attempts": [],
            "workspaces": [],
            "created_at": created_at,
            "updated_at": created_at,
            "terminal_reason": None,
            "judgment_sha256": None,
            "report_sha256": None,
        }
        self._write_run(run_root, state)
        return run_root

    def _drive(
        self,
        run_root: Path,
        request: EvaluationRequest,
    ) -> dict[str, Any]:
        while True:
            state = self._load_run(run_root)
            phase = str(state["phase"])
            if phase in TERMINAL_PHASES:
                return state
            if phase == "PREFLIGHT":
                state = self._prepare(run_root, request)
            elif phase == "PREPARED":
                state = self._transition(
                    run_root,
                    "PREPARED",
                    "INITIAL_TRIALS",
                    ("schedule.json", "state/preparation.json"),
                )
            elif phase == "INITIAL_TRIALS":
                state = self._initial_trials(run_root, request)
            elif phase == "CONSISTENCY_CHECK":
                state = self._consistency_check(run_root, request)
            elif phase == "OPTIONAL_THIRD_TRIAL":
                state = self._optional_third_trials(run_root, request)
            elif phase == "BLINDED_JUDGMENT":
                state = self._blinded_judgment(run_root, request)
            elif phase == "IDENTITY_REVEAL":
                state = self._transition(
                    run_root,
                    "IDENTITY_REVEAL",
                    "COMPLETE",
                    ("judge/judgment.json", "judge/reveal.json"),
                )
            else:
                raise EvaluationError(f"unsupported persisted evaluation phase: {phase}")

    def _prepare(
        self,
        run_root: Path,
        request: EvaluationRequest,
    ) -> dict[str, Any]:
        preparation_path = run_root / "state/preparation.json"
        if preparation_path.is_file():
            preparation = self._read_json(preparation_path, "preparation")
            if preparation.get("shared_materialization_failure") is True:
                return self._terminal(
                    run_root,
                    "PREFLIGHT",
                    "INCOMPLETE",
                    "shared workflow materialization failure prevents a fair comparison",
                )
            return self._transition(
                run_root,
                "PREFLIGHT",
                "PREPARED",
                (
                    "private/request.json",
                    "private/resolved-variants.json",
                    "private/variant-map.json",
                    "schedule.json",
                    "state/preparation.json",
                ),
            )

        private_map = self._private_map(run_root)
        resolved = self._resolved_variants(run_root)
        records: list[WorkspaceRecord] = []
        variants: dict[str, dict[str, Any]] = {}
        for anonymous_variant in ("A", "B"):
            identity = str(private_map[anonymous_variant])
            variant = resolved[identity]
            try:
                record = materialize_variant(
                    request.repository_root,
                    variant,
                    self.runs_root,
                    run_root.name,
                )
            except EvaluationError as error:
                evidence = (
                    run_root
                    / "variants"
                    / variant.commit_sha
                    / "evidence"
                    / "materialization.json"
                )
                evidence_hash = sha256_file(evidence) if evidence.is_file() else canonical_hash(
                    {"error_type": type(error).__name__}
                )
                blinded_failure = run_root / "trials" / anonymous_variant / "materialization-failure.json"
                blinded_failure.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_json(
                    blinded_failure,
                    {
                        "schema": "material-review-evaluation/workflow-failure/v1",
                        "anonymous_variant": anonymous_variant,
                        "evidence_kind": "workflow_failure",
                        "workflow_failure": {
                            "stage": "materialization",
                            "error_type": type(error).__name__,
                            "summary": "The anonymous workflow could not be materialized.",
                            "private_evidence_sha256": evidence_hash,
                        },
                        "evaluation_limitations": [
                            "No semantic trial could start for this anonymous workflow."
                        ],
                    },
                )
                variants[anonymous_variant] = {
                    "status": "materialization_failed",
                    "failure_artifact": blinded_failure.relative_to(run_root).as_posix(),
                    "failure_artifact_sha256": sha256_file(blinded_failure),
                }
            else:
                records.append(record)
                variants[anonymous_variant] = {
                    "status": "ready",
                    "workspace": _workspace_payload(record),
                }

        shared_failure = all(
            variants[label]["status"] == "materialization_failed"
            for label in ("A", "B")
        )
        mirror: WorkspaceRecord | None = None
        if not shared_failure:
            source = request.target_repository or request.benchmark
            mirror = prepare_target_mirror(source, self.runs_root, run_root.name)
            verify_benchmark_range(mirror.path, request.benchmark)
            records.append(mirror)

        wave_one = self.random_source.sample(["A1", "B1"], 2)
        wave_two = self.random_source.sample(["A2", "B2"], 2)
        if sorted(wave_one) != ["A1", "B1"] or sorted(wave_two) != ["A2", "B2"]:
            raise EvaluationError("paired trial randomization did not return exact permutations")
        atomic_write_json(
            run_root / "schedule.json",
            {
                "schema": "material-review-evaluation/trial-schedule/v1",
                "waves": [wave_one, wave_two],
                "persisted_before_trials": True,
                "created_at": _utc_now(),
            },
        )
        preparation = {
            "schema": "material-review-evaluation/preparation/v1",
            "variants": variants,
            "mirror": _workspace_payload(mirror) if mirror is not None else None,
            "shared_materialization_failure": shared_failure,
            "completed_at": _utc_now(),
        }
        atomic_write_json(preparation_path, preparation)
        self._save_workspace_records(run_root, records)

        scheduled_trials = []
        for anonymous_variant in ("A", "B"):
            for trial_number in (1, 2):
                failure = variants[anonymous_variant]["status"] != "ready"
                scheduled_trials.append(
                    {
                        "anonymous_variant": anonymous_variant,
                        "trial_number": trial_number,
                        "status": "failed" if failure else "pending",
                        "artifact_sha256": (
                            variants[anonymous_variant].get("failure_artifact_sha256")
                            if failure
                            else None
                        ),
                        "session_id": None,
                    }
                )

        def record_preparation(state: dict[str, Any]) -> None:
            state["trials"] = scheduled_trials
            for record in records:
                if record.kind == "variant-workflow":
                    self._add_public_workspace(state, record, "workflow")
                elif record.kind == "target-mirror":
                    self._add_public_workspace(state, record, "target")

        self._update_run(run_root, record_preparation)
        if shared_failure:
            return self._terminal(
                run_root,
                "PREFLIGHT",
                "INCOMPLETE",
                "shared workflow materialization failure prevents a fair comparison",
            )
        return self._transition(
            run_root,
            "PREFLIGHT",
            "PREPARED",
            (
                "private/request.json",
                "private/resolved-variants.json",
                "private/variant-map.json",
                "schedule.json",
                "state/preparation.json",
            ),
        )

    def _initial_trials(
        self,
        run_root: Path,
        request: EvaluationRequest,
    ) -> dict[str, Any]:
        schedule = self._read_json(run_root / "schedule.json", "trial schedule")
        preparation = self._read_json(run_root / "state/preparation.json", "preparation")
        for raw_wave in schedule["waves"]:
            labels = [
                str(label)
                for label in raw_wave
                if preparation["variants"][str(label)[0]]["status"] == "ready"
            ]
            terminal = self._run_wave(run_root, request, labels)
            if terminal is not None:
                return terminal
        required = ["schedule.json"]
        for trial in self._load_run(run_root)["trials"]:
            if trial["status"] == "complete":
                required.append(
                    f"trials/{trial['anonymous_variant']}/{trial['trial_number']}/normalized.json"
                )
        return self._transition(
            run_root,
            "INITIAL_TRIALS",
            "CONSISTENCY_CHECK",
            tuple(required),
        )

    def _run_wave(
        self,
        run_root: Path,
        request: EvaluationRequest,
        labels: Sequence[str],
    ) -> dict[str, Any] | None:
        if not labels:
            return None
        prepared = {
            label: self._prepare_attempt(run_root, request, label, self._next_attempt(run_root, label))
            for label in labels
            if not self._trial_complete(run_root, label)
        }
        if len(prepared) == 2:
            limitation = self._equivalent_environment_limitation(tuple(prepared.values()))
            if limitation is False:
                return self._terminal(
                    run_root,
                    str(self._load_run(run_root)["phase"]),
                    "INCOMPLETE",
                    "anonymous variants have unmatched environmental validation failures",
                )
            if isinstance(limitation, str):
                for attempt_path in prepared.values():
                    self._append_attempt_limitation(attempt_path, limitation)
        elif prepared:
            attempt_path = next(iter(prepared.values()))
            counterpart = next(
                (
                    self._latest_attempt_path(run_root, label)
                    for label in labels
                    if label not in prepared
                    and self._latest_attempt_path(run_root, label) is not None
                ),
                None,
            )
            if counterpart is None:
                only_label = next(iter(prepared))
                counterpart = self._latest_variant_attempt_path(
                    run_root,
                    "B" if only_label[0] == "A" else "A",
                )
            if counterpart is not None:
                limitation = self._equivalent_environment_limitation(
                    (attempt_path, counterpart)
                )
                if limitation is False:
                    return self._terminal(
                        run_root,
                        str(self._load_run(run_root)["phase"]),
                        "INCOMPLETE",
                        "resumed paired wave has unmatched environmental validation failures",
                    )
                if isinstance(limitation, str):
                    self._append_attempt_limitation(attempt_path, limitation)
            else:
                attempt = self._read_json(attempt_path, "trial attempt")
                if attempt["environment_failures"]:
                    self._append_attempt_limitation(
                        attempt_path,
                        "Environmental failures could not be paired because the other workflow failed materialization.",
                    )

        retry_labels: list[str] = []
        for label in labels:
            if self._trial_complete(run_root, label):
                continue
            attempt_path = prepared[label]
            result = self._advance_attempt(run_root, request, label, attempt_path)
            if result == "infrastructure_failure":
                retry_labels.append(label)
        for label in retry_labels:
            if self._attempt_count(run_root, label) > request.benchmark.infrastructure_retry_limit:
                self._mark_trial_failed(run_root, label)
                return self._terminal(
                    run_root,
                    str(self._load_run(run_root)["phase"]),
                    "INCOMPLETE",
                    f"repeated infrastructure failure exhausted the retry for {label}",
                )
            retry_path = self._prepare_attempt(
                run_root,
                request,
                label,
                self._next_attempt(run_root, label),
            )
            counterpart = next(
                (path for other, path in prepared.items() if other != label),
                None,
            )
            if counterpart is not None:
                limitation = self._equivalent_environment_limitation((retry_path, counterpart))
                if limitation is False:
                    return self._terminal(
                        run_root,
                        str(self._load_run(run_root)["phase"]),
                        "INCOMPLETE",
                        "infrastructure retry has unmatched environmental validation failures",
                    )
                if isinstance(limitation, str):
                    self._append_attempt_limitation(retry_path, limitation)
            retry_result = self._advance_attempt(run_root, request, label, retry_path)
            if retry_result == "infrastructure_failure":
                self._mark_trial_failed(run_root, label)
                return self._terminal(
                    run_root,
                    str(self._load_run(run_root)["phase"]),
                    "INCOMPLETE",
                    f"repeated infrastructure failure exhausted the retry for {label}",
                )
        return None

    def _prepare_attempt(
        self,
        run_root: Path,
        request: EvaluationRequest,
        label: str,
        attempt_number: int,
    ) -> Path:
        attempt_path = run_root / "attempts" / label / f"attempt-{attempt_number}.json"
        if attempt_path.is_file():
            return attempt_path
        attempt_path.parent.mkdir(parents=True, exist_ok=True)
        variant, trial_number = self._parse_label(label)
        preparation = self._read_json(run_root / "state/preparation.json", "preparation")
        mirror = _workspace_from_payload(preparation["mirror"])
        target = create_trial_target(
            mirror.path,
            request.benchmark,
            self.runs_root,
            run_root.name,
            f"{label}-attempt-{attempt_number}",
        )
        output_directory = run_root / "trials" / variant / str(trial_number) / f"attempt-{attempt_number}"
        output_directory.mkdir(parents=True, exist_ok=False)
        dependency_results = run_benchmark_commands(
            target,
            request.benchmark.dependency_installation_commands,
            output_directory / "environment/dependency-installation",
        )
        validation_results = run_benchmark_commands(
            target,
            request.benchmark.baseline_validation_commands,
            output_directory / "environment/baseline-validation",
        )
        environment_failures = self._environment_failures(
            output_directory,
            dependency_results,
            validation_results,
        )
        started_at = _utc_now()
        attempt = {
            "schema": "material-review-evaluation/trial-attempt/v1",
            "semantic_label": label,
            "anonymous_variant": variant,
            "trial_number": trial_number,
            "attempt_number": attempt_number,
            "status": "prepared",
            "started_at": started_at,
            "ended_at": None,
            "error": None,
            "target": _workspace_payload(target),
            "output_directory": str(output_directory),
            "environment": {
                "dependency_installation": [self._command_result(value) for value in dependency_results],
                "baseline_validation": [self._command_result(value) for value in validation_results],
            },
            "environment_failures": environment_failures,
            "limitations": [],
            "session_id": None,
            "sessions": [],
        }
        atomic_write_json(attempt_path, attempt)
        records = self._load_workspace_records(run_root)
        records.append(target)
        self._save_workspace_records(run_root, records)

        def record_attempt(state: dict[str, Any]) -> None:
            self._set_trial(state, variant, trial_number, status="running", session_id=None)
            state["infrastructure_attempts"].append(
                {
                    "semantic_label": label,
                    "attempt_number": attempt_number,
                    "status": "running",
                    "started_at": started_at,
                    "ended_at": None,
                    "error": None,
                }
            )
            self._add_public_workspace(state, target, "target")
            self._add_output_workspace(state, output_directory, label, attempt_number)

        self._update_run(run_root, record_attempt)
        return attempt_path

    def _environment_failures(
        self,
        output_directory: Path,
        dependency_results: Sequence[CommandResult],
        validation_results: Sequence[CommandResult],
    ) -> list[dict[str, Any]]:
        failures: list[dict[str, Any]] = []
        for stage, results, relative_root in (
            (
                "dependency_installation",
                dependency_results,
                output_directory / "environment/dependency-installation",
            ),
            (
                "baseline_validation",
                validation_results,
                output_directory / "environment/baseline-validation",
            ),
        ):
            for index, result in enumerate(results):
                if result.returncode == 0:
                    continue
                evidence_path = relative_root / f"command-{index:03d}.json"
                evidence = self._read_json(evidence_path, "command evidence")
                failures.append(
                    {
                        "stage": stage,
                        "command_index": index,
                        "returncode": result.returncode,
                        "normalized_failure_signature": evidence[
                            "normalized_failure_signature"
                        ],
                        "evidence": evidence_path.relative_to(output_directory).as_posix(),
                        "evidence_sha256": sha256_file(evidence_path),
                    }
                )
        return failures

    def _equivalent_environment_limitation(
        self,
        attempt_paths: Sequence[Path],
    ) -> str | bool | None:
        attempts = [self._read_json(path, "trial attempt") for path in attempt_paths]
        signatures = [
            [
                (
                    failure["stage"],
                    failure["command_index"],
                    failure["returncode"],
                    failure["normalized_failure_signature"],
                )
                for failure in attempt["environment_failures"]
            ]
            for attempt in attempts
        ]
        if all(not value for value in signatures):
            return None
        if all(value == signatures[0] for value in signatures[1:]):
            return (
                "Equivalent environmental command failures affected both anonymous variants; "
                "the comparison proceeds with this limitation."
            )
        return False

    def _append_attempt_limitation(self, attempt_path: Path, limitation: str) -> None:
        attempt = self._read_json(attempt_path, "trial attempt")
        if limitation not in attempt["limitations"]:
            attempt["limitations"].append(limitation)
            atomic_write_json(attempt_path, attempt)

    def _advance_attempt(
        self,
        run_root: Path,
        request: EvaluationRequest,
        label: str,
        attempt_path: Path,
    ) -> str:
        attempt = self._read_json(attempt_path, "trial attempt")
        variant, trial_number = self._parse_label(label)
        preparation = self._read_json(run_root / "state/preparation.json", "preparation")
        workflow = _workspace_from_payload(preparation["variants"][variant]["workspace"])
        target = _workspace_from_payload(attempt["target"])
        output_directory = Path(str(attempt["output_directory"]))
        request_path = output_directory / "trial-request.md"
        request_record = output_directory / "trial-request.record.json"
        configuration = self._executor_configuration(request)
        if not request_path.exists():
            build_trial_request(
                request_path,
                request_record,
                review_request_path=request.benchmark.root / "review-request.md",
                materialized_skill_path=workflow.path / "SKILL.md",
                target_path=target.path,
                artifact_root=output_directory,
                anonymous_trial_label=f"{variant}-{trial_number}",
                isolation_mode=request.isolation_mode,
                executor_configuration=configuration,
            )
        spec = SessionSpec(
            role="trial",
            working_directory=target.path,
            readable_workflow=workflow.path,
            output_directory=output_directory,
            prompt_path=request_path,
            output_schema=None,
            model=request.model,
            reasoning_effort=request.reasoning_effort,
            sandbox_mode=request.permission_profile,
            timeout_seconds=request.benchmark.default_timeout_seconds,
        )
        if attempt["status"] == "prepared":
            result = self.executor.start(spec)
            self._record_session(attempt, "start", result)
            if result.status != "complete" or result.failure is not None:
                self._record_infrastructure_failure(run_root, attempt_path, attempt, result)
                return "infrastructure_failure"
            if result.session_id is None:
                raise EvaluationError("successful trial start did not return a session ID")
            attempt["session_id"] = result.session_id
            attempt["status"] = "waiting_gate_a"
            atomic_write_json(attempt_path, attempt)

            def waiting_gate_a(state: dict[str, Any]) -> None:
                self._set_trial(
                    state,
                    variant,
                    trial_number,
                    status="waiting_gate_a",
                    session_id=result.session_id,
                )

            self._update_run(run_root, waiting_gate_a)

        attempt = self._read_json(attempt_path, "trial attempt")
        native_run = find_native_run(output_directory)
        controller_path = workflow.path / "scripts/reviewctl.py"
        if attempt["status"] == "waiting_gate_a":
            artifacts = validate_gate_a_artifacts(native_run, controller_path, target)
            phase = str(artifacts.state["phase"])
            if phase == "ADJUDICATED":
                command = gate_a_command(artifacts)
                expected = (
                    GATE_A_FINDINGS_STATEMENT
                    if command.approved_ids
                    else GATE_A_EMPTY_STATEMENT
                )
                if command.argv[-1] != expected:
                    raise EvaluationError("Gate A command did not contain the exact auto statement")
                result = self.executor.resume(str(attempt["session_id"]), expected, spec)
                self._record_session(attempt, "gate_a", result)
                if result.status != "complete" or result.failure is not None:
                    self._record_infrastructure_failure(run_root, attempt_path, attempt, result)
                    return "infrastructure_failure"
                atomic_write_json(attempt_path, attempt)
                artifacts = validate_gate_a_artifacts(native_run, controller_path, target)
                phase = str(artifacts.state["phase"])
            if phase == "COMPLETE":
                return self._complete_attempt(
                    run_root,
                    attempt_path,
                    attempt,
                    artifacts,
                    variant,
                    trial_number,
                )
            if phase != "PLAN_VALIDATED":
                raise EvaluationError(f"trial did not stop at Gate A or Gate B: {phase}")
            attempt["status"] = "waiting_gate_b"
            atomic_write_json(attempt_path, attempt)

            def waiting_gate_b(state: dict[str, Any]) -> None:
                self._set_trial(
                    state,
                    variant,
                    trial_number,
                    status="waiting_gate_b",
                    session_id=str(attempt["session_id"]),
                )

            self._update_run(run_root, waiting_gate_b)

        attempt = self._read_json(attempt_path, "trial attempt")
        if attempt["status"] == "waiting_gate_b":
            artifacts = validate_gate_b_artifacts(native_run, controller_path, target)
            phase = str(artifacts.state["phase"])
            if phase == "PLAN_VALIDATED":
                command = gate_b_command(artifacts)
                if command.argv[-1] != GATE_B_STATEMENT:
                    raise EvaluationError("Gate B command did not contain the exact auto statement")
                result = self.executor.resume(
                    str(attempt["session_id"]),
                    GATE_B_STATEMENT,
                    spec,
                )
                self._record_session(attempt, "gate_b", result)
                if result.status != "complete" or result.failure is not None:
                    self._record_infrastructure_failure(run_root, attempt_path, attempt, result)
                    return "infrastructure_failure"
                atomic_write_json(attempt_path, attempt)
                artifacts = validate_gate_b_artifacts(native_run, controller_path, target)
                phase = str(artifacts.state["phase"])
            if phase != "PLAN_APPROVED":
                raise EvaluationError(f"trial did not stop at PLAN_APPROVED: {phase}")
            return self._complete_attempt(
                run_root,
                attempt_path,
                attempt,
                artifacts,
                variant,
                trial_number,
            )
        if attempt["status"] == "complete":
            return "complete"
        if attempt["status"] == "infrastructure_failure":
            return "infrastructure_failure"
        raise EvaluationError(f"unsupported trial attempt status: {attempt['status']}")

    def _complete_attempt(
        self,
        run_root: Path,
        attempt_path: Path,
        attempt: dict[str, Any],
        artifacts: NativeTrialArtifacts,
        variant: str,
        trial_number: int,
    ) -> str:
        normalized = normalize_trial_evidence(
            artifacts,
            turn_metadata={
                "session_invocations": len(attempt["sessions"]),
            },
            tool_metadata={
                "tool_events": sum(
                    len(session.get("tool_events", []))
                    for session in attempt["sessions"]
                )
            },
        )
        normalized["anonymous_variant"] = variant
        normalized["trial_number"] = trial_number
        normalized["evaluation_limitations"] = list(attempt["limitations"])
        normalized["evaluation_environment"] = {
            "failure_count": len(attempt["environment_failures"]),
            "failures": [
                {
                    "stage": failure["stage"],
                    "command_index": failure["command_index"],
                    "returncode": failure["returncode"],
                    "normalized_failure_signature": failure[
                        "normalized_failure_signature"
                    ],
                    "evidence_sha256": failure["evidence_sha256"],
                }
                for failure in attempt["environment_failures"]
            ],
        }
        if "head" in normalized.get("cleanliness_attestation", {}):
            normalized["cleanliness_attestation"]["head"] = "<comparison>"
        normalized_path = run_root / "trials" / variant / str(trial_number) / "normalized.json"
        atomic_write_json(normalized_path, normalized)
        output_directory = Path(str(attempt["output_directory"]))
        atomic_write_json(
            output_directory / "validation.json",
            {
                "schema": "material-review-evaluation/trial-validation/v1",
                "native_phase": artifacts.state["phase"],
                "normalized_sha256": sha256_file(normalized_path),
            },
        )
        atomic_write_json(
            output_directory / "target-cleanliness.json",
            dict(artifacts.cleanliness_attestation),
        )
        atomic_write_json(
            output_directory / "no-repair-attestation.json",
            {
                "schema": "material-review-evaluation/no-repair-attestation/v1",
                "native_phase": artifacts.state["phase"],
                "repair_entered": False,
            },
        )
        atomic_write_json(
            output_directory / "limitations.json",
            {"limitations": list(attempt["limitations"])},
        )
        attempt["status"] = "complete"
        attempt["ended_at"] = _utc_now()
        attempt["normalized_artifact"] = normalized_path.relative_to(run_root).as_posix()
        attempt["normalized_artifact_sha256"] = sha256_file(normalized_path)
        atomic_write_json(attempt_path, attempt)

        def complete(state: dict[str, Any]) -> None:
            self._set_trial(
                state,
                variant,
                trial_number,
                status="complete",
                session_id=str(attempt["session_id"]),
                artifact_sha256=attempt["normalized_artifact_sha256"],
            )
            self._set_attempt_summary(
                state,
                str(attempt["semantic_label"]),
                int(attempt["attempt_number"]),
                status="complete",
                ended_at=str(attempt["ended_at"]),
                error=None,
            )

        self._update_run(run_root, complete)
        return "complete"

    def _record_session(
        self,
        attempt: dict[str, Any],
        stage: str,
        result: SessionResult,
    ) -> None:
        session = {
            "stage": stage,
            "session_id": result.session_id,
            "status": result.status,
            "usage": dict(result.usage),
            "tool_events": [dict(event) for event in result.tool_events],
            "stdout_path": str(result.stdout_path),
            "stdout_sha256": (
                sha256_file(result.stdout_path) if result.stdout_path.is_file() else None
            ),
            "stderr_path": str(result.stderr_path),
            "stderr_sha256": (
                sha256_file(result.stderr_path) if result.stderr_path.is_file() else None
            ),
            "failure": (
                {
                    "kind": result.failure.kind,
                    "message": result.failure.message,
                    "returncode": result.failure.returncode,
                }
                if result.failure is not None
                else None
            ),
            "recorded_at": _utc_now(),
        }
        attempt["sessions"].append(session)

    def _record_infrastructure_failure(
        self,
        run_root: Path,
        attempt_path: Path,
        attempt: dict[str, Any],
        result: SessionResult,
    ) -> None:
        if result.failure is None:
            raise EvaluationError("failed executor result lacks a typed infrastructure failure")
        attempt["status"] = "infrastructure_failure"
        attempt["ended_at"] = _utc_now()
        attempt["error"] = f"{result.failure.kind}: {result.failure.message}"
        atomic_write_json(attempt_path, attempt)

        def failed(state: dict[str, Any]) -> None:
            self._set_attempt_summary(
                state,
                str(attempt["semantic_label"]),
                int(attempt["attempt_number"]),
                status="infrastructure_failure",
                ended_at=str(attempt["ended_at"]),
                error=str(attempt["error"]),
            )

        self._update_run(run_root, failed)

    def _consistency_check(
        self,
        run_root: Path,
        request: EvaluationRequest,
    ) -> dict[str, Any]:
        consistency_path = run_root / "state/consistency.json"
        if not consistency_path.is_file():
            needs_third: list[str] = []
            agreements: dict[str, dict[str, Any]] = {}
            for variant in ("A", "B"):
                sources = self._variant_evidence(run_root, variant)
                agreement_path = self._ensure_agreement(
                    run_root,
                    request,
                    variant,
                    sources,
                    "after-2",
                )
                agreement = self._read_json(agreement_path, "agreement")
                agreements[variant] = {
                    "path": agreement_path.relative_to(run_root).as_posix(),
                    "sha256": sha256_file(agreement_path),
                }
                if agreement["classification"] == "insufficient_evidence":
                    if agreement["reason_category"] == "infrastructure_failure":
                        if not self._materialization_failed(run_root, variant):
                            return self._terminal(
                                run_root,
                                "CONSISTENCY_CHECK",
                                "INCOMPLETE",
                                f"agreement evidence for Variant {variant} is insufficient because of infrastructure failure",
                            )
                    if agreement["reason_category"] == "trial_variability":
                        needs_third.append(variant)
                elif agreement["classification"] == "materially_different":
                    needs_third.append(variant)
            atomic_write_json(
                consistency_path,
                {
                    "schema": "material-review-evaluation/consistency/v1",
                    "agreements": agreements,
                    "needs_third_trial": needs_third,
                    "completed_at": _utc_now(),
                },
            )
        return self._transition(
            run_root,
            "CONSISTENCY_CHECK",
            "OPTIONAL_THIRD_TRIAL",
            ("state/consistency.json",),
        )

    def _optional_third_trials(
        self,
        run_root: Path,
        request: EvaluationRequest,
    ) -> dict[str, Any]:
        completion_path = run_root / "state/optional-third.json"
        if completion_path.is_file():
            required = [
                "state/optional-third.json",
                "variant-a/agreement.json",
                "variant-b/agreement.json",
                "variant-a/stability.json",
                "variant-b/stability.json",
            ]
            return self._transition(
                run_root,
                "OPTIONAL_THIRD_TRIAL",
                "BLINDED_JUDGMENT",
                tuple(required),
            )
        consistency = self._read_json(run_root / "state/consistency.json", "consistency")
        variants = [str(value) for value in consistency["needs_third_trial"]]
        labels = [f"{variant}3" for variant in variants]
        randomized = self.random_source.sample(labels, len(labels)) if labels else []
        if sorted(randomized) != sorted(labels):
            raise EvaluationError("third-trial randomization did not return an exact permutation")
        atomic_write_json(
            run_root / "third-schedule.json",
            {
                "schema": "material-review-evaluation/third-schedule/v1",
                "labels": randomized,
                "created_at": _utc_now(),
            },
        )
        if labels:
            def add_third_records(state: dict[str, Any]) -> None:
                existing = {
                    (record["anonymous_variant"], record["trial_number"])
                    for record in state["trials"]
                }
                for variant in variants:
                    if (variant, 3) not in existing:
                        state["trials"].append(
                            {
                                "anonymous_variant": variant,
                                "trial_number": 3,
                                "status": "pending",
                                "artifact_sha256": None,
                                "session_id": None,
                            }
                        )

            self._update_run(run_root, add_third_records)
            terminal = self._run_wave(run_root, request, randomized)
            if terminal is not None:
                return terminal
        final_agreements: dict[str, dict[str, Any]] = {}
        for variant in ("A", "B"):
            initial_record = consistency["agreements"][variant]
            initial_path = run_root / str(initial_record["path"])
            history = [
                {
                    "path": initial_path.relative_to(run_root).as_posix(),
                    "sha256": sha256_file(initial_path),
                }
            ]
            if variant in variants:
                final_source = self._ensure_agreement(
                    run_root,
                    request,
                    variant,
                    self._variant_evidence(run_root, variant),
                    "after-3",
                )
                history.append(
                    {
                        "path": final_source.relative_to(run_root).as_posix(),
                        "sha256": sha256_file(final_source),
                    }
                )
            else:
                final_source = initial_path
            agreement = self._read_json(final_source, "final agreement")
            if (
                agreement["classification"] == "insufficient_evidence"
                and agreement["reason_category"] == "infrastructure_failure"
                and not self._materialization_failed(run_root, variant)
            ):
                return self._terminal(
                    run_root,
                    "OPTIONAL_THIRD_TRIAL",
                    "INCOMPLETE",
                    f"agreement evidence for Variant {variant} remains infrastructure-insufficient",
                )
            unstable = variant in variants and (
                agreement["classification"] == "materially_different"
                or (
                    agreement["classification"] == "insufficient_evidence"
                    and agreement["reason_category"] == "trial_variability"
                )
            )
            variant_root = run_root / f"variant-{variant.lower()}"
            atomic_write_json(variant_root / "agreement.json", agreement)
            atomic_write_json(
                variant_root / "stability.json",
                {
                    "schema": "material-review-evaluation/stability/v1",
                    "anonymous_variant": variant,
                    "third_trial_required": variant in variants,
                    "unstable": unstable,
                    "outlier_trials": list(agreement["outlier_trials"]),
                    "agreement_history": history,
                },
            )
            final_agreements[variant] = {
                "sha256": sha256_file(variant_root / "agreement.json"),
                "unstable": unstable,
            }
        atomic_write_json(
            completion_path,
            {
                "schema": "material-review-evaluation/optional-third/v1",
                "third_trial_labels": randomized,
                "final_agreements": final_agreements,
                "completed_at": _utc_now(),
            },
        )
        return self._transition(
            run_root,
            "OPTIONAL_THIRD_TRIAL",
            "BLINDED_JUDGMENT",
            (
                "state/optional-third.json",
                "third-schedule.json",
                "variant-a/agreement.json",
                "variant-b/agreement.json",
                "variant-a/stability.json",
                "variant-b/stability.json",
            ),
        )

    def _ensure_agreement(
        self,
        run_root: Path,
        request: EvaluationRequest,
        variant: str,
        sources: Sequence[Path],
        suffix: str,
    ) -> Path:
        output_path = run_root / f"variant-{variant.lower()}" / "agreements" / f"{suffix}.json"
        if output_path.is_file():
            self._validate_output_file(
                output_path,
                self._evaluation_root(request.benchmark) / "schemas/agreement.schema.json",
            )
            return output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        bundle = run_root / f"variant-{variant.lower()}" / f"agreement-bundle-{suffix}"
        private_tokens = self._private_tokens(run_root)
        if not bundle.exists():
            build_agreement_bundle(
                bundle,
                anonymous_variant=variant,
                normalized_trials=sources,
                prompt_path=self._evaluation_root(request.benchmark) / "prompts/trial-agreement.md",
                schema_path=self._evaluation_root(request.benchmark) / "schemas/agreement.schema.json",
                path_prefixes=self._path_prefixes(run_root, request),
                private_tokens=private_tokens,
            )
        scan_blinded_bundle(bundle, private_tokens)
        session_output = run_root / "judge" / "sessions" / f"agreement-{variant}-{suffix}"
        session_output.mkdir(parents=True, exist_ok=True)
        spec = SessionSpec(
            role="agreement",
            working_directory=bundle,
            readable_workflow=None,
            output_directory=session_output,
            prompt_path=bundle / "prompt.md",
            output_schema=bundle / "output.schema.json",
            model=request.model,
            reasoning_effort=request.reasoning_effort,
            sandbox_mode="read-only",
            timeout_seconds=request.benchmark.default_timeout_seconds,
        )
        result = self._fresh_judge_result(run_root, f"agreement-{variant}-{suffix}", spec)
        if result.final_output is None:
            raise EvaluationError("agreement executor did not return a final output")
        self._validate_output_text(result.final_output, spec.output_schema)
        value = json.loads(result.final_output)
        if value.get("anonymous_variant") != variant:
            raise EvaluationError("agreement output belongs to a different anonymous variant")
        atomic_write_json(output_path, value)
        return output_path

    def _blinded_judgment(
        self,
        run_root: Path,
        request: EvaluationRequest,
    ) -> dict[str, Any]:
        judgment_path = run_root / "judge/judgment.json"
        reveal_path = run_root / "judge/reveal.json"
        private_tokens = self._private_tokens(run_root)
        bundle = run_root / "judge/comparison-bundle"
        if not bundle.exists():
            build_comparison_bundle(
                bundle,
                variant_a_trials=self._variant_evidence(run_root, "A"),
                variant_b_trials=self._variant_evidence(run_root, "B"),
                agreement_a=run_root / "variant-a/agreement.json",
                agreement_b=run_root / "variant-b/agreement.json",
                rubric_path=self._evaluation_root(request.benchmark) / "judge-rubric.md",
                oracle_path=request.benchmark.root / "judge-oracle.json",
                prompt_path=self._evaluation_root(request.benchmark) / "prompts/comparison-judge.md",
                schema_path=self._evaluation_root(request.benchmark) / "schemas/judgment.schema.json",
                path_prefixes=self._path_prefixes(run_root, request),
                private_tokens=private_tokens,
            )
        scan_blinded_bundle(bundle, private_tokens)
        state = self._load_run(run_root)
        if not judgment_path.is_file():
            output_directory = run_root / "judge/sessions/comparison"
            output_directory.mkdir(parents=True, exist_ok=True)
            spec = SessionSpec(
                role="judge",
                working_directory=bundle,
                readable_workflow=None,
                output_directory=output_directory,
                prompt_path=bundle / "prompt.md",
                output_schema=bundle / "output.schema.json",
                model=request.model,
                reasoning_effort=request.reasoning_effort,
                sandbox_mode="read-only",
                timeout_seconds=request.benchmark.default_timeout_seconds,
            )
            result = self._fresh_judge_result(run_root, "comparison", spec)
            if result.final_output is None:
                raise EvaluationError("comparison judge did not return a final output")
            self._validate_output_text(result.final_output, spec.output_schema)
            judgment = json.loads(result.final_output)
            judgment["locked_at"] = _utc_now()
            atomic_write_json(judgment_path, judgment)
        judgment_hash = sha256_file(judgment_path)
        locked_judgment = self._read_json(judgment_path, "locked judgment")
        if "locked_at" not in locked_judgment:
            raise EvaluationError("locked judgment does not contain its lock timestamp")
        locked_at = _require_text(locked_judgment.pop("locked_at", None), "judgment lock timestamp")
        self._validate_output_text(
            json.dumps(locked_judgment),
            self._evaluation_root(request.benchmark) / "schemas/judgment.schema.json",
        )
        if state["judgment_sha256"] is None:
            self._update_run(
                run_root,
                lambda value: value.__setitem__("judgment_sha256", judgment_hash),
            )
        elif state["judgment_sha256"] != judgment_hash:
            raise EvaluationError("locked judgment hash does not match run state")

        if not reveal_path.is_file():
            persisted = self._load_run(run_root)
            if persisted["judgment_sha256"] != judgment_hash:
                raise EvaluationError("judgment hash was not persisted before identity reveal")
            private_map_path = run_root / "private/variant-map.json"
            if sha256_file(private_map_path) != persisted["private_variant_map_sha256"]:
                raise EvaluationError("private variant map hash changed before reveal")
            private_map = self._read_json(private_map_path, "private variant map")
            judgment = self._read_json(judgment_path, "locked judgment")
            atomic_write_json(
                reveal_path,
                {
                    "schema": "material-review-evaluation/reveal/v1",
                    "variant_map": private_map["variants"],
                    "judgment_sha256": judgment_hash,
                    "revealed_at": _utc_after(locked_at),
                },
            )
        reveal = self._read_json(reveal_path, "identity reveal")
        if set(reveal) != {
            "schema",
            "variant_map",
            "judgment_sha256",
            "revealed_at",
        }:
            raise EvaluationError("identity reveal fields do not match the locked contract")
        if (
            reveal["schema"] != "material-review-evaluation/reveal/v1"
            or reveal["variant_map"] != self._private_map(run_root)
            or reveal["judgment_sha256"] != judgment_hash
            or _require_text(reveal["revealed_at"], "reveal timestamp") <= locked_at
        ):
            raise EvaluationError("identity reveal does not match the locked judgment and map")
        return self._transition(
            run_root,
            "BLINDED_JUDGMENT",
            "IDENTITY_REVEAL",
            (
                "judge/comparison-bundle/bundle.json",
                "judge/judgment.json",
                "judge/reveal.json",
                "private/variant-map.json",
            ),
        )

    def _fresh_judge_result(
        self,
        run_root: Path,
        semantic_label: str,
        spec: SessionSpec,
    ) -> SessionResult:
        for attempt_number in (1, 2):
            result = self.executor.start(spec)
            record_path = run_root / "judge/attempts" / semantic_label / f"attempt-{attempt_number}.json"
            record = {
                "schema": "material-review-evaluation/judge-attempt/v1",
                "semantic_label": semantic_label,
                "attempt_number": attempt_number,
                "status": result.status,
                "session_id": result.session_id,
                "stdout_path": str(result.stdout_path),
                "stdout_sha256": sha256_file(result.stdout_path) if result.stdout_path.is_file() else None,
                "stderr_path": str(result.stderr_path),
                "stderr_sha256": sha256_file(result.stderr_path) if result.stderr_path.is_file() else None,
                "failure": (
                    {
                        "kind": result.failure.kind,
                        "message": result.failure.message,
                        "returncode": result.failure.returncode,
                    }
                    if result.failure is not None
                    else None
                ),
                "recorded_at": _utc_now(),
            }
            record_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(record_path, record)
            if result.status == "complete" and result.failure is None:
                return result
            if result.failure is None:
                raise EvaluationError("failed judge result lacks a typed infrastructure failure")
        raise EvaluationError(f"repeated infrastructure failure for {semantic_label}")

    def _variant_evidence(self, run_root: Path, variant: str) -> tuple[Path, ...]:
        state = self._load_run(run_root)
        completed = sorted(
            (
                int(record["trial_number"]),
                run_root
                / "trials"
                / variant
                / str(record["trial_number"])
                / "normalized.json",
            )
            for record in state["trials"]
            if record["anonymous_variant"] == variant and record["status"] == "complete"
        )
        if completed:
            return tuple(path for _, path in completed)
        preparation = self._read_json(run_root / "state/preparation.json", "preparation")
        failure = preparation["variants"][variant].get("failure_artifact")
        if failure is None:
            raise EvaluationError(f"Variant {variant} has no comparable trial evidence")
        return (run_root / str(failure),)

    def _materialization_failed(self, run_root: Path, variant: str) -> bool:
        preparation = self._read_json(run_root / "state/preparation.json", "preparation")
        return preparation["variants"][variant]["status"] == "materialization_failed"

    def _private_map(self, run_root: Path) -> dict[str, str]:
        state = self._load_run(run_root)
        path = run_root / "private/variant-map.json"
        if sha256_file(path) != state["private_variant_map_sha256"]:
            raise EvaluationError("private variant map hash does not match run state")
        value = self._read_json(path, "private variant map")
        variants = value.get("variants")
        if not isinstance(variants, dict) or sorted(variants.values()) != ["baseline", "candidate"]:
            raise EvaluationError("private variant map is malformed")
        return {"A": str(variants["A"]), "B": str(variants["B"])}

    def _resolved_variants(self, run_root: Path) -> dict[str, ResolvedVariant]:
        value = self._read_json(run_root / "private/resolved-variants.json", "resolved variants")
        result: dict[str, ResolvedVariant] = {}
        for identity in ("baseline", "candidate"):
            record = value[identity]
            result[identity] = ResolvedVariant(
                supplied_ref=str(record["supplied_ref"]),
                commit_sha=str(record["commit_sha"]),
                commit_subject_sha256=str(record["commit_subject_sha256"]),
            )
        return result

    def _private_tokens(self, run_root: Path) -> tuple[str, ...]:
        resolved = self._resolved_variants(run_root)
        tokens: list[str] = []
        for variant in resolved.values():
            tokens.extend(
                (
                    variant.supplied_ref,
                    variant.commit_sha,
                    variant.commit_subject_sha256,
                )
            )
        return tuple(tokens)

    def _path_prefixes(
        self,
        run_root: Path,
        request: EvaluationRequest,
    ) -> dict[Path, str]:
        prefixes = {
            run_root: "<run>",
            self.runs_root: "<runs>",
            request.repository_root: "<repository>",
        }
        if isinstance(request.target_repository, Path):
            prefixes[request.target_repository] = "<target>"
        return prefixes

    def _evaluation_root(self, benchmark: Benchmark) -> Path:
        return benchmark.root.parents[1]

    def _read_json(self, path: Path, context: str) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise EvaluationError(f"{context} is missing or symlinked")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise EvaluationError(f"{context} is unreadable") from error
        if not isinstance(value, dict):
            raise EvaluationError(f"{context} must be a JSON object")
        return value

    def _run_root(self, run_id: str) -> Path:
        identifier = safe_relative_path(_require_text(run_id, "run ID"), "run ID")
        if len(identifier.parts) != 1 or identifier.as_posix() in {".", ".."}:
            raise EvaluationError("run ID must be one safe path component")
        run_root = self.runs_root / identifier.as_posix()
        if run_root.is_symlink() or not run_root.is_dir():
            raise EvaluationError("evaluation run does not exist")
        return run_root

    def _load_run(self, run_root: Path) -> dict[str, Any]:
        state = self._read_json(run_root / "run.json", "evaluation run")
        self._validate_output_text(
            json.dumps(state),
            self._run_schema_path(run_root),
        )
        if state["run_id"] != run_root.name:
            raise EvaluationError("run ID does not match its directory")
        self._verify_predecessor_hashes(run_root, state)
        return state

    def _run_schema_path(self, run_root: Path) -> Path:
        repository_assets = run_root / "private/run-schema.json"
        if repository_assets.is_file():
            return repository_assets
        raise EvaluationError("run schema snapshot is missing")

    def _validate_output_text(self, text: str, schema_path: Path | None) -> None:
        if schema_path is None:
            raise EvaluationError("output schema path is missing")
        try:
            _validate_final_output(text, schema_path)
        except ValueError as error:
            raise EvaluationError("JSON output does not conform to its schema") from error

    def _validate_output_file(self, path: Path, schema_path: Path) -> None:
        self._validate_output_text(path.read_text(encoding="utf-8"), schema_path)

    def _write_run(self, run_root: Path, state: dict[str, Any]) -> None:
        schema_snapshot = run_root / "private/run-schema.json"
        if not schema_snapshot.exists():
            raise EvaluationError("run schema snapshot must exist before run state")
        self._validate_output_text(json.dumps(state), schema_snapshot)
        atomic_write_json(run_root / "run.json", state)

    def _verify_predecessor_hashes(
        self,
        run_root: Path,
        state: Mapping[str, Any],
    ) -> None:
        for record in state["validated_predecessor_hashes"]:
            relative = safe_relative_path(record["artifact"], "predecessor artifact")
            path = run_root.joinpath(*relative.parts)
            if path.is_symlink() or not path.is_file():
                raise EvaluationError(f"validated predecessor artifact is missing: {relative}")
            if sha256_file(path) != record["sha256"]:
                raise EvaluationError(f"validated predecessor artifact changed: {relative}")

    def _update_run(self, run_root: Path, mutate: object) -> dict[str, Any]:
        state = self._load_run(run_root)
        original_phase = state["phase"]
        updated = copy.deepcopy(state)
        mutate(updated)  # type: ignore[operator]
        if updated["phase"] != original_phase:
            raise EvaluationError("ordinary run updates cannot change lifecycle phase")
        updated["updated_at"] = _utc_after(str(state["updated_at"]))
        self._write_run(run_root, updated)
        return updated

    def _transition(
        self,
        run_root: Path,
        expected_phase: str,
        next_phase: str,
        required_artifacts: Sequence[str],
        *,
        terminal_reason: str | None = None,
    ) -> dict[str, Any]:
        state = self._load_run(run_root)
        if state["phase"] != expected_phase:
            raise EvaluationError(
                f"phase transition requires {expected_phase}; current phase is {state['phase']}"
            )
        if next_phase not in (*PHASES, "INCOMPLETE", "ABORTED"):
            raise EvaluationError(f"unsupported evaluation phase transition: {next_phase}")
        if next_phase not in {"INCOMPLETE", "ABORTED"}:
            expected_index = PHASES.index(expected_phase) + 1
            if expected_index >= len(PHASES) or PHASES[expected_index] != next_phase:
                raise EvaluationError(
                    f"non-sequential phase transition {expected_phase} -> {next_phase}"
                )
        predecessor_records = list(state["validated_predecessor_hashes"])
        checkpoint = (
            run_root
            / "state"
            / "checkpoints"
            / f"{len(predecessor_records):03d}-{expected_phase}.json"
        )
        atomic_write_json(checkpoint, state)
        additions = [checkpoint.relative_to(run_root).as_posix(), *required_artifacts]
        known = {record["artifact"]: record["sha256"] for record in predecessor_records}
        for relative_value in additions:
            relative = safe_relative_path(relative_value, "transition artifact")
            path = run_root.joinpath(*relative.parts)
            if path.is_symlink() or not path.is_file():
                raise EvaluationError(f"phase predecessor artifact is missing: {relative}")
            digest = sha256_file(path)
            existing = known.get(relative.as_posix())
            if existing is not None and existing != digest:
                raise EvaluationError(f"phase predecessor artifact changed: {relative}")
            if existing is None:
                predecessor_records.append(
                    {"artifact": relative.as_posix(), "sha256": digest}
                )
                known[relative.as_posix()] = digest
        updated = copy.deepcopy(state)
        updated["phase"] = next_phase
        updated["validated_predecessor_hashes"] = predecessor_records
        updated["terminal_reason"] = terminal_reason
        updated["updated_at"] = _utc_after(str(state["updated_at"]))
        self._write_run(run_root, updated)
        return updated

    def _terminal(
        self,
        run_root: Path,
        expected_phase: str,
        terminal_phase: str,
        reason: str,
    ) -> dict[str, Any]:
        if terminal_phase not in {"INCOMPLETE", "ABORTED"}:
            raise EvaluationError("invalid non-complete terminal phase")
        return self._transition(
            run_root,
            expected_phase,
            terminal_phase,
            (),
            terminal_reason=_require_text(reason, "terminal reason"),
        )

    def _summary(self, run_root: Path, state: Mapping[str, Any]) -> RunSummary:
        counts = {
            variant: sum(
                1
                for trial in state["trials"]
                if trial["anonymous_variant"] == variant and trial["status"] == "complete"
            )
            for variant in ("A", "B")
        }
        return RunSummary(
            run_id=str(state["run_id"]),
            run_root=run_root,
            phase=str(state["phase"]),
            terminal_reason=(
                str(state["terminal_reason"])
                if state["terminal_reason"] is not None
                else None
            ),
            semantic_trial_counts=MappingProxyType(counts),
            judgment_sha256=(
                str(state["judgment_sha256"])
                if state["judgment_sha256"] is not None
                else None
            ),
        )

    def _save_workspace_records(
        self,
        run_root: Path,
        records: Sequence[WorkspaceRecord],
    ) -> None:
        unique: dict[str, WorkspaceRecord] = {}
        for record in records:
            unique[str(record.path)] = record
        atomic_write_json(
            run_root / "state/workspaces.json",
            {
                "schema": "material-review-evaluation/workspaces/v1",
                "records": [_workspace_payload(record) for record in unique.values()],
            },
        )

    def _load_workspace_records(self, run_root: Path) -> list[WorkspaceRecord]:
        path = run_root / "state/workspaces.json"
        if not path.is_file():
            return []
        value = self._read_json(path, "workspace records")
        return [_workspace_from_payload(record) for record in value["records"]]

    def _add_public_workspace(
        self,
        state: dict[str, Any],
        record: WorkspaceRecord,
        kind: str,
    ) -> None:
        path = str(record.path)
        if any(value["path"] == path for value in state["workspaces"]):
            return
        state["workspaces"].append(
            {
                "workspace_id": canonical_hash(
                    {"owner": record.owner_run_id, "path": path}
                ),
                "kind": kind,
                "path": path,
                "owned": True,
                "cleaned": False,
            }
        )

    def _add_output_workspace(
        self,
        state: dict[str, Any],
        output: Path,
        label: str,
        attempt_number: int,
    ) -> None:
        path = str(output)
        if any(value["path"] == path for value in state["workspaces"]):
            return
        state["workspaces"].append(
            {
                "workspace_id": f"{label}-output-{attempt_number}",
                "kind": "trial_output",
                "path": path,
                "owned": True,
                "cleaned": False,
            }
        )

    def _set_trial(
        self,
        state: dict[str, Any],
        variant: str,
        trial_number: int,
        *,
        status: str,
        session_id: str | None,
        artifact_sha256: str | None = None,
    ) -> None:
        matches = [
            record
            for record in state["trials"]
            if record["anonymous_variant"] == variant
            and record["trial_number"] == trial_number
        ]
        if len(matches) != 1:
            raise EvaluationError("trial schedule does not contain one exact semantic trial")
        matches[0]["status"] = status
        matches[0]["session_id"] = session_id
        if artifact_sha256 is not None:
            matches[0]["artifact_sha256"] = artifact_sha256

    def _set_attempt_summary(
        self,
        state: dict[str, Any],
        label: str,
        attempt_number: int,
        *,
        status: str,
        ended_at: str,
        error: str | None,
    ) -> None:
        matches = [
            record
            for record in state["infrastructure_attempts"]
            if record["semantic_label"] == label
            and record["attempt_number"] == attempt_number
        ]
        if len(matches) != 1:
            raise EvaluationError("run state does not contain one exact attempt")
        matches[0]["status"] = status
        matches[0]["ended_at"] = ended_at
        matches[0]["error"] = error

    def _mark_trial_failed(self, run_root: Path, label: str) -> None:
        variant, trial_number = self._parse_label(label)
        self._update_run(
            run_root,
            lambda state: self._set_trial(
                state,
                variant,
                trial_number,
                status="failed",
                session_id=None,
            ),
        )

    def _trial_complete(self, run_root: Path, label: str) -> bool:
        variant, trial_number = self._parse_label(label)
        state = self._load_run(run_root)
        return any(
            record["anonymous_variant"] == variant
            and record["trial_number"] == trial_number
            and record["status"] == "complete"
            for record in state["trials"]
        )

    def _attempt_count(self, run_root: Path, label: str) -> int:
        directory = run_root / "attempts" / label
        return len(tuple(directory.glob("attempt-*.json"))) if directory.is_dir() else 0

    def _latest_attempt_path(self, run_root: Path, label: str) -> Path | None:
        attempts = sorted((run_root / "attempts" / label).glob("attempt-*.json"))
        return attempts[-1] if attempts else None

    def _latest_variant_attempt_path(
        self,
        run_root: Path,
        variant: str,
    ) -> Path | None:
        attempts = sorted(
            (run_root / "attempts").glob(f"{variant}[123]/attempt-*.json")
        )
        return attempts[-1] if attempts else None

    def _next_attempt(self, run_root: Path, label: str) -> int:
        attempts = sorted((run_root / "attempts" / label).glob("attempt-*.json"))
        if not attempts:
            return 1
        latest = self._read_json(attempts[-1], "trial attempt")
        if latest["status"] in {"prepared", "waiting_gate_a", "waiting_gate_b"}:
            return int(latest["attempt_number"])
        return int(latest["attempt_number"]) + 1

    def _parse_label(self, label: str) -> tuple[str, int]:
        if len(label) != 2 or label[0] not in {"A", "B"} or label[1] not in "123":
            raise EvaluationError(f"invalid semantic trial label: {label}")
        return label[0], int(label[1])

    def _command_result(self, result: CommandResult) -> dict[str, Any]:
        return {
            "argv": list(result.argv),
            "working_directory": result.working_directory,
            "returncode": result.returncode,
            "stdout_path": result.stdout_path,
            "stderr_path": result.stderr_path,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
        }
