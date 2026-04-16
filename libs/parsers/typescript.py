"""TypeScript / JavaScript parser built on tree-sitter.

Handles .ts, .tsx (via tree-sitter-typescript) and .js, .jsx (via
tree-sitter-javascript).  The same class serves both grammars — the
active grammar is selected by ``self.language``.
"""

from __future__ import annotations

import posixpath
import re

import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Node
from tree_sitter import Parser as TSParser

from libs.core.entities import Relation, RelationType, Symbol, SymbolType
from libs.core.paths import is_test_path
from libs.parsers.base import ParseResult
from libs.parsers.treesitter_base import TreeSitterParser

_UPPER_SNAKE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_TS_EXTS = (".ts", ".tsx")
_JS_EXTS = (".js", ".jsx", ".mjs", ".cjs")
_INTERNAL_ROOTS = frozenset(
    {
        "src",
        "libs",
        "apps",
        "app",
        "pkg",
        "internal",
        "modules",
        "domains",
        "services",
        "backend",
        "frontend",
        "packages",
        "shared",
        "core",
    }
)
# FSD (Feature-Sliced Design) layer aliases that map to src/<layer>/X.
# Covers typical tsconfig paths: "@shared/*": ["src/shared/*"], etc.
_FSD_ALIASES = frozenset(
    {
        "app",
        "pages",
        "widgets",
        "features",
        "entities",
        "shared",
        "processes",
    }
)


class TypeScriptParser(TreeSitterParser):
    """Parser for TypeScript (.ts/.tsx) and JavaScript (.js/.jsx) files."""

    language: str = "typescript"

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    def _get_ts_language(self) -> Language:
        if self.language == "javascript":
            return Language(tsjavascript.language())
        return Language(tstypescript.language_typescript())

    def _symbol_type_map(self) -> dict[str, SymbolType]:
        return {
            "function_declaration": SymbolType.FUNCTION,
            "class_declaration": SymbolType.CLASS,
            "method_definition": SymbolType.METHOD,
            "interface_declaration": SymbolType.CLASS,
            "type_alias_declaration": SymbolType.CLASS,
            "enum_declaration": SymbolType.CLASS,
        }

    def _import_node_types(self) -> set[str]:
        return {"import_statement"}

    def _detect_role(self, file_path: str) -> str:
        if file_path.endswith(".d.ts"):
            return "config"
        if ".test." in file_path or ".spec." in file_path or "/__tests__/" in file_path:
            return "test"
        return "source"

    # ------------------------------------------------------------------
    # Overridable hooks
    # ------------------------------------------------------------------

    def _extract_import_ref(self, node: Node) -> tuple[str, str] | None:
        """Extract module specifier from ``import ... from 'module'``."""
        source_node = node.child_by_field_name("source")
        if source_node is not None:
            raw = (source_node.text or b"").decode("utf-8", errors="replace")
            # Strip quotes
            ref = raw.strip("\"'")
            return ("module", ref)
        # Fallback: find first string node child
        for child in node.children:
            if child.type == "string":
                raw = (child.text or b"").decode("utf-8", errors="replace")
                return ("module", raw.strip("\"'"))
        return None

    # ------------------------------------------------------------------
    # Extended parse: collect top-level UPPER_CASE constants
    # ------------------------------------------------------------------

    def parse(self, *, file_path: str, data: bytes) -> ParseResult:
        """Parse file, then sweep root for top-level UPPER_CASE constants."""
        result = super().parse(file_path=file_path, data=data)

        # Re-parse to walk root children for constants
        parser = TSParser(self._get_ts_language())
        tree = parser.parse(data)
        root = tree.root_node

        module_fq = self._module_fq(file_path)
        extra_symbols: list[Symbol] = []
        extra_relations: list[Relation] = []

        for child in root.children:
            if child.type in ("lexical_declaration", "variable_declaration"):
                for sub in child.children:
                    if sub.type == "variable_declarator":
                        name_node = sub.child_by_field_name("name")
                        if name_node is None:
                            continue
                        name = (name_node.text or b"").decode("utf-8", errors="replace")
                        if _UPPER_SNAKE_RE.match(name):
                            fq = f"{module_fq}.{name}"
                            sym = Symbol(
                                name=name,
                                fq_name=fq,
                                symbol_type=SymbolType.CONSTANT,
                                file_path=file_path,
                                start_line=sub.start_point.row + 1,
                                end_line=sub.end_point.row + 1,
                                parent_fq_name=module_fq,
                            )
                            extra_symbols.append(sym)
                            extra_relations.append(
                                Relation(
                                    src_type="file",
                                    src_ref=file_path,
                                    dst_type="symbol",
                                    dst_ref=fq,
                                    relation_type=RelationType.DEFINES,
                                )
                            )

        combined_relations = list(result.relations) + extra_relations
        combined_relations.extend(self._extract_inherits(root, module_fq))
        combined_relations.extend(self._extract_same_file_calls(root, module_fq, result.symbols))
        combined_relations.extend(self._infer_tests_for(file_path, combined_relations))

        if extra_symbols or len(combined_relations) != len(result.relations):
            return ParseResult(
                file_path=result.file_path,
                language=result.language,
                role=result.role,
                symbols=result.symbols + tuple(extra_symbols),
                relations=tuple(combined_relations),
                errors=result.errors,
            )
        return result

    # ------------------------------------------------------------------
    # Inheritance extraction (extends / implements)
    # ------------------------------------------------------------------

    @classmethod
    def _extract_inherits(cls, root: Node, module_fq: str) -> list[Relation]:
        """Walk the AST and emit INHERITS relations for class/interface heritage.

        Covers:
        - ``class Foo extends Bar`` → INHERITS(Foo, Bar)
        - ``class Foo implements A, B`` → two INHERITS edges
        - ``interface Foo extends Bar`` → INHERITS(Foo, Bar)
        """
        relations: list[Relation] = []
        stack: list[Node] = [root]
        while stack:
            node = stack.pop()
            if node.type in ("class_declaration", "interface_declaration"):
                name_node = node.child_by_field_name("name")
                if name_node is not None and name_node.text:
                    class_name = name_node.text.decode("utf-8", errors="replace")
                    class_fq = f"{module_fq}.{class_name}"
                    for base in cls._collect_heritage(node):
                        relations.append(
                            Relation(
                                src_type="symbol",
                                src_ref=class_fq,
                                dst_type="symbol",
                                dst_ref=base,
                                relation_type=RelationType.INHERITS,
                            )
                        )
            stack.extend(node.children)
        return relations

    @staticmethod
    def _collect_heritage(class_node: Node) -> list[str]:
        """Return list of base type names from a class or interface declaration."""
        bases: list[str] = []
        for child in class_node.children:
            # class: class_heritage { extends_clause, implements_clause }
            if child.type == "class_heritage":
                for sub in child.children:
                    if sub.type in ("extends_clause", "implements_clause"):
                        bases.extend(_flatten_type_names(sub))
            # interface: extends_type_clause directly
            elif child.type == "extends_type_clause":
                bases.extend(_flatten_type_names(child))
        return bases

    # ------------------------------------------------------------------
    # Same-file call graph (function → function within the same file)
    # ------------------------------------------------------------------

    _FUNCTION_NODE_TYPES = frozenset(
        {
            "function_declaration",
            "method_definition",
            "arrow_function",
            "function_expression",
            "generator_function_declaration",
        }
    )

    @classmethod
    def _extract_same_file_calls(
        cls,
        root: Node,
        module_fq: str,
        symbols: tuple[Symbol, ...],
    ) -> list[Relation]:
        """Emit SAME_FILE_CALLS edges for call_expression nodes inside functions.

        Recursively tracks the current enclosing function's fq_name:
        - function_declaration / method_definition use symbol start-line match
        - arrow_function / function_expression infer name from parent
          variable_declarator (`const foo = () => …`) or property definition
        Top-level calls (outside any function) are ignored.
        """
        symbols_by_start_line = {sym.start_line: sym for sym in symbols}
        relations: list[Relation] = []

        def walk(node: Node, enclosing: str | None) -> None:
            current = enclosing
            if node.type in cls._FUNCTION_NODE_TYPES:
                derived = cls._derive_function_fq(node, module_fq, symbols_by_start_line)
                if derived is not None:
                    current = derived
            elif node.type == "call_expression" and enclosing is not None:
                callee = cls._call_target_name(node)
                if callee is not None:
                    relations.append(
                        Relation(
                            src_type="symbol",
                            src_ref=enclosing,
                            dst_type="symbol",
                            dst_ref=f"{module_fq}.{callee}",
                            relation_type=RelationType.SAME_FILE_CALLS,
                            confidence=0.8,
                        )
                    )
            for child in node.children:
                walk(child, current)

        walk(root, None)
        return relations

    @staticmethod
    def _derive_function_fq(
        fn_node: Node,
        module_fq: str,
        symbols_by_start_line: dict[int, Symbol],
    ) -> str | None:
        """Derive a fully-qualified name for a function-like node."""
        sym = symbols_by_start_line.get(fn_node.start_point.row + 1)
        if sym is not None:
            return sym.fq_name
        # Arrow / anonymous function — try to recover name from parent.
        parent = fn_node.parent
        if parent is None:
            return None
        if parent.type == "variable_declarator":
            name_node = parent.child_by_field_name("name")
            if name_node is not None and name_node.text:
                return f"{module_fq}.{name_node.text.decode('utf-8', errors='replace')}"
        if parent.type in ("pair", "property_signature", "public_field_definition"):
            key = parent.child_by_field_name("name") or parent.child_by_field_name("key")
            if key is not None and key.text:
                return f"{module_fq}.{key.text.decode('utf-8', errors='replace')}"
        return None

    @staticmethod
    def _call_target_name(call_node: Node) -> str | None:
        """Resolve a callee name from a call_expression.

        Handles:
        - plain identifier:          foo() → "foo"
        - this.method():             this.foo() → "foo"
        - object.method():           obj.foo() → "obj.foo"
        - dotted chains:             a.b.c() → "a.b.c"
        Returns None for more complex callees (computed, parenthesised, etc.).
        """
        fn = call_node.child_by_field_name("function")
        if fn is None:
            return None
        if fn.type == "identifier" and fn.text:
            return fn.text.decode("utf-8", errors="replace")
        if fn.type != "member_expression":
            return None
        obj = fn.child_by_field_name("object")
        prop = fn.child_by_field_name("property")
        if prop is None or not prop.text:
            return None
        prop_name = prop.text.decode("utf-8", errors="replace")
        if obj is None or not obj.text or obj.type == "this":
            return prop_name
        obj_text = obj.text.decode("utf-8", errors="replace")
        return f"{obj_text}.{prop_name}"

    # ------------------------------------------------------------------
    # tests_for inference (TS/JS) — ported from PythonParser with
    # module-specifier resolution (relative, @/ alias, rooted paths)
    # ------------------------------------------------------------------

    @classmethod
    def _infer_tests_for(cls, file_path: str, relations: list[Relation]) -> list[Relation]:
        """If *file_path* is a test file, promote its imports to tests_for relations."""
        if not is_test_path(file_path):
            return []
        exts = _JS_EXTS if file_path.endswith(_JS_EXTS) else _TS_EXTS
        seen: set[str] = set()
        result: list[Relation] = []
        src_dir = posixpath.dirname(file_path)
        for rel in relations:
            if rel.relation_type != RelationType.IMPORTS:
                continue
            for candidate in cls._resolve_specifier(src_dir, rel.dst_ref, exts):
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

    @staticmethod
    def _resolve_specifier(src_dir: str, specifier: str, exts: tuple[str, ...]) -> list[str]:
        """Return candidate file paths for a TS/JS import specifier.

        Handles:
        - Relative:    ``./foo``, ``../foo`` — resolve against src_dir
        - Alias:       ``@/foo`` — tsconfig-style, map to ``src/foo``
        - Rooted:      ``src/lib/foo``, ``libs/x`` — keep as-is
        - External:    ``react``, ``@playwright/test`` — skip (returns [])

        Generates one candidate per extension in *exts* unless the specifier
        already has a valid extension.
        """
        if specifier.startswith("./") or specifier.startswith("../"):
            resolved = posixpath.normpath(posixpath.join(src_dir or ".", specifier))
        elif specifier.startswith("@/"):
            resolved = "src/" + specifier[2:]
        elif specifier.startswith("@") and "/" in specifier:
            # FSD layer alias? "@shared/lib/foo" → "src/shared/lib/foo"
            # Reject npm scoped packages: "@playwright/test", "@testing-library/react"
            layer, _, rest = specifier[1:].partition("/")
            if layer in _FSD_ALIASES:
                resolved = f"src/{layer}/{rest}"
            else:
                return []
        elif specifier.split("/", 1)[0] in _INTERNAL_ROOTS:
            resolved = specifier
        else:
            return []
        if resolved.endswith(exts) or resolved.endswith(_JS_EXTS):
            return [resolved]
        return [resolved + ext for ext in exts]


def _flatten_type_names(node: Node) -> list[str]:
    """Collect all type identifiers under *node* (extends/implements clause)."""
    names: list[str] = []
    stack: list[Node] = list(node.children)
    while stack:
        cur = stack.pop()
        if cur.type in ("type_identifier", "identifier") and cur.text:
            names.append(cur.text.decode("utf-8", errors="replace"))
            continue
        # member_expression like `ns.Base` — take full text
        if cur.type == "member_expression" and cur.text:
            names.append(cur.text.decode("utf-8", errors="replace"))
            continue
        stack.extend(cur.children)
    return names
