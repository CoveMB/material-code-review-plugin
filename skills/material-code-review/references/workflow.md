# Controller workflow and command matrix

The canonical skill defines the judgment contract. `reviewctl.py` enforces state, hashes, exact IDs, paths, test records, checkpoints, and bounded loops.

| State | Command | Result |
|---|---|---|
| new | `init` | `CONTEXT_FROZEN` and immutable source/diff bundle |
| context | `check-scope` | confirms current identity still matches |
| context | `ingest-candidates --input ...` | validates reviewer JSON and writes normalized candidate bundle |
| candidates | `compile-ledger --input ...` | validates complete adjudication and assigns stable `F###` IDs |
| adjudicated | `gate-findings ...` | records user dispositions and Gate A receipt |
| findings approved | `validate-plan --input ...` | validates exact approved-ID plan; no write permission |
| plan validated | `gate-plan --approve|--reject` | records Gate B receipt |
| plan approved | `begin-fix` | captures repair-layer checkpoint and workspace guard |
| fixing | `start-finding --finding F###` | creates per-finding checkpoint |
| fixing | `run-test --finding F### --test ID` | executes exact approved test and audits mutation |
| fixing | `finish-finding ...` | retains a passing in-boundary repair |
| fixing | `rollback-finding ...` | restores the finding checkpoint |
| fixing | `run-global-test --test ID` | records exact approved plan-level validation |
| fixing | `prepare-verification` | verifies fix completion and creates fix-only bundle |
| verifying | `record-verification --input ...` | records pass, bounded repair requirement, or block |
| repair required | `begin-repair` | reopens only causal in-plan finding IDs within budget |
| mutation phases | `abort-fixes --reason ...` | restores frozen pre-fix state and aborts repair layer |
| any | `status` | renders current state and artifact paths |

## Run ID

Pass `--run-id` to each command or set `MATERIAL_REVIEW_RUN_ID`. Runs are bound to the originating repository.

## Artifact root

The default is the active repository's Git path `material-code-review`. A custom root must be outside the worktree or inside the active Git directory.

## Input order

Multiple candidate inputs may be ingested in one command. Adjudication consumes the normalized candidate bundle hash. The fix plan consumes the Gate A receipt hash. Verification consumes the approved plan hash and prepared fix-summary hash. Any mismatch fails closed.

Run `python3 scripts/reviewctl.py <command> --help` for exact flags. On Windows use `py -3`.
