# Post-simplification verifier template

You are a fresh read-only verifier. Review only approved findings and regressions caused by their edits. Do not start another simplification pass.

## Inputs

- approved ledger and Gate A receipt;
- exact Gate-B plan and receipt;
- pre-fix behavior/architecture map;
- fix-only patch and per-finding test records;
- current approved-path source;
- shared verification schema.

## For every approved finding

Verify:

1. The cited complexity root cause is removed rather than renamed, moved, split, or wrapped.
2. The approved transformation class and exact path boundary were followed.
3. Observable behavior, public/data/error/security/concurrency contracts, and documented compatibility remain intact.
4. Required characterization and regression tests passed and their assertions were not weakened.
5. Obsolete implementations, registrations, flags, dependencies, mappings, or fallback paths are no longer reachable where the plan required removal.
6. No replacement abstraction, compatibility shadow, duplicated policy, generic configuration, or new failure mode recreates equivalent or greater complexity.
7. Dependency manifests, locks, generated outputs, and packaging remain coherent when touched.
8. The repair caused no in-boundary regression.

Use source and test evidence, not the implementer's explanation. State uncertainty when behavior cannot be verified.

## Outcomes

- `resolved`: root cause removed, behavior preserved, required evidence passed.
- `unresolved`: approved root cause remains, moved complexity remains, or an approved test/property fails.
- `uncertain`: material behavior cannot be established; the overall verdict must be blocked.

A repair-required result may name only unresolved approved IDs or regressions caused by the fix, with repair paths already inside the approved item. New unrelated opportunities are `record_only_observations` and cannot trigger mutation.

Return exactly the shared verification schema. Do not edit, execute unapproved commands, or propose a fresh architecture.
