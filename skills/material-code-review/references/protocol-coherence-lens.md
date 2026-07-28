# Protocol-coherence lens

Use this read-only lens when the frozen context records a protocol risk signal: `multi_stage_lifecycle`, `cross_boundary_data`, `prompt_contract`, `conditional_validation`, `state_dependent_schema`, `trust_ordering`, or `shared_schema`.

## Ordering

Verify prerequisites, checkout cleanliness, canonicalization, and attestations occur before dependent reads or actions, and that mutable inputs are re-attested at their use boundary.

## Information availability

Trace every value from producer to consumer. A worker cannot be required to inspect private or omitted data; root-owned authority must be explicit.

## State completeness

Trace approve, reject, defer, empty, invalid, and no-plan states. Omission must not be used where an explicit hash-bound disposition is required.

## Phase-specific schemas

Separate pre-disposition, final, empty, error, and no-plan responses. Require only evidence available in that phase.

## Non-vacuous validation

Verify every conditionally read contract asset is independently required when absence would skip validation.

## Evidence and materiality

Anchor each candidate with one exact quote from its primary file. Use related files and checked counterevidence for the remaining cross-file proof; do not replace the primary quote with a collage of excerpts.

Return only evidenced defects, coverage gaps, documentation gaps, or risks with a plausible negative consequence in the frozen scope. Suppress naming preferences, explanatory-comment advice, harmless duplication, generic DRY suggestions, and minor test-economy advice unless exact evidence establishes a material consequence whose benefit clearly exceeds churn and regression risk.

Emit ordinary `material-review/candidate-set/v1` JSON under the assigned `protocol_coherence` lens. Do not invent a new schema or merge-readiness verdict.
