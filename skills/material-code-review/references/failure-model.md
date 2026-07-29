# Failure model and fail-closed behavior

| Failure | Required response |
|---|---|
| Repository/base/comparison cannot be resolved | Stop. Do not substitute a narrower diff. |
| Pull-request metadata is absent, incomplete, not repository-qualified, attached to another scope, or disagrees with the resolved host refs | Stop before run creation. Never fall back to the head parent or a direct range. |
| Frozen scope changed | Invalidate downstream artifacts and refreeze. |
| Ref/remote source unavailable | Mark coverage incomplete or stop; never inspect unrelated workspace files. |
| Malformed reviewer JSON | Reject the output. Do not repair it by guessing. |
| Coverage plan missing, stale, or incomplete | Stop before candidate dispatch or ingestion and repair the root-owned plan. |
| Coverage plan workflow profile differs from the root-owned run profile | Reject before recording coverage; do not let a reviewer or candidate select another workflow's lens policy. |
| Candidate draft is mechanically correctable | Permit primary-route attempt 2 only with the exact `--supersedes` hash; reject substantive drift, a third primary attempt, or primary resumption after fallback. |
| Assigned required route produces no readable draft | Only the observing root controller/scheduler may record `reviewer-failure-attestation/v1`; store a controlled reason and bounded numeric diagnostics, never candidate substance, free-form text, secrets, or raw logs. |
| Readable bytes exist | Keep them on candidate preflight; never reclassify malformed, invalid, or rejected output as no-output. |
| Required primary route fails | Record one root-owned fallback assignment bound to the exact latest failure trigger and actual actor identity; a correctable attempt with unused correction authority is not yet a failed route. |
| Fallback assignment is absent, stale, forged, duplicated, or mismatches the draft | Stop before fallback preflight without consuming fallback authority. |
| Required fallback is assigned | Run fallback-route attempt 1 only when declared; preserve primary diagnostics and assignment provenance, and reject fallback correction, repetition, or primary resumption. |
| Required lens remains unavailable after every permitted route has terminal evidence | Run `finalize-coverage`; persist `REVIEW_INCOMPLETE`, preserve receipt/attestation provenance, emit no candidates or merge verdict, and do not proceed to Gate A. |
| Required route lacks terminal evidence or retains unused correction/fallback authority | Refuse coverage finalization; do not infer failure from silence. |
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
| Earlier required finding test is stale after a later approved overlapping edit | Use `refresh-finding-test` for that exact approved command after all findings are fixed; do not reopen or consume a budget when no code change is needed. |
| Latest failed or stale required test evidence requires another code change before verification | Use `begin-pre-verification-repair` with the exact latest evidence hash, causal target IDs, and rationale; consume the existing attempt and shared repair-round budgets. |
| Recovery evidence is passing, nonlatest, optional, unbound, wrong-ID, out of plan, or budget-exhausted | Reject recovery authority and preserve the current fixed state. |
| Branch, HEAD, index, or unrelated workspace drift | Stop or restore according to controller output. |
| Repair needs a new path/strategy | Abort/restore repair layer and require a new plan plus Gate B. |
| Post-fix unrelated issue | Record-only; no repair loop. |
| Attempt or repair-round budget exhausted | `BLOCKED`; never continue indefinitely. |
| External reviewer route unavailable | Fall back locally only if policy permits and record the degraded route. Never silently egress elsewhere. |

Never convert a failed control into an optimistic prose claim. Preserve the last valid state and report the exact precondition that failed.
