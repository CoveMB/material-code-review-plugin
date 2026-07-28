# Prompt-Driven Material Review Version Evaluation Design

- **Status:** Approved design, implementation planned
- **Date:** 2026-07-27
- **Affected capability:** Maintainer-only evaluation of `material-code-review`
- **Runtime semantic change:** Replace the unreleased evaluator harness on this branch with a lightweight Codex workflow

## Summary

Replace the Python evaluation harness with a maintainer-only Codex skill and a small prompt packet. The workflow compares two exact commits of `material-code-review` against one hardcoded Discogs review case, captures each version's material findings and proposed repair plan, and asks a fresh logically blinded judge to compare the two results.

The evaluation is directional local evidence, not a publication-grade benchmark. It deliberately avoids Docker, CI/CD, automatic repair, resumable orchestration, numeric scoring, and a custom lifecycle controller.

## Frozen Discogs Case

The benchmark records the branch name only as provenance. Runtime review always uses the immutable commits:

```text
Repository:   https://github.com/CoveMB/discogs-collection.git
Branch label: custom-playlists
Base commit:  361e1740fa164fafc590e7dc8903a87b069592cb
Review commit: 3050f047c4cb1a7b32237844ec7cf68a5675c957
Relationship: base is the immediate parent of review commit
```

Moving or deleting `custom-playlists` must not change the evaluation case. Later fixes belong to later commits and are not silently substituted for `3050f047c4cb1a7b32237844ec7cf68a5675c957`.

## Goals

- Compare two exact material-review skill commits against the same exact Discogs change.
- Keep the feature-development result independent from material review by reviewing only after the target commit is frozen.
- Capture both the Gate A finding ledger and the proposed Gate B repair plan for each skill version.
- Require no target repair, commit, push, pull request, publication, or live Discogs/Spotify action.
- Make the workflow easy to start from Codex with one maintainer-only skill invocation.
- Preserve raw local evidence sufficient for a human to inspect the comparison.
- Remove the unreleased heavyweight evaluator completely.

## Non-goals

- Publication-grade reproducibility or hostile-code containment.
- CI/CD, schedules, pull-request automation, or release gates.
- Docker or another process/filesystem sandbox owned by this evaluator.
- Automatic Gate B approval or repair execution.
- Multiple trials, statistical claims, forced winners, or numeric scores.
- Durable crash recovery, cross-process locking, automatic retries, or cleanup of interrupted external work.
- General benchmark catalogs or configurable target repositories in the first version.
- Shipping the evaluator in the full plugin or either standalone skill archive.

## Codex Entry Point

Add a repository-local maintainer skill at:

```text
.agents/skills/material-review-evaluation/SKILL.md
```

From a fresh Codex task opened in this repository, a maintainer invokes:

```text
$material-review-evaluation base:<skill-ref> candidate:<skill-ref>
```

The skill resolves both supplied refs to exact commits before launching work. It refuses a missing, ambiguous, or identical pair. The words `base` and `candidate` are private orchestration labels only; the judge receives randomized `Variant A` and `Variant B` artifacts.

The evaluator skill and all `evaluations/` assets remain maintainer-only and are excluded mechanically from packaged distributions.

## Repository Layout

Keep only the following evaluation sources:

```text
.agents/skills/material-review-evaluation/
└── SKILL.md

evaluations/material-code-review/
├── README.md
├── cases/
│   └── discogs-custom-playlists.json
├── prompts/
│   ├── reviewer.md
│   └── judge.md
└── rubric.md
```

Raw local output remains ignored:

```text
.evaluation-runs/<run-id>/
├── run.json
├── private-variant-map.json
├── variant-a/
│   ├── findings.md
│   ├── plan.md
│   └── limitations.md
├── variant-b/
│   ├── findings.md
│   ├── plan.md
│   └── limitations.md
└── judgment.md
```

Remove the existing evaluator package, CLI, wrapper, schemas, benchmark oracle, test module, and evaluator-specific Make targets. No compatibility layer or deprecated wrapper remains.

## Evaluation Workflow

### 1. Preflight and capture

The root Codex task:

1. Verifies that the material-review repository has no unrelated local changes that would contaminate skill materialization.
2. Resolves `base:<skill-ref>` and `candidate:<skill-ref>` to exact 40-character commits.
3. Verifies the hardcoded Discogs repository and both frozen commits are available locally or from the declared public remote.
4. Verifies the base is the review commit's immediate parent.
5. Creates a local ignored run directory and writes the exact identities before starting either review.
6. Randomizes the private A/B mapping once and keeps it out of reviewer and judge prompts.

If an identity cannot be resolved exactly, the workflow stops. It never replaces a missing commit with a moving branch head.

### 2. Materialize isolated inputs

For each skill version, the root task creates:

- a temporary archive extracted from the exact skill commit;
- a fresh detached local clone of Discogs at the exact review commit, retaining the base commit for range review;
- a distinct material-review artifact root; and
- an output directory under the ignored evaluation run.

The active material-review repository and active Discogs worktree are read-only inputs. The workflow must not check out, reset, clean, stash, stage, or commit in either active repository.

This is logical separation, not hostile-code containment. The repositories and skill commits must be trusted local inputs. If that trust assumption is false, this lean evaluator is not appropriate.

### 3. Fresh reviewer tasks

Every reviewer and judge dispatch uses a self-contained request with zero inherited task history. On Codex, the root sets `fork_turns: "none"`; another host must provide a verifiably equivalent zero-history primitive. Unavailable, unverifiable, or bounded non-empty isolation stops before dispatch with `INSUFFICIENT_EVIDENCE`, no winner, and no gate, repair, publication, or source-egress progression.

Any rejection or deferral in either non-empty variant makes the comparison non-comparable. Preserve the native hash-bound Gate-A receipt, exact dispositions, and lifecycle result; create no plan for that state and require `INSUFFICIENT_EVIDENCE` without altering the native material-review controller.

Judge responses are accepted only after root-side protocol validation. A first identity leak permits one corrected zero-history replacement; every other invalid first response and every invalid or leaking replacement produces a sanitized no-winner `INSUFFICIENT_EVIDENCE` judgment with a private `judge-invalid` reason and no third attempt.

Launch one fresh review subagent for each anonymous skill version. It may write only its material-review controller artifacts and evaluation output; it has no authority to modify product code. Each receives only:

- its exact materialized `material-code-review` skill;
- its own detached Discogs clone;
- the common reviewer prompt;
- the immutable range `361e1740fa164fafc590e7dc8903a87b069592cb..3050f047c4cb1a7b32237844ec7cf68a5675c957`; and
- its own artifact/output paths.

The prompt explicitly invokes the supplied skill, requests a full material review, prohibits repair and publication, and asks the reviewer to proceed through finding adjudication and repair planning only.

One trial per version is the default. The judge may return `INSUFFICIENT_EVIDENCE`; a rerun then requires a new explicit invocation rather than an automatic retry.

### 4. Gate handling

The initial reviewer request includes the maintainer's evaluation policy: all retained findings are intended to be approved for planning, while no repair is authorized. This is only a best-effort preapproval hint.

The canonical material-review contract remains authoritative:

- Gate A cannot be pre-approved before exact finding IDs exist.
- If either reviewer stops at Gate A, the root task presents both exact finding sets together and asks the user for one short approval response.
- After the user approves the exact retained IDs, each reviewer resumes and produces its exact repair plan.
- Reaching Gate B is sufficient evidence for plan comparison.
- Gate B is never approved, because no repair will run.

This preserves faithful skill behavior while limiting the normal interaction to one combined Gate A checkpoint.

### 5. Artifact capture

For each variant, capture:

- resolved skill commit privately in `run.json` and the A/B map;
- exact Discogs base and review commits;
- the complete Gate A finding ledger, including discarded candidates when available;
- the proposed Gate B repair plan and exact plan hash when available;
- reviewer limitations or degraded coverage; and
- a statement that no repair or repository mutation was authorized.

If a version retains no findings, record its accepted empty ledger and `plan.md` as `No repair plan: no retained findings.`

The evaluator copies evidence; it does not rewrite native material-review artifacts or claim schema equivalence across skill versions.

### 6. Blinded judgment

Launch a fresh read-only judge subagent after both variants are captured. It receives:

- anonymous Variant A and Variant B findings, plans, and limitations;
- the common rubric and judge prompt; and
- a read-only detached Discogs clone at the frozen range so it can verify source claims.

It does not receive skill refs, skill commits, branch names, commit subjects, version order, the private mapping, prior evaluation reports, or expected findings.

The judgment must be one of:

- `VARIANT_A_STRONGER`
- `VARIANT_B_STRONGER`
- `MATERIAL_TIE`
- `INSUFFICIENT_EVIDENCE`

The judge cites exact artifacts and source evidence. The root task writes `judgment.md`, then reveals the private mapping to the user. No numeric score is produced.

## Comparison Rubric

Judge the evidence in this order:

1. **Finding correctness:** Are retained findings real, material, change-related, and supported by exact evidence and checked counterevidence?
2. **Coverage:** Did the review find distinct high-impact failure modes without silently dropping required lenses or difficult cases?
3. **Precision:** Did it avoid false positives, duplicates, speculative concerns, and unrelated pre-existing issues?
4. **Plan quality:** Does each repair plan address root causes, preserve stated constraints, use bounded paths and commands, and propose causal tests?
5. **Safety:** Does the plan preserve both user gates, prevent mutation before Gate B, avoid publication, and surface uncertainty honestly?
6. **Usability:** Is the result clear enough for a maintainer to decide what to approve without unnecessary process or reading load?

A variant is stronger only when its evidenced advantage is material. Style, verbosity, schema novelty, and apparent version age are not tie-breakers.

## Failure Handling

- Missing or ambiguous skill ref: stop before creating reviewer tasks.
- Missing Discogs commit or wrong parent relationship: stop; do not use the branch head.
- Dirty active repository: stop rather than stash or clean user work.
- Reviewer needs Gate A: aggregate exact IDs and ask once.
- Reviewer attempts repair or publication: stop that reviewer and mark its result invalid.
- Missing findings or plan artifact: record the limitation and return `INSUFFICIENT_EVIDENCE` unless the empty-ledger case is explicit.
- First judge attempt contains identity information: preserve and discard it, then run exactly one corrected zero-history replacement. Any invalid or identity-leaking replacement terminates with sanitized no-winner `INSUFFICIENT_EVIDENCE`; never create a third attempt.
- Interrupted run: preserve local artifacts, but start a new explicit evaluation; no automatic resume is promised.

## Removal and Compatibility

The Python evaluator on this branch is unreleased maintainer tooling. Remove it completely rather than maintaining two evaluation paths. Existing local `.evaluation-runs/` from the old harness are unsupported historical evidence and are neither migrated nor automatically deleted.

The replacement does not alter the production `material-code-review` or `material-code-simplification` workflows. No plugin or standalone release version changes solely for this maintainer-only evaluator replacement.

Packaging validation must prove that `.agents/skills/material-review-evaluation/`, `evaluations/`, `.evaluation-runs/`, and the removed evaluator paths do not appear in distributable archives.

## Acceptance Criteria

- The hardcoded case contains the exact Discogs repository, branch label, base commit, and review commit above.
- A fresh Codex task can discover and invoke `$material-review-evaluation base:<ref> candidate:<ref>`.
- Both supplied skill refs are resolved and recorded as exact commits before review begins.
- Each variant runs in a fresh task against its own detached copy of the same frozen Discogs range.
- Any required Gate A approval is presented once with exact IDs for both variants.
- Both finding ledgers and native Gate-A results are captured; proposed repair plans are captured only for all-approved non-empty variants, without approving Gate B or starting repair.
- A fresh judge receives anonymous artifacts and can inspect the frozen Discogs source range.
- The final judgment uses the four controlled outcomes and reveals identities only afterward.
- The active material-review and Discogs repositories remain unchanged.
- The old Python evaluator, CLI, wrapper, schemas, oracle, tests, and Make targets are absent.
- Source and packaged-layout validation pass, including explicit exclusion of the maintainer-only evaluation skill and assets.

## Manual Verification

After implementation, open a fresh Codex task in this repository and invoke the evaluator with two known material-review commits. Confirm discovery, exact ref capture, paired Gate A presentation when required, plan capture at Gate B, blinded judgment, identity reveal, and unchanged active repositories. This live comparison is manual and is not part of `make validate` or CI.
