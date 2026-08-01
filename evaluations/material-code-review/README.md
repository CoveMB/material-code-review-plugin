# Maintainer material-review version evaluation

This repository-local workflow provides directional local evidence about two exact `material-code-review` revisions. It is not a publication-grade benchmark or an implicit skill-selection test.

## Prerequisites and invocation

Open a fresh Codex task at the repository root. The material-review repository must have no unrelated local changes. Git must be able to resolve both requested skill refs. The frozen Discogs commits may come from an attested clean trusted local checkout with the declared origin or, when none is known, the public repository.

Invoke:

```text
$material-review-evaluation base:<skill-ref> candidate:<skill-ref>
```

This defaults to `discogs-custom-playlists`. The bounded missed-contract confirmation is selected explicitly:

```text
$material-review-evaluation case:missed-contracts base:<skill-ref> candidate:<skill-ref>
```

The selectors must resolve to two distinct exact commits. `base` and `candidate` are private orchestration labels; the judge receives randomized anonymous variants.

Every reviewer, challenger, and judge dispatch uses a self-contained request with zero inherited task history. Codex uses `fork_turns: "none"`; another host must provide a verifiably equivalent primitive or the evaluator stops before dispatch with `INSUFFICIENT_EVIDENCE` and no winner.

Any rejection or deferral in either non-empty variant makes the comparison non-comparable. The evaluator records the native hash-bound dispositions, keeps accepted-empty and missing-evidence states distinct, and requires `INSUFFICIENT_EVIDENCE` without producing a plan for the rejected or deferred state.

Judge responses are accepted only after root-side protocol validation. A first identity leak permits one corrected zero-history replacement; every other invalid first response and every invalid or leaking replacement produces a sanitized no-winner `INSUFFICIENT_EVIDENCE` judgment while raw attempts remain private local evidence.

## Frozen cases and workflow boundary

The default case is the provenance label `custom-playlists` from `https://github.com/CoveMB/discogs-collection.git`, frozen as the immediate-parent range:

```text
361e1740fa164fafc590e7dc8903a87b069592cb..3050f047c4cb1a7b32237844ec7cf68a5675c957
```

The `missed-contracts` case builds a deterministic temporary Git repository from committed allowlisted base and review trees. Its review commit introduces exactly five contract roots across version parsing, workflow ordering, schema/runtime path parity, required-risk cardinality, and archive closure. Exact fixture tree/commit hashes are verified before workers run. The private root IDs are acceptance evidence, never reviewer, challenger, or judge seeds.

Before dispatch, the evaluator scans the complete worker-visible guidance and prompt allowlist for private root IDs, exact root definitions, and the retired one-to-one fixture guidance. Any match stops the run. Frozen implementation source is intentionally outside this contamination scan and remains the evidence workers must inspect; the private oracle is used only after the blinded judgment is durable and identities are revealed.

Each skill version receives one fresh primary-reviewer trial in its own detached target clone. The evaluator captures each complete finding ledger and native Gate-A result. For missed-contracts only, each primary reviewer first pauses after declarative coverage recording and before candidate ingestion; a separate zero-history challenger receives frozen source plus change-unit, risk, obligation, assignment, and limitation declarations. Candidate findings, candidate sets, check results, expected roots, variant identities, refs, prior output, and the other variant are forbidden. It returns only `NO_COVERAGE_GAP` or a bounded declarative `COVERAGE_GAP` and cannot add findings or count as independent finding validation. `NO_COVERAGE_GAP` cannot establish check-result freshness, completeness, blocked status, resolution, or safety; native controller and evaluator-root result validation remains mandatory and independent.

Maintainer intent to approve retained findings for planning is only a hint: both valid variants always pause at one combined Gate-A interaction. Codex presents every exact retained ID and requests explicit acceptance for each empty ledger. Only an all-approved non-empty variant continues to a validated repair plan; a rejection or deferral uses the non-comparable no-plan policy above. Gate B is never approved, no repair starts, and no product, active worktree, remote, or live service is changed.

A fresh read-only judge compares anonymous artifacts, verifies claims against its detached clone, and returns one of `VARIANT_A_STRONGER`, `VARIANT_B_STRONGER`, `MATERIAL_TIE`, or `INSUFFICIENT_EVIDENCE`. An invalid reviewer, challenger declarative gap, stale, incomplete, blocked, duplicated, or unresolved native check-result evidence, or missing required artifact is preserved as a limitation and blocks a successful-strengthening claim; missing content is never reconstructed. Identities are revealed only after `judgment.md` is written.

Missed-contracts permits one comparison and at most one separately authorized repair-plus-confirmation when the first result identifies a concrete implementation defect. There is no resampling. Success requires all five private roots, every material baseline root, complete controller-valid assignments, obligations, `check_results`, and Gate-A evidence, no unsupported high-severity addition, declarative `NO_COVERAGE_GAP`, no mutation, and a candidate-stronger blinded judgment. A tie, baseline-stronger result, insufficient evidence, invalid judge, missing root, lost baseline finding, or challenger gap blocks the claim. Deterministic tests remain release authority.

## Local output

Raw evidence is written under the ignored `.evaluation-runs/<run-id>/` directory:

```text
run.json
private-variant-map.json
variant-a/findings.md
variant-a/plan.md
variant-a/limitations.md
variant-a/challenge.md  # missed-contracts only
variant-b/findings.md
variant-b/plan.md
variant-b/limitations.md
variant-b/challenge.md  # missed-contracts only
judgment.md
```

Raw local artifacts may contain machine-specific paths. They are not automatically published or sanitized. The repository-local evaluator skill, this `evaluations/` directory, and `.evaluation-runs/` are excluded from release archives.

## Trust and interruption

This workflow provides logical separation, not hostile-code containment. Use it only with trusted local repositories and trusted skill commits. It does not use Docker, CI/CD, automatic retry, or automatic resume.

If a run is interrupted, preserve its local evidence for inspection and start a new invocation. A new run is always a new explicit invocation; the workflow promises neither cleanup nor resume of interrupted external work.
