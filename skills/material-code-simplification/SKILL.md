---
name: material-code-simplification
description: "Use for evidence-gated, behavior-preserving simplification/refactoring of bounded codebases or changes: deletion, consolidation, inlining, dependency reduction, restructuring, or bounded rewriting that reduces current maintenance cost. Requires two explicit user approvals."
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

In both layouts, resolve the inherited repair-direction procedure from `"$CORE_DIR/references/remediation-auditor-template.md"`, `"$CORE_DIR/references/remediation-rubric.md"`, and `"$CORE_DIR/references/test-evidence-rubric.md"`. The standalone archive ships these paths under `core/references/`.

Use the simplification adapter for all controller commands:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" --help
```

The adapter delegates all lifecycle commands to the existing controller. Its only additional runtime behavior is `scope=codebase`, which freezes selected current files rather than only Git changes.

New codebase-scope and delegated change-scope simplification runs deliberately retain `material-review/state/v1` and `material-review/candidate-set/v1` with the exact trusted `profile=material-code-simplification`. They do not create change units, coverage plans, review obligations, assignments, specialist decisions, or check results. An unprofiled or contradictory `state/v1` run cannot inherit simplification authority from the adapter and must restart. Standalone adapter 1.3.0 embeds shared controller and helper 1.7.0 for runtime provenance, but selects only the simplification state/v1 profile.

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

Determine the current phase from the frozen run and persisted gate receipts. Before its first decision or action, read the required phase procedure and its applicable nested references:

| Phase | Required procedure |
|---|---|
| 0–3: scope, context, candidates, validation and adjudication | `references/discovery-and-adjudication.md` |
| 4: plan Gate-A-approved transformations, then Gate B below | `references/transformation-planning.md` |
| 5: execute only the exact Gate-B-approved plan | `references/transformation-execution.md` |
| 6: bounded verification and permitted repair rounds | `references/post-refactor-verification.md` |

Both gates below remain mandatory. Before drafting or presenting Gate B, load the planning procedure, including its test, command, compatibility and rollback prerequisites. A continuation or repair round revalidates scope, plan and receipts before entering its phase. Unknown, contradictory or stale state grants no authority: stop under Failure behavior. Keep the common failure catalog loaded in every active phase; load the failure model at any failed control point.

### Gate A — User validates opportunities

This is a hard pause. Gate A approves opportunities for planning only; it does not approve the provisional direction or any transformation. Do not draft the transformation plan before the user responds.

Render every required scope, coverage, action-posture, kept, discarded, direction-audit, validation, separate finding/direction confidence, and risk field through the Gate A section of `references/output-template.md`. Request an approve, reject, or defer decision for every kept ID.

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

### Gate B — User validates the exact plan

This is the second hard pause. Render every approved ID, transformation, behavior, uncertainty, step, path, command, test, compatibility, rollback, risk, and expected-reduction field through the Gate B section of `references/output-template.md`.

Persist approval only after an explicit response. Any changed path, command, strategy, or plan hash requires re-rendering and a new Gate B.

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" gate-plan \
  --repo-root . \
  --approve \
  --user-statement "<exact or faithful approval of the rendered plan>"
```

On rejection, use `--reject`, revise only after the user's direction, revalidate the changed plan, render its new hash, and request Gate B again.

## Common AI-agent failure guards

Load `references/ai-agent-failure-catalog.md` during discovery, planning, implementation, and verification. It is a search-and-disconfirmation aid, not evidence. Apply its guards for provenance, APIs and dependencies, existing mechanisms, speculative infrastructure, dynamic reachability, intentional domain differences, old/new paths, exception fallbacks, test protection, security and behavior contracts, abstraction churn, generated/vendor boundaries, metric gaming, and cleanup recursion.

Do not preserve both old and new implementations unless Gate B approves an explicitly time-bounded compatibility requirement.

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

Use every Result, Evidence chain, Delta, Verification, and Residual risk field in `references/output-template.md`. Also report the human-readable scope mode, paths, exclusions, refs, coverage limits, and architecture-map limitations; reviewer/validator independence and degraded areas; every kept, discarded, user-rejected, user-deferred, fixed, rolled-back, unresolved, and record-only item; and the run artifact directory. The report must remain traceable to the frozen scope, both gate receipts, approved IDs and paths, exact test evidence, verification outcome, repair rounds, limitations, and run artifacts.

Use the exact sentence below only when no material candidate survived adjudication and the user accepted the empty set at Gate A:

`No material simplifications recommended.`

## Failure behavior

Use `references/failure-model.md` and fail closed. Stop or restore on stale/unbounded scope, missing evidence or gates, changed plans, unapproved mutation, failed required tests, or out-of-plan regressions; preserve degraded uncertainty visibly; keep new improvements record-only; and block when finite budgets are exhausted.

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
- `references/output-template.md` — Gate A, Gate B and final output
- `references/failure-model.md` — any failed control point
- `references/workflow.md` — state/command matrix
- `examples/field-mapping.md` — candidate/plan mapping into shared schemas
