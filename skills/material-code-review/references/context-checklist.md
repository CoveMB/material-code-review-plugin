# Phase 0 context checklist

Use this checklist before candidate generation. Record omitted areas as limitations rather than silently assuming coverage.

## Scope identity

- Confirm the repository root, branch, HEAD, baseline, comparison, scope mode, changed files, untracked files, and `scope_hash`.
- For ref or remote scope, inspect comparison-side files through the frozen source snapshot or reviewed ref. Never use an unrelated workspace copy as evidence.
- Run `reviewctl check-scope` immediately before reviewer dispatch.

## Repository instructions and intent

- Read applicable `AGENTS.md`, `CLAUDE.md`, contribution guides, test conventions, security rules, and directory-local instructions.
- Gather task, PR, issue, plan, commit, or conversation intent. Mark intent as explicit, inferred, or uncertain.
- Identify settled user decisions. Alternative-preference findings against a settled decision are normally discarded unless the selected approach is demonstrably defective or infeasible.

## Code and behavior

For each changed behavior, inspect enough context to answer:

- Who calls it and under what inputs?
- Which guards, types, middleware, framework behavior, transactions, retries, and permissions already apply?
- What persistent state, external service, filesystem, process, or public contract can it affect?
- Which tests, docs, schemas, examples, and parallel implementations define expected behavior?
- Is an apparent issue introduced, exposed, merely adjacent, or unrelated and pre-existing?

## Risk signals

Select conditional lenses only when the actual change warrants them: authentication, authorization, secrets, user input, public APIs, migrations, data mutation, async/concurrency, retries/timeouts, external APIs, caching, heavy queries, serialization, deployment gates, or privacy-sensitive data.

## Dispatch bundle

Give each reviewer the same frozen scope identity, changed-file list, source/diff bundle, intent, applicable instructions, relevant context paths, schema path, and its bounded lens. Do not include another reviewer's candidates.
