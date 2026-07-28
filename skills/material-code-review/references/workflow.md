# Controller workflow and command matrix

The canonical skill defines the judgment contract. `reviewctl.py` enforces state, hashes, exact IDs, paths, test records, checkpoints, and bounded loops.

| State | Command | Result |
|---|---|---|
| new | `init` | `CONTEXT_FROZEN` and immutable source/diff bundle |
| context | `check-scope` | confirms current identity still matches |
| context | `record-coverage --input ...` | records the scope-bound root-owned lens roster and risk signals |
| context | `check-candidates --lens ... --input ...` | writes a hash-bound valid, correctable, or rejected receipt without advancing phase |
| context | `check-candidates ... --supersedes HASH` | permits the one mechanical correction attempt without substantive drift |
| context | `check-candidates ... --fallback` | records at most one declared sequential fallback for a failed required lens |
| context | `ingest-candidates --input ...` | verifies exact preflighted bytes and writes normalized candidates only when required coverage is complete |
| context | incomplete required coverage | terminal `REVIEW_INCOMPLETE`; no candidate bundle, merge verdict, adjudication, or Gate A |
| candidates | provisional grouping + repair audit | partitions every candidate once and binds every provisionally kept direction to scope, candidate IDs, and direction hash |
| audited provisional groups | `compile-ledger --input ...` | validates complete final adjudication and assigns stable `F###` IDs |
| adjudicated | `gate-findings ...` | records user dispositions and Gate A receipt |
| findings approved | `validate-plan --input ...` | loads the Gate-A ledger and validates exact approved IDs plus the direction-bound assessment; no write permission |
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

Multiple candidate inputs may be ingested in one command only after `record-coverage` and a valid `check-candidates` receipt for each input. Rejected primary, fallback, and optional coverage remains in `coverage-status.json`. Provisional grouping consumes the normalized candidate bundle; every retained group then receives a repair audit. Final adjudication consumes the normalized candidate bundle hash and its complete coverage status plus the audit's exact scope, candidate-ID, and repair-direction-hash bindings. Fix-plan/v2 consumes the Gate A receipt and its hash-verified ledger, then binds each approved item to the exact direction hash and complete constraint, state/exception, and decision coverage. Verification consumes the approved plan hash and prepared fix-summary hash. Any mismatch fails closed.

Run `python3 scripts/reviewctl.py <command> --help` for exact flags. On Windows use `py -3`.
