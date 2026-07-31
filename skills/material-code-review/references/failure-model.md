# Failure model and fail-closed behavior

| Failure | Required response |
|---|---|
| Repository/base/comparison cannot be resolved | Stop. Do not substitute a narrower diff. |
| Frozen scope or tracked context changed | Invalidate downstream work and start a fresh run. |
| Change-unit inventory misses or duplicates a changed path | Reject coverage; every changed path must occur exactly once as a primary path. |
| Controlled risk decision is missing, duplicated, unknown, or contradictory | Reject coverage; classify every controlled risk exactly once for every unit. |
| Context path is unsafe, untracked, a symlink, deleted, too large, or cannot be frozen | Reject coverage without authoritative plan or context artifacts. |
| Positive risk lacks exactly one obligation or obligation assignment | Reject coverage. A broad or supplemental assignment cannot substitute. |
| Obligation has the wrong lens or check set | Reject coverage before dispatch. |
| Coverage plan/context is absent, orphaned, stale, tampered, or different after recording | Stop. The immutable authority cannot be replaced; start a new run. |
| Ref/remote source unavailable | Mark coverage incomplete or stop; never inspect unrelated workspace files. |
| Malformed candidate-set/v3 JSON | Reject the entire wave. Do not repair it by guessing. |
| Missing, duplicate, stale, unassigned, or identity-mismatched assignment result | Reject the entire wave without authoritative candidates. |
| Required check is absent or duplicated | Reject the entire wave. |
| `pass` lacks evidence | Reject the entire wave. |
| `finding_emitted` lacks evidence, local IDs, or references an unknown local finding | Reject the entire wave. |
| Required check is `blocked` | Treat the obligation as incomplete; do not create candidate authority. |
| Required assignment paths are incomplete | Reject the entire wave. |
| Candidate-ingestion failure diagnostic | Treat it as non-authoritative; its findings and text cannot advance the lifecycle. |
| Corrected complete wave from `CONTEXT_FROZEN` | Retry ingestion only after all assignment, hash, check, and path controls pass. |
| Exact complete retry from `CANDIDATES_CAPTURED` | Verify existing authority and succeed with no authoritative or state write. |
| Different complete retry from `CANDIDATES_CAPTURED` | Reject it without replacement or renumbering; start a new run. |
| Incomplete, invalid, or unavailable-input retry from `CANDIDATES_CAPTURED` | Update only the failure diagnostic and preserve authority byte-for-byte. |
| Missing, tampered, or state-mismatched candidate authority | Fail closed; never backfill it from retry input. |
| All reviewer outputs fail | Report degraded or blocked coverage; never fabricate findings. |
| Validator unavailable | Use controller-direct only for mechanically authoritative facts; otherwise record degraded self-audit or uncertainty. |
| Validator rejects | Discard with `VALIDATOR_REJECTED`. |
| Validator uncertain | Keep only blocker/high with exact pre-fix verification and a user decision; otherwise discard. |
| Repair audit absent or mis-bound | Reject adjudication; repeat only the affected provisional audit. |
| Candidate omitted by adjudicator | Reject adjudication as incomplete. |
| Gate A absent | Stop before planning. |
| Plan direction hash is stale or coverage is incomplete | Reject fix-plan/v2 and rederive from the Gate-A ledger. |
| Plan differs after Gate B | Invalidate approval and re-present the new hash. |
| Unapproved path changes or required test failure | Restore the finding checkpoint and reject the attempt. |
| Repair needs a new path or strategy | Abort and restore the repair layer; require a new plan plus Gate B. |
| Post-fix unrelated issue | Record-only; no repair loop. |
| Attempt or repair-round budget exhausted | `BLOCKED`; never continue indefinitely. |
| Historical material-review `state/v1` or `state/v2` run | Do not migrate it into discovery. Preserve only established inspection, restoration, and marker-bound final-repair completion commands; other forward work requires a state/v3 run. |
| Unknown or contradictory state/profile identity | Fail before dispatch and preserve state, artifacts, source, and repository controls unchanged. |
| External reviewer route unavailable | Fall back locally only if policy permits and record the degraded route. Never silently egress. |

Never convert a failed control into an optimistic prose claim. Preserve the last valid state and report the exact failed precondition.
