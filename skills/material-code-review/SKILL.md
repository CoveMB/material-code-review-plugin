---
name: material-code-review
description: 'Evidence-gated review and bounded repair of a concrete Git change scope. Implicitly use only to assess uncommitted changes, a branch or diff, a local ref range, or a PR for material defects, regressions, test gaps protecting changed behavior, or merge readiness. Do not implicitly use for document or generated-output review, output diagnosis, general skill, plugin, or repository analysis, architecture exploration, or planning-only work.'
argument-hint: "[scope:auto|uncommitted|branch|range] [base:<ref>] [head:<ref>] [depth:auto|full] [external-review:off|ask]"
---

# Material Code Review

## Purpose

Use this skill when code changes need a review that is precise enough to drive repair, but must not mutate the tree before the user validates both:

1. the exact material findings; and
2. the exact repair plan.

The workflow is evidence-gated rather than score-gated. It persists scope, candidates, decisions, approvals, checkpoints, test logs, and final verification outside the worktree through `scripts/reviewctl.py`.

## Activation eligibility preflight

Apply this preflight before repository inspection, scope resolution, or any `reviewctl init` operation.

- **Explicit invocation remains supported.** `$material-code-review` may use the existing default scope or any supported selector below. Explicit invocation does not make a non-Git object supported: if the user explicitly invokes the skill for a document, generated artifact, output diagnosis, general analysis, architecture exploration, or planning-only task, report the mismatch and stop safely instead of repurposing this workflow.
- **Implicit eligibility requires both conditions in the prompt itself.** First, the review object must be concrete Git changes: uncommitted changes, a branch or diff, a local ref range, or a PR. Second, the requested outcome must assess material code defects, regressions or risks introduced or exposed by those changes, test gaps protecting changed behavior, or merge readiness.
- **Generic terminology is insufficient.** Words such as “review,” “analyze,” “issues,” “findings,” or “plan” do not establish eligibility. Document or generated-artifact comparison, diagnosis of another skill's output, general skill or plugin analysis, architecture exploration, planning-only work, and general repository analysis remain outside the implicit boundary.
- **Context cannot create eligibility.** The working directory, the existence of a Git repository, a supplied repository path, and `scope:auto` cannot manufacture change-review intent. `scope:auto` resolves a scope only after activation eligibility is already established.
- **Fail closed before initialization.** If implicit eligibility is absent, stop before initializing a run and explain that this workflow is not applicable to the request.

For example, “Review this plugin” is not eligible. “Review the changes on this plugin branch for merge blockers” is eligible.

## Codex and Agent Skills compatibility

When installed through the complete package, the archive-root `SKILL.md` is the portable Codex/OpenAI Skills entrypoint and this file is the canonical workflow. When this directory is imported directly as a standalone skill, this file is the entrypoint and its containing directory is `SKILL_DIR`.

On Codex:

- read applicable target-repository `AGENTS.md` files before review;
- use native agents/subagents only for bounded read-only discovery, validation, planning, or verification;
- fall back to sequential specialist passes without weakening the evidence bar;
- stop execution at Gate A and Gate B until the user responds;
- never infer independent corroboration from different persona labels alone.

The workflow does not require an external app, MCP server, or model route. External review remains opt-in and must disclose source-code egress before authorization.

## Hard invariants

These rules override convenience, reviewer enthusiasm, and host defaults.

1. **No mutation before Gate B.** Before the repair plan is approved, do not edit product files, test files, documentation, configuration, generated files, the Git index, commits, branches, pull requests, or issue trackers.
2. **Two user gates are mandatory.** Gate A approves findings. Gate B approves the repair plan. Agent inference, prior approval of a task, or a high confidence score is not a substitute.
3. **Freeze the reviewed scope.** Bind candidate, adjudication, and plan artifacts to the `scope_hash` created by `reviewctl init`. A stale hash invalidates downstream work.
4. **Do not mix reviewed trees.** A remote/ref diff may be inspected only through the reviewed ref or the supplied diff bundle. Do not use unrelated workspace copies as evidence.
5. **Separate roles.** Candidate reviewers discover. Validators verify. The adjudicator merges and disposes. A candidate generator may not validate its own finding as independent evidence. The adjudicator may not invent a new finding.
6. **Every candidate receives a disposition.** Kept and discarded candidates are both visible. No silent pruning after candidate capture.
7. **Evidence precedes scoring.** A confidence anchor cannot replace an exact source quote, a concrete consequence, diff causality, and checked counterevidence.
8. **Pre-existing scope is narrow.** Exclude unrelated pre-existing issues. Keep one only when the reviewed change directly exposes it, depends on it, or makes it newly reachable.
9. **Improvements have a stricter bar than defects.** A demonstrated defect is not discarded merely because its proper fix is nontrivial. An optional improvement must additionally show current maintenance/complexity cost and a favorable benefit-to-churn tradeoff.
10. **No semantic finding cap.** Keep every candidate that passes. Bound concurrency, validator count per wave, attempts, and repair rounds instead.
11. **Fix only approved IDs.** The plan must contain every Gate-A-approved finding exactly once and no unapproved finding.
12. **Exact write boundaries.** During repair, touch only the finding's Gate-B-approved paths. New paths or a changed strategy require restoration and a newly approved plan.
13. **Verify then retain.** Required approved tests must pass. An unverified or boundary-violating attempt is restored, not left in the tree.
14. **No improvement recursion.** Final verification covers approved findings and regressions caused by their fixes. Unrelated observations are record-only and cannot trigger a new review or repair loop.
15. **Finite retries.** Respect each plan item's `max_attempts` and the plan's `max_repair_rounds`. Never “keep improving until clean.”
16. **No outward publication.** Never push, open a PR, post review comments, file tickets, or send code to an external model/CLI unless the user explicitly authorizes that separate action. External review egress requires disclosure before dispatch.

## Control tool

Set the skill directory once for the active shell or substitute its absolute path in every command:

```bash
SKILL_DIR="<absolute path to skills/material-code-review>"
python3 "$SKILL_DIR/scripts/reviewctl.py" --help
```

The control tool requires Python 3.10 or newer and uses only the standard library. It writes runs below `git rev-parse --git-path material-code-review` unless `--artifact-root` is explicitly supplied. A custom artifact root must be outside the worktree or inside the active Git directory.

After `init`, preserve the printed run ID in working memory and in `MATERIAL_REVIEW_RUN_ID` when the shell permits:

```bash
export MATERIAL_REVIEW_RUN_ID="<run-id>"
```

The host agent remains the controller. Script success proves contract/state checks passed; it does not prove the review judgment is correct.

On Windows, substitute `py -3` for `python3` in the examples. Do not use a Python version older than 3.10.

## Host compatibility

- **Codex plugin:** discovered through `.codex-plugin/plugin.json`; invoke from `/skills` or with `$material-code-review`. Codex should read all applicable target-repository `AGENTS.md` files before dispatch.
- **Standalone Codex/Agent Skills import:** the package root `SKILL.md` is a small adapter to this canonical skill.
- **Claude Code plugin:** discovered through `.claude-plugin/plugin.json`; the same canonical skill is available, but host-specific custom agents are not required or assumed.
- **Other Agent Skills hosts:** load this directory as the skill root and use the generic role templates.

Host-native subagents are optional. Their outputs are untrusted until controller validation and adjudication complete. Parallelize read-only candidate discovery or validation only; keep mutations sequential and behind Gate B.

## Argument handling

Recognize these optional selectors:

- `scope:auto` — dirty tree -> uncommitted scope; clean tree -> current branch against a resolvable base.
- `scope:uncommitted` — `HEAD` against the current working tree, including staged and unstaged changes and untracked files by default.
- `scope:branch` — merge base with `base:<ref>` against the current working tree, including committed and uncommitted branch work.
- `scope:range` — `base:<ref>..head:<ref>`; read-only unless the current workspace is later reinitialized as a mutable, aligned scope.
- `depth:auto` — select conditional lenses from actual risk.
- `depth:full` — use the full applicable reviewer roster; this does not lower materiality thresholds.
- `external-review:off` — never route source to external models or CLIs.
- `external-review:ask` — external review may be proposed, but disclose recipient/route/egress and get explicit permission before dispatch.

Reject incompatible or incomplete selectors before reviewer dispatch. In particular, `scope:range` requires both `base:` and `head:`. Do not switch branches to satisfy a selector.

## Workflow

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
- changed-file groups and risk signals;
- tests and build commands already available;
- known unknowns;
- excluded paths or incomplete source access;
- external-review decision.

Run `check-scope` before every dispatch or synthesis step:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" check-scope --repo-root .
```

A mismatch means prior reviewer output is stale. Do not “adjust mentally”; reinitialize or regenerate affected artifacts.

### Phase 1 — Generate candidates

#### 1.1 Reviewer selection

Candidate generation is one bounded read-only wave. In Codex, use a bounded read-only `explorer` subagent or an installed project-scoped custom reviewer, seeded with `references/reviewer-template.md` and exactly one applicable lens. On another host, use the closest read-only subagent primitive. When subagents are unavailable, run the same lenses sequentially. In every host, provide the frozen scope hash, source bundle, repository constraints, and exact output schema.

Always cover:

- correctness and edge cases;
- test adequacy for fragile changed behavior;
- repository standards and explicit requirement/plan alignment.

Select conditional lenses only when the diff contains a real concern:

- security/privacy/authorization/input trust;
- reliability/retries/timeouts/error handling/background work;
- API, schema, serialization, event, or exported-type contracts;
- data migration/backfill/deployment safety;
- performance/resource use;
- concurrency/ordering/async UI;
- documentation mismatch;
- simplification/DRY/architecture.

Do not spawn a specialist from a filename alone. Conversely, verification mechanisms that can silently pass while the product is broken warrant an adversarial lens even when the diff is small.

For a trivial, low-risk, code-only diff, an inline controller pass plus correctness and standards may be sufficient. Any unknown scope signal, configuration/schema/CI change, security-sensitive behavior, public contract, concurrency, migration, or uncounted file type fails closed to the fuller roster.

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

#### 1.3 Candidate contract

Each reviewer returns JSON conforming to `schemas/candidate-set.schema.json`. Use exact source evidence and the behavioral confidence anchors in `references/materiality-rubric.md`.

A reviewer must actively check for:

- existing guards, callers, middleware, framework behavior, and type constraints;
- whether the cited behavior is actually introduced/exposed by the diff;
- explicit lint suppressions or project decisions;
- tests that already cover the claimed gap;
- intentional tradeoffs documented in the task or repository.

Do not seed reviewers with one another's candidates. That manufactures agreement.

Save each return to a temporary JSON file, then ingest all returns together:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" ingest-candidates \
  --repo-root . \
  --input /tmp/reviewer-correctness.json \
  --input /tmp/reviewer-testing.json
```

The tool verifies scope hashes, required fields, changed-path relation, source-side evidence, and ID uniqueness. Malformed findings are rejected visibly in the ingestion report; do not repair their substance during adjudication by guessing.

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

#### 2.2 Adjudication

Use `references/adjudicator-template.md` and `schemas/adjudication.schema.json`. In Codex, use a fresh read-only `default` subagent or installed project-scoped adjudicator when available. The adjudicator must not have generated or validated the same candidates and may not invent a finding. When no fresh role exists, the controller adjudicates and records the weaker independence accurately.

The adjudicator must:

1. group semantic duplicates without merging distinct failure modes;
2. include every candidate ID exactly once;
3. preserve source reviewers and independence groups;
4. attach the independent validation result;
5. apply the nature-specific materiality tests;
6. choose `keep` or `discard` with a reason code;
7. produce no new finding that lacks a candidate ID.

A serious evidenced defect may be kept even when the eventual fix is large or risky; that risk belongs in planning and Gate B. Optional simplification, DRY, or architecture candidates require demonstrated current cost and a change that is safer than leaving the cost in place.

Compile the ledger:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" compile-ledger \
  --repo-root . \
  --input /tmp/adjudication.json
```

The tool writes a stable finding ledger in JSON and Markdown, with `F###` IDs for kept findings and explicit discarded groups/reasons.

#### 2.3 Merge-readiness decision

Use this mapping:

- `READY` — no material findings remain.
- `READY WITH OPTIONAL FOLLOW-UPS` — only independently confirmed medium-value, non-blocking improvements remain.
- `SHOULD FIX BEFORE MERGE` — at least one high-value defect or material improvement should be addressed.
- `NOT READY` — blocker, serious correctness/security/privacy/data-loss issue, failing core behavior, or explicit required work missing.

Do not let pre-existing record-only observations affect the verdict.

### Gate A — User validates findings

This is a hard pause. Do not draft a fix plan before the user responds.

Present:

- frozen scope summary and hash;
- review coverage and degraded areas;
- merge-readiness decision;
- every kept `F###` finding with evidence, impact, confidence, validation result, risk, and recommendation;
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

### Phase 3 — Plan approved findings

Use `references/planner-template.md` and `schemas/fix-plan.schema.json`. In Codex, a bounded `default` planning subagent may draft the plan after Gate A. Planning remains read-only and grants no edit permission; only the controller presents and records Gate B.

The plan must include every Gate-A-approved ID exactly once and no rejected/deferred ID. Each item must define:

- root cause and observable goal;
- ordered, concrete repair steps;
- exact allowed file or final-symlink paths, including any new file anticipated; directory-wide permissions are invalid;
- dependencies on other approved findings;
- approved, non-mutating test commands, working directories, timeout, and purpose; formatting, generation, migrations, or fixture rewrites belong in explicit repair steps rather than tests;
- manual evidence only when automated verification is genuinely unavailable;
- rollback strategy;
- risk controls and contract/docs implications;
- `max_attempts` between 1 and 3.

The plan-level contract must set:

- `no_unrelated_cleanup: true`;
- `no_new_improvements_during_fix: true`;
- `post_fix_review_scope: approved_findings_and_fix_introduced_regressions_only`;
- a finite `max_repair_rounds` (default 2, maximum 2 for this profile);
- scope expansion policy requiring restoration and a new Gate B.

Validate and render it:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" validate-plan \
  --repo-root . \
  --input /tmp/fix-plan.json
```

Validation checks IDs, hashes, paths, test contracts, dependencies, attempt limits, and loop controls. It does not grant write permission.

### Gate B — User validates the repair plan

This is the second hard pause. Present:

- approved finding IDs;
- exact steps per finding;
- every allowed path;
- commands that will be executed;
- risks, assumptions, and rollback behavior;
- any manual decision or weakly verified area.

Persist approval only after an explicit user response:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" gate-plan \
  --repo-root . \
  --approve \
  --user-statement "Approved the repair plan and listed commands."
```

A rejection is also recorded:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" gate-plan \
  --repo-root . \
  --reject \
  --user-statement "Plan rejected; revise F002 to avoid changing the public API."
```

A changed plan has a new hash and requires a new Gate B approval. Never treat “approve with these edits” as approval of an artifact that has not yet been rewritten and re-presented.

### Phase 4 — Repair approved findings

#### 4.1 Begin the repair layer

Only after Gate B:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" begin-fix --repo-root .
```

This rechecks the frozen scope, confirms the working tree is mutable/aligned, captures a pre-fix restoration snapshot, and establishes a workspace guard. Do not stage or commit.

#### 4.2 Per-finding cycle

Process one finding at a time unless the plan explicitly declares a shared atomic repair. Respect dependencies.

Start a checkpoint:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" start-finding --repo-root . --finding F001
```

Then make only the approved changes. Prefer the smallest root-cause correction, but do not preserve a broken architecture merely to minimize line count. Do not perform opportunistic cleanup.

Execute each approved required test through the control tool so the command, output, timeout, and exit code are durable. Tests are evidence, not edit steps: any workspace/index mutation caused by a test is rejected and restored when safe. The tool is not a sandbox; a command runs with the current user's host permissions, so Gate B must review commands for filesystem, network, credential, process, and Git effects:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" run-test \
  --repo-root . \
  --finding F001 \
  --test unit-regression
```

When the repair is complete:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" finish-finding \
  --repo-root . \
  --finding F001 \
  --status fixed \
  --note "Guard now rejects cross-account IDs before lookup."
```

The finish command refuses to keep a repair when:

- an unapproved path changed;
- required tests were not run or failed;
- the active finding/checkpoint does not match;
- the attempt budget is exhausted;
- workspace state drifted outside the controller's expected state.

On a failed or suspect attempt, restore it:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" rollback-finding \
  --repo-root . \
  --finding F001 \
  --reason "Targeted test exposed a contract regression."
```

Do not manually undo a failed attempt when the checkpoint tool can restore it; manual partial reversal is harder to audit.

If the workflow must be abandoned or the plan must expand, restore the entire repair layer:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" abort-fixes \
  --repo-root . \
  --reason "Repair requires an unapproved schema path."
```

This returns the working tree to the frozen pre-fix state. Replan and repeat Gate B rather than editing around the boundary.

#### 4.3 Global tests

Run plan-level commands after all finding items pass:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" run-global-test \
  --repo-root . \
  --test focused-suite
```

A green command is not conclusive proof for authorization, migrations, distributed effects, public contracts, or concurrency. Preserve those residual verification limits in the final report.

### Phase 5 — Post-fix verification

Prepare the bounded verification bundle:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" prepare-verification --repo-root .
```

This checks that all approved findings are marked fixed, global required tests passed, and the aggregate repair delta remains inside Gate-B paths. It writes a fix-only diff/snapshot summary.

Use `references/postfix-verifier-template.md` and `schemas/verification.schema.json`. In Codex, prefer a fresh read-only `explorer` subagent or installed project-scoped post-fix verifier that did not implement the repair. Record degraded self-audit when no fresh verifier is available. The verifier must evaluate:

- each Gate-A-approved finding by stable ID;
- evidence that its root cause is resolved;
- tests and behavior relevant to that finding;
- regressions caused by the repair delta.

It must not run a broad “what else could be improved?” pass. Unrelated observations go only into `record_only_observations` and do not affect the verdict or initiate work.

Record the result:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" record-verification \
  --repo-root . \
  --input /tmp/postfix-verification.json
```

Possible outcomes:

- `COMPLETE` — every approved finding is resolved and no fix-caused regression remains.
- `REPAIR_REQUIRED` — an approved finding remains unresolved or its fix caused a regression that can be repaired within the already approved item paths and remaining attempt/repair budget.
- `PLAN_AMENDMENT_REQUIRED` — repair needs a new path, a materially different strategy, or more than the approved budget. Restore and return to planning/Gate B.
- `BLOCKED` — evidence or environment prevents safe completion.

For a bounded in-plan repair round:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" begin-repair --repo-root .
```

The tool reopens only causal approved finding IDs whose requested repair paths remain within their plan. It refuses an out-of-plan repair. Repeat the per-finding cycle and verification, never exceeding the plan's `max_repair_rounds`.

## Final report

Use `references/output-template.md`. Report:

- final state and merge-readiness;
- original scope mode, refs, files, and hash;
- reviewer/validator coverage and any degraded independence;
- kept, discarded, user-rejected, user-deferred, fixed, rolled-back, unresolved, and record-only items;
- Gate A and Gate B receipt hashes and exact user statements;
- changed paths attributable to the repair layer;
- required test commands, exit codes, and log paths;
- post-fix verification result and repair-round count;
- known limits requiring human review;
- run artifact directory.

Do not offer another broad review pass. Say the following exact sentence only when the adjudicated ledger kept zero material findings and the user explicitly accepted that empty set at Gate A:

`No material improvements recommended.`

When the ledger contained material findings but the user rejected or deferred all of them, report that decision and preserve the original merge-readiness verdict; do not use the no-material-findings sentence.

## Failure behavior

Read `references/failure-model.md`. In summary:

- unknown or stale scope -> stop and refreeze;
- malformed reviewer output -> reject that output, do not guess;
- unavailable subagents -> same checklist, sequential/degraded self-audit;
- validator infrastructure failure -> preserve high-impact uncertainty visibly;
- user gate absent -> stop;
- changed plan after approval -> invalidate Gate B;
- unapproved path mutation -> reject/restore attempt;
- failing required test -> reject/restore or repair within budget;
- new post-fix improvement -> record-only;
- out-of-plan regression repair -> restore and require a new plan approval;
- retry budget exhausted -> BLOCKED, not an infinite loop.

## Reference loading

Load references only at the stage that needs them:

- `references/context-checklist.md` — Phase 0
- `references/materiality-rubric.md` — Phases 1–2
- `references/reviewer-template.md` — Phase 1
- `references/validator-template.md` — Phase 2 validation
- `references/adjudicator-template.md` — Phase 2 adjudication
- `references/planner-template.md` — Phase 3
- `references/fixer-template.md` — Phase 4
- `references/postfix-verifier-template.md` — Phase 5
- `references/output-template.md` — Gate A and final output
- `references/failure-model.md` — whenever a control point fails
- `references/workflow.md` — state-machine details and command matrix
