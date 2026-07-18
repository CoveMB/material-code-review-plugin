# Bounded simplification implementer template

Use only after the exact plan hash passed Gate B and `simplifyctl.py begin-fix` succeeded. Process exactly one approved finding at a time. One finding may authorize an atomic multi-file transformation; distinct `F###` items are never edited concurrently.

## Cycle

1. Run `start-finding` for the approved ID.
2. Re-read the plan item, behavior boundary, exact allowed paths, transformation class, tests, and rollback.
3. When required, add characterization evidence first and run the approved command before destructive work.
4. Apply the smallest approved root-cause transformation.
5. Prefer deleting obsolete paths to retaining old and new implementations in parallel. Preserve a compatibility path only when Gate B explicitly requires it and defines its boundary.
6. Do not introduce a new abstraction, dependency, configuration option, fallback, retry, cache, async layer, or generic framework outside the approved shape.
7. Do not mix broad formatting, renaming, comments, generated churn, or unrelated cleanup into the semantic delta.
8. Do not weaken tests, validation, authorization, error semantics, data compatibility, ordering, concurrency, or idempotency to obtain a passing result.
9. Run every required approved test through the controller in the planned sequence.
10. Inspect the item delta for moved-not-removed complexity, duplicate replacement logic, old-path reachability, compatibility shadows, generated artifacts, dependency drift, and unapproved paths.
11. Finish as fixed only when evidence passes. Otherwise restore the item checkpoint.

## Rewrite behavior

A bounded rewrite replaces only the Gate-B-approved boundary. Keep the old implementation available only through the controller checkpoint, not as a permanent “safe” parallel path, unless the plan explicitly approves a migration bridge. Do not regenerate adjacent subsystems.

If implementation reveals an unapproved path, public contract change, data migration, security consequence, or materially different strategy, stop and restore. A confident workaround is not authorization.

Do not stage, commit, switch branches, push, open a PR, post comments, or file tickets. The controller is an integrity/restoration layer, not an OS sandbox; execute only the exact approved commands and explicit repair steps.
