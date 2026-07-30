# Failure model and fail-closed behavior

| Failure | Required response |
|---|---|
| Repository/base/comparison cannot be resolved | Stop. Do not substitute a narrower diff. |
| Frozen scope changed | Invalidate downstream artifacts and refreeze. |
| Coverage plan absent, orphaned, stale, tampered, or different after recording | Stop. The immutable plan cannot be replaced; start a new run for a different plan. |
| Ref/remote source unavailable | Mark coverage incomplete or stop; never inspect unrelated workspace files. |
| Malformed reviewer JSON | Reject the output. Do not repair it by guessing. |
| Missing, duplicate, stale, or wrong-lens candidate set | Reject the entire wave without an authoritative candidate bundle. |
| Risk-path-incomplete candidate set | Reject the entire wave; the assigned lens must review every recorded risk evidence path. |
| Candidate-ingestion failure diagnostic | Treat it as non-authoritative; correct the wave without treating its findings or rejection text as candidates. |
| Corrected complete candidate wave from `CONTEXT_FROZEN` | Retry ingestion. It may proceed only after all plan, identity, lens, scope, and risk-path checks pass. |
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
| Branch, HEAD, index, or unrelated workspace drift | Stop or restore according to controller output. |
| Repair needs a new path/strategy | Abort/restore repair layer and require a new plan plus Gate B. |
| Post-fix unrelated issue | Record-only; no repair loop. |
| Attempt or repair-round budget exhausted | `BLOCKED`; never continue indefinitely. |
| Legacy material-review run | Stop forward progress with `Run predates required coverage; start a new run.` Safe `status`, `check-scope`, active rollback, and `abort-fixes` restoration remain subject to their existing controls. |
| External reviewer route unavailable | Fall back locally only if policy permits and record the degraded route. Never silently egress elsewhere. |

Never convert a failed control into an optimistic prose claim. Preserve the last valid state and report the exact precondition that failed.
