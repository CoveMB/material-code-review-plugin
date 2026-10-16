# Repair planning and Gate B

Read this reference **before drafting or validating a repair plan, presenting Gate B, or recording a Gate B response**. Prerequisites: the frozen run and ledger remain valid, Gate A has a persisted explicit user decision, and the plan includes only its approved IDs. With no approved IDs, report the recorded decision without entering repair planning.

Paths such as `references/...` and `schemas/...` below are relative to `SKILL_DIR`. Before planning, also read the applicable remediation and test-evidence rubrics required by [the entrypoint](../SKILL.md#reference-loading).

The tool is not a sandbox; a command runs with the current user's host permissions, so Gate B must review commands for filesystem, network, credential, process, and Git effects.

Before choosing the rollback strategy or presenting Gate B, read and apply the [shared restoration boundaries](../SKILL.md#restoration-boundaries). Do not promise automatic rollback where those constraints require human reconciliation.

### Phase 3 — Plan approved findings

Use `references/planner-template.md` and `schemas/fix-plan.schema.json`. In Codex, a bounded `default` planning subagent may draft the plan after Gate A. Planning remains read-only and grants no edit permission; only the controller presents and records Gate B.

The plan must include every Gate-A-approved ID exactly once and no rejected/deferred ID. Each item must define:

- root cause and observable goal;
- a `repair_direction_assessment` bound to the approved direction hash, with one exact handling record for every constraint, state/exception, and open user decision;
- alternatives considered, an explicit divergence flag, and a rationale whenever the exact plan differs from the approved direction;
- alternatives considered and why the selected repair is the smallest safe root-cause correction;
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

Validation loads the hash-verified ledger through the Gate A receipt and checks exact IDs, the approved direction hash, complete constraint/state/decision coverage, explained divergence, paths, test contracts, dependencies, attempt limits, and loop controls. Legacy fix-plan/v1 payloads are rejected. Validation does not grant write permission.

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


After explicit approval of the exact validated plan, load [repair execution](repair-execution.md) before `begin-fix` or any repair action. A rejected or revised plan stays in this phase and needs a new Gate B. On resumption, verify the persisted receipts and hashes and reload this reference before planning or a gate decision; earlier context alone is not authority.
