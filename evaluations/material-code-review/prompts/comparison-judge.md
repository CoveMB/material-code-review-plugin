# Blinded material-review comparison

Compare anonymous Variant A and Variant B using the supplied trial bundles, agreement records, judge-only oracle, and rubric. Do not search for or infer branch names, commit messages, source ref labels, version labels, private mappings, credentials, prior runs, or machine-specific paths. Do not prefer a variant because of schema novelty, prose style, or apparent age.

Treat the oracle as non-exhaustive, fallible reference evidence. Re-check source boundaries, causal evidence, counterevidence, and safeguards. Credit a known failure only when a trial supports it, and credit an additional finding only after independently validating its materiality and evidence.

Assign `A_STRONGER`, `B_STRONGER`, `TIE`, or `UNKNOWN` to every primary and secondary dimension in the supplied rubric, with concrete artifact citations. Apply the rubric's exact qualitative overall-decision rule; do not calculate a numeric score. Report exactly one overall decision: `VARIANT_A_STRONGER`, `VARIANT_B_STRONGER`, `MATERIAL_TIE`, or `INSUFFICIENT_EVIDENCE`.

Include trial stability, known failures found and missed, unsupported findings, plan-boundary comparison, workflow failures, cost observations, confidence, and limitations. Return only JSON conforming to the supplied judgment schema. Do not reveal or guess variant identity.
