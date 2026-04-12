"""Rust parser built on tree-sitter-rust."""

from __future__ import annotations

import tree_sitter_rust as tsrust
from tree_sitter import Language, Node

from libs.core.entities import SymbolType
from libs.parsers.treesitter_base import TreeSitterParser


class RustParser(TreeSitterParser):
    """Parser for Rust (.rs) files."""

    language: str = "rust"

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    def _get_ts_language(self) -> Language:
        return Language(tsrust.language())

    def _symbol_type_map(self) -> dict[str, SymbolType]:
        return {
            "function_item": SymbolType.FUNCTION,
            "struct_item": SymbolType.CLASS,
            "enum_item": SymbolType.CLASS,
            "trait_item": SymbolType.CLASS,
            "const_item": SymbolType.CONSTANT,
            "static_item": SymbolType.CONSTANT,
            "mod_item": SymbolType.MODULE,
        }

    def _import_node_types(self) -> set[str]:
        return {"use_declaration"}

    def _detect_role(self, file_path: str) -> str:
        posix = file_path.replace("\\", "/")
        if posix.endswith("_test.rs") or "/tests/" in posix or posix.startswith("tests/"):
            return "test"
        return "source"

    # ------------------------------------------------------------------
    # Overridable hooks
    # ------------------------------------------------------------------

    def _extract_import_ref(self, node: Node) -> tuple[str, str] | None:
        """Extract use path from ``use std::collections::HashMap;``."""
        raw = (node.text or b"").decode("utf-8", errors="replace")
        # Strip "use " prefix and trailing ";"
        ref = raw.strip()
        if ref.startswith("use "):
            ref = ref[4:]
        ref = ref.rstrip(";").strip()
        if ref:
            return ("module", ref)
        return None

    @staticmethod
    def _module_fq(file_path: str) -> str:
        """Rust: strip .rs, strip src/ prefix, collapse mod."""
        posix = file_path.replace("\\", "/")
        if posix.endswith(".rs"):
            posix = posix[: -len(".rs")]
        if posix.endswith("/mod"):
            posix = posix[: -len("/mod")]
        # Strip src/ prefix
        if posix.startswith("src/"):
            posix = posix[len("src/") :]
        return posix.replace("/", ".")
