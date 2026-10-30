---
name: material-code-review
description: Review concrete Git changes (uncommitted, branch/diff, ref range, or PR) for material defects, regressions, behavior-protecting test gaps, or merge readiness, with evidence-gated repair. Implicit use excludes document/generated-output review, output diagnosis, general skill/plugin/repository analysis, architecture exploration, and planning-only work.
---

# Material Code Review — portable source-tree adapter

The native Codex plugin entrypoint is `.codex-plugin/plugin.json`, which discovers the canonical skill under `skills/material-code-review/`. This root adapter is provided for Agent Skills hosts or local tooling that load the complete source tree as one skill.

This adapter exposes material review only. To discover both material review and material simplification in OpenCode v2 or Antigravity, install the two complete sibling directories from `skills/` under `.agents/skills/`, or extract each standalone archive into its own named skill directory. Do not nest the repository root under a skill source and expect both skills to appear: OpenCode stops discovery inside a directory containing `SKILL.md`.

## Load the canonical workflow

1. Resolve `PACKAGE_ROOT` as this file's directory.
2. Read `PACKAGE_ROOT/skills/material-code-review/SKILL.md` completely.
3. Treat `PACKAGE_ROOT/skills/material-code-review` as `SKILL_DIR` for scripts, schemas, references, metadata, and tests.
4. Use:

```bash
python3 "$SKILL_DIR/scripts/reviewctl.py" --help
```

On Windows, use `py -3`. Do not improvise around a failed controller precondition. Preserve the last valid state and report the exact failure.

## Host adaptation

- In Codex, read applicable target-repository `AGENTS.md` files and use bounded read-only subagents where available.
- In Claude Code, use the packaged agents and command surface.
- On any host, mutation begins only after Gate B approves the exact plan hash, paths, and commands.
- Stop for explicit user responses at Gate A and Gate B. Never infer approval from silence, prior task approval, or confidence.
- Do not send source code to another model, CLI, connector, or app without explicit egress approval.

Continue with the canonical skill now.
