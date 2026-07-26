#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
R=Path(__file__).resolve().parents[1]
def rd(x): return (R/x).read_text(encoding='utf-8')
def wr(x,s): (R/x).write_text(s,encoding='utf-8')
def once(x,a,b):
 s=rd(x); n=s.count(a)
 if n!=1: raise RuntimeError(f'{x}: expected 1 anchor, got {n}: {a[:80]!r}')
 wr(x,s.replace(a,b,1))
def cmd(a,ok):
 p=subprocess.run(a,cwd=R,text=True,capture_output=True)
 print('$',' '.join(a)); print(p.stdout); print(p.stderr,file=sys.stderr)
 if (p.returncode==0)!=ok: raise RuntimeError(f'unexpected exit {p.returncode}')
 return p
FIX='''"repair_direction": {
                    "status": "reviewed",
                    "confidence": "high",
                    "root_cause": "The implementation violates the established addition contract.",
                    "objective": "Restore addition while preserving the public function signature.",
                    "smallest_safe_change": "Restore the addition operator and retain the existing API.",
                    "constraints_to_preserve": ["Keep the public add(a, b) signature unchanged."],
                    "state_or_exception_cases": ["Negative operands retain addition semantics."],
                    "alternatives_checked": ["Changing the test would redefine established behavior."],
                    "required_test_evidence": ["A regression test fails for subtraction and passes for addition."],
                    "open_user_decisions": [],
                    "known_limits": []
                }'''
def tests():
 x='skills/material-code-review/tests/test_reviewctl.py'; s=rd(x).replace('material-review/adjudication/v1','material-review/adjudication/v2')
 a='''                "recommended_action": "fix_now",\n                "required_pre_fix_verification": None,\n            }'''
 b=f'''                "recommended_action": "fix_now",\n                "required_pre_fix_verification": None,\n                {FIX},\n            }}'''
 if s.count(a)!=1: raise RuntimeError('kept fixture anchor')
 s=s.replace(a,b,1)
 a='''                    "recommended_action": "none",\n                    "required_pre_fix_verification": None,\n                }'''
 b='''                    "recommended_action": "none",\n                    "required_pre_fix_verification": None,\n                    "repair_direction": None,\n                }'''
 if s.count(a)!=1: raise RuntimeError('discard fixture anchor')
 s=s.replace(a,b,1)
 m='    def test_plan_rejects_unapproved_or_missing_ids(self) -> None:\n'
 t='''    def test_ledger_uses_adjudicated_repair_direction(self) -> None:
        scope_hash = self.init()
        candidates = self.candidate_set(scope_hash, include_style=False)
        candidates["findings"][0]["proposed_resolution"] = "Unsafe candidate suggestion."
        candidate_path = self.write_json("candidate-repair.json", candidates)
        self.run_tool("ingest-candidates", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(candidate_path))
        candidate_hash = self.load("candidates.json")["candidate_bundle_hash"]
        adjudication = self.adjudication(scope_hash, candidate_hash, include_style=False)
        adjudication["groups"][0]["repair_direction"]["smallest_safe_change"] = "Restore only the operator."
        adjudication_path = self.write_json("adjudication-repair.json", adjudication)
        self.run_tool("compile-ledger", "--repo-root", str(self.repo), "--run-id", self.run_id, "--input", str(adjudication_path))
        ledger = self.load("ledger.json")
        self.assertEqual(ledger["findings"][0]["repair_direction"]["smallest_safe_change"], "Restore only the operator.")
        rendered = (self.run_dir / "ledger.md").read_text(encoding="utf-8")
        self.assertIn("Gate A approves findings for repair planning only", rendered)
        self.assertNotIn("Unsafe candidate suggestion", rendered)
        self.assertNotIn("Suggested response", rendered)

'''
 if s.count(m)!=1: raise RuntimeError('test marker')
 wr(x,s.replace(m,t+m,1))
def schema():
 x='skills/material-code-review/schemas/adjudication.schema.json'; d=json.loads(rd(x)); d['properties']['schema_version']['const']='material-review/adjudication/v2'; g=d['properties']['groups']['items']; g['required'].append('repair_direction')
 arr={'type':'array','items':{'type':'string','minLength':1},'uniqueItems':True}
 g['properties']['repair_direction']={'oneOf':[{'type':'null'},{'type':'object','additionalProperties':False,'required':['status','confidence','root_cause','objective','smallest_safe_change','constraints_to_preserve','state_or_exception_cases','alternatives_checked','required_test_evidence','open_user_decisions','known_limits'],'properties':{'status':{'enum':['reviewed','needs_refinement','needs_user_decision','unsafe_to_apply','insufficient_evidence']},'confidence':{'enum':['certain','high','medium','low']},'root_cause':{'type':'string','minLength':1},'objective':{'type':'string','minLength':1},'smallest_safe_change':{'type':'string','minLength':1},'constraints_to_preserve':{**arr,'minItems':1},'state_or_exception_cases':arr,'alternatives_checked':arr,'required_test_evidence':{**arr,'minItems':1},'open_user_decisions':arr,'known_limits':arr},'allOf':[{'if':{'properties':{'status':{'const':'needs_user_decision'}},'required':['status']},'then':{'properties':{'open_user_decisions':{'minItems':1}}}}]}]}
 for c in g['allOf']:
  v=c.get('if',{}).get('properties',{}).get('disposition',{}).get('const')
  if v=='keep': c['then']['properties']['repair_direction']={'type':'object'}
  if v=='discard': c['then']['properties']['repair_direction']={'type':'null'}
 wr(x,json.dumps(d,indent=2)+'\n')
def controller():
 x='skills/material-code-review/scripts/reviewctl.py'; s=rd(x).replace('material-review/adjudication/v1','material-review/adjudication/v2').replace('material-review/ledger/v1','material-review/ledger/v2')
 a='RECOMMENDATIONS = {"fix_now", "defer", "monitor", "none"}\n'; b=a+'REPAIR_DIRECTION_STATUSES = {"reviewed", "needs_refinement", "needs_user_decision", "unsafe_to_apply", "insufficient_evidence"}\n';
 if s.count(a)!=1: raise RuntimeError('constant anchor')
 s=s.replace(a,b,1)
 m='\ndef validate_adjudication(raw: Any, *, candidates_bundle: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:\n'
 h='''

def validate_repair_direction(value: Any, context: str, *, required: bool) -> dict[str, Any] | None:
    if value is None:
        if required: raise ReviewError(f"{context} is required for a kept finding")
        return None
    if not required: raise ReviewError(f"{context} must be null for a discarded finding")
    obj = require_object(value, context)
    keys = {"status", "confidence", "root_cause", "objective", "smallest_safe_change", "constraints_to_preserve", "state_or_exception_cases", "alternatives_checked", "required_test_evidence", "open_user_decisions", "known_limits"}
    require_exact_keys(obj, keys, context)
    status=require_string(obj["status"],f"{context}.status"); confidence=require_string(obj["confidence"],f"{context}.confidence")
    if status not in REPAIR_DIRECTION_STATUSES: raise ReviewError(f"{context}.status is invalid")
    if confidence not in CONFIDENCES: raise ReviewError(f"{context}.confidence is invalid")
    constraints=require_string_array(obj["constraints_to_preserve"],f"{context}.constraints_to_preserve"); evidence=require_string_array(obj["required_test_evidence"],f"{context}.required_test_evidence"); decisions=require_string_array(obj["open_user_decisions"],f"{context}.open_user_decisions")
    if not constraints or not evidence: raise ReviewError(f"{context} needs constraints and causal test evidence")
    if status=="needs_user_decision" and not decisions: raise ReviewError(f"{context} must name the user decision")
    return {"status":status,"confidence":confidence,"root_cause":require_string(obj["root_cause"],f"{context}.root_cause"),"objective":require_string(obj["objective"],f"{context}.objective"),"smallest_safe_change":require_string(obj["smallest_safe_change"],f"{context}.smallest_safe_change"),"constraints_to_preserve":constraints,"state_or_exception_cases":require_string_array(obj["state_or_exception_cases"],f"{context}.state_or_exception_cases"),"alternatives_checked":require_string_array(obj["alternatives_checked"],f"{context}.alternatives_checked"),"required_test_evidence":evidence,"open_user_decisions":decisions,"known_limits":require_string_array(obj["known_limits"],f"{context}.known_limits")}
'''
 if s.count(m)!=1: raise RuntimeError('function marker')
 s=s.replace(m,h+m,1)
 a='''        "recommended_action",\n        "required_pre_fix_verification",\n    }'''; b='''        "recommended_action",\n        "required_pre_fix_verification",\n        "repair_direction",\n    }'''
 if s.count(a)!=1: raise RuntimeError('group keys')
 s=s.replace(a,b,1)
 a='''        required_pre_fix = group["required_pre_fix_verification"]\n        if required_pre_fix is not None:\n            required_pre_fix = require_string(required_pre_fix, f"{context}.required_pre_fix_verification")\n\n        if disposition == "keep":'''; b='''        required_pre_fix = group["required_pre_fix_verification"]\n        if required_pre_fix is not None:\n            required_pre_fix = require_string(required_pre_fix, f"{context}.required_pre_fix_verification")\n        repair_direction = validate_repair_direction(group["repair_direction"], f"{context}.repair_direction", required=disposition == "keep")\n\n        if disposition == "keep":'''
 if s.count(a)!=1: raise RuntimeError('parse anchor')
 s=s.replace(a,b,1)
 a='''            "recommended_action": recommendation,\n            "required_pre_fix_verification": required_pre_fix,\n        }'''; b='''            "recommended_action": recommendation,\n            "required_pre_fix_verification": required_pre_fix,\n            "repair_direction": repair_direction,\n        }'''
 if s.count(a)!=1: raise RuntimeError('normalize anchor')
 s=s.replace(a,b,1)
 a='''                "observable_consequence": representative["observable_consequence"],\n                "trigger_conditions": representative["trigger_conditions"],\n                "proposed_resolution": representative["proposed_resolution"],\n                "estimated_fix_risk": representative["estimated_fix_risk"],'''; b='''                "observable_consequence": representative["observable_consequence"],\n                "trigger_conditions": representative["trigger_conditions"],\n                "repair_direction": group["repair_direction"],\n                "estimated_fix_risk": representative["estimated_fix_risk"],'''
 if s.count(a)!=1: raise RuntimeError('compile anchor')
 s=s.replace(a,b,1).replace('                f"- Suggested response: {finding[\'proposed_resolution\']}",\n','',1)
 a='''        "## Kept material findings",\n        "",\n    ]'''; b='''        "## Kept material findings",\n        "",\n        "Gate A approves findings for repair planning only. It does not approve the provisional repair direction or authorize edits.",\n        "",\n    ]'''
 if s.count(a)!=1: raise RuntimeError('ledger header')
 s=s.replace(a,b,1)
 a='''        if finding["required_pre_fix_verification"]:\n            lines.append(f"- Required pre-fix verification: {finding['required_pre_fix_verification']}")\n        lines.append("")'''; b='''        direction = finding["repair_direction"]
        lines.extend(["- Provisional repair direction:", f"  - Status / confidence: `{direction['status']}` / `{direction['confidence']}`", f"  - Root cause: {direction['root_cause']}", f"  - Objective: {direction['objective']}", f"  - Smallest safe change: {direction['smallest_safe_change']}"])
        for label, key in (("Constraints to preserve", "constraints_to_preserve"), ("States and exceptions", "state_or_exception_cases"), ("Alternatives checked", "alternatives_checked"), ("Required test evidence", "required_test_evidence"), ("Open user decisions", "open_user_decisions"), ("Known limits", "known_limits")):
            if direction[key]:
                lines.append(f"  - {label}:")
                lines.extend(f"    - {value}" for value in direction[key])
        if finding["required_pre_fix_verification"]:
            lines.append(f"- Required pre-fix verification: {finding['required_pre_fix_verification']}")
        lines.append("")'''
 if s.count(a)!=1: raise RuntimeError('ledger detail')
 wr(x,s.replace(a,b,1))
def docs():
 x='skills/material-code-review/references/materiality-rubric.md'; s=rd(x)
 if '## Repair-direction quality' not in s: s+='''\n\n## Repair-direction quality\n\nFinding validity and repair sufficiency are separate. Use [remediation-rubric.md](remediation-rubric.md) for every kept finding and [test-evidence-rubric.md](test-evidence-rubric.md) for coverage recommendations and planned regression evidence. A real defect is not discarded merely because its candidate response needs refinement.\n'''
 wr(x,s)
 x='skills/material-code-review/SKILL.md'; s=rd(x)
 a='- `references/materiality-rubric.md` — Phases 1–2\n'; b=a+'- `references/remediation-rubric.md` — repair-direction audit, adjudication, and planning\n- `references/test-evidence-rubric.md` — coverage findings and repair-test design\n- `references/remediation-auditor-template.md` — Phase 2 repair-direction audit\n'
 if s.count(a)!=1: raise RuntimeError('skill refs')
 s=s.replace(a,b,1).replace('### Gate A — User validates findings\n\nThis is a hard pause. Do not draft a fix plan before the user responds.','### Gate A — User approves findings for repair planning\n\nThis is a hard pause. Gate A approves whether each finding should proceed to planning. It does not approve the provisional repair direction, exact edits, paths, commands, or any mutation. Do not draft a fix plan before the user responds.',1)
 wr(x,s)
def package():
 refs=['references/remediation-rubric.md','references/test-evidence-rubric.md','references/remediation-auditor-template.md']
 x='skills/material-code-review/scripts/validate_package.py'; s=rd(x); a='    "references/materiality-rubric.md",\n'
 if s.count(a)!=1: raise RuntimeError('standalone validator')
 wr(x,s.replace(a,a+''.join(f'    "{z}",\n' for z in refs),1))
 x='scripts/validate_package.py'; s=rd(x); a='    "skills/material-code-review/schemas/verification.schema.json",\n'
 if s.count(a)!=1: raise RuntimeError('root validator')
 wr(x,s.replace(a,a+''.join(f'    "skills/material-code-review/{z}",\n' for z in refs),1))
def clean():
 for z in ['.github/workflows/agent-strengthen-repair-directions.yml','.github/agent','scripts/agent_strengthen_repair_directions.py']:
  q=R/z
  if q.is_dir():
   import shutil; shutil.rmtree(q)
  elif q.exists(): q.unlink()
 for q in [R/'.github/workflows',R/'.github']:
  if q.exists() and not any(q.iterdir()): q.rmdir()
def main():
 tests(); out=cmd([sys.executable,'-m','unittest','discover','-s','skills/material-code-review/tests','-p','test_*.py','-v'],False)
 if 'adjudication schema_version' not in out.stdout+out.stderr and 'repair_direction' not in out.stdout+out.stderr: raise RuntimeError('red failure was unrelated')
 schema(); controller(); docs(); package(); cmd(['make','validate'],True); clean(); return 0
if __name__=='__main__': raise SystemExit(main())
