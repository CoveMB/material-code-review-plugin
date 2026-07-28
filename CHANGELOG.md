# Changelog

## 1.2.0 — 2026-07-26

- Bound pull-request review to exact host base/head provenance, added required protocol-aware coverage and one bounded candidate preflight correction, and made missing required coverage fail closed as `REVIEW_INCOMPLETE` while retaining the existing low-value-advice suppression.
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
