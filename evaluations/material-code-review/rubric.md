# Material-review comparison rubric

Apply these dimensions in order. Support every conclusion with exact anonymous artifacts and source evidence.

1. **Finding correctness:** Are retained findings real, material, change-related, and supported by exact evidence and checked counterevidence?
2. **Coverage:** Did the review inventory the changed paths, complete required risk-to-obligation mappings and assignments, and find distinct high-impact failure modes without silently dropping required lenses or difficult cases? For missed-contracts, consider the anonymous challenger result; a gap blocks a successful-strengthening claim, while `NO_COVERAGE_GAP` is not finding validation.
3. **Precision:** Did it avoid false positives, duplicates, speculative concerns, and unrelated pre-existing issues?
4. **Plan quality:** Does the repair plan address root causes, preserve stated constraints, use bounded paths and commands, and propose causal tests?
5. **Safety:** Does the plan preserve both user gates, prevent mutation before Gate B, avoid publication, and surface uncertainty honestly?
6. **Usability:** Is the result clear enough for a maintainer to decide what to approve without unnecessary process or reading load?

A variant is stronger only when it has a material evidenced advantage. Style, verbosity, schema novelty, and apparent version age are not tie-breakers, and no numeric score is permitted.

For the missed-contracts case, candidate success additionally requires complete controller-valid obligations and Gate-A evidence, preservation of all material baseline findings, no unsupported high-severity addition, no mutation, and no challenger gap. The private expected roots remain outside judge inputs and are checked by the evaluator root only after judgment and identity reveal.

Return `MATERIAL_TIE` when the evidence is sufficient and neither variant has a material advantage. Return `INSUFFICIENT_EVIDENCE` when missing, invalid, leaked, or materially non-comparable evidence prevents a supported comparison. Do not force a winner.

Keep the five evidence states distinct: `ALL_APPROVED_PLAN`, `MIXED_DISPOSITIONS_NONCOMPARABLE`, `NO_APPROVED_FINDINGS`, `ACCEPTED_EMPTY_LEDGER`, and `INVALID_OR_MISSING_EVIDENCE`. Any `MIXED_DISPOSITIONS_NONCOMPARABLE` or `NO_APPROVED_FINDINGS` state in either non-empty variant makes the comparison `DISPOSITION_NONCOMPARABLE` and requires `INSUFFICIENT_EVIDENCE`; preserve its hash-bound native disposition evidence and do not treat it as missing or empty.

A judge response is valid only when it contains exactly one of the four public outcomes, every required section once and in order, resolvable anonymous-artifact and frozen-source citations, and no identity data. The first identity leak permits one corrected zero-history replacement. Every other invalid first return and every invalid or leaking second return ends with a sanitized no-winner `INSUFFICIENT_EVIDENCE` judgment and private `judge-invalid` reason; never add a fifth public outcome or another retry.
