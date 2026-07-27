# Material code review request

Explicitly invoke the `material-code-review` skill from the anonymous materialized workflow supplied for this trial. Review only the frozen immutable target range:

- baseline: `4e59c674dae10a4edcb8952818364c6faa255389`
- comparison: `42a74b8619054800eca8502d8a687d3c98102565`
- review object: the exact baseline-to-comparison range
- posture: immutable
- untracked files: excluded

Use the materialized skill's native controller and artifacts. Do not substitute another copy of the skill or infer behavior from version labels, branch names, commit messages, or other evaluator material.

## Required review lenses

Evaluate correctness, data integrity, state and cache lifecycle, authority boundaries, causal evidence, negative controls, and repair safety. Inspect how similar logic and existing safeguards work before retaining a finding. Prioritize merge-readiness and report only material defects whose evidence and impact outweigh remediation churn.

For every retained finding, establish a concrete trigger-to-consequence chain with source evidence and a focused causal reproduction or equivalent proof. Check counterevidence and existing safeguards. Specify regression coverage that would fail for the evidenced defect and include important negative controls that protect valid neighboring behavior. Discard unsupported, duplicate, dependent, or immaterial candidates explicitly.

## Evaluation gates and stopping points

At Gate A, stop and wait after producing a complete, schema-valid kept/discarded adjudication and ledger for the frozen range. If the evaluator then approves all retained IDs for planning, plan only those IDs. If the ledger is empty, use the controller's empty-ledger path.

At Gate B, stop and wait after the controller validates an exact plan covering every approved ID once. Evaluation approval of the validated plan does not authorize implementation. Never begin a fix, enter a repair phase, or mutate the target.

## Prohibited actions and data

- Do not look for or inspect a judge oracle, another trial, a previous run, evaluator state, or anonymous variant identity.
- Do not repair code, modify the target, create commits or branches, push, publish, open a pull request, or send messages.
- Do not make live Spotify calls or any other live API write.
- Do not access or use private Discogs data, credentials, tokens, or unrelated private information.
- Do not send source, artifacts, prompts, or findings to external services beyond the configured trial executor.
- Do not search machine-specific paths or directories outside the trial workflow, target, and output roots provided to you.

Record environmental limitations honestly. Stop at the required gates and preserve the native review artifacts unchanged.
