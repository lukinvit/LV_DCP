"""Go parser built on tree-sitter-go."""

from __future__ import annotations

import tree_sitter_go as tsgo
from tree_sitter import Language, Node

from libs.core.entities import Relation, RelationType, SymbolType
from libs.core.paths import is_test_path
from libs.parsers.base import ParseResult
from libs.parsers.treesitter_base import TreeSitterParser

# Go import path prefixes that indicate a hosted module URL whose first three
# segments (host + owner + repo) should be stripped to get a project-relative path.
_HOSTED_MODULE_PREFIXES = (
    "github.com/",
    "gitlab.com/",
    "bitbucket.org/",
    "codeberg.org/",
)
_GO_PROJECT_ROOTS = frozenset(
    {
        "services",
        "pkg",
        "internal",
        "cmd",
        "apps",
        "domains",
        "core",
        "modules",
        "gen",
    }
)


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

    # ------------------------------------------------------------------
    # tests_for inference
    # ------------------------------------------------------------------

    def parse(self, *, file_path: str, data: bytes) -> ParseResult:
        result = super().parse(file_path=file_path, data=data)
        inferred = self._infer_tests_for(file_path, list(result.relations))
        if not inferred:
            return result
        return ParseResult(
            file_path=result.file_path,
            language=result.language,
            role=result.role,
            symbols=result.symbols,
            relations=result.relations + tuple(inferred),
            errors=result.errors,
        )

    @classmethod
    def _infer_tests_for(cls, file_path: str, relations: list[Relation]) -> list[Relation]:
        """For a *_test.go file, promote project-internal imports to TESTS_FOR.

        Go imports a directory (one package = one dir), so we emit a
        best-effort candidate file path ``<dir>/<package_name>.go`` where
        ``package_name`` is the last segment of the resolved import path.
        External and stdlib imports are skipped.
        """
        if not is_test_path(file_path):
            return []
        seen: set[str] = set()
        result: list[Relation] = []
        for rel in relations:
            if rel.relation_type != RelationType.IMPORTS:
                continue
            candidate = cls._resolve_go_import(rel.dst_ref)
            if candidate is None or candidate in seen:
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
    def _resolve_go_import(specifier: str) -> str | None:
        """Map a Go import path to a candidate project-local ``.go`` file.

        Rules:
        - Standard library (single segment, no slash): skip
        - Hosted URL prefix (``github.com/<org>/<repo>/...``): strip the
          first three segments; accept the remainder iff it begins with a
          known project root (``services/``, ``pkg/``, ``internal/``, …)
        - Bare project-root path (``internal/foo``): accept as-is
        - Everything else (third-party single-host, ``modernc.org/sqlite``):
          skip

        Returns ``<dir>/<last_segment>.go`` — best-effort pointing at the
        primary file of the package; graph lookups ignore non-existent paths.
        """
        if "/" not in specifier:
            return None
        if specifier.startswith(_HOSTED_MODULE_PREFIXES):
            parts = specifier.split("/")
            if len(parts) <= 3:
                return None
            rest = parts[3:]
        else:
            rest = specifier.split("/")
        if not rest or rest[0] not in _GO_PROJECT_ROOTS:
            return None
        dir_path = "/".join(rest)
        return f"{dir_path}/{rest[-1]}.go"
