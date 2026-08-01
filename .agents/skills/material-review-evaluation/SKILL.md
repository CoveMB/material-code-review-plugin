---
name: material-review-evaluation
description: Use when a maintainer wants to compare two exact material-code-review Git revisions against a frozen, allowlisted evaluation case from a fresh Codex task.
argument-hint: "[case:<case-id>] base:<skill-ref> candidate:<skill-ref>"
---

# Material review evaluation

Run one maintainer-only, prompt-driven comparison. Treat active repositories as immutable trusted inputs, keep variant identities private until judgment is written, and never authorize repair or publication.

The existing invocation remains the default Discogs case:

```text
$material-review-evaluation base:<skill-ref> candidate:<skill-ref>
```

Select the frozen missed-contracts case only with:

```text
$material-review-evaluation case:missed-contracts base:<skill-ref> candidate:<skill-ref>
```

## Hard stops

- Require exactly one `base:` and one `candidate:` selector plus either no case selector or exactly one controlled `case:` selector. No selector means `discogs-custom-playlists`; the only explicit case selector is `case:missed-contracts`. Reject unknown, duplicated, empty, or traversal-shaped case values and every other argument.
- `base:` and `candidate:` always name material-review repository commits; the selected case JSON separately owns target identity. If the invocation omits the two skill selectors, stop and ask for them. Never reuse a target-case commit as a missing skill selector.
- Reject a missing, empty, ambiguous, non-commit, or identical resolved pair before reviewer dispatch.
- Stop on a dirty active material-review repository; never stash, clean, reset, check out, stage, or commit it.
- Use one primary-reviewer trial per version. The missed-contracts case also uses one coverage challenger per version; it is not a reviewer retry and cannot add findings. Do not automatically retry workers or resume an interrupted run.
- Never approve Gate B. Never start repair, edit product code, publish, push, open a pull request, call live Discogs/Spotify APIs, or send source to an external review service.
- Keep `private-variant-map.json`, supplied refs, exact skill commits, ordering, commit subjects, and prior output out of every reviewer and judge bundle.

## 1. Resolve, attest, and load contracts before creating workers

1. Locate the repository root and confirm the invocation is running in a source checkout, not a packaged distribution.
2. Immediately capture the active material-review repository's `HEAD` and porcelain status. Require an empty status.
3. From that attested repository root, resolve exactly this repository-root-relative evaluator asset allowlist:

   <!-- evaluator-asset-allowlist:start -->
   - `evaluations/material-code-review/cases/discogs-custom-playlists.json`
   - `evaluations/material-code-review/cases/missed-contracts.json`
   - `evaluations/material-code-review/prompts/reviewer.md`
   - `evaluations/material-code-review/prompts/challenger.md`
   - `evaluations/material-code-review/prompts/judge.md`
   - `evaluations/material-code-review/rubric.md`
   - `evaluations/material-code-review/fixtures/missed-contracts/base/AGENTS.md`
   - `evaluations/material-code-review/fixtures/missed-contracts/base/scripts/validate_package.py`
   - `evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/scripts/validate_package.py`
   - `evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/references/workflow.md`
   - `evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/schemas/candidate-set.json`
   - `evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/schemas/coverage-plan.json`
   - `evaluations/material-code-review/fixtures/missed-contracts/base/skills/demo/package-layouts.json`
   - `evaluations/material-code-review/fixtures/missed-contracts/review/scripts/validate_package.py`
   - `evaluations/material-code-review/fixtures/missed-contracts/review/skills/demo/scripts/validate_package.py`
   - `evaluations/material-code-review/fixtures/missed-contracts/review/skills/demo/references/workflow.md`
   - `evaluations/material-code-review/fixtures/missed-contracts/review/skills/demo/schemas/candidate-set.json`
   - `evaluations/material-code-review/fixtures/missed-contracts/review/skills/demo/schemas/coverage-plan.json`
   <!-- evaluator-asset-allowlist:end -->

   Before reading an asset, canonicalize its path, require it to remain beneath the attested repository root, reject symlinks, and require a regular file. Stop on a missing, non-regular, out-of-root, or hash-drifted asset. Do not search alternate directories, fall back to skill-relative resolution, or use parent traversal from the skill directory. Read the selected case and its prompt contracts completely. Case resolution is fixed to this allowlist; never construct a path from user input. The case JSON is the sole target-identity owner.
4. Resolve each selector once with Git's commit-peeling form:

   ```text
   git rev-parse --verify --end-of-options <selector>^{commit}
   ```

   Pass each selector as a separate argument, not interpolated shell syntax. Require exactly one lowercase 40-character SHA from each command. Record those SHAs and use them for every later operation; never resolve the supplied refs again.
5. Reject identical SHAs immediately. Do not create a run directory or target clone for an invalid pair.
6. Resolve the selected case from a fixed mapping: no selector maps to `discogs-custom-playlists.json`; `case:missed-contracts` maps to `missed-contracts.json`. Require its controlled `target_type`, immediate-parent enforcement, range review, immutable posture, and every case-specific identity or fixture hash. For Discogs, require base `361e1740fa164fafc590e7dc8903a87b069592cb` and review commit `3050f047c4cb1a7b32237844ec7cf68a5675c957`. For missed-contracts, require all declared fixture files, exact base/review tree hashes, exact deterministic commits, and exactly the five declared changed paths. Keep `required_root_ids` and `root_contracts` private; candidate findings are forbidden from the challenger bundle.
7. For Discogs, select the clone source once. Prefer an explicitly supplied or already known trusted local clone source only when its normalized `origin` matches the case repository, it contains both exact case commits, and its porcelain status is empty. Capture that checkout's path, `HEAD`, status, and remotes. Do not search unrelated directories. If no eligible local checkout is known, select the case's public HTTPS repository and record that no active Discogs checkout was used. For missed-contracts, do not use an active target checkout: copy the allowlisted base tree into a run-owned temporary directory, initialize Git, commit it with the exact case identity/message/timestamp and `commit.gpgsign=false`, overlay only the allowlisted review files, and commit again with signing disabled. Verify both tree hashes, both exact commits, immediate parentage, changed paths, and clean status before any worker dispatch.

For `case:missed-contracts`, before any reviewer, challenger, or judge dispatch, scan the complete worker-visible guidance allowlist below against the private `required_root_ids`, exact `root_contracts` definitions, and the retired one-to-one fixture guidance. Stop before dispatch if any private root or known semantic seed appears. This contamination check covers guidance and prompt inputs, not the frozen source evidence whose defects workers must inspect. Keep the private oracle unavailable to every worker and apply it only after a durable blinded judgment and identity reveal.

<!-- evaluator-worker-contamination-contract:start
case=missed-contracts
check_timing=before-any-worker-dispatch
worker_visible_guidance=evaluations/material-code-review/fixtures/missed-contracts/base/AGENTS.md,evaluations/material-code-review/prompts/reviewer.md,evaluations/material-code-review/prompts/challenger.md,evaluations/material-code-review/prompts/judge.md,evaluations/material-code-review/rubric.md
deny=root-ids,root-contract-definitions,retired-one-to-one-guidance
frozen_source_evidence_scan=false
private_oracle_timing=after-durable-judgment-and-identity-reveal
contamination_dispatch=false
evaluator-worker-contamination-contract:end -->

Do not continue if any identity or attestation is unavailable. Never substitute a moving ref.

## 2. Create private run state and isolated inputs

1. Create `.evaluation-runs/<UTC timestamp>-<short random id>/` under the repository root. Verify `.evaluation-runs/` is ignored. Write initial identities and status to `run.json` before reviewer dispatch.
2. Randomize the base/candidate assignment to Variant A/B once. Store the mapping only in the root task's private context and `private-variant-map.json`. Never rename or recompute it.
3. Create a run-owned temporary root with `mktemp -d` outside every active worktree. Record its exact path in private run state. Do not promise cleanup after interruption.
4. For each anonymous variant, archive `skills/material-code-review/` from its recorded skill SHA, extract it into a separately named anonymous directory, and verify its `SKILL.md` and referenced shipped files exist. Use `git archive`; do not check out or mutate the active repository.
5. Create distinct target clones under the temporary root from the selected case source: one per primary reviewer, one per missed-contracts challenger when selected, and one for the judge. For Discogs, use the single attested local or public source and detach at `3050f047c4cb1a7b32237844ec7cf68a5675c957`; verify `HEAD^` is `361e1740fa164fafc590e7dc8903a87b069592cb`. For missed-contracts, clone only the run-owned deterministic fixture repository and detach at the exact case review commit; verify its parent and both tree hashes. Never mix sources or share a mutable clone between workers. Record clean status for every clone.
6. Give each reviewer a distinct controller artifact root outside its target clone and a distinct output directory under the ignored run directory.

These inputs provide logical separation, not hostile-code containment. Stop if the repositories or commits are not trusted.

### Context-free worker dispatch contract

Before creating any reviewer, challenger, or judge, verify that the host can dispatch a self-contained request with zero inherited task history. On Codex, every worker dispatch must set `fork_turns` to `none`; another host may use only a verifiably equivalent zero-history primitive. A bounded but non-empty history is not anonymous. Immediately before each reviewer, challenger, or judge dispatch, recapture the active material-review repository's `HEAD` and porcelain status and require an exact match to the initial clean attestation. Persist a private structured dispatch receipt for each worker role recording the zero-history mode and the exact allowlist supplied. Root-side verification is authoritative; never require a worker to inspect the private receipt or place private orchestration data in a worker-visible request. Prohibit recursive worker fan-out.

<!-- evaluator-dispatch-contract:start
reviewers=2
challengers=case:missed-contracts-only
reviewer_history=none
challenger_history=none
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

## 3. Dispatch exactly two anonymous primary reviewers

Dispatch exactly two fresh reviewers in parallel through the context-free worker dispatch contract above. Prohibit recursive fan-out. If the supplied material-review skill would delegate but host depth is unavailable, the reviewer must run the canonical lenses sequentially.

Give each primary reviewer only:

- its anonymous Variant A or Variant B label;
- its exact materialized skill path;
- its own detached selected-case clone and the case's public target identity, never private expected roots;
- its own controller artifact and evaluation output roots; and
- `evaluations/material-code-review/prompts/reviewer.md`.

The initial request may say that the maintainer intends to approve all retained findings for planning. State that this is intent only, not exact-ID Gate-A approval. Do not provide the other variant, supplied ref, skill commit, commit subject, private map, judge prompt, prior output, or expected roots.

### Missed-contracts challenger checkpoint

For `case:missed-contracts` only, require each primary reviewer to pause after the native controller has frozen context and recorded coverage-plan/v2 plus the complete assignment set, but before candidate ingestion and Gate A. Capture a read-only declarative summary of frozen context identity, change units, risk decisions, obligations, assignments, and limitations. Do not include candidate findings, candidate sets, assignment `check_results`, adjudication, the ledger, expected roots, variant identity, refs, private mapping, prior output, or the other variant.

Immediately dispatch one zero-history challenger per anonymous variant with `fork_turns=none`, its distinct read-only fixture clone, that variant's declarative coverage summary, and `evaluations/material-code-review/prompts/challenger.md`. The challenger is case-only: it returns `NO_COVERAGE_GAP` or a bounded `COVERAGE_GAP` over missing or duplicated change units, unsupported risk decisions, missing or mismatched obligations, compound or mismatched assignments, or limitations that defeat the declaration. `NO_COVERAGE_GAP` certifies only that bounded declarative claim; it never establishes that any check result was performed, fresh, complete, unblocked, resolved, or safe. The challenger cannot add findings, repair artifacts, act as an independent finding validator, progress a gate, or mutate source. Persist its response as `variant-a/challenge.md` or `variant-b/challenge.md`, then allow the corresponding primary reviewer to continue without revealing the challenge response as candidate-generation guidance. Native controller validation and evaluator-root acceptance of assignments, obligations, `check_results`, and Gate-A evidence remain mandatory and fail closed independently of the challenger result.

<!-- evaluator-challenger-boundary-contract:start
case=missed-contracts
challenger_inputs=frozen-source,change-units,risk-decisions,obligations,assignments,limitations
challenger_forbidden=candidates,candidate-sets,check-results,adjudication,ledgers,plans,expected-roots,variant-identities,refs,private-mapping,other-variant,prior-output
challenger_claim=declarative-coverage-only
challenger_outcomes=NO_COVERAGE_GAP,COVERAGE_GAP
no_coverage_gap_proves=declarative-coverage-only
native_assignment_validation=required-independent
native_obligation_validation=required-independent
native_check_results_fresh=true
native_check_results_complete=true
native_check_results_unblocked=true
native_check_results_unique=true
native_check_results_resolved=true
native_gate_a_validation=required-independent
invalid_empty_or_gap=blocks-success-no-retry
challenge_response_to_reviewer=false
default_discogs_challenger=false
evaluator-challenger-boundary-contract:end -->

For the default Discogs case, do not dispatch a challenger and do not create challenge artifacts. If a missed-contracts challenger is invalid, unavailable, receives forbidden inputs, or reports a gap, preserve the response and mark that variant insufficient for a successful-strengthening claim; do not retry the challenger.

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

Create these public comparison files for every case:

```text
variant-a/findings.md
variant-a/plan.md
variant-a/limitations.md
variant-b/findings.md
variant-b/plan.md
variant-b/limitations.md
```

For missed-contracts, also require the already captured files:

```text
variant-a/challenge.md
variant-b/challenge.md
```

For each variant:

- `findings.md`: include the complete retained ledger and discarded candidates when available; cite exact native artifact paths and hashes.
- `plan.md`: for `ALL_APPROVED_PLAN`, include the complete controller-validated Gate-B plan and exact native plan hash. For `MIXED_DISPOSITIONS_NONCOMPARABLE`, include the ledger hash, Gate-A receipt hash, exact anonymous approve/reject/defer sets, native state, and `Disposition state: MIXED_DISPOSITIONS_NONCOMPARABLE`; state that no plan was requested because the comparison is `DISPOSITION_NONCOMPARABLE`. For `NO_APPROVED_FINDINGS`, include the same hash-bound dispositions, native `COMPLETE` state, no-approved-findings artifact, and `Disposition state: NO_APPROVED_FINDINGS`; do not label it empty or Gate B. For `ACCEPTED_EMPTY_LEDGER`, write exactly `No repair plan: no retained findings.` and identify the state separately.
- `limitations.md`: record degraded coverage or missing evidence and an explicit no-mutation/no-repair attestation. For missed-contracts, state whether the challenger returned `NO_COVERAGE_GAP`, `COVERAGE_GAP`, or invalid evidence without copying private expected roots.

Copy evidence faithfully. Do not alter native controller artifacts, reconstruct missing evidence, or claim schema equivalence across skill versions. Record exact target commits, exact skill commits, timestamps, native artifact paths/hashes, limitations, and current run status in private `run.json`. Never include `run.json` or `private-variant-map.json` in judge inputs.

For an invalid reviewer or missing required artifact, still create all six anonymous files. Copy available native evidence faithfully. Where evidence is unavailable, write `Missing reviewer evidence: <specific reason>` in the affected findings or plan file, and explain the failure and any early termination in `limitations.md`; do not synthesize a ledger or plan. The other variant's files must likewise distinguish available evidence from work not reached because the comparison terminated early. Give these missing-evidence representations to the judge, which must terminate with `INSUFFICIENT_EVIDENCE` rather than compare incomplete variants or force a winner.

When disposition policy terminates the comparison, create all six files and label the affected evidence `DISPOSITION_NONCOMPARABLE`, not missing. The other variant must preserve evidence already reached and explicitly identify later work as not reached because the peer variant's hash-bound rejection or deferral ended comparison planning.

## 6. Dispatch the blinded judge and reveal afterward

After both variants are captured, dispatch one fresh read-only judge through the same context-free worker dispatch contract. Give it only:

- the six anonymous findings/plan/limitations files and, for missed-contracts only, both anonymous `challenge.md` files;
- `evaluations/material-code-review/prompts/judge.md`;
- `evaluations/material-code-review/rubric.md`; and
- the judge's detached, read-only selected-case clone at the frozen range.

Require exact anonymous artifact and source citations and exactly one outcome:

- `VARIANT_A_STRONGER`
- `VARIANT_B_STRONGER`
- `MATERIAL_TIE`
- `INSUFFICIENT_EVIDENCE`

The judge must not receive or infer refs, skill commits, branch names, commit subjects, version order, private mapping, prior reports, or expected roots.

For missed-contracts, the judge may evaluate whether the anonymous ledgers support all five privately required roots only through the root's post-judgment acceptance check; do not give the private root list or root definitions to the judge. A challenger-reported gap, invalid challenger evidence, incomplete obligation evidence, missing candidate root, lost baseline material root, unsupported high-severity addition, invalid Gate-A evidence, or mutation requires `INSUFFICIENT_EVIDENCE` for a successful-strengthening claim. `NO_COVERAGE_GAP` is necessary but does not by itself prove finding correctness.

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

## 7. Apply the bounded missed-contracts acceptance rule

After judgment and identity reveal, evaluate `case:missed-contracts` against its private case contract. A successful-strengthening claim requires all of the following together:

- the candidate ledger supports every one of the five `required_root_ids` with source evidence;
- every material baseline root remains represented in the candidate ledger;
- the candidate adds no unsupported high-severity finding;
- coverage-plan/v2, assignment, obligation, check-result, and Gate-A evidence is controller-valid independently of the challenger;
- both candidate-side challenger evidence and limitations support `NO_COVERAGE_GAP` for the bounded declarative coverage claim only;
- no product or fixture mutation occurred; and
- the blinded judge found the candidate variant materially stronger.

One comparison is permitted. One repair-plus-confirmation comparison is permitted only when the first comparison identifies a concrete implementation defect and the maintainer separately authorizes implementation and a new invocation. There is no resampling. A tie, baseline-stronger judgment, insufficient or invalid evidence, missing root, lost baseline finding, unsupported high-severity addition, challenger gap, or mutation blocks a successful-strengthening claim. Deterministic tests remain release authority; this bounded live case is confirmation evidence only.

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
