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

## Exhaustive targeted coverage

Before reviewer dispatch, record exactly one positive or negative assessment for each controlled code. A positive assessment names normalized frozen-scope evidence paths; a negative assessment leaves `evidence_paths` empty and records the checked non-trigger evidence. Filenames alone never establish either trigger.

| Code | Positive trigger | Required lenses when present | Non-trigger evidence |
|---|---|---|---|
| `user_selectable_output_paths` | Changed behavior writes multiple authoritative or auxiliary artifacts and at least one destination is user-selectable, including when a pre-existing selectable path gains a new artifact, writer, cleanup target, or write order that creates a collision opportunity. | `reliability` | Checked destinations, writers, cleanup, and ordering show no user-selectable destination with a new collision opportunity. |
| `persisted_config_semantics` | Changed behavior alters an optional persisted field's accepted shape, serialization, default, missing-key fallback, interpretation, migration, durable output, or downstream local/remote identity. | `migration_data_safety`, `api_config_compatibility` | Checked field shape, serialization, defaults, fallbacks, interpretation, migration, durable output, and downstream identity show no affected optional persisted-field semantics. |

## Dispatch bundle

Give each reviewer the same frozen scope identity, changed-file list, source/diff bundle, intent, applicable instructions, relevant context paths, the verified coverage-plan hash, its exact assigned lens ID, the assigned risk evidence paths, and the material-review candidate-set/v2 schema path. Do not include another reviewer's candidates.
