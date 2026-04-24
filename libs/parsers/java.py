"""Java parser built on tree-sitter-java.

Covers the core Java 21 surface: classes, interfaces, enums, records,
annotation types, methods, constructors, and field declarations. Imports
are emitted as ``module`` refs for static + on-demand (wildcard) variants
alike. Role detection honours Maven/Gradle layout (``src/test/java/``)
and the common JUnit naming conventions (``*Test.java``, ``*Tests.java``,
``Test*.java``). Module fq names strip the ``src/main/java/`` or
``src/test/java/`` source root when present so the Java package path is
what lands on the symbol's ``parent_fq_name``.

This parser aims for parity with :class:`libs.parsers.rust.RustParser` —
symbol + import + role + fq. Richer features (call graph, inheritance
edges, ``tests_for`` inference) can be added incrementally following the
TypeScript parser's lead.
"""

from __future__ import annotations

import tree_sitter_java as tsjava
from tree_sitter import Language, Node

from libs.core.entities import SymbolType
from libs.parsers.treesitter_base import TreeSitterParser

_MAVEN_SOURCE_ROOTS: tuple[str, ...] = (
    "src/main/java/",
    "src/test/java/",
)
_JUNIT_TEST_DIR_FRAGMENTS: tuple[str, ...] = (
    "/src/test/java/",
    "src/test/java/",
    "/tests/",
    "tests/",
    "/test/",
    "test/",
)


class JavaParser(TreeSitterParser):
    """Parser for Java (``.java``) files."""

    language: str = "java"

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    def _get_ts_language(self) -> Language:
        return Language(tsjava.language())

    def _symbol_type_map(self) -> dict[str, SymbolType]:
        return {
            "class_declaration": SymbolType.CLASS,
            "interface_declaration": SymbolType.CLASS,
            "enum_declaration": SymbolType.CLASS,
            "annotation_type_declaration": SymbolType.CLASS,
            "record_declaration": SymbolType.CLASS,
            "method_declaration": SymbolType.METHOD,
            "constructor_declaration": SymbolType.METHOD,
            "field_declaration": SymbolType.VARIABLE,
        }

    def _import_node_types(self) -> set[str]:
        return {"import_declaration"}

    def _detect_role(self, file_path: str) -> str:
        """Classify a Java file as ``test`` or ``source``.

        Rules (first match wins):

        1. Maven/Gradle layout: path contains ``src/test/java/``.
        2. Path contains ``/test/`` or ``/tests/`` (also accepts a
           leading, non-anchored match at the repo root).
        3. Filename ends with ``Test.java`` or ``Tests.java``
           (JUnit 4/5 convention).
        4. Filename starts with ``Test`` (JUnit 3 convention —
           less common but still encountered in legacy codebases).
        """
        posix = file_path.replace("\\", "/")
        if any(fragment in posix for fragment in _JUNIT_TEST_DIR_FRAGMENTS):
            return "test"
        basename = posix.rsplit("/", 1)[-1]
        if basename.endswith(("Test.java", "Tests.java")) or basename.startswith("Test"):
            return "test"
        return "source"

    # ------------------------------------------------------------------
    # Overridable hooks
    # ------------------------------------------------------------------

    def _extract_name(self, node: Node) -> str | None:
        """Extract the symbol name from a Java definition node.

        Most Java definition nodes expose the name via
        ``child_by_field_name("name")`` (the default path), but
        ``field_declaration`` is structurally different — the
        identifier lives inside a ``variable_declarator`` child:

        .. code-block:: text

            field_declaration
              modifiers
              type_identifier
              variable_declarator
                identifier  ← this is the name
                …initializer…

        For multi-declarator fields like ``private int a, b;`` we
        surface the **first** declarator's name only. Emitting one
        symbol per declarator would require restructuring the
        base walker's one-node-one-symbol assumption; keeping the
        first-only behaviour is consistent with how the base class
        handles every other language and covers the common case
        (single-variable field declarations).
        """
        if node.type == "field_declaration":
            for child in node.children:
                if child.type == "variable_declarator":
                    name_node = child.child_by_field_name("name")
                    if name_node is not None and name_node.text:
                        return name_node.text.decode("utf-8", errors="replace")
            return None
        return super()._extract_name(node)

    def _extract_import_ref(self, node: Node) -> tuple[str, str] | None:
        """Extract the import path from an ``import_declaration``.

        Java import forms:

        .. code-block:: java

            import java.util.List;            // scoped_identifier
            import java.util.*;               // scoped_identifier + asterisk
            import static java.util.Arrays.asList;  // static + scoped_identifier
            import static java.util.Arrays.*; // static + scoped + asterisk
            import java.lang.Object;          // unusual, but valid

        For every form we emit the fully-qualified path as a ``module``
        ref — the same convention Go uses for ``import "net/http"`` and
        Rust uses for ``use std::collections::HashMap``. Wildcard
        imports land as the package path without the ``.*`` suffix
        since the downstream graph consumer only cares about the
        module, not whether every symbol is pulled.
        """
        for child in node.children:
            if child.type == "scoped_identifier" and child.text:
                return ("module", child.text.decode("utf-8", errors="replace"))
            # Single-segment import (rare) — ``import Foo;``
            if child.type == "identifier" and child.text:
                return ("module", child.text.decode("utf-8", errors="replace"))
        return None

    @staticmethod
    def _module_fq(file_path: str) -> str:
        """Derive a dotted module fq_name for a Java source file.

        Strips:

        1. The ``.java`` extension.
        2. The Maven/Gradle source root prefix (``src/main/java/`` or
           ``src/test/java/``) **if present** — the dotted path that
           remains matches the Java package declaration on the file's
           first line, which is the natural identifier for the
           containing module.

        Non-Maven layouts (a bare ``MyClass.java`` or ``pkg/Foo.java``)
        are handled by the fallback: strip extension, swap ``/`` for
        ``.``, unchanged root.
        """
        posix = file_path.replace("\\", "/")
        if posix.endswith(".java"):
            posix = posix[: -len(".java")]
        for root in _MAVEN_SOURCE_ROOTS:
            idx = posix.find(root)
            if idx >= 0:
                posix = posix[idx + len(root) :]
                break
        return posix.replace("/", ".")
