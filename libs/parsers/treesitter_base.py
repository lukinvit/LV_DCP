"""Abstract base class for tree-sitter based parsers.

Concrete parsers (TypeScript, Go, Rust, etc.) subclass TreeSitterParser
and implement a small set of language-specific hooks.  The base class owns
the tree walk, symbol/relation extraction, and the FileParser protocol.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from tree_sitter import Language, Node, Parser

from libs.core.entities import Relation, RelationType, Symbol, SymbolType
from libs.parsers.base import ParseResult


class TreeSitterParser(ABC):
    """Shared tree-sitter walker for all non-Python languages.

    Subclass contract (must implement):
        _get_ts_language()   -> tree_sitter.Language
        _symbol_type_map()   -> dict mapping node type str to SymbolType
        _import_node_types() -> set of node type strings that represent imports
        _detect_role()       -> file role string ("source", "test", ...)

    Overridable hooks (have default implementations):
        _extract_name()        -> symbol name from a definition node
        _extract_docstring()   -> docstring text or None
        _extract_signature()   -> signature string or None
        _extract_import_ref()  -> (dst_type, dst_ref) for an import node
    """

    language: str  # must be set by subclass

    # ------------------------------------------------------------------
    # Abstract methods
    # ------------------------------------------------------------------

    @abstractmethod
    def _get_ts_language(self) -> Language:
        """Return the tree-sitter Language object for this parser."""

    @abstractmethod
    def _symbol_type_map(self) -> dict[str, SymbolType]:
        """Map tree-sitter node type strings to SymbolType.

        Example for Python:
            {"function_definition": SymbolType.FUNCTION,
             "class_definition": SymbolType.CLASS}
        """

    @abstractmethod
    def _import_node_types(self) -> set[str]:
        """Return the set of node types that represent import statements.

        Example for Python: {"import_statement", "import_from_statement"}
        """

    @abstractmethod
    def _detect_role(self, file_path: str) -> str:
        """Return role string for the file ("source", "test", "config", ...)."""

    # ------------------------------------------------------------------
    # Overridable hooks (sensible defaults)
    # ------------------------------------------------------------------

    def _extract_name(self, node: Node) -> str | None:
        """Extract the symbol name from a definition node.

        Default: look for ``child_by_field_name("name")`` which works for
        most tree-sitter grammars (Python, TS, Go, Rust, ...).
        """
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return (name_node.text or b"").decode("utf-8", errors="replace")
        return None

    def _extract_docstring(self, node: Node) -> str | None:
        """Extract docstring from a definition node.

        Default: look for a ``string`` as first statement in the body block.
        Works for Python; other languages should override.
        """
        body = node.child_by_field_name("body")
        if body is None:
            return None
        for child in body.children:
            if child.type == "expression_statement":
                for sub in child.children:
                    if sub.type == "string":
                        raw = (sub.text or b"").decode("utf-8", errors="replace")
                        return raw.strip("\"'").strip()
            # Stop at first non-expression child
            if child.is_named:
                break
        return None

    def _extract_signature(self, node: Node) -> str | None:
        """Extract signature from a function/method node.

        Default: ``name(parameters_text)``.
        """
        name = self._extract_name(node)
        if name is None:
            return None
        params_node = node.child_by_field_name("parameters")
        if params_node is not None:
            params_text = (params_node.text or b"").decode("utf-8", errors="replace")
            return f"{name}{params_text}"
        return name

    def _extract_import_ref(self, node: Node) -> tuple[str, str] | None:
        """Extract (dst_type, dst_ref) from an import node.

        Must be overridden per language. Returns None if extraction fails.
        Default handles Python import_statement / import_from_statement.
        """
        if node.type == "import_statement":
            # import X, Y => take first dotted_name
            for child in node.children:
                if child.type == "dotted_name":
                    ref = (child.text or b"").decode("utf-8", errors="replace")
                    return ("module", ref)
        elif node.type == "import_from_statement":
            # from X import Y
            module_parts: list[str] = []
            names: list[str] = []
            phase = "from"
            for child in node.children:
                if child.type in ("from", "import"):
                    phase = child.type
                    continue
                if phase == "from" and child.type == "dotted_name":
                    module_parts.append((child.text or b"").decode("utf-8", errors="replace"))
                elif phase == "import" and child.type == "dotted_name":
                    names.append((child.text or b"").decode("utf-8", errors="replace"))
            module = ".".join(module_parts) if module_parts else ""
            if names:
                ref = f"{module}.{names[0]}" if module else names[0]
                return ("symbol", ref)
            elif module:
                return ("module", module)
        return None

    # ------------------------------------------------------------------
    # Public API (implements FileParser protocol)
    # ------------------------------------------------------------------

    def parse(self, *, file_path: str, data: bytes) -> ParseResult:
        """Parse a file and return structured symbols + relations."""
        parser = Parser(self._get_ts_language())
        tree = parser.parse(data)
        root = tree.root_node

        errors: list[str] = []
        if root.has_error:
            errors.append("tree-sitter reported parse errors")

        module_fq = self._module_fq(file_path)
        sym_map = self._symbol_type_map()
        import_types = self._import_node_types()

        symbols: list[Symbol] = []
        relations: list[Relation] = []

        self._walk(
            node=root,
            file_path=file_path,
            module_fq=module_fq,
            scope_stack=[module_fq],
            sym_map=sym_map,
            import_types=import_types,
            symbols=symbols,
            relations=relations,
        )

        return ParseResult(
            file_path=file_path,
            language=self.language,
            role=self._detect_role(file_path),
            symbols=tuple(symbols),
            relations=tuple(relations),
            errors=tuple(errors),
        )

    # ------------------------------------------------------------------
    # Module fq_name derivation
    # ------------------------------------------------------------------

    @staticmethod
    def _module_fq(file_path: str) -> str:
        """Derive a dotted fq_name from a POSIX file path.

        Examples:
            libs/parsers/python.py  -> libs.parsers.python
            libs/core/__init__.py   -> libs.core
            src/index.ts            -> src.index
        """
        posix = file_path.replace("\\", "/")
        # Strip known extensions
        for ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"):
            if posix.endswith(ext):
                posix = posix[: -len(ext)]
                break
        # Collapse __init__ / mod (Rust)
        if posix.endswith("/__init__"):
            posix = posix[: -len("/__init__")]
        if posix.endswith("/mod"):
            posix = posix[: -len("/mod")]
        return posix.replace("/", ".")

    # ------------------------------------------------------------------
    # Tree walk
    # ------------------------------------------------------------------

    def _walk(  # noqa: PLR0913
        self,
        *,
        node: Node,
        file_path: str,
        module_fq: str,
        scope_stack: list[str],
        sym_map: dict[str, SymbolType],
        import_types: set[str],
        symbols: list[Symbol],
        relations: list[Relation],
    ) -> None:
        """Iteratively walk the CST, extracting symbols and relations.

        Uses an explicit work stack to avoid RecursionError on deeply
        nested ASTs (e.g., large Go files with 500+ nested expressions).
        """
        # Each item: (node, scope_depth) — scope_depth tracks how deep
        # in scope_stack we were when this node was enqueued.
        work: list[tuple[Node, int]] = [(node, len(scope_stack))]

        while work:
            cur, expected_depth = work.pop()

            # Pop scopes that were pushed by sibling subtrees already processed.
            while len(scope_stack) > expected_depth:
                scope_stack.pop()

            # --- handle imports (leaf — no children enqueued) ---
            if cur.type in import_types:
                ref = self._extract_import_ref(cur)
                if ref is not None:
                    dst_type, dst_ref = ref
                    relations.append(
                        Relation(
                            src_type="file",
                            src_ref=file_path,
                            dst_type=dst_type,
                            dst_ref=dst_ref,
                            relation_type=RelationType.IMPORTS,
                        )
                    )
                continue

            # --- handle symbol definitions ---
            pushed_scope = False
            if cur.type in sym_map:
                sym_type = sym_map[cur.type]
                name = self._extract_name(cur)
                if name is not None:
                    parent_fq = scope_stack[-1]
                    fq_name = f"{parent_fq}.{name}"

                    actual_type = sym_type
                    if sym_type == SymbolType.FUNCTION and self._is_class_scope(
                        parent_fq, symbols
                    ):
                        actual_type = SymbolType.METHOD

                    docstring = self._extract_docstring(cur)
                    signature = (
                        self._extract_signature(cur)
                        if actual_type in (SymbolType.FUNCTION, SymbolType.METHOD)
                        else None
                    )

                    symbols.append(
                        Symbol(
                            name=name,
                            fq_name=fq_name,
                            symbol_type=actual_type,
                            file_path=file_path,
                            start_line=cur.start_point.row + 1,
                            end_line=cur.end_point.row + 1,
                            parent_fq_name=parent_fq,
                            signature=signature,
                            docstring=docstring,
                        )
                    )

                    relations.append(
                        Relation(
                            src_type="file",
                            src_ref=file_path,
                            dst_type="symbol",
                            dst_ref=fq_name,
                            relation_type=RelationType.DEFINES,
                        )
                    )

                    scope_stack.append(fq_name)
                    pushed_scope = True

            # Enqueue children in reverse order (so first child is processed first).
            child_depth = len(scope_stack)
            for child in reversed(cur.children):
                work.append((child, child_depth))

            # If we pushed a scope, the children will inherit it via child_depth.
            # After all children are processed, the scope will be popped by the
            # depth-tracking logic at the top of the loop.
            if pushed_scope:
                pass  # No explicit pop — handled by expected_depth check above.

    @staticmethod
    def _is_class_scope(fq: str, symbols: list[Symbol]) -> bool:
        """Check whether fq refers to a class symbol already collected."""
        return any(s.fq_name == fq and s.symbol_type == SymbolType.CLASS for s in symbols)
