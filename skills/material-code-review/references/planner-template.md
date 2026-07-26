# Approved-finding repair planner template

Planning begins only after Gate A. The input is the approved ledger receipt and its canonical provisional repair directions, not the original candidate list. You are read-only.

Create exactly one item for each approved `F###` and no other item. For each:

- reread the canonical contract owner and all direct consumers affected by the finding;
- state the supported root cause and observable objective;
- rederive the exact repair instead of copying the provisional direction;
- preserve every listed constraint and resolve each material state or exception;
- compare the literal candidate proposal, the smallest safe change, and any wider alternative required by the contract;
- state in the objective or steps when and why the exact plan differs from the provisional repair direction;
- list ordered, concrete steps;
- list exact repository-relative files or final symlinks that may change, including anticipated new files; never authorize a directory;
- list dependencies on other approved findings;
- specify exact non-mutating test commands, working directories, required flags, timeouts, and purposes;
- use `test-evidence-rubric.md` so each required test discriminates the named cause rather than a generic failure;
- place formatters, generators, migrations, fixture rewrites, and other mutating commands in explicit repair steps, not test commands;
- include manual verification only when automated evidence is unavailable;
- include rollback strategy, risk controls, success evidence, and `max_attempts` from 1 to 3.

If planning reveals that the finding itself must be broadened or split, stop for re-adjudication and a new Gate A. If the finding remains the same but the repair strategy changes, present that difference at Gate B.

At plan level set:

- `no_unrelated_cleanup: true`;
- `no_new_improvements_during_fix: true`;
- `post_fix_review_scope: approved_findings_and_fix_introduced_regressions_only`;
- `scope_expansion_policy: restore_and_reapprove`;
- `max_repair_rounds` from 0 to 2.

Return exactly `schemas/fix-plan.schema.json`. Do not edit code or imply that plan validation grants permission; Gate B is still required.
