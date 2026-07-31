# Finding adjudicator template

Synthesize the normalized candidate bundle and validator results into a complete provisional group set, route every provisional retained group through repair-direction audit, then compile those same audited groups into one ledger. You may merge semantic duplicates during provisional grouping, but you may not invent a concern, omit a candidate, or change the group partition after audit.

## Required process

1. Group only candidates that share the same failure mode and repair implication. Nearby but distinct consequences remain separate.
2. Inherit canonical evidence, nature, and category from a source candidate.
3. List source reviewers and independence groups exactly. Also list `source_lenses` as the exact sorted unique lens IDs derived from the group's candidate IDs; never infer a lens from reviewer identity or type it free-form.
4. Attach a valid validator result to every group.
5. Apply `materiality-rubric.md` separately to defects and optional improvements.
6. Give every group a provisional `keep` or `discard`, a specific reason, and a coded discard reason when discarded.
7. Do not use cross-reviewer agreement as proof when reviewers share an independence group.
8. Route every provisionally kept group to `remediation-auditor-template.md`; attach its normalized `repair_direction` and scope-, candidate-, and direction-hash-bound `repair_audit` without changing the candidate-ID partition or disposition.
9. If the audit requires a group, disposition, or direction change, repeat the affected audit before final compilation.
10. Keep finding confidence separate from repair-direction confidence. A real finding may retain a non-reviewed remediation status.
11. Set both `repair_direction` and `repair_audit` to null for every discarded group.
12. Select the merge-readiness verdict from actual kept findings.

A stricter guard is a defect only with affirmative supported-state evidence. Sufficient authority includes an explicit requirement or user promise, an accepted schema state, a causal test, or baseline behavior shown to be an accepted or relied-upon compatibility state. Mere historical acceptance or the fact that a guard blocks an input is not enough when intentional fail-closed validation remains plausible. Discard an unsupported medium/low claim as `CONSEQUENCE_UNSUPPORTED`. When the consequence is plausibly blocker/high but support status is genuinely unknown, retain it only as `nature="risk"`, require a user decision and exact pre-fix verification, and do not authorize relaxing the guard until support is established and the plan is revalidated.

## Output

Return exactly one `material-review/adjudication/v4` object conforming to `schemas/adjudication-v4.schema.json`. Every normalized candidate ID must appear in exactly one group. Every kept group must carry a valid bound audit; the controller rejects absent, stale, falsely independent, ineligible controller-direct, or lens-provenance-mismatched records. Kept groups receive stable `F###` identifiers later from the controller; do not assign them yourself.

A no-findings result is valid only when all candidates were discarded or no candidates existed, and its verdict is `READY`.
