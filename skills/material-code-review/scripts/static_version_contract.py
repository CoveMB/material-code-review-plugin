#!/usr/bin/env python3
"""Static, side-effect-free validation of module version declarations."""

from __future__ import annotations

import ast


def validate_static_version_declaration(
    source: str | bytes,
    constant_name: str,
    expected_value: str,
    inspected_path: str,
) -> str | None:
    """Certify exactly one immediate module-body literal string assignment."""
    if isinstance(source, bytes):
        try:
            source = source.decode("utf-8")
        except UnicodeDecodeError:
            return f"{inspected_path}: {constant_name} declaration has invalid UTF-8"
    try:
        tree = ast.parse(source, filename=inspected_path)
    except SyntaxError:
        return f"{inspected_path}: {constant_name} declaration has invalid syntax"

    direct_assignments = {
        id(statement)
        for statement in tree.body
        if isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id == constant_name
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    }

    class BindingVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.bindings: list[bool] = []
            self.direct_values: list[str] = []
            self.recording_module_bindings = True

        def record_binding(self, *, direct: bool = False) -> None:
            if self.recording_module_bindings:
                self.bindings.append(direct)

        def record_target(self, target: ast.AST, *, direct: bool = False) -> None:
            if isinstance(target, ast.Name):
                if target.id == constant_name and isinstance(
                    target.ctx, (ast.Store, ast.Del)
                ):
                    self.record_binding(direct=direct)
            elif isinstance(target, (ast.Tuple, ast.List)):
                for element in target.elts:
                    self.record_target(element)
            elif isinstance(target, ast.Starred):
                self.record_target(target.value)

        def visit_Assign(self, node: ast.Assign) -> None:
            direct = id(node) in direct_assignments
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
            self.recording_module_bindings = self.class_body_declares_global(node.body)
            try:
                for statement in node.body:
                    self.visit(statement)
            finally:
                self.recording_module_bindings = previous_recording

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
