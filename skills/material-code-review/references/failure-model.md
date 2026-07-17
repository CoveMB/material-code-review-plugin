# Failure model and fail-closed behavior

| Failure | Required response |
|---|---|
| Repository/base/comparison cannot be resolved | Stop. Do not substitute a narrower diff. |
| Frozen scope changed | Invalidate downstream artifacts and refreeze. |
| Ref/remote source unavailable | Mark coverage incomplete or stop; never inspect unrelated workspace files. |
| Malformed reviewer JSON | Reject the output. Do not repair it by guessing. |
| All reviewer outputs fail | Report degraded/blocked coverage; do not fabricate findings. |
| Validator unavailable | Use controller-direct only for mechanically authoritative facts; otherwise record degraded self-audit or uncertainty. |
| Validator rejects | Discard with `VALIDATOR_REJECTED`. |
| Validator uncertain | Keep only blocker/high with explicit required pre-fix verification; otherwise discard. |
| Candidate omitted by adjudicator | Reject adjudication as incomplete. |
| Gate A absent | Stop before planning. |
| Plan differs after Gate B | Invalidate approval and re-present the new hash. |
| Unapproved path changes | Restore the finding checkpoint and reject the attempt. |
| Required test fails or mutates workspace | Restore when safe; retry only inside budget. |
| Branch, HEAD, index, or unrelated workspace drift | Stop or restore according to controller output. |
| Repair needs a new path/strategy | Abort/restore repair layer and require a new plan plus Gate B. |
| Post-fix unrelated issue | Record-only; no repair loop. |
| Attempt or repair-round budget exhausted | `BLOCKED`; never continue indefinitely. |
| External reviewer route unavailable | Fall back locally only if policy permits and record the degraded route. Never silently egress elsewhere. |

Never convert a failed control into an optimistic prose claim. Preserve the last valid state and report the exact precondition that failed.
