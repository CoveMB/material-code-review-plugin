#!/usr/bin/env python3
"""Validate the dual-host material-code-review source package and ZIP archives."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import zipfile

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 fallback: use conservative key checks below.
    tomllib = None
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.1.0"
ACTIVATION_DISCOVERY_DESCRIPTION = (
    "Evidence-gated review and bounded repair of a concrete Git change scope. "
    "Implicitly use only to assess uncommitted changes, a branch or diff, a local ref range, or a PR "
    "for material defects, regressions, test gaps protecting changed behavior, or merge readiness. "
    "Do not implicitly use for document or generated-output review, output diagnosis, general skill, "
    "plugin, or repository analysis, architecture exploration, or planning-only work."
)
ACTIVATION_SHORT_DESCRIPTION = "Material-defect review of Git changes"
ACTIVATION_PREFLIGHT_MARKERS = (
    "## Activation eligibility preflight",
    "**Implicit eligibility requires both conditions in the prompt itself.**",
    "**Context cannot create eligibility.**",
    "**Fail closed before initialization.**",
)

REQUIRED = {
    ".codex-plugin/plugin.json",
    ".agents/plugins/marketplace.json",
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    "SKILL.md",
    "AGENTS.md",
    "README.md",
    "CODEX.md",
    "LICENSE",
    "THIRD_PARTY.md",
    "CHANGELOG.md",
    "Makefile",
    "bin/material-reviewctl",
    "bin/material-reviewctl.cmd",
    "bin/material-reviewctl.ps1",
    "scripts/package_plugin.py",
    "scripts/validate_package.py",
    "skills/material-code-review/SKILL.md",
    "skills/material-code-review/agents/openai.yaml",
    "skills/material-code-review/scripts/reviewctl.py",
    "skills/material-code-review/tests/test_reviewctl.py",
    "skills/material-code-review/schemas/candidate-set.schema.json",
    "skills/material-code-review/schemas/adjudication.schema.json",
    "skills/material-code-review/schemas/fix-plan.schema.json",
    "skills/material-code-review/schemas/verification.schema.json",
    "examples/codex-project-config/.codex/config.toml",
    "examples/codex-project-config/.codex/agents/material_candidate.toml",
    "examples/codex-project-config/.codex/agents/material_validator.toml",
    "examples/codex-project-config/.codex/agents/material_adjudicator.toml",
    "examples/codex-project-config/.codex/agents/material_postfix.toml",
}

FORBIDDEN_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo"}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def parse_frontmatter(path: Path, errors: list[str]) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        fail(errors, f"{path.relative_to(ROOT)} lacks YAML frontmatter")
        return {}
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration:
        fail(errors, f"{path.relative_to(ROOT)} has unterminated YAML frontmatter")
        return {}
    result: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip("'\"")
    return result


def load_json(path: Path, errors: list[str]) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(errors, f"invalid JSON in {path.relative_to(ROOT)}: {exc}")
        return None


def load_toml(path: Path, errors: list[str]) -> dict[str, object] | None:
    text = path.read_text(encoding="utf-8")
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
        except Exception as exc:
            fail(errors, f"invalid TOML in {path.relative_to(ROOT)}: {exc}")
            return None
        return data if isinstance(data, dict) else None

    # Python 3.10 has no tomllib. This fallback is deliberately narrow: it checks
    # the required top-level keys while keeping package validation dependency-free.
    result: dict[str, object] = {}
    for key in ("name", "description", "developer_instructions", "sandbox_mode"):
        if re.search(rf"(?m)^{re.escape(key)}\s*=", text):
            result[key] = True
    if re.search(r"(?m)^\[agents\]\s*$", text):
        result["agents"] = True
    return result


def yaml_block_entries(text: str, block_name: str, key: str) -> list[str] | None:
    """Return matching scalar lines from one top-level YAML block.

    The OpenAI metadata shape used here is deliberately small. Keeping this
    parser narrow preserves the standard-library-only validation contract.
    """
    lines = text.splitlines()
    block_indices = [index for index, line in enumerate(lines) if line == f"{block_name}:"]
    if len(block_indices) != 1:
        return None
    entries: list[str] = []
    for line in lines[block_indices[0] + 1 :]:
        if line and not line[0].isspace():
            break
        if line.lstrip().startswith(f"{key}:"):
            entries.append(line)
    return entries


def validate_openai_activation_metadata(text: str, errors: list[str]) -> None:
    implicit_policy = yaml_block_entries(text, "policy", "allow_implicit_invocation")
    if implicit_policy != ["  allow_implicit_invocation: true"]:
        fail(errors, "openai.yaml must set policy.allow_implicit_invocation exactly to true")

    short_description = yaml_block_entries(text, "interface", "short_description")
    expected_short_description = f'  short_description: "{ACTIVATION_SHORT_DESCRIPTION}"'
    if short_description != [expected_short_description]:
        fail(errors, "openai.yaml short_description does not match the Git-change activation contract")


def iter_files(root: Path) -> Iterable[Path]:
    """Yield package files while excluding this checkout's own Git metadata.

    Only the root-level `.git` entry is ignored. Nested `.git` entries remain
    visible so accidental vendored repository metadata is still rejected by
    the existing forbidden-path checks.
    """
    for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        base = Path(directory)
        if base == root:
            dirnames[:] = [name for name in dirnames if name != ".git"]
            filenames[:] = [name for name in filenames if name != ".git"]

        symlink_directories = [name for name in dirnames if (base / name).is_symlink()]
        dirnames[:] = sorted(name for name in dirnames if name not in symlink_directories)

        for name in sorted(symlink_directories):
            yield base / name
        for name in sorted(filenames):
            path = base / name
            if path.is_file() or path.is_symlink():
                yield path


def check_source_package(root: Path) -> list[str]:
    errors: list[str] = []
    if sys.version_info < (3, 10):
        return ["package validation requires Python 3.10+"]
    if not root.is_dir():
        return [f"package root is not a directory: {root}"]

    actual = {path.relative_to(root).as_posix() for path in iter_files(root)}
    for rel in sorted(REQUIRED - actual):
        fail(errors, f"missing required file: {rel}")

    for rel in sorted(actual):
        path = Path(rel)
        if any(part in FORBIDDEN_PARTS for part in path.parts) or path.suffix in FORBIDDEN_SUFFIXES:
            fail(errors, f"forbidden generated/VCS path in source package: {rel}")

    codex = load_json(root / ".codex-plugin/plugin.json", errors)
    if isinstance(codex, dict):
        for key in ("name", "version", "description", "skills"):
            if key not in codex:
                fail(errors, f"Codex manifest missing {key}")
        if codex.get("name") != "material-code-review":
            fail(errors, "Codex plugin name must be material-code-review")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", str(codex.get("name", ""))):
            fail(errors, "Codex plugin name is not kebab-case")
        if codex.get("version") != VERSION:
            fail(errors, f"Codex manifest version must be {VERSION}")
        if codex.get("description") != ACTIVATION_DISCOVERY_DESCRIPTION:
            fail(errors, "Codex manifest description does not match the Git-change activation contract")
        interface = codex.get("interface")
        if not isinstance(interface, dict):
            fail(errors, "Codex manifest interface must be an object")
        else:
            if interface.get("shortDescription") != ACTIVATION_SHORT_DESCRIPTION:
                fail(errors, "Codex manifest shortDescription does not match the Git-change activation contract")
            if interface.get("longDescription") != ACTIVATION_DISCOVERY_DESCRIPTION:
                fail(errors, "Codex manifest longDescription does not match the Git-change activation contract")
        skills_value = codex.get("skills")
        if isinstance(skills_value, str):
            if not skills_value.startswith("./"):
                fail(errors, "Codex skills path must start with ./")
            skills_path = (root / skills_value).resolve()
            try:
                skills_path.relative_to(root.resolve())
            except ValueError:
                fail(errors, "Codex skills path escapes plugin root")
            if not skills_path.is_dir():
                fail(errors, "Codex skills path does not exist")
        else:
            fail(errors, "Codex skills path must be a string")

    marketplace = load_json(root / ".agents/plugins/marketplace.json", errors)
    if isinstance(marketplace, dict):
        plugins = marketplace.get("plugins")
        if not isinstance(plugins, list) or len(plugins) != 1:
            fail(errors, "Codex marketplace must expose exactly this plugin")
        else:
            entry = plugins[0]
            if not isinstance(entry, dict) or entry.get("name") != "material-code-review":
                fail(errors, "Codex marketplace plugin name mismatch")
            else:
                source = entry.get("source")
                if not isinstance(source, dict) or source.get("source") != "local" or source.get("path") != "./":
                    fail(errors, "Codex marketplace local source must be {source: local, path: ./}")
                policy = entry.get("policy")
                if not isinstance(policy, dict) or policy.get("installation") != "AVAILABLE" or policy.get("authentication") != "ON_INSTALL":
                    fail(errors, "Codex marketplace policy is incomplete")
                if not entry.get("category"):
                    fail(errors, "Codex marketplace category is required")

    claude = load_json(root / ".claude-plugin/plugin.json", errors)
    claude_market = load_json(root / ".claude-plugin/marketplace.json", errors)
    if isinstance(claude, dict):
        if claude.get("name") != "material-code-review" or claude.get("version") != VERSION:
            fail(errors, "Claude and Codex manifest identity/version differ")
        if claude.get("description") != ACTIVATION_DISCOVERY_DESCRIPTION:
            fail(errors, "Claude manifest description does not match the Git-change activation contract")
    if isinstance(claude_market, dict) and claude_market.get("version") != VERSION:
        fail(errors, f"Claude marketplace version must be {VERSION}")
    if isinstance(claude_market, dict):
        plugins = claude_market.get("plugins")
        if not isinstance(plugins, list) or len(plugins) != 1 or not isinstance(plugins[0], dict):
            fail(errors, "Claude marketplace must expose exactly this plugin")
        elif plugins[0].get("description") != ACTIVATION_DISCOVERY_DESCRIPTION:
            fail(errors, "Claude marketplace description does not match the Git-change activation contract")

    for rel in ("SKILL.md", "skills/material-code-review/SKILL.md"):
        path = root / rel
        if not path.is_file():
            continue
        frontmatter = parse_frontmatter(path, errors)
        if frontmatter.get("name") != "material-code-review":
            fail(errors, f"{rel} has wrong skill name")
        if frontmatter.get("description") != ACTIVATION_DISCOVERY_DESCRIPTION:
            fail(errors, f"{rel} description does not match the Git-change activation contract")

    openai_yaml = root / "skills/material-code-review/agents/openai.yaml"
    if openai_yaml.is_file():
        text = openai_yaml.read_text(encoding="utf-8")
        for token in ("interface:", "display_name:", "short_description:", "default_prompt:", "policy:"):
            if token not in text:
                fail(errors, f"openai.yaml missing {token}")
        validate_openai_activation_metadata(text, errors)

    custom_agents = sorted((root / "examples/codex-project-config/.codex/agents").glob("*.toml"))
    for path in custom_agents:
        data = load_toml(path, errors)
        if not isinstance(data, dict):
            continue
        for key in ("name", "description", "developer_instructions"):
            value = data.get(key)
            if tomllib is not None:
                if not isinstance(value, str) or not value.strip():
                    fail(errors, f"{path.relative_to(root)} missing non-empty {key}")
            elif not value:
                fail(errors, f"{path.relative_to(root)} missing {key}")
        if tomllib is not None and data.get("sandbox_mode") != "read-only":
            fail(errors, f"{path.relative_to(root)} must be read-only")

    project_config = root / "examples/codex-project-config/.codex/config.toml"
    if project_config.is_file():
        data = load_toml(project_config, errors)
        if isinstance(data, dict):
            agents = data.get("agents")
            if tomllib is not None:
                if not isinstance(agents, dict) or agents.get("max_depth") != 1:
                    fail(errors, "example Codex config must keep agents.max_depth=1")
            elif not agents:
                fail(errors, "example Codex config lacks [agents]")

    canonical = root / "skills/material-code-review/SKILL.md"
    if canonical.is_file():
        text = canonical.read_text(encoding="utf-8")
        refs = set(re.findall(r"`((?:references|schemas)/[A-Za-z0-9._/-]+)`", text))
        for rel in sorted(refs):
            if not (canonical.parent / rel).is_file():
                fail(errors, f"canonical skill references missing file: {rel}")
        if "No mutation before Gate B" not in text:
            fail(errors, "canonical skill no longer states the pre-Gate-B mutation invariant")
        if "No improvement recursion" not in text:
            fail(errors, "canonical skill must preserve the post-fix no-improvement-loop rule")
        for marker in ACTIVATION_PREFLIGHT_MARKERS:
            if marker not in text:
                fail(errors, f"canonical skill activation preflight missing marker: {marker}")

    for path in sorted((root / "skills/material-code-review/schemas").glob("*.json")):
        data = load_json(path, errors)
        if isinstance(data, dict):
            if data.get("type") != "object":
                fail(errors, f"{path.relative_to(root)} schema root must be object")
            if data.get("additionalProperties") is not False:
                fail(errors, f"{path.relative_to(root)} must set additionalProperties=false")

    for path in iter_files(root):
        if path.suffix.lower() == ".json" and path.is_file():
            load_json(path, errors)

    wrapper = root / "bin/material-reviewctl"
    if wrapper.exists() and os.name != "nt" and not (wrapper.stat().st_mode & stat.S_IXUSR):
        fail(errors, "bin/material-reviewctl is not executable")

    controller = root / "skills/material-code-review/scripts/reviewctl.py"
    if controller.is_file():
        text = controller.read_text(encoding="utf-8")
        if f'TOOL_VERSION = "{VERSION}"' not in text:
            fail(errors, "controller version does not match package version")
        if os.name != "nt" and not (controller.stat().st_mode & stat.S_IXUSR):
            fail(errors, "reviewctl.py is not executable")

    packager = root / "scripts/package_plugin.py"
    if packager.is_file():
        text = packager.read_text(encoding="utf-8")
        if f'VERSION = "{VERSION}"' not in text:
            fail(errors, "archive builder version does not match package version")

    readme = root / "README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        for token in (
            ".codex-plugin/plugin.json",
            "codex plugin marketplace add",
            "19 lifecycle",
            "## Invocation and activation boundary",
            "implicit selection remains model-mediated",
            "no behavioral skill-selection evaluation harness",
        ):
            if token not in text:
                fail(errors, f"README lacks required Codex or validation text: {token}")

    return errors


def check_zip(path: Path, *, standalone: bool) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        return [f"archive not found: {path}"]
    try:
        with zipfile.ZipFile(path) as zf:
            names = [name for name in zf.namelist() if not name.endswith("/")]
            if len(names) != len(set(names)):
                fail(errors, f"{path.name}: duplicate archive entries")
            for name in names:
                rel = Path(name)
                if rel.is_absolute() or ".." in rel.parts:
                    fail(errors, f"{path.name}: unsafe archive path {name}")
                if any(part in FORBIDDEN_PARTS for part in rel.parts) or rel.suffix in FORBIDDEN_SUFFIXES:
                    fail(errors, f"{path.name}: forbidden archive entry {name}")
            required = (
                {"SKILL.md", "agents/openai.yaml", "scripts/reviewctl.py", "schemas/candidate-set.schema.json"}
                if standalone
                else {
                    "SKILL.md",
                    ".codex-plugin/plugin.json",
                    ".agents/plugins/marketplace.json",
                    "skills/material-code-review/SKILL.md",
                    "skills/material-code-review/agents/openai.yaml",
                    "scripts/package_plugin.py",
                }
            )
            for rel in sorted(required - set(names)):
                fail(errors, f"{path.name}: missing archive entry {rel}")
            bad_prefixes = {name.split("/", 1)[0] for name in names if name.startswith("material-code-review-plugin/")}
            if bad_prefixes:
                fail(errors, f"{path.name}: archive has an unwanted wrapper directory")
            if not standalone and ".codex-plugin/plugin.json" in names:
                manifest = json.loads(zf.read(".codex-plugin/plugin.json"))
                if manifest.get("version") != VERSION or manifest.get("name") != "material-code-review":
                    fail(errors, f"{path.name}: embedded Codex manifest identity/version mismatch")
    except (zipfile.BadZipFile, json.JSONDecodeError) as exc:
        fail(errors, f"{path.name}: invalid ZIP or embedded JSON: {exc}")
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", default=str(ROOT), help="Source package root")
    parser.add_argument("--full-archive", action="append", default=[], help="Full package ZIP to validate")
    parser.add_argument("--standalone-archive", action="append", default=[], help="Standalone Codex skill ZIP to validate")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    errors = check_source_package(Path(args.package_root).resolve())
    for raw in args.full_archive:
        errors.extend(check_zip(Path(raw).resolve(), standalone=False))
    for raw in args.standalone_archive:
        errors.extend(check_zip(Path(raw).resolve(), standalone=True))
    if errors:
        print("[FAIL] material-code-review package validation", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"[OK] material-code-review package {VERSION} is structurally valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
