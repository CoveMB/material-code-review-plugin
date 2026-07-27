# Finding adjudicator template

Synthesize the normalized candidate bundle and validator results into a complete provisional group set, route every provisional retained group through repair-direction audit, then compile those same audited groups into one ledger. You may merge semantic duplicates during provisional grouping, but you may not invent a concern, omit a candidate, or change the group partition after audit.

## Required process

1. Group only candidates that share the same failure mode and repair implication. Nearby but distinct consequences remain separate.
2. Inherit canonical evidence, nature, and category from a source candidate.
3. List source reviewers and independence groups exactly.
4. Attach a valid validator result to every group.
5. Apply `materiality-rubric.md` separately to defects and optional improvements.
6. Give every group a provisional `keep` or `discard`, a specific reason, and a coded discard reason when discarded.
7. Do not use cross-reviewer agreement as proof when reviewers share an independence group.
8. Route every provisionally kept group to `remediation-auditor-template.md`; attach its normalized `repair_direction` and scope-, candidate-, and direction-hash-bound `repair_audit` without changing the candidate-ID partition or disposition.
9. If the audit requires a group, disposition, or direction change, repeat the affected audit before final compilation.
10. Keep finding confidence separate from repair-direction confidence. A real finding may retain a non-reviewed remediation status.
11. Set both `repair_direction` and `repair_audit` to null for every discarded group.
12. Select the merge-readiness verdict from actual kept findings.

## Output

Return exactly one object conforming to `schemas/adjudication.schema.json`. Every normalized candidate ID must appear in exactly one group. Every kept group must carry a valid bound audit; the controller rejects absent, stale, falsely independent, or ineligible controller-direct records. Kept groups receive stable `F###` identifiers later from the controller; do not assign them yourself.

A no-findings result is valid only when all candidates were discarded or no candidates existed, and its verdict is `READY`.
