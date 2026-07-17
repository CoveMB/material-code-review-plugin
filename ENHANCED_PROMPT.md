# Enhanced invocation prompt

Use the `$material-code-review` skill to review the selected change set and, only after two explicit user approvals, repair approved findings.

## Objective

Determine whether the changes contain material defects or material improvement opportunities clearly worth addressing before completion. This is an evidence-and-decision workflow, not open-ended brainstorming.

## Controls

1. Freeze and hash the exact review scope before analysis. Account explicitly for committed, staged, unstaged, and untracked files according to the selected scope. Never inspect a ref or remote diff using unrelated workspace contents.
2. Do not modify code, tests, documentation, configuration, Git state, branches, pull requests, or tickets before the exact repair plan passes Gate B.
3. Separate candidate discovery, independent validation, and adjudication. The adjudicator may deduplicate and decide, but may not invent findings.
4. Record every candidate. Show what was kept or discarded and why; do not silently suppress plausible-but-rejected ideas.
5. Require exact file/line evidence, source side, observable consequence, triggering conditions, relation to the current change, checked counterevidence, and a reason the concern is not preference.
6. Exclude unrelated pre-existing concerns. Keep one only when the change exposes it, depends on it, or makes it newly reachable.
7. Apply a stricter materiality test to optional improvements than to defects. A serious evidenced defect is not discarded merely because its correct repair is nontrivial.
8. Reject style, ordinary linter output, speculative future needs, harmless local duplication, generic test advice, and abstractions whose cost exceeds their demonstrated benefit.
9. Do not cap valid findings. Bound reviewer concurrency, validation attempts, repair attempts, and repair rounds instead.
10. External review is opt-in. Disclose recipient, route, model-identity uncertainty, code egress, and fallback before dispatch.

## Workflow

### Phase 0 — Freeze scope and gather context

Create a controller run. Read applicable repository instructions, changed files, relevant callers and contracts, tests, documentation, intent, and prior decisions. Record unknowns and incomplete coverage. Fail closed when the base or reviewed tree cannot be established.

### Phase 1 — Generate candidates

Run one bounded read-only reviewer wave. Always cover correctness, fragile-behavior tests, and explicit repository standards/requirements. Add security, privacy, reliability, API-contract, migration, concurrency, performance, documentation, simplification, DRY, or architecture lenses only when the actual diff warrants them. Do not seed reviewers with another reviewer's candidates.

### Phase 2 — Validate and adjudicate

Independently validate each candidate against source, callers, guards, tests, standards, and diff causality. Deduplicate true semantic duplicates without combining distinct failure modes. Produce all kept findings, every discarded candidate and reason code, validation method, evidence and counterevidence, merge readiness, and coverage limitations.

### Gate A — User validates findings

Stop. Present the frozen scope/hash, coverage, merge-readiness decision, every kept `F###`, every discarded candidate, validation confidence, and limitations. Ask the user to approve, reject, or defer each kept finding. Persist the exact decision against the scope and ledger hashes. Do not plan or edit until Gate A is complete.

### Phase 3 — Plan approved findings

Create exactly one plan item for every approved finding and no others. Specify root cause, intended observable result, exact repair steps, exact file/symlink paths, dependencies, exact non-mutating test commands, manual evidence where necessary, risk controls, rollback, and bounded attempts. Prohibit unrelated cleanup and new improvements.

### Gate B — User validates the repair plan

Stop. Present the exact plan, allowed paths, commands, risks, assumptions, rollback, and retry limits. Persist approval against the exact plan hash. Do not edit before approval.

### Phase 4 — Repair resiliently

For each approved finding: verify no drift; create a checkpoint; apply the smallest root-cause repair inside approved paths; run only approved validation commands; audit path/index/branch/HEAD/test-induced mutation; retain only when checks pass; otherwise restore; retry only within budget. Never stage, commit, push, switch branches, open a PR, file a ticket, or modify unrelated paths.

### Phase 5 — Verify completion

Review the repair delta against the frozen pre-fix state. Re-evaluate every approved finding and check only regressions caused by its repair. Do not start another broad review. Unrelated observations are record-only. A repair loop is allowed only for unresolved approved findings or fix-caused regressions within approved paths, strategy, and budget. New paths or strategy require restoration and a newly approved plan.

## Completion output

Report `COMPLETE`, `BLOCKED`, `PLAN AMENDMENT REQUIRED`, or `ABORTED`; reviewed scope and hashes; approved/rejected/deferred/fixed/restored/unresolved findings; commands and statuses; repair-layer paths; regressions checked; both gate receipts; degraded or unverified areas; and artifact directory. Stop after the report. Do not recommend another broad review pass.
