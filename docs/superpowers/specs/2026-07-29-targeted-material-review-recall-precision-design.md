# Targeted Material-Review Recall and Precision Design

**Status:** Approved design direction; pending written-spec review

**Date:** 2026-07-29

**Affected capabilities:** Material review, shared controller, and packaging

**Canonical owners:** `skills/material-code-review/SKILL.md` for review judgment and workflow semantics; `skills/material-code-review/scripts/reviewctl.py` for lifecycle enforcement; `skills/material-code-review/schemas/` for machine contracts

## Decision summary

Implement a targeted, fail-closed coverage contract for two evidenced review risks:

- user-selectable output destinations and auxiliary write ordering; and
- persisted-configuration semantics and downstream identity changes.

The root records one immutable, scope-bound coverage plan before reviewer dispatch. New material-review reviewer outputs identify the exact plan and assigned lens. Candidate ingestion succeeds only for a complete, identity-matched wave whose declared file coverage includes the risk-bearing paths. The existing validation, adjudication, Gate A, Gate B, repair, restoration, finite-attempt, and publication controls remain unchanged after ingestion.

The design also adds a precision rule for claims that validation is overly strict. A blocked state must be shown to be supported before it is called a defect. High-impact uncertainty remains visible as a risk rather than being silently discarded or converted into authority to relax a guard.

## Evidence and limits

One blinded comparison and a later external-review addendum support the targeted hypothesis:

- the missing persisted `playlist_prefix` fallback was found by a migration/data-safety specialist that the stronger base did not run;
- the report-path alias finding was produced by a reliability reviewer, but both variants already used reliability; and
- the conservative validation disposition used the existing `CONSEQUENCE_UNSUPPORTED` code rather than a new controller capability.

This is directional, single-trial evidence. The migration result was mechanistically associated with a specialist lens absent from the base in that run; it does not prove general causal superiority. The report-alias and validation-precision results are reviewer-attention variance converted into explicit reusable checks. The evaluated base remained stronger overall.

## Goals

1. Make both controlled risk categories explicitly assessed before reviewer dispatch.
2. Require the relevant specialist lenses when a risk is present.
3. Bind each material-review candidate set to the exact scope, coverage plan, lens, reviewer identity, process-independence group, and review mode.
4. Refuse incomplete, stale, mismatched, or risk-path-incomplete waves without creating an authoritative candidate bundle.
5. Improve output-integrity and persisted-config discovery instructions without lowering materiality.
6. Prevent unsupported strict-validation claims from becoming defect findings or repair authority while preserving blocker/high uncertainty as a visible risk.
7. Preserve every existing user gate, mutation boundary, checkpoint, retry limit, restoration guarantee, and source-egress/publication restriction.
8. Keep material-simplification workflow semantics and candidate-set v1 unchanged.

## Non-goals

- Porting PR provenance, protocol-coherence review, candidate preflight/correction, fallback scheduling, evaluator replacement, pre-verification recovery, or other behavior from `feature/material-review-discovery-recall`.
- Automatically detecting semantic risks from filenames or heuristics.
- Proving that a model reasoned correctly merely because it returned a contract-valid lens result.
- Migrating unfinished pre-1.3 material-review runs.
- Changing Gate A, Gate B, repair authorization, exact approved paths/tests, retry budgets, publication authority, or external-review permission.
- Applying the new material-review lens policy to material simplification.

## 1. Root-owned exhaustive coverage assessment

### Controlled assessments

Every new material-review run records exactly one assessment for each controlled code:

- `user_selectable_output_paths`
- `persisted_config_semantics`

Each assessment contains:

- `code`;
- `present` as an explicit boolean;
- a non-empty `rationale`; and
- `evidence_paths`.

When `present` is true, `evidence_paths` must contain at least one unique normalized path from the frozen scope. When false, `evidence_paths` is empty and the rationale states the checked non-trigger evidence. Requiring both positive and negative assessments makes omission distinguishable from an explicit root decision. It cannot prove that the root's semantic judgment is correct, so documentation and evaluation must state that limitation.

The submitted plan's exact top-level fields are `schema_version`, `scope_hash`, `workflow_profile`, `risk_assessments`, and `lenses`. Each lens contains `lens_id`, `required`, `reviewer_id`, `independence_group`, and `review_mode`. `lens_id` is unique; repeated `reviewer_id` values are allowed and remain truthfully grouped by `independence_group`.

### Required lenses

Every material review requires:

- `correctness`
- `test_adequacy`
- `standards_alignment`

`user_selectable_output_paths: present` additionally requires `reliability`.

`persisted_config_semantics: present` additionally requires both `migration_data_safety` and `api_config_compatibility`.

Every core or mapped lens is marked required. Optional additional lenses remain allowed, but they cannot substitute for a required assignment.

### Trigger semantics

`user_selectable_output_paths` is present when changed behavior writes multiple authoritative or auxiliary artifacts and at least one destination is user-selectable, including when the selectable path predates the diff but a new artifact, writer, cleanup target, or write order creates a new collision opportunity.

`persisted_config_semantics` is present when changed behavior alters the accepted shape, serialization, default, missing-key fallback, interpretation, migration, durable output, or downstream local/remote identity of an optional persisted field.

Filenames alone are never sufficient. The context checklist supplies explicit positive and negative examples.

## 2. Immutable coverage-plan artifact

The root records `coverage-plan.json` with schema `material-review/coverage-plan/v1` after context freeze and before reviewer dispatch. The normalized plan is bound to `scope_hash`; its canonical hash is stored in the artifact and `state.hashes.coverage_plan_hash`.

Recording is single-write:

- no existing plan or state hash: validate and record;
- an existing valid plan with the identical canonical hash: return idempotent success without a second event;
- any different plan, orphaned artifact, missing state binding, or failed content hash: fail closed and require a new run.

The controller event contains `at`, `event`, and `coverage_plan_hash`. Recording does not advance beyond `CONTEXT_FROZEN`; the presence of a verified coverage hash is the required substate for dispatch and ingestion.

Runtime validation mirrors the public JSON Schema using the controller's standard-library validators. It rejects extra or missing keys, invalid types and controlled values, duplicates, unsafe paths, incomplete assessments, missing core/mapped lenses, and mismatched scope/profile. A schema file that is not enforced at runtime is insufficient.

## 3. Material-review candidate-set v2

New material-review runs require `material-review/candidate-set/v2`. It extends the existing candidate contract with:

- `coverage_plan_hash`; and
- `lens_id`.

The existing `reviewer_id`, `independence_group`, and `review_mode` must match the assignment for that lens in the verified plan. `scope_hash` must match the frozen scope.

Material-simplification continues to use candidate-set v1. The controller selects the accepted schema from the trusted run profile; a user-supplied public flag cannot relabel a material-review run as simplification.

`reviewer_id` identifies the actual reviewer/controller identity, not independent corroboration. The same reviewer may execute more than one lens sequentially and therefore may appear in multiple assignments. `lens_id` is the unique assignment key. Shared process/model executions must use the same `independence_group`, preventing multiple lens personas from being presented as independent evidence.

The plan hash and lens ID prove which declared assignment the output addresses. They do not prove the quality of model reasoning; validation, adjudication, and the two user gates remain necessary.

## 4. Coverage-complete candidate ingestion

Candidate-set inputs are fully validated in memory before authoritative writes. For each required lens, ingestion verifies:

1. exactly one candidate set addresses the lens assignment;
2. scope and coverage-plan hashes match;
3. reviewer identity, independence group, and review mode match;
4. `coverage.files_reviewed` contains only normalized frozen-scope paths; and
5. for every mapped risk, the assigned lens's `files_reviewed` includes that risk assessment's evidence paths.

An empty `findings` array is a valid completion only when all identity and coverage checks pass. Extra unassigned material-review candidate sets, duplicate lens completions, stale v1/v2 outputs, and partial waves are rejected.

On failure, the phase and authoritative state hashes do not change and no `candidates.json` or `candidates.md` is created or replaced. A clearly non-authoritative ingestion-failure diagnostic may record input hashes and validation reasons so the wave can be corrected without guessing. A complete retry from `CONTEXT_FROZEN` remains allowed.

On success, normalized `candidates.json` includes `coverage_plan_hash` before `candidate_bundle_hash` is computed. Ledger compilation reloads and verifies the recorded coverage artifact, checks the candidate bundle against that verified hash, and then performs the existing complete adjudication contract. The candidate-bundle hash already carries coverage into adjudication and downstream gates; no duplicate adjudication field is needed.

## 5. Legacy-run compatibility and safe retirement

The maintainer approved no migration for unfinished material-review runs created before this contract.

New material-review state records `workflow_profile="material_review"` and `coverage_required=true`. A centralized compatibility guard rejects every command that would advance a legacy unfinished material-review run, including `record-coverage`; an old run cannot silently acquire a new plan and continue.

The exact operator error is:

`Run predates required coverage; start a new run.`

Allowed legacy operations are limited to:

- `status` and direct reads of historical artifact files;
- `check-scope` where it remains meaningful;
- `rollback-finding` for an active finding checkpoint; and
- `abort-fixes` to restore the pre-fix checkpoint and retire a mutation-phase run safely.

No test execution, finding completion, verification, new Gate A/Gate B decision, planning, repair continuation, or mutation may advance a legacy run. Completed and aborted historical artifacts remain readable as files.

Representative tests cover legacy states at context, adjudicated, plan-approved, and fixing phases, including successful restoration/abort from a mutation phase.

## 6. Material-simplification isolation

Material simplification supports codebase and delegated change scopes. Every simplification initialization path must pass a trusted internal workflow profile into the shared controller and record `profile="material-code-simplification"`. No simplification run receives material-review coverage fields or requires `record-coverage`.

The internal profile is selected by the adapter call path, not a user-settable command-line escape hatch. Existing candidate-set v1, lifecycle, scope, gates, repair behavior, and bundle shape remain unchanged.

Existing codebase-scope simplification runs already carry the authoritative profile and remain exempt. Existing delegated change-scope simplification runs do not persist an authoritative discriminator and are indistinguishable from legacy material-review runs; they fail closed and must restart. This is a compatibility limitation, not a change to simplification review semantics, and must be called out in the changelog.

Regression tests exercise both the existing codebase lifecycle and a complete delegated change-scope lifecycle without a coverage plan.

## 7. Targeted reviewer guidance

### Reliability and output integrity

When assigned for `user_selectable_output_paths`, the lens inventories authoritative outputs, metadata, splits, reports, logs, temporary files, cleanup targets, and publisher artifacts. It traces defaults and overrides, then checks:

- pairwise resolved-destination aliasing;
- relative, symlink-mediated, case-folded, Unicode-normalized, and relevant platform-specific path aliases;
- parent/child ownership overlap;
- success- and failure-path write ordering; and
- auxiliary or cleanup writes after authoritative writes.

It must check counterevidence such as early validation, atomic replacement, no-follow operations, ownership metadata, guarded cleanup, and causal tests. A path collision rejected before authoritative mutation is not reported as an active defect.

### Persisted configuration and migration

When assigned for `persisted_config_semantics`, the lens compares baseline and comparison behavior for:

- a new-file default;
- a missing-key fallback;
- an explicit empty value;
- an explicit legacy value; and
- an explicit custom value.

It traces each difference through serialization, durable local output, external target identity, remote mutation, and user-visible migration. Counterevidence includes schema requirements, version gates, migration documentation, creation-time normalization, baseline fixtures, and proof that older writers always persisted the field.

## 8. Strict-validation precision and uncertainty

A stricter guard is a defect only with affirmative evidence that the blocked state is supported. Sufficient authority includes an explicit requirement or user promise, an accepted schema state, a causal test, or baseline behavior shown to be an accepted or relied-upon compatibility state. Mere historical acceptance or the fact that a guard blocks an input is not enough when intentional fail-closed validation remains plausible.

Disposition precedence is explicit:

- supported state plus material consequence: adjudicate normally as a defect;
- unsupported medium/low claim: discard as `CONSEQUENCE_UNSUPPORTED`;
- plausible blocker/high consequence with genuinely unknown support status: retain only as `nature="risk"`, require a user decision and exact pre-fix verification, and do not authorize relaxing the guard until support is established and the plan is revalidated.

This exception preserves the existing high-impact uncertainty rule without converting uncertainty into a product decision. Contract tests cover all three cases.

## 9. Lifecycle and safety invariants

The material-review discovery order becomes:

```text
init -> context record -> record-coverage -> dispatch assigned lenses ->
ingest complete candidate wave -> validate -> repair-direction audit ->
compile-ledger -> Gate A -> validate plan -> Gate B
```

After candidate ingestion, the existing lifecycle is unchanged:

- every valid candidate receives one kept/discarded disposition;
- each retained direction is audited and hash-bound;
- Gate A approves findings only;
- Gate B approves exact IDs, paths, strategies, and tests;
- no mutation occurs before Gate B;
- checkpoints and workspace guards preserve restoration;
- attempts and repair rounds remain finite;
- post-fix verification is bounded to approved findings and fix-caused regressions; and
- publication, external review, source egress, permission changes, and PR/comment actions require separate explicit authority.

The coverage contract grants no repair permission and cannot weaken a later gate.

## 10. Packaging, versions, and documentation

Release identities are:

- full plugin and standalone material review: `1.3.0`;
- standalone material simplification: `1.2.0`.

The simplification version records the changed embedded shared runtime; its workflow semantics remain unchanged.

All material-review/full-plugin manifests, packagers, validators, archive names, tests, README/Codex guidance, changelog, and evaluator documentation must align. The standalone simplification archive must retain candidate-set v1 support while shipping the shared controller and schemas in the layout its adapter expects.

The broader 2026-07-27 discovery design and plan are marked superseded for implementation. Their PR provenance, protocol-coherence, candidate-preflight, fallback, and recovery work is deferred, not silently implemented. This targeted design is the active semantic decision.

## 11. Validation strategy

Implementation follows test-driven development and adds deterministic tests for:

- exhaustive positive/negative risk assessments;
- runtime/schema parity and path normalization;
- immutable/idempotent coverage recording;
- required-lens routing and `required=true` enforcement;
- material-review candidate-set v2 plan/lens/identity binding;
- risk evidence-path coverage and out-of-scope coverage rejection;
- incomplete, malformed, duplicate, extra, stale, and tampered waves;
- retry success and failure atomicity;
- coverage verification again at ledger compilation;
- legacy forward-progress blocking across representative phases;
- safe legacy rollback/abort;
- simplification codebase and delegated change-scope v1 lifecycles;
- reliability and migration controlled guidance;
- strict-guard supported, unsupported, and high-uncertainty cases; and
- required shipped files, schema versions, archive contents, and release identities.

During implementation, run only the smallest relevant deterministic tests. On the final coherent tree, run `make package package-simplification` once.

After deterministic validation and one bounded whole-branch review, run at most one fresh-task evaluation confirmation against exact base `c18d31fbd704ba76fe7e4c28959ae81c4b4049ea` and the final implementation commit. A tie, base-stronger, or insufficient-evidence result is preserved as inconclusive or negative and is not resampled without a new material defect and implementation change. Gate B is never approved in the evaluator.

## 12. Success criteria

The change succeeds when:

- both controlled risks receive an explicit root assessment;
- a present risk cannot omit its required specialist lens;
- a reviewer output cannot satisfy coverage without naming the exact plan and lens and reviewing the risk-bearing paths;
- incomplete or stale waves cannot create or replace an authoritative candidate bundle;
- legacy material-review runs cannot advance but can restore safely;
- material simplification completes every supported scope without the new review contract;
- unsupported guard-relaxation claims do not become repair authority while high-impact uncertainty remains visible;
- all existing gates, repair bounds, restoration, and publication/source-egress controls remain intact; and
- source validation and every distribution pass on the final tree.
