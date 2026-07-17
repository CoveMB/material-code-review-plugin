---
description: Run the evidence-gated material code-review workflow and stop at mandatory user gates.
argument-hint: "[scope:auto|uncommitted|branch|range] [base:<ref>] [head:<ref>] [depth:auto|full] [external-review:off|ask]"
---

Read and execute `skills/material-code-review/SKILL.md`. Resolve its directory as `SKILL_DIR`. Preserve the frozen-scope controls and stop at Gate A and Gate B for explicit user decisions. Do not mutate code before Gate B.
