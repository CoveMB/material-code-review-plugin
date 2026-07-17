# Security model

## Trust boundary

`material-reviewctl` is a local state and evidence controller, not a sandbox. It validates hashes, IDs, transitions, exact repository-relative paths, checkpoints, and approved command identities. It cannot make arbitrary repository code safe to execute.

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

## Codex and host permissions

Codex sandboxing, tool approval policy, internet access, and workspace-managed plugin controls are separate from this controller. Installing the plugin does not grant trust to arbitrary repository commands. Keep Codex approvals restrictive until Gate B presents the exact commands and paths. A host-native subagent inherits the host's data and execution boundaries; this package does not prove its model identity or provider separation.
