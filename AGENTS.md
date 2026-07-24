# Repository guidance

This repository packages two reusable Agent Skills—material code review and material code simplification—with a shared deterministic lifecycle controller and multiple host and distribution surfaces.

## Source of truth

- Material-review activation, judgment rules, workflow semantics, and human-facing invariants: `skills/material-code-review/SKILL.md`
- Material-simplification scope, judgment rules, behavior-preservation semantics, and simplification-specific invariants: `skills/material-code-simplification/SKILL.md`
- Shared lifecycle, state, hash, gate, checkpoint, restoration, exact-ID/path/test, attempt, and repair-round enforcement: `skills/material-code-review/scripts/reviewctl.py`
- Simplification codebase-scope selection and delegation to the shared controller: `skills/material-code-simplification/scripts/simplifyctl.py`
- Shared machine-facing JSON shapes and controlled values: `skills/material-code-review/schemas/`
- Stage-specific procedures, prompts, rubrics, output guidance, and failure handling: each skill's `references/` directory
- Archive composition, required shipped files, structural validation, and distribution integrity: the packaging and validation scripts under `scripts/` and each skill's `scripts/` directory

## Change rules

- Keep Codex and Claude manifests version-aligned.
- Do not add a reference path to `SKILL.md` unless the referenced file ships in the package.
- Preserve the two mandatory user gates and the no-mutation-before-Gate-B invariant.
- Preserve exact-path repair boundaries and finite retry limits.
- Keep runtime dependencies in the Python standard library unless the package metadata and tests are intentionally revised.

## Contract coherence

Apply this coherence pass to every change that can alter activation, workflow semantics, judgment rules, controller behavior, machine-facing artifacts, mutation authority, host presentation, or packaged runtime behavior for either shipped skill.

1. Before editing, state:
   - the affected capability: material review, material simplification, shared controller, or packaging;
   - the intended semantic change;
   - the canonical owner from the source-of-truth map above;
   - whether backward compatibility, migration, or a version change is required.
2. Inventory all affected consumers before editing. Check, where applicable:
   - both canonical `SKILL.md` files and their references;
   - the shared controller, simplification adapter, and schemas;
   - root `SKILL.md`, `commands/`, `agents/`, and `skills/*/agents/openai.yaml`;
   - `.codex-plugin/`, `.claude-plugin/`, and `.agents/plugins/`;
   - `README.md`, `CODEX.md`, `EVALUATION.md`, `CHANGELOG.md`, and examples;
   - controller tests, simplification tests, packaging tests, validators, packagers, and `Makefile`.
3. Before changing prose or behavior, define every affected:
   - explicit and implicit activation state;
   - supported and unsupported review object;
   - scope mode and mutable or immutable posture;
   - lifecycle state and permitted transition;
   - user gate and source of authority;
   - artifact hash, finding ID, allowed path, and approved command boundary;
   - retry, repair-round, rollback, restoration, and abort outcome;
   - external-review, source-egress, and publication permission;
   - simplification-specific behavior-preservation or rewrite exception.
4. Update the canonical owner and every affected consumer as one coherent change. Remove superseded language and obsolete states instead of layering qualifications over the old contract.
5. Keep normative behavior in its canonical owner. Consumer surfaces may repeat only the minimum information needed for routing, host compatibility, or operation. When controlled wording must be repeated across manifests or adapters, validate its alignment mechanically.
6. Preserve the hard safety model across both workflows: frozen and hash-bound scope, complete kept/discarded adjudication, Gate A before planning, Gate B before mutation, exact approved IDs and paths, checkpointed restoration, approved tests, finite attempts and repair rounds, bounded post-fix verification, and no unapproved publication or source egress. Stop for explicit user direction before weakening one of these guarantees.
7. Put prerequisites before dependent steps. Place exceptions beside the rules they qualify. When simplification delegates to the shared controller, describe only the changed semantics and link directly to the shared contract for inherited behavior.
8. After editing, search the complete inventory for:
   - old and new controlled wording;
   - synonyms and renamed states;
   - negations and universal terms such as `never`, `always`, `only`, and `every`;
   - exception terms such as `unless`, `except`, `allow`, and `degraded`;
   - affected enum values, schema versions, command names, paths, limits, and version numbers.
9. Prefer behavioral tests for lifecycle, authorization, restoration, scope, and failure behavior. Exercise every meaningful finite state and exception. Use exact-phrase assertions only for controlled activation vocabulary, stable host interfaces, archive identities, or explicitly owned literals.
10. For release-version changes, first distinguish the full-plugin version from any independently versioned standalone artifact. Keep every surface representing the same release aligned, including manifests, `Makefile`, packagers, validators, documentation, archive names, and changelog entries.
11. Before completion, validate the source tree and every affected distributable layout. Confirm that each referenced path ships in the relevant package and that the standalone simplification archive contains the shared controller and schemas in the layout its adapter expects.
12. Stop and ask when canonical owners conflict, ownership is unclear, inherited and skill-specific behavior cannot both be satisfied, compatibility expectations are unknown, or a distribution cannot contain every contract it references.

## Validation

Run:

```bash
make validate
```

For the full plugin and standalone material-review archive:

```bash
make package
```

For the standalone material-simplification archive:

```bash
make package-simplification
```
