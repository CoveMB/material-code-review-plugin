# Finding adjudicator template

Synthesize the normalized candidate bundle, validator results, and any repair-direction audit into one complete ledger. You may merge semantic duplicates, but you may not invent a concern or omit a candidate.

## Required process

1. Group only candidates that share the same failure mode and repair implication. Nearby but distinct consequences remain separate.
2. Inherit canonical evidence, nature, and category from a source candidate.
3. List source reviewers and independence groups exactly.
4. Attach a valid validator result to every group.
5. Apply `materiality-rubric.md` separately to defects and optional improvements.
6. Give every group `keep` or `discard`, a specific reason, and a coded discard reason when discarded.
7. Do not use cross-reviewer agreement as proof when reviewers share an independence group.
8. For every kept group, produce one canonical `repair_direction` under `remediation-rubric.md`. Do not copy one representative candidate's suggestion without checking constraints, exceptions, authority, alternatives, and causal test evidence.
9. Keep finding confidence separate from repair-direction confidence. A real finding may retain a non-reviewed remediation status.
10. Set `repair_direction` to null for every discarded group.
11. Select the merge-readiness verdict from actual kept findings.

## Output

Return exactly one object conforming to `schemas/adjudication.schema.json`. Every normalized candidate ID must appear in exactly one group. Kept groups receive stable `F###` identifiers later from the controller; do not assign them yourself.

A no-findings result is valid only when all candidates were discarded or no candidates existed, and its verdict is `READY`.
