# Simplification workflow and command matrix

The canonical skill defines simplification judgment. `simplifyctl.py` adds bounded current-codebase selection and delegates lifecycle enforcement to the shared `reviewctl.py`.

Both codebase and delegated change scopes use `material-review/state/v1` and candidate-set/v1 only when state carries the exact `profile=material-code-simplification`. The adapter does not grant authority to an unprofiled or contradictory v1 run; it must restart. Adapter 1.3.0 embeds shared controller and obligation helper 1.5.1 for runtime provenance, but this profile-specific v1 contract does not select change units, coverage-plan/v3, candidate-set/v4, specialist assignments, check results, or review obligations from current material-review state/v4.

| State | Command | Result |
|---|---|---|
| new | `init --scope codebase --path ...` | selected current files frozen and hashed; `CONTEXT_FROZEN` |
| new | `init --scope auto\|uncommitted\|branch ...` | delegated mutable Git-change scope |
| new | `init --scope range --base ... --head ...` | delegated immutable review-only range; refreeze before mutation |
| context | `check-scope` | selected file/ref identity remains fresh |
| context | `ingest-candidates --input ...` | strict shared candidate validation and normalization |
| candidates | provisional grouping + inherited repair audit | complete partition plus behavior-preserving, hash-bound direction for every provisionally kept group |
| audited provisional groups | `compile-ledger --input ...` | adjudication/v3 validation and stable `F###` IDs |
| adjudicated | `gate-findings ...` | Gate A dispositions persisted against ledger hash |
| findings approved | `validate-plan --input ...` | fix-plan/v2 IDs and complete direction-bound assessment validated; no write permission |
| plan validated | `gate-plan --approve|--reject` | Gate B receipt persisted against exact plan hash |
| plan approved | `begin-fix` | pre-fix checkpoint and workspace guard |
| fixing | `start-finding --finding F###` | per-item checkpoint |
| fixing | `run-test --finding F### --test ID` | exact approved non-mutating test logged |
| fixing | `finish-finding ...` | passing in-boundary delta retained |
| fixing | `rollback-finding ...` | item checkpoint restored |
| fixing | `run-global-test --test ID` | exact approved global check logged |
| fixing | `prepare-verification` | fix-only verification bundle |
| verifying | `record-verification --input ...` | pass, bounded repair, plan amendment, or block |
| repair required | `begin-repair` | only causal in-plan IDs reopen within budget |
| mutation phases | `abort-fixes --reason ...` | complete pre-fix state restored |
| any | `status` | active run state and artifact paths |

## Codebase scope semantics

- Includes selected current tracked files and selected non-ignored untracked files unless `--exclude-untracked` is explicit.
- `--path` and `--exclude-path` are repository-relative exact file/directory prefixes, not globs.
- `--max-selected-files` and `--max-selected-bytes` fail closed before artifacts are created. Raising them does not justify claiming full semantic coverage.
- No baseline tree exists; `baseline_sha` is an all-zero sentinel so baseline evidence fails closed, and candidate evidence uses `comparison`.
- Selected content, modes, paths, branch, HEAD, selectors, exclusions, and untracked policy contribute to `scope_hash`.
- Uncommitted changes outside selected prefixes do not alter the selected-content hash. Any branch or `HEAD` change still stales the scope because repository identity is frozen; the repair workspace guard also protects pre-existing workspace changes.
- Empty patch artifacts are intentional in codebase mode; selected file hashes are authoritative and snapshots are used when within configured limits.

## Run identity

Always pass `--run-id` or set `MATERIAL_REVIEW_RUN_ID` when more than one review run may exist. The adapter uses the shared default Git-path artifact root `material-code-review` so all controller commands see one state store.

## Bounded loops

- two discovery waves only;
- no candidate generation after ledger compilation;
- per-item attempts 1–3;
- plan repair rounds 0–2, normally 1;
- post-fix review restricted to approved IDs and fix-caused regressions;
- unrelated observations never reopen discovery.

## Inherited direction and plan contracts

Resolve the shared remediation auditor, remediation rubric, and causal test-evidence rubric from `$CORE_DIR/references/` in both layouts. Every retained provisional group carries an audit bound to scope, candidate IDs, and direction hash. Gate A approves only the opportunity. Fix-plan/v2 must then handle every approved constraint, state/exception, and open decision exactly, name alternatives, and explain any divergence before Gate B.
