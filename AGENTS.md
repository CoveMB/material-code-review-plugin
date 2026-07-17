# Repository guidance

This repository packages a reusable code-review skill and its deterministic controller.

## Source of truth

- Workflow contract: `skills/material-code-review/SKILL.md`
- Controller contract: `skills/material-code-review/scripts/reviewctl.py`
- Machine-facing JSON shapes: `skills/material-code-review/schemas/`
- Stage prompts and rubrics: `skills/material-code-review/references/`

## Change rules

- Keep Codex and Claude manifests version-aligned.
- Do not add a reference path to `SKILL.md` unless the referenced file ships in the package.
- Preserve the two mandatory user gates and the no-mutation-before-Gate-B invariant.
- Preserve exact-path repair boundaries and finite retry limits.
- Keep runtime dependencies in the Python standard library unless the package metadata and tests are intentionally revised.

## Validation

Run:

```bash
make validate
```

For a distributable archive:

```bash
make package
```
