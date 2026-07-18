# Failure model and recovery rules

## Scope and context

- **No files selected**: fail init; correct selectors.
- **Unbounded or unaffordable scope**: narrow paths and state coverage; do not silently sample.
- **Stale scope before Gate B**: discard downstream artifacts and refreeze.
- **Missing repository intent/contract**: record uncertainty; characterize or discard rather than guessing.
- **Generated/vendor/submodule boundary unknown**: exclude explicitly or require human/tool-specific review.

## Review and adjudication

- **Malformed candidate output**: reject the input visibly. One formatting-only correction may be requested; do not repair substantive claims by guessing.
- **Every candidate rejected by schema/evidence checks**: coverage is invalid; regenerate within the same fixed discovery wave or stop.
- **Subagent unavailable**: run sequentially and record degraded self-audit. Do not pretend persona separation is independence.
- **Validator unavailable**: use controller-direct checks for mechanical facts and expose semantic uncertainty.
- **Candidate requires new discovery to justify itself**: discard or defer; do not recurse.
- **No material candidates**: compile an empty ledger and still obtain Gate A acceptance.

## Gates and plan

- **Missing/ambiguous Gate A**: stop.
- **User approves only the general goal**: not a disposition; request exact IDs.
- **Plan adds an unapproved item**: reject plan.
- **Plan lacks behavior evidence or exact paths**: reject plan.
- **Rewrite boundary is open-ended**: reject or split into bounded approved items.
- **Plan changes after Gate B**: invalidate Gate B and obtain a new receipt.
- **Missing/ambiguous Gate B**: stop.

## Implementation

- **Workspace drift**: stop and reconcile; do not overwrite user/tool changes.
- **Unapproved path changes**: reject the attempt and restore its checkpoint.
- **Test command mutates**: controller restores it; treat the command as failed and revise only through a new Gate B if the command must change.
- **Required test fails**: repair only inside the approved item and remaining attempt budget, otherwise restore/block.
- **Necessary contract/data/security change discovered**: restore and return to Gate B planning.
- **New simplification noticed**: record-only; never expand current repair.
- **Old and new paths both remain unexpectedly**: unresolved; remove within plan or restore.
- **Dependency/API cannot be authoritatively verified**: block dependency transformation.

## Verification

- **Root cause moved rather than removed**: unresolved.
- **Behavior uncertainty remains material**: blocked, not pass.
- **Fix-caused regression inside approved paths**: one bounded repair round if budget remains.
- **Regression requires a new path/strategy**: plan amendment and new Gate B.
- **Unrelated issue found**: record-only.
- **Attempt/repair budget exhausted**: blocked.

## Restoration limits

The controller protects normal Git working-tree and index state. Submodules, sparse checkouts, exotic filters, generated/ignored side effects, external services, databases, and processes may require human recovery. Do not claim automatic rollback beyond captured filesystem/Git boundaries.
