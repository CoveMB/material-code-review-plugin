---
name: material-review-evaluation
description: Use when a maintainer wants to compare two exact material-code-review Git revisions against the frozen Discogs custom-playlists change from a fresh Codex task.
argument-hint: "base:<skill-ref> candidate:<skill-ref>"
---

# Material review evaluation

Run one maintainer-only, prompt-driven comparison. Treat active repositories as immutable trusted inputs, keep variant identities private until judgment is written, and never authorize repair or publication.

Invoke exactly:

```text
$material-review-evaluation base:<skill-ref> candidate:<skill-ref>
```

## Hard stops

- Require exactly one `base:` and one `candidate:` selector and no other arguments.
- `base:` and `candidate:` always name material-review repository commits; the case JSON separately owns the Discogs target commits. If the invocation omits the two skill selectors, stop and ask for them. Never reuse either case commit as a missing skill selector.
- Reject a missing, empty, ambiguous, non-commit, or identical resolved pair before reviewer dispatch.
- Stop on a dirty active material-review repository; never stash, clean, reset, check out, stage, or commit it.
- Use one reviewer trial per version. Do not automatically retry reviewers or resume an interrupted run.
- Never approve Gate B. Never start repair, edit product code, publish, push, open a pull request, call live Discogs/Spotify APIs, or send source to an external review service.
- Keep `private-variant-map.json`, supplied refs, exact skill commits, ordering, commit subjects, and prior output out of every reviewer and judge bundle.

## 1. Resolve, attest, and load contracts before creating workers

1. Locate the repository root and confirm the invocation is running in a source checkout, not a packaged distribution.
2. Immediately capture the active material-review repository's `HEAD` and porcelain status. Require an empty status.
3. From that attested repository root, resolve exactly this repository-root-relative evaluator asset allowlist:

   <!-- evaluator-asset-allowlist:start -->
   - `evaluations/material-code-review/cases/discogs-custom-playlists.json`
   - `evaluations/material-code-review/prompts/reviewer.md`
   - `evaluations/material-code-review/prompts/judge.md`
   - `evaluations/material-code-review/rubric.md`
   <!-- evaluator-asset-allowlist:end -->

   Before reading an asset, canonicalize its path, require it to remain beneath the attested repository root, and require a regular file. Stop on a missing, non-regular, or out-of-root asset. Do not search alternate directories, fall back to skill-relative resolution, or use parent traversal from the skill directory. Read all four contracts completely. The case JSON is the sole target-identity owner; do not replace its commits with the branch label or another revision.
4. Resolve each selector once with Git's commit-peeling form:

   ```text
   git rev-parse --verify --end-of-options <selector>^{commit}
   ```

   Pass each selector as a separate argument, not interpolated shell syntax. Require exactly one lowercase 40-character SHA from each command. Record those SHAs and use them for every later operation; never resolve the supplied refs again.
5. Reject identical SHAs immediately. Do not create a run directory or target clone for an invalid pair.
6. Read the case JSON and require exactly:
   - base `361e1740fa164fafc590e7dc8903a87b069592cb`;
   - review commit `3050f047c4cb1a7b32237844ec7cf68a5675c957`;
   - immediate-parent enforcement, range review, and immutable posture.
7. Select the Discogs clone source once. Prefer an explicitly supplied or already known trusted local clone source only when its normalized `origin` matches the case repository, it contains both exact case commits, and its porcelain status is empty. Capture that checkout's path, `HEAD`, status, and remotes. Do not search unrelated directories. If no eligible local checkout is known, select the case's public HTTPS repository and record that no active Discogs checkout was used.

Do not continue if any identity or attestation is unavailable. Never substitute a moving ref.

## 2. Create private run state and isolated inputs

1. Create `.evaluation-runs/<UTC timestamp>-<short random id>/` under the repository root. Verify `.evaluation-runs/` is ignored. Write initial identities and status to `run.json` before reviewer dispatch.
2. Randomize the base/candidate assignment to Variant A/B once. Store the mapping only in the root task's private context and `private-variant-map.json`. Never rename or recompute it.
3. Create a run-owned temporary root with `mktemp -d` outside every active worktree. Record its exact path in private run state. Do not promise cleanup after interruption.
4. For each anonymous variant, archive `skills/material-code-review/` from its recorded skill SHA, extract it into a separately named anonymous directory, and verify its `SKILL.md` and referenced shipped files exist. Use `git archive`; do not check out or mutate the active repository.
5. Create three distinct clones under the temporary root from the single selected Discogs clone source: one per reviewer and one for the judge. The source is either the attested trusted local clone source or `https://github.com/CoveMB/discogs-collection.git`; never mix sources within a run. Detach each at `3050f047c4cb1a7b32237844ec7cf68a5675c957`, verify `HEAD^` is exactly `361e1740fa164fafc590e7dc8903a87b069592cb`, and record clean status. Stop if either commit is missing or the relationship differs.
6. Give each reviewer a distinct controller artifact root outside its target clone and a distinct output directory under the ignored run directory.

These inputs provide logical separation, not hostile-code containment. Stop if the repositories or commits are not trusted.

### Context-free worker dispatch contract

Before creating any reviewer or judge, verify that the host can dispatch a self-contained request with zero inherited task history. On Codex, every worker dispatch must set `fork_turns` to `none`; another host may use only a verifiably equivalent zero-history primitive. A bounded but non-empty history is not anonymous. Immediately before each reviewer or judge dispatch, recapture the active material-review repository's `HEAD` and porcelain status and require an exact match to the initial clean attestation. Persist a private structured dispatch receipt for each worker role recording the zero-history mode and the exact allowlist supplied. Root-side verification is authoritative; never require a worker to inspect the private receipt or place private orchestration data in a worker-visible request. Prohibit recursive worker fan-out.

<!-- evaluator-dispatch-contract:start
reviewers=2
reviewer_history=none
initial_judge_history=none
replacement_judge_history=none
codex_fork_turns=none
worker_message=self-contained-allowlist
private_dispatch_receipt=true
recursive_fanout=false
isolation_unavailable_dispatch=false
isolation_unverifiable_dispatch=false
bounded_nonempty_dispatch=false
isolation_failure_outcome=INSUFFICIENT_EVIDENCE
isolation_failure_winner=none
isolation_failure_gate_progression=false
isolation_failure_repair_publication_egress=false
evaluator-dispatch-contract:end -->

If zero inherited history is unavailable or cannot be verified, or if the host offers only bounded non-empty history, do not dispatch the affected worker. Preserve private run evidence, record the specific context-isolation failure, write a sanitized terminal `judgment.md` with public Outcome `INSUFFICIENT_EVIDENCE` and no winner, and stop. Do not progress Gate A or Gate B, repair, publish, or send source elsewhere. This isolation failure is distinct from invalid-reviewer and missing-evidence handling and never authorizes a retry.

## 3. Dispatch exactly two anonymous reviewers

Dispatch exactly two fresh reviewers in parallel through the context-free worker dispatch contract above. Prohibit recursive fan-out. If the supplied material-review skill would delegate but host depth is unavailable, the reviewer must run the canonical lenses sequentially.

Give each reviewer only:

- its anonymous Variant A or Variant B label;
- its exact materialized skill path;
- its own detached Discogs clone;
- its own controller artifact and evaluation output roots; and
- `evaluations/material-code-review/prompts/reviewer.md`.

The initial request may say that the maintainer intends to approve all retained findings for planning. State that this is intent only, not exact-ID Gate-A approval. Do not provide the other variant, supplied ref, skill commit, commit subject, private map, judge prompt, prior output, or expected findings.

Wait for both reviewers. A reviewer may write only its run-owned controller/evaluation artifacts. Stop and mark its result invalid if it attempts repair, product mutation, publication, or prohibited source egress.

Validate both returns before Gate A. If a reviewer is invalid or lacks its required findings evidence, preserve every available native artifact, record the exact failure, and do not retry, reconstruct content, or reinterpret missing evidence as an empty ledger. Skip Gate A and planning for both variants and follow the missing-evidence branch in section 5.

## 4. Combined Gate-A checkpoint

After both reviewers return valid findings ledgers, always pause both valid variants at Gate A:

1. Display both variants together, listing every exact retained ID with its one-line title/effect. Identify each zero-finding variant as awaiting explicit empty-ledger acceptance; do not call it accepted yet.
2. Ask once for approve, reject, or defer dispositions on every displayed ID and for explicit acceptance of each displayed empty ledger. Do not fabricate a disposition or acceptance.
3. Treat “approved all” as authority only for the exact IDs in the immediately preceding combined checkpoint. It does not accept an empty ledger unless the same response explicitly accepts that variant's no-material-findings decision.
4. Send each reviewer its own complete recorded dispositions and exact user statement. For an accepted empty ledger, send explicit `--accept-empty` authority and its exact user statement. Continue only after the native controller records the gate.

Classify each recorded variant using exactly one of these states:

- `ALL_APPROVED_PLAN` — a non-empty ledger whose every retained ID was approved; continue to its controller-validated plan and stop at unapproved Gate B.
- `MIXED_DISPOSITIONS_NONCOMPARABLE` — a non-empty ledger with at least one approved ID and at least one rejected or deferred ID; preserve the native Gate-A receipt and `PLANNING` state, but do not request or fabricate a plan.
- `NO_APPROVED_FINDINGS` — a non-empty ledger whose retained IDs were all rejected or deferred; preserve the native `COMPLETE` result and its no-approved-findings artifact without calling it empty or Gate B.
- `ACCEPTED_EMPTY_LEDGER` — an actually empty ledger accepted with explicit `--accept-empty` authority; preserve its existing controlled no-plan result.
- `INVALID_OR_MISSING_EVIDENCE` — invalid reviewer output or required evidence that was never produced; preserve the existing missing-evidence representation without treating it as any Gate-A disposition state.

<!-- evaluator-gate-disposition-contract:start
all_approved=ALL_APPROVED_PLAN
mixed_reject_or_defer=MIXED_DISPOSITIONS_NONCOMPARABLE
zero_approved=NO_APPROVED_FINDINGS
accepted_empty=ACCEPTED_EMPTY_LEDGER
invalid_or_missing=INVALID_OR_MISSING_EVIDENCE
reject_or_defer_policy=DISPOSITION_NONCOMPARABLE
reject_or_defer_outcome=INSUFFICIENT_EVIDENCE
reject_or_defer_winner=none
reject_or_defer_plan=false
reject_or_defer_gate_b=false
native_controller_change=false
disposition_evidence=ledger-hash,gate-receipt-hash,anonymous-dispositions,native-state
evaluator-gate-disposition-contract:end -->

After both native receipts are recorded, any `MIXED_DISPOSITIONS_NONCOMPARABLE` or `NO_APPROVED_FINDINGS` state in either non-empty variant makes the entire comparison `DISPOSITION_NONCOMPARABLE`. Stop plan production for both variants, preserve evidence already reached, create the faithful public representations in section 5, and require public Outcome `INSUFFICIENT_EVIDENCE` with no winner. Do not change native controller behavior, fabricate a plan, approve Gate B, or reinterpret an accepted empty or invalid/missing result.

Gate-A continuation is part of the current run, not permission to resume an interrupted run. Reaching Gate B supplies plan evidence; it does not authorize Gate-B approval or repair.

## 5. Capture anonymous evidence

Create exactly these public comparison files:

```text
variant-a/findings.md
variant-a/plan.md
variant-a/limitations.md
variant-b/findings.md
variant-b/plan.md
variant-b/limitations.md
```

For each variant:

- `findings.md`: include the complete retained ledger and discarded candidates when available; cite exact native artifact paths and hashes.
- `plan.md`: for `ALL_APPROVED_PLAN`, include the complete controller-validated Gate-B plan and exact native plan hash. For `MIXED_DISPOSITIONS_NONCOMPARABLE`, include the ledger hash, Gate-A receipt hash, exact anonymous approve/reject/defer sets, native state, and `Disposition state: MIXED_DISPOSITIONS_NONCOMPARABLE`; state that no plan was requested because the comparison is `DISPOSITION_NONCOMPARABLE`. For `NO_APPROVED_FINDINGS`, include the same hash-bound dispositions, native `COMPLETE` state, no-approved-findings artifact, and `Disposition state: NO_APPROVED_FINDINGS`; do not label it empty or Gate B. For `ACCEPTED_EMPTY_LEDGER`, write exactly `No repair plan: no retained findings.` and identify the state separately.
- `limitations.md`: record degraded coverage or missing evidence and an explicit no-mutation/no-repair attestation.

Copy evidence faithfully. Do not alter native controller artifacts, reconstruct missing evidence, or claim schema equivalence across skill versions. Record exact target commits, exact skill commits, timestamps, native artifact paths/hashes, limitations, and current run status in private `run.json`. Never include `run.json` or `private-variant-map.json` in judge inputs.

For an invalid reviewer or missing required artifact, still create all six anonymous files. Copy available native evidence faithfully. Where evidence is unavailable, write `Missing reviewer evidence: <specific reason>` in the affected findings or plan file, and explain the failure and any early termination in `limitations.md`; do not synthesize a ledger or plan. The other variant's files must likewise distinguish available evidence from work not reached because the comparison terminated early. Give these missing-evidence representations to the judge, which must terminate with `INSUFFICIENT_EVIDENCE` rather than compare incomplete variants or force a winner.

When disposition policy terminates the comparison, create all six files and label the affected evidence `DISPOSITION_NONCOMPARABLE`, not missing. The other variant must preserve evidence already reached and explicitly identify later work as not reached because the peer variant's hash-bound rejection or deferral ended comparison planning.

## 6. Dispatch the blinded judge and reveal afterward

After both variants are captured, dispatch one fresh read-only judge through the same context-free worker dispatch contract. Give it only:

- the six anonymous findings/plan/limitations files;
- `evaluations/material-code-review/prompts/judge.md`;
- `evaluations/material-code-review/rubric.md`; and
- the third detached, read-only Discogs clone at the frozen range.

Require exact anonymous artifact and source citations and exactly one outcome:

- `VARIANT_A_STRONGER`
- `VARIANT_B_STRONGER`
- `MATERIAL_TIE`
- `INSUFFICIENT_EVIDENCE`

The judge must not receive or infer refs, skill commits, branch names, commit subjects, version order, private mapping, prior reports, or expected findings.

<!-- evaluator-judge-protocol:start
public_outcomes=VARIANT_A_STRONGER,VARIANT_B_STRONGER,MATERIAL_TIE,INSUFFICIENT_EVIDENCE
valid_outcome_count=1
required_sections=Outcome,Finding comparison,Repair-plan comparison,Limitations and uncertainty,Citations
citations=anonymous-artifacts,frozen-source
identity_data=forbidden
judgment_before_mapping=true
raw_attempts=private-local
max_attempts=2
attempt_2_trigger=first-identity-leak-only
other_invalid_first_replacement=false
second_leak_replacement=false
terminal_outcome=INSUFFICIENT_EVIDENCE
terminal_winner=none
private_terminal_reason=judge-invalid
interrupted_run=preserve-and-new-invocation
repair_publication_egress_resume=false
evaluator-judge-protocol:end -->

The root accepts a response only after validating the complete judge protocol. Apply this bounded procedure:

1. Preserve the raw first return as private local `judge-attempt-1.md`; when no return exists, write an explicit absent-return marker. Before accepting it, validate exactly one public Outcome, every required section exactly once and in order, resolvable citations to the supplied anonymous artifacts and frozen source, the zero-history dispatch receipt, and absence of identity-bearing data.
2. If the first return is valid, write and close the complete validated response as `judgment.md` before reading or revealing `private-variant-map.json`.
3. If and only if the first return contains identity leakage, preserve the leak reason in private `judge-validation.json`, discard it as a public judgment, and create exactly one replacement through the context-free dispatch contract with a corrected anonymous allowlist. Give the replacement no prior response or validation history and preserve its return as `judge-attempt-2.md`.
4. Do not replace a malformed, empty, absent, multi-outcome, unsupported-outcome, missing-section, missing-citation, or otherwise invalid first return. Do not create a third attempt after any invalid or identity-leaking second return.
5. For every non-replaceable invalid return, preserve the raw attempt and exact validation failures in private `judge-validation.json`, set the private terminal reason to `judge-invalid`, and write a sanitized `judgment.md` with all ordered sections, public Outcome `INSUFFICIENT_EVIDENCE`, no winner, and citations to the local validation evidence. Write and close that terminal judgment before reading or revealing the private mapping.
6. Keep raw attempts and validation reasons out of every judge input and automatic publication. The terminal path never authorizes repair, publication, source egress, automatic resume, or another retry.

After a validated or sanitized terminal `judgment.md` is durable, compare the active-repository attestations with their pre-run snapshots, reveal the private mapping, update private `run.json`, and report the judgment, mapping, evidence directory, limitations, and unchanged-repository result to the maintainer. Do not publish automatically.

## Interrupted runs

Preserve the ignored run evidence and recorded temporary path, mark the run interrupted when possible, and stop. Interruption is not a judge-return attempt and never enters the replacement branch. A later attempt requires a new explicit invocation, new run ID, new random mapping, and fresh workers. Do not resume, retry, or automatically delete interrupted external work.

## Observed baseline red flags

| Red flag | Required correction |
|---|---|
| “Record Gate A as satisfied by the maintainer's explicit preapproval.” | Gate A requires the exact retained IDs displayed in the combined checkpoint. |
| “Gate B is not applicable because repair is unauthorized.” | Produce and validate the repair plan, stop at Gate B, and never approve it. |
| Unblind and then compare the variants in the root task. | Keep identities private and use a fresh anonymous source-checking judge. |
| Return an ad hoc comparison without a controlled outcome. | Require one of the four controlled outcomes above. |
| Revalidate and resume after interruption. | Preserve evidence and require a new explicit invocation. |
| Reuse the frozen Discogs commits when skill selectors are missing. | Stop and request two material-review refs; target commits and skill commits are different identities. |
