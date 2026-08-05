# Controller workflow and command matrix

The canonical skill defines the judgment contract. `reviewctl.py` enforces state, hashes, exact IDs, paths, test records, checkpoints, and bounded loops.

Discovery order is fixed:

```text
init
context record and change-unit inventory (manual; see references/context-checklist.md)
python3 "$SKILL_DIR/scripts/reviewctl.py" check-scope --repo-root .
record-coverage
dispatch assignments
ingest one complete assignment-matched wave
validate
repair-direction audit
compile-ledger
Gate A
validate plan
Gate B
```

New material-review runs use `material-review/state/v5`, `coverage-plan/v4`, `candidate-set/v5`, and `candidates-normalized/v5`. Material-review `state/v1` through `state/v4` runs are not migrated, backfilled, or reinterpreted to infer atomic scenario evidence. They retain only bounded inspection and checkpointed restoration commands; forward commands require a new run. The shared controller separately recognizes explicitly profiled material-code-simplification `state/v1` as forward-capable with its established candidate and ledger contracts.

Material-review normalized reviewer sets retain assignment identity, lens, obligation identity when applicable, exact required paths and checks, specialist unit/path/scenario provenance, resolved check results, and reviewed coverage. Local finding IDs in `finding_emitted` results become canonical candidate IDs only after deterministic candidate ordering. Temporary filenames and input order never become authority.

Current checkpoints use `material-review/checkpoint/v4`. They bind HEAD attachment and commit, the complete refs namespace, semantic index content, workspace guard, and exact path snapshots. Rollback, abort, finding-test cleanup, global-test cleanup, and final refresh all use one recovery engine with a caller-bound expected post-command observation. Manual rollback and abort bind only approved-path repair deltas; ref, HEAD, index, or unrelated-path drift is preserved for human reconciliation. The engine compares complete authority before its first repository write, uses expected-old ref updates, and verifies the complete restored authority. A conflict or incomplete restore writes structured recovery evidence and stops for human recovery. Historical checkpoints remain isolated on bounded legacy restoration.

| State | Command | Result |
|---|---|---|
| new | `init` | `CONTEXT_FROZEN` and immutable source/diff bundle |
| context | `check-scope` | confirms current identity still matches |
| context | `record-coverage --input ...` | validates the exact change-unit owner/consumer partition, exhaustive risk and specialist scenario decisions, derived assignment paths/checks, obligations, assignments, and frozen context; an identical plan/context is idempotent |
| context with verified coverage | `ingest-candidates --input ...` | accepts exactly one complete assignment-matched candidate-set/v5 wave and writes candidates-normalized/v5; findings may be empty but required checks, evidence, and paths may not |
| candidates | `ingest-candidates --input ...` | exact canonical retry is no-write; a different complete wave requires a new run; invalid input updates only the non-authoritative failure diagnostic |
| candidates | provisional grouping + repair audit | partitions every candidate once and binds every provisionally kept direction to scope, candidate IDs, and direction hash |
| audited provisional groups | `compile-ledger --input ...` | validates adjudication/v4 plus exact candidate-derived source lenses and writes ledger/v4 |
| adjudicated | `gate-findings ...` | records user dispositions and Gate A receipt |
| findings approved | `validate-plan --input ...` | validates exact approved IDs and direction-bound assessment; no write permission |
| plan validated | `gate-plan --approve|--reject` | records Gate B receipt |
| plan approved | `begin-fix` | captures repair-layer checkpoint and workspace guard |
| fixing | `start-finding --finding F###` | creates per-finding checkpoint |
| fixing | `run-test --finding F### --test ID` | executes exact approved test and audits mutation |
| fixing | `finish-finding ...` | retains a passing in-boundary repair |
| fixing | `rollback-finding ...` | restores the finding checkpoint when only approved paths differ; otherwise preserves drift and stops |
| fixing | `run-global-test --test ID` | records exact approved plan-level validation |
| fixing, all findings fixed | `refresh-finding-test --finding F### --test ID` | refreshes exact approved evidence at the final shared tree without consuming an attempt |
| fixing | `prepare-verification` | verifies fix completion and creates the fix-only bundle |
| verifying | `record-verification --input ...` | records pass, bounded repair requirement, or block |
| repair required | `begin-repair` | reopens only causal in-plan finding IDs within budget |
| mutation phases | `abort-fixes --reason ...` | restores frozen pre-fix state when only plan-approved paths differ; otherwise preserves drift and stops |
| any | `status` | renders current state and artifact paths |

## Input order and authority

Material-review ingestion sorts reviewer sets by validated assignment identity and candidates by stable identity fields. Every retained group receives a repair audit. Adjudication consumes the normalized candidate bundle hash. Fix-plan/v2 consumes the Gate A receipt and hash-verified ledger. Verification consumes the approved plan hash and prepared fix-summary hash. Any mismatch fails closed.

Pass `--run-id` to each command or set `MATERIAL_REVIEW_RUN_ID`. Run `python3 scripts/reviewctl.py <command> --help` for exact flags. On Windows use `py -3`.
