# Human output templates

## Coverage and assignment status

Before candidate synthesis or Gate A, report:

- frozen scope mode, baseline, comparison, changed paths, untracked policy, and `scope_hash`;
- every change unit's purpose, primary paths, frozen context paths, and `coverage_context_hash`;
- every controlled risk's positive or negative decision and evidence;
- each obligation's risk, required lens, required checks, evidence paths, and exact assignment;
- completion status for every assignment and any blocked, missing, stale, or degraded evidence.

Completion means the controller accepted the structure and evidence fields. It does not prove semantic quality or reviewer cognition.

## Gate A — findings approval for planning

Present the frozen coverage summary, merge-readiness verdict, every kept finding, and every discarded candidate. For each kept `F###`, show exact evidence, consequence and trigger, causality, counterevidence, validation, materiality, source assignments/lenses/independence groups, fix risk, pre-fix verification, provisional repair direction and hash, and repair-audit provenance.

State exactly that Gate A approves findings for repair planning only. It does not approve the provisional direction, exact edits, paths, commands, or mutation. Ask the user to approve, reject, or defer every kept ID. No plan or edit occurs before the response is persisted.

## Gate B — exact plan approval

For every approved `F###`, show root cause, objective, approved direction hash, exact handling for every constraint and state/exception, open user decisions, alternatives, divergence rationale, ordered steps, exact paths and commands, causal test evidence, manual checks, dependencies, risks, rollback, success evidence, and attempt limit. Show global tests, scope-expansion behavior, and maximum repair rounds. Ask for explicit approval or rejection of this exact plan hash.

## Final report

State `COMPLETE`, `BLOCKED`, `PLAN AMENDMENT REQUIRED`, or `ABORTED`; original scope and hashes; coverage/obligation/assignment completion; Gate A/B receipts; kept/discarded/user-rejected/user-deferred/fixed/restored/unresolved findings; repair paths; commands and exit statuses; verification result; degraded areas; human-review limits; and artifact directory.

Do not recommend another broad review pass. Use `No material improvements recommended.` only when the ledger kept zero findings and the user explicitly accepted the empty set at Gate A.
