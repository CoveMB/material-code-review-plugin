# Material Review Discovery Recall Design

**Status:** Superseded for implementation by `2026-07-29-targeted-material-review-recall-precision-design.md`

> The targeted design retains fail-closed, root-owned review coverage but defers this document's PR provenance, protocol-coherence, candidate-preflight, fallback, and recovery scope. Do not use this document as the active implementation contract.

**Date:** 2026-07-27

**Affected capability:** Material review and its shared lifecycle controller

**Canonical owners:** `skills/material-code-review/SKILL.md`, `skills/material-code-review/references/`, and `skills/material-code-review/scripts/reviewctl.py`

## Problem

A comparison between CodeRabbit's review of pull request 3 and a later material-review run exposed two different classes of discrepancy.

First, the review scopes were not equivalent. CodeRabbit reviewed the pull request's base-to-head range, `8ebeb7ae2a1f28acfe297c258f703865280c4fa4..c740131b0953a04a93cbe1c970dcbf36dae8bca1`, containing 15 changed files. The material-review run reviewed the head commit against its immediate parent, `5f1dcaf066e0a2e63787cf8e07708459ee505047..c740131b0953a04a93cbe1c970dcbf36dae8bca1`, containing 36 changed files and more than 15,000 deletions. The broader replacement diff diluted attention and made the comparison unsuitable for evaluating relative finding recall.

Second, the material-review workflow has genuine recall weaknesses even after accounting for scope:

- no dedicated lens requires a producer-consumer and state-machine audit of cross-file protocols;
- a substantively valid phase-specific return-schema candidate was rejected because its evidence quote combined or paraphrased text rather than quoting one exact frozen source region;
- a completely rejected reviewer set loses useful coverage detail from the normalized reviewer roster;
- a required high-risk lens can fail mechanically without a machine-enforced rule preventing an overconfident merge-readiness conclusion; and
- PR metadata is read by the host but is not bound to the controller's frozen scope as review-object provenance.

The goal is to improve recall for material findings without turning material review into a general style or low-value cleanup review.

## Goals

1. Bind PR reviews to the exact PR base and head rather than silently substituting an immediate-parent range.
2. Require a protocol-coherence lens when the change contains cross-file lifecycle, authorization, prompt, validator, schema, or trust-boundary behavior.
3. Prevent mechanically malformed candidate output from erasing an otherwise material concern when one bounded, author-owned correction can make the evidence ingestible.
4. Preserve rejected-set coverage and make missing required-lens evidence fail closed.
5. Keep candidate-set v1 compatible and preserve the current validation, adjudication, Gate A, Gate B, repair, restoration, and post-fix contracts.
6. Continue suppressing style preferences, harmless duplication, explanatory-comment suggestions, and minor test-economy advice unless they demonstrate a material current consequence.
7. Validate the improvement against the actual PR 3 scope without exposing the expected finding inventory to candidate reviewers.

## Non-goals

- Adding CodeRabbit or another external reviewer as a required dependency.
- Importing existing PR comments into the independent candidate-discovery wave.
- Guaranteeing exhaustive discovery from a nondeterministic model.
- Weakening exact evidence, materiality, independence, or user-gate requirements.
- Adding multiple evidence anchors or introducing candidate-set v2 in this change.
- Changing repair authority, retry budgets after Gate B, publication authority, or source-egress policy.
- Surfacing low-value nitpicks in Gate A merely because another reviewer reported them.

## Design

### 1. PR review-object provenance

When the requested review object is a pull request, the host must obtain the PR URL or stable identity, exact base SHA, and exact head SHA through a read-only API before controller initialization. The controller must accept this optional provenance only with `scope:range` and must verify that the resolved frozen baseline and comparison equal the supplied 40-character SHAs.

The verified review-object record is stored in the frozen scope and controller state and participates in the scope hash. At minimum it contains:

- review-object kind `pull_request`;
- stable repository-relative or remote PR identity;
- exact base SHA;
- exact head SHA; and
- the fact that metadata came from a read-only host lookup.

If PR metadata is missing, ambiguous, stale, or inconsistent with the requested refs, initialization stops before creating a run. It must not fall back to `HEAD^`, a merge base guessed from local branches, or another plausible range.

An explicitly requested non-PR range remains supported. The context and Gate-A output must label it as a direct range and must not claim comparability with an existing PR review unless the stored PR base and head match exactly.

Direct range, branch, and uncommitted runs remain backward compatible and need no review-object provenance.

### 2. Root-owned coverage plan

Before candidate dispatch, the root records a scope-hash-bound coverage plan in the run artifacts. The plan contains:

- normalized risk signals derived from changed behavior and the context record;
- required lens identifiers;
- optional lens identifiers;
- the assigned reviewer identity and actual independence group for each dispatch;
- the permitted sequential fallback for each required lens; and
- the maximum candidate-draft correction attempts, fixed at one after the initial draft.

Correctness, fragile-behavior test adequacy, and repository/requirement alignment remain mandatory. The new `protocol_coherence` lens becomes mandatory when contextual evidence shows any of the following:

- a multi-stage lifecycle or user gate;
- data or authority passed between files, workers, processes, or phases;
- prompts or instructions whose inputs and outputs are consumed elsewhere;
- validators whose checks depend on optional or separately required files;
- state-dependent request or response shapes;
- initialization, attestation, or trust-boundary ordering; or
- a schema or controlled vocabulary shared by multiple consumers.

Filenames alone cannot trigger the lens. The coverage plan must cite the behavioral risk signal that made the lens applicable.

### 3. Protocol-coherence lens

Add a dedicated reviewer reference that applies the normal candidate schema and materiality threshold while checking five relationships:

1. **Ordering:** prerequisites, cleanliness checks, canonicalization, attestation, and validation occur before any dependent read or action, with required re-attestation at dispatch or use boundaries.
2. **Information availability:** every consumer receives or can authoritatively rely on every value it is instructed to inspect; private or prohibited values are not simultaneously required as worker inputs.
3. **State completeness:** every state transition receives complete hash-bound data, including explicit negative or deferred states rather than ambiguous omission.
4. **Phase-specific schemas:** pre-disposition, final, error, empty, and no-plan outcomes require only evidence available in that phase and forbid fabricated later-phase artifacts.
5. **Non-vacuous validation:** every conditionally inspected contract file is independently required when absence would silently bypass validation.

The lens must inspect producer and consumer surfaces together, name counterevidence, choose one exact primary source quote for candidate ingestion, and place secondary cross-file support in `related_changed_files` and `counterevidence_checked`. It must continue suppressing low-value cleanup advice.

### 4. Candidate draft preflight

Add a read-only controller command for candidate-draft preflight. It validates a draft against the active frozen run without advancing the lifecycle or adding candidate IDs. It returns structured diagnostics for:

- JSON and schema errors;
- stale scope hash;
- invalid controlled values;
- changed-file relation failures;
- missing or non-verbatim evidence;
- evidence outside the declared line range; and
- duplicate local IDs.

The root runs preflight on every draft. A valid draft proceeds to final ingestion unchanged.

When preflight reports only mechanical representation or evidence-anchor failures, the same originating reviewer may receive those diagnostics and return one corrected draft. The correction remains part of candidate generation, not adjudication. No controller, validator, or adjudicator may invent a concern or rewrite its substance.

For a parsable initial draft, the controller records a semantic fingerprint over all substantive finding fields. A corrected draft may change only serialization and the primary evidence anchor: `file`, `line_start`, `line_end`, `evidence_side`, and `evidence_quote`. The title, nature, category, severity, confidence, scope relation, related files, dependency classification, consequence, trigger, counterevidence, materiality rationale, proposed direction, risk, user-decision flag, and assumptions remain fixed.

For an unparseable initial draft, no semantic fingerprint can be proven. One syntax-correction attempt is still allowed from the same reviewer, is recorded as degraded evidence handling, and receives no additional retry.

Semantic weakness is not repairable through preflight. Speculative, low-confidence, unsupported, or non-material candidates remain rejected rather than being polished until accepted.

### 5. Preserved rejected coverage

Preflight and ingestion record each reviewer set whether it is accepted, partially accepted, empty, or rejected. Coverage areas, files reviewed, limitations, lens identity, attempt hashes, structured diagnostics, and fallback status remain in a root-owned coverage artifact even when every finding fails.

The normalized candidate bundle continues to contain only valid candidate-set v1 findings. Rejected material is never silently converted into a candidate, but the ledger limitations can accurately describe which required work failed and why.

### 6. Fail-closed coverage completion

Before final candidate ingestion and before ledger compilation, the controller compares completed reviewer evidence with the recorded coverage plan.

For a failed required lens, the root may dispatch its one recorded sequential degraded-self-audit fallback. Candidate correction and lens fallback are separate bounded actions: each has at most one attempt beyond the original execution.

If the required lens still has no valid completion, the run becomes review-incomplete and stops before a merge-readiness verdict. It cannot compile an empty `READY` ledger. Optional lens failure may continue with an explicit limitation when every required lens completed.

This design does not invent a new merge-readiness verdict. Review-incomplete is a pre-ledger terminal condition, distinct from `READY`, `SHOULD FIX BEFORE MERGE`, `NOT READY`, and a repair-phase `BLOCKED` outcome.

### 7. Existing lifecycle after ingestion

Once a coverage-complete candidate bundle exists, the current lifecycle remains unchanged:

- candidates receive stable IDs;
- validators confirm, reject, or retain high-impact uncertainty;
- adjudication includes every valid candidate exactly once;
- every kept group receives a repair-direction audit;
- Gate A approves findings only;
- Gate B approves the exact repair plan and commands;
- mutation remains exact-path, checkpointed, bounded, and restorable; and
- final verification covers approved findings and fix-caused regressions only.

## Failure handling

| Failure | Required outcome |
|---|---|
| PR metadata cannot be resolved | Stop before initialization; do not guess a base. |
| Supplied PR SHAs do not match the frozen range | Reject initialization with the expected and actual identities. |
| Coverage plan is absent or stale | Refuse candidate dispatch or ingestion. |
| Candidate draft passes preflight | Ingest the same bytes; no correction is offered. |
| Candidate draft has a mechanical error | Return structured diagnostics to the same reviewer for one correction. |
| Corrected parsable draft changes substantive fields | Reject the correction and preserve both attempt hashes. |
| Corrected draft remains invalid | Mark that lens execution rejected and consider its recorded fallback. |
| Required lens and fallback both fail | Stop as review-incomplete; do not compile a ledger. |
| Optional lens fails | Continue only with an explicit coverage limitation. |
| Candidate is non-material | Suppress or discard through the existing materiality rules. |

## Compatibility and versioning

Candidate-set v1 remains the only reviewer output schema. Existing direct-range, branch, uncommitted, candidate validation, adjudication, ledger, gate, plan, repair, and verification artifacts remain valid.

New coverage and preflight artifacts are additive and root-owned. The controller must tolerate their absence only for runs created by an older controller version; new runs cannot bypass them. No artifact migration is required because run artifacts are local, immutable records rather than long-lived shared data.

No plugin release-version change is required solely for this internal workflow improvement. If implementation changes a shipped public schema or host-facing command incompatibly, stop and reconsider versioning before proceeding.

## Validation strategy

### Deterministic controller tests

Add focused tests for:

- matching PR base/head provenance;
- missing, ambiguous, stale, and mismatched PR metadata;
- refusal to substitute a commit parent for a PR base;
- protocol-lens routing from each semantic risk signal;
- negative controls showing filenames alone do not require the lens;
- valid candidate preflight without lifecycle advancement;
- structured JSON, schema, quote, line-range, scope, and duplicate-ID diagnostics;
- one permitted mechanical correction;
- rejection when a parsable correction changes substantive fields;
- the unparseable-draft degraded correction path;
- preservation of wholly rejected reviewer coverage;
- required-lens fallback and exhausted-fallback behavior;
- review-incomplete runs refusing `compile-ledger`; and
- optional-lens failure remaining visible without blocking a coverage-complete run.

Existing controller lifecycle tests must continue to pass unchanged unless an additive setup step is required for newly initialized runs.

### Materiality controls

Tests and rubric fixtures must continue excluding low-value examples unless their consequence becomes material:

- harmless Makefile command deduplication;
- an explanatory comment for intentionally split string literals; and
- minor test-economy cleanup that does not create a meaningful reliability or development-cost risk.

A source document whose deletion silently disables multiple validator contracts is not automatically a nitpick merely because another reviewer labeled it one; its concrete validation consequence remains eligible for material review.

### Bounded regression evaluation

Add a maintainer-only evaluation case bound to PR 3's actual range:

`8ebeb7ae2a1f28acfe297c258f703865280c4fa4..c740131b0953a04a93cbe1c970dcbf36dae8bca1`

The expected inventory remains private to the evaluation root and is never supplied to candidate reviewers. It covers these material failure modes:

- pre-read checkout cleanliness ordering;
- private receipt versus worker-verification requirements;
- complete approve/reject/defer disposition propagation;
- phase-specific Gate-A and final return shapes;
- non-vacuous required-document validation;
- portable case-folded maintainer-only archive exclusion; and
- evaluator-entrypoint regular-file and root-containment validation.

Acceptance requires:

- the controller freezes the exact PR base and head;
- each expected material failure mode is represented by at least one ingestible candidate, and it is not discarded unless new exact-source counterevidence disproves the expected failure;
- no material candidate is lost solely to a mechanical evidence-format failure after the bounded correction path;
- low-value controls do not become kept Gate-A findings; and
- all required coverage and degraded-independence information is explicit.

Follow repository evaluation economy: run at most one baseline and one post-change confirmation. If nondeterministic results conflict after the permitted confirmation, report the evidence as inconclusive rather than resampling.

## Affected consumers

Implementation must review and update, where applicable:

- `skills/material-code-review/SKILL.md`;
- `skills/material-code-review/references/reviewer-template.md`;
- a new protocol-coherence lens reference;
- `skills/material-code-review/references/context-checklist.md`;
- `skills/material-code-review/references/failure-model.md`;
- `skills/material-code-review/references/workflow.md`;
- `skills/material-code-review/scripts/reviewctl.py`;
- `skills/material-code-review/tests/test_reviewctl.py`;
- candidate, state, scope, and packaging contract tests affected by additive artifacts;
- `scripts/validate_package.py` and `scripts/tests/test_packaging.py` for shipped-file and contract validation;
- the material-review agent definitions and host-facing routing surfaces if they repeat lens or scope behavior;
- `README.md`, `CODEX.md`, and `EVALUATION.md` only where they expose the affected workflow; and
- package composition rules so every new runtime reference ships with the material-review skill.

## Security and privacy

- PR lookup is read-only and stores only public or already authorized repository metadata required to identify the review object.
- Candidate preflight never sends source externally and never mutates the worktree.
- Correction diagnostics contain only schema paths and frozen-source evidence locations already available to the originating reviewer.
- Independent reviewers remain unseeded with other reviewer candidates or the private evaluation oracle.
- The change grants no additional repair, publication, credential, network, source-egress, or external-review authority.

## Success criteria

The design succeeds when a PR review is scope-equivalent by construction, cross-file protocol risks receive mandatory dedicated coverage, mechanical candidate errors receive one safe author-owned correction, required coverage cannot silently collapse into `READY`, and low-value nitpicks remain outside Gate A.
