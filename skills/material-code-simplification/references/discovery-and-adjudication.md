Read this procedure before resolving or freezing scope, mapping behavior, generating candidates, validating or adjudicating them. Apply all common invariants, gates, stop and failure rules in `SKILL.md`.

Paths such as `references/...` and `examples/...` are relative to `SKILL_DIR`; shared schemas and remediation references use the entrypoint-resolved `SCHEMA_DIR` and `CORE_DIR`.

### Phase 0 — Resolve, bound, and freeze the source

#### 0.1 Read repository control and intent sources

Before interpreting architecture, read applicable `AGENTS.md`, `CLAUDE.md`, contribution guidance, test commands, architectural decision records, API/schema contracts, migration rules, generation instructions, and directory-local guidance.

Gather the user/task intent and distinguish:

- explicit requirements;
- behavior inferred from tests and callers;
- conventions inferred from repeated repository patterns;
- unknown or contradictory behavior;
- settled tradeoffs that should not be reopened without evidence.

Use `references/context-checklist.md`.

#### 0.2 Choose a bounded codebase scope

For a selected codebase area:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" init \
  --repo-root . \
  --scope codebase \
  --path src \
  --path tests \
  --exclude-path src/generated \
  --max-selected-files 2000 \
  --max-selected-bytes 268435456
```

For all currently selected repository files:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" init \
  --repo-root . \
  --scope codebase
```

For current changes instead:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" init --repo-root . --scope auto
```

Preserve the printed run ID in working memory and, where supported:

```bash
export MATERIAL_REVIEW_RUN_ID="<run-id>"
```

The codebase adapter hashes every selected current file and snapshots content within the configured per-file/total snapshot limits. It fails closed above the configured file/byte budgets. Those budgets protect enumeration and storage; they do not imply that every selected file fits model context. Scope coverage remains a reviewer responsibility, and any unread selected file must be reported as a limitation rather than silently sampled.

#### 0.3 Create the context and behavior record

Use `references/context-checklist.md` to create a read-only context note outside the worktree or under the run artifact directory. Preserve the exact scope, paths, exclusions, snapshot limitations, `scope_hash`, intent and repository rules, behavior and architecture boundaries, available test evidence, known unknowns, and external-review decision. Treat possible AI-agent provenance only as a non-evidential routing note.

Run before every dispatch or synthesis step:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" check-scope --repo-root .
```

A mismatch invalidates downstream review artifacts. Reinitialize rather than adjusting conclusions from memory.

### Phase 1 — Map behavior and architecture

This phase is read-only and produces an architecture/behavior map, not findings.

Use `references/context-checklist.md` to map only enough of the selected scope and direct dependencies to establish observable contracts and flows; ownership of policy, state, errors, retries, and side effects; dependency and intentional-isolation boundaries; dynamic/generated entry points; test seams; and unknown or historically justified behavior.

Use bounded architecture exploration. For each evidenced hotspot, compare at most:

1. leave the current shape in place;
2. the smallest local simplification;
3. a boundary-level restructure only when local work cannot remove the root cause.

Do not generate repository-wide “clean architecture” alternatives. The purpose is to establish constraints and possible reduction shapes, not to reward novelty.

Store the map with evidence paths and explicit uncertainty. It becomes shared read-only context for candidate reviewers, validators, and planners.

### Phase 2 — Generate simplification candidates

Candidate generation is limited to two read-only waves. When subagents are unavailable, run the same lenses sequentially and record `degraded_self_audit` coverage.

Pack applicable lenses into at most three reviewer assignments per wave, with a maximum of three concurrent read-only reviewers. Use one assignment per wave for a cohesive small scope; use two or three only for genuinely distinct domains or risk boundaries. Never spawn one reviewer per smell or per repeated occurrence. This bounds orchestration without imposing a semantic cap on supported candidates.

#### Wave A — Structural and architectural candidates

Use only the applicable bounded structural lens from `references/architecture-reviewer-template.md`, with `references/ai-agent-failure-catalog.md` as a disprovable search aid rather than a finding checklist.

#### Wave B — Code and test candidates

Use only the applicable bounded code/test lens from `references/code-reviewer-template.md`, with `references/ai-agent-failure-catalog.md` under the same non-presumptive constraint.

#### Candidate contract

Return JSON conforming exactly to the shared `candidate-set.schema.json` in `SCHEMA_DIR`. Do not add fields; the shared controller fails closed on extras.
Use `examples/field-mapping.md` as a shape example for both candidate and plan field mapping; replace every illustrative value with active-run evidence.

For this skill, populate the shared fields as follows:

- `nature`: normally `improvement`; use `risk` only when complexity itself creates a demonstrated operational/correctness risk.
- `category`: `simplification`, `dry`, or `architecture` unless another existing category more accurately describes the present cost.
- `scope_relation`: normally `primary` when the cited file is in the selected codebase boundary.
- `related_changed_files`: despite the inherited name, list selected files that establish the cross-file simplification relation.
- `direct_dependency`: in codebase mode, set `true` when the candidate is directly inside the selected simplification boundary. This is required for an honestly `pre_existing` retained candidate under the shared change-oriented controller. Do not use it to smuggle unrelated repository findings into scope.
- `observable_consequence`: the **current complexity cost**, not a hypothetical future benefit.
- `trigger_conditions`: the concrete maintenance, debugging, operation, or change scenario in which the cost materializes.
- `counterevidence_checked`: callers, tests, contracts, framework behavior, intentional divergence, dynamic reachability, history, and existing abstractions checked to disprove the candidate.
- `why_not_preference`: why the concern is not style or metric optimization, what behavior must remain, and why the proposed shape is net simpler.
- `proposed_resolution`: a bounded before-to-after structural description; do not provide unreviewed implementation detail.
- `estimated_fix_risk`: include deletion, migration, data, public contract, concurrency, authorization, and dependency risk.
- `assumptions`: every unresolved behavior or reachability assumption.

A smell name, high complexity score, long file, repeated syntax, or AI-like wording is insufficient. Emit one candidate per supported root cause and transformation boundary, not one per repeated occurrence; cite a canonical location and list related selected files. An empty candidate set is valid.

Ingest all reviewer outputs together:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" ingest-candidates \
  --repo-root . \
  --input /tmp/architecture-candidates.json \
  --input /tmp/code-candidates.json
```

Do not seed reviewers with one another's outputs. Agreement from the same model/process is not independent corroboration.

### Phase 3 — Validate, adjudicate, and stop candidate expansion

#### 3.1 Independent validation

Validate one semantic candidate group at a time with `references/validator-template.md`.

The template owns the evidence, reachability, current-cost, counterevidence, behavior-preservation, net-reduction, smaller-alternative, risk, and rewrite checks. The validator may confirm, reject, or remain uncertain, but may not invent a new candidate. When no independent process/model exists, label the result honestly as controller-direct or degraded self-audit.

#### 3.2 Provisional grouping and disposition

Use `references/adjudicator-template.md`, the shared adjudication schema, and `references/simplification-rubric.md`.

Create a complete read-only provisional partition: dispose every candidate exactly once; merge only semantic duplicates with one root cause and transformation boundary; preserve sources and real independence groups; attach validation; and apply the complete net-simplification test. Reject unsupported or preference-only work, invent no issue or candidate ID, and give every group a provisional `keep` or `discard` without assigning `F###` IDs.

#### 3.3 Repair-direction audit

Every provisionally kept simplification group receives the inherited audit from `"$CORE_DIR/references/remediation-auditor-template.md"`. The audit must rederive the smallest behavior-preserving reduction from the evidence; preserve public contracts, states, exceptions, compatibility, authorization, generated ownership, and rewrite limits; compare leave-as-is, local reduction, and any wider alternative; and name causal characterization/regression evidence.

Attach the normalized shared `repair_direction` and `repair_audit`. The audit record must bind the exact scope hash, ordered candidate IDs, and canonical direction hash and report its actual auditor, independence group, mode, trigger, rationale, evidence, and counterevidence. Use controller-direct only for a mechanically entailed low-risk local correction; otherwise report unavailable independence as degraded. Discarded groups keep both fields null.

#### 3.4 Final adjudication

Compile the same complete provisional candidate-ID partition after every retained direction is audited. Any changed group, disposition, or direction makes the audit stale and must be repeated. End candidate expansion after the ledger; do not add a new simplification during audit or adjudication.

Use the shared controller verdicts as an action posture:

- `READY` — no material simplification survived.
- `READY WITH OPTIONAL FOLLOW-UPS` — only bounded optional reductions remain.
- `SHOULD FIX BEFORE MERGE` — meaningful current complexity has a favorable, actionable reduction path. In codebase mode, read this as “recommended before further expansion,” not necessarily as a literal pending merge.
- `NOT READY` — use only when complexity contributes to a blocker-level correctness, safety, data, security, or operability risk.

Compile the complete audited kept/discarded ledger:

```bash
python3 "$SKILL_DIR/scripts/simplifyctl.py" compile-ledger \
  --repo-root . \
  --input /tmp/simplification-adjudication.json
```
