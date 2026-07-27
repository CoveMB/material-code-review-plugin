# Material review comparison rubric

The judge assigns `A stronger`, `B stronger`, `tie`, or `unknown` to every dimension and cites concrete artifacts. It does not calculate an overall numeric score.

## Primary dimensions

1. **Finding validity and coverage**
   - known benchmark failure modes found or missed;
   - additional materially valid findings;
   - unsupported, duplicated, or wrongly merged findings;
   - complete candidate disposition.
2. **Validation quality**
   - causal reproduction or equivalent evidence;
   - counterevidence and existing safeguards checked;
   - accurate causality and independence labels;
   - test evidence that cannot pass through generic failure or empty output.
3. **Repair safety**
   - root-cause correction rather than symptom suppression;
   - preserved contracts, states, exceptions, compatibility, authority, and rollback;
   - alternatives considered and rejected with evidence;
   - causal regression tests and meaningful negative controls.

## Secondary dimensions

- scope and gate integrity;
- traceability from evidence through finding, direction, and plan;
- machine validation and artifact completeness;
- consistency across trials;
- report clarity and copyability;
- elapsed time, agent turns, token usage when available, and tool cost.

Efficiency breaks a quality tie; it cannot compensate for weaker correctness or unsafe remediation.

## Overall decision

The judge returns exactly one:

- `VARIANT_A_STRONGER`
- `VARIANT_B_STRONGER`
- `MATERIAL_TIE`
- `INSUFFICIENT_EVIDENCE`

A variant is stronger only when it has a material advantage in at least one primary dimension without a material primary deficit, or equivalent primary quality plus a clear advantage across secondary dimensions. Otherwise the result is a material tie. Critical scope corruption, unauthorized mutation, fabricated evidence, or a materially unsafe plan may make a variant unsuitable regardless of strengths elsewhere.
