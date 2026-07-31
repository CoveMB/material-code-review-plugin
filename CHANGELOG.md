# Changelog

## 1.3.0 — 2026-07-29

- Added immutable exhaustive coverage plans and candidate-set/v2 bindings, including targeted reliability and persisted-configuration/migration lenses.
- Added deterministic material-review lens provenance through candidates-normalized/v2, adjudication/v4, and ledger/v4, including exact candidate-derived source lenses and stable tied-candidate IDs.
- Kept explicit material simplification isolated on candidates-normalized/v1, adjudication/v3, and ledger/v3; legacy or lens-less material-review artifacts are never backfilled or rewritten and require restart except for bounded final-repair completion.
- New material-review runs use state/v2 so controller 1.2 rejects them before forward mutation; material-review state/v1 is not migrated, while marked final-repair runs may refresh approved tests and complete verification without reopening attempts. Explicitly profiled simplification stays fully functional on state/v1.
- Added strict-guard evidence handling, including the visible high-impact risk exception and `CONSEQUENCE_UNSUPPORTED` disposition for unsupported lower-impact claims.
- Unmarked legacy material-review runs restart under the new contract; they are not migrated. Existing checkpointed work remains safely restorable before a new run begins.
- Ambiguous delegated material-simplification runs restart rather than inherit material-review v2 coverage semantics; simplification remains on candidate-set/v1.
- Preserved Gate A and Gate B, no mutation before Gate B, bounded repair/restoration, publication controls, and source-egress authorization requirements.
- Released the full plugin and standalone material-review skill as 1.3.0, and the standalone material-simplification skill as 1.2.0 with embedded shared-controller provenance.

## 1.2.0 — 2026-07-26

- Added provisional grouping followed by a mandatory, hash-bound repair-direction audit for every retained finding.
- Added adjudication/v3 and ledger/v3 audit provenance, including accurate independent, controller-direct, and degraded modes.
- Added fix-plan/v2 with exact approved-direction hashes, complete constraint/state/decision handling, alternatives, and explicit divergence rationale.
- Aligned material simplification with the shared audit and plan lifecycle while preserving behavior characterization, net-reduction, and bounded-rewrite rules.
- Added the independently versioned material-simplification 1.1.0 archive with its required shared controller, schemas, and remediation references.
- Aligned Codex and Claude plugin manifests, validators, packagers, archive identities, and current-capability documentation.

## 1.1.0 — 2026-07-17

- Added a root Agent Skills `SKILL.md` entrypoint for Codex and OpenAI Skills import.
- Added Codex-specific host adaptation and `AGENTS.md` package guidance.
- Completed all previously referenced schemas, prompts, agents, command wrapper, controller wrapper, validation tooling, licensing, and documentation.
- Added deterministic full-package and standalone Codex-skill packaging.
- Added package-integrity checks for missing references and archive-root compatibility.
- Corrected the documented test count to 19.

## 1.0.0

- Initial frozen-scope, two-gate material review controller and lifecycle test suite.
