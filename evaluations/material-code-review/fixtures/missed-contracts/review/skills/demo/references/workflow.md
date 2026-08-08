# Demo workflow

Run the lifecycle in this exact order:

```text
init
freeze-context
record-coverage
dispatch-assignments
ingest-results
gate-findings
```

Coverage is recorded against the frozen source before dispatch.
