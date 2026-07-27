from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TextIO

from .benchmark import load_benchmark
from .controller import EvaluationController, EvaluationRequest
from .executor import CodexExecutor
from .model import EvaluationError, sha256_file
from .reporting import (
    copy_sanitized_report,
    load_run_state,
    read_sanitized_report,
    render_comparison_report,
    select_run_root,
)


_TERMINAL_EXIT_CODES = {"INCOMPLETE": 3, "ABORTED": 4}


def _nonempty_argument(value: str) -> str:
    if not value.strip() or any(character in value for character in "\x00\n\r"):
        raise argparse.ArgumentTypeError("must be a non-empty single-line value")
    return value


def _add_runs_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--runs-root",
        default=".evaluation-runs",
        help="Local root for raw evaluation run artifacts.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="material-review-evaluate",
        description="Compare immutable material-review versions on a frozen benchmark.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    compare = subparsers.add_parser("compare", help="Start or resume a comparison.")
    compare.add_argument("--base-ref", required=True, type=_nonempty_argument)
    compare.add_argument("--candidate-ref", required=True, type=_nonempty_argument)
    compare.add_argument("--benchmark", required=True, type=_nonempty_argument)
    compare.add_argument("--model", required=True, type=_nonempty_argument)
    compare.add_argument("--reasoning-effort", required=True, type=_nonempty_argument)
    compare.add_argument("--repository-root", default=".")
    _add_runs_root(compare)
    compare.add_argument("--executor", choices=("codex",), default="codex")
    compare.add_argument(
        "--new-run",
        action="store_true",
        help="Ignore a matching resumable run and create a new run.",
    )

    status = subparsers.add_parser("status", help="Show durable comparison state.")
    _add_runs_root(status)
    status.add_argument("--run-id", type=_nonempty_argument)

    report = subparsers.add_parser("report", help="Print the sanitized final report.")
    _add_runs_root(report)
    report.add_argument("--run-id", required=True, type=_nonempty_argument)
    report.add_argument("--output", help="Atomically copy the sanitized report here.")

    clean = subparsers.add_parser(
        "clean",
        help="Remove bounded disposable workspaces while retaining run evidence.",
    )
    _add_runs_root(clean)
    clean.add_argument("--run-id", required=True, type=_nonempty_argument)
    return parser


def _read_json_object(path: Path, context: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise EvaluationError(f"{context} is missing or symlinked")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvaluationError(f"{context} is unreadable") from error
    if not isinstance(value, dict):
        raise EvaluationError(f"{context} must be a JSON object")
    return value


def _compare(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    repository_root = Path(arguments.repository_root).expanduser().resolve(strict=True)
    benchmark = load_benchmark(
        repository_root / "evaluations/material-code-review",
        arguments.benchmark,
    )
    runs_root = Path(arguments.runs_root).expanduser().resolve(strict=False)
    executor = CodexExecutor()
    controller = EvaluationController(runs_root=runs_root, executor=executor)
    summary = controller.compare(
        EvaluationRequest(
            repository_root=repository_root,
            benchmark=benchmark,
            base_ref=arguments.base_ref,
            candidate_ref=arguments.candidate_ref,
            executor_adapter=arguments.executor,
            adapter_version="1",
            model=arguments.model,
            reasoning_effort=arguments.reasoning_effort,
            permission_profile="workspace-write",
            isolation_mode="logical_blinding",
            new_run=arguments.new_run,
        )
    )
    if summary.phase == "COMPLETE":
        report_path = render_comparison_report(summary.run_root)
        stdout.write(f"Run: {summary.run_id}\n")
        stdout.write("Phase: COMPLETE\n")
        stdout.write(f"Sanitized report: {report_path}\n")
        return 0
    if summary.phase in _TERMINAL_EXIT_CODES:
        stderr.write(f"Run: {summary.run_id}\n")
        stderr.write(f"Phase: {summary.phase}\n")
        if summary.terminal_reason:
            stderr.write(f"Reason: {summary.terminal_reason}\n")
        return _TERMINAL_EXIT_CODES[summary.phase]
    stderr.write(f"Run {summary.run_id} stopped in nonterminal phase {summary.phase}.\n")
    return 1


def _agreement_status(run_root: Path, variant: str) -> str:
    path = run_root / f"variant-{variant.lower()}/agreement.json"
    if not path.exists():
        return "pending"
    value = _read_json_object(path, f"Variant {variant} agreement")
    classification = value.get("classification")
    if not isinstance(classification, str) or not classification:
        raise EvaluationError(f"Variant {variant} agreement lacks a classification")
    return classification


def _judgment_status(run_root: Path, state: dict[str, Any]) -> str:
    expected_hash = state.get("judgment_sha256")
    if expected_hash is None:
        return "pending"
    path = run_root / "judge/judgment.json"
    if not isinstance(expected_hash, str) or sha256_file(path) != expected_hash:
        raise EvaluationError("locked judgment hash does not match run state")
    judgment = _read_json_object(path, "locked judgment")
    decision = judgment.get("overall_decision")
    if not isinstance(decision, str) or not decision:
        raise EvaluationError("locked judgment lacks an overall decision")
    return decision


def _status(arguments: argparse.Namespace, stdout: TextIO) -> int:
    run_root = select_run_root(
        Path(arguments.runs_root).expanduser(),
        arguments.run_id,
    )
    state = load_run_state(run_root)
    trials = state.get("trials")
    if not isinstance(trials, list):
        raise EvaluationError("evaluation run trials must be an array")
    stdout.write(f"Run: {run_root.name}\n")
    stdout.write(f"Phase: {state.get('phase')}\n")
    for variant in ("A", "B"):
        complete = sum(
            1
            for trial in trials
            if isinstance(trial, dict)
            and trial.get("anonymous_variant") == variant
            and trial.get("status") == "complete"
        )
        stdout.write(f"Variant {variant} trials: {complete} complete\n")
        stdout.write(
            f"Variant {variant} agreement: {_agreement_status(run_root, variant)}\n"
        )
    stdout.write(f"Judgment: {_judgment_status(run_root, state)}\n")
    terminal_reason = state.get("terminal_reason")
    if isinstance(terminal_reason, str) and terminal_reason:
        stdout.write(f"Terminal reason: {terminal_reason}\n")
    return 0


def _report(arguments: argparse.Namespace, stdout: TextIO) -> int:
    run_root = select_run_root(
        Path(arguments.runs_root).expanduser(),
        arguments.run_id,
    )
    render_comparison_report(run_root)
    report_text = read_sanitized_report(run_root)
    if arguments.output:
        copy_sanitized_report(report_text, Path(arguments.output))
    stdout.write(report_text)
    return 0


def _clean(arguments: argparse.Namespace, stdout: TextIO) -> int:
    runs_root = Path(arguments.runs_root).expanduser().resolve(strict=True)
    controller = EvaluationController(runs_root=runs_root, executor=CodexExecutor())
    removed = controller.clean(arguments.run_id)
    noun = "workspace" if len(removed) == 1 else "workspaces"
    stdout.write(f"Removed {len(removed)} disposable {noun}.\n")
    return 0


def main(
    argv: list[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    output = sys.stdout if stdout is None else stdout
    errors = sys.stderr if stderr is None else stderr
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "compare":
            return _compare(arguments, output, errors)
        if arguments.command == "status":
            return _status(arguments, output)
        if arguments.command == "report":
            return _report(arguments, output)
        if arguments.command == "clean":
            return _clean(arguments, output)
        raise EvaluationError(f"unsupported evaluator command: {arguments.command}")
    except (EvaluationError, OSError) as error:
        errors.write(f"material-review-evaluate: {error}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
