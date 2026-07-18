# Context and behavior checklist

Use this before candidate generation. Record omissions as limitations rather than filling them with convention or model memory.

## Scope identity

- Confirm repository root, branch, HEAD, scope mode, selected prefixes, exclusions, tracked/untracked policy, file list, snapshot limitations, and `scope_hash`.
- In `codebase` mode, cite evidence from the `comparison` snapshot. There is no meaningful baseline tree.
- Confirm the selected area is small enough to review faithfully. A file inventory is not proof that every file was semantically inspected.
- Run `simplifyctl.py check-scope` immediately before dispatch, adjudication, planning, Gate B, and mutation.

## Instructions and intent

- Read applicable `AGENTS.md`, `CLAUDE.md`, contribution guides, ADRs, generation instructions, test conventions, and directory-local rules.
- Gather task, issue, PR, plan, commit, and conversation intent. Label each source explicit, inferred, uncertain, or contradictory.
- Identify settled decisions and compatibility commitments. A different design preference is not a simplification finding.
- Identify generated, vendored, migration, schema, lockfile, and deployment-controlled areas.

## Behavior boundary

For each selected subsystem, identify:

- public APIs, CLI commands, events, jobs, routes, schemas, and configuration;
- callers and downstream consumers;
- validation, authorization, privacy, and security boundaries;
- persistent state, data formats, migrations, caches, external services, filesystem/process effects, and message ordering;
- error type/message/status/retry/fallback semantics that callers may rely on;
- concurrency, transaction, idempotency, timeout, and temporal assumptions;
- dynamic loading, reflection, decorators, plugin registration, framework conventions, and generated references;
- tests and documents that establish behavior, and gaps where behavior remains uncertain.

## Architecture map

Record:

- entry points and major flows;
- ownership of policy, state, mapping, serialization, errors, retries, and side effects;
- dependency direction and cross-layer calls;
- intentional boundaries and justified duplication;
- likely hotspots, with evidence rather than complexity adjectives;
- “leave as is,” minimal local reduction, and boundary-level alternative only where a hotspot is evidenced.

## AI-assisted-code routing notes

AI-agent provenance may justify checking for recurring patterns, but never increases severity or confidence. Record only observable signals such as:

- recently introduced broad scaffolding;
- repeated generated comments or duplicated implementations;
- dependencies or APIs that need authoritative verification;
- tests that appear to restate implementation logic;
- compatibility layers or fallback paths without a documented consumer.

Do not write “AI-generated” as the reason a candidate should be kept.

## Dispatch bundle

Every reviewer receives the same:

- frozen scope identity and selected file list;
- architecture/behavior map;
- intent and repository rules;
- applicable risk boundaries;
- candidate schema location;
- one bounded lens and explicit exclusions;
- instruction not to read other reviewer outputs.
