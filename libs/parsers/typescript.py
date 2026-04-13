"""TypeScript / JavaScript parser built on tree-sitter.

Handles .ts, .tsx (via tree-sitter-typescript) and .js, .jsx (via
tree-sitter-javascript).  The same class serves both grammars — the
active grammar is selected by ``self.language``.
"""

from __future__ import annotations

import re

import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Node
from tree_sitter import Parser as TSParser

from libs.core.entities import Relation, RelationType, Symbol, SymbolType
from libs.parsers.base import ParseResult
from libs.parsers.treesitter_base import TreeSitterParser

_UPPER_SNAKE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


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

        if extra_symbols:
            return ParseResult(
                file_path=result.file_path,
                language=result.language,
                role=result.role,
                symbols=result.symbols + tuple(extra_symbols),
                relations=result.relations + tuple(extra_relations),
                errors=result.errors,
            )
        return result
