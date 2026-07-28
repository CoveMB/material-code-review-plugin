# Prompt-Driven Material Review Version Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unreleased Python evaluator with one maintainer-only Codex skill and a small, reviewable prompt packet that compare two exact `material-code-review` commits against the frozen Discogs `custom-playlists` change, capture findings and Gate-B repair plans without repairing anything, and produce a blinded qualitative judgment.

**Architecture:** A repository-local skill at `.agents/skills/material-review-evaluation/SKILL.md` is the only entrypoint. It resolves immutable identities, creates run-owned temporary skill snapshots and detached Discogs clones, dispatches two fresh anonymous reviewer workers, coordinates at most one combined Gate-A approval, captures both reviewers at Gate B, and dispatches a fresh anonymous judge. Committed JSON and Markdown under `evaluations/material-code-review/` define the single frozen case, reviewer contract, judge contract, and rubric. There is no custom runtime controller: Codex performs the workflow directly and writes inspectable ignored evidence under `.evaluation-runs/`.

**Tech Stack:** Agent Skills Markdown, Codex native subagents, Git CLI, JSON, existing Python standard-library source/package validation, `unittest`, Make, ZIP inspection.

## Global Constraints

- Implement only in `/private/tmp/material-review-evaluation-design.YbbJ4g/worktree` on branch `docs/material-review-evaluation-design`. Do not edit the active checkouts at `/Users/CoveMB/Code/CoveMB/material-code-review-plugin` or `/Users/CoveMB/Code/CoveMB/discogs-collection`.
- Before the first edit, fetch the repository and verify the worktree, branch, HEAD, and existing user changes. Preserve the approved spec edit already present in this worktree.
- Affected capability: maintainer-only evaluation of `material-code-review`. The canonical owners are the evaluator skill for orchestration and `evaluations/material-code-review/` for the case, prompts, and rubric.
- Production `material-code-review`, `material-code-simplification`, their shared controller, schemas, manifests, activation semantics, gates, and repair behavior must not change.
- Backward compatibility: the old evaluator is unreleased and receives no compatibility wrapper or migration. Existing ignored `.evaluation-runs/` are retained as unsupported historical evidence and are never automatically deleted.
- No plugin or standalone artifact version change is required because the new evaluator is maintainer-only and excluded from all distributable layouts.
- Do not create Docker files, CI/CD workflows, a Python evaluator package, a CLI, a shell wrapper, a schema framework, retry/resume machinery, an oracle, or a second lifecycle controller.
- Do not add a configurable benchmark catalog. Version one has exactly one case: repository `https://github.com/CoveMB/discogs-collection.git`, branch label `custom-playlists`, base `361e1740fa164fafc590e7dc8903a87b069592cb`, and review commit `3050f047c4cb1a7b32237844ec7cf68a5675c957`.
- Treat the branch label as provenance only. Every review uses the exact commits, and the base must be the review commit's immediate parent.
- Use one reviewer trial per skill version. No automatic retries, third trials, numeric scores, forced winner, or statistical claim.
- Every reviewer and judge dispatch uses a self-contained request with zero inherited task history. Codex uses `fork_turns: "none"`; an unavailable or unverifiable equivalent fails closed before dispatch with `INSUFFICIENT_EVIDENCE` and no winner.
- Any rejection or deferral in either non-empty variant makes the comparison non-comparable. Preserve the native hash-bound disposition evidence, produce no plan for that state, and require `INSUFFICIENT_EVIDENCE` without changing controller behavior.
- Judge responses are accepted only after root-side protocol validation. Allow one corrected zero-history replacement only for a first identity leak; every other invalid first response and every invalid or leaking replacement terminates with sanitized no-winner `INSUFFICIENT_EVIDENCE`, private `judge-invalid`, and no third attempt.
- Best-effort approval language may express the maintainer's intent, but Gate A remains exact-ID gated. If needed, aggregate both variants into one user checkpoint. Never approve Gate B, call a repair command, or modify product code.
- Reviewer workers may write only their run-owned controller/evaluation artifacts. They must not modify, stage, commit, push, publish, or make live Discogs/Spotify calls. The judge is read-only.
- Active repositories are immutable inputs. Do not check out, reset, clean, stash, stage, or commit in them. Temporary clones and archives must live outside the active worktrees.
- Keep the A/B mapping private until `judgment.md` is complete. Reviewer and judge bundles must omit skill refs, skill commits, ordering, commit subjects, private paths, earlier reports, and expected findings.
- Preserve `.evaluation-runs/` in `.gitignore`. Raw output is local and may contain machine-specific paths; it is not packaged or published.
- Apply TDD to validator changes. Apply the `superpowers:writing-skills` RED-GREEN-REFACTOR process to the new skill: observe fresh-agent behavior without the skill before writing it, then repeat the same scenario with the skill.
- Do not create commits, push, open a pull request, or respond to GitHub review comments during implementation unless the user separately authorizes that action.

---

### Task 1: Record the no-skill behavioral baseline

**Files:**
- Create locally, ignored: `.evaluation-runs/skill-authoring-<timestamp>/baseline.md`
- Do not modify tracked files in this task.

- [ ] **Step 1: Verify the implementation worktree and preserve the approved design**

Run:

```bash
git fetch --all --prune
git status --short --branch
git branch --show-current
git rev-parse HEAD
git diff -- docs/superpowers/specs/2026-07-27-material-review-version-evaluation-design.md
```

Expected: branch `docs/material-review-evaluation-design`; the approved design diff is present; no unrelated changes are silently discarded. If fetch changes the remote state, do not rebase or merge without user direction.

- [ ] **Step 2: Create an ignored evidence directory**

Use `mktemp -d` for any temporary scenario fixtures. Store only the human-readable baseline record under `.evaluation-runs/`; verify `git check-ignore .evaluation-runs/probe` succeeds before writing it.

- [ ] **Step 3: Run one fresh-agent control scenario without loading the proposed evaluator skill**

Give a fresh bounded subagent this scenario, with no access to the proposed `SKILL.md` because it does not yet exist:

```text
This is an execution decision, not a documentation quiz. A maintainer wants one quick local comparison of two material-code-review commits on the exact Discogs range 361e1740fa164fafc590e7dc8903a87b069592cb..3050f047c4cb1a7b32237844ec7cf68a5675c957. They say “all gates are preapproved,” want findings and repair plans compared, do not want Docker or CI, and do not authorize repair, commits, pushes, publication, or live API calls. Describe the exact actions and artifacts you would produce from a fresh Codex task. You must decide how Gate A, Gate B, identity blinding, active repositories, and interrupted work are handled.
```

The control passes only if it independently produces every approved invariant: exact commit resolution, separate temporary inputs, unchanged active repositories, anonymous one-trial reviewers, exact-ID Gate A with at most one combined user interaction, no Gate-B approval, findings and plan capture, a fresh source-checking judge, the four controlled outcomes, and no automatic retry/resume claim.

- [ ] **Step 4: Verify RED and capture exact failure evidence**

Expected: the no-skill worker omits or violates at least one invariant or produces a materially different artifact shape. Copy its exact decisions and rationalizations into `baseline.md`; do not summarize them into hypothetical failures.

If the control satisfies every invariant, stop before authoring the skill and report that the simpler prompt already appears sufficient. That result would materially challenge the approved implementation choice and requires user direction under the skill-authoring rules.

---

### Task 2: Add the frozen case and prompt packet

**Files:**
- Modify: `scripts/tests/test_packaging.py`
- Create: `evaluations/material-code-review/README.md`
- Create: `evaluations/material-code-review/cases/discogs-custom-playlists.json`
- Create: `evaluations/material-code-review/prompts/reviewer.md`
- Create: `evaluations/material-code-review/prompts/judge.md`
- Create: `evaluations/material-code-review/rubric.md`

- [ ] **Step 1: Read the test-quality guidance before changing tests**

Use `superpowers:test-driven-development` and read its `writing-good-tests.md` reference. Name the production contract that would make each test fail before writing it. Test externally visible source/package behavior, not implementation helpers.

- [ ] **Step 2: Write the frozen-case test first**

Add `test_prompt_driven_evaluation_case_is_frozen` to `scripts/tests/test_packaging.py`. Load the committed JSON and assert this complete controlled identity:

```python
expected = {
    "schema_version": "material-review-evaluation/case/v1",
    "case_id": "discogs-custom-playlists",
    "repository": "https://github.com/CoveMB/discogs-collection.git",
    "branch_label": "custom-playlists",
    "base_commit": "361e1740fa164fafc590e7dc8903a87b069592cb",
    "review_commit": "3050f047c4cb1a7b32237844ec7cf68a5675c957",
    "require_immediate_parent": True,
    "review_mode": "range",
    "posture": "immutable",
}
self.assertEqual(case, expected)
```

Add `test_prompt_driven_evaluation_prompts_define_controlled_contract`. Assert that:

- `reviewer.md` contains the exact range, `Gate A`, `Gate B`, the no-repair boundary, retained and discarded findings, plan hash, and limitation capture;
- `judge.md` contains all four exact judgment outcomes and forbids identity inference;
- `rubric.md` names finding correctness, coverage, precision, plan quality, safety, and usability in that order; and
- `README.md` gives the exact invocation `$material-review-evaluation base:<skill-ref> candidate:<skill-ref>` and labels the result directional local evidence.

Use exact-phrase assertions only for these controlled interface terms. Do not test paragraph wording or line counts.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
python3 -B -m unittest \
  scripts.tests.test_packaging.StandalonePackagingTests.test_prompt_driven_evaluation_case_is_frozen \
  scripts.tests.test_packaging.StandalonePackagingTests.test_prompt_driven_evaluation_prompts_define_controlled_contract \
  -v
```

Expected: both tests fail because the lean case and prompt packet do not exist.

- [ ] **Step 4: Write the exact case JSON**

Create `evaluations/material-code-review/cases/discogs-custom-playlists.json` with exactly the object shown in Step 2, UTF-8, two-space indentation, and a trailing newline. Do not add moving refs, local absolute paths, expected findings, credentials, commands, or model settings.

- [ ] **Step 5: Write the reviewer prompt as a positive output recipe**

`reviewer.md` must tell a fresh reviewer to:

1. Load the supplied exact `material-code-review` skill from its materialized directory.
2. Review only the frozen range in its detached Discogs clone with `scope:range`, the exact base/head commits, full depth, immutable posture, and external review off.
3. Use the supplied artifact root outside the target worktree.
4. Run the canonical workflow faithfully, with sequential lenses if recursive subagents are unavailable.
5. Treat the initial “approve all retained findings for planning” sentence as maintainer intent only, never as an exact-ID Gate-A approval.
6. Stop and return the exact retained/discarded ledger when Gate A requires approval.
7. After exact dispositions are supplied, produce and validate a repair plan only for an all-approved non-empty ledger; otherwise return the native hash-bound disposition state without fabricating a plan.
8. Return a findings section, plan section, limitations section, native artifact paths/hashes, and an explicit no-mutation attestation.

State the prohibited actions as hard boundaries: no product edits, repair start, Gate-B approval, tests that mutate external state, live APIs, commit, push, PR, publication, source egress, oracle lookup, other variant, or earlier run discovery.

- [ ] **Step 6: Write the judge prompt and rubric**

`judge.md` must define this output recipe in order:

1. controlled outcome;
2. material comparison of findings;
3. material comparison of repair plans;
4. limitations and uncertainty;
5. exact anonymous artifact/source citations.

Allow only `VARIANT_A_STRONGER`, `VARIANT_B_STRONGER`, `MATERIAL_TIE`, or `INSUFFICIENT_EVIDENCE`. Require source verification against the detached frozen Discogs range. Forbid guessing identities or using style, verbosity, apparent age, or schema novelty as tie-breakers.

`rubric.md` must reproduce the six approved dimensions and the rule that a winner requires a material evidenced advantage. It must explain when to return a tie versus insufficient evidence and must not introduce numeric scoring.

- [ ] **Step 7: Write the maintainer README**

Document prerequisites, the exact invocation, the fixed case, the one possible combined Gate-A interaction, the no-Gate-B/no-repair stop, output layout, trust boundary, interrupted-run behavior, and the fact that the evaluator is excluded from release archives. Explicitly state that a new run is a new invocation and that raw local artifacts are not automatically published or sanitized.

- [ ] **Step 8: Run focused tests and verify GREEN**

Run the command from Step 3.

Expected: both tests pass. Then run:

```bash
python3 -c 'import json, pathlib; json.loads(pathlib.Path("evaluations/material-code-review/cases/discogs-custom-playlists.json").read_text()); print("case JSON OK")'
git diff --check
```

Expected: `case JSON OK` and no whitespace errors.

---

### Task 3: Author and pressure-test the repository-local Codex skill

**Files:**
- Modify: `scripts/tests/test_packaging.py`
- Create: `.agents/skills/material-review-evaluation/SKILL.md`
- Use locally, ignored: `.evaluation-runs/skill-authoring-<timestamp>/green.md`

- [ ] **Step 1: Write a static discovery/contract test before the skill**

Add `test_prompt_driven_evaluation_skill_has_discoverable_contract`. It must parse the new file and assert:

```python
self.assertEqual(frontmatter["name"], "material-review-evaluation")
self.assertTrue(frontmatter["description"].startswith("Use when "))
self.assertEqual(frontmatter["argument-hint"], "base:<skill-ref> candidate:<skill-ref>")
```

Also assert the body contains the exact invocation, all four judgment outcomes, `.evaluation-runs/`, `private-variant-map.json`, the fixed Discogs commits, Gate-A aggregation, and the prohibition on Gate-B approval. Do not make the test depend on prose formatting.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
python3 -B -m unittest \
  scripts.tests.test_packaging.StandalonePackagingTests.test_prompt_driven_evaluation_skill_has_discoverable_contract \
  -v
```

Expected: failure because `.agents/skills/material-review-evaluation/SKILL.md` does not exist.

- [ ] **Step 3: Write minimal discovery frontmatter**

Use this exact frontmatter:

```yaml
---
name: material-review-evaluation
description: Use when a maintainer wants to compare two exact material-code-review Git revisions against the frozen Discogs custom-playlists change from a fresh Codex task.
argument-hint: "base:<skill-ref> candidate:<skill-ref>"
---
```

The description is only the trigger; keep workflow details in the body.

- [ ] **Step 4: Write the skill's hard invariants and preflight**

The body must define:

- exactly two required selectors, with missing, ambiguous, non-commit, or identical resolved commits rejected;
- exact 40-character SHA capture before reviewer dispatch;
- case JSON as the target identity owner;
- clean active material-review repository and unchanged active-repository attestations before and after the run;
- a run-owned directory `.evaluation-runs/<UTC timestamp>-<short random id>/`;
- one private randomized A/B assignment stored only in `private-variant-map.json` and private root context;
- active worktrees as immutable and trusted local inputs;
- one trial per version, no automatic retry/resume, and no cleanup promise for interrupted runs; and
- no repair, Gate-B approval, publication, or source egress.

Resolve refs with Git's commit-peeling form and record the returned SHA once. Materialize each version from that exact SHA into a temporary run-owned directory; never check out the active repository. Create two distinct detached Discogs clones at the exact review commit and verify the immediate parent equals the exact base.

- [ ] **Step 5: Write the reviewer and Gate-A recipe**

The evaluator root may dispatch exactly two fresh reviewer workers in parallel. Prohibit recursive fan-out from those workers; when the material-review skill would delegate and host depth is unavailable, reviewers run the same lenses sequentially as its canonical fallback permits.

Give each reviewer only its anonymous label, exact materialized skill path, exact target clone, its artifact/output roots, and `reviewer.md`. Do not give it the other variant, supplied ref, commit subject, private map, judge prompt, prior output, or expected findings.

Wait for both reviewers. If either needs Gate A:

1. extract and display both variants' exact retained IDs and one-line finding titles/effects;
2. identify each zero-finding variant as awaiting explicit empty-ledger acceptance;
3. ask the user once for an approve, reject, or defer disposition on every displayed ID and explicit acceptance of each displayed empty ledger;
4. send each reviewer its complete disposition set, including every retained ID's status and the exact user statement, or explicit `--accept-empty` authority plus that statement; and
5. use the complete native receipt and lifecycle evidence to classify each reviewer as reaching Gate B with an all-approved plan or reporting an accepted-empty, mixed-disposition, or no-approved-findings result.

The initial request may state the maintainer intends to approve all retained findings for planning, but the evaluator must not fabricate approval. A user reply such as “approved all” applies only to the exact IDs displayed in the immediately preceding combined checkpoint.

- [ ] **Step 6: Write the capture and judge recipe**

For each anonymous variant, create:

```text
variant-a/findings.md
variant-a/plan.md
variant-a/limitations.md
variant-b/findings.md
variant-b/plan.md
variant-b/limitations.md
```

`findings.md` contains the complete retained ledger plus discarded candidates when available and cites the native artifact path/hash. For an all-approved non-empty variant, `plan.md` contains the complete validated Gate-B plan plus exact native plan hash. For an accepted empty ledger it contains exactly `No repair plan: no retained findings.` Mixed and zero-approved non-empty states instead contain the hash-bound native disposition evidence and distinct no-plan reason required by the non-comparable policy. `limitations.md` records degraded coverage, missing evidence, and a no-mutation attestation. Do not rewrite native artifacts or claim cross-version schema equivalence.

Write `run.json` with the exact target commits, exact skill commits, timestamps, artifact paths/hashes, and run status. Keep `private-variant-map.json` out of all judge inputs.

Dispatch one fresh read-only judge worker with only anonymous findings/plans/limitations, `judge.md`, `rubric.md`, and a third detached read-only Discogs clone at the same frozen range. Preserve its raw response privately and accept it only after validating one controlled outcome, every ordered section, anonymous artifact and frozen-source citations, zero-history context, and no identity data. Permit one corrected replacement only for a first identity leak; otherwise write sanitized no-winner `INSUFFICIENT_EVIDENCE`. Write validated or terminal `judgment.md` before revealing the private mapping to the user.

- [ ] **Step 7: Address only failures observed in the baseline**

Use the exact Task-1 omissions/rationalizations to add a short “Red flags” or “Common mistakes” section. Do not add hypothetical infrastructure or generic skill-authoring advice. Keep the skill concise enough to scan; move detailed comparison criteria to the committed prompt/rubric files instead of repeating them.

- [ ] **Step 8: Run static GREEN verification**

Run the command from Step 2 and `git diff --check`.

Expected: the discovery/contract test passes and the skill has valid frontmatter.

- [ ] **Step 9: Repeat the baseline scenario with the skill**

Give the same Task-1 scenario to a fresh bounded subagent with the new skill supplied. Capture its exact actions in `green.md`. It passes only if every invariant listed in Task 1 is satisfied and it closes the observed baseline failure without inventing another workflow.

If it finds a new loophole, minimally revise the skill, record the exact new rationalization, and repeat this same scenario. Do not expand the committed evaluator into automated orchestration.

---

### Task 4: Remove the heavyweight evaluator and replace its documentation

**Files:**
- Modify: `scripts/tests/test_packaging.py`
- Modify: `scripts/validate_package.py`
- Modify: `Makefile`
- Modify: `README.md`
- Modify: `EVALUATION.md`
- Preserve: `.gitignore`
- Delete: `bin/material-review-evaluate`
- Delete: `scripts/evaluate_material_review.py`
- Delete: `scripts/tests/test_evaluate_material_review.py`
- Delete: `scripts/material_review_evaluation/`
- Delete: `evaluations/material-code-review/benchmarks/`
- Delete: `evaluations/material-code-review/schemas/`
- Delete: `evaluations/material-code-review/prompts/trial-agreement.md`
- Delete: `evaluations/material-code-review/prompts/comparison-judge.md`
- Delete: `evaluations/material-code-review/judge-rubric.md`

- [ ] **Step 1: Write the removal regression test first**

Replace evaluator-specific tests with `test_source_uses_only_prompt_driven_evaluation_surface`. Assert that every old path listed above is absent and every new path from Tasks 2-3 is present. Read `Makefile` and assert it has no `evaluate-review`, `EVALUATOR_PYTHON`, `EVALUATOR_WRAPPER`, `scripts/evaluate_material_review.py`, or `bin/material-review-evaluate` reference.

Update the source-validator fixture test so deleting any new required evaluator source produces `missing required file: <exact path>`. Remove tests whose purpose was to require the old executable wrapper, Python module, CLI flags, evaluator compile target, old schemas, or old benchmark JSON.

- [ ] **Step 2: Run the removal test and verify RED**

Run:

```bash
python3 -B -m unittest \
  scripts.tests.test_packaging.StandalonePackagingTests.test_source_uses_only_prompt_driven_evaluation_surface \
  -v
```

Expected: failure listing the existing old evaluator paths and Make surface.

- [ ] **Step 3: Delete the old evaluator implementation and assets**

Use `apply_patch` for tracked-file deletion. Remove the complete Python package, entry script, Bash wrapper, dedicated evaluator test, old benchmark/oracle, old prompts, old rubric, and three old schemas. Do not leave deprecated shims, empty directories, imports, or copied compatibility files.

- [ ] **Step 4: Simplify Make targets**

Remove the evaluator variables and `evaluate-review` phony target. `SHELL_WRAPPERS` becomes only `bin/material-reviewctl`. The `validate` and `compile` targets compile only shipped/current repository Python. Keep the existing `validate`, `package`, `package-simplification`, `package-check`, `test`, `json`, `shell`, and `clean` behavior otherwise unchanged.

- [ ] **Step 5: Replace source validation requirements**

In `scripts/validate_package.py`:

- replace every old evaluator member of `MAINTAINER_SOURCE_REQUIRED` with the six new paths from Tasks 2-3;
- remove old evaluator exact archive entries and the old executable-wrapper check;
- keep generic validation of every committed JSON file, which covers the new case;
- validate the new skill frontmatter name, `Use when` description, and exact argument hint in source-layout mode; and
- keep distribution-layout validation independent of maintainer-only source files.

Do not add schema validation, controller logic, or a behavioral evaluator to the validator.

- [ ] **Step 6: Rewrite the maintainer documentation**

Replace the old evaluator sections in `README.md` and `EVALUATION.md` with the lean workflow:

- exact invocation from a fresh Codex task;
- exact frozen Discogs case;
- one trial per version;
- findings plus repair-plan comparison;
- best-effort approval intent and one possible combined Gate-A interaction;
- Gate B never approved and no repair;
- anonymous four-outcome judge;
- trusted-local/directional-evidence limitation;
- no Docker, CI/CD, automatic resume, or publication; and
- raw ignored output plus package exclusion.

Keep the existing statement that this is an explicit workflow and does not prove implicit skill selection. Remove CLI commands, model flags, benchmark IDs, agreement trials, oracle claims, sanitized report claims, cleanup commands, and resumable-controller language.

- [ ] **Step 7: Verify obsolete wording is gone**

Run:

```bash
rg -n \
  'material-review-evaluate|material_review_evaluation|evaluate-review|discogs-album-recovery|judge-oracle|trial-agreement|comparison-judge|evaluation-run\.schema|agreement\.schema|judgment\.schema' \
  --glob '!docs/superpowers/**' .
```

Expected: no matches.

Verify the ignored evidence boundary remains:

```bash
git check-ignore .evaluation-runs/probe
```

Expected: `.evaluation-runs/probe`.

- [ ] **Step 8: Run focused GREEN verification**

Run the removal test from Step 2 plus the two Task-2 tests and Task-3 static test.

Expected: all pass.

---

### Task 5: Exclude the maintainer skill without hiding shipped Agent metadata

**Files:**
- Modify: `scripts/tests/test_packaging.py`
- Modify: `scripts/package_plugin.py`
- Modify: `scripts/validate_package.py`

- [ ] **Step 1: Write package-boundary tests first**

Update `test_archive_validator_rejects_maintainer_only_evaluator_entries` to inject `.agents/skills/material-review-evaluation/SKILL.md` into a generated full archive and expect:

```text
forbidden maintainer-only archive entry .agents/skills/material-review-evaluation/SKILL.md
```

Add or update the successful archive test to assert all of these:

```python
self.assertNotIn(".agents/skills/material-review-evaluation/SKILL.md", names)
self.assertFalse(any(name.startswith("evaluations/") for name in names))
self.assertFalse(any(name.startswith(".evaluation-runs/") for name in names))
self.assertIn(".agents/plugins/marketplace.json", names)
```

Also retain absence assertions for the deleted Python package, script, wrapper, and old evaluator test so a future reintroduction cannot silently ship.

- [ ] **Step 2: Run focused tests and verify RED**

Run the two updated archive tests.

Expected: the new repository-local evaluator skill appears in the full archive or is not rejected by archive validation; the test must fail for that exact boundary.

- [ ] **Step 3: Add the narrow maintainer-only prefix**

Add exactly `.agents/skills/material-review-evaluation/` to `MAINTAINER_ONLY_PREFIXES` in `scripts/package_plugin.py` and `MAINTAINER_ONLY_ARCHIVE_PREFIXES` in `scripts/validate_package.py`.

Do not exclude `.agents/` broadly. The shipped `.agents/plugins/marketplace.json` must remain present in the full plugin archive.

Keep `evaluations/`, `.evaluation-runs/`, `.superpowers/`, and `docs/superpowers/` excluded. Remove exclusion constants that exist only for now-deleted old evaluator source paths.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
python3 -B -m unittest scripts.tests.test_packaging.StandalonePackagingTests -v
```

Expected: all packaging tests pass except any already documented platform-specific skip; full archives retain marketplace metadata and omit every maintainer evaluation asset.

---

### Task 6: Complete coherence and distribution verification

**Files:**
- Review all changed files from Tasks 1-5.
- Do not modify production skill/controller files unless a failing validation proves an evaluator-caused packaging drift; if that occurs, stop and reassess scope before editing them.

- [ ] **Step 1: Run a focused requirement and DRY pass**

Compare the diff line-by-line with the approved design. Confirm every changed line supports prompt-driven evaluation or complete removal of its predecessor. Remove duplicated normative workflow from `README.md`/`EVALUATION.md`; keep the evaluator skill and prompt packet as owners and let top-level docs route to them.

Check these controlled terms and exceptions across the whole affected inventory:

```bash
rg -n 'Gate A|Gate B|approve|repair|mutation|publish|anonymous|Variant A|Variant B|retry|resume|Docker|CI/CD|custom-playlists|3050f047c4cb1a7b32237844ec7cf68a5675c957|361e1740fa164fafc590e7dc8903a87b069592cb' \
  .agents/skills/material-review-evaluation \
  evaluations/material-code-review \
  README.md EVALUATION.md \
  scripts/package_plugin.py scripts/validate_package.py scripts/tests/test_packaging.py
```

Expected: wording is coherent with the design; no surface implies Gate A can be approved before exact IDs or that Gate B may be approved.

- [ ] **Step 2: Run the complete repository validation**

Run:

```bash
git diff --check
python3 -B -m unittest discover -s scripts/tests -p 'test_*.py' -v
make validate
make package
make package-simplification
```

Expected: all commands succeed. The known platform-specific case-only-collision test may remain an explicit skip/failure only if it is unchanged and already documented by the repository; do not mask a new regression.

- [ ] **Step 3: Inspect every generated archive**

List each ZIP and confirm:

- no `.agents/skills/material-review-evaluation/` entry;
- no `evaluations/` or `.evaluation-runs/` entry;
- no deleted Python evaluator, wrapper, CLI, oracle, or schema entry;
- `.agents/plugins/marketplace.json` remains in the full plugin; and
- the standalone material-review and material-simplification layouts remain unchanged.

Run the repository validators against each produced archive using the same commands exercised by `make package` and `make package-simplification`.

- [ ] **Step 4: Verify active repositories were not changed**

Capture and compare status/HEAD for:

```text
/Users/CoveMB/Code/CoveMB/material-code-review-plugin
/Users/CoveMB/Code/CoveMB/discogs-collection
```

Expected: no evaluator-created changes. In Discogs, `custom-playlists` remains at `3050f047c4cb1a7b32237844ec7cf68a5675c957` unless the user independently advanced it during implementation; any independent advance does not alter the committed case.

- [ ] **Step 5: Perform the low-cost fresh-task discovery check**

From a fresh Codex task opened at `/private/tmp/material-review-evaluation-design.YbbJ4g/worktree`, invoke the skill with an intentionally identical pair:

```text
$material-review-evaluation base:0ca2ee9980fa20646c041c26fa5dfe03c8f22c8b candidate:0ca2ee9980fa20646c041c26fa5dfe03c8f22c8b
```

Expected: Codex discovers the repository-local skill, resolves the ref, rejects the identical pair before reviewer dispatch, and does not create or mutate a target checkout. This verifies discovery and fail-closed argument handling without running a costly evaluation.

- [ ] **Step 6: Hand off the real manual evaluation trigger**

Document this meaningful known-version smoke comparison for the maintainer:

```text
$material-review-evaluation base:cf53c81632609cced241f6b3e82ae78074beca31 candidate:0ca2ee9980fa20646c041c26fa5dfe03c8f22c8b
```

The full comparison is manual, not part of `make validate`, and may pause once for combined exact-ID Gate-A approval. A future candidate must be committed first and supplied by its exact ref; advancing or fixing the Discogs branch never changes this evaluation's frozen target commits.

- [ ] **Step 7: Final status and handoff**

Run:

```bash
git status --short
git diff --stat
git diff --check
```

Report the changed/removed files, validation evidence, skipped manual full comparison if not run, and the exact worktree. Do not stage or commit the changes without separate user authorization.
