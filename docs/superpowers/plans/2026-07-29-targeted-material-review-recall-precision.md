# Targeted Material-Review Recall and Precision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add immutable, exhaustive, risk-bound material-review coverage; bind reviewer outputs to exact plans, lenses, and evidence paths; and improve output-integrity, persisted-config, and strict-validation review precision without weakening gates or repair safety.

**Architecture:** New material-review runs record one scope-hash-bound `coverage-plan/v1` before dispatch and accept only `candidate-set/v2` responses bound to that plan and lens. The shared controller validates complete waves atomically, blocks legacy forward progress while preserving restoration, and uses a trusted internal profile to keep all material-simplification scopes on candidate-set v1. Judgment rules remain in the canonical material-review skill and references; machine enforcement remains in `reviewctl.py` and schemas.

**Tech Stack:** Python 3.10+ standard library, JSON Schema draft 2020-12, `unittest`, Markdown Agent Skills contracts, Make-based packaging and validation.

## Global Constraints

- Start from exact base `c18d31fbd704ba76fe7e4c28959ae81c4b4049ea`; fetched `origin/main` matched before the isolated worktree was created.
- Work only on branch `feature/targeted-review-recall-precision`; never use the forbidden `codex` prefix.
- Affected capabilities: material review, shared controller, and packaging. Material-simplification judgment and repair semantics remain unchanged.
- Canonical semantic owner: `skills/material-code-review/SKILL.md`. Controller enforcement belongs in `skills/material-code-review/scripts/reviewctl.py`; machine shapes belong in `skills/material-code-review/schemas/`.
- Preserve frozen/hash-bound scope, complete candidate adjudication, repair-direction audit, Gate A before planning, Gate B before mutation, exact approved IDs/paths/tests, checkpoint restoration, finite attempts and repair rounds, bounded post-fix verification, and no automatic publication or source egress.
- Keep runtime dependencies in the Python standard library.
- Implement only the targeted design in `docs/superpowers/specs/2026-07-29-targeted-material-review-recall-precision-design.md`. Do not port PR provenance, protocol coherence, candidate correction/preflight, fallback scheduling, evaluator replacement, pre-verification recovery, or unrelated candidate-branch behavior.
- Unfinished pre-contract material-review runs are not migrated. They fail closed with `Run predates required coverage; start a new run.` Forward progress is blocked, while `status`, direct artifact reads, `check-scope`, `rollback-finding`, and `abort-fixes` remain available where their existing phase rules permit safe inspection or restoration.
- Existing profiled codebase-simplification runs remain exempt. Ambiguous legacy delegated-scope simplification runs lack a trustworthy discriminator and must restart. Every new simplification scope is profiled internally and remains outside material-review coverage.
- Material-review/full-plugin release version: `1.3.0`. Standalone material-simplification release version: `1.2.0`.
- During implementation, run only targeted deterministic tests for the changed behavior. Run `make package package-simplification` once on the final coherent tree.
- Run at most one fresh-task confirmation evaluation after deterministic validation and final review. Never use live/model evaluation as an implementation loop; never approve evaluator Gate B.

## File Map

### Create

- `skills/material-code-review/schemas/coverage-plan.schema.json` — root input contract for exhaustive risk assessments and lens assignments.
- `skills/material-code-review/schemas/candidate-set-v2.schema.json` — material-review output contract bound to coverage plan and lens.
- `skills/material-code-review/references/reliability-output-integrity-lens.md` — destination alias, ownership, and write-order review procedure.
- `skills/material-code-review/references/persisted-config-migration-lens.md` — persisted-field compatibility and downstream-identity procedure.
- `skills/material-code-review/tests/test_discovery_contract.py` — controlled workflow and judgment wording tests.

### Modify

- `skills/material-code-review/scripts/reviewctl.py` — coverage recording, candidate v2 validation, atomic wave enforcement, ledger binding, compatibility guard, and trusted profiles.
- `skills/material-code-review/tests/test_reviewctl.py` — controller behavioral tests.
- `skills/material-code-simplification/scripts/simplifyctl.py` — trusted internal profile for delegated change scopes.
- `skills/material-code-simplification/tests/test_simplifyctl.py` — complete delegated-scope v1 lifecycle regression.
- `skills/material-code-review/SKILL.md` and targeted `references/` files — canonical selection, reviewer, lifecycle, failure, and adjudication rules.
- `skills/material-code-review/scripts/validate_package.py`, `scripts/validate_package.py`, and `scripts/tests/test_packaging.py` — required files, markers, archive contents, and versions.
- `.codex-plugin/plugin.json`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `Makefile`, packagers, and validators — aligned release identities.
- `README.md`, `CODEX.md`, `CHANGELOG.md`, and `EVALUATION.md` — workflow, compatibility, versions, and evidence limits.

### Inspect and normally leave unchanged

- Root `SKILL.md`, `commands/material-review.md`, `agents/`, `skills/*/agents/openai.yaml`, `.agents/plugins/`, examples, adjudication schema, repair schemas, and material-simplification canonical skill/references.

---

### Task 1: Record One Exhaustive, Immutable Coverage Plan

**Files:**

- Create: `skills/material-code-review/schemas/coverage-plan.schema.json`
- Modify: `skills/material-code-review/scripts/reviewctl.py`
- Modify: `skills/material-code-review/tests/test_reviewctl.py`
- Modify: `skills/material-code-simplification/scripts/simplifyctl.py`
- Modify: `skills/material-code-simplification/tests/test_simplifyctl.py`

**Interfaces:**

- Consumes: active material-review `state.json`, verified frozen `scope.json`, and a root plan with exact fields `schema_version`, `scope_hash`, `workflow_profile`, `risk_assessments`, and `lenses`.
- Produces: trusted `main(argv: Sequence[str] | None = None, *, workflow_profile: str = WORKFLOW_PROFILE_REVIEW) -> int`, profile-correct review/simplification states, `is_simplification_state(state: dict[str, Any]) -> bool`, `require_current_material_review_contract(state: dict[str, Any]) -> None`, `validate_coverage_plan(raw: object, *, run_dir: Path, state: dict[str, Any]) -> dict[str, Any]`, `required_lenses_for_assessments(assessments: list[dict[str, Any]]) -> set[str]`, `command_record_coverage(args: argparse.Namespace) -> int`, `load_recorded_coverage_plan(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]`, `coverage-plan.json`, and `state.hashes.coverage_plan_hash`.

- [ ] **Step 1: Add failing coverage-plan fixtures and tests**

Add a helper that always supplies both assessments and allows targeted mutations:

```python
def coverage_plan(
    self,
    scope_hash: str,
    *,
    output_paths_present: bool = True,
    persisted_config_present: bool = True,
    omit_lens: str | None = None,
) -> dict:
    assessments = [
        {
            "code": "user_selectable_output_paths",
            "present": output_paths_present,
            "rationale": "Configurable generated and report destinations were checked.",
            "evidence_paths": ["calc.py"] if output_paths_present else [],
        },
        {
            "code": "persisted_config_semantics",
            "present": persisted_config_present,
            "rationale": "Optional durable configuration semantics were checked.",
            "evidence_paths": ["calc.py"] if persisted_config_present else [],
        },
    ]
    assignments = (
        "correctness",
        "test_adequacy",
        "standards_alignment",
        "reliability",
        "migration_data_safety",
        "api_config_compatibility",
    )
    return {
        "schema_version": "material-review/coverage-plan/v1",
        "scope_hash": scope_hash,
        "workflow_profile": "material_review",
        "risk_assessments": assessments,
        "lenses": [
            {
                "lens_id": lens_id,
                "required": True,
                "reviewer_id": "shared-reviewer" if lens_id in {"migration_data_safety", "api_config_compatibility"} else lens_id,
                "independence_group": "model-a",
                "review_mode": "subagent",
            }
            for lens_id in assignments
            if lens_id != omit_lens
        ],
    }
```

Add tests with these exact behavioral assertions:

```python
def test_coverage_plan_records_exhaustive_risk_assessments(self) -> None:
    scope_hash = self.init()
    path = self.write_json("coverage-input.json", self.coverage_plan(scope_hash))
    self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path))
    state = self.load("state.json")
    artifact = self.load("coverage-plan.json")
    self.assertEqual(state["phase"], "CONTEXT_FROZEN")
    self.assertEqual(state["hashes"]["coverage_plan_hash"], artifact["coverage_plan_hash"])
    self.assertEqual({item["code"] for item in artifact["risk_assessments"]}, {
        "user_selectable_output_paths", "persisted_config_semantics",
    })

def test_coverage_plan_requires_each_positive_risk_lens(self) -> None:
    scope_hash = self.init()
    for missing in ("reliability", "migration_data_safety", "api_config_compatibility"):
        path = self.write_json(f"missing-{missing}.json", self.coverage_plan(scope_hash, omit_lens=missing))
        _, stderr = self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path), expected=2)
        self.assertIn(f"requires {missing}", stderr)

def test_coverage_plan_allows_repeated_reviewer_identity(self) -> None:
    scope_hash = self.init()
    path = self.write_json("shared-reviewer.json", self.coverage_plan(scope_hash))
    self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path))

def test_coverage_plan_is_idempotent_but_not_replaceable(self) -> None:
    scope_hash = self.init()
    original = self.coverage_plan(scope_hash)
    path = self.write_json("coverage.json", original)
    self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path))
    event_count = len(self.load("state.json")["events"])
    self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(path))
    self.assertEqual(len(self.load("state.json")["events"]), event_count)
    original["risk_assessments"][0]["rationale"] = "Replacement attempt."
    replacement = self.write_json("replacement.json", original)
    _, stderr = self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(replacement), expected=2)
    self.assertIn("Coverage plan is already recorded", stderr)
```

Also add separate tests that reject: a missing or duplicate assessment code; a false assessment with non-empty paths; a true assessment with no paths; an evidence path outside `all_scope_paths`; an extra top-level or nested field; duplicate lens IDs; a core/mapped lens with `required=false`; an unsupported review mode; a stale scope hash; and a pre-contract state attempting `record-coverage`.

In `test_simplifyctl.py`, add this prerequisite regression so material-review fields cannot leak into delegated simplification initialization:

```python
def test_change_scope_init_records_trusted_simplification_profile(self) -> None:
    (self.repo / "src" / "service.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    self.run_tool("init", "--repo-root", str(self.repo), "--run-id", self.run_id, "--scope", "uncommitted")
    state = self.load("state.json")
    self.assertEqual(state["profile"], "material-code-simplification")
    self.assertNotIn("coverage_required", state)
    self.assertNotIn("workflow_profile", state)
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
rtk python3 -B skills/material-code-review/tests/test_reviewctl.py -v
rtk python3 -B skills/material-code-simplification/tests/test_simplifyctl.py -v
```

Expected: new tests fail because the schema, trusted delegated profile, state profile, `record-coverage`, and runtime validation do not exist.

- [ ] **Step 3: Create the fail-closed public schema**

Create `coverage-plan.schema.json` with `additionalProperties: false` at every object boundary. Use exactly:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "material-review/coverage-plan/v1",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "scope_hash", "workflow_profile", "risk_assessments", "lenses"],
  "properties": {
    "schema_version": {"const": "material-review/coverage-plan/v1"},
    "scope_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "workflow_profile": {"const": "material_review"},
    "risk_assessments": {
      "type": "array", "minItems": 2, "maxItems": 2,
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["code", "present", "rationale", "evidence_paths"],
        "properties": {
          "code": {"enum": ["user_selectable_output_paths", "persisted_config_semantics"]},
          "present": {"type": "boolean"},
          "rationale": {"type": "string", "minLength": 1},
          "evidence_paths": {"type": "array", "uniqueItems": true, "items": {"type": "string", "minLength": 1}}
        },
        "allOf": [{"if": {"properties": {"present": {"const": true}}}, "then": {"properties": {"evidence_paths": {"minItems": 1}}}, "else": {"properties": {"evidence_paths": {"maxItems": 0}}}}]
      }
    },
    "lenses": {
      "type": "array", "minItems": 3,
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["lens_id", "required", "reviewer_id", "independence_group", "review_mode"],
        "properties": {
          "lens_id": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
          "required": {"type": "boolean"},
          "reviewer_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$"},
          "independence_group": {"type": "string", "minLength": 1},
          "review_mode": {"enum": ["subagent", "controller", "external"]}
        }
      }
    }
  }
}
```

- [ ] **Step 4: Implement runtime validation, state fields, and immutable recording**

Add controlled constants:

```python
COVERAGE_PLAN_SCHEMA = "material-review/coverage-plan/v1"
WORKFLOW_PROFILE_REVIEW = "material_review"
SIMPLIFICATION_PROFILE = "material-code-simplification"
RISK_ASSESSMENT_CODES = frozenset({"user_selectable_output_paths", "persisted_config_semantics"})
CORE_REVIEW_LENSES = frozenset({"correctness", "test_adequacy", "standards_alignment"})
REQUIRED_LENSES_BY_RISK = {
    "user_selectable_output_paths": frozenset({"reliability"}),
    "persisted_config_semantics": frozenset({"migration_data_safety", "api_config_compatibility"}),
}
```

Implement manual validation using `require_object`, `require_exact_keys`, `require_array`, `require_bool`, `require_string`, `require_sha256`, and `normalize_repo_path`. Load the verified scope and require every assessment path in `all_scope_paths(scope["identity"])`. Require the assessment-code set to equal `RISK_ASSESSMENT_CODES`; require unique lens IDs but allow repeated reviewer IDs. Require every core and positive-risk lens to exist with `required is True`.

First make the core initializer profile trusted and internal:

```python
def main(
    argv: Sequence[str] | None = None,
    *,
    workflow_profile: str = WORKFLOW_PROFILE_REVIEW,
) -> int:
```

Validate the internal value against `{WORKFLOW_PROFILE_REVIEW, SIMPLIFICATION_PROFILE}` and attach it to parsed init arguments as a private attribute. In `simplifyctl.main`, delegate non-codebase scopes with:

```python
return int(core.main(values, workflow_profile=PROFILE_NAME))
```

Do not add a public `--workflow-profile` option. The direct `reviewctl.py` CLI always initializes material review. Then add these fields only for `WORKFLOW_PROFILE_REVIEW`:

```python
"workflow_profile": WORKFLOW_PROFILE_REVIEW,
"coverage_required": True,
```

For `SIMPLIFICATION_PROFILE`, add only `"profile": SIMPLIFICATION_PROFILE` to state. Preserve the existing codebase initializer's authoritative profile behavior.

Add the profile helpers before commands use them:

```python
def is_simplification_state(state: dict[str, Any]) -> bool:
    return state.get("profile") == SIMPLIFICATION_PROFILE

def require_current_material_review_contract(state: dict[str, Any]) -> None:
    if is_simplification_state(state):
        raise ReviewError("Material-review coverage is not used for material simplification")
    if state.get("coverage_required") is not True or state.get("workflow_profile") != WORKFLOW_PROFILE_REVIEW:
        raise ReviewError("Run predates required coverage; start a new run.")
```

Implement immutable recording:

```python
def command_record_coverage(args: argparse.Namespace) -> int:
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if state["phase"] != PHASE_CONTEXT:
        raise ReviewError(f"Cannot record coverage in phase {state['phase']}")
    require_current_material_review_contract(state)
    check_scope_fresh(repo, run_dir, state)
    plan = validate_coverage_plan(load_json(Path(args.input).expanduser().resolve()), run_dir=run_dir, state=state)
    plan_hash = canonical_hash(plan)
    existing_hash = state["hashes"].get("coverage_plan_hash")
    if existing_hash:
        existing = load_recorded_coverage_plan(run_dir, state)
        if existing_hash == plan_hash and canonical_hash(existing) == plan_hash:
            print(f"[OK] Coverage plan already recorded: {plan_hash}")
            return 0
        raise ReviewError("Coverage plan is already recorded; start a new run to change it")
    if (run_dir / "coverage-plan.json").exists():
        raise ReviewError("Coverage plan artifact exists without a valid state binding; start a new run")
    artifact = {**plan, "coverage_plan_hash": plan_hash}
    atomic_write_json(run_dir / "coverage-plan.json", artifact)
    state["hashes"]["coverage_plan_hash"] = plan_hash
    state["events"].append({"at": utc_now(), "event": "coverage_plan_recorded", "coverage_plan_hash": plan_hash})
    save_state(run_dir, state)
    print(f"[OK] Coverage plan recorded: {plan_hash}")
    return 0
```

`load_recorded_coverage_plan` must strip only `coverage_plan_hash`, recompute and compare the canonical hash with both embedded and state hashes, then call `validate_coverage_plan` again. Add `record-coverage --repo-root --artifact-root --run-id --input` following existing parser conventions.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
rtk python3 -B skills/material-code-review/tests/test_reviewctl.py -v
rtk python3 -B skills/material-code-simplification/tests/test_simplifyctl.py -v
```

Expected: every controller and simplification test passes; delegated simplification state has its profile and no material-review coverage fields; no generated cache or product file remains.

- [ ] **Step 6: Commit the coverage foundation**

```bash
rtk git add skills/material-code-review/schemas/coverage-plan.schema.json skills/material-code-review/scripts/reviewctl.py skills/material-code-review/tests/test_reviewctl.py skills/material-code-simplification/scripts/simplifyctl.py skills/material-code-simplification/tests/test_simplifyctl.py
rtk git commit -m "feat: record immutable review coverage"
```

---

### Task 2: Bind Candidate Waves to Plans, Lenses, and Risk Paths

**Files:**

- Create: `skills/material-code-review/schemas/candidate-set-v2.schema.json`
- Modify: `skills/material-code-review/scripts/reviewctl.py`
- Modify: `skills/material-code-review/tests/test_reviewctl.py`
- Inspect: `skills/material-code-review/schemas/candidate-set.schema.json`

**Interfaces:**

- Consumes: verified coverage plan, material-review candidate-set/v2 inputs, and simplification candidate-set/v1 inputs.
- Produces: `validate_candidate_wave_against_coverage(plan: dict[str, Any], candidate_sets: list[dict[str, Any]]) -> None`, `required_paths_by_lens(plan: dict[str, Any]) -> dict[str, set[str]]`, authoritative normalized candidates with `coverage_plan_hash`, and non-authoritative `candidate-ingestion-failure.json` diagnostics.

- [ ] **Step 1: Add failing v2 and atomic-wave tests**

Add `empty_candidate_set_v2`:

```python
def empty_candidate_set_v2(self, scope_hash: str, coverage_hash: str, assignment: dict) -> dict:
    return {
        "schema_version": "material-review/candidate-set/v2",
        "scope_hash": scope_hash,
        "coverage_plan_hash": coverage_hash,
        "lens_id": assignment["lens_id"],
        "reviewer_id": assignment["reviewer_id"],
        "independence_group": assignment["independence_group"],
        "review_mode": assignment["review_mode"],
        "findings": [],
        "coverage": {"files_reviewed": ["calc.py"], "areas": [assignment["lens_id"]], "limitations": []},
    }
```

Add complete-wave helpers:

```python
def init_with_recorded_coverage(self) -> str:
    scope_hash = self.init()
    plan_path = self.write_json("coverage-input.json", self.coverage_plan(scope_hash))
    self.run_tool("record-coverage", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(plan_path))
    return scope_hash

def candidate_paths_for_coverage(
    self,
    scope_hash: str,
    *,
    primary_candidate: dict | None = None,
    omit_lens: str | None = None,
) -> list[Path]:
    plan = self.load("coverage-plan.json")
    coverage_hash = plan["coverage_plan_hash"]
    paths: list[Path] = []
    for assignment in plan["lenses"]:
        lens_id = assignment["lens_id"]
        if lens_id == omit_lens:
            continue
        if lens_id == "correctness":
            payload = primary_candidate or self.candidate_set(scope_hash)
            payload["schema_version"] = "material-review/candidate-set/v2"
            payload["coverage_plan_hash"] = coverage_hash
            payload["lens_id"] = lens_id
            payload["reviewer_id"] = assignment["reviewer_id"]
            payload["independence_group"] = assignment["independence_group"]
            payload["review_mode"] = assignment["review_mode"]
        else:
            payload = self.empty_candidate_set_v2(scope_hash, coverage_hash, assignment)
        paths.append(self.write_json(f"candidate-{lens_id}.json", payload))
    return paths

def ingest_candidate_paths(self, paths: list[Path], *, expected: int = 0) -> tuple[str, str]:
    input_args = [value for path in paths for value in ("--input", str(path))]
    return self.run_tool("ingest-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id, *input_args, expected=expected)
```

Add exact tests for:

```python
def test_ingest_refuses_missing_required_lens_without_authoritative_artifacts(self) -> None:
    scope_hash = self.init_with_recorded_coverage()
    paths = self.candidate_paths_for_coverage(scope_hash, omit_lens="migration_data_safety")
    _, stderr = self.ingest_candidate_paths(paths, expected=2)
    self.assertIn("Missing required review coverage: migration_data_safety", stderr)
    self.assertEqual(self.load("state.json")["phase"], "CONTEXT_FROZEN")
    self.assertFalse((self.run_dir / "candidates.json").exists())
    self.assertTrue((self.run_dir / "candidate-ingestion-failure.json").exists())

def test_ingest_refuses_stale_plan_hash_and_wrong_lens(self) -> None:
    scope_hash = self.init_with_recorded_coverage()
    paths = self.candidate_paths_for_coverage(scope_hash)
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    payload["coverage_plan_hash"] = "0" * 64
    paths[0].write_text(json.dumps(payload), encoding="utf-8")
    _, stderr = self.ingest_candidate_paths(paths, expected=2)
    self.assertIn("coverage_plan_hash does not match", stderr)

def test_required_lens_must_cover_risk_evidence_paths(self) -> None:
    scope_hash = self.init_with_recorded_coverage()
    paths = self.candidate_paths_for_coverage(scope_hash)
    migration = next(path for path in paths if "migration_data_safety" in path.name)
    payload = json.loads(migration.read_text(encoding="utf-8"))
    payload["coverage"]["files_reviewed"] = ["test_calc.py"]
    migration.write_text(json.dumps(payload), encoding="utf-8")
    _, stderr = self.ingest_candidate_paths(paths, expected=2)
    self.assertIn("did not review required risk paths: calc.py", stderr)

def test_complete_wave_binds_coverage_hash_and_retry_succeeds(self) -> None:
    scope_hash = self.init_with_recorded_coverage()
    incomplete = self.candidate_paths_for_coverage(scope_hash, omit_lens="reliability")
    self.ingest_candidate_paths(incomplete, expected=2)
    complete = self.candidate_paths_for_coverage(scope_hash)
    self.ingest_candidate_paths(complete)
    state = self.load("state.json")
    candidates = self.load("candidates.json")
    self.assertEqual(candidates["coverage_plan_hash"], state["hashes"]["coverage_plan_hash"])
    self.assertEqual(state["phase"], "CANDIDATES_CAPTURED")
```

Also test duplicate lens completion, unassigned lens, reviewer/group/mode mismatch, out-of-scope `files_reviewed`, v1 rejection for new material review, partial-invalid v2 finding rejection of the whole wave, tampered/deleted coverage plan before ingestion, invalid retry after a prior valid bundle not replacing it, and ledger compilation rejecting coverage deletion/tampering/stale candidate coverage.

- [ ] **Step 2: Run the focused suite and verify RED**

```bash
rtk python3 -B skills/material-code-review/tests/test_reviewctl.py -v
```

Expected: new v2 and coverage-wave tests fail while existing tests remain at their baseline behavior.

- [ ] **Step 3: Create candidate-set/v2 without altering v1**

Create `candidate-set-v2.schema.json` as a versioned copy of the existing candidate schema with these exact top-level differences:

```json
{
  "$id": "material-review/candidate-set/v2",
  "required": [
    "schema_version", "scope_hash", "coverage_plan_hash", "lens_id",
    "reviewer_id", "independence_group", "review_mode", "findings", "coverage"
  ],
  "properties": {
    "schema_version": {"const": "material-review/candidate-set/v2"},
    "scope_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "coverage_plan_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "lens_id": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"}
  }
}
```

Retain every existing v1 `reviewer_id`, `independence_group`, `review_mode`, `findings`, `coverage`, finding-property, enum, and conditional definition unchanged in the v2 file. Do not edit `candidate-set.schema.json`; it remains the simplification v1 contract.

- [ ] **Step 4: Implement profile-selected candidate validation**

Refactor `validate_candidate_set` to select exact top-level keys from the trusted state profile. For material review, require v2 and normalize `coverage_plan_hash` plus `lens_id`. For simplification, preserve the v1 top-level shape and existing partial-finding rejection behavior.

For material-review v2 only:

- reject the entire set when any finding fails validation;
- require every `coverage.files_reviewed` path in `all_scope_paths`;
- preserve `lens_id` and `coverage_plan_hash` in the normalized reviewer set.

Implement:

```python
def required_paths_by_lens(plan: dict[str, Any]) -> dict[str, set[str]]:
    required: dict[str, set[str]] = {item["lens_id"]: set() for item in plan["lenses"]}
    for assessment in plan["risk_assessments"]:
        if not assessment["present"]:
            continue
        for lens_id in REQUIRED_LENSES_BY_RISK[assessment["code"]]:
            required[lens_id].update(assessment["evidence_paths"])
    return required

def validate_candidate_wave_against_coverage(plan: dict[str, Any], candidate_sets: list[dict[str, Any]]) -> None:
    assignments = {item["lens_id"]: item for item in plan["lenses"]}
    required_paths = required_paths_by_lens(plan)
    seen: set[str] = set()
    for candidate_set in candidate_sets:
        lens_id = candidate_set["lens_id"]
        if lens_id in seen:
            raise ReviewError(f"Duplicate candidate lens_id: {lens_id}")
        seen.add(lens_id)
        assignment = assignments.get(lens_id)
        if assignment is None:
            raise ReviewError(f"Lens is absent from coverage plan: {lens_id}")
        actual = (candidate_set["reviewer_id"], candidate_set["independence_group"], candidate_set["review_mode"])
        expected = (assignment["reviewer_id"], assignment["independence_group"], assignment["review_mode"])
        if actual != expected:
            raise ReviewError(f"candidate identity does not match coverage assignment: {lens_id}")
        missing_paths = required_paths[lens_id] - set(candidate_set["coverage"]["files_reviewed"])
        if missing_paths:
            raise ReviewError(f"{lens_id} did not review required risk paths: " + ", ".join(sorted(missing_paths)))
    missing = sorted(item["lens_id"] for item in plan["lenses"] if item["required"] and item["lens_id"] not in seen)
    if missing:
        raise ReviewError("Missing required review coverage: " + ", ".join(missing))
```

- [ ] **Step 5: Make material-review ingestion atomic and coverage-bound**

Load and verify the recorded plan before validating inputs. Validate every input into memory. If any v2 input or finding is invalid, or the wave check fails, write only this diagnostic and raise:

```python
failure = {
    "schema_version": "material-review/candidate-ingestion-failure/v1",
    "scope_hash": state["scope_hash"],
    "coverage_plan_hash": state["hashes"]["coverage_plan_hash"],
    "input_hashes": [sha256_file(Path(raw).expanduser().resolve()) for raw in args.input],
    "rejections": rejections,
}
atomic_write_json(run_dir / "candidate-ingestion-failure.json", failure)
```

Do not create or replace `candidates.json`, `candidates.md`, `candidate-rejections.json`, state phase, or state candidate hash on material-review failure. Preserve existing v1 simplification ingestion semantics.

On material-review success, add `coverage_plan_hash` to the normalized payload before computing `candidate_bundle_hash`. In `command_compile_ledger`, call `load_recorded_coverage_plan` and require the candidate bundle's coverage hash to equal the verified plan/state hash before adjudication validation.

Update every successful material-review ingestion fixture to record coverage and submit the complete v2 wave. Keep correctness findings and expected normalized candidate ordering unchanged by using `lens_id="correctness"` for the primary set. Do not change simplification fixtures in this task.

- [ ] **Step 6: Run material-review tests and verify GREEN**

```bash
rtk python3 -B skills/material-code-review/tests/test_reviewctl.py -v
```

Expected: all controller tests pass, including complete retry and no-authoritative-write failure assertions.

- [ ] **Step 7: Commit candidate-wave enforcement**

```bash
rtk git add skills/material-code-review/schemas/candidate-set-v2.schema.json skills/material-code-review/scripts/reviewctl.py skills/material-code-review/tests/test_reviewctl.py
rtk git commit -m "feat: bind reviewer waves to coverage"
```

---

### Task 3: Block Legacy Progress and Verify Simplification Lifecycles

**Files:**

- Modify: `skills/material-code-review/scripts/reviewctl.py`
- Modify: `skills/material-code-review/tests/test_reviewctl.py`
- Modify: `skills/material-code-simplification/tests/test_simplifyctl.py`

**Interfaces:**

- Consumes: parsed controller command and Task 1's trusted state profile.
- Produces: `enforce_command_compatibility(args: argparse.Namespace) -> None`, lifecycle-wide legacy blocking, safe restoration exceptions, and complete v1 simplification regression coverage.

- [ ] **Step 1: Add phase-spanning legacy compatibility tests**

Add a helper that removes the new discriminator fields from a material-review state:

```python
def make_run_legacy(self) -> None:
    state = self.load("state.json")
    state.pop("coverage_required", None)
    state.pop("workflow_profile", None)
    (self.run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

def reach_plan_approved(self) -> None:
    self.approve_and_plan()

def reach_fixing(self) -> None:
    self.approve_and_plan()
    self.run_tool("begin-fix", "--repo-root", str(self.repo), "--run-id", self.run_id)
```

Add representative tests:

```python
def test_legacy_context_run_cannot_record_coverage_or_ingest(self) -> None:
    scope_hash = self.init()
    self.make_run_legacy()
    plan = self.write_json("legacy-plan.json", self.coverage_plan(scope_hash))
    for command in (
        ("record-coverage", "--input", str(plan)),
        ("ingest-candidates", "--input", str(self.write_json("legacy-candidate.json", self.candidate_set(scope_hash)))),
    ):
        _, stderr = self.run_tool(command[0], "--repo-root", str(self.repo), "--run-id", self.run_id, *command[1:], expected=2)
        self.assertIn("Run predates required coverage; start a new run.", stderr)

def test_legacy_adjudicated_run_cannot_advance_gate_a(self) -> None:
    self.reach_adjudicated()
    self.make_run_legacy()
    _, stderr = self.run_tool("gate-findings", "--repo-root", str(self.repo), "--run-id", self.run_id, "--approve", "F001", "--user-statement", "Attempt legacy approval.", expected=2)
    self.assertIn("Run predates required coverage; start a new run.", stderr)
    self.assertEqual(self.load("state.json")["phase"], "ADJUDICATED")

def test_legacy_plan_approved_run_cannot_begin_fix(self) -> None:
    self.reach_plan_approved()
    self.make_run_legacy()
    _, stderr = self.run_tool("begin-fix", "--repo-root", str(self.repo), "--run-id", self.run_id, expected=2)
    self.assertIn("Run predates required coverage; start a new run.", stderr)
    self.assertFalse((self.run_dir / "checkpoints" / "pre-fix").exists())

def test_legacy_fixing_run_can_abort_and_restore(self) -> None:
    self.reach_fixing()
    original = (self.repo / "calc.py").read_text(encoding="utf-8")
    (self.repo / "calc.py").write_text("def add(a, b):\n    return 999\n", encoding="utf-8")
    self.make_run_legacy()
    self.run_tool("abort-fixes", "--repo-root", str(self.repo), "--run-id", self.run_id, "--reason", "Retire legacy run safely.")
    self.assertEqual((self.repo / "calc.py").read_text(encoding="utf-8"), original)
    self.assertEqual(self.load("state.json")["phase"], "ABORTED")
```

Also assert `status`, `check-scope`, and an applicable active `rollback-finding` remain available; `validate-plan`, `gate-plan`, `start-finding`, `run-test`, `finish-finding`, `run-global-test`, `prepare-verification`, `record-verification`, and `begin-repair` are rejected before their command bodies can change state or workspace.

- [ ] **Step 2: Add failing simplification lifecycle and ambiguous-legacy tests**

Mechanically extract the current `test_codebase_scope_completes_full_gated_repair_lifecycle` into `complete_full_gated_repair_lifecycle(self, *init_arguments: str) -> dict`: replace only its `self.init_src("--exclude-untracked")` statement with the `self.run_tool("init", ...)` call below; retain its existing candidate, adjudication, Gate A/B, repair, verification payloads, and assertions byte-for-byte; then add the three final coverage/profile assertions and return.

```python
self.run_tool("init", "--repo-root", str(self.repo), "--run-id", self.run_id, *init_arguments)
state = self.load("state.json")
self.assertEqual(state["phase"], "COMPLETE")
self.assertNotIn("coverage_plan_hash", state["hashes"])
self.assertFalse((self.run_dir / "coverage-plan.json").exists())
return state
```

Replace the original test with these wrappers:

```python

def test_codebase_scope_completes_full_gated_repair_lifecycle(self) -> None:
    state = self.complete_full_gated_repair_lifecycle(
        "--scope", "codebase", "--path", "src", "--exclude-untracked"
    )
    self.assertEqual(self.load("scope.json")["identity"]["actual_scope"], "codebase")
    self.assertEqual(state["profile"], "material-code-simplification")

def test_change_scope_completes_full_gated_repair_lifecycle(self) -> None:
    (self.repo / "src" / "service.py").write_text(
        "def value():\n    return 1\n# selected uncommitted change\n", encoding="utf-8"
    )
    state = self.complete_full_gated_repair_lifecycle("--scope", "uncommitted")
    self.assertEqual(self.load("scope.json")["identity"]["actual_scope"], "uncommitted")
    self.assertEqual(state["profile"], "material-code-simplification")
```

The comment in the change-scope fixture makes `src/service.py` part of the frozen uncommitted scope while retaining the existing comparison-side `return 1` evidence used by the lifecycle payload.

Add a compatibility test for an unprofiled delegated legacy state: a forward command returns the exact restart error. Keep the existing profiled codebase legacy fixture exempt.

- [ ] **Step 3: Run both focused suites and verify RED**

```bash
rtk python3 -B skills/material-code-review/tests/test_reviewctl.py -v
rtk python3 -B skills/material-code-simplification/tests/test_simplifyctl.py -v
```

Expected: later-phase legacy commands still advance; the new full delegated simplification lifecycle remains green because Task 1 already supplies the trusted profile.

- [ ] **Step 4: Add one centralized compatibility guard**

Implement:

```python
LEGACY_ALLOWED_COMMANDS = frozenset({"status", "check-scope", "rollback-finding", "abort-fixes"})

def enforce_command_compatibility(args: argparse.Namespace) -> None:
    if args.command == "init":
        return
    repo = resolve_repo_root(args.repo_root)
    _, run_dir = resolve_run_dir(args, repo)
    state = load_state(run_dir)
    if is_simplification_state(state):
        return
    if state.get("coverage_required") is True and state.get("workflow_profile") == WORKFLOW_PROFILE_REVIEW:
        return
    if args.command not in LEGACY_ALLOWED_COMMANDS:
        raise ReviewError("Run predates required coverage; start a new run.")
```

Call `enforce_command_compatibility(args)` in `main` after empty argument normalization and before `args.func(args)`. Retain command-local coverage checks in ingestion and compilation as defense in depth. Do not bypass the existing phase and checkpoint rules for the allowed restoration commands.

- [ ] **Step 5: Run both focused suites and verify GREEN**

```bash
rtk python3 -B skills/material-code-review/tests/test_reviewctl.py -v
rtk python3 -B skills/material-code-simplification/tests/test_simplifyctl.py -v
```

Expected: all material-review and simplification tests pass; delegated simplification completes with v1 and no coverage plan; legacy restoration works without legacy progression.

- [ ] **Step 6: Commit compatibility and profile isolation**

```bash
rtk git add skills/material-code-review/scripts/reviewctl.py skills/material-code-review/tests/test_reviewctl.py skills/material-code-simplification/tests/test_simplifyctl.py
rtk git commit -m "fix: isolate coverage by workflow profile"
```

---

### Task 4: Add Targeted Discovery and Strict-Guard Judgment Contracts

**Files:**

- Create: `skills/material-code-review/references/reliability-output-integrity-lens.md`
- Create: `skills/material-code-review/references/persisted-config-migration-lens.md`
- Create: `skills/material-code-review/tests/test_discovery_contract.py`
- Modify: `skills/material-code-review/SKILL.md`
- Modify: `skills/material-code-review/references/context-checklist.md`
- Modify: `skills/material-code-review/references/reviewer-template.md`
- Modify: `skills/material-code-review/references/materiality-rubric.md`
- Modify: `skills/material-code-review/references/adjudicator-template.md`
- Modify: `skills/material-code-review/references/workflow.md`
- Modify: `skills/material-code-review/references/failure-model.md`

**Interfaces:**

- Consumes: coverage-plan/v1 assessments and candidate-set/v2 assignment fields from Tasks 1–3.
- Produces: canonical signal-selection rules, reviewer lens procedures, complete-wave workflow, and three-way strict-guard disposition guidance.

- [ ] **Step 1: Write failing controlled-contract tests**

Create `test_discovery_contract.py` with:

```python
from __future__ import annotations

import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]


class DiscoveryContractTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (SKILL_DIR / relative).read_text(encoding="utf-8")

    def test_skill_requires_exhaustive_coverage_before_dispatch(self) -> None:
        text = self.read("SKILL.md")
        for marker in (
            "risk_assessments", "user_selectable_output_paths", "persisted_config_semantics",
            "record-coverage", "material-review/candidate-set/v2", "Missing required review coverage",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_targeted_lenses_define_causal_checks(self) -> None:
        reliability = self.read("references/reliability-output-integrity-lens.md")
        migration = self.read("references/persisted-config-migration-lens.md")
        for marker in ("pairwise resolved-destination aliasing", "success- and failure-path write ordering", "platform-specific path aliases"):
            self.assertIn(marker, reliability)
        for marker in ("new-file default", "missing-key fallback", "explicit empty value", "external target identity"):
            self.assertIn(marker, migration)

    def test_strict_guard_rule_preserves_high_impact_uncertainty(self) -> None:
        skill = self.read("SKILL.md")
        adjudicator = self.read("references/adjudicator-template.md")
        for text in (skill, adjudicator):
            self.assertIn("A stricter guard is a defect only with affirmative supported-state evidence.", text)
            self.assertIn("CONSEQUENCE_UNSUPPORTED", text)
            self.assertIn('nature="risk"', text)
            self.assertIn("do not authorize relaxing the guard", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new suite and verify RED**

```bash
rtk python3 -B skills/material-code-review/tests/test_discovery_contract.py -v
```

Expected: missing files and controlled wording fail.

- [ ] **Step 3: Create the reliability/output-integrity lens**

Create these normative sections:

```markdown
# Reliability and output-integrity lens

Use only when the verified root-owned coverage plan assigns `reliability` for a present `user_selectable_output_paths` assessment.

## Destination inventory

Enumerate authoritative outputs, metadata, splits, reports, debug logs, temporary files, cleanup targets, and publisher artifacts. Trace defaults and every user-selectable override on success and failure paths.

## Alias, ownership, and ordering checks

Check pairwise resolved-destination aliasing; relative, symlink-mediated, case-folded, Unicode-normalized, and relevant platform-specific path aliases; parent/child ownership overlap; success- and failure-path write ordering; and auxiliary or cleanup writes after authoritative writes. A successful command that can overwrite its own authoritative artifact is a material reliability defect.

## Counterevidence

Check early path validation, atomic replacement semantics, no-follow behavior, ownership metadata, guarded cleanup, write ordering, and causal custom-path tests. Do not report a collision that the existing boundary rejects before authoritative mutation.
```

- [ ] **Step 4: Create the persisted-config migration lens**

```markdown
# Persisted-configuration migration lens

Use only when the verified root-owned coverage plan assigns `migration_data_safety` or `api_config_compatibility` for a present `persisted_config_semantics` assessment.

## Compatibility matrix

Compare baseline and comparison behavior for a new-file default, a missing-key fallback, an explicit empty value, an explicit legacy value, and an explicit custom value.

## Downstream identity

Trace every semantic difference through serialization, durable local output, external target identity, remote mutation, and user-visible migration behavior. A previously accepted missing-key payload must not silently select a different external target without explicit migration authority.

## Counterevidence

Check schema requirements, version gates, migration documentation, creation-time normalization, baseline fixtures, and whether older writers always persisted the field. State residual compatibility exposure precisely.
```

- [ ] **Step 5: Update canonical selection, reviewer, workflow, and failure contracts**

In `SKILL.md`, after context freeze and before dispatch:

- require exactly one positive/negative assessment for each controlled code;
- define the trigger semantics from the approved design;
- record the immutable plan;
- give each reviewer the verified plan hash, exact lens ID, frozen source bundle, and risk evidence paths;
- require candidate-set/v2 for material review; and
- refuse synthesis, ingestion, and any verdict until the complete valid wave exists.

In `context-checklist.md`, add a table with code, positive trigger, required lenses, and non-trigger evidence. In `reviewer-template.md`, require the exact plan hash/lens ID and prohibit unassigned lens references. State that reviewer identity and independence group must describe the actual process rather than personas.

In `workflow.md`, use exact order:

```text
init -> context record -> record-coverage -> dispatch assigned lenses ->
ingest complete candidate wave -> validate -> repair-direction audit ->
compile-ledger -> Gate A -> validate plan -> Gate B
```

In `failure-model.md`, add immutable-plan, missing/duplicate/stale/wrong-lens, risk-path-incomplete, non-authoritative diagnostic, retry, legacy restart, and safe-restoration outcomes. Do not change Gate A/B or repair failure behavior.

- [ ] **Step 6: Add strict-validation precedence without weakening high-impact uncertainty**

Add this controlled paragraph to `SKILL.md` and `adjudicator-template.md`:

```markdown
A stricter guard is a defect only with affirmative supported-state evidence. Sufficient authority includes an explicit requirement or user promise, an accepted schema state, a causal test, or baseline behavior shown to be an accepted or relied-upon compatibility state. Mere historical acceptance or the fact that a guard blocks an input is not enough when intentional fail-closed validation remains plausible. Discard an unsupported medium/low claim as `CONSEQUENCE_UNSUPPORTED`. When the consequence is plausibly blocker/high but support status is genuinely unknown, retain it only as `nature="risk"`, require a user decision and exact pre-fix verification, and do not authorize relaxing the guard until support is established and the plan is revalidated.
```

Add a shorter operational restatement under defect materiality in `materiality-rubric.md`. Do not change `adjudication.schema.json`; `risk`, high-impact uncertainty, and `CONSEQUENCE_UNSUPPORTED` already exist.

- [ ] **Step 7: Run discovery and controller tests**

```bash
rtk python3 -B skills/material-code-review/tests/test_discovery_contract.py -v
rtk python3 -B skills/material-code-review/tests/test_reviewctl.py -v
```

Expected: all tests pass; controlled prose matches controller behavior.

- [ ] **Step 8: Commit the canonical discovery contract**

```bash
rtk git add skills/material-code-review/SKILL.md skills/material-code-review/references/context-checklist.md skills/material-code-review/references/reviewer-template.md skills/material-code-review/references/materiality-rubric.md skills/material-code-review/references/adjudicator-template.md skills/material-code-review/references/workflow.md skills/material-code-review/references/failure-model.md skills/material-code-review/references/reliability-output-integrity-lens.md skills/material-code-review/references/persisted-config-migration-lens.md skills/material-code-review/tests/test_discovery_contract.py
rtk git commit -m "feat: target review recall and precision"
```

---

### Task 5: Align Packaging, Versions, and User Documentation

**Files:**

- Modify: `skills/material-code-review/scripts/validate_package.py`
- Modify: `skills/material-code-simplification/scripts/validate_package.py`
- Modify: `scripts/validate_package.py`
- Modify: `scripts/package_plugin.py`
- Modify: `scripts/package_simplification_skill.py`
- Modify: `scripts/tests/test_packaging.py`
- Modify: `.codex-plugin/plugin.json`
- Modify: `.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`
- Modify: `Makefile`
- Modify: `skills/material-code-review/scripts/reviewctl.py`
- Modify: `skills/material-code-simplification/scripts/simplifyctl.py`
- Modify: `README.md`
- Modify: `CODEX.md`
- Modify: `CHANGELOG.md`
- Modify: `EVALUATION.md`

**Interfaces:**

- Consumes: new schemas, references, controller behavior, and approved compatibility policy.
- Produces: coherent source validation and full plugin, standalone review, and standalone simplification distributions at versions `1.3.0`, `1.3.0`, and `1.2.0` respectively.

- [ ] **Step 1: Write failing packaging and version assertions**

Extend the full packager helper exactly:

```python
def run_full_packager(
    self,
    fixture_root: Path,
    output: Path,
    *,
    standalone_output: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    packager = fixture_root / FULL_PACKAGER.relative_to(REPOSITORY_ROOT)
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(packager),
            "--package-root",
            str(fixture_root),
            "--output",
            str(output),
            "--standalone-output",
            "" if standalone_output is None else str(standalone_output),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
```

Add:

```python
def test_review_archives_ship_targeted_coverage_contract(self) -> None:
    with tempfile.TemporaryDirectory() as temp_directory:
        temp_root = Path(temp_directory)
        fixture_root = self.create_full_plugin_fixture(temp_root)
        full_output = temp_root / "full-plugin.zip"
        standalone_output = temp_root / "material-review.zip"
        result = self.run_full_packager(fixture_root, full_output, standalone_output=standalone_output)
        self.assertEqual(result.returncode, 0, result.stderr)
        full_required = {
            "skills/material-code-review/schemas/coverage-plan.schema.json",
            "skills/material-code-review/schemas/candidate-set-v2.schema.json",
            "skills/material-code-review/references/reliability-output-integrity-lens.md",
            "skills/material-code-review/references/persisted-config-migration-lens.md",
            "skills/material-code-review/tests/test_discovery_contract.py",
        }
        with zipfile.ZipFile(full_output) as archive:
            self.assertTrue(full_required.issubset(set(archive.namelist())))
        standalone_required = {
            "schemas/coverage-plan.schema.json",
            "schemas/candidate-set-v2.schema.json",
            "references/reliability-output-integrity-lens.md",
            "references/persisted-config-migration-lens.md",
            "tests/test_discovery_contract.py",
        }
        with zipfile.ZipFile(standalone_output) as archive:
            self.assertTrue(standalone_required.issubset(set(archive.namelist())))
```

Set version expectations:

```python
full_version = "1.3.0"
simplification_version = "1.2.0"
```

In the simplification archive test, assert `core/reviewctl.py` contains `TOOL_VERSION = "1.3.0"`, `simplifyctl.py` contains `ADAPTER_VERSION = "1.2.0"`, and `core/schemas/` contains both v1 and v2 candidate schemas plus the coverage-plan schema. This checks embedded runtime provenance without claiming the v2 material-review policy applies to simplification.

- [ ] **Step 2: Run packaging tests and verify RED**

```bash
rtk python3 -B -m unittest discover -s scripts/tests -p 'test_packaging.py' -v
```

Expected: absent new files and old version identities fail.

- [ ] **Step 3: Update validator ownership and controlled markers**

Add the new schemas, lens references, and discovery test to material-review standalone and source-package required-file sets. Add controlled markers for `risk_assessments`, `record-coverage`, candidate-set/v2, both risk codes, complete-wave failure, `CONSEQUENCE_UNSUPPORTED`, and the high-impact risk exception.

Keep the simplification validator's own workflow files unchanged except version and embedded-core requirements. `scripts/package_plugin.py` already copies complete material-review schema/reference/test directories; `scripts/package_simplification_skill.py` already copies every core schema. Change enumeration only if a targeted test proves a shipped path is absent. Do not ship `docs/superpowers/` or `.evaluation-runs/`.

- [ ] **Step 4: Apply coherent versions**

Change material-review/full-plugin `1.2.0` to `1.3.0` in:

```text
.codex-plugin/plugin.json
.claude-plugin/plugin.json
.claude-plugin/marketplace.json
Makefile VERSION
scripts/package_plugin.py
scripts/validate_package.py
skills/material-code-review/scripts/reviewctl.py
skills/material-code-review/scripts/validate_package.py
scripts/tests/test_packaging.py exact assertions
```

Change simplification `1.1.0` to `1.2.0` in:

```text
Makefile SIMPLIFY_VERSION
skills/material-code-simplification/scripts/simplifyctl.py
skills/material-code-simplification/scripts/validate_package.py
scripts/package_simplification_skill.py
scripts/tests/test_packaging.py exact assertions
```

- [ ] **Step 5: Update user-facing documentation without duplicating the canonical contract**

Add a `1.3.0` changelog entry covering immutable exhaustive coverage, candidate-set/v2 binding, targeted lenses, strict-guard evidence, legacy restart/safe restoration, ambiguous delegated simplification restart, and unchanged Gate A/B/mutation/publication policies.

Update README/CODEX workflow summaries and archive names to review `1.3.0` and simplification `1.2.0`. State that new simplification runs retain v1 semantics even though their archive embeds the newer shared controller and schemas.

In `EVALUATION.md`, record: the migration finding was mechanistically associated with an added specialist in one trial; report-alias and precision results were attention variance converted into explicit checks; the base remained stronger overall; and the confirmation remains directional rather than causal proof.

- [ ] **Step 6: Run targeted validators and packaging tests**

```bash
rtk python3 skills/material-code-review/scripts/validate_package.py
rtk python3 scripts/validate_package.py --package-root .
rtk python3 skills/material-code-simplification/scripts/validate_package.py
rtk python3 -B -m unittest discover -s scripts/tests -p 'test_packaging.py' -v
```

Expected: all exit 0 with review/full-plugin `1.3.0` and simplification `1.2.0` identities.

- [ ] **Step 7: Commit packaging and documentation coherence**

```bash
rtk git add .codex-plugin/plugin.json .claude-plugin/plugin.json .claude-plugin/marketplace.json Makefile scripts/package_plugin.py scripts/package_simplification_skill.py scripts/validate_package.py scripts/tests/test_packaging.py skills/material-code-review/scripts/reviewctl.py skills/material-code-review/scripts/validate_package.py skills/material-code-simplification/scripts/simplifyctl.py skills/material-code-simplification/scripts/validate_package.py README.md CODEX.md CHANGELOG.md EVALUATION.md
rtk git commit -m "chore: release targeted review coverage"
```

---

## Final Verification and Review

After Tasks 1–5 pass their independent SDD reviews, run this sequence once on the unchanged coherent tree.

### Controlled drift search

```bash
rtk rg -n 'risk_assessments|record-coverage|candidate-set/v1|candidate-set/v2|user_selectable_output_paths|persisted_config_semantics|CONSEQUENCE_UNSUPPORTED|Run predates required coverage|Gate A|Gate B|1\.1\.0|1\.2\.0|1\.3\.0' skills scripts .codex-plugin .claude-plugin .agents docs/superpowers README.md CODEX.md EVALUATION.md CHANGELOG.md Makefile
```

Confirm normative rules live in the canonical material-review skill; operational references repeat only what they need; old versions occur only in history; and no simplification surface claims material-review v2 or specialist policy applies to simplification.

### Focused final regression suites

```bash
rtk python3 -B -m unittest discover -s skills/material-code-review/tests -p 'test_*.py' -v
rtk python3 -B -m unittest discover -s skills/material-code-simplification/tests -p 'test_*.py' -v
```

### Canonical full validation and packaging

```bash
rtk make package package-simplification
```

Run this canonical command once. Record tree SHA, exit status, test totals, skipped tests, and archive paths. Do not rerun it against an unchanged tree.

### Repository checks

```bash
rtk git diff --check
rtk git status --short
rtk git log --oneline --decorate -8
```

Expected: no whitespace failures; no uncommitted product changes; only ignored `dist/` and SDD/evaluation artifacts may exist.

### One bounded whole-branch review

Use the SDD final reviewer with the full base-to-head review package. Ask only for merge-blocking or materially beneficial findings, with attention to coverage-plan replacement, candidate v1/v2 profile bypass, missing risk paths, partial artifacts, legacy restoration, simplification lifecycle compatibility, strict-guard/high-impact precedence, and distribution drift. If no material finding remains, record `No material improvements recommended.`

### One fresh-task evaluation confirmation

After deterministic validation and final review, record exact identities:

```bash
rtk git rev-parse c18d31fbd704ba76fe7e4c28959ae81c4b4049ea
rtk git rev-parse HEAD
rtk git status --porcelain=v1
```

From one fresh Codex task, invoke exactly once:

```text
$material-review-evaluation base:c18d31fbd704ba76fe7e4c28959ae81c4b4049ea candidate:<final-implementation-sha>
```

At the combined Gate-A checkpoint, only the maintainer supplies approve/reject/defer dispositions. Never approve Gate B. Treat the result as supporting evidence only when the candidate produces valid hash-bound findings and a Gate-B plan without mutation, shows the required reliability and migration/config lenses ran, loses no material base finding solely from skipped coverage, and the blinded judge returns candidate stronger. Preserve tie, base stronger, or insufficient evidence as inconclusive/negative; do not resample without a new concrete defect and material implementation change.
