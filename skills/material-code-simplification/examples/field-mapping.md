# Shared-schema field mapping for a simplification candidate

The shared controller rejects extra fields. Encode simplification evidence in the existing candidate contract.

```json
{
  "local_id": "duplicate-policy-owner",
  "title": "Authorization policy is implemented in three request paths",
  "nature": "improvement",
  "category": "dry",
  "severity": "medium",
  "confidence": "high",
  "file": "src/api/orders.py",
  "line_start": 81,
  "line_end": 96,
  "evidence_side": "comparison",
  "evidence_quote": "<exact frozen-source quote>",
  "scope_relation": "primary",
  "related_changed_files": ["src/api/orders.py", "src/jobs/orders.py"],
  "direct_dependency": true,
  "observable_consequence": "Changing the authorization rule requires synchronized edits in three reachable paths; two already differ in their treatment of suspended accounts.",
  "trigger_conditions": "A maintainer changes account eligibility or adds a new order entry point.",
  "counterevidence_checked": [
    "The paths use the same domain rule rather than intentionally isolated policies.",
    "No framework hook or security boundary requires independent implementations.",
    "Callers and tests were checked for different error/status contracts."
  ],
  "why_not_preference": "The current cost is duplicated policy ownership and observed divergence, not repeated syntax. Preserve the existing public status/error behavior while giving the domain rule one owner.",
  "proposed_resolution": "Move the eligibility decision to the existing OrderPolicy boundary, keep transport-specific error mapping at each entry point, and delete the duplicate rule bodies.",
  "estimated_fix_risk": "medium",
  "requires_user_decision": false,
  "assumptions": [
    "No external consumer depends on the suspended-account divergence; characterize both paths before consolidation."
  ]
}
```

In codebase mode, `direct_dependency: true` means the candidate is directly within the selected simplification boundary. The shared controller uses that flag to permit an honestly `pre_existing` retained item; it must not be used for unrelated repository observations.

This is illustrative only. Real `scope_hash`, evidence, paths, lines, callers, counterevidence, and behavior claims must come from the active frozen run.


## Shared fix-plan mapping

The shared fix-plan schema is also fail-closed and has no `transformation_class` property. Encode the class in an existing semantic field rather than adding JSON:

```json
{
  "finding_id": "F001",
  "root_cause": "Three reachable request paths own the same authorization decision.",
  "objective": "Transformation class: consolidate. Give the domain eligibility rule one owner while preserving transport-specific status and error mapping.",
  "depends_on": [],
  "steps": ["..."],
  "allowed_paths": ["src/api/orders.py", "src/jobs/orders.py", "src/domain/order_policy.py"],
  "tests": ["... shared test objects ..."],
  "manual_verification": [],
  "rollback_strategy": "Restore the per-finding checkpoint.",
  "risk_controls": ["Preserve deny-by-default behavior and public error contracts."],
  "success_evidence": ["Required behavior tests pass and duplicate rule bodies are absent."],
  "max_attempts": 2
}
```

Create exactly one plan item per approved `F###`. A single item may change several exact paths. If two approved IDs cannot be implemented separately, the grouping was wrong; stop for re-adjudication or a newly approved plan rather than inventing a combined item that the controller cannot represent.
