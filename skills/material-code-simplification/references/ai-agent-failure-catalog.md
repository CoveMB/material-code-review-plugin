# AI-agent coding failure catalog and guards

This catalog supplies search lenses, not presumptions. Conventional human code can exhibit every pattern, and AI-assisted code may not. Keep nothing without frozen-source evidence and the materiality rubric.

## 1. Scaffolding and abstraction stacking

Look for:

- interfaces with one stable implementation and no policy boundary;
- factories/builders/registries used once;
- adapter-facade-wrapper chains that only forward arguments;
- generic repositories, services, managers, or utility layers with no domain-specific responsibility;
- many small modules that remain mutually coupled and must be read together.

Disconfirm by checking public seams, test substitution, platform variants, security boundaries, and documented near-term implementations. Do not inline a real boundary merely because it has one current implementation.

## 2. Speculative generality

Look for unused configuration, feature flags, strategy hooks, plugin systems, fallback modes, compatibility paths, abstract base classes, generic type parameters, or option objects created for imagined futures.

Disconfirm by locating real consumers, staged rollouts, compatibility commitments, downstream integrations, generated use, or an ADR. A future requirement written only in an AI-generated comment is weak evidence.

## 3. Duplication and parallel implementations

Look for copied validation, mapping, serialization, API calls, policy, retry logic, fixtures, and old/new implementations that are both reachable.

Disconfirm by checking whether similar syntax represents intentionally different domain rules, security isolation, performance specialization, or expected divergence. Consolidate shared policy, not merely similar-looking code.

## 4. Fragmented control and state

Look for routine behavior spread across many files/layers, repeated conversion between near-identical shapes, state synchronized manually, excessive branching, or one change requiring shotgun edits.

Disconfirm by checking transaction boundaries, event-driven ownership, failure isolation, framework lifecycle, and stable public interfaces. Splitting a large file is not simplification if the same coupled flow becomes harder to trace.

## 5. Defensive-code accumulation

Look for broad exception catches, silent fallbacks, retries without failure classification, redundant null/type checks already guaranteed by upstream contracts, duplicate validation, default-success behavior, or catch-log-continue paths.

Disconfirm by tracing untrusted inputs, network/process boundaries, backward compatibility, and reliability requirements. Removing defense without understanding the threat/failure model can create defects.

## 6. Cargo-cult concurrency, caching, and resilience

Look for unnecessary async layers, queues, worker pools, locks, caches, batching, retries, circuit breakers, timeouts, or idempotency scaffolding around local deterministic work.

Disconfirm with latency/throughput evidence, external calls, scheduler behavior, race risks, transactional requirements, deployment topology, and operational incidents. Never simplify concurrency from syntax alone.

## 7. Dependency and API hallucination

Look for packages with trivial use, wrappers around a single call, nonexistent/deprecated APIs, duplicate packages serving the same role, or custom code compensating for misunderstood framework behavior.

Guard:

- verify installed manifests/locks and actual imports;
- consult authoritative documentation when current API behavior matters;
- do not add, remove, or replace a dependency before Gate B;
- include manifest, lockfile, packaging, and resolution tests in the plan;
- do not assume a package is unused until dynamic loading, plugins, build tooling, and scripts are checked.

## 8. Reimplementation of existing mechanisms

Look for hand-written parsing, validation, routing, serialization, retry, caching, collection, date/time, path, or protocol behavior already provided by the repository, framework, or standard library.

Disconfirm by checking whether the local implementation has required semantics not supplied by the existing mechanism. Replacement is material only when it reduces edge cases and dependency/maintenance surface without changing contracts.

## 9. Dead and shadow code

Look for unused imports, unreachable branches, obsolete flags, duplicate implementations, stale adapters, abandoned migrations, debug paths, and commented-out code.

Guard against false deletion by checking reflection, decorators, registration, dependency injection, CLI discovery, serialization names, templates, build scripts, code generation, external callers, and convention-based entry points.

## 10. Test mimicry and overfitting

Look for tests that repeat implementation logic, mock every collaborator, assert internal calls rather than behavior, duplicate fixtures, use broad snapshots for narrow contracts, or were weakened alongside code changes.

Guard:

- preserve meaningful failing behavior before restructuring;
- prefer public/observable assertions;
- use mocks only at real boundaries;
- run characterization before and after destructive steps;
- do not delete tests merely because their implementation coupling makes a refactor inconvenient;
- investigate whether a test exposes a real contract before changing it.

## 11. Comment and documentation noise

Look for comments that restate syntax, verbose generated docstrings, stale explanations, contradictory architecture prose, and documentation for speculative options.

Disconfirm by checking onboarding, public API, safety, operational, and generated-doc requirements. Removing obvious comments may help; deleting rationale or invariants does not.

## 12. Security and contract drift

AI-assisted simplification may accidentally erase validation, authorization, sanitization, audit, privacy, error, or compatibility boundaries because they appear repetitive.

Guard:

- trace trust boundaries and caller assumptions;
- preserve deny-by-default behavior;
- retain defense-in-depth when the layers protect different boundaries;
- test status/error/data contracts;
- require human review for auth, crypto, secrets, payment, migration, destructive data, and distributed concurrency changes.

## 13. Metric gaming

Look for plans justified by lines removed, function length, cyclomatic/cognitive complexity, file count, or test count alone.

Guard by requiring a concrete behavior/maintenance cost and a before-to-after concept/path explanation. A metric may prioritize reading order; it cannot keep a candidate or prove success.

## 14. Cleanup recursion

Look for the agent noticing another “improvement” during implementation and expanding paths, abstractions, tests, or architecture repeatedly.

Guard with fixed discovery waves, complete adjudication, two user gates, exact paths, finite attempts, and post-fix verification restricted to approved IDs and fix-caused regressions.


## 15. Placeholder, demo, debug, and fabricated-success residue

Look for hard-coded sample values, debug routes/logging, TODO branches returning success, dummy fallbacks, copied fixtures in production code, no-op implementations, and placeholder adapters kept beside the real path.

Disconfirm by checking documented development modes, health checks, examples, migration windows, and operational tooling. A reachable fake-success path is primarily a correctness/reliability issue; preserve it as such or route it through the material-review contract rather than disguising it as a line-removal opportunity.

## 16. Data-shape and conversion proliferation

Look for many near-identical DTOs, request/response/domain models, mapper layers, option objects, boolean parameter matrices, and repeated encode/decode cycles created without a real trust, versioning, persistence, or ownership boundary.

Disconfirm by tracing validation, serialization, API versioning, privacy, persistence, and anti-corruption boundaries. Consolidate only shapes that are contractually the same; superficially similar external and internal models may need separation.

## 17. Wrong-layer edits to generated or vendored output

Look for manual fixes duplicated across generated files, checked-in bundles, lockfiles, vendored sources, snapshots, or compiled artifacts while the generator/template/source remains unchanged.

Guard by identifying the owning source and repository generation policy. Put generator or dependency actions in explicit Gate-B repair steps, include all expected generated paths, verify deterministic regeneration, and avoid hand-editing outputs unless repository policy explicitly requires it.
