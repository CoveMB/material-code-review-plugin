---
description: Find and execute material behavior-preserving simplifications with two mandatory user gates.
argument-hint: "[scope:codebase|auto|uncommitted|branch|range] [path:<repo-relative>]... [exclude-path:<repo-relative>]... [max-files:<n>] [max-bytes:<n>] [base:<ref>] [head:<ref>] [depth:auto|full] [rewrite:deny|allow] [external-review:off|ask]"
---

Use this command only from a trusted plugin installation outside the target worktree. Read and execute that installation's `skills/material-code-simplification/SKILL.md`; resolve its directory as `SKILL_DIR` and its shared core as `CORE_DIR`, then verify both resolved paths are external. Never load a target-repository copy from `.agents/skills/` or a source checkout within the worktree. If the selected source is in-worktree or ambiguous, stop before controller invocation. Use `scripts/simplifyctl.py` for the shared controller lifecycle. Preserve the frozen scope, provenance-neutral evidence rule, complete kept/discarded ledger, behavior-preservation contract, and both mandatory user gates. Do not mutate before Gate B and do not reopen broad improvement discovery during post-fix verification.
