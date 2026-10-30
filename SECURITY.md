# Security model

## Trust boundary

`material-reviewctl` is a local state and evidence controller, not a sandbox. It validates hashes, IDs, transitions, exact repository-relative paths, checkpoints, and approved command identities. It cannot make arbitrary repository code safe to execute.

## Trusted skill code

The skill instructions, controller, adapters, and imported helpers are executable trust inputs: artifact hashes cannot protect code that has already run. Install and load them only from a trusted location outside the repository worktree being reviewed. Never execute a project-local `.agents/skills/` copy or a source checkout within that worktree; the reviewed branch can modify those files before Gate A or Gate B. Resolve symlinks when checking locations, and ensure the host selected the intended external copy rather than a duplicate project-local skill. If the selected source is in-worktree, ambiguous, or cannot be verified, stop before repository inspection or controller invocation. Project-local skill files may be reviewed as data, but must not be loaded as executable workflow instructions.

This boundary protects against changes made on the reviewed branch; it does not authenticate a compromised global installation, host, or user account. Keep the external installation trusted and do not treat a checksum stored alongside the package as independent authentication.

A Gate-B-approved test command runs through the host shell with the current user's permissions. Such a command—or code executed by that command—may access the filesystem, network, credentials, processes, or Git metadata available to that user. Review every command before Gate B. Prefer focused, deterministic, non-mutating checks. Formatting, code generation, migrations, fixture updates, and other write-capable operations belong in explicit repair steps and approved path boundaries, not in `run-test`.

The tool detects workspace, index, branch, and HEAD mutation caused by tests. Ordinary file/index mutations are restored when a valid checkpoint permits it. A command that changes HEAD/branch, tampers with checkpoint artifacts, or attacks the host can exceed automatic recovery; the run then fails closed and requires human recovery.

## External review

The plugin does not contact external models or services itself. The skill requires explicit disclosure and user authorization before a host routes code to an external model or CLI. Host telemetry and the primary model provider remain governed by the host's own policies.

## Artifact integrity

Run artifacts default to `git rev-parse --git-path material-code-review`, outside the product worktree. Scope, candidate, ledger, gate, plan, checkpoint, fix-summary, and verification artifacts are hash-bound where they become authorization inputs. These hashes detect accidental or unsophisticated local tampering; they are not signatures against an attacker with the same filesystem permissions.

## Human review required

Do not treat green local tests as sufficient approval for authentication/authorization, secrets, privacy, payment, public or cross-service contracts, schema/data migrations, distributed systems, concurrency, destructive operations, generated/ignored assets, submodules, sparse checkouts, custom Git filters, or platform-specific behavior. Use domain owners and production-safe validation.

## Reporting

Report vulnerabilities privately to the package maintainer before public disclosure. Do not include secrets, proprietary source, or exploitable production details in a public report.

## Host permissions

Host sandboxing, tool approvals, internet access, and workspace-managed plugin controls are separate from this controller. Installing a skill does not grant trust to repository commands. A tool approval does not supply Gate A, Gate B, or separate publication/source-egress authority; workflow approval also cannot override a host restriction.

Verify each worker's effective permissions before read-only delegation, including write-capable shell commands and tools. OpenCode v2 custom subagents use their own configured permissions; the parent's permission to launch a child does not make that child read-only. Antigravity documents inherited safety scopes alongside surface-specific tool and execution controls; inheritance alone does not establish a read-only reviewer. Use a verified restricted native worker or the canonical sequential/degraded fallback. [OpenCode agents](https://opencode.ai/v2/docs/agents), [OpenCode permissions](https://opencode.ai/v2/docs/permissions), [Antigravity subagents](https://antigravity.google/docs/subagents)

The root `agents/` files target Claude Code, and `agents/openai.yaml` is Codex interface metadata. Neither is a portable permission configuration for OpenCode or Antigravity. This package does not establish worker model identity or provider separation; different role names are not independent corroboration.
