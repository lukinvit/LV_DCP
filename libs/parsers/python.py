"""Python parser using stdlib ast.

Primary parser for Python — stdlib is more accurate for Python name resolution
than tree-sitter, which shines for multi-language heuristics. We can add
tree-sitter cross-validation later if precision drops.
"""

from __future__ import annotations

import ast

from libs.core.entities import Relation, RelationType, Symbol, SymbolType
from libs.core.paths import is_test_path
from libs.parsers.base import ParseResult


class PythonParser:
    language = "python"

    def parse(self, *, file_path: str, data: bytes) -> ParseResult:
        try:
            tree = ast.parse(data, filename=file_path, type_comments=False)
        except SyntaxError as exc:
            return ParseResult(
                file_path=file_path,
                language=self.language,
                role=self._role(file_path),
                errors=(f"python parse error: {exc}",),
            )

        module_fq = self._module_fq(file_path)
        collector = _SymbolCollector(file_path=file_path, module_fq=module_fq)
        collector.visit(tree)

        relations = list(collector.relations)
        relations.extend(self._infer_tests_for(file_path, collector.relations))

        return ParseResult(
            file_path=file_path,
            language=self.language,
            role=self._role(file_path),
            symbols=tuple(collector.symbols),
            relations=tuple(relations),
        )

    @staticmethod
    def _module_fq(file_path: str) -> str:
        posix = file_path.replace("\\", "/")
        if posix.endswith(".py"):
            posix = posix[:-3]
        if posix.endswith("/__init__"):
            posix = posix[: -len("/__init__")]
        return posix.replace("/", ".")

    @staticmethod
    def _role(file_path: str) -> str:
        return "test" if is_test_path(file_path) else "source"

    # Top-level directories that indicate a project-internal import.
    _INTERNAL_PREFIXES: frozenset[str] = frozenset(
        {"src", "libs", "apps", "bot", "app", "pkg", "internal", "modules"}
    )

    @classmethod
    def _infer_tests_for(
        cls, file_path: str, relations: list[Relation]
    ) -> list[Relation]:
        """If *file_path* is a test file, promote its imports to tests_for relations."""
        if not is_test_path(file_path):
            return []

        seen: set[str] = set()
        result: list[Relation] = []
        for rel in relations:
            if rel.relation_type != RelationType.IMPORTS:
                continue
            # Derive the module path (strip symbol name for from-imports).
            # from-imports: dst_type="symbol", dst_ref="libs.core.entities.File"
            #   → module parts = ["libs", "core", "entities"]
            # plain imports: dst_type="module", dst_ref="libs.core.entities"
            #   → module parts = ["libs", "core", "entities"]
            ref = rel.dst_ref
            parts = ref.split(".")
            if rel.dst_type == "symbol" and len(parts) >= 2:
                # Last segment is the symbol name, not a module
                parts = parts[:-1]

            # Filter: only project-internal imports (first segment in known prefixes)
            if not parts or parts[0] not in cls._INTERNAL_PREFIXES:
                continue

            candidate = "/".join(parts) + ".py"
            if candidate in seen:
                continue
            seen.add(candidate)
            result.append(
                Relation(
                    src_type="file",
                    src_ref=file_path,
                    dst_type="file",
                    dst_ref=candidate,
                    relation_type=RelationType.TESTS_FOR,
                )
            )
        return result


class _SymbolCollector(ast.NodeVisitor):
    def __init__(self, *, file_path: str, module_fq: str) -> None:
        self.file_path = file_path
        self.module_fq = module_fq
        self.symbols: list[Symbol] = []
        self.relations: list[Relation] = []
        self._scope_stack: list[str] = [module_fq]
        self._current_function_fq: str | None = None

    # --- imports ------------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.relations.append(
                Relation(
                    src_type="file",
                    src_ref=self.file_path,
                    dst_type="module",
                    dst_ref=alias.name,
                    relation_type=RelationType.IMPORTS,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            dst = f"{module}.{alias.name}" if module else alias.name
            self.relations.append(
                Relation(
                    src_type="file",
                    src_ref=self.file_path,
                    dst_type="symbol",
                    dst_ref=dst,
                    relation_type=RelationType.IMPORTS,
                )
            )

    # --- definitions --------------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        fq = self._join_scope(node.name)
        self.symbols.append(
            Symbol(
                name=node.name,
                fq_name=fq,
                symbol_type=SymbolType.CLASS,
                file_path=self.file_path,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                parent_fq_name=self._scope_stack[-1],
                docstring=ast.get_docstring(node),
            )
        )
        self._add_defines(fq)
        self._add_inherits(fq, node)
        self._scope_stack.append(fq)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_func(node)

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        fq = self._join_scope(node.name)
        parent = self._scope_stack[-1]
        sym_type = (
            SymbolType.METHOD
            if len(self._scope_stack) > 1 and self._is_class_scope(parent)
            else SymbolType.FUNCTION
        )
        signature = self._render_signature(node)
        self.symbols.append(
            Symbol(
                name=node.name,
                fq_name=fq,
                symbol_type=sym_type,
                file_path=self.file_path,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                parent_fq_name=parent,
                signature=signature,
                docstring=ast.get_docstring(node),
            )
        )
        self._add_defines(fq)

        prev = self._current_function_fq
        self._current_function_fq = fq
        self._scope_stack.append(fq)
        self.generic_visit(node)
        self._scope_stack.pop()
        self._current_function_fq = prev

    def visit_Assign(self, node: ast.Assign) -> None:
        # Module-level uppercase assignments → CONSTANT
        if len(self._scope_stack) == 1:
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    fq = self._join_scope(target.id)
                    self.symbols.append(
                        Symbol(
                            name=target.id,
                            fq_name=fq,
                            symbol_type=SymbolType.CONSTANT,
                            file_path=self.file_path,
                            start_line=node.lineno,
                            end_line=node.end_lineno or node.lineno,
                            parent_fq_name=self._scope_stack[-1],
                        )
                    )
                    self._add_defines(fq)
        self.generic_visit(node)

    # --- calls --------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        if self._current_function_fq is not None:
            target = self._call_target(node.func)
            if target is not None:
                self.relations.append(
                    Relation(
                        src_type="symbol",
                        src_ref=self._current_function_fq,
                        dst_type="symbol",
                        dst_ref=target,
                        relation_type=RelationType.SAME_FILE_CALLS,
                        confidence=0.8,
                    )
                )
        self.generic_visit(node)

    # --- helpers ------------------------------------------------------------

    def _join_scope(self, name: str) -> str:
        return f"{self._scope_stack[-1]}.{name}"

    def _is_class_scope(self, fq: str) -> bool:
        return any(s.fq_name == fq and s.symbol_type == SymbolType.CLASS for s in self.symbols)

    def _add_defines(self, fq: str) -> None:
        self.relations.append(
            Relation(
                src_type="file",
                src_ref=self.file_path,
                dst_type="symbol",
                dst_ref=fq,
                relation_type=RelationType.DEFINES,
            )
        )

    @staticmethod
    def _render_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        try:
            return f"{node.name}({ast.unparse(node.args)})"
        except Exception:
            return node.name

    def _add_inherits(self, class_fq: str, node: ast.ClassDef) -> None:
        """Create INHERITS relations for each base class."""
        for base in node.bases:
            base_name = self._base_class_name(base)
            if base_name is None:
                continue
            resolved = self._resolve_name(base_name)
            self.relations.append(
                Relation(
                    src_type="symbol",
                    src_ref=class_fq,
                    dst_type="symbol",
                    dst_ref=resolved,
                    relation_type=RelationType.INHERITS,
                )
            )

    def _resolve_name(self, name: str) -> str:
        """Resolve a bare or dotted name using imports seen so far.

        If *name* was imported (``from x.y import Name``), return the
        fully-qualified ``x.y.Name``.  If it looks like a local definition
        (another class in the same file), prefix with the module fq name.
        Otherwise return the name unchanged.
        """
        # Check imports collected so far
        for rel in self.relations:
            if rel.relation_type != RelationType.IMPORTS:
                continue
            # from-imports store dst_ref as "module.Name"
            if rel.dst_ref.endswith(f".{name}") or rel.dst_ref == name:
                return rel.dst_ref
        # Check if defined in same file
        for sym in self.symbols:
            if sym.name == name:
                return sym.fq_name
        # Fallback: qualify with module prefix (best-effort)
        return f"{self.module_fq}.{name}"

    @staticmethod
    def _base_class_name(node: ast.expr) -> str | None:
        """Extract the name string from a base class AST node."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parts: list[str] = [node.attr]
            cur: ast.expr = node.value
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
                return ".".join(reversed(parts))
        return None

    @staticmethod
    def _call_target(func: ast.AST) -> str | None:
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            parts: list[str] = [func.attr]
            cur: ast.AST = func.value
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
            return ".".join(reversed(parts))
        return None
