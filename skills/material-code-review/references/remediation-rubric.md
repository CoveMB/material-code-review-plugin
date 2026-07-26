# Repair-direction quality rubric

A material finding and a safe repair direction are separate judgments. A finding may remain confirmed when its proposed repair is incomplete, over-broad, or unsafe. Gate A approves the finding for planning; only Gate B approves an exact repair.

## Root cause and scope

A repair direction must:

- address the supported root cause rather than only the visible symptom;
- name the smallest safe change that can remove the defect;
- preserve unrelated behavior and avoid opportunistic cleanup;
- identify the canonical contract owner and affected direct consumers when the change crosses files or schemas.

## Constraints, states, and exceptions

Record the behavior, contracts, permissions, formats, compatibility, and human edits that must remain. Enumerate material finite states and field- or strategy-specific exceptions rather than weakening a universal rule broadly.

Keep orthogonal dimensions separate. Examples include finding confidence versus repair confidence, role requirement versus embedding policy, workflow status versus causal blocked reason, and profile completeness versus human visual approval.

## Authority and user decisions

Do not guess a destination, owner, policy, default, approval, migration choice, compatibility posture, or product meaning. Mark `needs_user_decision` and name the exact unresolved choice when authority is absent.

## Alternatives

For a material or risky finding, compare:

1. leaving the current behavior unchanged;
2. the candidate's literal proposal;
3. the smallest safe root-cause correction; and
4. a wider restructure only when the smaller correction cannot satisfy the contract.

Reject an alternative explicitly when it broadens exceptions, weakens safety, hides a migration, or adds more concepts than it removes.

## Test evidence

Use [test-evidence-rubric.md](test-evidence-rubric.md). Required evidence must distinguish the named failure cause from a generic error, refusal, blocked state, or keyword match.

## Remediation status

Use:

- `reviewed` when the direction is sufficiently bounded for Gate-A presentation;
- `needs_refinement` when the finding is valid but planning must resolve named gaps;
- `needs_user_decision` when product or authority input is required;
- `unsafe_to_apply` when the literal candidate suggestion would create a material defect;
- `insufficient_evidence` when no safe repair direction can yet be supported.

A kept finding may use any status. Do not discard a real defect merely because its original suggestion is weak.
