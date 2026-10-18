---
name: material-code-review
description: "Review concrete Git changes (uncommitted, branch/diff, ref range, or PR) for material defects, regressions, behavior-protecting test gaps, or merge readiness, with evidence-gated repair. Implicit use excludes document/generated-output review, output diagnosis, general skill/plugin/repository analysis, architecture exploration, and planning-only work."
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

New material-review runs use `material-review/state/v6` with `coverage_required=true` and `workflow_profile=material_review`. They require `material-review/coverage-plan/v5`, `material-review/candidate-set/v6`, and `material-review/candidates-normalized/v6` during discovery. Material-review `state/v1` through `state/v5` runs are never migrated, backfilled, or reinterpreted to infer newer evidence authority. They retain bounded inspection and checkpointed restoration, but forward work requires a fresh v6 run. Unsupported or contradictory state/profile combinations fail before command dispatch.

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
- `depth:auto` — classify all eight specialist lenses from behavior evidence and select every applicable, ambiguous, or unknown lens.
- `depth:full` — select all eight specialist lenses for every change unit; this does not lower materiality thresholds.
- `external-review:off` — never route source to external models or CLIs.
- `external-review:ask` — external review may be proposed, but disclose recipient/route/egress and get explicit permission before dispatch.

Reject incompatible or incomplete selectors before reviewer dispatch. In particular, `scope:range` requires both `base:` and `head:`. Do not switch branches to satisfy a selector.

## Restoration boundaries

Before choosing a rollback strategy or presenting Gate B, account for these shared limits. A checkpoint does not guarantee automatic undo:

- Current v4 worktree recovery supports no-ops or exclusive creation from an expected-missing path. Replacing or deleting an existing path fails during preflight before recovery authority writes and requires manual reconciliation.
- Manual rollback and abort bind only approved-path repair deltas. Preserve unrelated ref, HEAD, index, or worktree drift and stop for human reconciliation. Test-caused mutations use only the controller-bound expected post-command authority and supported conditional recovery boundaries.
- HEAD/ref recovery uses ordered expected-old transactions; index restoration holds `index.lock` while verifying semantic identity. There is no global transaction across independently accepted components. Unsupported transitions or platform capabilities, lock contention, identity mismatches, and incomplete restoration require recovery evidence and human reconciliation rather than unconditional writes.
- Historical checkpoints retain only their narrower bounded restoration path. Never fabricate missing v4 authority.

These constraints govern planning and approval; load the detailed execution reference before performing recovery.

## Shared discovery evidence contract

<!-- material-review-obligation-workflow-contract:start -->
check_contracts=controller-derived
obligation_check_results=evidence_items
obligation_evidence_paths=all_required_review_paths
<!-- material-review-obligation-workflow-contract:end -->

## Phase selection and continuation

For a new eligible review, load the initial-review reference and follow Phases 0–2 through Gate A; later phase references are not prerequisites for discovery or adjudication. Before any phase decision or action, load its governing instructions and applicable references listed below. Do not load unrelated later-phase references merely because they exist.

When starting midway, resuming after interruption, or revisiting an earlier phase, first read this entrypoint and inspect the persisted run with `status` and the saved run ID. Verify the relevant frozen artifact identities, receipts, active checkpoint, and remaining budgets before choosing the next phase. A state label or earlier conversation is not approval. Continue a valid run rather than recreating it; stale authority follows the failure rules. If the next permitted action cannot be established, stop and report the missing evidence.

Reload the governing phase reference when it is no longer available in context. A backward transition requires the earlier phase's instructions before its decisions or actions; no transition bypasses Gate A, Gate B, restoration, exact-path authority, or finite retries.

## Workflow

### Phases 0–2 — Resolve scope, generate candidates, validate and adjudicate

After activation eligibility succeeds, read [initial review through Gate A](references/review-discovery.md) **before repository inspection, scope resolution, initialization, reviewer dispatch, validation, adjudication, or a Gate A decision**. It owns the exact scope/coverage contract, candidate wave, independent checks, repair-direction audit, ledger, and merge-readiness decision.

### Gate A — User approves findings for repair planning

This is a hard pause. Gate A approves findings for planning, not repair directions, edits, paths, commands, or mutation. Follow the [initial-review reference](references/review-discovery.md) for the complete presentation and exact receipt procedure, including user acceptance of an empty set. Do not draft a fix plan before the user responds; do not reinterpret silence as approval.

### Phase 3 — Plan approved findings

Only after the user's Gate A response has been persisted, read [repair planning and Gate B](references/repair-planning.md) **before drafting or validating a plan, presenting Gate B, or recording its response**. With no Gate-A-approved IDs, report the recorded decision without entering repair planning. Planning remains read-only.

### Gate B — User validates the repair plan

This is the second hard pause. The [repair-planning reference](references/repair-planning.md) owns the exact presentation and receipt procedure. Obtain an explicit user response to the exact validated plan, paths, commands, risks, assumptions, and rollback behavior. A changed plan has a new hash and requires a new Gate B. Never treat “approve with these edits” as approval of an artifact that has not yet been rewritten and re-presented.

### Phase 4 — Repair approved findings

Read [approved repair execution](references/repair-execution.md) **before `begin-fix`, any repair, required test or refresh, rollback, or abort**. Forward execution requires current exact Gate B approval; recovery follows saved checkpoint authority and the controller's conditional restoration boundaries, including for historical runs or invalidated plans. Stay within approved IDs, paths, commands, and finite budgets. Restoration that cannot establish ownership fails closed for human reconciliation.

### Phase 5 — Post-fix verification

After all approved findings are fixed and required evidence is current, read [bounded post-fix verification](references/postfix-verification.md) **before preparing, dispatching, judging, or recording verification, or deciding whether to reopen a repair**. Verify only approved findings and fix-caused regressions. In-plan repair requires remaining budget; plan amendments require restoration and a new Gate B. Unrelated observations remain record-only.

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
- incomplete units, unsafe context, missing or duplicate obligations, wrong lenses/checks, stale hashes, blocked checks, or unresolved local IDs -> reject coverage or the entire candidate wave, do not guess;
- unavailable subagents -> same checklist, sequential/degraded self-audit;
- validator infrastructure failure -> preserve high-impact uncertainty visibly;
- user gate absent -> stop;
- changed plan after approval -> invalidate Gate B;
- unapproved path mutation -> reject the attempt; automatic rollback preserves it and stops for reconciliation when ownership cannot be bound to a controller-executed command;
- failing required test -> reject/restore or repair within budget;
- new post-fix improvement -> record-only;
- out-of-plan regression repair -> restore and require a new plan approval;
- retry budget exhausted -> BLOCKED, not an infinite loop.

## Reference loading

Read each applicable reference **before the decision or action it governs**, including on resumption or a backward transition. Paths in this list are relative to `SKILL_DIR`. Load only the references needed for the selected phase or condition:

- `references/review-discovery.md` — Phases 0–2 and Gate A, only after eligibility succeeds and before any initial-review decision or action
- `references/repair-planning.md` — Phase 3 and Gate B, after persisted Gate A approval and before planning, plan validation, or a Gate B decision
- `references/repair-execution.md` — before Phase 4 forward execution under current Gate B, or recovery under saved checkpoint authority; also before a bounded repair round
- `references/postfix-verification.md` — Phase 5, after current passing required evidence and before verification preparation, dispatch, judgment, or repair-round selection

- `references/context-checklist.md` — Phase 0 change-unit construction and exhaustive classification
- `references/review-obligations.md` — controlled risks, required lenses/checks, and check-result evidence
- `references/reliability-output-integrity-lens.md` — assigned `reliability` lens for present `user_selectable_output_paths`
- `references/persisted-config-migration-lens.md` — assigned `migration_data_safety` or `api_config_compatibility` lens for present `persisted_config_semantics`
- `references/materiality-rubric.md` — Phases 1–2
- `references/remediation-rubric.md` — repair-direction audit, adjudication, and planning
- `references/test-evidence-rubric.md` — coverage findings and repair-test design
- `references/remediation-auditor-template.md` — Phase 2 repair-direction audit
- `references/reviewer-template.md` — Phase 1
- `references/validator-template.md` — Phase 2 validation
- `references/adjudicator-template.md` — Phase 2 adjudication
- `references/planner-template.md` — Phase 3
- `references/fixer-template.md` — Phase 4
- `references/postfix-verifier-template.md` — Phase 5
- `references/output-template.md` — Gate A and final output
- `references/failure-model.md` — whenever a control point fails
- `references/workflow.md` — state-machine details and command matrix
