Read this procedure before plan-level checks or post-refactor verification; all approved items must have their recorded disposition. Apply all common invariants, gates, stop and failure rules in `SKILL.md`.

Paths such as `references/...` and `examples/...` are relative to `SKILL_DIR`; shared schemas and remediation references use the entrypoint-resolved `SCHEMA_DIR` and `CORE_DIR`.

### Phase 6 — Bounded post-refactor verification

After all approved items are retained, run each required plan-level check and then prepare verification:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" run-global-test --repo-root . --test <approved-global-test-id>
python3 "$SKILL_DIR/scripts/simplifyctl.py" prepare-verification --repo-root .
```

Omit the first line only when the validated plan contains no required global test.

Use a fresh read-only verifier and `references/postfix-verifier-template.md`. For each approved ID, verify:

Apply every template check against source and test evidence: prove the root cause was removed rather than moved, required behavior and tests remain intact, obsolete paths are gone, no replacement recreates the complexity, no in-boundary regression was introduced, and every edit remains within Gate-B-approved paths.

Do not run a broad “what else can be simplified?” pass. Unrelated observations are record-only and cannot reopen candidate generation.

Record verification with the shared controller:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" record-verification \
  --repo-root . \
  --input /tmp/simplification-verification.json
```

A bounded repair round may address only unresolved approved IDs or regressions caused by their changes, within approved paths and remaining budgets. Anything else requires restoration and a new Gate B.
