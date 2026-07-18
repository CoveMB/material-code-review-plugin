# Approved simplification planner template

Planning begins only after Gate A. Input is the approved ledger receipt and frozen architecture/behavior map. Remain read-only.

Create exactly one plan item per approved `F###`. A single item may be an atomic multi-file transformation. If two approved IDs actually share one root cause and indivisible boundary, stop for re-adjudication or plan amendment rather than inventing a combined plan item. Add no new improvements.

## For each item

Specify:

- supported root cause and present cost;
- observable behavior and contracts to preserve;
- transformation class: delete, consolidate, inline, reuse-existing, dependency-reduce, restructure, or bounded-rewrite; because the shared schema has no class field, begin `objective` with `Transformation class: <class>.` and add no extra JSON field;
- why a smaller class is insufficient for restructure/rewrite;
- ordered steps, including characterization before destructive work when behavior is uncertain;
- exact repository-relative files or final symlinks allowed to change, including files to delete and anticipated new files;
- dependencies on other approved findings;
- an overlap audit: same-root-cause/same-boundary work should have been one adjudicated finding; when distinct approved findings unavoidably share paths, order them explicitly and use final-state global required tests because a later edit makes an earlier item's required test hash stale;
- explicit handling for public APIs, persistence, migration, authorization, error semantics, concurrency, generated code, configuration, and dependencies when applicable;
- exact non-mutating test commands, working directories, required flags, timeouts, and purposes;
- when the same characterization command must run before and after the structural change; the pre-change run is baseline evidence, while the latest post-change run must still be current and passing when the item finishes;
- checks that obsolete code, registrations, flags, dependencies, or duplicate paths are gone;
- rollback strategy, risk controls, success evidence, and 1–3 attempts.

Place formatters, generators, migrations, dependency updates, and fixture rewrites in explicit repair steps, not test commands. A test command may not mutate the workspace.

## Test quality guards

- Prefer observable behavior over internal-call assertions.
- Do not delete or weaken a meaningful test merely because it blocks the proposed structure.
- Avoid broad snapshots where precise contracts are available.
- Avoid mocks that simply reproduce the implementation.
- Include authoritative dependency/build resolution when changing packages.
- Prefer disjoint per-item allowed paths. Never conceal a shared path to avoid the controller's freshness check.
- For unavoidable overlap, earlier item-local checks may be optional characterization evidence, while the final relevant regression must be a required global test after every item is fixed.
- Include security, data, migration, concurrency, ordering, or retry tests when those boundaries are touched.
- Manual verification is allowed only when automated evidence is unavailable and must be concrete.

## Plan-level controls

Set exactly:

- `no_unrelated_cleanup: true`;
- `no_new_improvements_during_fix: true`;
- `post_fix_review_scope: approved_findings_and_fix_introduced_regressions_only`;
- `scope_expansion_policy: restore_and_reapprove`;
- `max_repair_rounds`: normally 1, maximum 2.

Return exactly the shared fix-plan schema. Do not imply validation is write permission; Gate B remains mandatory.
