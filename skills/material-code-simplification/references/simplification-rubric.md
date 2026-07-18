# Material simplification rubric

A different implementation is not automatically simpler. Establish current cost, preserved behavior, and net reduction before retaining a candidate.

## Required gates for every kept candidate

All must be supported.

1. **Exact evidence** — the current frozen source contains the cited structure, duplication, state, dependency, or flow.
2. **Current cost** — a concrete present maintenance, debugging, operational, reliability, or change cost exists now. “Might be useful later” is not a cost.
3. **Root cause** — the candidate identifies the structural cause rather than only a long file, score, or symptom.
4. **Behavior boundary** — the behavior and contracts that must remain are identified. Unknown behavior is visible and has a characterization path.
5. **Net concept reduction** — the proposal removes meaningful branches, states, policies, dependencies, indirections, duplicated ownership, or failure modes. It does not merely redistribute them.
6. **Favorable tradeoff** — expected benefit exceeds implementation churn, test burden, migration cost, rollback difficulty, and regression risk.
7. **Smallest sufficient shape** — deletion, consolidation, inlining, or reuse was considered before adding or replacing abstractions.
8. **Executable verification** — the plan can produce behavior evidence inside exact paths and finite attempts.

Failing any gate normally means discard or defer for missing evidence.

## Evidence of current cost

Potentially material evidence includes:

- one policy is implemented in several places and already diverges or requires synchronized edits;
- routine changes require edits across unrelated layers or many files;
- wrapper/adapter chains obscure error, state, or side-effect ownership;
- speculative configuration, flags, fallbacks, or compatibility branches create reachable states with no current consumer;
- duplicate old/new implementations both remain reachable;
- reimplemented framework/standard-library behavior adds maintenance and edge cases;
- excessive branching/state makes a demonstrated behavior hard to reason about or test;
- dependencies or generated glue exist solely for trivial behavior available locally;
- test structure makes real behavior difficult to change safely.

A long file, large function, repeated syntax, or high static score is only a locator.

## Counterevidence that may justify complexity

Check for:

- intentionally isolated domains expected to diverge;
- performance or allocation constraints;
- backward compatibility and staged migration requirements;
- framework entry points, reflection, plugins, serialization, or code generation;
- security boundaries or defense-in-depth duplication;
- transaction, concurrency, retry, ordering, or failure-isolation requirements;
- platform-specific behavior;
- readability gained by explicit local duplication;
- stable public APIs where indirection shields consumers;
- historical incidents or ADRs explaining the shape.

## Net-simplification test

Compare current and proposed shapes qualitatively. Do not fabricate precise scores.

Ask:

- Which concepts disappear?
- Which paths or states become impossible?
- Which dependency or configuration surface is removed?
- Which duplicated policy gains one owner?
- Which new concepts, compatibility layers, or migration steps are introduced?
- Is the proposed code easier to trace at the behavior boundary, not merely shorter?
- Does the proposal leave both old and new paths in place?
- Could a smaller edit achieve most of the value with less risk?

Keep only when the balance is clearly favorable or when pre-fix characterization can resolve a high-impact uncertainty.

## Rewrite gates

A bounded rewrite requires all general gates plus:

- local refactors cannot remove the root cause without preserving most of the problematic shape;
- the replacement boundary and consumers are finite and explicit;
- behavior can be characterized before replacement;
- data/API compatibility and migration are explicit;
- rollback can restore the old boundary;
- no big-bang repository-wide conversion is required;
- the replacement has fewer concepts and failure modes, not only newer patterns;
- rewrite permission is not inferred from `rewrite:allow`; Gate A and Gate B still approve it.

Discard rewrites motivated by dislike, trend adoption, “clean architecture,” language/framework novelty, or a desire to regenerate code from scratch.

## Typical discard reasons

Use the existing controller codes where they fit:

- `DUPLICATE`
- `NOT_IN_SCOPE`
- `PRE_EXISTING_UNRELATED`
- `EVIDENCE_MISMATCH`
- `CONSEQUENCE_UNSUPPORTED`
- `VALIDATOR_REJECTED`
- `UNCERTAIN_BELOW_HIGH_IMPACT`
- `STYLE_OR_LINTER`
- `SPECULATIVE_FUTURE`
- `HARMLESS_DUPLICATION`
- `ABSTRACTION_COST_EXCEEDS_VALUE`
- `SIMPLIFICATION_NOT_MATERIAL`
- `SETTLED_PREFERENCE`
- `OUTSIDE_REVIEWER_CONTRACT`

When none is perfect, choose the closest code and make the decision reason specific.

## Confidence

- `certain`: source and reachability directly establish the current cost and reduction boundary.
- `high`: callers, contracts, tests, and counterevidence strongly support the candidate.
- `medium`: a material uncertainty remains; normally discard or require explicit characterization when impact is high.
- `low`: suppress unless a blocker-level risk must remain visible.

Confidence is not a percentage and does not substitute for independent validation.
