"""Java parser built on tree-sitter-java.

Covers the core Java 21 surface: classes, interfaces, enums, records,
annotation types, methods, constructors, and field declarations. Imports
are emitted as ``module`` refs for static + on-demand (wildcard) variants
alike. Role detection honours Maven/Gradle layout (``src/test/java/``)
and the common JUnit naming conventions (``*Test.java``, ``*Tests.java``,
``Test*.java``). Module fq names strip the ``src/main/java/`` or
``src/test/java/`` source root when present so the Java package path is
what lands on the symbol's ``parent_fq_name``.

In addition to the base symbol + import + role + fq scaffolding, this
parser emits :data:`RelationType.INHERITS` edges for ``extends`` and
``implements`` clauses (class / interface / enum / record), following
the TypeScript parser's pattern. Richer features (call graph, record
component surfacing) can be added incrementally.
"""

from __future__ import annotations

import tree_sitter_java as tsjava
from tree_sitter import Language, Node, Parser

from libs.core.entities import Relation, RelationType, SymbolType
from libs.parsers.base import ParseResult
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

# AST node kinds that can carry an ``extends`` or ``implements`` clause.
# Annotation types (``@interface``) cannot inherit, so they stay off this list.
_TYPE_DECLARATION_NODES: frozenset[str] = frozenset(
    {
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "record_declaration",
    }
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

    # ------------------------------------------------------------------
    # Extended parse: emit INHERITS edges for extends / implements clauses
    # ------------------------------------------------------------------

    def parse(self, *, file_path: str, data: bytes) -> ParseResult:
        """Parse, then supplement the base result with INHERITS edges."""
        result = super().parse(file_path=file_path, data=data)

        parser = Parser(self._get_ts_language())
        tree = parser.parse(data)
        root = tree.root_node

        module_fq = self._module_fq(file_path)
        inherits = self._extract_inherits(root, module_fq)
        if not inherits:
            return result
        return ParseResult(
            file_path=result.file_path,
            language=result.language,
            role=result.role,
            symbols=result.symbols,
            relations=result.relations + tuple(inherits),
            errors=result.errors,
        )

    @classmethod
    def _extract_inherits(cls, root: Node, module_fq: str) -> list[Relation]:
        """Emit INHERITS edges for every ``extends`` / ``implements`` clause.

        Walks the CST scope-aware so nested types correctly qualify their
        edge source: ``class Outer { class Inner extends Base {} }``
        produces ``<module>.Outer.Inner INHERITS Base`` — matching the
        nested symbol's ``fq_name`` in the symbol table.

        Covers:

        - ``class Foo extends Bar`` → 1 edge
        - ``class Foo implements A, B`` → 2 edges
        - ``class Foo extends Bar implements A`` → 2 edges
        - ``interface Foo extends A, B`` → 2 edges
        - ``enum Color implements Serializable`` → 1 edge
        - ``record Point(int x, int y) implements Coord`` → 1 edge
        - Generics: ``extends Container<String>`` → ``Container`` (arguments stripped)
        - Scoped: ``extends pkg.Outer.Inner`` → ``pkg.Outer.Inner`` (full path)

        Annotation types (``@interface``) cannot have heritage and never
        appear as sources; they are not in ``_TYPE_DECLARATION_NODES``.
        """
        relations: list[Relation] = []
        # (node, enclosing_fq) — enclosing_fq is the fq_name the walker
        # would push onto the scope stack for this node's parent in the
        # main symbol walk, so nested types get the right src_ref.
        stack: list[tuple[Node, str]] = [(root, module_fq)]
        while stack:
            node, scope = stack.pop()
            next_scope = scope
            if node.type in _TYPE_DECLARATION_NODES:
                name_node = node.child_by_field_name("name")
                if name_node is not None and name_node.text:
                    type_name = name_node.text.decode("utf-8", errors="replace")
                    type_fq = f"{scope}.{type_name}"
                    next_scope = type_fq
                    for base in cls._collect_heritage(node):
                        relations.append(
                            Relation(
                                src_type="symbol",
                                src_ref=type_fq,
                                dst_type="symbol",
                                dst_ref=base,
                                relation_type=RelationType.INHERITS,
                            )
                        )
            for child in node.children:
                stack.append((child, next_scope))
        return relations

    @classmethod
    def _collect_heritage(cls, type_node: Node) -> list[str]:
        """Return base type names for one class/interface/enum/record node.

        Handles the three Java heritage carriers:

        - ``superclass`` (class only, single type) — the ``extends`` clause
        - ``super_interfaces`` (class/enum/record) — the ``implements`` clause
        - ``extends_interfaces`` (interface) — the ``extends`` clause

        ``extends`` and ``implements`` semantics collapse onto a single
        ``INHERITS`` edge type: graph consumers treat "is-a" as one
        relation regardless of whether the source is a class or an
        interface. Distinguishing the two would require a new relation
        type in :mod:`libs.core.entities`.
        """
        bases: list[str] = []
        for child in type_node.children:
            if child.type == "superclass":
                # Single base type; skip the ``extends`` keyword token.
                for sub in child.children:
                    name = cls._heritage_type_name(sub)
                    if name is not None:
                        bases.append(name)
                        break  # class extends at most one base
            elif child.type in ("super_interfaces", "extends_interfaces"):
                for sub in child.children:
                    if sub.type == "type_list":
                        for item in sub.children:
                            name = cls._heritage_type_name(item)
                            if name is not None:
                                bases.append(name)
        return bases

    @classmethod
    def _heritage_type_name(cls, node: Node) -> str | None:
        """Extract a base type name from a heritage type node.

        - ``type_identifier`` → ``"Foo"``
        - ``scoped_type_identifier`` → ``"pkg.Outer.Inner"`` (full dotted path)
        - ``generic_type`` → strip ``type_arguments`` and recurse on the
          base node, so ``Container<String>`` becomes ``"Container"`` and
          ``pkg.Box<T>`` becomes ``"pkg.Box"``

        Other node types (keywords, punctuation, comments) return None
        so the caller can ignore them cleanly.
        """
        if node.type == "type_identifier" and node.text:
            return node.text.decode("utf-8", errors="replace")
        if node.type == "scoped_type_identifier" and node.text:
            return node.text.decode("utf-8", errors="replace")
        if node.type == "generic_type":
            for child in node.children:
                if child.type in ("type_identifier", "scoped_type_identifier"):
                    return cls._heritage_type_name(child)
        return None
