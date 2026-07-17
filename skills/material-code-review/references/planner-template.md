# Approved-finding repair planner template

Planning begins only after Gate A. The input is the approved ledger receipt, not the original candidate list. You are read-only.

Create exactly one item for each approved `F###` and no other item. For each:

- state the supported root cause and observable objective;
- list ordered, concrete steps;
- list exact repository-relative files or final symlinks that may change, including anticipated new files; never authorize a directory;
- list dependencies on other approved findings;
- specify exact non-mutating test commands, working directories, required flags, timeouts, and purposes;
- place formatters, generators, migrations, fixture rewrites, and other mutating commands in explicit repair steps, not test commands;
- include manual verification only when automated evidence is unavailable;
- include rollback strategy, risk controls, success evidence, and `max_attempts` from 1 to 3.

At plan level set:

- `no_unrelated_cleanup: true`;
- `no_new_improvements_during_fix: true`;
- `post_fix_review_scope: approved_findings_and_fix_introduced_regressions_only`;
- `scope_expansion_policy: restore_and_reapprove`;
- `max_repair_rounds` from 0 to 2.

Return exactly `schemas/fix-plan.schema.json`. Do not edit code or imply that plan validation grants permission; Gate B is still required.
