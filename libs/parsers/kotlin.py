"""Kotlin parser built on tree-sitter-kotlin.

Kotlin shares the JVM ecosystem with Java and follows the same
``TreeSitterParser`` hook-method shape as the Go, Rust and Java
parsers. The extension from Java is mostly a different grammar,
a broader set of type-declaration nodes (Kotlin's ``object`` /
``companion object`` / ``sealed class`` / ``data class`` all share
the ``class_declaration`` / ``object_declaration`` AST shape),
and different source-root conventions (Gradle ``src/main/kotlin/``,
Android ``src/androidTest/kotlin/``, plus Java-style
``src/main/java/`` in mixed projects).

The v1 scope intentionally mirrors the Java parser's v1 scope:

- ``class_declaration`` collapses regular / interface / enum /
  annotation / data / sealed classes onto ``SymbolType.CLASS``.
- ``object_declaration`` (named singleton objects) also maps to
  ``CLASS`` — the runtime shape is a class with a single instance.
- ``companion_object`` has no name field in the grammar, so the
  base walker naturally skips it for symbol emission but still
  recurses into its body. Children (methods / properties on the
  companion) end up with ``parent_fq_name`` pointing at the
  enclosing class, which matches Kotlin semantics — companion
  members are addressed as ``EnclosingClass.member``.
- ``function_declaration`` → ``METHOD`` (consistent with Java,
  Go, Rust — top-level functions are classified as methods for
  graph purposes; the Python parser's dedicated ``FUNCTION``
  kind is not generalized).
- ``property_declaration`` → ``VARIABLE`` (``val`` and ``var``
  both land here; ``const val`` at file / companion scope is
  also ``VARIABLE`` for v1, matching the Java v1 handling of
  ``static final``).

Inheritance / delegation (``delegation_specifiers`` under a class
or object declaration — the Kotlin equivalent of Java's
``extends`` / ``implements``) is not yet surfaced as graph
edges. Call-graph edges are likewise out of v1 scope — both
follow the Go / Rust / Java shape.
"""

from __future__ import annotations

import tree_sitter_kotlin as tskotlin
from tree_sitter import Language, Node

from libs.core.entities import SymbolType
from libs.parsers.treesitter_base import TreeSitterParser

# Source roots recognised by ``_module_fq``.  The first match in the path
# wins — so a nested Gradle layout like
# ``modules/foo/src/main/kotlin/com/example/Bar.kt`` resolves to
# ``com.example.Bar`` regardless of the outer directory structure.
_KOTLIN_SOURCE_ROOTS: tuple[str, ...] = (
    "src/main/kotlin/",
    "src/test/kotlin/",
    "src/androidTest/kotlin/",
    # Kotlin projects frequently mix Java sources — the resulting
    # package fq_name shape is identical, so strip those roots too.
    "src/main/java/",
    "src/test/java/",
    "src/androidTest/java/",
)

# Directory fragments that flip a file's role to ``test``.  Checked
# before the filename fallback so the directory wins over the filename
# (a ``Helper.kt`` under ``src/test/kotlin/`` is still a test file).
_KOTLIN_TEST_DIR_FRAGMENTS: tuple[str, ...] = (
    "/src/test/kotlin/",
    "src/test/kotlin/",
    "/src/androidTest/kotlin/",
    "src/androidTest/kotlin/",
    "/src/test/java/",
    "src/test/java/",
    "/src/androidTest/java/",
    "src/androidTest/java/",
    "/tests/",
    "tests/",
    "/test/",
    "test/",
)


class KotlinParser(TreeSitterParser):
    """Kotlin parser — first non-Java JVM language on the platform."""

    language: str = "kotlin"

    def _get_ts_language(self) -> Language:
        return Language(tskotlin.language())

    def _symbol_type_map(self) -> dict[str, SymbolType]:
        return {
            "class_declaration": SymbolType.CLASS,
            "object_declaration": SymbolType.CLASS,
            "function_declaration": SymbolType.METHOD,
            "property_declaration": SymbolType.VARIABLE,
        }

    def _import_node_types(self) -> set[str]:
        return {"import"}

    def _detect_role(self, file_path: str) -> str:
        posix = file_path.replace("\\", "/")
        if any(fragment in posix for fragment in _KOTLIN_TEST_DIR_FRAGMENTS):
            return "test"
        basename = posix.rsplit("/", 1)[-1]
        # Strip ``.kt`` / ``.kts`` before running prefix/suffix checks so
        # ``ConfigTest.kt`` matches the ``*Test`` suffix rule without
        # tripping on the extension.
        stem = basename
        for ext in (".kts", ".kt"):
            if stem.endswith(ext):
                stem = stem[: -len(ext)]
                break
        if stem.endswith(("Test", "Tests")) or stem.startswith("Test"):
            return "test"
        return "source"

    def _extract_name(self, node: Node) -> str | None:
        # ``property_declaration`` doesn't carry a ``name`` field in the
        # Kotlin grammar — the name lives inside a ``variable_declaration``
        # child. Walk the first such child and read its identifier.
        if node.type == "property_declaration":
            for child in node.children:
                if child.type == "variable_declaration":
                    for grand in child.children:
                        if grand.type == "identifier" and grand.text:
                            return grand.text.decode("utf-8", errors="replace")
                    return None
            return None
        return super()._extract_name(node)

    def _extract_import_ref(self, node: Node) -> tuple[str, str] | None:
        # The Kotlin grammar places the fully-qualified module path as a
        # single ``qualified_identifier`` child of the ``import`` node.
        # Wildcard imports (``import foo.bar.*``) place ``.`` and ``*`` as
        # sibling tokens after the qualified_identifier — so reading the
        # qualified_identifier text naturally yields the package path
        # without the wildcard suffix, matching the Java wildcard rule.
        # Alias imports (``import foo.Bar as Baz``) surface ``as`` and
        # ``identifier`` as trailing siblings — also ignored, the graph
        # tracks the original module path.
        for child in node.children:
            if child.type == "qualified_identifier" and child.text:
                return ("module", child.text.decode("utf-8", errors="replace"))
            if child.type == "identifier" and child.text:
                return ("module", child.text.decode("utf-8", errors="replace"))
        return None

    @staticmethod
    def _module_fq(file_path: str) -> str:
        posix = file_path.replace("\\", "/")
        for ext in (".kts", ".kt"):
            if posix.endswith(ext):
                posix = posix[: -len(ext)]
                break
        for root in _KOTLIN_SOURCE_ROOTS:
            idx = posix.find(root)
            if idx >= 0:
                posix = posix[idx + len(root) :]
                break
        return posix.replace("/", ".")
