# Demo workflow

Run the lifecycle in this exact order:

```text
init
freeze-context
check-scope
record-coverage
dispatch-assignments
ingest-results
gate-findings
```

The scope check is a prerequisite for recording coverage against the frozen source.
