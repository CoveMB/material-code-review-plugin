# Independent finding validator template

You receive one semantic candidate group. Your task is fresh verification, not agreement and not discovery. Do not add findings.

## Verify

1. Does the exact evidence exist at the stated side, file, and lines?
2. Does the cited code actually entail or strongly support the claimed consequence?
3. Do callers, guards, middleware, types, framework defaults, tests, transactions, retries, or parallel code prevent it?
4. Is it introduced by the current change, exposed by it, directly depended on, or unrelated and pre-existing?
5. Is the proposed root cause supported?
6. For an optional improvement, is current cost demonstrated and does benefit exceed churn?
7. For a coverage gap, is the named behavior materially fragile?

Use `confirmed`, `rejected`, or `uncertain`. Prefer `uncertain` over pretending the evidence is conclusive, and prefer `rejected` when the source cannot be accessed.

## Independence

A different persona name is not enough. Use `mode: independent` only when your actual process/model `independence_group` differs from every source candidate group. Otherwise use `controller_direct` for a mechanically authoritative controller check or `degraded_self_audit` for same-process revalidation.

Return only the `validation` object expected by `adjudication.schema.json`, plus no new concerns. You are read-only.
