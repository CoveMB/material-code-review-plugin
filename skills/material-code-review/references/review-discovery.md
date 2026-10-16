# Initial review through Gate A

Read this reference **after entrypoint activation eligibility succeeds and before repository inspection, scope resolution, initialization, discovery, validation, adjudication, or a Gate A decision**. Phases 0–2 form one read-only stage. Load the applicable references required by [the entrypoint](../SKILL.md#reference-loading) before their governed actions. Paths such as `references/...` and `schemas/...` below are relative to `SKILL_DIR`. The entrypoint retains the shared obligation-workflow contract.

### Phase 0 — Resolve and freeze scope

#### 0.1 Read repository control files

Before interpreting the diff, locate and read applicable repository instructions, including root and ancestor-scoped `AGENTS.md`, `CLAUDE.md`, contribution docs, test instructions, and architecture/decision records. Read only files relevant to the changed paths.

For a PR, also read the PR title/body, linked requirement or plan, prior unresolved review threads, and base/head metadata through read-only APIs. Do not check out a remote PR merely to review it.

#### 0.2 Initialize the run

Typical current-change invocation:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" init \
  --repo-root . \
  --scope auto
```

Explicit examples:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" init --repo-root . --scope uncommitted
python3 "$SKILL_DIR/scripts/reviewctl.py" init --repo-root . --scope branch --base origin/main
python3 "$SKILL_DIR/scripts/reviewctl.py" init --repo-root . --scope range --base origin/main --head refs/review/pr-123-head
```

`init` must fail rather than guess when it cannot establish the base or reviewed tree. Untracked files are included unless `--exclude-untracked` is explicitly used and the exclusion is reported to the user.

#### 0.3 Complete the context record

Use `references/context-checklist.md`. Read the changed functions/classes and enough surrounding code to understand callers, guards, contracts, side effects, tests, and documentation. Avoid loading the entire repository by default.

Write a controller context note under the run directory or another local temporary path. It should include:

- intent and its source/confidence;
- relevant repository rules;
- `change_units`, their coherent purposes, and risk signals;
- tests and build commands already available;
- known unknowns;
- excluded paths or incomplete source access;
- external-review decision.

Run `check-scope` before every dispatch or synthesis step:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" check-scope --repo-root .
```

A mismatch means prior reviewer output is stale. Do not “adjust mentally”; reinitialize or regenerate affected artifacts.

#### 0.4 Record exhaustive targeted coverage

Build a `material-review/coverage-plan/v5` using `references/context-checklist.md` and `references/review-obligations.md`.

Every changed comparison path must occur exactly once in one `change_units[*].primary_paths` list. Group paths by coherent behavior or contract ownership, not directory or reviewer persona. Each unit names one `canonical_owner` from its primary paths and every other primary path in `affected_consumers`; bounded unchanged `context_paths` and relevant context consumers make the ownership claim inspectable. The controller freezes those tracked regular comparison-tree files and binds them through `coverage_context_hash`.

For every unit, make exactly one positive or negative decision for all six controlled risks:

- `verification_mechanism_semantics`;
- `machine_contract_semantics`;
- `distribution_contract_integrity`;
- `normative_workflow_coherence`;
- `user_selectable_output_paths`;
- `persisted_config_semantics`.

Positive decisions appear in `risk_codes` and `selected_risk_rationale` with concrete evidence paths. Negative decisions appear in `rejected_risk_rationale` with checked non-trigger evidence. Filenames are hints only. Every positive `(unit_id, risk_code)` pair creates exactly one item in `review_obligations` and exactly one obligation assignment with the controlled required lens and `required_checks`. Before dispatch, derive that obligation assignment's machine-owned `check_contracts` with `check_contracts_for_assignment`; each contract fixes one bounded claim, the exact required evidence-item codes and path scope, and one countercontrol.

The `user_selectable_output_paths` obligation includes independent `runtime_target_derivation_parity` and `validation_to_mutation_identity_stability` checks. Use `references/review-obligations.md` for their repository-neutral derivation and last-validation-to-mutation controls; neither may be discharged by another output-path finding.

Every plan contains the three core assignments: `core-correctness`, `core-standards`, and `core-tests`. Add only the obligation and controlled supporting assignments required by positive risks. Independently classify all eight specialist lenses for every unit in `specialist_decisions`. Under `depth:auto`, select a lens when behavior evidence makes it applicable or when applicability is ambiguous or unknown; reject it only with concrete non-trigger evidence. Under `depth:full`, select all eight for every unit. Every selected decision defines one or more unique atomic `scenario_checks`; each names a bounded claim, exact in-unit evidence paths, and a concrete countercontrol. Rejected decisions have no scenarios. Generic prompts such as “review concurrency” and `full_depth` alone are not scenarios. A low-risk auto plan may therefore contain only the three core assignments and no obligations or specialists.

Create exactly one specialist assignment for each selected lens. Every assignment carries controller-derived `required_review_paths` and `required_checks`. Core paths are the union of all frozen primary and context paths; obligation paths are the union of the obligation owner, consumers, and evidence; supplemental paths cover their complete unit; specialist paths cover every selected unit's primary and context paths. Core and supplemental checks are empty, obligation checks equal the controlled set, and specialist checks equal the exact union of their atomic scenario codes. Specialists cannot satisfy core assignments or controlled obligations. A reviewer process may handle multiple assignments sequentially, but each output remains isolated by exact `assignment_id`.

Run the freshness check after constructing the inventory and before recording it:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" check-scope --repo-root .
python3 "$SKILL_DIR/scripts/reviewctl.py" record-coverage \
  --repo-root . \
  --input /tmp/coverage-plan.json
```

The controller validates the exact primary partition, exhaustive risk decisions, obligation and assignment mappings, context safety, and bounded context size. It writes immutable `coverage-plan.json` and `coverage-context.json` authority. An exact plan/context retry is idempotent; any changed, orphaned, missing-bound, stale, or failed-hash authority requires a new run. Recording grants no repair authority and remains in `CONTEXT_FROZEN`.
### Phase 1 — Generate candidates

#### 1.1 Assignment selection

Candidate generation is one bounded read-only assignment-matched wave. In Codex, use a bounded read-only `explorer` subagent or installed project-scoped reviewer when permitted. On another host, use the closest read-only primitive. When subagents are unavailable, run the same assignments sequentially.

Give every reviewer the frozen scope and context hashes, exact `assignment_id`, `assignment_kind`, `lens_id`, assigned `reviewer_id`, `independence_group`, and `review_mode`, `required_review_paths`, `required_checks`, repository constraints, and `schemas/candidate-set-v6.schema.json`. For an obligation assignment, also provide its single `obligation_id`, risk code, and controller-derived `check_contracts`. For a specialist assignment, provide its exact `unit_ids`, `primary_paths`, `context_paths`, and scenario definitions. Reviewers must echo those assigned values unchanged and must not weaken or reconstruct machine-owned check contracts.

The three core assignments always cover correctness and edge cases, test adequacy for fragile changed behavior, and repository standards plus explicit requirement alignment. Every positive controlled risk adds its obligation assignment. Add supplemental assignments only when the plan's controlled mapping requires them. Specialist assignments remain separate broad lenses and never replace these authorities.

Do not create an obligation from a filename alone. Conversely, do not omit one when behavior-based evidence meets a controlled positive trigger. A reviewer may run several assignments sequentially, but one broad result cannot satisfy multiple assignment IDs or obligations.
#### 1.2 Independence and scheduling

Assign each reviewer an `independence_group` that describes the actual process/model family. Two personas running in the same process/model are distinct lenses, not independent corroboration.

Use bounded parallelism without hard-coding a host capacity. Treat capacity errors as backpressure and retry only within a bounded scheduler loop. If subagents are unavailable, run the same lenses sequentially or as controller self-audits and label coverage `degraded_self_audit`.

External model/CLI review is optional. Before egress, state:

- exact recipient or CLI;
- requested model and whether served identity is verifiable;
- files/diff leaving the host;
- fallback route behavior;
- whether independence is actually established.

Obtain explicit user permission for that egress. A failed or unverifiable external route does not count as independent corroboration.

#### 1.3 Candidate and check-result contract

Each assignment returns one object conforming exactly to `schemas/candidate-set-v6.schema.json`. It includes the exact scope, coverage-plan, and coverage-context hashes plus the assigned identity. Obligation assignments echo one `obligation_id`. Obligation and specialist assignments return every required `check_results` entry exactly once:

- `pass` requires concrete evidence and no finding IDs;
- `finding_emitted` requires concrete evidence and one or more local IDs present in the same result;
- `blocked` identifies missing evidence and leaves the obligation incomplete.

For an obligation result, replace the old check-level evidence fields with the exact machine-owned `evidence_items`. Every evidence item appears exactly once and contains non-empty `evidence` plus non-empty `evidence_paths` drawn from both assignment authority and reviewed coverage. An item with `path_scope: all_required_review_paths` must cite the complete assignment path set; assignment-wide `coverage.files_reviewed` alone cannot satisfy that per-check item. Specialist check results retain check-level `evidence` and `evidence_paths` bound to their scenario.



Each outcome accounts only for its named check. A `finding_local_id` may appear in only one required check result. A finding on one check does not complete another required check or evidence item. Candidate limitations are objects with a description and `related_check_codes`; every linked result must be `blocked`. Do not record `pass` or hide unresolved evidence in a general limitation.

Core and supplemental assignments return an empty `check_results` array. Specialist results echo the assigned `unit_ids`, `primary_paths`, and `context_paths`. Every result must name every `required_review_path` in `coverage.files_reviewed`, including context paths, even when `findings` is empty. A reviewer may not combine assignments, substitute a lens, or report another assignment's obligation.

Reviewers still actively check existing guards, callers, middleware, types, framework behavior, diff causality, explicit project decisions, existing tests, and counterevidence. Use exact source evidence and `references/materiality-rubric.md`. Do not seed reviewers with one another's candidates.

Evidence identity is side-aware. Baseline evidence for a rename or copy uses its exact `old_path`; comparison evidence uses only the exact current `path`. A comparison-side changed path that is frozen as missing remains missing and cannot fall through to coverage context. Only a true no-match may use an unchanged bounded coverage-context source. Frozen hashes and requested line ranges remain mandatory.

Save each return separately and ingest the complete wave together:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" ingest-candidates \
  --repo-root . \
  --input /tmp/assignment-core-correctness.json \
  --input /tmp/assignment-obligation-unit-001.json
```

The controller validates all results in memory. It rejects missing or duplicate assignment IDs, stale hashes, wrong identities or obligations, absent, duplicated, or unknown checks, unsafe evidence paths, unsupported outcomes, `pass` without evidence, unresolved `finding_emitted` IDs, limitations linked to non-blocked results, `blocked` checks, and incomplete required paths. Missing assignments report `Missing required assignment coverage`. Until the complete valid wave exists, no authoritative candidate bundle, adjudication, verdict, or Gate A artifact may exist.

The first accepted wave is write-once authority. An exact canonical retry is no-write. A different complete wave requires a new run. Invalid or unavailable retry input may update only `candidate-ingestion-failure.json`; it cannot replace accepted candidates or state.

After deterministic candidate IDs are assigned, the controller resolves each check's local finding IDs to canonical candidate IDs and writes `material-review/candidates-normalized/v6`. Reviewer sets retain assignment identity, obligation identity when applicable, exact required paths and checks, machine-owned obligation check contracts, specialist unit/path/scenario provenance, check results, and coverage. Reports label raw findings as `candidate_records` and count completed atomic checks separately; neither count proves breadth, recall, independence, cognition, or semantic quality. Temporary input filenames and order are excluded from authority.
### Phase 2 — Validate and adjudicate

#### 2.1 Independent per-finding validation

Use `references/validator-template.md`. In Codex, dispatch a fresh read-only `explorer` subagent or an installed project-scoped validator when available. A validator receives one semantic candidate group, the frozen scope bundle, and no instruction to agree. A fresh persona is not automatically independent: record the actual process/model boundary in `independence_group`. It answers only whether:

- the issue is real;
- it is introduced or exposed by this scope;
- it is not handled elsewhere;
- the consequence/materiality claim is supported;
- the proposed resolution addresses the root cause.

Validators may reject or mark uncertainty. They may not invent new findings. For judgment-heavy, high-impact, security, concurrency, public-contract, or cross-file claims, an independent validator is required whenever host capability exists. Direct controller verification can replace a validator only for mechanically entailed facts and must be labeled as non-independent.

Do not batch unrelated findings into one validator context. Fresh per-finding context is the point. Bound validator concurrency and total attempts; never drop P0/high-impact candidates solely because validator infrastructure failed. Instead mark validation degraded and route the uncertainty visibly to Gate A.

#### 2.2 Provisional grouping and disposition

Use `references/adjudicator-template.md` to form read-only provisional groups after validation. Include every candidate ID exactly once, group only semantic duplicates, attach validation and materiality, and give each group a provisional `keep` or `discard` disposition. This pass does not assign stable `F###` IDs or compile the ledger.

Every provisionally kept group must proceed to a repair-direction audit. Every provisionally discarded group keeps both `repair_direction` and `repair_audit` null. Final adjudication must use the same complete candidate-ID partition; changing a group or disposition requires repeating the affected audit before compilation.

#### 2.3 Repair-direction audit

Use `references/remediation-auditor-template.md`, `references/remediation-rubric.md`, and `references/test-evidence-rubric.md`. The audit determines whether the candidate suggestions support one safe provisional repair direction. It does not revalidate the finding, discover a new finding, or produce the exact Gate-B plan.

Require a fresh repair-direction audit for every provisionally kept group. Use an independent auditor whenever host capability exists for judgment-heavy, high-impact, security, privacy, public-contract, configuration, schema, serialization, migration, concurrency, authorization, cross-owner, or materially divergent suggestions. A mechanically entailed low-risk local correction may use a controller-direct audit; otherwise an unavailable independent route must be recorded as `degraded_self_audit`, never mislabeled as independent.

The audit must compare the literal candidate suggestion with the smallest safe root-cause correction, preserve material states and exceptions, reject guessed authority, keep orthogonal policy dimensions separate, and name causal verification evidence. It returns a normalized `repair_direction` plus a `repair_audit` record bound to the run `scope_hash`, exact candidate IDs, and canonical direction hash. The record names its actual mode, auditor, independence group, trigger, rationale, evidence, and counterevidence. A real finding remains valid when its direction is `needs_refinement`, `needs_user_decision`, `unsafe_to_apply`, or `insufficient_evidence`.

#### 2.4 Final adjudication

Use `references/adjudicator-template.md` and `schemas/adjudication-v4.schema.json`. In Codex, use a fresh read-only `default` subagent or installed project-scoped adjudicator when available. The adjudicator must not have generated or validated the same candidates and may not invent a finding. When no fresh role exists, the controller adjudicates and records the weaker independence accurately.

The adjudicator must:

1. reuse the audited provisional groups without merging distinct failure modes;
2. include every candidate ID exactly once and reject group or disposition drift after audit;
3. preserve source reviewers and independence groups, and provide the exact sorted unique `source_lenses` derived from each group's candidate IDs;
4. attach the independent validation result;
5. apply the nature-specific materiality tests;
6. choose `keep` or `discard` with a reason code;
7. attach the hash-bound `repair_direction` and `repair_audit` to every kept group and null to every discarded group;
8. keep finding confidence separate from repair-direction status and confidence;
9. produce no new finding that lacks a candidate ID.

A serious evidenced defect may be kept even when the eventual fix is large or risky; that risk belongs in planning and Gate B. Optional simplification, DRY, or architecture candidates require demonstrated current cost and a change that is safer than leaving the cost in place.

A stricter guard is a defect only with affirmative supported-state evidence. Sufficient authority includes an explicit requirement or user promise, an accepted schema state, a causal test, or baseline behavior shown to be an accepted or relied-upon compatibility state. Mere historical acceptance or the fact that a guard blocks an input is not enough when intentional fail-closed validation remains plausible. Discard an unsupported medium/low claim as `CONSEQUENCE_UNSUPPORTED`. When the consequence is plausibly blocker/high but support status is genuinely unknown, retain it only as `nature="risk"`, require a user decision and exact pre-fix verification, and do not authorize relaxing the guard until support is established and the plan is revalidated.

Compile the ledger:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" compile-ledger \
  --repo-root . \
  --input /tmp/adjudication.json
```

The tool writes `material-review/ledger/v4` in JSON and Markdown, with `F###` IDs for kept findings, explicit discarded groups/reasons, and the derived source lenses on both. Historical material-review state/v1 through state/v5 artifacts and runs containing earlier normalized candidates are never migrated, backfilled, rehashed, or granted v6 forward authority. They retain only bounded inspection and restoration; forward work requires a new run. Explicit material simplification remains on its separate candidates-normalized/v1, adjudication/v3, and ledger/v3 contracts.

#### 2.5 Merge-readiness decision

Use this mapping:

- `READY` — no material findings remain.
- `READY WITH OPTIONAL FOLLOW-UPS` — only independently confirmed medium-value, non-blocking improvements remain.
- `SHOULD FIX BEFORE MERGE` — at least one high-value defect or material improvement should be addressed.
- `NOT READY` — blocker, serious correctness/security/privacy/data-loss issue, failing core behavior, or explicit required work missing.

Do not let pre-existing record-only observations affect the verdict.

### Gate A — User approves findings for repair planning

This is a hard pause. Gate A approves whether each finding should proceed to planning. It does not approve the provisional repair direction, exact edits, paths, commands, or any mutation. Do not draft a fix plan before the user responds.

Present:

- frozen scope summary and hash;
- review coverage and degraded areas;
- merge-readiness decision;
- every kept `F###` finding with evidence, impact, finding confidence, validation result, risk, and the provisional repair direction's status, confidence, constraints, alternatives, causal evidence, open decisions, and known limits;
- every discarded candidate group with its reason;
- a precise decision request: approve, reject, or defer each kept ID.

The user may approve all, approve a subset, reject, or defer. Do not reinterpret silence as approval.

After the user responds, persist the exact decision:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" gate-findings \
  --repo-root . \
  --approve F001,F003 \
  --reject F002 \
  --defer F004 \
  --user-statement "Approved F001 and F003; rejected F002; deferred F004."
```

When no finding was kept, still record the user's acceptance of the empty material set:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" gate-findings \
  --repo-root . \
  --accept-empty \
  --user-statement "Accepted the no-material-findings decision."
```

The tool verifies that every kept ID has exactly one user disposition and that scope/ledger hashes still match.


After persisting Gate A, load [repair planning](repair-planning.md) before planning any approved ID. An accepted empty set or no approved IDs proceeds to [Final report](../SKILL.md#final-report). On resumption or a return to review, inspect the persisted run and verify its authority as required by [Phase selection and continuation](../SKILL.md#phase-selection-and-continuation); stale authority requires the failure path rather than reuse.
