# Anonymous trial agreement task

Compare the supplied trials for one anonymous workflow variant. You receive only that variant's native and normalized trial artifacts. Do not search for another variant, evaluator state, prior runs, an oracle, source ref identities, credentials, or machine-specific paths.

Classify the trials as exactly one of `materially_similar`, `materially_different`, or `insufficient_evidence`. Cite concrete evidence from every supplied trial artifact.

Judge material similarity by semantic failure modes, kept versus discarded disposition, merge-readiness posture, causal validation results, root-cause and repair boundaries, required causal tests and important negative controls, and blockers or unsafe directions. Differences in exact hashes, prose, ordering, IDs, or incidental severity wording do not make trials materially different when their underlying judgments agree.

If evidence is insufficient, identify whether the reason is trial variability or infrastructure failure. When a third trial is present, preserve and discuss any outlier rather than hiding it. Return only JSON conforming to the supplied agreement schema.
