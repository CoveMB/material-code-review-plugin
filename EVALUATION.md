# Evaluation and design rationale

## What the source workflows do well

### recursive-mode

The strongest properties are process integrity rather than reviewer cleverness:

- repository artifacts are the durable source of truth;
- phase inputs are reread instead of trusted from chat memory;
- audited work loops through draft, audit, repair, re-audit, pass, and lock;
- diff basis is normalized and executable rather than informally inferred later;
- delegated review receives a complete bundle and is verified by the controller;
- repaired scope invalidates stale review evidence;
- locked artifacts and hashes make accidental rewriting visible.

These controls directly address context drift, stale conclusions, and unsupported claims. The full recursive-mode workflow is too broad for a focused review plugin, so this package adopts its evidence, hashing, freshness, and controller-verification ideas without importing its requirements-to-memory lifecycle.

### ce-code-review

The strongest properties are review precision and scope correctness:

- it distinguishes local-aligned, remote-PR, and remote-branch review trees;
- it fails closed when scope signals are unknown;
- it uses specialist reviewer lenses selectively;
- reviewer outputs have a strict machine-readable contract;
- evidence at high confidence must quote the source line;
- findings are deduplicated and independently validated;
- subagent capacity failures are treated as backpressure rather than substantive review failure;
- pre-existing issues and weak maintainability/testing observations are routed away from primary findings.

The current skill also applies fixes automatically in its default mode. That is intentionally not adopted here because the requested workflow requires an explicit finding gate and an explicit plan gate before mutation.

## Evaluation of the original review prompt

### Strong parts retained

- It explicitly rejects brainstorming and aesthetic advice.
- It defines relevant categories without limiting the number of findings.
- It requires concrete evidence, consequence, value beyond style, and a favorable benefit/churn tradeoff.
- It has useful simplification, DRY, and deduplication constraints.
- It requires a merge-readiness decision and a rejected-candidate section.
- It includes a stop condition that discourages broad follow-up passes.

### Material weaknesses corrected

1. **One model both discovers and scores its own findings.** Self-scoring does not create independence and tends to preserve the model's first framing. The new workflow separates discovery, validation, and adjudication.
2. **The 1–5 scores imply more calibration than the evidence supports.** The package uses behavioral confidence anchors but treats evidence and validation as the actual gates.
3. **No frozen scope.** A review can become stale while agents read or edit. Every artifact is bound to a scope hash, ledger hash, or plan hash.
4. **No explicit reviewed-tree rule.** Remote diffs can be accidentally checked against local files. The package records source mode and refuses mutation when the workspace is not the reviewed tree.
5. **No strong diff-causality rule.** Pre-existing concerns can leak into review. Candidates must declare primary, secondary, or pre-existing relation and direct dependency.
6. **Evidence is prose-only.** High-confidence candidates now carry a verifiable source quote, side, line range, and source path.
7. **The “fix must be smaller than leaving it” rule can hide serious defects.** The benefit/churn test remains mandatory for optional improvements, but not as a validity gate for a demonstrated serious defect.
8. **Impact and confidence alone decide externalization.** High-impact uncertainty now triggers explicit validation or a visible degraded/verification-required state rather than a numeric exception.
9. **“Spawn subagents if appropriate” is underspecified.** The skill defines capability probing, role boundaries, bounded scheduling, independence groups, controller verification, and self-audit fallback.
10. **No malformed-output handling.** JSON contracts and the control tool reject missing fields, invalid enums, duplicate IDs, incomplete dispositions, stale hashes, or unapproved plan items.
11. **No user-gate receipts.** Both approvals are persisted against exact artifact hashes.
12. **No repair boundary or rollback mechanism.** Each repair has a checkpoint, exact allowed paths, executable tests, and restoration behavior.
13. **No loop boundary.** Post-fix review is restricted to approved findings and fix-caused regressions, with finite attempts and repair rounds.
14. **“Do not change code” conflicts with the desired endpoint.** It is now phase-scoped: review and adjudication are read-only; mutation begins only after Gate B.
15. **Untracked files are ambiguous.** They are included by default for uncommitted review and fingerprinted explicitly.
16. **External code egress is not addressed.** Routed or cross-model review requires user opt-in and recipient disclosure.

## Main design choice

Finding validity and fix permission are separate decisions:

- independent evidence determines whether a finding belongs in the material ledger;
- Gate A determines whether the user wants that finding addressed;
- a concrete plan determines how it would be addressed;
- Gate B grants permission for those exact edits and commands;
- tests and post-fix verification determine whether the result is retained.

This separation is the main defense against both false-positive review output and over-eager autonomous modification.

## Known limitations

- This repository has no behavioral skill-selection evaluation harness. Static validation can prevent the packaged activation metadata and preflight from drifting, but implicit selection remains model-mediated and cannot be proven by these tests.
- The control tool can enforce files, hashes, commands, state transitions, and local restoration. It cannot prove that an AI reviewer reasoned correctly; independent review and user gates reduce but do not eliminate that risk.
- A passing targeted test is evidence, not proof that auth, concurrency, distributed-system, migration, or public-contract changes are safe.
- Host platforms expose different subagent, model-routing, and plugin APIs. The skill contains fallbacks, but exact parallelism and model identity remain host-dependent.
- Workspace restoration assumes normal Git working-tree behavior. Exotic filters, submodules, sparse checkouts, filesystem races, and generated/ignored files require human review.

## Codex compatibility audit

The initial package's canonical `SKILL.md` already matched the portable Agent Skills shape, but the distribution was not a native Codex plugin because it lacked `.codex-plugin/plugin.json`. It also lacked the Codex marketplace catalog and `agents/openai.yaml` metadata. Version 1.1.0 adds all three.

A second packaging defect was found during this audit: the README and canonical skill referenced schemas, stage templates, agents, wrappers, and validation files that were absent from the source directory. Native discovery alone would therefore have produced a partially broken workflow. The release now includes those files and validates all canonical references before packaging.

Codex integration is intentionally skill-only: no MCP server, connector, lifecycle hook, or external service is required. Codex-native subagents are treated as optional read-only workers. The controller never assumes that agent names imply model or process independence.

The remaining uncertainty is host-level rather than package-level: the build environment did not contain the Codex executable or ChatGPT desktop Plugins Directory, so installation, UI metadata rendering, and native subagent dispatch could not be exercised end to end. The ZIP is validated after extraction, and the controller suite runs independently of the host.
