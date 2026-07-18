# Independent simplification validator template

You receive one semantic candidate group. Perform fresh verification. Do not agree by default, add findings, improve the proposal, or edit code.

## Verify source and reachability

1. Does the exact evidence exist in the frozen side, file, and lines?
2. Is the relevant path reachable through callers, registration, reflection, generation, configuration, or external contracts?
3. Is the apparent duplication/indirection/state actually one semantic concern?

## Verify present cost

4. What concrete maintenance, debugging, operational, reliability, or change cost exists now?
5. Under what real scenario does it materialize?
6. Is the cost supported by source, tests, history, contracts, or repeated change surface rather than a metric or aesthetic judgment?

## Seek disconfirming evidence

7. Do compatibility, security, performance, transaction, concurrency, platform, failure-isolation, framework, or expected-divergence requirements justify the shape?
8. Are callers or tests relying on behavior the candidate would erase?
9. Is an existing abstraction already the correct owner, making the proposed consolidation misplaced?

## Verify reduction shape

10. What behavior and contracts must remain?
11. Which concepts, paths, states, dependencies, or duplicated policies disappear?
12. Which new concepts, migration steps, or failure modes appear?
13. Is deletion/consolidation/reuse safer than the proposed abstraction?
14. Does benefit clearly exceed churn and regression risk?
15. Can behavior be characterized and the change rolled back inside exact paths?

## Rewrite validation

For rewrite candidates, also verify that local refactors cannot remove the root cause, the boundary is finite, data/API compatibility is explicit, rollback is feasible, and the replacement is materially simpler rather than merely newer.

## Verdict

Use:

- `confirmed` only when evidence and tradeoff are strong;
- `rejected` when evidence, reachability, current cost, root cause, or net-simplification claim fails;
- `uncertain` when a material condition cannot be resolved from available evidence.

Prefer uncertainty over invented behavior and rejection when the frozen source cannot be accessed. State exact pre-fix characterization needed for a high-impact uncertainty. In codebase mode, use `causality: pre_existing` for existing complexity; do not relabel it `introduced` or `exposed` merely to pass the controller. Confirm that at least one source candidate truthfully marks the issue as a direct dependency of the selected boundary.

Use `mode: independent` only when the actual model/process independence group differs from every source group. A persona name is not independence. Return only the validation object required by the shared adjudication schema.
