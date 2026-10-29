Read this procedure before drafting or validating the plan or presenting Gate B; Gate A must have approved its exact IDs. Apply all common invariants, gates, stop and failure rules in `SKILL.md`.

Paths such as `references/...` and `examples/...` are relative to `SKILL_DIR`; shared schemas and remediation references use the entrypoint-resolved `SCHEMA_DIR` and `CORE_DIR`.

Before planning commands, tests or rollback, also read `references/refactorer-template.md` for the execution/restoration constraints the plan must satisfy. Reading it is not authorization to execute its cycle.

### Phase 4 — Plan only Gate-A-approved transformations

Use `references/planner-template.md` and shared fix-plan/v2.

Create exactly one plan item per Gate-A-approved `F###`. One item may span several exact files. If two IDs require one indivisible transformation, stop for re-adjudication or a plan amendment; do not combine IDs into an unrepresentable plan item.

Follow every item field and test-quality guard in `references/planner-template.md`. In particular, bind `repair_direction_assessment` to the approved direction hash and handle every constraint, state/exception, and open decision; encode the exact transformation class at the start of `objective`; name exact ownership and allowed paths; order characterization before uncertain destructive work; address overlap, compatibility, migration, generated code, dependencies, rollback, and 1–3 attempts; and specify exact non-mutating tests and success evidence.

The shared controller loads the hash-verified ledger through the Gate A receipt and rejects legacy fix-plan/v1, a stale direction hash, incomplete or reordered handling, an omitted decision, or unexplained divergence.

#### Test strategy

Prefer the behavior-level, characterization, contract, compatibility, boundary, build, dependency, packaging, and old-path-removal evidence applicable to the approved change. Do not substitute incidental implementation-shape assertions.

A characterization command may run before destructive work, but that baseline run does not satisfy final retention after the allowed paths change; rerun it after the final item edit so the latest required result is current.

The shared controller hashes each required per-item test against that item's full allowed-path subset. If a later item changes an overlapping path, the earlier required test becomes stale. Prefer disjoint item boundaries; otherwise make earlier local checks optional evidence and require the relevant final-state command globally after all items are fixed. Do not hide overlap by omitting it from `allowed_paths`.

Do not add tests whose only purpose is to freeze incidental implementation structure. Do not replace precise assertions with snapshots or mocks merely to make change easier.

Set the shared plan loop controls exactly as required by the controller:

- `no_unrelated_cleanup: true`;
- `no_new_improvements_during_fix: true`;
- `post_fix_review_scope: approved_findings_and_fix_introduced_regressions_only`;
- `scope_expansion_policy: restore_and_reapprove`;
- `max_repair_rounds`: normally 1; never more than 2.

Validate the plan:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" validate-plan \
  --repo-root . \
  --input /tmp/simplification-plan.json
```

Validation does not grant write permission.
