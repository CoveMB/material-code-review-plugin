# Failure model and fail-closed behavior

| Failure | Required response |
|---|---|
| Repository/base/comparison cannot be resolved | Stop. Do not substitute a narrower diff. |
| Frozen scope changed | Invalidate downstream artifacts and refreeze. |
| Coverage plan absent, orphaned, stale, tampered, or different after recording | Stop. The immutable plan cannot be replaced; start a new run for a different plan. |
| Ref/remote source unavailable | Mark coverage incomplete or stop; never inspect unrelated workspace files. |
| Malformed reviewer JSON | Reject the output. Do not repair it by guessing. |
| Missing, duplicate, stale, or wrong-lens candidate set | Reject the entire wave without an authoritative candidate bundle. |
| Zero-file candidate-set/v2 coverage | Reject the entire wave without replacing authoritative candidates; every result must name at least one normalized frozen-scope path even when findings are empty. |
| Risk-path-incomplete candidate set | Reject the entire wave; the assigned lens must review every recorded risk evidence path. |
| Candidate-ingestion failure diagnostic | Treat it as non-authoritative; correct the wave without treating its findings or rejection text as candidates. |
| Corrected complete candidate wave from `CONTEXT_FROZEN` | Retry ingestion. It may proceed only after all plan, identity, lens, scope, and risk-path checks pass. |
| Exact complete candidate retry from `CANDIDATES_CAPTURED` | Verify the existing bundle's embedded hash and state binding, compare the full canonical lens-bearing normalized wave, and succeed without any authoritative or state write. Temporary input filenames and input order do not change identity. |
| Different complete candidate wave from `CANDIDATES_CAPTURED` | Reject it without replacing, pruning, or renumbering the first authority; start a new run. |
| Incomplete, invalid, or unavailable-input retry from `CANDIDATES_CAPTURED` | Update only the non-authoritative ingestion-failure diagnostic. Preserve candidate JSON, derived views, state, hashes, phase, events, timestamps, and IDs byte-for-byte. |
| Missing, tampered, or state-mismatched candidate authority during retry | Fail closed. Do not accept the retry as idempotent and do not recreate or backfill authority; start a new run. |
| All reviewer outputs fail | Report degraded/blocked coverage; do not fabricate findings. |
| Validator unavailable | Use controller-direct only for mechanically authoritative facts; otherwise record degraded self-audit or uncertainty. |
| Validator rejects | Discard with `VALIDATOR_REJECTED`. |
| Validator uncertain | Keep only blocker/high with explicit required pre-fix verification; otherwise discard. |
| Repair auditor unavailable | Use controller-direct only for a mechanically entailed low-risk local correction; otherwise record `degraded_self_audit`. |
| Repair audit absent or mis-bound | Reject adjudication; repeat the affected provisional audit without changing candidate coverage. |
| Group, disposition, or direction changes after audit | Treat the audit as stale and repeat it before final adjudication. |
| Candidate omitted by adjudicator | Reject adjudication as incomplete. |
| Gate A absent | Stop before planning. |
| Plan direction hash is stale or coverage is incomplete | Reject fix-plan/v2; rederive the item from the Gate-A ledger. |
| Plan diverges without a rationale | Reject the plan; make the difference explicit before Gate B. |
| Plan differs after Gate B | Invalidate approval and re-present the new hash. |
| Unapproved path changes | Restore the finding checkpoint and reject the attempt. |
| Required test fails or mutates workspace | Restore when safe; retry only inside budget. |
| A fixed finding's test is stale after a later approved shared-path repair | After every finding is fixed, use `refresh-finding-test` for that finding's exact Gate-B-approved test. Do not reopen the finding or consume another attempt. |
| A refreshed fixed-finding test fails or mutates workspace or repository controls | Record the failed evidence, restore any mutation, and keep verification blocked until the same approved test passes at the current final state. |
| Branch, HEAD, index, or unrelated workspace drift | Stop or restore according to controller output. |
| Repair needs a new path/strategy | Abort/restore repair layer and require a new plan plus Gate B. |
| Post-fix unrelated issue | Record-only; no repair loop. |
| Attempt or repair-round budget exhausted | `BLOCKED`; never continue indefinitely. |
| Unmarked legacy material-review `state/v1` run | Do not migrate it. Stop forward progress with `Run predates required coverage; start a new run.` Safe `status`, `check-scope`, active rollback, and `abort-fixes` restoration remain subject to their existing controls and preserve `state/v1`. |
| Marked material-review `state/v1` run already in final repair | Preserve `state/v1` and allow only fixed-finding test refresh, final global tests, verification preparation, and verification recording in addition to the legacy observation/restoration commands. Every other forward command still requires a new run. |
| Unknown or contradictory state schema/profile identity | Fail before command dispatch and preserve state, artifacts, source, and repository control data unchanged. |
| External reviewer route unavailable | Fall back locally only if policy permits and record the degraded route. Never silently egress elsewhere. |

Never convert a failed control into an optimistic prose claim. Preserve the last valid state and report the exact precondition that failed.
