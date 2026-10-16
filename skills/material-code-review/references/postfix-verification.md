# Bounded post-fix verification

Read this reference **before `prepare-verification`, verifier dispatch, judging or recording verification, or deciding whether to reopen a repair**. Prerequisites: all approved findings are fixed, required finding evidence is current, global required tests passed, and the repair delta remains within Gate B. On resumption, verify the persisted state, plan and evidence identities, and remaining budgets before continuing.

Paths such as `references/...` and `schemas/...` below are relative to `SKILL_DIR`.

### Phase 5 — Post-fix verification

Prepare the bounded verification bundle:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" prepare-verification --repo-root .
```

This checks that all approved findings are marked fixed, each required finding test is current through its retained attempt or a final-state refresh, global required tests passed, and the aggregate repair delta remains inside Gate-B paths. It writes a fix-only diff/snapshot summary that includes the refreshed evidence.

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


For `REPAIR_REQUIRED`, load [repair execution](repair-execution.md) before `begin-repair` or another per-finding cycle; afterward reload this reference before verification. For `PLAN_AMENDMENT_REQUIRED`, load repair execution before restoration and [repair planning](repair-planning.md) before replanning and a new Gate B. For `BLOCKED`, load the [failure model](failure-model.md) before recovery decisions. For `COMPLETE`, return to [Final report](../SKILL.md#final-report); do not start a new improvement pass.
