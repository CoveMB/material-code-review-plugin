Read this procedure before beginning a fix or processing an approved item; the exact plan must have passed Gate B. Apply all common invariants, gates, stop and failure rules in `SKILL.md`.

Paths such as `references/...` and `examples/...` are relative to `SKILL_DIR`; shared schemas and remediation references use the entrypoint-resolved `SCHEMA_DIR` and `CORE_DIR`.

### Phase 5 — Apply transformations sequentially

Only after Gate B:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" begin-fix --repo-root .
```

Process exactly one approved ID at a time through the checkpointed cycle in `references/refactorer-template.md`. It owns characterization order, the smallest exact-path transformation, obsolete-path removal, prohibited mixed cleanup, approved tests, delta inspection, retain-or-restore behavior, and escalation when the approved boundary proves insufficient.

Controller pattern for one item:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" start-finding --repo-root . --finding F001
python3 "$SKILL_DIR/scripts/simplifyctl.py" run-test --repo-root . --finding F001 --test <approved-test-id>
# perform only the approved edit steps and rerun every required current-state test
python3 "$SKILL_DIR/scripts/simplifyctl.py" finish-finding \
  --repo-root . --finding F001 --status fixed --note "<evidence summary>"
```

When an attempt cannot be retained, restore it explicitly:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" rollback-finding \
  --repo-root . --finding F001 --reason "<failure or boundary reason>"
```

Use `references/refactorer-template.md`.

A rewrite should proceed as a bounded replacement of an approved boundary, not as a greenfield redesign. If implementation reveals a necessary new path, public contract change, data migration, or materially different strategy, restore and return to planning/Gate B.
