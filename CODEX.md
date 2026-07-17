# Codex compatibility

## Compatibility decision

Version 1.1.0 is natively compatible with the current Codex plugin system and also remains portable as an Agent Skill.

The native package surfaces are:

```text
.codex-plugin/plugin.json
.agents/plugins/marketplace.json
skills/material-code-review/SKILL.md
skills/material-code-review/agents/openai.yaml
```

The plugin is skill-only. It does not require an app, MCP server, OAuth connection, external CLI, or secondary model.

The package also includes a root `SKILL.md` adapter and a standalone skill archive for Codex or other OpenAI Skills import surfaces.

## Native local installation

Extract the full ZIP:

```bash
unzip material-code-review-plugin-1.1.0.zip -d material-code-review-plugin
```

Register the extracted directory as a marketplace:

```bash
codex plugin marketplace add ./material-code-review-plugin
codex plugin marketplace list
```

Launch Codex, enter `/plugins`, choose the `material-code-review-local` marketplace, install the plugin, and start a new session. The same marketplace can be opened from the ChatGPT desktop app's Plugins Directory.

The marketplace registration is path-based. Re-add it after moving the extracted directory.

The package structure and extracted archives were validated in this build. The Codex executable and ChatGPT desktop app were not available, so the live marketplace-browser installation and invocation remain host-level checks for the installing environment.

## Standalone Skill installation

Install the smaller archive directly into the user skill directory:

```bash
mkdir -p "$HOME/.agents/skills/material-code-review"
unzip material-code-review-codex-skill-1.1.0.zip \
  -d "$HOME/.agents/skills/material-code-review"
```

Restart Codex if it does not detect the skill immediately. An OpenAI Skills surface that supports ZIP import can use the same archive.

Its archive root contains the canonical `SKILL.md`, `agents/openai.yaml`, controller, schemas, references, examples, and tests.

## Invocation

Explicit invocation:

```text
Use $material-code-review to review the current uncommitted changes for material issues only. Use scope:auto, depth:auto, and external-review:off. Do not edit code. Stop at Gate A and show every kept and discarded candidate.
```

After Gate A approval:

```text
For the Gate-A-approved findings only, draft the exact repair plan with exact writable paths, commands, risks, rollback behavior, and retry limits. Stop at Gate B without editing.
```

Only after Gate B:

```text
Apply the exact approved plan through the material-code-review controller. Keep each repair only after approved validation passes; otherwise restore its checkpoint. Then run bounded post-fix verification only for approved findings and repair-caused regressions.
```

## Codex-specific operating rules

- Read every applicable `AGENTS.md` in the target repository before analysis. A package-level `AGENTS.md` governs maintenance of this plugin itself, not arbitrary target repositories.
- Native subagents are optional and must be used only for bounded read-only candidate, validator, adjudicator, planner, or post-fix roles.
- Different persona names do not establish independent corroboration. Record the actual process/model boundary in `independence_group`.
- Keep all mutation sequential, controller-authorized, and behind Gate B.
- Never inspect a remote branch or pull-request diff using an unrelated local checkout.
- Do not continue through Gate A or Gate B based on inferred consent.
- External review is disabled by default and requires a separate source-code-egress disclosure and authorization.

## Optional project agent configuration

The examples under `examples/codex-project-config/` define read-only project-scoped roles:

- `material_candidate`
- `material_validator`
- `material_adjudicator`
- `material_postfix`

Copy them into a target repository only after review:

```bash
cp -R examples/codex-project-config/.codex /path/to/repository/
```

The plugin does not require them. They make role separation more explicit when the installed Codex version supports project-scoped custom agents.

## Direct controller use

The controller works independently of the Codex UI:

```bash
./bin/material-reviewctl init --repo-root . --scope auto
```

From the standalone skill archive:

```bash
python3 scripts/reviewctl.py init --repo-root . --scope auto
```

The controller is an integrity, state-transition, and restoration layer. It is not an operating-system sandbox. Review every Gate-B command before approval.

## Live Codex validation

The packaged local marketplace was installed successfully with Codex CLI 0.144.5 using an isolated `CODEX_HOME`. The validation covered marketplace registration, plugin discovery, installation, enabled state, cache population, and copying of the complete `material-code-review` skill resource tree. The ChatGPT desktop UI was not available, so desktop-side invocation remains untested.

## Availability caveat

A structurally valid local plugin can still be unavailable in a managed Codex workspace because installation and invocation may depend on plan, rollout, workspace policy, role, region, and supported surface. Local CLI validation demonstrates package compatibility; it does not override organizational policy.
