---
name: material-code-review
description: Evidence-gated code review and bounded repair for Codex and other Agent Skills hosts. Freeze the exact change scope, independently validate findings, show kept and discarded candidates, require user approval of findings and the exact repair plan, apply checkpointed fixes, and prevent open-ended improvement loops.
---

# Material Code Review — portable source-tree adapter

The native Codex plugin entrypoint is `.codex-plugin/plugin.json`, which discovers the canonical skill under `skills/material-code-review/`. This root adapter is provided for Agent Skills hosts or local tooling that load the complete source tree as one skill.

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
