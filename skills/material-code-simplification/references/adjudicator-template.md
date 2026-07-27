# Simplification adjudicator template

Synthesize normalized candidates and validator results into one complete provisional partition, route every provisionally kept group through the inherited repair-direction audit, then compile the same audited partition. You may merge semantic duplicates before audit; you may not invent or omit a candidate or change a group after audit.

## Required process

1. Group only candidates sharing the same root cause, behavior boundary, and transformation implication.
2. Inherit canonical evidence, nature, and category from a source candidate.
3. Preserve source reviewers and actual independence groups exactly.
4. Attach one validator result to every group.
5. Apply every gate in `simplification-rubric.md`.
6. Treat AI provenance, smell names, line count, and static metrics as non-evidential.
7. Test the “leave as is” explanation and smallest local alternative before retaining a boundary restructure.
8. Apply extra rewrite gates and discard rewrites when local work is adequate or behavior is not characterizable.
9. Give every group a provisional `keep` or `discard`, a specific reason, and a valid controller discard code when discarded.
10. Route each provisionally kept group through `$CORE_DIR/references/remediation-auditor-template.md`. Attach its normalized shared `repair_direction` and scope-, candidate-, and direction-hash-bound `repair_audit`, using the preserved behavior, smallest safer alternative, net-reduction shape, characterization evidence, and rewrite limits.
11. If the group, disposition, or direction changes, repeat the affected audit before final compilation. Set both direction and audit to null when discarded.
12. End discovery after the ledger. Do not request another broad pass to improve confidence or find more items.

## Materiality mapping

For a kept simplification candidate:

- `concrete_evidence`: exact current structure is verified;
- `plausible_negative_consequence`: current complexity has a concrete maintenance/operation consequence;
- `beyond_preference`: evidence exceeds style, metrics, provenance, and pattern preference;
- `current_scope_relevance`: candidate belongs to selected codebase/change scope;
- `improvement_current_cost`: true;
- `improvement_benefit_exceeds_churn`: true;
- `coverage_targets_fragile_behavior`: null unless nature is `coverage_gap`.

A validator-rejected candidate cannot be kept. An uncertain optional simplification normally must be discarded or deferred; do not inflate severity to retain it.

## Action posture

Use the shared verdict contract. In whole-codebase mode, interpret `SHOULD FIX BEFORE MERGE` as “recommended before further expansion” in user-facing prose. Use `NOT READY` only for blocker-level risk, not for ordinary bloat.

## Output

Return exactly adjudication/v3 under the shared schema, including one canonical provisional `repair_direction` and bound `repair_audit` for every kept group. Every normalized candidate ID appears in exactly one group. Do not assign `F###` IDs; the controller does that.

A no-findings result is valid and uses `READY`.
