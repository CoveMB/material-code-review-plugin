# Phase 0 context and change-unit checklist

Use this checklist before candidate generation. Record omitted areas as limitations rather than silently assuming coverage.

## Scope identity

- Confirm repository root, branch, HEAD, baseline, comparison, scope mode, changed files, untracked policy, and `scope_hash`.
- For ref or remote scope, inspect comparison-side files through the frozen source snapshot or reviewed ref. Never use an unrelated workspace copy as evidence.
- Run `reviewctl check-scope` after the inventory is prepared and immediately before `record-coverage`.

## Repository instructions and intent

- Read applicable `AGENTS.md`, `CLAUDE.md`, contribution guides, test conventions, security rules, and directory-local instructions.
- Gather task, PR, issue, plan, commit, or conversation intent. Mark intent as explicit, inferred, or uncertain.
- Identify settled user decisions. Alternative-preference findings against a settled decision are normally discarded unless the selected approach is demonstrably defective or infeasible.

## Change-unit inventory

Build `change_units` around coherent behavior or contract ownership, not directory layout or reviewer persona.

- Every changed comparison path appears exactly once in one unit's `primary_paths`.
- A unit may cross files when they jointly implement one contract. Do not combine unrelated contracts because one reviewer could inspect them together.
- Record a concise `purpose`, one exact `canonical_owner` from `primary_paths`, every other primary path in `affected_consumers`, and any unchanged `context_paths` and consumers needed to evaluate the contract.
- Context paths must be canonical repository-relative tracked regular files from the comparison tree. Symlinks, untracked files, deleted files, unsafe spellings, and unrelated checkout copies are not valid context.
- Keep frozen context within 32 files, 2 MiB per file, and 25 MiB total.

For each unit, inspect callers, guards, types, middleware, framework behavior, transactions, retries, permissions, persistent state, external services, filesystem behavior, public contracts, tests, docs, schemas, examples, and parallel implementations. Distinguish behavior introduced or exposed by the change from adjacent pre-existing behavior.

## Exhaustive controlled-risk decisions

For every unit, classify every controlled code in `references/review-obligations.md` exactly once. Put positive codes in `risk_codes` and `selected_risk_rationale`; put all remaining codes in `rejected_risk_rationale`.

A positive rationale names concrete `evidence_paths` within the unit's primary and frozen context paths. A negative rationale states the checked non-trigger evidence. Filenames are hints only and cannot establish either decision.

Every positive `(unit_id, risk_code)` pair creates exactly one `review_obligation` with the controlled lens and checks. It also creates exactly one obligation assignment. Add the three mandatory core assignments in every plan. Add only the controlled supporting assignments required by a selected risk. Ordinary low-risk plans have three core assignments and no obligations.

## Exhaustive specialist decisions

For every unit, `specialist_decisions` classifies exactly these eight lenses as `selected` or `rejected`: `security_privacy`, `reliability`, `api_contract`, `migration_deployment`, `concurrency`, `performance`, `documentation`, and `architecture_simplification`.

Under `depth:auto`, select a lens when behavior evidence makes it applicable. Ambiguous or unknown evidence selects the lens; reject only with concrete behavior-based non-trigger evidence. Under `depth:full`, select all eight lenses for every unit with `full_depth` basis.

Every selected decision defines non-empty atomic `scenario_checks`. Each check has a plan-unique canonical code, one bounded behavior or failure-path claim, non-empty evidence paths from that unit, and a concrete countercontrol that could disprove the claim. Rejected decisions have an empty scenario list; generic lens restatements are invalid.

Create exactly one specialist assignment per selected lens. Bind it to the exact selected `unit_ids`, the exact union of those units' `primary_paths` and `context_paths`, and the exact union of the selected scenario codes. Specialist selection is independent of the six controlled risks: it cannot add, replace, or satisfy a core assignment, review obligation, or obligation-derived supplemental assignment.

## Dispatch bundle

Give each assignment the frozen scope and context identities, `coverage_plan_hash`, `coverage_context_hash`, exact `assignment_id` and `assignment_kind`, assigned lens and process identity, exact `required_review_paths`, and exact `required_checks`. Include any exact `obligation_id` plus the canonical check definitions, or for a specialist the exact `unit_ids`, paths, and scenario definitions. Supply `schemas/candidate-set-v5.schema.json`. Do not include another assignment's candidate output.

## Evidence-side identity

- Baseline evidence for a rename or copy addresses the exact `old_path`.
- Comparison evidence addresses only the exact current changed `path`; an old name recreated as a separate changed path is distinct authority.
- A matched comparison path whose frozen state is missing remains missing. Do not substitute a same-named coverage-context source.
- Use unchanged bounded coverage context only when the requested comparison path has no changed-path match.
- Verify the frozen byte hash and exact requested line range before accepting the quote.
