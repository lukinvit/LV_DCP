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

In addition to the base symbol + import + role + fq scaffolding, this
parser emits :data:`RelationType.INHERITS` edges for Kotlin's single
heritage keyword (``:``), which collapses Java's ``extends`` and
``implements`` onto one syntax. Kotlin's ``delegation_specifier`` node
carries three shapes — plain ``user_type`` (interface conformance),
``constructor_invocation`` (class extension with parentheses), and
``explicit_delegation`` (``Iface by impl``). All three emit INHERITS
edges; the graph consumer treats explicit delegation as "is-a" for
impact-analysis purposes.

Call-graph edges are still out of v1 scope — matching the Go / Rust /
Java shape.
"""

from __future__ import annotations

import tree_sitter_kotlin as tskotlin
from tree_sitter import Language, Node, Parser

from libs.core.entities import Relation, RelationType, SymbolType
from libs.parsers.base import ParseResult
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

# AST node kinds that can carry a ``delegation_specifiers`` child and
# whose :class:`libs.core.entities.Symbol` is emitted by the base walker
# — so :data:`RelationType.INHERITS` ``src_ref`` resolves to an actual
# symbol fq_name in the same file.
#
# Notes on what is *not* on this list:
#
# - ``companion_object`` has no ``name`` field and is not in
#   :meth:`KotlinParser._symbol_type_map`, so emitting an INHERITS edge
#   with a companion as source would violate the
#   ``src_ref → symbol.fq_name`` invariant. Companion-object inheritance
#   is therefore silently skipped in v1.
# - ``annotation class Foo`` is still a ``class_declaration`` in the
#   Kotlin grammar (``annotation`` lives inside ``modifiers``), and
#   annotation classes cannot legally carry delegation specifiers.
#   They naturally produce zero edges — no special-case filter needed.
_TYPE_DECLARATION_NODES: frozenset[str] = frozenset(
    {
        "class_declaration",
        "object_declaration",
    }
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

    # ------------------------------------------------------------------
    # Extended parse: emit INHERITS edges for the Kotlin `:` clause
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
        """Emit INHERITS edges for every ``class`` / ``object`` heritage clause.

        Walks the CST scope-aware so nested types correctly qualify their
        edge source: ``class Outer { class Inner : Base {} }`` produces
        ``<module>.Outer.Inner INHERITS Base``, matching the nested
        symbol's ``fq_name`` in the symbol table (locked by
        ``test_kotlin_inherits_src_ref_matches_symbol_fq``).

        Covers:

        - ``class Foo : Bar()`` (class extension, parentheses mandatory)
        - ``class Foo : Trainable`` (interface conformance)
        - ``class Foo : Bar(), A, B`` (one extends + multiple implements)
        - ``interface Foo : A, B`` (interface inheritance — same ``:``)
        - ``object Foo : Base()`` (singleton with heritage)
        - ``enum class Color : Serializable`` (enum implementing interface)
        - ``data class Point(...) : Coord`` (data class heritage)
        - ``sealed class Tree : Node`` (sealed-class heritage)
        - ``class Impl(x) : Iface by x`` (explicit delegation)
        - Generics stripped: ``: Container<String>`` → ``Container``
        - Scoped paths preserved: ``: pkg.Outer.Inner`` → ``pkg.Outer.Inner``

        Companion objects (``companion_object`` node) are intentionally
        excluded — they carry no ``name`` field and the base walker does
        not emit a symbol for them, so emitting an INHERITS edge would
        violate the ``src_ref → symbol.fq_name`` invariant.
        """
        relations: list[Relation] = []
        # (node, enclosing_fq) — enclosing_fq is what the base symbol
        # walker uses as ``parent_fq_name`` for this node's children, so
        # nested types get the same fq the symbol table holds.
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
        """Return base type names for one ``class_declaration`` / ``object_declaration``.

        Kotlin wraps every heritage entry in a ``delegation_specifier``
        node. The grammar distinguishes three shapes inside it:

        - ``constructor_invocation`` — ``Base()`` (class extension)
        - ``user_type`` directly — ``Trait`` (interface conformance)
        - ``explicit_delegation`` — ``Iface by impl`` (Kotlin-specific
          "implements by delegation"; still an is-a relation for the
          graph)

        All three collapse onto a single :data:`RelationType.INHERITS`
        edge — Kotlin has no syntactic distinction between class
        extension and interface conformance, and the graph consumer
        treats delegation as inheritance for impact-analysis purposes.
        """
        bases: list[str] = []
        for child in type_node.children:
            if child.type != "delegation_specifiers":
                continue
            for specifier in child.children:
                if specifier.type != "delegation_specifier":
                    continue
                name = cls._delegation_base_name(specifier)
                if name is not None:
                    bases.append(name)
        return bases

    @classmethod
    def _delegation_base_name(cls, specifier: Node) -> str | None:
        """Extract the base type name from a ``delegation_specifier`` node.

        The single interesting child is either ``constructor_invocation``
        (class extension), ``user_type`` (plain interface conformance),
        or ``explicit_delegation`` (``: Iface by impl``). The first two
        point directly or via a nested ``user_type`` at the base type
        name; ``explicit_delegation`` holds the ``user_type`` as its
        first meaningful child, with ``by`` and the delegate identifier
        as trailing siblings.
        """
        for child in specifier.children:
            if child.type == "user_type":
                return cls._user_type_name(child)
            if child.type == "constructor_invocation":
                for grand in child.children:
                    if grand.type == "user_type":
                        return cls._user_type_name(grand)
                return None
            if child.type == "explicit_delegation":
                for grand in child.children:
                    if grand.type == "user_type":
                        return cls._user_type_name(grand)
                return None
        return None

    @classmethod
    def _user_type_name(cls, node: Node) -> str | None:
        """Flatten a Kotlin ``user_type`` node to a dotted name.

        The Kotlin grammar represents a scoped type as a flat sequence
        of ``identifier`` + ``.`` tokens under the ``user_type`` node
        (e.g. ``pkg.Outer.Inner`` → three ``identifier`` children
        interleaved with ``.`` tokens). An optional ``type_arguments``
        child carries the generic arguments and must be ignored so
        ``Container<String>`` emits ``Container``, not ``Container<…>``.

        Nested ``user_type`` children inside ``type_arguments`` are also
        ignored — the edge tracks the outer base, never the type-
        argument substitution.
        """
        parts: list[str] = []
        for child in node.children:
            if child.type == "identifier" and child.text:
                parts.append(child.text.decode("utf-8", errors="replace"))
            # Skip:
            # - ``.`` tokens (punctuation)
            # - ``type_arguments`` (strips generic parameters)
            # - anonymous inner nodes such as nested ``user_type`` inside
            #   type_arguments (unreachable in a direct child iteration)
        if not parts:
            return None
        return ".".join(parts)
