# Material Review Discovery Recall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve material-finding recall by binding PR scope identity, requiring protocol-coherence coverage, mechanically preflighting candidate drafts once, and refusing an optimistic verdict when required coverage fails.

**Architecture:** Extend the dependency-free controller with additive PR provenance, a root-owned coverage plan, hash-bound candidate receipts or no-output attestations, runtime fallback assignments, and a pre-ledger `REVIEW_INCOMPLETE` terminal state. Keep candidate-set v1 and all post-ingestion gates unchanged; add one focused protocol-coherence reviewer surface and a maintainer-only PR 3 regression case.

**Tech Stack:** Python 3.10+ standard library, `unittest`, JSON Schema documents, Markdown Agent Skill references, Git, Make, ZIP packaging validators.

## Global Constraints

- Candidate-set v1 remains the only reviewer output schema; do not introduce candidate-set v2.
- Keep runtime dependencies in the Python standard library.
- Preserve both mandatory user gates and the no-mutation-before-Gate-B invariant.
- Preserve frozen/hash-bound scope, complete candidate disposition, exact approved IDs and paths, checkpoints, restoration, finite attempts, and bounded post-fix verification.
- Do not require CodeRabbit, another external reviewer, network access, publication, or source egress.
- Do not seed independent candidate reviewers with other reviewer output or the private regression oracle.
- Permit at most one candidate correction after the initial draft and one sequential fallback after a required lens fails.
- Keep low-value style, harmless duplication, explanatory-comment, and minor test-economy advice outside Gate A unless a concrete material consequence is demonstrated.
- Keep plugin and standalone version `1.2.0`; stop for explicit versioning review if implementation requires an incompatible shipped schema or command change.
- Do not create compatibility artifacts for local immutable runs; tolerate missing additive metadata only for runs created by an older controller.

---

### Task 1: Bind pull-request provenance to the frozen scope

**Files:**
- Modify: `skills/material-code-review/scripts/reviewctl.py`
- Modify: `skills/material-code-review/tests/test_reviewctl.py`
- Modify: `skills/material-code-simplification/scripts/simplifyctl.py`
- Modify: `skills/material-code-simplification/tests/test_simplifyctl.py`
- Modify: `skills/material-code-review/SKILL.md`, `commands/material-review.md`, package validation/tests, the PR evaluation case, and affected documentation

**Interfaces:**
- Consumes: existing `build_scope(repo, requested_scope, base_ref, head_ref, include_untracked)` and `scope_identity_hash(identity)` behavior.
- Produces: first-class immutable `scope=pull_request`; mandatory repository-qualified host provenance; persisted `effective_merge_base` and `comparison_kind=merge_base_to_head`; and the four existing `--review-object-*` flags.

- [ ] **Step 1: Add causal failing tests**

Create a diverged Git history where the host base advances after the feature branch diverges. Prove the future PR scope must equal `git diff merge-base(host_base, host_head)..host_head`, must differ from direct `host_base..host_head`, and must snapshot baseline/head bytes from commit trees. Add fail-before-run cases for absent or partial metadata, an unqualified identity, missing refs, SHA mismatch, and PR provenance on ordinary range. Pin ordinary range to its existing direct bytes and `comparison_kind=commit`.

Add separate failing tests proving material simplification refuses `pull_request` before delegating to the shared controller and that the canonical skill, shipped command, package validator, and maintainer PR evaluation case expose one aligned selector contract.

- [ ] **Step 2: Implement the first-class scope**

Require `scope=pull_request`, `owner/repository#number`, exact lowercase host base/head SHAs, and supplied refs resolving to that pair. Verify the host pair before computing `effective_merge_base`; persist provenance, effective comparison, and `comparison_kind=merge_base_to_head` separately. Use the effective merge base for patch bytes, file states, source snapshots, scope hashing/rendering, and freshness recomputation.

Treat both `commit` and `merge_base_to_head` as commit-backed comparisons. Reject unknown comparison kinds rather than treating them as working-tree state. Preserve ordinary range identity byte-for-byte for backward-compatible legacy freshness. Fail closed with a restart diagnostic for provisional PR-as-range runs.

- [ ] **Step 3: Guard consumers and validate repeated wording**

Add an explicit material-simplification allowlist for `codebase`, `auto`, `uncommitted`, `branch`, and `range`. Update the canonical skill, shipped command, context/workflow/failure references, user docs, design, changelog, and PR evaluation request. Require `commands/material-review.md` in the full package and mechanically compare its argument hint with the canonical review skill.

- [ ] **Step 4: Run focused tests and verify GREEN**

```bash
python3 -B skills/material-code-review/tests/test_reviewctl.py -k pull_request_scope -v
python3 -B skills/material-code-simplification/tests/test_simplifyctl.py -k pull_request_scope -v
python3 -B scripts/tests/test_packaging.py -k pull_request_scope_contract -v
```

Expected: PR bytes/files/snapshots and freshness derive from merge-base-to-head; invalid initialization creates no run; ordinary range remains direct and legacy-compatible; simplification rejects the selector; package contract drift fails deterministically.

---

### Task 2: Record and validate the root-owned coverage plan

**Files:**
- Create: `skills/material-code-review/schemas/coverage-plan.schema.json`
- Modify: `skills/material-code-review/scripts/reviewctl.py:29-100,2578-2657,4190-4265`
- Modify: `skills/material-code-review/tests/test_reviewctl.py:21-160,471-570`

**Interfaces:**
- Consumes: frozen `scope_hash`, the controller-owned workflow profile, context-derived risk signals, actual reviewer identities, and independence groups.
- Produces: `material-review/coverage-plan/v1`, `validate_coverage_plan(raw, state) -> dict[str, Any]`, `record-coverage --input PATH`, `coverage-plan.json`, `coverage_plan_hash`, and `state["workflow_profile"]`, `state["coverage_required"]`, and `state["candidate_preflight"]` for new runs.

- [ ] **Step 1: Write the failing coverage-plan tests**

Add a test helper:

```python
def coverage_plan(self, scope_hash: str, *, protocol: bool = False) -> dict:
    signals = []
    lenses = [
        {"lens_id": "correctness", "required": True, "reviewer_id": "correctness", "independence_group": "model-a", "review_mode": "subagent", "fallback": "sequential_degraded_self_audit"},
        {"lens_id": "test_adequacy", "required": True, "reviewer_id": "test-adequacy", "independence_group": "model-a", "review_mode": "subagent", "fallback": "sequential_degraded_self_audit"},
        {"lens_id": "standards_alignment", "required": True, "reviewer_id": "standards", "independence_group": "model-a", "review_mode": "subagent", "fallback": "sequential_degraded_self_audit"},
    ]
    if protocol:
        signals.append({"code": "state_dependent_schema", "rationale": "The response shape changes at Gate A.", "evidence_paths": ["calc.py"]})
        lenses.append({"lens_id": "protocol_coherence", "required": True, "reviewer_id": "protocol", "independence_group": "model-a", "review_mode": "subagent", "fallback": "sequential_degraded_self_audit"})
    return {
        "schema_version": "material-review/coverage-plan/v1",
        "scope_hash": scope_hash,
        "workflow_profile": "material_review",
        "risk_signals": signals,
        "lenses": lenses,
        "max_candidate_corrections": 1,
    }

def init_with_coverage(self, *, protocol: bool = False) -> str:
    scope_hash = self.init()
    path = self.write_json("coverage-plan.json", self.coverage_plan(scope_hash, protocol=protocol))
    self.run_tool(
        "record-coverage", "--repo-root", str(self.repo),
        "--run-id", self.run_id, "--input", str(path),
    )
    return scope_hash
```

Add tests that record a valid plan, reject a stale scope hash, reject duplicate lens/reviewer IDs, and reject a `state_dependent_schema` signal without required `protocol_coherence` coverage. Assert `coverage-plan.json`, its canonical hash, and `state["hashes"]["coverage_plan_hash"]` agree.

- [ ] **Step 2: Run the coverage tests and verify RED**

Run:

```bash
python3 -B skills/material-code-review/tests/test_reviewctl.py -k coverage_plan -v
```

Expected: failures report that `record-coverage` is not a recognized command.

- [ ] **Step 3: Add the fail-closed coverage-plan schema**

Create a Draft 2020-12 object schema with `additionalProperties: false` and this exact logical shape:

```json
{
  "schema_version": "material-review/coverage-plan/v1",
  "scope_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "workflow_profile": "material_review",
  "risk_signals": [
    {"code": "state_dependent_schema", "rationale": "The response shape changes at Gate A.", "evidence_paths": ["calc.py"]}
  ],
  "lenses": [
    {"lens_id": "correctness", "required": true, "reviewer_id": "correctness", "independence_group": "model-a", "review_mode": "subagent", "fallback": "sequential_degraded_self_audit"},
    {"lens_id": "test_adequacy", "required": true, "reviewer_id": "test-adequacy", "independence_group": "model-a", "review_mode": "subagent", "fallback": "sequential_degraded_self_audit"},
    {"lens_id": "standards_alignment", "required": true, "reviewer_id": "standards", "independence_group": "model-a", "review_mode": "subagent", "fallback": "sequential_degraded_self_audit"},
    {"lens_id": "protocol_coherence", "required": true, "reviewer_id": "protocol", "independence_group": "model-a", "review_mode": "subagent", "fallback": "sequential_degraded_self_audit"}
  ],
  "max_candidate_corrections": 1
}
```

Use controlled risk codes `multi_stage_lifecycle`, `cross_boundary_data`, `prompt_contract`, `conditional_validation`, `state_dependent_schema`, `trust_ordering`, and `shared_schema`. Use fallback values `sequential_degraded_self_audit` and `none`.

- [ ] **Step 4: Implement coverage-plan validation and recording**

Add constants:

```python
COVERAGE_PLAN_SCHEMA = "material-review/coverage-plan/v1"
WORKFLOW_PROFILE_REVIEW = "material_review"
WORKFLOW_PROFILE_SIMPLIFICATION = "material_simplification"
CORE_LENSES = {"correctness", "test_adequacy", "standards_alignment"}
SIMPLIFICATION_CORE_LENSES = {"architecture_structural", "code_test"}
PROTOCOL_RISK_SIGNALS = {"multi_stage_lifecycle", "cross_boundary_data", "prompt_contract", "conditional_validation", "state_dependent_schema", "trust_ordering", "shared_schema"}
```

`validate_coverage_plan` must enforce exact keys, unique lens and reviewer IDs, equality with the state-owned workflow profile, the `material_review` core/protocol rules, the `material_simplification` required `architecture_structural` and `code_test` rules, optional-only simplification extras, `max_candidate_corrections == 1`, and honest controlled modes. `command_record_coverage` runs only in `CONTEXT_FROZEN`, rechecks scope freshness, writes the hash-bound plan, stores its hash, and appends a `coverage_plan_recorded` event.

Set the internal root-owned `state["workflow_profile"]`, set `state["coverage_required"] = True`, and initialize `state["candidate_preflight"] = {}` for every newly created run. Direct review initialization uses `material_review`; the simplification adapter supplies `material_simplification` internally for codebase and delegated Git selectors. Do not expose a CLI profile selector. State files lacking `coverage_required` remain legacy-compatible; provisional feature-branch coverage artifacts missing the final profile contract are rejected with a restart-run outcome rather than interpreted through a dual reader.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run:

```bash
python3 -B skills/material-code-review/tests/test_reviewctl.py -k coverage_plan -v
```

Expected: every coverage-plan test passes.

- [ ] **Step 6: Commit the coverage-plan contract**

```bash
git add skills/material-code-review/schemas/coverage-plan.schema.json skills/material-code-review/scripts/reviewctl.py skills/material-code-review/tests/test_reviewctl.py
git commit -m "feat: record required review coverage"
```

---

### Task 3: Preflight candidate drafts with one hash-bound correction

**Files:**
- Create: `skills/material-code-review/schemas/candidate-preflight.schema.json`
- Create: `skills/material-code-review/schemas/fallback-assignment.schema.json`
- Create: `skills/material-code-review/schemas/reviewer-failure-attestation.schema.json`
- Modify: `skills/material-code-review/scripts/reviewctl.py:1312-1572,2669-2743,4248-4260`
- Modify: `skills/material-code-review/tests/test_reviewctl.py:73-160,570-760`

**Interfaces:**
- Consumes: candidate-set v1 draft when readable bytes exist; otherwise one root-observed required-route failure with controlled reason and bounded numeric metadata; active coverage plan; exact `lens_id`; optional prior receipt hash; and a root-owned fallback assignment before any fallback evidence.
- Produces: `record-reviewer-failure --lens LENS --route ROUTE --reason REASON --observer-kind KIND --observer-id ID [--diagnostic CODE=INTEGER]`; immutable `material-review/reviewer-failure-attestation/v1`; `assign-fallback --lens LENS --failure-trigger-kind KIND --failure-trigger-hash HASH --reviewer-id ID --independence-group GROUP --review-mode MODE`; immutable `material-review/fallback-assignment/v1` under `fallback-assignments/{lens_id}.json`; `check-candidates --lens LENS --input PATH [--fallback] [--supersedes RECEIPT_HASH]`; route-local `material-review/candidate-preflight/v1` receipts; `finalize-coverage` after all incomplete required routes are exhausted; and `candidate_semantic_hash(findings) -> str | None`.

- [ ] **Step 1: Add failing preflight tests**

Add helpers that initialize and record a coverage plan, then tests for:

```python
def test_valid_candidate_preflight_does_not_advance_phase(self) -> None:
    scope_hash = self.init_with_coverage()
    path = self.write_json("candidate.json", self.candidate_set(scope_hash, include_style=False))
    self.run_tool("check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id, "--lens", "correctness", "--input", str(path))
    receipt = self.load("candidate-preflight/correctness/primary/attempt-1.json")
    self.assertEqual(receipt["verdict"], "valid")
    self.assertEqual(self.load("state.json")["phase"], "CONTEXT_FROZEN")

def test_nonverbatim_quote_gets_one_correctable_receipt(self) -> None:
    scope_hash = self.init_with_coverage()
    draft = self.candidate_set(scope_hash, include_style=False)
    draft["findings"][0]["evidence_quote"] = "return something else"
    path = self.write_json("bad-quote.json", draft)
    self.run_tool("check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id, "--lens", "correctness", "--input", str(path), expected=2)
    receipt = self.load("candidate-preflight/correctness/primary/attempt-1.json")
    self.assertEqual(receipt["verdict"], "correctable")
    self.assertEqual(receipt["diagnostics"][0]["code"], "EVIDENCE_NOT_FOUND")

def test_second_attempt_cannot_change_substantive_fields(self) -> None:
    scope_hash = self.init_with_coverage()
    draft = self.candidate_set(scope_hash, include_style=False)
    draft["findings"][0]["evidence_quote"] = "return something else"
    first = self.write_json("first.json", draft)
    self.run_tool("check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id, "--lens", "correctness", "--input", str(first), expected=2)
    prior = self.load("candidate-preflight/correctness/primary/attempt-1.json")
    draft["findings"][0]["evidence_quote"] = "    return a - b"
    draft["findings"][0]["observable_consequence"] = "Changed substance."
    second = self.write_json("second.json", draft)
    self.run_tool("check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id, "--lens", "correctness", "--input", str(second), "--supersedes", prior["receipt_hash"], expected=2)
    self.assertIn("SUBSTANTIVE_DRIFT", {item["code"] for item in self.load("candidate-preflight/correctness/primary/attempt-2.json")["diagnostics"]})
```

Also test a corrected evidence-only second attempt succeeds, a third attempt is refused, a stale scope is refused, and an unparseable first attempt permits exactly one degraded syntax correction.

- [ ] **Step 2: Run the preflight tests and verify RED**

Run:

```bash
python3 -B skills/material-code-review/tests/test_reviewctl.py -k candidate_preflight -v
```

Expected: failures report that `check-candidates` is unknown and no receipts exist.

- [ ] **Step 3: Refactor candidate inspection without weakening ingestion**

Introduce these internal records using dictionaries rather than a new dependency:

```python
EVIDENCE_ANCHOR_FIELDS = {"file", "line_start", "line_end", "evidence_side", "evidence_quote"}
CANDIDATE_FINDING_FIELDS = (  # exact candidate-set/v1 property order
    "local_id", "title", "nature", "category", "severity", "confidence",
    "file", "line_start", "line_end", "evidence_side", "evidence_quote",
    "scope_relation", "related_changed_files", "direct_dependency",
    "observable_consequence", "trigger_conditions", "counterevidence_checked",
    "why_not_preference", "proposed_resolution", "estimated_fix_risk",
    "requires_user_decision", "assumptions",
)
CANDIDATE_MECHANICAL_FIELDS = EVIDENCE_ANCHOR_FIELDS | {"local_id"}
CANDIDATE_SUBSTANTIVE_FIELDS = tuple(
    field for field in CANDIDATE_FINDING_FIELDS if field not in CANDIDATE_MECHANICAL_FIELDS
)
CORRECTABLE_DIAGNOSTIC_CODES = {"JSON_SYNTAX", "TOP_LEVEL_METADATA", "UNKNOWN_FIELD", "EVIDENCE_NOT_FOUND", "EVIDENCE_OUTSIDE_RANGE", "DUPLICATE_LOCAL_ID"}

def candidate_semantic_hash(findings: list[dict[str, Any]]) -> str | None:
    if not all(isinstance(item, dict) for item in findings):
        return None
    payload = [
        {field: item[field] for field in CANDIDATE_SUBSTANTIVE_FIELDS if field in item}
        for item in findings
    ]
    return canonical_hash(payload)
```

Reuse `CANDIDATE_FINDING_FIELDS` for exact-key validation and the substantive projection. This permits the documented local-ID repair and undeclared-key removal without excluding any schema-declared non-mechanical field. Extract the current per-finding validation into an inspection function that returns normalized findings plus structured diagnostics. Keep `validate_candidate_set` as the fail-closed wrapper used by ingestion so existing accepted/rejected semantics remain unchanged.

- [ ] **Step 4: Implement preflight receipts and bounded correction**

The receipt schema must fail closed and require:

```json
{
  "schema_version": "material-review/candidate-preflight/v1",
  "scope_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "coverage_plan_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "lens_id": "correctness",
  "route": "primary",
  "attempt": 1,
  "draft_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "semantic_hash": null,
  "supersedes_receipt_hash": null,
  "verdict": "valid",
  "diagnostics": [],
  "reviewer_id": "correctness",
  "independence_group": "model-a",
  "review_mode": "subagent",
  "fallback_assignment_hash": null,
  "degraded": false,
  "source_file": "/absolute/private/path/candidate.json",
  "receipt_hash": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
}
```

Controlled candidate verdicts are `valid`, `correctable`, and `rejected`. Each candidate diagnostic requires `code`, `path`, `message`, and `correctable`. Primary attempt 2 must reference primary attempt 1, must be from the same lens and reviewer, and must preserve the semantic hash whenever attempt 1 was parsable. No primary attempt 3 is permitted. A route may instead have one root-owned no-output attestation, never both receipts and an attestation. Attestations use controlled reasons and code-and-integer diagnostics only; no free-form summary, candidate substance, or raw logs. Fallback has only route-local attempt 1, is unavailable until `fallback-assignment/v1` binds the exact failed-primary receipt or attestation to the actual actor, and permanently prevents primary resumption. Fallback receipts and normalized candidates copy the verified assignment hash, identity, route, and degraded marker; candidate-supplied identity never creates authority.

When attempt 1 is not parseable, take `reviewer_id` from the hash-verified coverage-plan assignment and set `semantic_hash` to null. The corrected draft must declare that same reviewer ID before candidate validation continues.

Write receipts atomically, persist their hashes under `state["candidate_preflight"][lens_id][route]`, include `completion_route` in coverage status, and return exit status 2 for `correctable` or `rejected` while retaining the receipt.

- [ ] **Step 5: Run preflight and legacy-ingestion tests and verify GREEN**

Run:

```bash
python3 -B skills/material-code-review/tests/test_reviewctl.py -k candidate_preflight -v
python3 -B skills/material-code-review/tests/test_reviewctl.py \
  ReviewCtlTest.test_tampered_frozen_snapshot_is_rejected_during_ingestion -v
```

Expected: all preflight tests pass and frozen-source tampering is still rejected.

- [ ] **Step 6: Commit candidate preflight**

```bash
git add skills/material-code-review/schemas/candidate-preflight.schema.json skills/material-code-review/scripts/reviewctl.py skills/material-code-review/tests/test_reviewctl.py
git commit -m "feat: preflight material review candidates"
```

---

### Task 4: Enforce coverage-complete ingestion and preserve rejected sets

**Files:**
- Create: `skills/material-code-review/schemas/coverage-status.schema.json`
- Modify: `skills/material-code-review/scripts/reviewctl.py:44-64,2669-2845,4198-4230`
- Modify: `skills/material-code-review/tests/test_reviewctl.py:73-302,487-570,949-995`

**Interfaces:**
- Consumes: coverage-plan hash, latest preflight receipt per lens, exact candidate input bytes, and recorded fallback status.
- Produces: `coverage-status.json`, additive `coverage` field in normalized candidate bundle, terminal phase `REVIEW_INCOMPLETE`, and compile-ledger coverage verification for new runs.

- [ ] **Step 1: Update test helpers to exercise the new workflow**

Add helpers that record the three mandatory core lenses, preflight one substantive correctness set plus valid empty test/standards sets, and return all three paths:

```python
def empty_candidate_set(self, scope_hash: str, reviewer_id: str, area: str) -> dict:
    return {
        "schema_version": "material-review/candidate-set/v1",
        "scope_hash": scope_hash,
        "reviewer_id": reviewer_id,
        "independence_group": "model-a",
        "review_mode": "subagent",
        "findings": [],
        "coverage": {"files_reviewed": ["calc.py"], "areas": [area], "limitations": []},
    }

def preflight_core_wave(self, scope_hash: str, correctness: dict) -> list[Path]:
    payloads = [
        ("correctness", correctness),
        ("test_adequacy", self.empty_candidate_set(scope_hash, "test-adequacy", "tests")),
        ("standards_alignment", self.empty_candidate_set(scope_hash, "standards", "standards")),
    ]
    paths = []
    for lens_id, payload in payloads:
        path = self.write_json(f"{lens_id}.json", payload)
        self.run_tool("check-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id, "--lens", lens_id, "--input", str(path))
        paths.append(path)
    return paths
```

Update `reach_adjudicated` and candidate-ingestion tests to use the recorded coverage plan and these preflighted inputs.

- [ ] **Step 2: Add failing fail-closed coverage tests**

Add tests proving:

- ingesting bytes that do not match a valid preflight draft hash fails;
- a wholly rejected optional reviewer remains in `coverage-status.json` with diagnostics and limitations;
- a failed required lens can be satisfied only by one valid `--fallback` preflight;
- a required lens with failed primary and fallback sets phase `REVIEW_INCOMPLETE`;
- `compile-ledger` refuses missing, stale, or incomplete coverage status; and
- an empty material ledger remains valid only after all required lenses completed.

Use exact assertions:

```python
self.assertEqual(self.load("state.json")["phase"], "REVIEW_INCOMPLETE")
self.assertEqual(self.load("coverage-status.json")["status"], "incomplete")
self.assertFalse((self.run_dir / "candidates.json").exists())
```

- [ ] **Step 3: Run the coverage-completion tests and verify RED**

Run:

```bash
python3 -B skills/material-code-review/tests/test_reviewctl.py -k coverage_completion -v
python3 -B skills/material-code-review/tests/test_reviewctl.py \
  ReviewCtlTest.test_empty_material_set_requires_explicit_gate_and_completes -v
```

Expected: coverage-completion tests fail because ingestion does not inspect preflight receipts; the existing empty-ledger test fails until its helper includes mandatory coverage.

- [ ] **Step 4: Implement coverage aggregation and the pre-ledger terminal state**

Add:

```python
PHASE_REVIEW_INCOMPLETE = "REVIEW_INCOMPLETE"

def build_coverage_status(
    *, state: dict[str, Any], coverage_plan: dict[str, Any], receipts: list[dict[str, Any]]
) -> dict[str, Any]:
    lens_results: list[dict[str, Any]] = []
    limitations: list[str] = []
    for lens in coverage_plan["lenses"]:
        matching = [item for item in receipts if item["lens_id"] == lens["lens_id"]]
        primary = max(
            (item for item in matching if not item["fallback"]),
            key=lambda item: item["attempt"],
            default=None,
        )
        fallback = max(
            (item for item in matching if item["fallback"]),
            key=lambda item: item["attempt"],
            default=None,
        )
        completed = any(item is not None and item["verdict"] == "valid" for item in (primary, fallback))
        if not completed:
            limitations.append(f"{lens['lens_id']}: required review evidence is unavailable" if lens["required"] else f"{lens['lens_id']}: optional review evidence is unavailable")
        lens_results.append(
            {
                "lens_id": lens["lens_id"],
                "required": lens["required"],
                "completed": completed,
                "primary_receipt_hash": primary["receipt_hash"] if primary else None,
                "fallback_receipt_hash": fallback["receipt_hash"] if fallback else None,
                "reviewer_id": lens["reviewer_id"],
                "independence_group": lens["independence_group"],
                "review_mode": lens["review_mode"],
                "diagnostics": [diagnostic["code"] for item in matching for diagnostic in item["diagnostics"]],
            }
        )
    complete = all(item["completed"] for item in lens_results if item["required"])
    payload = {
        "schema_version": "material-review/coverage-status/v1",
        "scope_hash": state["scope_hash"],
        "coverage_plan_hash": state["hashes"]["coverage_plan_hash"],
        "workflow_profile": coverage_plan["workflow_profile"],
        "status": "complete" if complete else "incomplete",
        "lenses": lens_results,
        "limitations": limitations,
    }
    payload["coverage_status_hash"] = canonical_hash(payload)
    return payload
```

Implement the function with explicit output keys `schema_version`, `scope_hash`, `coverage_plan_hash`, `workflow_profile`, `status`, `lenses`, `limitations`, and `coverage_status_hash`. Each lens records primary and fallback receipt hashes, completion status, reviewer identity, mode, and diagnostic summaries. Use schema value `material-review/coverage-status/v1` as a controller-owned artifact.

Create `coverage-status.schema.json` with the exact fields produced by `build_coverage_status`, controlled `complete`/`incomplete` status, nullable primary/fallback receipt hashes, fail-closed lens objects, and `additionalProperties: false` at every object level.

For new runs, `ingest-candidates` must verify each input against a latest valid receipt, aggregate required and optional lenses, preserve rejected coverage, and write `coverage-status.json`. If required coverage is incomplete and every incomplete route is terminally evidenced with no correction or fallback authority unused, write the artifact, set `REVIEW_INCOMPLETE`, save state, and return a failure without writing `candidates.json`. Otherwise reject premature ingestion without status or phase mutation. `finalize-coverage` provides the corresponding zero-input path only after the same exhaustion check. Treat `REVIEW_INCOMPLETE` as a terminal non-mutation phase in active-run discovery and status output so it does not masquerade as a resumable candidate run.

For complete coverage, include the normalized coverage object and hash in `candidates.json`. `compile-ledger` must load and hash-verify that object before adjudication. Runs created by older controllers use `state.get("coverage_required", False)` and keep the legacy path.

- [ ] **Step 5: Run all controller tests and verify GREEN**

Run:

```bash
python3 -B -m unittest discover -s skills/material-code-review/tests -p 'test_*.py' -v
```

Expected: all material-review controller and repair-direction tests pass; no existing post-ingestion state or gate behavior changes.

- [ ] **Step 6: Commit fail-closed coverage integration**

```bash
git add skills/material-code-review/schemas/coverage-status.schema.json skills/material-code-review/scripts/reviewctl.py skills/material-code-review/tests/test_reviewctl.py
git commit -m "feat: fail closed on incomplete review coverage"
```

---

### Task 5: Add the protocol-coherence reviewer contract

**Files:**
- Create: `skills/material-code-review/references/protocol-coherence-lens.md`
- Create: `agents/protocol-reviewer.md`
- Modify: `skills/material-code-review/SKILL.md:113-229,299-312,552-582`
- Modify: `skills/material-code-review/references/reviewer-template.md:1-35`
- Modify: `skills/material-code-review/references/context-checklist.md:1-40`
- Modify: `skills/material-code-review/references/failure-model.md:1-32`
- Modify: `skills/material-code-review/references/workflow.md:1-35`
- Create: `skills/material-code-review/tests/test_discovery_contract.py`

**Interfaces:**
- Consumes: frozen context record, scope hash, coverage plan, candidate-set v1 schema, and exactly one assigned lens.
- Produces: controlled `protocol_coherence` lens instructions and a host custom reviewer that emits ordinary candidate-set v1 JSON.

- [ ] **Step 1: Add failing contract tests for the new workflow language**

Create focused discovery-contract tests that require all of these markers without asserting paragraph formatting:

```python
required = {
    "record-coverage",
    "check-candidates",
    "protocol_coherence",
    "REVIEW_INCOMPLETE",
    "one correction attempt",
    "actual pull-request base and head",
}
```

Assert `protocol-coherence-lens.md` exists and contains the controlled headings `Ordering`, `Information availability`, `State completeness`, `Phase-specific schemas`, and `Non-vacuous validation`. Assert `agents/protocol-reviewer.md` points to that reference and prohibits edits, candidate seeding, and low-value advice.

- [ ] **Step 2: Run contract tests and verify RED**

Run:

```bash
python3 -B skills/material-code-review/tests/test_discovery_contract.py -v
```

Expected: failures name the missing reference, agent, and controlled workflow markers.

- [ ] **Step 3: Write the protocol-coherence lens**

Define the five required checks exactly:

```markdown
## Ordering
Verify prerequisites, checkout cleanliness, canonicalization, and attestations occur before dependent reads or actions, and that mutable inputs are re-attested at their use boundary.

## Information availability
Trace every value from producer to consumer. A worker cannot be required to inspect private or omitted data; root-owned authority must be explicit.

## State completeness
Trace approve, reject, defer, empty, invalid, and no-plan states. Omission must not be used where an explicit hash-bound disposition is required.

## Phase-specific schemas
Separate pre-disposition, final, empty, error, and no-plan responses. Require only evidence available in that phase.

## Non-vacuous validation
Verify every conditionally read contract asset is independently required when absence would skip validation.
```

Require one exact primary quote and use related files/counterevidence for the remaining cross-file proof. Repeat the existing materiality threshold and suppress naming, comment, harmless DRY, and minor test-economy advice.

- [ ] **Step 4: Update the canonical workflow and generic reviewer guidance**

Document the exact sequence:

```text
read PR metadata -> init exact range with provenance -> record coverage plan ->
dispatch one lens per reviewer -> preflight each draft -> at most one author-owned
mechanical correction -> bind actual fallback identity after primary failure ->
optional required-lens fallback -> ingest only with complete required coverage ->
validate/adjudicate -> Gate A; otherwise finalize only fully exhausted required
routes as REVIEW_INCOMPLETE and stop
```

State that a PR lookup failure never falls back to the head parent, completely rejected coverage remains visible, `REVIEW_INCOMPLETE` has no merge verdict, and Gate A still approves findings only. Add the new reference to the SKILL reference list and update the workflow/failure tables with the new commands and states.

- [ ] **Step 5: Run contract tests and verify GREEN**

Run:

```bash
python3 -B skills/material-code-review/tests/test_discovery_contract.py -v
python3 -B skills/material-code-review/scripts/validate_package.py
```

Expected: contract tests and standalone source validation pass; the new file exists even though Task 6 has not yet made its absence a structural validation failure.

- [ ] **Step 6: Commit the reviewer-contract change**

```bash
git add skills/material-code-review/SKILL.md skills/material-code-review/references agents/protocol-reviewer.md skills/material-code-review/tests/test_discovery_contract.py
git commit -m "feat: add protocol coherence review lens"
```

---

### Task 6: Ship and validate every new runtime contract

**Files:**
- Modify: `skills/material-code-review/scripts/validate_package.py:18-47,82-145`
- Modify: `scripts/validate_package.py:48-82,750-875`
- Modify: `scripts/tests/test_packaging.py:1460-1585`
- Modify: `README.md:20-55,146-205`
- Modify: `CODEX.md:58-120`
- Modify: `CHANGELOG.md:1-12`

**Interfaces:**
- Consumes: the two new schemas, protocol lens reference, controller commands, and custom protocol reviewer.
- Produces: source and archive validation that prevents missing runtime contracts; concise user-facing PR-scope and review-incomplete guidance.

- [ ] **Step 1: Add failing packaging assertions**

Add `test_material_review_runtime_contracts_are_required`. Extend standalone/full archive assertions to require:

```python
required = {
    "schemas/coverage-plan.schema.json",
    "schemas/candidate-preflight.schema.json",
    "schemas/coverage-status.schema.json",
    "references/protocol-coherence-lens.md",
}
self.assertTrue(required.issubset(names))
```

For the full plugin archive, additionally assert `agents/protocol-reviewer.md` ships. Add a mutation test that removes each new standalone file in turn and expects source validation to report its exact missing path.

- [ ] **Step 2: Run packaging tests and verify RED**

Run:

```bash
python3 -B -m unittest \
  scripts.tests.test_packaging.StandalonePackagingTests.test_material_review_runtime_contracts_are_required -v
```

Expected: FAIL because deleting a new schema or lens reference from a fixture does not yet make the standalone validator fail.

- [ ] **Step 3: Update source and archive validators**

Add every new runtime schema and the protocol reference to both canonical required-file sets. Keep generic JSON-schema validation unchanged: every schema remains an object with `additionalProperties: false`. Add controlled SKILL markers for `record-coverage`, `check-candidates`, `record-reviewer-failure`, `assign-fallback`, `finalize-coverage`, `protocol_coherence`, and `REVIEW_INCOMPLETE` so a package cannot ship the controller without its human workflow.

Do not change package version, archive names, maintainer-only exclusions, the standalone simplification layout, or marketplace metadata.

- [ ] **Step 4: Update host-facing documentation minimally**

Add these operational points to README/CODEX prompts and examples:

- PR reviews use exact read-only base/head metadata and never default to the head parent.
- New runs record required coverage and preflight candidate drafts once.
- A missing required lens ends as review-incomplete rather than `READY`.
- Low-value nitpicks remain suppressed.

Keep detailed normative behavior in `SKILL.md`; public docs should route rather than duplicate the full state machine. Leave `openai.yaml`, activation descriptions, and both version-aligned manifests unchanged at `1.2.0` because activation and the default uncommitted-review prompt do not change.

Add one `1.2.0` changelog bullet describing exact PR provenance, required protocol coverage, bounded candidate preflight, and fail-closed incomplete reviews without presenting low-value nitpicks as a new feature.

- [ ] **Step 5: Run packaging checks and verify GREEN**

Run:

```bash
python3 -B skills/material-code-review/scripts/validate_package.py
python3 -B -m unittest \
  scripts.tests.test_packaging.StandalonePackagingTests.test_completed_standalone_archive_is_structurally_valid \
  scripts.tests.test_packaging.StandalonePackagingTests.test_simplification_archive_ships_repair_direction_references -v
```

Expected: standalone validation and both packaging tests pass.

- [ ] **Step 6: Commit distribution and documentation updates**

```bash
git add skills/material-code-review/scripts/validate_package.py scripts/validate_package.py scripts/tests/test_packaging.py README.md CODEX.md CHANGELOG.md
git commit -m "docs: expose fail-closed review discovery"
```

---

### Task 7: Add the bounded PR 3 discovery-recall evaluation

**Files:**
- Create: `evaluations/material-code-review/cases/pr-3-discovery-recall.json`
- Modify: `EVALUATION.md:1-120`
- Modify: `scripts/validate_package.py:73-92,120-135`
- Modify: `scripts/tests/test_packaging.py:315-410,1219-1247`

**Interfaces:**
- Consumes: exact repository identity, PR 3 base/head, current material-review skill, and a fresh root-controlled review task.
- Produces: maintainer-only `material-review/discovery-recall-case/v1` oracle and a bounded baseline/confirmation procedure that never enters worker allowlists.

- [ ] **Step 1: Write a failing frozen-case test**

Add `test_material_review_discovery_recall_case_is_frozen_and_maintainer_only` asserting exact identity, seven unique material IDs, three low-value controls, and exclusion from full and standalone archives.

Expected material IDs:

```python
{
    "checkout-attestation-order",
    "private-receipt-visibility",
    "complete-disposition-propagation",
    "phase-specific-return-schema",
    "required-document-validation",
    "casefolded-maintainer-archive-path",
    "evaluator-entrypoint-root-boundary",
}
```

Expected low-value control IDs:

```python
{"make-json-deduplication", "split-literal-comment", "minor-test-economy"}
```

- [ ] **Step 2: Run the frozen-case test and verify RED**

Run:

```bash
python3 -B -m unittest \
  scripts.tests.test_packaging.StandalonePackagingTests.test_material_review_discovery_recall_case_is_frozen_and_maintainer_only -v
```

Expected: FAIL because the case file does not exist.

- [ ] **Step 3: Create the exact private oracle**

Write JSON with:

```json
{
  "schema_version": "material-review/discovery-recall-case/v1",
  "repository": "CoveMB/material-code-review-plugin",
  "pull_request": 3,
  "base_commit": "8ebeb7ae2a1f28acfe297c258f703865280c4fa4",
  "head_commit": "c740131b0953a04a93cbe1c970dcbf36dae8bca1",
  "review_request": "Review scope:pull_request with the exact host base/head provenance, depth:full, and external-review:off; stop at Gate A.",
  "expected_material_failure_modes": [
    {"id": "checkout-attestation-order", "primary_path": ".agents/skills/material-review-evaluation/SKILL.md"},
    {"id": "private-receipt-visibility", "primary_path": ".agents/skills/material-review-evaluation/SKILL.md"},
    {"id": "complete-disposition-propagation", "primary_path": "docs/superpowers/plans/2026-07-27-material-review-version-evaluator.md"},
    {"id": "phase-specific-return-schema", "primary_path": "evaluations/material-code-review/prompts/reviewer.md"},
    {"id": "required-document-validation", "primary_path": "scripts/validate_package.py"},
    {"id": "casefolded-maintainer-archive-path", "primary_path": "scripts/validate_package.py"},
    {"id": "evaluator-entrypoint-root-boundary", "primary_path": "scripts/validate_package.py"}
  ],
  "low_value_controls": [
    {"id": "make-json-deduplication", "primary_path": "Makefile"},
    {"id": "split-literal-comment", "primary_path": "scripts/tests/test_packaging.py"},
    {"id": "minor-test-economy", "primary_path": "scripts/tests/test_packaging.py"}
  ],
  "max_executions": {"baseline": 1, "post_change_confirmation": 1}
}
```

Add it to `MAINTAINER_SOURCE_REQUIRED`; do not add it to any distributable required set.

- [ ] **Step 4: Document the bounded manual evaluation**

In `EVALUATION.md`, require a fresh task with the exact base/head and PR provenance, no oracle path in reviewer requests, one baseline at most, one post-change confirmation at most, and this acceptance checklist:

- all seven material IDs map to ingestible candidates and are not discarded without new exact counterevidence;
- no candidate is lost after the one mechanical correction solely because of evidence formatting;
- all required lenses complete or the run ends `REVIEW_INCOMPLETE`;
- the three low-value controls do not become kept Gate-A findings; and
- same-model-family validation remains labeled degraded rather than independent.

- [ ] **Step 5: Run the case and archive tests and verify GREEN**

Run:

```bash
python3 -B -m unittest \
  scripts.tests.test_packaging.StandalonePackagingTests.test_material_review_discovery_recall_case_is_frozen_and_maintainer_only \
  scripts.tests.test_packaging.StandalonePackagingTests.test_full_archive_excludes_maintainer_evaluation_and_keeps_marketplace -v
```

Expected: both tests pass and neither archive contains the oracle.

- [ ] **Step 6: Commit the bounded evaluation case**

```bash
git add evaluations/material-code-review/cases/pr-3-discovery-recall.json EVALUATION.md scripts/validate_package.py scripts/tests/test_packaging.py
git commit -m "test: add material review recall regression case"
```

---

### Task 7A: Close final-state test-evidence recovery deadlocks

**Files:** shared controller, both canonical skills and workflow/failure references, controller/simplification/packaging tests and validators, plus current capability documentation.

**Interfaces:**
- `refresh-finding-test --finding F### --test ID` reruns only an exact required Gate-B-approved finding command after all findings are fixed. It records evidence bound to the latest retained attempt, current allowed-path hash, current workspace guard, and exact test definition; it consumes no attempt or repair round.
- `begin-pre-verification-repair` requires the exact hash of the latest failed or stale required test evidence, exact approved target IDs, and a non-empty causal rationale. It consumes remaining per-finding attempts and one shared repair round, and grants no new path, command, strategy, or finding authority.

- [ ] Add append-only refresh and recovery history to new controller state while accepting older state that omits those additive fields.
- [ ] Make `prepare-verification` consume a current refresh for the latest retained attempt and fail closed on failed, mutating, stale, superseded, or definition-mismatched evidence.
- [ ] Reject passing, nonlatest, optional, unbound, wrong-ID, out-of-plan, or budget-exhausted recovery evidence.
- [ ] Exercise refresh invalidation, mutation restoration, exact evidence-hash binding, shared budgets, simplification delegation, package contract markers, and the two coverage-completion regressions.
- [ ] Keep state/schema and plugin versions unchanged because the commands and optional state fields are additive and local run artifacts require no migration.

---

### Task 8: Perform coherent final validation and one confirmation evaluation

**Files:**
- Verify only; modify files solely to repair failures caused by Tasks 1-7.

**Interfaces:**
- Consumes: completed implementation, deterministic test suite, package validators, and the root-private PR 3 oracle.
- Produces: one validated current tree, distributable archives, and at most one post-change model-mediated confirmation record.

- [ ] **Step 1: Run focused deterministic validation**

Run:

```bash
python3 -B -m unittest discover -s skills/material-code-review/tests -p 'test_*.py' -v
python3 -B -m unittest scripts.tests.test_packaging -v
python3 -B skills/material-code-review/scripts/validate_package.py
git diff --check
```

Expected: all unit and packaging tests pass, standalone validation reports version `1.2.0` structurally valid, and `git diff --check` emits no output.

- [ ] **Step 2: Audit controlled wording and compatibility**

Run:

```bash
rg -n "protocol_coherence|record-coverage|check-candidates|REVIEW_INCOMPLETE|candidate-set/v1|1\.2\.0" \
  skills/material-code-review agents scripts README.md CODEX.md EVALUATION.md
! rg -n "candidate-set/v2|fallback to.*parent|low-value.*Gate A" \
  skills/material-code-review agents scripts README.md CODEX.md EVALUATION.md
```

Expected: the first command shows coherent owner/consumer coverage; the second finds no candidate-set v2, no PR-parent fallback, and no instruction to elevate low-value advice.

- [ ] **Step 3: Run the canonical full packaging validation once**

Run:

```bash
make package package-simplification
```

Expected: shared validation runs once, full plugin and standalone material-review archives validate, and standalone material-simplification packaging validates.

- [ ] **Step 4: Run at most one post-change confirmation evaluation**

From a fresh material-review task, use exactly:

```text
Review pull request CoveMB/material-code-review-plugin#3 using exact base
8ebeb7ae2a1f28acfe297c258f703865280c4fa4 and exact head
c740131b0953a04a93cbe1c970dcbf36dae8bca1. Use scope:pull_request, depth:full,
external-review:off, the PR provenance contract, and the complete required lens
roster. Do not read the discovery-recall oracle. Stop at Gate A without edits.
```

After Gate A, compare the immutable ledger and coverage artifacts with `evaluations/material-code-review/cases/pr-3-discovery-recall.json` only from the root task. Do not execute another confirmation if results are mixed; record them as inconclusive.

- [ ] **Step 5: Commit only confirmation-driven deterministic repairs, if any**

If Step 4 exposes a concrete implementation defect and its correction changes the tested tree, repair only the Task 1-7 owner paths, rerun Steps 1 and 3 once, then stage this bounded set (unchanged files are ignored by Git):

```bash
git add skills/material-code-review scripts/validate_package.py scripts/tests/test_packaging.py agents/protocol-reviewer.md README.md CODEX.md EVALUATION.md evaluations/material-code-review/cases/pr-3-discovery-recall.json
git commit -m "fix: close material review recall validation gap"
```

If no deterministic repair is needed, do not create an empty commit and do not rerun unchanged validation.

- [ ] **Step 6: Report final evidence**

Record the final commit, scope of changed files, focused test totals, canonical package result, confirmation-evaluation disposition, same-model-family limitations, and the fact that low-value controls remained outside Gate A.
