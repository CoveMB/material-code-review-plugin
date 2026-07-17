# Post-fix verifier template

Review the fix-only bundle after `prepare-verification`. Your scope is intentionally narrow:

- every Gate-A-approved finding by stable ID;
- whether its supported root cause is resolved;
- the approved tests and evidence for that finding;
- regressions demonstrably caused by the repair delta.

Do not conduct a broad code-quality or improvement review. A newly noticed unrelated issue belongs only in `record_only_observations` and cannot affect the verdict or start work.

A `repair_required` verdict is valid only for an unresolved approved finding or a fix-caused regression. Every regression must quote current code, set `caused_by_fix: true`, identify its approved repair owner, and keep proposed repair paths inside that owner's already approved paths. A new path or strategy requires plan amendment, not an in-place repair loop.

Use `blocked` when evidence is uncertain or inaccessible. Use `pass` only when all approved findings are resolved and no fix-caused regressions remain. Return exactly `schemas/verification.schema.json`.
