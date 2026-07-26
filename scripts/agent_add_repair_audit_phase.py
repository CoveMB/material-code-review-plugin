#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
skill_path = root / "skills/material-code-review/SKILL.md"
text = skill_path.read_text(encoding="utf-8")

anchor = '''Do not batch unrelated findings into one validator context. Fresh per-finding context is the point. Bound validator concurrency and total attempts; never drop P0/high-impact candidates solely because validator infrastructure failed. Instead mark validation degraded and route the uncertainty visibly to Gate A.

#### 2.2 Adjudication
'''
replacement = '''Do not batch unrelated findings into one validator context. Fresh per-finding context is the point. Bound validator concurrency and total attempts; never drop P0/high-impact candidates solely because validator infrastructure failed. Instead mark validation degraded and route the uncertainty visibly to Gate A.

#### 2.2 Repair-direction audit

Use `references/remediation-auditor-template.md`, `references/remediation-rubric.md`, and `references/test-evidence-rubric.md`. The audit determines whether the candidate suggestions support one safe provisional repair direction. It does not revalidate the finding, discover a new finding, or produce the exact Gate-B plan.

Require a fresh repair-direction audit whenever a kept candidate group is blocker or high severity; concerns security, privacy, public APIs, configuration, schemas, serialization, migration, concurrency, or authorization; has medium, high, or unknown fix risk; requires a user decision; crosses canonical contract owners; or contains materially different candidate repair suggestions. A mechanically entailed low-risk local correction may use a controller-direct audit, but label the weaker independence accurately.

The audit must compare the literal candidate suggestion with the smallest safe root-cause correction, preserve material states and exceptions, reject guessed authority, keep orthogonal policy dimensions separate, and name causal verification evidence. A real finding remains valid when its direction is `needs_refinement`, `needs_user_decision`, `unsafe_to_apply`, or `insufficient_evidence`.

#### 2.3 Adjudication
'''
if text.count(anchor) != 1:
    raise RuntimeError(f"expected one validation-to-adjudication anchor, found {text.count(anchor)}")
text = text.replace(anchor, replacement, 1)

old_list = '''6. choose `keep` or `discard` with a reason code;
7. produce no new finding that lacks a candidate ID.
'''
new_list = '''6. choose `keep` or `discard` with a reason code;
7. attach one canonical provisional `repair_direction` to every kept group and null to every discarded group;
8. keep finding confidence separate from repair-direction status and confidence;
9. produce no new finding that lacks a candidate ID.
'''
if text.count(old_list) != 1:
    raise RuntimeError(f"expected one adjudicator requirement list, found {text.count(old_list)}")
text = text.replace(old_list, new_list, 1)

if text.count("#### 2.3 Merge-readiness decision") != 1:
    raise RuntimeError("expected one merge-readiness heading")
text = text.replace("#### 2.3 Merge-readiness decision", "#### 2.4 Merge-readiness decision", 1)

old_gate = "- every kept `F###` finding with evidence, impact, confidence, validation result, risk, and recommendation;\n"
new_gate = "- every kept `F###` finding with evidence, impact, finding confidence, validation result, risk, and the provisional repair direction's status, confidence, constraints, alternatives, causal evidence, open decisions, and known limits;\n"
if text.count(old_gate) != 1:
    raise RuntimeError("expected one Gate-A kept-finding bullet")
text = text.replace(old_gate, new_gate, 1)

old_plan = '''- root cause and observable goal;
- ordered, concrete repair steps;
'''
new_plan = '''- root cause and observable goal;
- the provisional repair direction, constraints, states and exceptions, and any material reason the exact plan differs from it;
- alternatives considered and why the selected repair is the smallest safe root-cause correction;
- ordered, concrete repair steps;
'''
if text.count(old_plan) != 1:
    raise RuntimeError("expected one Phase-3 plan requirements anchor")
text = text.replace(old_plan, new_plan, 1)
skill_path.write_text(text, encoding="utf-8")

test_path = root / "skills/material-code-review/tests/test_repair_direction_contract.py"
test_text = test_path.read_text(encoding="utf-8")
marker = '''    def test_valid_direction_is_normalized_without_candidate_suggestion(self) -> None:
'''
test = '''    def test_skill_requires_a_conditional_repair_direction_audit(self) -> None:
        skill_text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("#### 2.2 Repair-direction audit", skill_text)
        self.assertIn("Require a fresh repair-direction audit whenever", skill_text)
        self.assertIn("smallest safe root-cause correction", skill_text)

'''
if test_text.count(marker) != 1:
    raise RuntimeError("expected one repair-direction test insertion marker")
test_path.write_text(test_text.replace(marker, test + marker, 1), encoding="utf-8")
