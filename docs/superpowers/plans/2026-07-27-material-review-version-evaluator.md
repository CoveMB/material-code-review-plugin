# Material Review Version Evaluator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an explicitly invoked, resumable local harness that compares two immutable `material-code-review` commits on the frozen Discogs benchmark without repairing the target or shipping evaluator code in plugin archives.

**Architecture:** A dependency-free Python package under `scripts/material_review_evaluation/` separates benchmark validation, Git/workspace ownership, native artifact validation, agent execution, orchestration, and reporting. The durable controller writes atomically under `.evaluation-runs/`; it materializes each skill through that commit's standalone packager, drives fresh blinded reviewer/agreement/judge sessions, automates evaluation-only Gate A and Gate B approvals, and locks the blinded judgment before revealing the private A/B map. The public `scripts/evaluate_material_review.py` and `bin/material-review-evaluate` surfaces are thin entrypoints.

**Tech Stack:** Python 3.10+ standard library, Git CLI, Codex CLI adapter, JSON/JSON Schema assets, `unittest`, Make, POSIX shell wrapper.

## Global Constraints

- Affected capability: repository-maintainer evaluation tooling for `material-code-review`; production review and simplification semantics must not change.
- Canonical owners: evaluator behavior in `scripts/material_review_evaluation/`; committed benchmark/rubric/prompt contracts in `evaluations/material-code-review/`; packaging exclusion in `scripts/package_plugin.py`.
- Backward compatibility: preserve native artifacts unchanged and accept the repository's declared controller generations: adjudication/ledger v1 with fix-plan v1, adjudication/ledger v2 with fix-plan v1, and adjudication/ledger v3 with fix-plan v2. No artifact migration is allowed.
- No plugin, standalone-skill, Codex, or Claude manifest version change is required.
- Use only the Python standard library; do not add runtime dependencies.
- The benchmark target is `https://github.com/CoveMB/discogs-collection.git`, baseline `4e59c674dae10a4edcb8952818364c6faa255389`, comparison `42a74b8619054800eca8502d8a687d3c98102565`, and the comparison must have the baseline as its immediate parent.
- Run two fresh trials per anonymous variant; run Trial 3 only after `materially_different` or trial-variability `insufficient_evidence` agreement.
- Automatically approve every retained Gate A finding for planning and approve the exact validated Gate B plan; never call `begin-fix`, `begin-repair`, an approved plan command, a push, or publication action.
- Reviewer trials receive neither oracle content nor earlier trial output. Agreement agents receive only one anonymous variant. The comparison judge receives no skill ref label, skill SHA, commit message, version ordering, private mapping, credential, or machine-specific path.
- Persist raw artifacts under Git-ignored `.evaluation-runs/<run-id>/`; sanitize only report and semantic-agent bundles, never rewrite native artifacts.
- All state transitions and judgment locking are atomic. Matching incomplete runs resume by default; a new run requires `--new-run`.
- Cleanup may remove only recorded controller-owned workspace paths after exact resolution and cleanliness checks. It preserves reports and refuses unresolved, changed, broad, active-repository, or unrecorded paths.
- `compare` requires explicit `--model` and `--reasoning-effort`. `make evaluate-review` requires non-empty `MODEL` and `REASONING_EFFORT`; no costly or time-sensitive model default is committed.
- The live Discogs smoke test remains manual and must not run in `make validate` or CI.
- The known macOS case-insensitive failure in `test_packager_rejects_case_only_collision` remains visible and is not part of this feature.

---

### Task 1: Commit the benchmark contracts and strict loader

**Files:**
- Create: `evaluations/material-code-review/benchmarks/discogs-album-recovery/manifest.json`
- Create: `evaluations/material-code-review/benchmarks/discogs-album-recovery/review-request.md`
- Create: `evaluations/material-code-review/benchmarks/discogs-album-recovery/judge-oracle.json`
- Create: `evaluations/material-code-review/prompts/trial-agreement.md`
- Create: `evaluations/material-code-review/prompts/comparison-judge.md`
- Create: `evaluations/material-code-review/schemas/agreement.schema.json`
- Create: `evaluations/material-code-review/schemas/evaluation-run.schema.json`
- Create: `evaluations/material-code-review/schemas/judgment.schema.json`
- Create: `evaluations/material-code-review/judge-rubric.md`
- Create: `scripts/material_review_evaluation/__init__.py`
- Create: `scripts/material_review_evaluation/model.py`
- Create: `scripts/material_review_evaluation/benchmark.py`
- Create: `scripts/tests/test_evaluate_material_review.py`

**Interfaces:**
- Produces: `EvaluationError`, `canonical_hash(value) -> str`, `sha256_file(path) -> str`, `atomic_write_json(path, value) -> None`, `safe_relative_path(value, context) -> PurePosixPath`, `CommandSpec`, `Benchmark`, and `load_benchmark(catalog_root, benchmark_id) -> Benchmark`.
- Produces: immutable benchmark fields used by every later task, including exact refs, review posture, commands, trial policy, hashes, required lenses, prohibited actions, and executor isolation policy.

- [ ] **Step 1: Write loader tests that name the contract breaks**

Add `BenchmarkLoaderTests` using a copied temporary benchmark directory. The first test must assert the committed benchmark loads with the exact public URL, two SHAs, `initial_trials == 2`, `conditional_third == true`, `review_mode == "range"`, `posture == "immutable"`, `include_untracked == false`, `infrastructure_retry_limit == 1`, and Gate policies `approve_all_retained_for_planning` / `approve_validated_plan_no_repair`. Add separate tests that mutate one input at a time and assert `EvaluationError` for: prompt hash mismatch, oracle hash mismatch, rubric hash mismatch, moving target ref, unsafe working directory, shell metacharacters in a command, missing no-repair prohibition, and an unsupported schema version.

```python
class BenchmarkLoaderTests(unittest.TestCase):
    def test_discogs_benchmark_loads_exact_frozen_contract(self) -> None:
        benchmark = load_benchmark(EVALUATION_ROOT, "discogs-album-recovery")
        self.assertEqual(benchmark.target_repository, "https://github.com/CoveMB/discogs-collection.git")
        self.assertEqual(benchmark.baseline_sha, "4e59c674dae10a4edcb8952818364c6faa255389")
        self.assertEqual(benchmark.comparison_sha, "42a74b8619054800eca8502d8a687d3c98102565")
        self.assertEqual(benchmark.initial_trials, 2)
        self.assertTrue(benchmark.conditional_third)
        self.assertEqual(benchmark.gate_a_policy, "approve_all_retained_for_planning")
        self.assertEqual(benchmark.gate_b_policy, "approve_validated_plan_no_repair")

    def test_prompt_hash_mismatch_is_rejected(self) -> None:
        benchmark_root = self.copy_benchmark()
        (benchmark_root / "review-request.md").write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(EvaluationError, "review_request_sha256"):
            load_benchmark(benchmark_root.parent.parent, benchmark_root.name)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python3 -B -m unittest scripts.tests.test_evaluate_material_review.BenchmarkLoaderTests -v`

Expected: import failure for `scripts.material_review_evaluation.benchmark`; this proves the production loader does not yet exist.

- [ ] **Step 3: Define the benchmark, oracle, rubric, prompt, and schema assets**

The manifest must use schema `material-review-evaluation/benchmark/v1` and include these exact command arrays (never shell strings):

```json
{
  "dependency_installation_commands": [
    {"argv": ["npm", "ci", "--ignore-scripts"], "working_directory": ".", "timeout_seconds": 300}
  ],
  "baseline_validation_commands": [
    {"argv": ["python3", "scripts/dev_checks.py", "--all"], "working_directory": ".", "timeout_seconds": 120},
    {"argv": ["python3", "-m", "compileall", "-q", "scripts", "tests"], "working_directory": ".", "timeout_seconds": 120},
    {"argv": ["npm", "run", "typecheck"], "working_directory": ".", "timeout_seconds": 180},
    {"argv": ["python3", "-m", "unittest", "discover", "-s", "tests"], "working_directory": ".", "timeout_seconds": 300}
  ]
}
```

`review-request.md` must explicitly invoke the materialized skill, name the frozen target range and required lenses, require causal evidence and negative controls, stop at Gate A and Gate B, and prohibit oracle lookup, repair, live Spotify calls, private Discogs data, publication, source egress, and prior-run discovery. `judge-oracle.json` must encode the three approved failure modes with `trigger`, `consequence`, `source_boundary`, `reproduction_shape`, `counterevidence`, and `provenance`; provenance must state that historical run two was non-blind and both historical validations were same-process degraded self-audits. `judge-rubric.md` must reproduce every primary/secondary dimension and the exact overall decision rule from the approved design.

The agreement schema must allow only `materially_similar`, `materially_different`, and `insufficient_evidence`. The judgment schema must allow per-dimension `A_STRONGER`, `B_STRONGER`, `TIE`, or `UNKNOWN` and overall `VARIANT_A_STRONGER`, `VARIANT_B_STRONGER`, `MATERIAL_TIE`, or `INSUFFICIENT_EVIDENCE`. All schemas must be draft 2020-12 object schemas with `additionalProperties: false` at each controlled object boundary.

- [ ] **Step 4: Implement the dependency-free loader and shared primitives**

Use frozen dataclasses and tuple fields so loaded policy cannot mutate during a run:

```python
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
    prohibitions: frozenset[str]
    file_hashes: Mapping[str, str]
```

Reject command arguments containing NUL, newline, or carriage return; reject command executables outside the committed allowlist `{python3, npm}`; reject absolute or parent-traversing working directories; require lowercase 40-character Git SHAs; require HTTPS public repository URLs; and recompute all declared file hashes from bytes. `atomic_write_json` must use `mkstemp`, flush, `os.fsync`, and `os.replace`.

- [ ] **Step 5: Recompute and write exact committed asset hashes**

Run this after finalizing the three files, then write the printed lowercase SHA-256 values into `manifest.json`:

```bash
python3 -c 'import hashlib,pathlib; root=pathlib.Path("evaluations/material-code-review"); files=[root/"benchmarks/discogs-album-recovery/review-request.md",root/"benchmarks/discogs-album-recovery/judge-oracle.json",root/"judge-rubric.md"]; [print(path.relative_to(root), hashlib.sha256(path.read_bytes()).hexdigest()) for path in files]'
```

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `python3 -B -m unittest scripts.tests.test_evaluate_material_review.BenchmarkLoaderTests -v`

Expected: every loader test passes with pristine output.

- [ ] **Step 7: Commit Task 1**

```bash
git add evaluations/material-code-review scripts/material_review_evaluation scripts/tests/test_evaluate_material_review.py
git commit -m "Add evaluation benchmark contracts"
```

### Task 2: Materialize immutable variants and owned target workspaces

**Files:**
- Create: `scripts/material_review_evaluation/workspace.py`
- Modify: `scripts/tests/test_evaluate_material_review.py`

**Interfaces:**
- Consumes: `EvaluationError`, `Benchmark`, `canonical_hash`, `sha256_file`, and `atomic_write_json` from Task 1.
- Produces: `ResolvedVariant`, `WorkspaceRecord`, `CommandResult`, `resolve_variant(repo_root, ref) -> ResolvedVariant`, `verify_benchmark_range(mirror, benchmark) -> None`, `materialize_variant(...) -> WorkspaceRecord`, `prepare_target_mirror(...) -> WorkspaceRecord`, `create_trial_target(...) -> WorkspaceRecord`, `run_benchmark_commands(...) -> tuple[CommandResult, ...]`, `attest_clean_target(...) -> dict[str, object]`, and `clean_owned_workspaces(...) -> tuple[Path, ...]`.

- [ ] **Step 1: Write Git and cleanup tests first**

Create temporary Git repositories with commits and a minimal historical packager. Tests must prove: refs resolve once to 40-character SHAs; moving ref names are not reused after resolution; non-parent benchmark pairs fail; variant materialization invokes the selected commit's packager and produces a workflow tree without `.git`, evaluator files, oracle, other variant, or source checkout; trial clones are detached at the comparison SHA; cleanliness attestation detects branch/HEAD/index/worktree changes; cleanup refuses unrecorded paths, the repository root, a changed workspace, and a symlinked workspace; and cleanup removes only exact clean recorded directories.

```python
class WorkspaceManagerTests(unittest.TestCase):
    def test_resolved_variant_remains_bound_after_ref_moves(self) -> None:
        repository = self.create_skill_repository()
        original = resolve_variant(repository, "candidate")
        self.commit_file(repository, "later.txt", "later\n")
        self.run_git(repository, "branch", "-f", "candidate", "HEAD")
        self.assertNotEqual(self.git(repository, "rev-parse", "candidate"), original.commit_sha)
        materialized = materialize_variant(repository, original, self.workspace_root, "run-one")
        self.assertEqual((materialized.path / "materialized-commit.txt").read_text().strip(), original.commit_sha)

    def test_cleanup_refuses_changed_recorded_workspace(self) -> None:
        record = self.make_owned_workspace()
        (record.path / "unexpected.txt").write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(EvaluationError, "unrecorded changes"):
            clean_owned_workspaces(self.repository_root, (record,))
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python3 -B -m unittest scripts.tests.test_evaluate_material_review.WorkspaceManagerTests -v`

Expected: import failure for `scripts.material_review_evaluation.workspace`.

- [ ] **Step 3: Implement safe Git primitives and range verification**

Every subprocess call must use an argument list, `shell=False`, a timeout, captured text, and a checked return code translated to `EvaluationError` without environment dumps. `resolve_variant` records ref, SHA, subject hash (not subject text in blinded data), and repository root. `verify_benchmark_range` must execute `git rev-parse <comparison>^` in the mirror and compare the exact result to the baseline.

```python
@dataclass(frozen=True)
class ResolvedVariant:
    supplied_ref: str
    commit_sha: str
    commit_subject_sha256: str

@dataclass(frozen=True)
class WorkspaceRecord:
    kind: str
    path: Path
    owner_run_id: str
    expected_head: str | None
    initial_status_sha256: str

@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    working_directory: str
    returncode: int
    stdout_path: str
    stderr_path: str
    started_at: str
    finished_at: str
```

- [ ] **Step 4: Implement distribution-faithful variant materialization**

For each resolved skill SHA: create an owned temporary source directory; stream `git archive <sha>` to a tar file; reject absolute, parent-traversing, device, FIFO, hard-link, and symlink members before extraction; run that snapshot's `scripts/package_plugin.py --package-root <snapshot> --output <discarded-full.zip> --standalone-output <standalone.zip>`; run that snapshot's `scripts/validate_package.py --package-root <snapshot> --standalone-archive <standalone.zip>`; safely extract the standalone ZIP into `workflow/material-code-review`; delete the source snapshot and discarded full ZIP; and hash the final materialized file inventory. Variant-specific materialization failure must be returned as structured workflow evidence rather than silently substituting another skill copy.

- [ ] **Step 5: Implement mirror, trial clone, attestation, and bounded cleanup**

Create one run-owned `git clone --mirror` and then local fresh clones for each trial. Each target clone must be detached at the comparison SHA and record: HEAD, branch (empty), porcelain-v1 `-z` status hash, refs hash, and object range. `attest_clean_target` compares all recorded values and rejects new branches, commits, index/worktree changes, or remote URL drift. Cleanup resolves every path strictly, confirms it is a descendant of the run workspace root with at least two path components below it, rejects symlinks and active repository aliases, re-runs cleanliness checks, then uses `shutil.rmtree` only for the approved records.

`run_benchmark_commands` executes only the already validated argv arrays in their safe relative working directories, with exact timeouts and separate stdout/stderr files. Run dependency-installation and baseline-validation commands for every trial target before launching its reviewer; record exit status and log hashes. Environmental validation failures may proceed only when every variant receives the same command, return code, and normalized failure signature. A variant-specific or unmatched failure ends the run `INCOMPLETE`.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `python3 -B -m unittest scripts.tests.test_evaluate_material_review.WorkspaceManagerTests -v`

Expected: all workspace tests pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add scripts/material_review_evaluation/workspace.py scripts/tests/test_evaluate_material_review.py
git commit -m "Add isolated evaluation workspaces"
```

### Task 3: Validate native review artifacts and enforce automatic gates

**Files:**
- Create: `scripts/material_review_evaluation/artifacts.py`
- Modify: `scripts/tests/test_evaluate_material_review.py`

**Interfaces:**
- Consumes: shared primitives from Task 1 and target cleanliness from Task 2.
- Produces: `NATIVE_SCHEMA_PROFILES`, `NativeTrialArtifacts`, `find_native_run(trial_root)`, `validate_gate_a_artifacts(...)`, `gate_a_command(...)`, `validate_gate_b_artifacts(...)`, `gate_b_command(...)`, and `normalize_trial_evidence(...)`.

- [ ] **Step 1: Write artifact-integrity and policy tests first**

Use invented native run directories for all three declared schema profiles. Cover: every candidate group is kept or discarded exactly once; embedded ledger/gate/plan hashes match canonical JSON; state hashes and gate hashes match artifacts; Gate A approves all and only retained finding IDs; empty ledgers require `accepted_empty`; Gate B approves the exact validated plan hash; every approved ID appears exactly once in the plan; plan paths remain within the frozen scope; phases `FIXING`, `VERIFYING`, `REPAIR_REQUIRED`, `PLAN_AMENDMENT_REQUIRED`, and `BLOCKED` are rejected; a second native run directory is rejected as ambiguous; missing files are rejected rather than reconstructed from Markdown; native files are byte-identical before and after normalization.

```python
class NativeArtifactTests(unittest.TestCase):
    def test_gate_a_command_approves_every_retained_id_and_no_other_id(self) -> None:
        artifacts = self.native_artifacts(findings=("F001", "F002"))
        command = gate_a_command(artifacts)
        self.assertEqual(command.approved_ids, ("F001", "F002"))
        self.assertEqual(command.argv[-2:], ("--user-statement", "Evaluation policy approves every retained finding for planning and no others; repair is not authorized."))

    def test_mutation_phase_is_unconditionally_rejected(self) -> None:
        artifacts = self.native_artifacts(phase="FIXING")
        with self.assertRaisesRegex(EvaluationError, "repair phase"):
            validate_gate_b_artifacts(artifacts.run_directory, artifacts.controller, artifacts.target)
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python3 -B -m unittest scripts.tests.test_evaluate_material_review.NativeArtifactTests -v`

Expected: import failure for `scripts.material_review_evaluation.artifacts`.

- [ ] **Step 3: Implement declared native schema profiles and independent hash checks**

```python
NATIVE_SCHEMA_PROFILES = {
    ("material-review/state/v1", "material-review/ledger/v1", "material-review/fix-plan/v1"),
    ("material-review/state/v1", "material-review/ledger/v2", "material-review/fix-plan/v1"),
    ("material-review/state/v1", "material-review/ledger/v3", "material-review/fix-plan/v2"),
}
```

Recompute `ledger_hash` after removing `ledger_hash` and `generated_at`; recompute `plan_hash` after removing `plan_hash` and `validated_at`; recompute both gate receipt hashes after removing `receipt_hash`. Require state-to-artifact equality for scope, ledger, plan, and receipt hashes. Invoke the materialized controller's own `check-scope` and `status --json` commands using its recorded run ID so native semantics remain authoritative.

- [ ] **Step 4: Implement exact Gate A and Gate B policy commands**

`gate_a_command` returns a fully split argv for the materialized controller. For retained findings it supplies one comma-separated `--approve` value containing sorted IDs and the exact statement `Evaluation policy approves every retained finding for planning and no others; repair is not authorized.` For an empty ledger it supplies `--accept-empty` and `Evaluation policy accepts the empty material ledger; repair is not authorized.` It never supplies reject or defer IDs.

`gate_b_command` requires `PLAN_VALIDATED`, validates the fix plan, supplies `--approve`, and uses the exact statement `Evaluation policy approves this exact validated plan for comparison evidence only; no repair or plan command execution is authorized.` The evaluator must stop at `PLAN_APPROVED` and reject any later phase.

- [ ] **Step 5: Implement immutable normalization for semantic comparison**

`normalize_trial_evidence` copies comparison fields into a new JSON object: native schema versions, ledger verdict/summary, kept findings with dispositions/evidence/validation/materiality/repair direction, discarded groups, limitations, Gate A decisions, plan items with root cause/objective/paths/tests/risk controls/rollback, Gate B receipt, timing/turn/tool metadata, scope freshness, and cleanliness attestations. It stores SHA-256 hashes and relative artifact references to every native file; it never modifies native JSON.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `python3 -B -m unittest scripts.tests.test_evaluate_material_review.NativeArtifactTests -v`

Expected: every native-artifact test passes.

- [ ] **Step 7: Commit Task 3**

```bash
git add scripts/material_review_evaluation/artifacts.py scripts/tests/test_evaluate_material_review.py
git commit -m "Validate evaluation review artifacts"
```

### Task 4: Add blinded bundles and the local Codex executor adapter

**Files:**
- Create: `scripts/material_review_evaluation/executor.py`
- Create: `scripts/material_review_evaluation/bundles.py`
- Modify: `scripts/tests/test_evaluate_material_review.py`

**Interfaces:**
- Consumes: evaluation schemas/prompts, benchmark, normalized evidence, and materialized workflow/target paths.
- Produces: `SessionSpec`, `SessionResult`, `AgentExecutor` protocol, `CodexExecutor`, `build_trial_request`, `build_agreement_bundle`, `build_comparison_bundle`, `scan_blinded_bundle`, and `redact_machine_paths`.

- [ ] **Step 1: Write executor and blinding tests first**

Test JSONL parsing with recorded invented events containing `thread.started`, token usage, tool events, and final output. Assert start argv contains `codex exec --json --ignore-user-config --model <model> -c model_reasoning_effort=<effort> --sandbox workspace-write --cd <target> --add-dir <workflow> --add-dir <trial-output>` and never contains the other variant or oracle path. Assert resume uses the recorded session ID and the same model/reasoning settings. Test that agreement bundles contain exactly one anonymous variant's normalized trials; comparison bundles contain A and B, agreement summaries, oracle, rubric, and schemas but no private mapping. Assert scanning rejects skill refs, skill SHAs, commit subjects, `old`/`new` labels used as identities, credentials, absolute workspace paths, and symlinks escaping the bundle.

```python
class ExecutorAndBlindingTests(unittest.TestCase):
    def test_codex_start_records_thread_id_and_exact_configuration(self) -> None:
        runner = RecordingRunner(stdout='{"type":"thread.started","thread_id":"trial-session"}\n')
        result = CodexExecutor(runner=runner).start(self.session_spec())
        self.assertEqual(result.session_id, "trial-session")
        self.assertIn("model_reasoning_effort=high", runner.argv)
        self.assertNotIn(str(self.oracle_path), " ".join(runner.argv))

    def test_comparison_bundle_rejects_private_variant_identity(self) -> None:
        bundle = self.build_bundle_with_text("candidate ref feature/evaluator")
        with self.assertRaisesRegex(EvaluationError, "identity leak"):
            scan_blinded_bundle(bundle, self.private_tokens())
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python3 -B -m unittest scripts.tests.test_evaluate_material_review.ExecutorAndBlindingTests -v`

Expected: import failure for `executor` or `bundles`.

- [ ] **Step 3: Implement the executor protocol and Codex adapter**

```python
class AgentExecutor(Protocol):
    def start(self, session_spec: SessionSpec) -> SessionResult: ...
    def resume(self, session_id: str, statement: str, session_spec: SessionSpec) -> SessionResult: ...
    def status(self, session_id: str) -> Literal["running", "waiting", "complete", "failed"]: ...

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
```

Use `subprocess.Popen` with stdout/stderr captured to per-session log files, `shell=False`, and no environment dump. Construct a narrow child environment that preserves `PATH`, `HOME`, `CODEX_HOME`, locale, temporary-directory variables, and `OPENAI_API_KEY` only when already configured for Codex; never persist their values. Remove `SSH_AUTH_SOCK`, GitHub tokens, cloud credentials, and unrelated variables whose names contain `TOKEN`, `SECRET`, `PASSWORD`, or `KEY`. Parse the thread ID and usage from JSONL without trusting model text. Agreement/judge calls use `--ephemeral`, `--sandbox read-only`, `--skip-git-repo-check`, `--output-schema`, and a fresh process. Trial calls remain resumable. `status` reports only recorded process/session state. Nonzero exit, missing thread ID, timeout, malformed JSONL, or schema-invalid final output returns a typed infrastructure failure.

- [ ] **Step 4: Build identical trial requests and allowlisted semantic bundles**

`build_trial_request` writes a generated wrapper containing only: the common `review-request.md`, materialized skill path, target path, controller artifact root, anonymous trial label, explicit instruction to read that exact skill and no other copy, and the host isolation mode. Hash the request and executor configuration into the trial record.

Bundle builders copy only normalized evidence and committed prompts/rubric/oracle required for that role. Replace the repository root, run root, target roots, workflow roots, and user home prefixes with `<repository>`, `<run>`, `<target>`, `<workflow>`, and `<home>`. Reject path-like strings still beginning with `/`, private mapping values, variant refs/SHAs/subjects, credential assignment patterns, and non-regular files.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `python3 -B -m unittest scripts.tests.test_evaluate_material_review.ExecutorAndBlindingTests -v`

Expected: every executor and blinding test passes.

- [ ] **Step 6: Commit Task 4**

```bash
git add scripts/material_review_evaluation/executor.py scripts/material_review_evaluation/bundles.py scripts/tests/test_evaluate_material_review.py
git commit -m "Add blinded evaluation agents"
```

### Task 5: Implement the durable evaluation state machine and adaptive trials

**Files:**
- Create: `scripts/material_review_evaluation/controller.py`
- Modify: `scripts/tests/test_evaluate_material_review.py`

**Interfaces:**
- Consumes: every interface from Tasks 1–4.
- Produces: `EvaluationController.compare(request) -> RunSummary`, `EvaluationController.status(run_id)`, `EvaluationController.clean(run_id)`, and durable `run.json`, trial, agreement, judgment, reveal, and infrastructure-attempt records.

- [ ] **Step 1: Write fake-executor lifecycle tests first**

Implement a test-only `FakeExecutor` that writes native controller fixtures at Gate A and Gate B and returns schema-valid agreement/judgment results. Add integration tests for: two consistent zero-finding variants; one consistent and one inconsistent variant where only the inconsistent variant receives Trial 3; old and current native schema profiles; one infrastructure failure followed by one retry that does not increment semantic trial count; repeated infrastructure failure producing `INCOMPLETE`; a variant-specific materialization failure retained as judge-visible workflow evidence while the runnable variant continues; shared materialization failure producing `INCOMPLETE`; equivalent environmental validation failures proceeding with limitations; unmatched environmental validation failure producing `INCOMPLETE`; interruption/resume at Gate A, Gate B, agreement, and blinded judgment; no consensus after Trial 3 marking the variant unstable; model/reasoning/executor mismatch producing `ABORTED`; judgment hash present before reveal creation; and any repair-phase entry invalidating the trial.

```python
class EvaluationControllerTests(unittest.TestCase):
    def test_conditional_third_trial_runs_only_for_inconsistent_variant(self) -> None:
        executor = FakeExecutor(agreement={"A": "materially_different", "B": "materially_similar"})
        summary = self.controller(executor).compare(self.request())
        self.assertEqual(executor.trial_labels, ["A1", "B1", "B2", "A2", "A3"])
        self.assertEqual(summary.semantic_trial_counts, {"A": 3, "B": 2})

    def test_reveal_is_written_only_after_locked_judgment(self) -> None:
        summary = self.controller(FakeExecutor()).compare(self.request())
        judgment = self.read_json(summary.run_root / "judge/judgment.json")
        reveal = self.read_json(summary.run_root / "judge/reveal.json")
        self.assertEqual(reveal["judgment_sha256"], sha256_file(summary.run_root / "judge/judgment.json"))
        self.assertLess(judgment["locked_at"], reveal["revealed_at"])
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python3 -B -m unittest scripts.tests.test_evaluate_material_review.EvaluationControllerTests -v`

Expected: import failure for `scripts.material_review_evaluation.controller`.

- [ ] **Step 3: Implement the exact durable state model**

Persist only these ordered phases: `PREFLIGHT`, `PREPARED`, `INITIAL_TRIALS`, `CONSISTENCY_CHECK`, `OPTIONAL_THIRD_TRIAL`, `BLINDED_JUDGMENT`, `IDENTITY_REVEAL`, `COMPLETE`, plus terminal `INCOMPLETE` and `ABORTED`. `run.json` uses schema `material-review-evaluation/run/v1` and contains run ID, request fingerprint, benchmark hashes, executor/model/reasoning/permission configuration, resolved skill SHAs, private-map hash (not contents), phase, validated predecessor hashes, trial/attempt records, workspace records, timestamps, terminal reason, and report hash.

Write the private random map separately with `secrets.SystemRandom().sample`; record only its hash in `run.json`. Every transition function must load the current state, require the exact predecessor phase and artifact hashes, write its output atomically, then atomically replace `run.json`. Search matching nonterminal runs by request fingerprint; resume the newest exact match unless `--new-run` is true.

- [ ] **Step 4: Drive paired trial waves through Gate B without repair**

Randomize A/B order separately for wave 1 and wave 2 and persist the schedule before starting. For each trial: create a fresh target; build the request; start a new session; validate Gate A; resume with the exact Gate A statement; validate Gate B; resume with the exact Gate B statement; require `PLAN_APPROVED` or empty-ledger `COMPLETE`; stop without another resume; run scope and target-cleanliness attestations; normalize artifacts; and persist attempt/session/log metadata. Retry the same semantic label once only for typed infrastructure failure and retain both attempt histories.

Before each reviewer starts, execute and record the benchmark's dependency-installation and baseline-validation commands. Compare normalized environmental failure signatures across anonymous variants before deciding whether the equivalence exception applies. Preserve variant-specific package/materialization failures as blinded workflow evidence and continue the runnable side to judgment; stop `INCOMPLETE` when the shared environment prevents fair materialization or validation.

- [ ] **Step 5: Implement adaptive agreement and blinded comparison**

After two trials for one anonymous variant, launch a new agreement session and validate/copy its output to `variant-a/agreement.json` or `variant-b/agreement.json`. Schedule Trial 3 only for `materially_different`, or `insufficient_evidence` whose `reason_category` is `trial_variability`; infrastructure insufficiency ends `INCOMPLETE`. Preserve all three trials and agreement outliers.

After agreements complete, create and scan the comparison bundle, launch one fresh comparison judge, schema-validate the result, add `locked_at`, atomically write `judge/judgment.json`, compute its file SHA-256, and persist that hash in `run.json`. Only then write `judge/reveal.json` containing the private A/B map and judgment hash, transition through `IDENTITY_REVEAL`, and render-ready `COMPLETE`. Never infer a winner if the judge returns `MATERIAL_TIE` or `INSUFFICIENT_EVIDENCE`.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `python3 -B -m unittest scripts.tests.test_evaluate_material_review.EvaluationControllerTests -v`

Expected: every lifecycle and resume test passes.

- [ ] **Step 7: Commit Task 5**

```bash
git add scripts/material_review_evaluation/controller.py scripts/tests/test_evaluate_material_review.py
git commit -m "Orchestrate resumable review evaluations"
```

### Task 6: Expose CLI/reporting, protect distributions, and document operation

**Files:**
- Create: `scripts/material_review_evaluation/reporting.py`
- Create: `scripts/material_review_evaluation/cli.py`
- Create: `scripts/evaluate_material_review.py`
- Create: `bin/material-review-evaluate`
- Modify: `.gitignore`
- Modify: `Makefile`
- Modify: `scripts/package_plugin.py`
- Modify: `scripts/validate_package.py`
- Modify: `scripts/tests/test_packaging.py`
- Modify: `scripts/tests/test_evaluate_material_review.py`
- Modify: `README.md`
- Modify: `EVALUATION.md`

**Interfaces:**
- Consumes: `EvaluationController` and completed run artifacts.
- Produces: `material-review-evaluate compare|status|report|clean`, `make evaluate-review`, sanitized `comparison-report.md`, root validation coverage, and explicit archive exclusions.

- [ ] **Step 1: Write CLI, report, validation, and packaging tests first**

Tests must assert: compare rejects missing model or reasoning effort before cloning/agents; status prints phase/trial/agreement/judgment state; report refuses unlocked judgment and prints/copies only the sanitized report; clean preserves run metadata/reports and removes only approved workspaces; report contains decision, per-dimension evidence, stability, known failures found/missed, unsupported findings, plan-boundary comparison, workflow failures, cost, confidence, limitations, then post-lock identity reveal; report contains no credential or absolute machine path; full and standalone archives contain no `evaluations/`, evaluator modules/entrypoint/tests, `bin/material-review-evaluate`, `.evaluation-runs/`, `.superpowers/`, or `docs/superpowers/`; source validation requires the evaluator wrapper to be executable and all committed evaluation JSON valid.

```python
class EvaluationCliTests(unittest.TestCase):
    def test_compare_requires_explicit_model_and_reasoning_before_side_effects(self) -> None:
        result = run_cli(["compare", "--base-ref", "main", "--candidate-ref", "HEAD", "--benchmark", "discogs-album-recovery"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("--model", result.stderr)
        self.assertFalse(self.runs_root.exists())

class EvaluationPackagingTests(unittest.TestCase):
    def test_plugin_archives_exclude_repository_maintainer_evaluator(self) -> None:
        names = self.build_full_archive_names()
        forbidden = ("evaluations/", "scripts/material_review_evaluation/", "scripts/evaluate_material_review.py", "bin/material-review-evaluate", "docs/superpowers/")
        self.assertFalse(any(name.startswith(forbidden) or name in forbidden for name in names))
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python3 -B -m unittest scripts.tests.test_evaluate_material_review.EvaluationCliTests scripts.tests.test_evaluate_material_review.EvaluationPackagingTests -v`

Expected: imports or entrypoints are missing, and the current full packager includes evaluator/design paths.

- [ ] **Step 3: Implement the CLI and dependency-free sanitized reporter**

`compare` requires `--base-ref`, `--candidate-ref`, `--benchmark`, `--model`, and `--reasoning-effort`; accepts `--repository-root`, `--runs-root`, `--executor codex`, and `--new-run`; and returns nonzero for `INCOMPLETE` or `ABORTED`. `status` accepts `--run-id` or selects the newest run. `report` accepts `--run-id` and optional `--output`; it refuses any phase before `COMPLETE`. `clean` accepts `--run-id` and calls bounded cleanup while preserving `run.json`, private map, native evidence, judgment, reveal, and report.

The report renderer reads the locked judgment and reveal, not model prose outside those contracts. It redacts the configured path prefixes and credential patterns, validates no absolute path remains, writes atomically, and records its hash in `run.json`.

- [ ] **Step 4: Add thin entrypoints and Make integration**

`scripts/evaluate_material_review.py` imports and calls `scripts.material_review_evaluation.cli.main`. `bin/material-review-evaluate` resolves the repository root exactly as `bin/material-reviewctl` does and `exec`s the Python entrypoint. Add `.evaluation-runs/` and `.superpowers/` to `.gitignore`.

Add this target shape without a default model:

```make
.PHONY: evaluate-review

evaluate-review:
	@test -n "$(BASE_REF)" -a -n "$(CANDIDATE_REF)" -a -n "$(BENCHMARK)" -a -n "$(MODEL)" -a -n "$(REASONING_EFFORT)" || { echo "BASE_REF, CANDIDATE_REF, BENCHMARK, MODEL, and REASONING_EFFORT are required" >&2; exit 2; }
	$(PYTHON) scripts/evaluate_material_review.py compare --base-ref "$(BASE_REF)" --candidate-ref "$(CANDIDATE_REF)" --benchmark "$(BENCHMARK)" --model "$(MODEL)" --reasoning-effort "$(REASONING_EFFORT)"
```

Extend `compile`, `shell`, and `validate` to cover evaluator Python, the wrapper, and evaluator tests. Do not add the live comparison to validation.

- [ ] **Step 5: Exclude maintainer tooling from every distribution**

In `scripts/package_plugin.py`, exclude exact maintainer-only paths/prefixes from the full archive: `evaluations/`, `scripts/material_review_evaluation/`, `scripts/evaluate_material_review.py`, `scripts/tests/test_evaluate_material_review.py`, `bin/material-review-evaluate`, `docs/superpowers/`, `.evaluation-runs/`, and `.superpowers/`. The standalone allowlist remains unchanged. In `scripts/validate_package.py`, reject those entries if present in any archive and validate their source JSON only when operating on a source checkout. Add behavioral packaging tests that build both archives and inspect names.

- [ ] **Step 6: Update maintainer documentation without changing shipped skill claims**

Add a `README.md` maintainer-evaluation section with the exact invocation:

```bash
make evaluate-review \
  BASE_REF=origin/main \
  CANDIDATE_REF=HEAD \
  BENCHMARK=discogs-album-recovery \
  MODEL=gpt-5.6-sol \
  REASONING_EFFORT=high
```

Explain cost, local raw artifacts, logical-versus-filesystem blinding, manual live smoke testing, no repair, no implicit-activation claim, resume/new-run behavior, and report/clean commands. Update `EVALUATION.md` with the qualitative rubric, oracle provenance caveat, native-schema preservation, explicit limitations, and the known macOS case-only fixture failure. Do not describe evaluator code as part of installed plugin contents.

- [ ] **Step 7: Run focused tests and verify GREEN**

Run: `python3 -B -m unittest scripts.tests.test_evaluate_material_review.EvaluationCliTests scripts.tests.test_evaluate_material_review.EvaluationPackagingTests -v`

Expected: CLI/report and archive-boundary tests pass.

- [ ] **Step 8: Run the complete evaluator and repository verification set**

Run in order:

```bash
python3 -B -m unittest scripts.tests.test_evaluate_material_review -v
python3 -B -m unittest discover -s skills/material-code-review/tests -p 'test_*.py' -v
python3 -B -m unittest discover -s skills/material-code-simplification/tests -p 'test_*.py' -v
python3 -B -m unittest discover -s scripts/tests -p 'test_*.py' -v
make package
make package-simplification
```

Expected: evaluator, controller, simplification, and all non-filesystem-limited packaging tests pass; the known case-only collision test remains the only expected failure on case-insensitive APFS. If any other test fails, stop and fix it before completion. Do not run the live Discogs comparison.

- [ ] **Step 9: Focused requirements and DRY pass**

Re-read the approved design and verify each acceptance criterion maps to a passing test. Search the complete contract inventory for evaluator paths, old/new schema terms, `begin-fix`, `begin-repair`, `never`, `always`, `only`, `unless`, `except`, `allow`, `degraded`, version numbers, archive include/exclude rules, and no-repair statements. Remove duplicated policy logic only when one existing helper can own it without obscuring boundaries.

- [ ] **Step 10: Commit Task 6**

```bash
git add .gitignore Makefile README.md EVALUATION.md bin/material-review-evaluate scripts/evaluate_material_review.py scripts/material_review_evaluation scripts/package_plugin.py scripts/validate_package.py scripts/tests evaluations/material-code-review
git commit -m "Expose material review version evaluator"
```
