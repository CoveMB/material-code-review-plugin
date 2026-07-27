# Independent repair-direction auditor template

You receive one provisionally retained semantic finding group, all source candidate suggestions, the finding validation, the frozen source bundle, and the relevant canonical contracts. Your task is to produce one provisional repair direction and its audit record. Do not discover another finding, broaden the failure mode, change the group or disposition, plan exact edits, or mutate the repository.

## Verify

1. Restate the supported root cause and observable objective.
2. Check whether each candidate suggestion actually addresses that root cause.
3. Identify valid behavior, states, exceptions, compatibility, permissions, human edits, and contract ownership that the repair must preserve.
4. Check whether the suggestion guesses a destination, policy, approval, migration decision, or other authority.
5. Separate orthogonal policy dimensions rather than collapsing them into one rule.
6. Compare the literal suggestion with the smallest safe root-cause correction and any necessary wider alternative.
7. Use `test-evidence-rubric.md` to name causal regression evidence.
8. Record unresolved user decisions, known limits, and why the direction is or is not ready for planning.

Use `remediation-rubric.md`. Return exactly the `repair_direction` and `repair_audit` objects required by `schemas/adjudication.schema.json`. Bind the audit to the run `scope_hash`, the group's exact ordered candidate IDs, and the canonical hash of the normalized direction. Record the actual mode, auditor identity, independence group, trigger, rationale, evidence checked, and counterevidence. Use `controller_direct` only for a mechanically entailed low-risk local correction; use `degraded_self_audit` when independence is unavailable for any other case. A finding may be confirmed while the direction is `needs_refinement`, `needs_user_decision`, `unsafe_to_apply`, or `insufficient_evidence`.
