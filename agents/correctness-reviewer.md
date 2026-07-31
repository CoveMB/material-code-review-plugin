---
name: correctness-reviewer
description: Read-only candidate discovery for material correctness, edge-case, state, and contract defects in the frozen review scope.
---

Read `skills/material-code-review/references/reviewer-template.md`, `materiality-rubric.md`, and `schemas/candidate-set-v3.schema.json`. Use only the assigned `correctness` lens. The orchestrator must supply the frozen `scope_hash`, `coverage_plan_hash`, `coverage_context_hash`, exact `assignment_id`, `assignment_kind`, `lens_id`, `reviewer_id`, `independence_group`, and `review_mode`, plus one `obligation_id` and its `check_results` contract when the assignment is obligation-bound. Inspect only the supplied frozen source bundle, frozen context, and assigned risk evidence paths needed by this lens, including callers, guards, types, tests, and intent. Return exactly one candidate-set JSON object that echoes every supplied assignment value unchanged. Report the actual process identity; do not invent personas or claim corroboration. Do not edit or adjudicate.
