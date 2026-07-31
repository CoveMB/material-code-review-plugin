# Controller workflow and command matrix

The canonical skill defines the judgment contract. `reviewctl.py` enforces state, hashes, exact IDs, paths, test records, checkpoints, and bounded loops.

Discovery order is fixed:

```text
init
context record (manual; see references/context-checklist.md)
python3 "$SKILL_DIR/scripts/reviewctl.py" check-scope --repo-root .
record-coverage
dispatch assigned lenses
ingest complete candidate wave
validate
repair-direction audit
compile-ledger
Gate A
validate plan
Gate B
```

New material-review runs are `material-review/state/v2` and require the current review markers. Material-review `state/v1` is not migrated. Unmarked runs retain only `status`, `check-scope`, active `rollback-finding`, and `abort-fixes`. Marked runs in the final repair state may also use `refresh-finding-test`, `run-global-test`, `prepare-verification`, and `record-verification`; every other forward command requires a new run. The shared controller separately recognizes an explicitly profiled material-code-simplification `state/v1` run as forward-capable. Unknown or contradictory schema/profile identities fail before dispatch.

Current material review uses `candidates-normalized/v2`, `adjudication/v4`, and `ledger/v4`. The controller carries only the already validated candidate-set lens into normalized candidates, uses it only as the final candidate sort tie-breaker, and requires every adjudication/ledger source-lens array to equal the sorted unique lens IDs derived from the exact candidate IDs. The first complete normalized candidate wave is write-once: after verifying the existing embedded/state hash binding, a full canonical lens-bearing match is an exact no-write retry, while a different complete wave requires a new run. Temporary input filenames and input order are excluded from authority identity. It never infers, backfills, renumbers, or rewrites legacy hash-bound artifacts. Explicit material simplification remains on `candidates-normalized/v1`, `adjudication/v3`, and `ledger/v3` without lens fields.

| State | Command | Result |
|---|---|---|
| new | `init` | `CONTEXT_FROZEN` and immutable source/diff bundle |
| context | `check-scope` | confirms current identity still matches |
| context | `record-coverage --input ...` | validates and records the immutable scope-bound coverage plan; an identical plan is idempotent and a changed plan requires a new run |
| context with verified coverage plan | `ingest-candidates --input ...` | accepts only a complete valid candidate wave in which every v2 result names at least one normalized frozen-scope path, then writes candidates-normalized/v2 with validated lens provenance; findings may be empty and assigned risk paths remain additional requirements |
| candidates | `ingest-candidates --input ...` | validates the complete wave before authority comparison; an exact canonical retry is a byte-preserving no-op, a different complete wave requires a new run, invalid or unavailable input updates only the non-authoritative failure diagnostic, and missing/tampered/state-mismatched authority fails closed |
| candidates | provisional grouping + repair audit | partitions every candidate once and binds every provisionally kept direction to scope, candidate IDs, and direction hash |
| audited provisional groups | `compile-ledger --input ...` | validates adjudication/v4 plus exact candidate-derived source lenses and writes ledger/v4 with stable `F###` IDs |
| adjudicated | `gate-findings ...` | records user dispositions and Gate A receipt |
| findings approved | `validate-plan --input ...` | loads the Gate-A ledger and validates exact approved IDs plus the direction-bound assessment; no write permission |
| plan validated | `gate-plan --approve|--reject` | records Gate B receipt |
| plan approved | `begin-fix` | captures repair-layer checkpoint and workspace guard |
| fixing | `start-finding --finding F###` | creates per-finding checkpoint |
| fixing | `run-test --finding F### --test ID` | executes exact approved test and audits mutation |
| fixing | `finish-finding ...` | retains a passing in-boundary repair |
| fixing | `rollback-finding ...` | restores the finding checkpoint |
| fixing | `run-global-test --test ID` | records exact approved plan-level validation |
| fixing, all findings fixed | `refresh-finding-test --finding F### --test ID` | reruns the exact approved test at the final repair state, stores evidence outside immutable attempt history, consumes no attempt, and restores any test mutation |
| fixing | `prepare-verification` | verifies fix completion with current retained-or-refreshed finding tests and creates the fix-only bundle |
| verifying | `record-verification --input ...` | records pass, bounded repair requirement, or block |
| repair required | `begin-repair` | reopens only causal in-plan finding IDs within budget |
| mutation phases | `abort-fixes --reason ...` | restores frozen pre-fix state and aborts repair layer |
| any | `status` | renders current state and artifact paths |

## Run ID

Pass `--run-id` to each command or set `MATERIAL_REVIEW_RUN_ID`. Runs are bound to the originating repository.

## Artifact root

The default is the active repository's Git path `material-code-review`. A custom root must be outside the worktree or inside the active Git directory.

## Input order

Multiple candidate inputs may be ingested in one command. Material-review ingestion sorts normalized reviewer sets by validated assignment identity and normalized candidates by their stable identity fields, including the final lens tie-breaker; temporary source filenames are diagnostic context only and are omitted from candidate authority. Provisional grouping consumes the normalized candidate bundle; every retained group then receives a repair audit. Final adjudication consumes the normalized candidate bundle hash and the audit's exact scope, candidate-ID, and repair-direction-hash bindings. Fix-plan/v2 consumes the Gate A receipt and its hash-verified ledger, then binds each approved item to the exact direction hash and complete constraint, state/exception, and decision coverage. Verification consumes the approved plan hash and prepared fix-summary hash. Any mismatch fails closed.

Run `python3 scripts/reviewctl.py <command> --help` for exact flags. On Windows use `py -3`.
