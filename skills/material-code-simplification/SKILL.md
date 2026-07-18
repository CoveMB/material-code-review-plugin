---
name: material-code-simplification
description: 'Evidence-gated, behavior-preserving simplification and refactoring of bounded codebase or change scopes. Maps architecture and contracts, captures code-bloat and complexity candidates, independently validates and adjudicates every candidate, requires two explicit user approvals, plans characterization and regression tests, applies checkpointed edits, and stops without recursive cleanup. Use for AI-assisted or conventionally written codebases when meaningful deletion, consolidation, inlining, dependency reduction, restructuring, or tightly bounded rewriting may reduce present maintenance cost.'
argument-hint: "[scope:codebase|auto|uncommitted|branch|range] [path:<repo-relative>]... [exclude-path:<repo-relative>]... [max-files:<n>] [max-bytes:<n>] [base:<ref>] [head:<ref>] [depth:auto|full] [rewrite:deny|allow] [external-review:off|ask]"
---

# Material Code Simplification

## Purpose

Use this skill to identify and execute **material, behavior-preserving reductions in codebase complexity** without turning the work into an open-ended cleanup campaign.

The skill is especially useful after substantial AI-agent implementation, but AI provenance is only a routing hint. It is never evidence that code is bad. A candidate survives only when the current source demonstrates a meaningful cost and the proposed change is safer and simpler than leaving that cost in place.

This skill reuses the state, evidence, gate, checkpoint, test, and verification controller bundled in a standalone archive or, in the full plugin layout, from the sibling `material-code-review` skill. It adds:

- a bounded whole-codebase/path snapshot mode;
- architecture-first and code-level simplification lenses;
- stricter net-simplification and rewrite tests;
- behavior-characterization requirements;
- guards against recurring AI-agent coding failures.

## Resolve the shared controller

Set `SKILL_DIR` to this skill directory. Resolve `CORE_DIR` and `SCHEMA_DIR` in this order:

1. Standalone layout when bundled core is present:
   - `CORE_DIR="$SKILL_DIR/core"`
   - `SCHEMA_DIR="$CORE_DIR/schemas"`
2. Full plugin fallback when bundled core is absent:
   - `CORE_DIR="$SKILL_DIR/../material-code-review"`
   - `SCHEMA_DIR="$CORE_DIR/schemas"`

Use the simplification adapter for all controller commands:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" --help
```

The adapter delegates all lifecycle commands to the existing controller. Its only additional runtime behavior is `scope=codebase`, which freezes selected current files rather than only Git changes.

## Hard invariants

These rules override reviewer enthusiasm, metric output, and host defaults.

1. **No mutation before Gate B.** Do not edit product code, tests, documentation, configuration, generated files, dependency manifests, lockfiles, the Git index, branches, commits, pull requests, or issue trackers before the exact plan is approved.
2. **Two user gates are mandatory.** Gate A approves the adjudicated simplification opportunities. Gate B approves the exact transformation plan, paths, and commands.
3. **Freeze an exact bounded scope.** Every candidate, decision, gate, plan, checkpoint, and verification result remains bound to the controller `scope_hash`.
4. **Provenance is not evidence.** Do not keep, prioritize, or describe a finding merely because code was AI-generated, appears generated, is verbose, or differs from personal style.
5. **Preserve observable behavior unless Gate A explicitly identifies behavior removal.** Preserve public APIs, persistence formats, authorization, validation, error semantics, ordering, idempotency, timing assumptions, concurrency guarantees, external effects, and supported configuration.
6. **Map behavior before proposing structure.** Architecture review must identify contracts and dependency direction before local simplification candidates are adjudicated.
7. **Every captured candidate receives a disposition.** Kept and discarded candidates are both visible. No silent pruning.
8. **Separate discovery, validation, adjudication, implementation, and verification.** Different persona labels in one process do not establish independence.
9. **Require net simplification.** A kept candidate must remove meaningful concepts, paths, states, dependencies, or duplicated policy. Moving code, renaming symbols, splitting files, or adding an abstraction does not by itself simplify anything.
10. **Do not optimize for line count, file count, function count, or a static metric.** Metrics may locate hotspots; they cannot establish materiality or approve a transformation.
11. **Prefer deletion and reuse before new abstraction.** Check whether code can be deleted, consolidated, inlined, or replaced by an existing repository/framework/standard-library mechanism before adding helpers, interfaces, factories, adapters, flags, or configuration.
12. **Rewrite is a last resort.** A rewrite may be kept only when a bounded local refactor cannot remove the evidenced root cause, behavior can be characterized, the replacement boundary is isolated, rollback is feasible, and the expected result is materially simpler than incremental retention.
13. **Uncertain behavior requires characterization.** Do not delete or merge an uncertain path merely because current tests are absent. The plan must first create or identify behavior evidence.
14. **Do not weaken tests to make a refactor pass.** Assertion deletion, broad snapshots, excessive mocks, ignored failures, wider tolerances, and tests that merely mirror the implementation require explicit justification and review.
15. **Fix only approved IDs and exact paths.** New paths, dependency changes, public-contract changes, or a different transformation strategy require restoration and a newly approved Gate B plan.
16. **One approved finding at a time.** A finding may be an atomic multi-file transformation, but distinct `F###` items are never edited concurrently. Read-only discovery may be parallel.
17. **No mixed cleanup.** Avoid combining semantic refactoring with broad formatting, mass renaming, comment rewriting, generated-file churn, or unrelated dependency updates.
18. **Tests are evidence, not edit steps.** Execute only Gate-B-approved commands through the controller. A test that mutates the workspace is rejected and restored.
19. **Finite attempts and rounds.** Respect per-item attempt limits and the plan-level repair-round limit. Never continue until “perfect,” “clean,” or a score reaches a target.
20. **No post-fix improvement recursion.** Final verification covers approved IDs and regressions caused by those edits. New unrelated opportunities are record-only.
21. **No outward publication or code egress without separate approval.** Do not push, open a PR, post comments, file tickets, or send source to an external model or CLI unless the user explicitly authorizes that action after recipient and scope disclosure.
22. **Do not relabel unrelated defects as simplifications.** Keep a correctness, security, privacy, or reliability issue here only when the evidenced complexity is causal and the proposed response is a bounded simplification. Otherwise record it separately and route it to `material-code-review` without expanding this run.

## Argument handling

Recognize these selectors:

Resolve omitted selectors as `scope:codebase`, `depth:auto`, `rewrite:deny`, and `external-review:off`. These conservative defaults are part of the safety contract, not suggestions.

- `scope:codebase` — freeze selected current tracked files and, by default, selected non-ignored untracked files. This is the default for this skill.
- `scope:auto|uncommitted|branch|range` — use the existing change-scope semantics from `material-code-review`. `range` is immutable/review-only; implementation requires a newly frozen mutable scope and new hash-bound gates.
- `path:<repo-relative>` — include an exact file or directory prefix. Repeat to select multiple bounded areas. With no `path:`, `scope:codebase` selects the repository root; do this only when context and snapshot limits are credible.
- `exclude-path:<repo-relative>` — explicitly exclude an exact file or directory prefix. Repeat as needed. Report every exclusion.
- `max-files:<n>` / `max-bytes:<n>` — explicit fail-closed selection budgets passed to `--max-selected-files` / `--max-selected-bytes`. Defaults are 5,000 files and 512 MiB; these limit snapshot enumeration, not semantic model capacity.
- `base:<ref>` / `head:<ref>` — existing branch/range selectors.
- `depth:auto` — choose only lenses warranted by observed structure and risk.
- `depth:full` — use all applicable simplification lenses; this does not reduce the materiality threshold.
- `rewrite:deny` — do not retain rewrite candidates. Local refactors may still be retained.
- `rewrite:allow` — rewrite candidates may be evaluated under the additional rewrite gates. This does not authorize a rewrite.
- `external-review:off` — never send code to external models or CLIs.
- `external-review:ask` — an external review may be proposed only after disclosing recipient, route, files, model-identity uncertainty, fallback behavior, and whether actual independence exists.

Reject unsafe paths, incompatible selectors, unresolved refs, or an unbounded scope that cannot be reviewed faithfully. Do not silently sample files and call the result a whole-codebase review. Instead narrow the scope and report coverage.

## Workflow

### Phase 0 — Resolve, bound, and freeze the source

#### 0.1 Read repository control and intent sources

Before interpreting architecture, read applicable `AGENTS.md`, `CLAUDE.md`, contribution guidance, test commands, architectural decision records, API/schema contracts, migration rules, generation instructions, and directory-local guidance.

Gather the user/task intent and distinguish:

- explicit requirements;
- behavior inferred from tests and callers;
- conventions inferred from repeated repository patterns;
- unknown or contradictory behavior;
- settled tradeoffs that should not be reopened without evidence.

Use `references/context-checklist.md`.

#### 0.2 Choose a bounded codebase scope

For a selected codebase area:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" init \
  --repo-root . \
  --scope codebase \
  --path src \
  --path tests \
  --exclude-path src/generated \
  --max-selected-files 2000 \
  --max-selected-bytes 268435456
```

For all currently selected repository files:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" init \
  --repo-root . \
  --scope codebase
```

For current changes instead:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" init --repo-root . --scope auto
```

Preserve the printed run ID in working memory and, where supported:

```bash
export MATERIAL_REVIEW_RUN_ID="<run-id>"
```

The codebase adapter hashes every selected current file and snapshots content within the configured per-file/total snapshot limits. It fails closed above the configured file/byte budgets. Those budgets protect enumeration and storage; they do not imply that every selected file fits model context. Scope coverage remains a reviewer responsibility, and any unread selected file must be reported as a limitation rather than silently sampled.

#### 0.3 Create the context and behavior record

Write a read-only context note outside the worktree or under the run artifact directory containing:

- scope, paths, exclusions, snapshot limitations, and `scope_hash`;
- intent sources and confidence;
- repository rules and generated/vendor boundaries;
- languages, frameworks, build systems, package managers, and runtime topology;
- public entry points, integrations, data stores, queues, filesystems, processes, and external services;
- security, privacy, authorization, migration, concurrency, retry, and ordering boundaries;
- available tests and what they actually assert;
- known unknowns and conflicting contracts;
- likely AI-agent provenance only as a non-evidential routing note;
- external-review decision.

Run before every dispatch or synthesis step:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" check-scope --repo-root .
```

A mismatch invalidates downstream review artifacts. Reinitialize rather than adjusting conclusions from memory.

### Phase 1 — Map behavior and architecture

This phase is read-only and produces an architecture/behavior map, not findings.

Map only enough of the selected scope and direct dependencies to establish:

- externally observable behavior and public contracts;
- entry points and call paths;
- ownership of validation, policy, state, errors, retries, caching, transactions, and side effects;
- dependency direction and layer boundaries;
- intentionally duplicated or isolated domains;
- dynamic loading, reflection, plugin registration, generated code, and convention-based entry points;
- test seams and behavior that currently lacks reliable characterization;
- historical or documented reasons for apparent complexity.

Use bounded architecture exploration. For each evidenced hotspot, compare at most:

1. leave the current shape in place;
2. the smallest local simplification;
3. a boundary-level restructure only when local work cannot remove the root cause.

Do not generate repository-wide “clean architecture” alternatives. The purpose is to establish constraints and possible reduction shapes, not to reward novelty.

Store the map with evidence paths and explicit uncertainty. It becomes shared read-only context for candidate reviewers, validators, and planners.

### Phase 2 — Generate simplification candidates

Candidate generation is limited to two read-only waves. When subagents are unavailable, run the same lenses sequentially and record `degraded_self_audit` coverage.

Pack applicable lenses into at most three reviewer assignments per wave, with a maximum of three concurrent read-only reviewers. Use one assignment per wave for a cohesive small scope; use two or three only for genuinely distinct domains or risk boundaries. Never spawn one reviewer per smell or per repeated occurrence. This bounds orchestration without imposing a semantic cap on supported candidates.

#### Wave A — Structural and architectural candidates

Select only applicable lenses:

- dependency direction, cycles, unstable boundaries, and unnecessary cross-layer traffic;
- duplicated policy or parallel implementations;
- fragmented ownership and “modular mirage” where many files obscure one coupled flow;
- unnecessary factories, interfaces, adapters, facades, managers, registries, or configuration surfaces;
- speculative extensibility, compatibility branches, feature flags, retries, caches, queues, or concurrency;
- framework or standard-library functionality reimplemented locally;
- architecture that makes routine changes require shotgun edits.

Use `references/architecture-reviewer-template.md` and `references/ai-agent-failure-catalog.md`.

#### Wave B — Code and test candidates

Select only applicable lenses:

- duplicated or near-duplicated logic with shared policy;
- avoidable branching, nesting, state, conversion, mapping, validation, and exception flow;
- dead, unreachable, obsolete, or shadow implementations;
- wrapper chains and pass-through helpers with no policy boundary;
- over-generalized utilities, generics, builders, or configuration used by one real case;
- repeated inline API/dependency usage that should have one existing boundary;
- broad fallbacks or catch-all error handling that conceal failure semantics;
- implementation-coupled tests, excessive mocks, duplicate fixtures, and tests that do not prove behavior;
- generated comments, stale explanations, and documentation that obscure rather than clarify behavior;
- placeholder/demo/debug residue, fabricated success fallbacks, or hard-coded artifacts that create duplicate paths;
- near-identical DTO/model/schema layers and conversion chains with no contract boundary;
- edits made directly to generated/vendor output instead of the owning source or generator;
- unnecessary dependencies or dependency wrappers.

Use `references/code-reviewer-template.md` and `references/ai-agent-failure-catalog.md`.

#### Candidate contract

Return JSON conforming exactly to the shared `candidate-set.schema.json` in `SCHEMA_DIR`. Do not add fields; the shared controller fails closed on extras.
Use `examples/field-mapping.md` as a shape example for both candidate and plan field mapping; replace every illustrative value with active-run evidence.

For this skill, populate the shared fields as follows:

- `nature`: normally `improvement`; use `risk` only when complexity itself creates a demonstrated operational/correctness risk.
- `category`: `simplification`, `dry`, or `architecture` unless another existing category more accurately describes the present cost.
- `scope_relation`: normally `primary` when the cited file is in the selected codebase boundary.
- `related_changed_files`: despite the inherited name, list selected files that establish the cross-file simplification relation.
- `direct_dependency`: in codebase mode, set `true` when the candidate is directly inside the selected simplification boundary. This is required for an honestly `pre_existing` retained candidate under the shared change-oriented controller. Do not use it to smuggle unrelated repository findings into scope.
- `observable_consequence`: the **current complexity cost**, not a hypothetical future benefit.
- `trigger_conditions`: the concrete maintenance, debugging, operation, or change scenario in which the cost materializes.
- `counterevidence_checked`: callers, tests, contracts, framework behavior, intentional divergence, dynamic reachability, history, and existing abstractions checked to disprove the candidate.
- `why_not_preference`: why the concern is not style or metric optimization, what behavior must remain, and why the proposed shape is net simpler.
- `proposed_resolution`: a bounded before-to-after structural description; do not provide unreviewed implementation detail.
- `estimated_fix_risk`: include deletion, migration, data, public contract, concurrency, authorization, and dependency risk.
- `assumptions`: every unresolved behavior or reachability assumption.

A smell name, high complexity score, long file, repeated syntax, or AI-like wording is insufficient. Emit one candidate per supported root cause and transformation boundary, not one per repeated occurrence; cite a canonical location and list related selected files. An empty candidate set is valid.

Ingest all reviewer outputs together:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" ingest-candidates \
  --repo-root . \
  --input /tmp/architecture-candidates.json \
  --input /tmp/code-candidates.json
```

Do not seed reviewers with one another's outputs. Agreement from the same model/process is not independent corroboration.

### Phase 3 — Validate, adjudicate, and stop candidate expansion

#### 3.1 Independent validation

Validate one semantic candidate group at a time with `references/validator-template.md`.

The validator checks:

- exact source evidence and actual reachability;
- current maintenance or operational cost;
- callers, guards, contracts, tests, framework behavior, history, and intentional isolation that may justify the existing shape;
- the behavior-preservation boundary;
- whether deletion/consolidation/reuse is genuinely available;
- whether the proposal removes more concepts and failure modes than it adds;
- whether a smaller or safer alternative exists;
- churn, migration, dependency, and regression risk;
- rewrite-specific gates when relevant.

The validator may confirm, reject, or remain uncertain. It may not invent a new candidate. When no independent process/model exists, label the result honestly as controller-direct or degraded self-audit.

#### 3.2 Adjudication

Use `references/adjudicator-template.md`, the shared adjudication schema, and `references/simplification-rubric.md`.

The adjudicator must:

1. dispose every candidate exactly once;
2. merge only semantic duplicates that share the same root cause and transformation boundary;
3. preserve candidate sources and real independence groups;
4. attach validation to every group;
5. apply the complete net-simplification test;
6. reject aesthetics, metric gaming, speculative future flexibility, harmless duplication, abstraction churn, uncharacterized behavior removal, and rewrites lacking bounded evidence;
7. keep no new issue that lacks a candidate ID;
8. end candidate expansion after compiling the ledger.

Use the shared controller verdicts as an action posture:

- `READY` — no material simplification survived.
- `READY WITH OPTIONAL FOLLOW-UPS` — only bounded optional reductions remain.
- `SHOULD FIX BEFORE MERGE` — meaningful current complexity has a favorable, actionable reduction path. In codebase mode, read this as “recommended before further expansion,” not necessarily as a literal pending merge.
- `NOT READY` — use only when complexity contributes to a blocker-level correctness, safety, data, security, or operability risk.

Compile the complete kept/discarded ledger:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" compile-ledger \
  --repo-root . \
  --input /tmp/simplification-adjudication.json
```

### Gate A — User validates opportunities

This is a hard pause. Do not draft the transformation plan before the user responds.

Present:

- frozen scope, paths, exclusions, hash, and coverage limits;
- behavior/architecture map summary;
- reviewer and validator coverage, including degraded independence;
- action posture;
- every kept `F###` item with exact evidence, present cost, preserved behavior, proposed reduction shape, alternatives checked, validation result, confidence, and risk;
- every discarded group with the specific reason and code;
- a decision request to approve, reject, or defer each kept ID.

Persist the exact response with the shared `gate-findings` command. Silence, prior task approval, or agreement with the general goal is not approval.

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" gate-findings \
  --repo-root . \
  --approve F001,F003 \
  --reject F002 \
  --defer F004 \
  --user-statement "<exact or faithful user decision>"
```

Use `--accept-empty` instead of ID dispositions only when no kept finding survived and the user explicitly accepts the empty ledger.

### Phase 4 — Plan only Gate-A-approved transformations

Use `references/planner-template.md` and the shared fix-plan schema.

Create exactly one plan item per Gate-A-approved `F###`. One item may span several exact files. If two IDs require one indivisible transformation, stop for re-adjudication or a plan amendment; do not combine IDs into an unrepresentable plan item.

Each approved item must define:

- supported root cause and observable behavior to preserve;
- transformation class: `delete`, `consolidate`, `inline`, `reuse-existing`, `dependency-reduce`, `restructure`, or `bounded-rewrite`; the shared fix-plan schema has no class field, so begin `objective` with `Transformation class: <class>.` and add no extra JSON property;
- why a smaller transformation is insufficient when using `restructure` or `bounded-rewrite`;
- exact current and replacement ownership boundaries;
- ordered steps with characterization before destructive work when behavior is uncertain;
- exact allowed file or final-symlink paths, including files to delete and any anticipated new file;
- an overlap audit across plan items: candidates sharing one root cause/boundary should already be one adjudicated finding; for unavoidable overlapping paths, make ordering explicit and place final-state regression commands in `global_tests` so earlier per-item required tests do not become stale after later approved edits;
- dependency-manifest and lockfile paths when dependencies change;
- compatibility, migration, generated-code, and rollback handling;
- exact non-mutating test commands, working directories, purposes, and timeouts;
- success evidence for behavior preservation and for removal of the old path;
- risk controls and `max_attempts` from 1 to 3.

#### Test strategy

Prefer behavior-level evidence over implementation-shape assertions. The plan should select from:

- existing focused regression tests;
- characterization tests for currently unproven behavior;
- public API/contract tests;
- serialization, migration, or persistence compatibility tests;
- authorization/security boundary tests;
- ordering, concurrency, retry, idempotency, and timing tests where relevant;
- build/type/lint/static checks when they establish a relevant property;
- dependency resolution and packaging checks;
- a broader existing suite after focused tests;
- explicit checks that the old implementation, registration, dependency, flag, or duplicate path is no longer reachable.

A characterization command may run before destructive work, but that baseline run does not satisfy final retention after the allowed paths change; rerun it after the final item edit so the latest required result is current.

The shared controller hashes each required per-item test against that item's full allowed-path subset. If a later item changes an overlapping path, the earlier required test becomes stale. Prefer disjoint item boundaries; otherwise make earlier local checks optional evidence and require the relevant final-state command globally after all items are fixed. Do not hide overlap by omitting it from `allowed_paths`.

Do not add tests whose only purpose is to freeze incidental implementation structure. Do not replace precise assertions with snapshots or mocks merely to make change easier.

Set the shared plan loop controls exactly as required by the controller:

- `no_unrelated_cleanup: true`;
- `no_new_improvements_during_fix: true`;
- `post_fix_review_scope: approved_findings_and_fix_introduced_regressions_only`;
- `scope_expansion_policy: restore_and_reapprove`;
- `max_repair_rounds`: normally 1; never more than 2.

Validate the plan:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" validate-plan \
  --repo-root . \
  --input /tmp/simplification-plan.json
```

Validation does not grant write permission.

### Gate B — User validates the exact plan

This is the second hard pause. Present:

- approved IDs and transformation class as encoded in each plan item's `objective`;
- preserved behavior and known uncertainty;
- exact ordered steps;
- every allowed path, including deletions and dependency files;
- every command with working directory and purpose;
- test additions and whether they run before and after destructive work;
- migration, compatibility, rollback, and risk controls;
- expected concept/path/dependency reduction without treating estimates as guarantees.

Persist approval only after an explicit response. Any changed path, command, strategy, or plan hash requires re-rendering and a new Gate B.

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" gate-plan \
  --repo-root . \
  --approve \
  --user-statement "<exact or faithful approval of the rendered plan>"
```

On rejection, use `--reject`, revise only after the user's direction, revalidate the changed plan, render its new hash, and request Gate B again.

### Phase 5 — Apply transformations sequentially

Only after Gate B:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" begin-fix --repo-root .
```

For each approved ID:

1. start the controller checkpoint;
2. re-read the approved plan item and behavior boundary;
3. add or identify characterization evidence before destructive work when required;
4. run the approved baseline characterization command when the plan calls for it;
5. implement the smallest root-cause reduction inside exact paths;
6. remove obsolete code, registrations, flags, dependencies, and compatibility shadows named by the plan rather than leaving old and new paths in parallel;
7. avoid opportunistic abstraction, formatting, renaming, and comments unrelated to the approved item;
8. run focused tests, then broader approved checks;
9. inspect the item diff for changed behavior, widened contracts, hidden fallback paths, duplicated replacement logic, weakened tests, generated churn, dependency drift, and unapproved files;
10. retain with `finish-finding` only after all required evidence passes; otherwise restore with `rollback-finding`.

Controller pattern for one item:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" start-finding --repo-root . --finding F001
python3 "$SKILL_DIR/scripts/simplifyctl.py" run-test --repo-root . --finding F001 --test <approved-test-id>
# perform only the approved edit steps and rerun every required current-state test
python3 "$SKILL_DIR/scripts/simplifyctl.py" finish-finding \
  --repo-root . --finding F001 --status fixed --note "<evidence summary>"
```

When an attempt cannot be retained, restore it explicitly:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" rollback-finding \
  --repo-root . --finding F001 --reason "<failure or boundary reason>"
```

Use `references/refactorer-template.md`.

A rewrite should proceed as a bounded replacement of an approved boundary, not as a greenfield redesign. If implementation reveals a necessary new path, public contract change, data migration, or materially different strategy, restore and return to planning/Gate B.

### Phase 6 — Bounded post-refactor verification

After all approved items are retained, run each required plan-level check and then prepare verification:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" run-global-test --repo-root . --test <approved-global-test-id>
python3 "$SKILL_DIR/scripts/simplifyctl.py" prepare-verification --repo-root .
```

Omit the first line only when the validated plan contains no required global test.

Use a fresh read-only verifier and `references/postfix-verifier-template.md`. For each approved ID, verify:

- the evidenced complexity root cause is removed rather than moved;
- required behavior and contracts remain intact;
- characterization and regression tests pass and were not weakened;
- obsolete paths, dependencies, flags, registrations, and duplicate implementations are gone where the plan required;
- no replacement abstraction, compatibility shadow, fallback, or indirection recreates equivalent complexity;
- the repair delta caused no regression within approved behavior boundaries;
- all edits remain within Gate-B-approved paths.

Do not run a broad “what else can be simplified?” pass. Unrelated observations are record-only and cannot reopen candidate generation.

Record verification with the shared controller:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" record-verification \
  --repo-root . \
  --input /tmp/simplification-verification.json
```

A bounded repair round may address only unresolved approved IDs or regressions caused by their changes, within approved paths and remaining budgets. Anything else requires restoration and a new Gate B.

## Common AI-agent failure guards

Load `references/ai-agent-failure-catalog.md` during discovery, planning, implementation, and verification. The minimum guards are:

- do not infer quality from AI provenance;
- verify packages, APIs, framework behavior, and dependency versions from repository evidence or authoritative documentation before changing dependencies;
- prefer existing repository/framework/standard-library mechanisms over generated helpers;
- reject speculative interfaces, factories, registries, flags, fallbacks, retries, caches, async layers, and configuration without present use;
- check dynamic entry points before declaring code dead;
- do not collapse intentionally different domain rules because their syntax is similar;
- do not preserve both old and new implementations “for safety” unless Gate B approves a time-bounded compatibility requirement;
- do not catch broad exceptions or add silent fallback behavior to make tests pass;
- do not rewrite tests to mirror the replacement implementation;
- do not weaken assertions, authorization checks, validation, error contracts, or concurrency semantics;
- do not replace one large module with many mutually dependent tiny modules and call that simplification;
- do not create a generic abstraction for one concrete case without demonstrated near-term variants;
- do not mix generated/vendor/lockfile churn with semantic edits unless explicitly required;
- do not use a static smell catalog as a checklist that must produce findings.

## Stop rules

The workflow stops when any of these is true:

- Gate A is absent, rejects all items, or accepts an empty ledger;
- Gate B is absent or rejects the plan;
- scope becomes stale before mutation;
- required behavior cannot be characterized safely;
- an approved transformation exceeds paths, strategy, or risk approved at Gate B;
- attempt or repair-round budgets are exhausted;
- post-refactor verification passes;
- the environment prevents reliable verification.

Do not start another broad review cycle at completion.

## Final report

Use `references/output-template.md`. Report:

- final state and action posture;
- scope mode, paths, exclusions, refs, hash, and coverage limits;
- architecture/behavior-map limitations;
- reviewers, validators, independence groups, and degraded areas;
- kept, discarded, user-rejected, user-deferred, fixed, rolled-back, unresolved, and record-only items;
- why each retained change was net simpler and what behavior was preserved;
- Gate A and Gate B receipt hashes and user statements;
- changed and deleted paths attributable to the approved layer;
- dependency/configuration surface changed or removed;
- exact test commands, exit codes, and log paths;
- post-fix verification and repair-round count;
- residual risk and human-review requirements;
- run artifact directory.

Use the exact sentence below only when no material candidate survived adjudication and the user accepted the empty set at Gate A:

`No material simplifications recommended.`

## Failure behavior

Use `references/failure-model.md`. In summary:

- stale or unbounded scope -> stop and refreeze;
- missing behavior evidence -> plan characterization or discard;
- malformed output -> reject visibly, do not repair the model's claim by guessing;
- unavailable subagents -> sequential/degraded self-audit;
- validator infrastructure failure -> preserve uncertainty visibly;
- missing user gate -> stop;
- changed plan -> invalidate Gate B;
- unapproved mutation -> reject and restore;
- failing required test -> restore or repair only within approved budget;
- new improvement during implementation/verification -> record-only;
- out-of-plan regression -> restore and require a new plan;
- exhausted budget -> blocked, not recursive cleanup.

## Reference loading

Load only the stage-specific references needed:

- `references/context-checklist.md` — Phases 0–1
- `references/ai-agent-failure-catalog.md` — Phases 1–6
- `references/simplification-rubric.md` — Phases 2–3 and verification
- `references/architecture-reviewer-template.md` — Phase 2 Wave A
- `references/code-reviewer-template.md` — Phase 2 Wave B
- `references/validator-template.md` — Phase 3 validation
- `references/adjudicator-template.md` — Phase 3 adjudication
- `references/planner-template.md` — Phase 4
- `references/refactorer-template.md` — Phase 5
- `references/postfix-verifier-template.md` — Phase 6
- `references/output-template.md` — Gate A and final output
- `references/failure-model.md` — any failed control point
- `references/workflow.md` — state/command matrix
- `examples/field-mapping.md` — candidate/plan mapping into shared schemas
