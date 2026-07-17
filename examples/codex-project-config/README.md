# Optional Codex project configuration

The plugin works without custom agents. Codex can use its built-in `explorer`, `default`, and `worker` agents when the skill requests delegation.

To give the workflow named, read-only specialist roles, copy the `.codex/` directory from this example into the repository being reviewed:

```bash
cp -R examples/codex-project-config/.codex /path/to/target-repository/.codex
```

Project custom agents are deliberately examples rather than plugin components: Codex discovers custom-agent TOML files from `.codex/agents/` or `~/.codex/agents/`, not from a plugin's `skills/` tree.
