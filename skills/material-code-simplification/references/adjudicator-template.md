# Simplification adjudicator template

Synthesize normalized candidates and validator results into one complete adjudication. You may merge semantic duplicates; you may not invent or omit a candidate.

## Required process

1. Group only candidates sharing the same root cause, behavior boundary, and transformation implication.
2. Inherit canonical evidence, nature, and category from a source candidate.
3. Preserve source reviewers and actual independence groups exactly.
4. Attach one validator result to every group.
5. Apply every gate in `simplification-rubric.md`.
6. Treat AI provenance, smell names, line count, and static metrics as non-evidential.
7. Test the “leave as is” explanation and smallest local alternative before retaining a boundary restructure.
8. Apply extra rewrite gates and discard rewrites when local work is adequate or behavior is not characterizable.
9. Give every group `keep` or `discard`, a specific reason, and a valid controller discard code when discarded.
10. End discovery after the ledger. Do not request another broad pass to improve confidence or find more items.

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

Return exactly one object conforming to the shared adjudication schema. Every normalized candidate ID appears in exactly one group. Do not assign `F###` IDs; the controller does that.

A no-findings result is valid and uses `READY`.
