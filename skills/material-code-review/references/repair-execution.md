# Approved repair execution

Read this reference **before `begin-fix`, any per-finding repair, test execution or refresh, rollback, or abort**, including a bounded repair round. Forward repair and test execution require Gate B approval of the exact current plan, IDs, paths, commands, and budgets, still accepted by the controller. Recovery instead follows the saved checkpoint and controller-supported conditional restoration boundary; it grants no forward authority, including for historical runs or invalidated plans. Read the [fixer template](fixer-template.md) before implementing a repair.

Paths such as `references/...` and `schemas/...` below are relative to `SKILL_DIR`. On resumption, inspect the persisted state, active checkpoint, receipts, and budgets before choosing a command; do not restart an active finding or infer missing authority.

### Phase 4 — Repair approved findings

#### 4.1 Begin the repair layer

Only after Gate B:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" begin-fix --repo-root .
```

This rechecks the frozen scope, confirms the working tree is mutable/aligned, captures a pre-fix v4 restoration checkpoint, and establishes a workspace guard. The checkpoint binds HEAD attachment and commit, the complete refs namespace, semantic Git-index content, workspace state, and path snapshots. Do not stage or commit.

#### 4.2 Per-finding cycle

Process one finding at a time unless the plan explicitly declares a shared atomic repair. Respect dependencies.

Start a checkpoint:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" start-finding --repo-root . --finding F001
```

Then make only the approved changes. Prefer the smallest root-cause correction, but do not preserve a broken architecture merely to minimize line count. Do not perform opportunistic cleanup.

Execute each approved required test through the control tool so the command, output, timeout, and exit code are durable. Tests are evidence, not edit steps: any workspace, index, HEAD, or refs mutation caused by a test is rejected and restored only when a proven conditional component boundary is available. V4 recovery uses ordered expected-old transactions for symbolic HEAD and the complete changed-ref set, holds the canonical Git index lock while rechecking semantic index identity, and permits worktree writes only for exclusive creation from an expected-missing path. Git forbids changing symbolic `HEAD` and its current referent in one transaction, so that overlapping referent is conditionally handled after `HEAD`; a later failure may leave extra authority for reconciliation but never overwrites concurrent authority. Existing-path replacement or deletion fails before recovery authority writes and requires manual reconciliation.

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

Automatic rollback is limited to deltas on the finding's approved paths and to component transitions with a proven conditional primitive. HEAD/ref transactions, cooperative index-lock restoration, and expected-missing worktree creation may proceed; replacing or deleting an existing worktree path does not. Unsupported transitions, unrelated drift, lock contention, or an expected-old mismatch preserve the repository, write recovery evidence, and stop for human reconciliation.

If the workflow must be abandoned or the plan must expand, restore the entire repair layer:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" abort-fixes \
  --repo-root . \
  --reason "Repair requires an unapproved schema path."
```

This returns the complete saved repository authority only when every required component transition has its approved conditional boundary. Current v4 recovery prepares all worktree actions before authority writes, commits symbolic HEAD and changed refs through ordered expected-old transactions, and holds `index.lock` across semantic verification and index restoration. The current symbolic-HEAD referent is deferred when Git's transaction overlap rule requires it; no global transaction across independently accepted components is claimed. Worktree no-ops and exclusive creation from expected missing are supported; existing-path replacement or deletion fails closed for manual reconciliation. Historical checkpoints remain on their narrower bounded restoration path; missing v4 metadata is never fabricated. Replan and repeat Gate B rather than editing around the boundary.

#### 4.3 Global tests

Run plan-level commands after all finding items pass:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" run-global-test \
  --repo-root . \
  --test focused-suite
```

A green command is not conclusive proof for authorization, migrations, distributed effects, public contracts, or concurrency. Preserve those residual verification limits in the final report.

#### 4.4 Refresh tests invalidated by later shared-file repairs

When a later approved finding changes a path shared with an already-fixed finding, rerun the earlier finding's exact Gate-B-approved test at the final repair state:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" refresh-finding-test \
  --repo-root . \
  --finding F001 \
  --test unit-regression
```

This command is available only in `FIXING` with no active finding and after every approved finding is fixed. It does not reopen the finding, change its status or history, consume an attempt, or authorize a different command. The controller records the refreshed evidence separately, rejects and restores test-caused workspace or repository-control mutations, and binds the result to the retained attempt and current approved-path hash.


After the required finding and global tests are current and pass, load [post-fix verification](postfix-verification.md) before preparing or judging verification. For a plan amendment, use the restoration rules above and load [repair planning](repair-planning.md) before revising or presenting a plan; repeat Gate B. At a failed control point, load the [failure model](failure-model.md) before deciding on recovery.
