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
| Artifact run or authoritative descendant is initially a symlink/reparse point, is rebound during a command, or no complete platform capability is available | Fail before the next mutation and never fall back to pathname writes. Identity-bound writes remain in the retained original directory; the rebound target is untouched. |
| Artifact run is renamed after an identity-bound replacement | Stop with terminal evidence that a bounded mutation may exist in the renamed original identity. Do not report success at the old name or attempt pathname rollback. |
| Ref/remote source unavailable | Mark coverage incomplete or stop; never inspect unrelated workspace files. |
| Specialist decision is missing, duplicated, unknown, or unsupported | Reject coverage; classify all eight specialist lenses exactly once for every unit. Ambiguous or unknown applicability selects the lens. |
| Selected specialist lacks atomic scenarios, repeats a scenario code, uses a generic claim/countercontrol, or cites a path outside its unit | Reject coverage before dispatch. Rejected specialists must have no scenarios. |
| Specialist assignment is missing, duplicated, wrong-lens, wrong-unit, or wrong-path | Reject coverage. It cannot substitute for core or obligation authority. |
| Assignment `required_review_paths` or `required_checks` differs from controller derivation | Reject coverage before dispatch. Do not widen or narrow authority manually. |
| Malformed candidate-set/v6 JSON | Reject the entire wave. Do not repair it by guessing. |
| Missing, duplicate, stale, unassigned, or identity-mismatched assignment result | Reject the entire wave without authoritative candidates. |
| Required check is absent or duplicated | Reject the entire wave. |
| Obligation evidence item is absent, duplicated, unknown, or reconstructed instead of using its machine-owned check contract | Reject the entire wave. Every required evidence item must occur exactly once. |
| An `all_required_review_paths` evidence item omits any assignment path | Reject the entire wave. Assignment-wide `coverage.files_reviewed` cannot substitute for the check-specific all-path trace. |
| `pass` lacks evidence | Reject the entire wave. |
| `finding_emitted` lacks evidence, local IDs, or references an unknown local finding | Reject the entire wave. |
| Required obligation or specialist check is `blocked` | Treat the wave as incomplete; do not create candidate authority. |
| Check evidence path is outside assignment authority or absent from reviewed coverage | Reject the entire wave. Evidence must remain exact and path-bound. |
| Limitation names a non-blocked check, or an unresolved check appears only as a general limitation or another check's finding | Reject the entire wave. Return the affected check as `blocked`, obtain the missing evidence, and submit a new complete wave; the controller must not infer an outcome. |
| One `finding_local_id` is reused across multiple required check results | Reject the entire wave. Each finding may discharge only the single atomic check whose evidence it records; return independent outcomes for every other check. |
| Required assignment paths are incomplete | Reject the entire wave. |
| Evidence side/path resolves to a changed-path entry frozen as missing | Reject the evidence as missing. Do not fall through to coverage context. |
| Evidence side/path has no changed-path match | Comparison evidence may use only an exact frozen coverage-context path; baseline evidence has no context fallback. |
| Frozen evidence bytes or requested line range do not match | Reject the candidate evidence. Do not search another side or alias. |
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
| Required test failure or failed attempt limited to approved paths | Restore the finding checkpoint and reject the attempt. |
| Manual rollback or abort observes ref, HEAD, index, or unrelated-path drift | Preserve the repository, record recovery-conflict evidence, and require human reconciliation; do not infer that the drift belongs to the repair. |
| Repair needs a new path or strategy | Abort and restore the repair layer; require a new plan plus Gate B. |
| V4 recovery observation no longer matches current HEAD, refs, index, or workspace | Fail before the first repository write, record structured recovery-conflict evidence, and require human reconciliation. |
| V4 worktree recovery would replace or delete an existing path, or its parent is no longer unchanged | Fail during preflight before recovery authority writes, preserve the path, record recovery-conflict evidence, and require manual reconciliation. Only no-op and exclusive expected-missing creation are automatic. |
| Required symbolic-ref transactions are unsupported or `index.lock` cannot be acquired with the expected semantic index identity | Fail closed, preserve repository authority, record recovery-conflict evidence, and require manual reconciliation; do not fall back to unconditional writes. |
| V4 recovery write or final authority verification fails | Record structured recovery evidence and stop for human recovery; do not continue the lifecycle. |
| Historical checkpoint lacks v4 repository authority | Use only the isolated bounded legacy restore path. Never synthesize missing HEAD/ref/index authority. |
| Post-fix unrelated issue | Record-only; no repair loop. |
| Attempt or repair-round budget exhausted | `BLOCKED`; never continue indefinitely. |
| Historical material-review `state/v1` through `state/v5` run | Do not migrate, backfill, or reinterpret it into discovery. Preserve only bounded inspection and checkpointed restoration; forward work requires a state/v6 run. |
| Unknown or contradictory state/profile identity | Fail before dispatch and preserve state, artifacts, source, and repository controls unchanged. |
| External reviewer route unavailable | Fall back locally only if policy permits and record the degraded route. Never silently egress. |

Never convert a failed control into an optimistic prose claim. Preserve the last valid state and report the exact failed precondition.
