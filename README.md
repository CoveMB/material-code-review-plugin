# Material Code Review

`material-code-review` is a dual-host Codex and Claude Code plugin for evidence-gated review and bounded repair of a concrete Git change scope. It is designed for repositories where false positives, stale scope, premature edits, and recursive “one more improvement” loops are more costly than producing a long list of suggestions.

The package freezes the exact Git change set, gathers repository context, captures review candidates, independently validates them, and produces a complete kept/discarded ledger. It then stops at two mandatory user gates:

1. **Gate A — finding approval:** approve, reject, or defer each exact material finding.
2. **Gate B — repair-plan approval:** approve the exact repair steps, writable paths, validation commands, risks, retry limits, and rollback behavior.

Only after Gate B may repair work begin. Each approved finding is handled from a local checkpoint, tested, boundary-audited, and either retained or restored. Final verification is restricted to the approved findings and regressions caused by their repairs.

## Compatibility

| Host | Status | Primary package surface |
|---|---|---|
| Codex CLI / Codex plugin system | Native and locally installable | `.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json`, `skills/` |
| Codex / OpenAI Agent Skills import | Portable fallback | root `SKILL.md`, or the standalone Codex skill ZIP |
| Claude Code | Packaged compatibility surface | `.claude-plugin/`, `commands/`, `agents/` |
| Other Agent Skills hosts | Portable skill | `skills/material-code-review/` |

The Codex plugin is skill-only: it does not require an app, MCP server, OAuth connection, or external model route.

## Invocation and activation boundary

Explicit invocation with `$material-code-review` is always available and remains the most deterministic option. It supports the existing uncommitted, branch, local ref-range, and locally aligned PR scopes. If the skill is explicitly invoked for an unsupported non-Git object, it reports the mismatch and stops instead of silently becoming a document-review, output-diagnosis, architecture, or planning workflow.

Narrowly qualified implicit invocation is also supported. The prompt itself must identify concrete Git changes and ask for assessment of material defects, regressions or risks introduced or exposed by those changes, test gaps protecting changed behavior, or merge readiness. For example:

- Eligible: “Review the uncommitted changes for material regressions before merge.”
- Eligible: “Review this branch diff against `main` for merge blockers and missing tests.”
- Not eligible: “Review this plugin and prepare an improvement plan.”
- Not eligible: “Compare these two documents and diagnose why the producing skill generated the wrong artifact.”

A repository path, Git working directory, `scope:auto`, or generic words such as “review,” “issues,” “findings,” or “plan” are insufficient. `scope:auto` resolves the change scope only after activation eligibility has been established from the prompt.

The narrowed descriptions and the workflow preflight reduce false activation; they do not guarantee host or model routing. Implicit selection remains model-mediated, while explicit invocation remains deterministic.

## Package contents

- Codex plugin manifest: `.codex-plugin/plugin.json`
- Codex local marketplace: `.agents/plugins/marketplace.json`
- Codex skill interface metadata: `skills/material-code-review/agents/openai.yaml`
- Portable package entrypoint: root `SKILL.md`
- Canonical workflow: `skills/material-code-review/SKILL.md`
- Claude Code compatibility manifests: `.claude-plugin/`
- Read-only Claude specialist agents: `agents/`
- Claude compatibility command: `commands/material-review.md`
- Dependency-free controller: `skills/material-code-review/scripts/reviewctl.py`
- Cross-platform wrappers: `bin/material-reviewctl`, `.cmd`, and `.ps1`
- Machine contracts: `skills/material-code-review/schemas/`
- Stage prompts and rubrics: `skills/material-code-review/references/`
- Optional project-scoped Codex agent examples: `examples/codex-project-config/`
- Lifecycle and security tests: `skills/material-code-review/tests/`

## Requirements

- Git
- Python 3.10 or newer
- A host agent with access to the repository being reviewed
- Codex CLI with the `plugin` command when using the native local-plugin installation path

The controller uses only the Python standard library.

## Install in Codex from the full ZIP

Extract the archive first:

```bash
unzip material-code-review-plugin-1.1.0.zip -d material-code-review-plugin
```

Register the extracted directory as a local Codex marketplace:

```bash
codex plugin marketplace add ./material-code-review-plugin
codex plugin marketplace list
```

Then launch Codex, enter `/plugins`, choose the `material-code-review-local` marketplace, install **Material Code Review**, and start a new Codex session before invoking the skill. The ChatGPT desktop app can install it from the same local marketplace through its Plugins Directory.

The marketplace registration is path-based. Re-add it after moving the extracted directory.

Invoke it explicitly in a Codex prompt:

```text
Use $material-code-review to review the current uncommitted changes for material issues only. Show all kept and discarded candidates, then stop at Gate A. Do not edit code.
```

After Gate A, ask for the exact repair plan and require another stop at Gate B. Only an explicit Gate-B approval authorizes repair.

## Install as a standalone Codex / OpenAI Skill

Use the smaller archive for direct Codex skill installation:

```bash
mkdir -p "$HOME/.agents/skills/material-code-review"
unzip material-code-review-codex-skill-1.1.0.zip \
  -d "$HOME/.agents/skills/material-code-review"
```

Restart Codex if the skill does not appear immediately. The archive also works with an OpenAI Skills import surface that accepts a ZIP.

That archive opens directly to:

```text
SKILL.md
agents/openai.yaml
scripts/
schemas/
references/
examples/
tests/
```

Skills may have separate installation state across OpenAI product surfaces, so install the archive in the surface where it will be used.

## Optional project-scoped Codex reviewers

The plugin works without custom project agents. To make the candidate, validator, adjudicator, and post-fix roles explicit in a repository, copy the example `.codex` directory:

```bash
cp -R examples/codex-project-config/.codex /path/to/target-repository/
```

Review those files before copying. They define read-only specialist roles and conservative concurrency defaults. They do not grant repair permission and do not replace Gate A or Gate B.

## Claude Code compatibility

Extract the full package and load the directory through the Claude Code plugin mechanism supported by your installed version. The canonical skill is namespaced as:

```text
/material-code-review:material-code-review scope:auto depth:auto external-review:off
```

The compatibility command is:

```text
/material-code-review:material-review
```

The specialist agents are read-only review roles. The canonical skill remains the workflow authority.

## Direct controller use

Inside the repository being reviewed:

```bash
/path/to/material-code-review-plugin/bin/material-reviewctl \
  init --repo-root . --scope auto
```

Or call the script directly:

```bash
python3 /path/to/material-code-review-plugin/skills/material-code-review/scripts/reviewctl.py \
  init --repo-root . --scope auto
```

`init` prints a run ID and artifact directory. Later commands accept `--run-id` or `MATERIAL_REVIEW_RUN_ID`.

## Artifact location

By default, run artifacts are stored below:

```bash
git rev-parse --git-path material-code-review
```

This keeps source snapshots, evidence, hashes, test logs, checkpoints, and user-gate receipts outside the product diff and supports linked worktrees. A custom `--artifact-root` must be outside the worktree or inside the repository’s Git directory. Runs are bound to their originating repository and cannot be reused against another checkout.

## State machine

```text
CONTEXT_FROZEN
  -> CANDIDATES_CAPTURED
  -> ADJUDICATED
  -> Gate A: user dispositions for every kept finding
  -> FINDINGS_APPROVED
  -> PLAN_VALIDATED
  -> Gate B: approval of the exact plan hash
  -> PLAN_APPROVED
  -> FIXING (checkpoint -> edit -> approved test -> keep/restore)
  -> VERIFYING
  -> COMPLETE
     | bounded REPAIR_REQUIRED
     | PLAN_AMENDMENT_REQUIRED
     | BLOCKED
     | ABORTED
```

See `skills/material-code-review/references/workflow.md` for command and transition details.

## Main controls

- No product mutation before Gate B.
- Frozen source, diff, candidate, ledger, gate, plan, checkpoint, and fix-summary integrity checks.
- Candidate generators cannot independently validate their own claims.
- Adjudicators must account for every candidate and cannot invent findings.
- Exact source-side evidence and checked counterevidence for high-confidence candidates.
- Narrow treatment of pre-existing issues.
- A stricter materiality bar for optional improvements than for demonstrated defects.
- No semantic finding cap; concurrency and retries are bounded instead.
- Exact file-or-symlink write permissions; directory-wide repair permissions are rejected.
- Validation commands are exact Gate-B inputs and are expected to be non-mutating.
- Test-induced workspace mutation is detected and restored when automatic recovery remains safe.
- Repair attempts and post-fix repair rounds are finite.
- Final verification cannot reopen broad review or unrelated improvements.
- No push, PR, review comment, issue, ticket, or external-model egress without separate explicit authorization.

## Command execution warning

`material-reviewctl` is not an operating-system sandbox. An approved test command runs through the host shell with the current user’s permissions, and repository test code may access the filesystem, network, credentials, processes, or Git metadata available to that user. Review every command at Gate B. Put formatting, generation, migrations, and other write-capable actions in explicit repair steps—not in `run-test`. See `SECURITY.md`.

## Build and validation

Run the full validation suite:

```bash
make validate
```

Build both ZIP archives and SHA-256 sidecars:

```bash
make package
```

Core tests alone:

```bash
python3 -m unittest discover -s skills/material-code-review/tests -p 'test_*.py' -v
```

The package includes **19 lifecycle, boundary, restoration, and artifact-integrity tests**. Packaging validation also checks the Codex and Claude manifests, skill frontmatter, activation contract, referenced support files, JSON schemas, generated-file hygiene, Python compilation, the Bash wrapper, and both extracted ZIP layouts. These static checks prove that the intended activation contract is packaged and cannot silently drift; they do not prove model-selection behavior. This repository has no behavioral skill-selection evaluation harness, so implicit selection remains model-mediated. A live local install was also validated with **Codex CLI 0.144.5** in an isolated `CODEX_HOME`: marketplace registration, plugin installation, enablement, cache population, and skill-resource discovery all succeeded. The ChatGPT desktop UI was not available in this environment, so desktop-side invocation was not exercised.

## Distribution files

Packaging produces:

```text
material-code-review-plugin-1.1.0.zip
material-code-review-plugin-1.1.0.zip.sha256
material-code-review-codex-skill-1.1.0.zip
material-code-review-codex-skill-1.1.0.zip.sha256
```

The full ZIP is the recommended dual-host distribution. The standalone ZIP is the compact Agent Skills/Codex import.

## Design research

`EVALUATION.md` explains what was retained, revised, or rejected from `try-works/recursive-mode`, Every’s `ce-code-review`, and the original review prompt. `THIRD_PARTY.md` records attribution and licensing context. No upstream source files are vendored.
