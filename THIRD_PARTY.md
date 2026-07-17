# Third-party research and attribution

This package was designed after reviewing the public workflow concepts in:

- `try-works/recursive-mode` — Apache License 2.0.
- `EveryInc/compound-engineering-plugin`, especially `ce-code-review` — MIT License.

No upstream source file is vendored in this package. The implementation, schemas, prompts, controller, and tests here were written for this package. General workflow ideas retained include file-backed state, frozen diff bases, review bundles, independent validation, explicit gate receipts, bounded repair, and controller verification.

OpenAI Codex compatibility uses the Agent Skills package shape described by current OpenAI Skills documentation: a `SKILL.md` entrypoint with supporting instructions and code. OpenAI product names and trademarks remain the property of OpenAI.
