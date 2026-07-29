# Controller workflow and command matrix

The canonical skill defines the judgment contract. `reviewctl.py` enforces state, hashes, exact IDs, paths, test records, checkpoints, and bounded loops.

| State | Command | Result |
|---|---|---|
| new | `init` | `CONTEXT_FROZEN`, immutable source/diff bundle, and root-owned `material_review` workflow profile |
| context | `check-scope` | confirms current identity still matches |
| context | `record-coverage --input ...` | records the scope- and workflow-profile-bound root-owned lens roster and risk signals |
| context | `record-reviewer-failure ...` | records one hash-bound root controller/scheduler attestation when an assigned required route produced no readable draft |
| context | `check-candidates --lens ... --input ...` | writes primary-route attempt 1 without advancing phase |
| context | `check-candidates ... --supersedes HASH` | writes primary-route attempt 2 for the one author-owned mechanical correction |
| context | `assign-fallback ...` | binds the exact failed-primary trigger to the actual fallback identity in a root-owned immutable assignment |
| context | `check-candidates ... --fallback` | writes fallback-route attempt 1 only after its draft matches the verified fallback assignment |
| context | `ingest-candidates --input ...` | verifies exact preflighted bytes and writes normalized candidates only when required coverage is complete |
| context | `finalize-coverage` | writes hash-bound incomplete status and terminal `REVIEW_INCOMPLETE` only after every incomplete required route is evidenced and its fallback authority exhausted |
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
| fixing, all fixed | `refresh-finding-test --finding F### --test ID` | reruns one exact required finding command at final state without consuming repair budgets |
| fixing | `run-global-test --test ID` | records exact approved plan-level validation |
| fixing, all fixed | `begin-pre-verification-repair ...` | binds the latest failed or stale required test evidence to exact approved repair targets and consumes one shared repair round |
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

Multiple candidate inputs may be ingested in one command only after `record-coverage` and a valid `check-candidates` receipt for each input. State and artifacts address receipts by `{lens}/{primary|fallback}/attempt-N`; primary has at most two attempts, fallback exactly one, and neither route can resume or supersede the other. A route may instead have one root-owned `reviewer-failure-attestation/v1` only when it produced no readable draft; receipts and attestations are mutually exclusive. A fallback additionally requires `fallback-assignments/{lens}.json`, bound to the scope, plan, profile, exact receipt-or-attestation trigger, actual actor identity, and canonical assignment hash. Coverage status names the completion route and actual identity while preserving receipt and attestation provenance, the assignment, degraded marker, rejected fallback, and controlled diagnostics. The controller-owned `evidence_handling` provenance is `standard` unless primary attempt 2 supersedes an unparseable attempt 1, in which case it is `unparseable_origin_degraded`; this is independent of fallback-route degradation and propagates through coverage plus normalized reviewer and finding records without changing candidate-set/v1. `finalize-coverage` accepts no candidate input and requires terminal evidence for every incomplete required route; it cannot consume a pending correction or unused fallback. Provisional grouping consumes the normalized candidate bundle; every retained group then receives a repair audit. Final adjudication consumes the normalized candidate bundle hash and its complete coverage status plus the audit's exact scope, candidate-ID, and repair-direction-hash bindings. Fix-plan/v2 consumes the Gate A receipt and its hash-verified ledger, then binds each approved item to the exact direction hash and complete constraint, state/exception, and decision coverage. Verification consumes the approved plan hash and prepared fix-summary hash. Any mismatch fails closed.

Final-state refresh and pre-verification recovery are separate authorities. `refresh-finding-test` can only reuse a required command from the approved plan and records evidence bound to the latest retained attempt, current item-path hash, current workspace guard, and exact test definition; it changes no finding status and consumes no attempt or repair round. `begin-pre-verification-repair` requires the exact hash of the latest failed or stale required test evidence, a non-empty causal rationale, exact approved target IDs, remaining per-finding attempts, and a remaining shared repair round. It never accepts current passing evidence and never grants new paths, commands, IDs, or strategy.

Run `python3 scripts/reviewctl.py <command> --help` for exact flags. On Windows use `py -3`.

`init --scope pull_request` is a distinct immutable GitHub review scope. It verifies the repository-qualified identity and exact host base/head pair before run creation, persists that provenance separately, and freezes `merge-base(host_base, host_head)..host_head`. Ordinary `scope=range` retains its direct base-to-head `comparison_kind=commit` identity. Material simplification does not expose the pull-request selector.
