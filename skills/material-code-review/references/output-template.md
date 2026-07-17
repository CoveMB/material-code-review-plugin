# Human output templates

## Gate A — findings approval

Present this information before asking for any decision:

### Frozen scope
- mode, baseline, comparison, branch/HEAD, changed files, untracked policy, `scope_hash`;
- intent and confidence;
- reviewer lenses, validators, actual independence groups, failed/degraded coverage.

### Merge-readiness
Use exactly one: `READY`, `READY WITH OPTIONAL FOLLOW-UPS`, `SHOULD FIX BEFORE MERGE`, `NOT READY`. Explain the load-bearing reason.

### Kept findings
For every `F###`: title; nature/category; severity/confidence; recommendation; exact evidence; consequence and trigger; causality; counterevidence checked; validation result; materiality reason; fix risk; required pre-fix verification.

### Discarded candidates
List every group with candidate IDs, title, discard code, and concrete reason. Do not hide duplicate, style, speculative, or validator-rejected candidates.

### Gate A request
Ask the user to approve, reject, or defer every kept `F###`. State that no plan or edit will occur before the response is persisted.

## Gate B — plan approval

For every approved `F###`, show root cause, objective, ordered steps, exact paths, exact commands, manual checks, dependencies, risks, rollback, success evidence, and attempt limit. Show global tests, scope-expansion behavior, and maximum repair rounds. Ask for explicit approval or rejection of this exact plan hash.

## Final report

State `COMPLETE`, `BLOCKED`, `PLAN AMENDMENT REQUIRED`, or `ABORTED`; original scope and hashes; Gate A/B receipts; kept/discarded/user-rejected/user-deferred/fixed/restored/unresolved findings; repair-layer paths; commands and exit statuses; verification result; degraded areas; human-review limits; and artifact directory.

Do not recommend another broad review pass. Use `No material improvements recommended.` only when the ledger kept zero findings and the user explicitly accepted the empty set at Gate A.
