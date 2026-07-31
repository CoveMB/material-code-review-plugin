#!/usr/bin/env python3
"""Validate an extracted standalone material-code-review Agent Skill."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.3.0"
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
CONTROLLED_WORKFLOW_MARKERS = (
    "risk_assessments",
    "record-coverage",
    "material-review/candidate-set/v2",
    "user_selectable_output_paths",
    "persisted_config_semantics",
    "Missing required review coverage",
    "CONSEQUENCE_UNSUPPORTED",
    "plausibly blocker/high",
)
WORKFLOW_BLOCK_START = "Discovery order is fixed:\n\n```text\n"
WORKFLOW_BLOCK_END = "\n```"
WORKFLOW_DISCOVERY_MARKERS = (
    "init",
    "context record (manual; see references/context-checklist.md)",
    'python3 "$SKILL_DIR/scripts/reviewctl.py" check-scope --repo-root .',
    "record-coverage",
    "dispatch assigned lenses",
)
LAYOUT_NAMES = ("full-plugin", "standalone")
LAYOUT_MANIFEST_NAME = "package-layouts.json"
VALIDATOR_SOURCE = "skills/material-code-review/scripts/validate_package.py"
MANIFEST_SOURCE = "skills/material-code-review/package-layouts.json"


def normalize_layout_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"unsafe layout {label}: {value!r}")
    path = PurePosixPath(value)
    normalized = path.as_posix()
    if (
        path.is_absolute()
        or ".." in path.parts
        or normalized in {"", "."}
        or normalized != value
    ):
        raise ValueError(f"unsafe layout {label}: {value}")
    return normalized


def load_layout_contract(
    errors: list[str],
) -> tuple[str, Path, dict[str, object]] | None:
    full_root = ROOT.parents[1]
    if (
        (full_root / VALIDATOR_SOURCE).resolve() == Path(__file__).resolve()
        and (full_root / ".codex-plugin/plugin.json").is_file()
    ):
        layout_name = "full-plugin"
        package_root = full_root
        expected_validator_destination = VALIDATOR_SOURCE
        expected_manifest_destination = MANIFEST_SOURCE
    else:
        layout_name = "standalone"
        package_root = ROOT
        expected_validator_destination = "scripts/validate_package.py"
        expected_manifest_destination = LAYOUT_MANIFEST_NAME

    manifest_path = ROOT / LAYOUT_MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"missing package layout manifest: {LAYOUT_MANIFEST_NAME}")
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid package layout manifest: {exc}")
        return None
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        errors.append("package layout manifest schema_version must be 1")
        return None
    layouts = manifest.get("layouts")
    if not isinstance(layouts, dict) or set(layouts) != set(LAYOUT_NAMES):
        errors.append("package layout manifest must define full-plugin and standalone")
        return None

    normalized_layouts: dict[str, dict[str, object]] = {}
    try:
        for manifest_layout_name in LAYOUT_NAMES:
            layout = layouts[manifest_layout_name]
            if not isinstance(layout, dict):
                raise ValueError(f"layout {manifest_layout_name} must be an object")
            canonical_skill = normalize_layout_path(
                layout.get("canonical_skill"),
                f"canonical skill for {manifest_layout_name}",
            )
            mappings = layout.get("required_mappings")
            if not isinstance(mappings, list) or not mappings:
                raise ValueError(
                    f"layout {manifest_layout_name} required_mappings must be a non-empty array"
                )
            seen_sources: set[str] = set()
            seen_destinations: set[str] = set()
            normalized_mappings: list[dict[str, str]] = []
            for index, mapping in enumerate(mappings):
                if not isinstance(mapping, dict) or set(mapping) != {
                    "source",
                    "destination",
                }:
                    raise ValueError(
                        f"layout {manifest_layout_name} mapping {index} must contain source and destination"
                    )
                source = normalize_layout_path(mapping["source"], "source")
                destination = normalize_layout_path(
                    mapping["destination"], "destination"
                )
                if source in seen_sources:
                    raise ValueError(f"duplicate layout source: {source}")
                if destination in seen_destinations:
                    raise ValueError(f"duplicate layout destination: {destination}")
                seen_sources.add(source)
                seen_destinations.add(destination)
                normalized_mappings.append(
                    {"source": source, "destination": destination}
                )
            if canonical_skill not in seen_destinations:
                raise ValueError(
                    f"layout {manifest_layout_name} canonical skill is not a required destination: "
                    f"{canonical_skill}"
                )
            normalized_layouts[manifest_layout_name] = {
                "canonical_skill": canonical_skill,
                "required_mappings": normalized_mappings,
            }
    except ValueError as exc:
        errors.append(f"invalid package layout manifest: {exc}")
        return None

    layout = normalized_layouts[layout_name]
    validator_destination = next(
        (
            mapping["destination"]
            for mapping in layout["required_mappings"]
            if mapping["source"] == VALIDATOR_SOURCE
        ),
        None,
    )
    if validator_destination is None:
        errors.append(
            f"package layout {layout_name} does not map its validator to "
            f"{expected_validator_destination}"
        )
    elif validator_destination != expected_validator_destination:
        errors.append(
            f"package layout {layout_name} validator destination is "
            f"{validator_destination}; expected {expected_validator_destination}"
        )
    manifest_destination = next(
        (
            mapping["destination"]
            for mapping in layout["required_mappings"]
            if mapping["source"] == MANIFEST_SOURCE
        ),
        None,
    )
    if manifest_destination is None:
        errors.append(
            f"package layout {layout_name} does not map its manifest to "
            f"{expected_manifest_destination}"
        )
    elif manifest_destination != expected_manifest_destination:
        errors.append(
            f"package layout {layout_name} manifest destination is "
            f"{manifest_destination}; expected {expected_manifest_destination}"
        )
    return layout_name, package_root, layout


def validate_workflow_discovery_order(
    source: str | bytes,
    inspected_path: str,
) -> str | None:
    if isinstance(source, bytes):
        try:
            source = source.decode("utf-8")
        except UnicodeDecodeError:
            return f"{inspected_path}: workflow discovery order has invalid UTF-8"
    if source.count(WORKFLOW_BLOCK_START) != 1:
        return f"{inspected_path}: workflow discovery order block missing or duplicate"
    block, separator, _ = source.split(WORKFLOW_BLOCK_START, 1)[1].partition(
        WORKFLOW_BLOCK_END
    )
    if not separator:
        return f"{inspected_path}: workflow discovery order block is unterminated"
    lines = block.splitlines()
    for marker in WORKFLOW_DISCOVERY_MARKERS:
        if lines.count(marker) != 1:
            return (
                f"{inspected_path}: workflow discovery order marker missing or "
                f"duplicate: {marker}"
            )
    positions = [lines.index(marker) for marker in WORKFLOW_DISCOVERY_MARKERS]
    if positions != sorted(positions):
        return f"{inspected_path}: workflow discovery order markers out of order"
    return None


def validate_static_version_declaration(
    source: str | bytes,
    constant_name: str,
    expected_value: str,
    inspected_path: str,
) -> str | None:
    """Statically certify one direct module-scope string declaration.

    This deliberately does not model dynamic rebinding performed by later calls,
    ``exec``, ``globals()``, or import hooks; it never executes inspected source.
    """
    if isinstance(source, bytes):
        try:
            source = source.decode("utf-8")
        except UnicodeDecodeError:
            return f"{inspected_path}: {constant_name} declaration has invalid UTF-8"
    try:
        tree = ast.parse(source, filename=inspected_path)
    except SyntaxError:
        return f"{inspected_path}: {constant_name} declaration has invalid syntax"

    class BindingVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.bindings: list[bool] = []
            self.direct_values: list[str] = []
            self.recording_module_bindings = True
            self.accepting_direct_declaration = True

        def record_binding(self, *, direct: bool = False) -> None:
            if self.recording_module_bindings:
                self.bindings.append(direct)

        def record_target(self, target: ast.AST, *, direct: bool = False) -> None:
            if isinstance(target, ast.Name):
                if (
                    target.id == constant_name
                    and isinstance(target.ctx, (ast.Store, ast.Del))
                ):
                    self.record_binding(direct=direct)
            elif isinstance(target, (ast.Tuple, ast.List)):
                for element in target.elts:
                    self.record_target(element)
            elif isinstance(target, ast.Starred):
                self.record_target(target.value)

        def visit_Assign(self, node: ast.Assign) -> None:
            direct = (
                self.accepting_direct_declaration
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == constant_name
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            )
            for target in node.targets:
                self.record_target(target, direct=direct and target is node.targets[0])
            if direct:
                self.direct_values.append(node.value.value)
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            self.record_target(node.target)
            self.generic_visit(node)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            self.record_target(node.target)
            self.generic_visit(node)

        def visit_Delete(self, node: ast.Delete) -> None:
            for target in node.targets:
                self.record_target(target)
            self.generic_visit(node)

        def visit_For(self, node: ast.For) -> None:
            self.record_target(node.target)
            self.generic_visit(node)

        visit_AsyncFor = visit_For

        def visit_With(self, node: ast.With) -> None:
            for item in node.items:
                if item.optional_vars is not None:
                    self.record_target(item.optional_vars)
            self.generic_visit(node)

        visit_AsyncWith = visit_With

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                if (alias.asname or alias.name.split(".", 1)[0]) == constant_name:
                    self.record_binding()

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            for alias in node.names:
                if alias.name == "*" or (alias.asname or alias.name) == constant_name:
                    self.record_binding()

        def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
            self.record_target(node.target)
            self.generic_visit(node)

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if node.name == constant_name:
                self.record_binding()
            self.generic_visit(node)

        def visit_MatchAs(self, node: ast.MatchAs) -> None:
            if node.name == constant_name:
                self.record_binding()
            self.generic_visit(node)

        def visit_MatchStar(self, node: ast.MatchStar) -> None:
            if node.name == constant_name:
                self.record_binding()
            self.generic_visit(node)

        def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
            if node.rest == constant_name:
                self.record_binding()
            self.generic_visit(node)

        def record_definition_name(self, name: str) -> None:
            if name == constant_name:
                self.record_binding()

        def class_body_declares_global(self, statements: list[ast.stmt]) -> bool:
            class GlobalFinder(ast.NodeVisitor):
                def __init__(self) -> None:
                    self.found = False

                def visit_Global(self, node: ast.Global) -> None:
                    if constant_name in node.names:
                        self.found = True

                def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                    pass

                visit_AsyncFunctionDef = visit_FunctionDef

                def visit_ClassDef(self, node: ast.ClassDef) -> None:
                    pass

                def visit_Lambda(self, node: ast.Lambda) -> None:
                    pass

            finder = GlobalFinder()
            for statement in statements:
                finder.visit(statement)
            return finder.found

        def visit_function_expressions(
            self, node: ast.FunctionDef | ast.AsyncFunctionDef
        ) -> None:
            self.record_definition_name(node.name)
            for decorator in node.decorator_list:
                self.visit(decorator)
            arguments = node.args
            for default in (*arguments.defaults, *arguments.kw_defaults):
                if default is not None:
                    self.visit(default)
            for argument in (
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
            ):
                if argument.annotation is not None:
                    self.visit(argument.annotation)
            for argument in (arguments.vararg, arguments.kwarg):
                if argument is not None and argument.annotation is not None:
                    self.visit(argument.annotation)
            if node.returns is not None:
                self.visit(node.returns)
            for type_parameter in getattr(node, "type_params", ()):
                self.visit(type_parameter)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.visit_function_expressions(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.visit_function_expressions(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.record_definition_name(node.name)
            for decorator in node.decorator_list:
                self.visit(decorator)
            for base in node.bases:
                self.visit(base)
            for keyword in node.keywords:
                self.visit(keyword.value)
            for type_parameter in getattr(node, "type_params", ()):
                self.visit(type_parameter)
            previous_recording = self.recording_module_bindings
            previous_accepting = self.accepting_direct_declaration
            self.recording_module_bindings = self.class_body_declares_global(node.body)
            self.accepting_direct_declaration = False
            try:
                for statement in node.body:
                    self.visit(statement)
            finally:
                self.recording_module_bindings = previous_recording
                self.accepting_direct_declaration = previous_accepting

        def visit_Lambda(self, node: ast.Lambda) -> None:
            for default in (*node.args.defaults, *node.args.kw_defaults):
                if default is not None:
                    self.visit(default)

    visitor = BindingVisitor()
    visitor.visit(tree)
    if not visitor.bindings:
        return f"{inspected_path}: {constant_name} declaration is missing"
    if len(visitor.bindings) != 1:
        return f"{inspected_path}: {constant_name} declaration is duplicate/competing"
    if not visitor.bindings[0]:
        return f"{inspected_path}: {constant_name} declaration is non-direct/nonliteral"
    actual_value = visitor.direct_values[0]
    if actual_value != expected_value:
        return (
            f"{inspected_path}: {constant_name} declaration has wrong value "
            f"{actual_value!r}; expected {expected_value!r}"
        )
    return None


def parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration:
        return {}
    result: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip("'\"")
    return result


def yaml_block_entries(text: str, block_name: str, key: str) -> list[str] | None:
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


def main() -> int:
    errors: list[str] = []
    if sys.version_info < (3, 10):
        errors.append("Python 3.10+ is required")
    layout_contract = load_layout_contract(errors)
    if layout_contract is not None:
        _, package_root, layout = layout_contract
        for mapping in layout["required_mappings"]:
            destination = mapping["destination"]
            if not (package_root / destination).is_file():
                errors.append(f"missing required layout file: {destination}")
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if "__pycache__" in rel.parts or ".pytest_cache" in rel.parts or path.suffix in {".pyc", ".pyo"}:
            errors.append(f"generated file present: {rel.as_posix()}")
    skill = ROOT / "SKILL.md"
    if skill.is_file():
        text = skill.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
        if frontmatter.get("name") != "material-code-review":
            errors.append("SKILL.md frontmatter is missing or has the wrong name")
        if frontmatter.get("description") != ACTIVATION_DISCOVERY_DESCRIPTION:
            errors.append("SKILL.md description does not match the Git-change activation contract")
        for marker in ACTIVATION_PREFLIGHT_MARKERS:
            if marker not in text:
                errors.append(f"SKILL.md activation preflight missing marker: {marker}")
        for marker in CONTROLLED_WORKFLOW_MARKERS:
            if marker not in text:
                errors.append(f"SKILL.md controlled workflow marker missing: {marker}")
        for rel in sorted(set(re.findall(r"`((?:references|schemas)/[A-Za-z0-9._/-]+)`", text))):
            if not (ROOT / rel).is_file():
                errors.append(f"SKILL.md references missing file: {rel}")
    workflow = ROOT / "references/workflow.md"
    if workflow.is_file():
        workflow_error = validate_workflow_discovery_order(
            workflow.read_bytes(),
            workflow.relative_to(ROOT).as_posix(),
        )
        if workflow_error is not None:
            errors.append(workflow_error)
    controller = ROOT / "scripts/reviewctl.py"
    if controller.is_file():
        declaration_error = validate_static_version_declaration(
            controller.read_bytes(),
            "TOOL_VERSION",
            VERSION,
            controller.relative_to(ROOT).as_posix(),
        )
        if declaration_error is not None:
            errors.append(declaration_error)
        if not sys.platform.startswith("win") and not (controller.stat().st_mode & 0o100):
            errors.append("reviewctl.py is not executable")
    for path in (ROOT / "schemas").glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"invalid JSON in {path.name}: {exc}")
            continue
        if data.get("type") != "object" or data.get("additionalProperties") is not False:
            errors.append(f"schema must be object and fail closed: {path.name}")
    yaml = ROOT / "agents/openai.yaml"
    if yaml.is_file():
        text = yaml.read_text(encoding="utf-8")
        for token in ("interface:", "display_name:", "short_description:", "default_prompt:", "policy:"):
            if token not in text:
                errors.append(f"openai.yaml missing {token}")
        implicit_policy = yaml_block_entries(text, "policy", "allow_implicit_invocation")
        if implicit_policy != ["  allow_implicit_invocation: true"]:
            errors.append("openai.yaml must set policy.allow_implicit_invocation exactly to true")
        short_description = yaml_block_entries(text, "interface", "short_description")
        expected_short_description = f'  short_description: "{ACTIVATION_SHORT_DESCRIPTION}"'
        if short_description != [expected_short_description]:
            errors.append("openai.yaml short_description does not match the Git-change activation contract")
    if errors:
        print("[FAIL] standalone material-code-review skill validation", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"[OK] standalone material-code-review skill {VERSION} is structurally valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
