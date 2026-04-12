"""Go parser built on tree-sitter-go."""

from __future__ import annotations

import tree_sitter_go as tsgo
from tree_sitter import Language, Node

from libs.core.entities import SymbolType
from libs.parsers.treesitter_base import TreeSitterParser


class GoParser(TreeSitterParser):
    """Parser for Go (.go) files."""

    language: str = "go"

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    def _get_ts_language(self) -> Language:
        return Language(tsgo.language())

    def _symbol_type_map(self) -> dict[str, SymbolType]:
        return {
            "function_declaration": SymbolType.FUNCTION,
            "method_declaration": SymbolType.METHOD,
            "type_spec": SymbolType.CLASS,
            "const_spec": SymbolType.CONSTANT,
        }

    def _import_node_types(self) -> set[str]:
        return {"import_spec"}

    def _detect_role(self, file_path: str) -> str:
        if file_path.endswith("_test.go"):
            return "test"
        return "source"

    # ------------------------------------------------------------------
    # Overridable hooks
    # ------------------------------------------------------------------

    def _extract_import_ref(self, node: Node) -> tuple[str, str] | None:
        """Extract import path from an import_spec node.

        Go import_spec contains an interpreted_string_literal like
        ``"fmt"`` or ``"net/http"``.
        """
        for child in node.children:
            if child.type == "interpreted_string_literal":
                raw = (child.text or b"").decode("utf-8", errors="replace")
                return ("module", raw.strip('"'))
        # Sometimes the path child is named "path"
        path_node = node.child_by_field_name("path")
        if path_node is not None:
            raw = (path_node.text or b"").decode("utf-8", errors="replace")
            return ("module", raw.strip('"'))
        return None

    @staticmethod
    def _module_fq(file_path: str) -> str:
        """Go: strip .go extension, use dots."""
        posix = file_path.replace("\\", "/")
        if posix.endswith(".go"):
            posix = posix[: -len(".go")]
        return posix.replace("/", ".")
