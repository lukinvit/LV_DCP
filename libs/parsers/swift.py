"""Swift parser built on tree-sitter-swift.

Third shipped increment of Phase 10, following Java (v0.8.20) and Kotlin
(v0.8.21). Reuses the `TreeSitterParser` hook-method shape — grammar binding,
symbol-type map, role detection, module FQ derivation — established by the
JVM pair.

Design notes for v1:

- `class_declaration` is one AST node kind that covers `class`, `struct`,
  `actor`, `enum`, AND `extension Foo { ... }`. The node's `name` field is
  the type identifier in all cases — including extensions, where the name
  is the *extended* type (`extension User: P` has `name = b"User"`). For
  v1 we let the base walker emit a CLASS symbol for every such node; the
  apparent "duplicate" for extensions is semantically correct: the graph
  now answers "where is this type touched?" across the primary declaration
  and every file that extends it, and methods inside each extension land
  with `parent_fq_name = <module>.<ExtendedType>`, which correctly ties
  the members to the type they extend.

- `protocol_declaration` is a distinct node kind with a `name` field.
  Swift protocols are interface-like and map to `SymbolType.CLASS` for
  graph purposes (matches Kotlin `interface`'s mapping to CLASS).

- `init_declaration` → METHOD. The node's `name` is the literal string
  `"init"`. Multiple `init`s (designated + convenience) therefore emit
  multiple METHOD symbols all named `"init"` — reflecting that Swift
  classes really do have multiple initializers and the graph should
  record them all.

- `property_declaration` → VARIABLE. Covers `var`, `let`, `static let`,
  `static var`. Static / class / const properties map to VARIABLE
  uniformly (parity with Java `static final` → VARIABLE and Kotlin
  `const val` → VARIABLE); promoting them requires inspecting modifier
  children at parse time and is deferred as a deliberate v1 scope limit.

- `typealias_declaration` and `deinit_declaration` are intentionally
  **not** in the symbol-type map for v1. Type aliases would need a
  separate SymbolType decision (they're type-level names but not
  types); `deinit` has no name and is effectively an anonymous
  destructor. Both are natural future sub-increments.

- `import Foundation`, `import class Foundation.NSData`,
  `import struct Foundation.URL`, `import func Swift.print` all share
  the same grammar shape: `import_declaration` with an `identifier`
  child holding the full module path (the kind-keyword like `class` /
  `struct` / `func` appears as a sibling before the identifier). The
  extractor walks children for the first `identifier` and emits the
  full path as `dst_ref`, `dst_type="module"`. Scoped symbol imports
  therefore surface as their full path (e.g. `Foundation.NSData`) —
  matches the Java v1 decision to surface `java.util.Arrays.asList`
  for static imports rather than trimming to the module.

- Role detection accepts both SPM layout (`Tests/<Target>Tests/` —
  strictly capitalized per the SPM convention) and the broader
  `/tests/` / `/test/` directory fragments used across the codebase's
  other parsers, plus the filename fallbacks `*Tests.swift` /
  `*Test.swift` / `Test*.swift`.

- Module FQ derivation understands SPM: `Sources/<Target>/...` and
  `Tests/<Target>/...` are stripped along with the target-name segment,
  so `Sources/MyLib/Utils/Parser.swift` derives `Utils.Parser`. Nested
  multi-package layouts (`modules/foo/Sources/MyLib/Parser.swift`)
  work because the search looks for the `Sources/` / `Tests/` marker
  anywhere in the path, not just at the start — parity with Java's
  handling of nested Gradle `modules/foo/src/main/java/...`.

In addition to the base symbol + import + role + fq scaffolding, this
parser emits :data:`RelationType.INHERITS` edges for Swift's single
heritage colon (``:``), which unifies class inheritance, protocol
conformance, enum raw-value types, actor conformance, and extension
conformance under one syntactic shape. Unlike Java (`super_interfaces`
wrapper) and Kotlin (`delegation_specifiers` wrapper), Swift places
each `inheritance_specifier` as a *direct* sibling of the type name
inside `class_declaration` / `protocol_declaration`, separated by
`,` tokens. The extractor walks those direct children to collect the
heritage list, skipping unrelated siblings such as `type_parameters`
(generic parameters on the source) and `type_constraints` (the `where`
clause — its nested `user_type` children are not inheritance edges
and must not leak). Extensions flow through the same path: the base
walker emits a CLASS symbol named after the *extended* type, so the
heritage edge for `extension User: Equatable` correctly surfaces as
`<module>.User INHERITS Equatable` — answering "does this file add a
conformance to User?" without any extension-specific special case.

Call-graph edges are still out of v1 scope — matching the Go / Rust /
Java / Kotlin shape.

Explicit non-goals (v1):
- No `SAME_FILE_CALLS` edges — matches Go / Rust / Java / Kotlin shape;
  only the Python parser emits call-graph edges today.
- No separate symbols for `enum_case_declaration`. Cases live inside
  enum bodies; graph lookup for the enum still succeeds.
- No typealias extraction. Future sub-increment.
"""

from __future__ import annotations

import tree_sitter_swift as tsswift
from tree_sitter import Language, Node, Parser

from libs.core.entities import Relation, RelationType, SymbolType
from libs.parsers.base import ParseResult
from libs.parsers.treesitter_base import TreeSitterParser

# SPM source roots to strip in `_module_fq`. Non-SPM layouts (Xcode, bare
# files) fall through the stripping logic unchanged.
_SWIFT_SOURCE_ROOT_KEYS: tuple[str, ...] = ("Sources/", "Tests/")

# Test-dir fragments for role detection. The SPM-capitalized `/Tests/`
# anchors first; lowercase `/tests/` / `/test/` catch the broader Unix
# test-dir conventions seen elsewhere. Path-start cases are handled
# separately (startswith check) to avoid false positives from a
# substring match on `Tests/` inside a longer directory name.
_SWIFT_TEST_DIR_FRAGMENTS: tuple[str, ...] = (
    "/Tests/",
    "/tests/",
    "/Test/",
    "/test/",
)

_SWIFT_TEST_DIR_PREFIXES: tuple[str, ...] = ("Tests/", "tests/", "Test/", "test/")

# AST node kinds whose heritage clause emits :data:`RelationType.INHERITS`
# edges and whose :class:`libs.core.entities.Symbol` is produced by the base
# walker — so the edge's ``src_ref`` resolves to an actual symbol fq_name
# in the same file.
#
# Notes on what is *not* on this list:
#
# - `typealias_declaration` and `associatedtype_declaration` are distinct
#   node kinds that can carry a `= Type` or `: P` clause respectively; they
#   are not in :meth:`SwiftParser._symbol_type_map`, so emitting INHERITS
#   with them as source would violate the ``src_ref → symbol.fq_name``
#   invariant. Future sub-increment.
# - `enum_case_declaration` does not carry heritage and has no symbol.
_TYPE_DECLARATION_NODES: frozenset[str] = frozenset(
    {
        "class_declaration",
        "protocol_declaration",
    }
)


class SwiftParser(TreeSitterParser):
    """Tree-sitter parser for Swift source files.

    Scope covers Swift Package Manager and Xcode project layouts. Recognises
    class / struct / actor / enum / extension / protocol declarations as
    `CLASS` symbols, regular and initializer functions as `METHOD`, and
    stored / computed / static properties as `VARIABLE`. See module
    docstring for the rationale behind each mapping and the v1 non-goals.
    """

    language: str = "swift"

    def _get_ts_language(self) -> Language:
        return Language(tsswift.language())

    def _symbol_type_map(self) -> dict[str, SymbolType]:
        return {
            "class_declaration": SymbolType.CLASS,
            "protocol_declaration": SymbolType.CLASS,
            "function_declaration": SymbolType.METHOD,
            "init_declaration": SymbolType.METHOD,
            # Protocol bodies use distinct grammar node kinds for their
            # requirements — `func draw()` inside `protocol Drawable` is a
            # `protocol_function_declaration`, not `function_declaration`.
            # Surfacing them as METHOD matches the in-class case for
            # graph purposes (protocol methods are part of the protocol's
            # API contract and should be findable by name).
            "protocol_function_declaration": SymbolType.METHOD,
            "property_declaration": SymbolType.VARIABLE,
        }

    def _import_node_types(self) -> set[str]:
        return {"import_declaration"}

    def _detect_role(self, file_path: str) -> str:
        posix = file_path.replace("\\", "/")
        if any(fragment in posix for fragment in _SWIFT_TEST_DIR_FRAGMENTS):
            return "test"
        if posix.startswith(_SWIFT_TEST_DIR_PREFIXES):
            return "test"
        basename = posix.rsplit("/", 1)[-1]
        stem = basename[:-6] if basename.endswith(".swift") else basename
        if stem.endswith(("Tests", "Test")) or stem.startswith("Test"):
            return "test"
        return "source"

    def _extract_import_ref(self, node: Node) -> tuple[str, str] | None:
        # `import Foundation` and `import class Foundation.NSData` both
        # surface the full module path inside an `identifier` child
        # (the kind keyword `class` / `struct` / `func` appears as a
        # sibling before the identifier). Reading the first identifier
        # text therefore naturally yields `Foundation` for a plain import
        # and `Foundation.NSData` / `Swift.print` for scoped imports.
        for child in node.children:
            if child.type == "identifier" and child.text:
                return ("module", child.text.decode("utf-8", errors="replace"))
        return None

    @staticmethod
    def _module_fq(file_path: str) -> str:
        posix = file_path.replace("\\", "/")
        if posix.endswith(".swift"):
            posix = posix[:-6]
        # SPM: strip `Sources/<Target>/` or `Tests/<Target>/` — the marker
        # is matched anywhere in the path (supports nested multi-package
        # layouts), and the immediately following segment (the target
        # name) is also stripped so that `Sources/MyLib/Utils/Parser`
        # derives `Utils.Parser` rather than `MyLib.Utils.Parser`.
        for key in _SWIFT_SOURCE_ROOT_KEYS:
            idx = posix.find(f"/{key}")
            if idx >= 0:
                cursor = idx + 1 + len(key)
            elif posix.startswith(key):
                cursor = len(key)
            else:
                continue
            tail = posix[cursor:]
            slash = tail.find("/")
            posix = tail[slash + 1 :] if slash >= 0 else tail
            break
        return posix.replace("/", ".")

    # ------------------------------------------------------------------
    # Extended parse: emit INHERITS edges for the Swift `:` heritage clause
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
        """Emit INHERITS edges for every Swift heritage clause.

        Walks the CST scope-aware so nested types correctly qualify their
        edge source: ``class Outer { class Inner: Base {} }`` produces
        ``<module>.Outer.Inner INHERITS Base``, matching the nested
        symbol's ``fq_name`` in the symbol table (locked by
        ``test_inherits_src_ref_matches_symbol_fq``).

        Covers:

        - ``class Dog: Animal`` (class inheritance)
        - ``class Cat: Animal, Feline, Cuddly`` (class + protocol conformance)
        - ``struct User: CustomStringConvertible`` (struct protocol conformance)
        - ``protocol P: Q, R`` (protocol-to-protocol composition)
        - ``enum Color: Int, Serializable`` (raw-value type + protocol)
        - ``actor Counter: Sendable`` (actor conformance)
        - ``extension User: Equatable, Hashable`` (extension adds conformances —
          edge source is the *extended* type, which is the CLASS symbol the
          base walker emits for the extension)
        - Generics stripped: ``: Container<String>`` → ``Container``
        - Scoped paths preserved: ``: pkg.Deep<T>`` → ``pkg.Deep``
        - Where-clause ignored: ``class Foo<T>: Base where T: Hashable`` emits
          only ``Foo INHERITS Base``, never ``Foo INHERITS Hashable``.
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
        """Return base type names for one `class_declaration` / `protocol_declaration`.

        Unlike Java (`super_interfaces` wrapper) and Kotlin
        (`delegation_specifiers` wrapper), Swift places each
        `inheritance_specifier` node as a **direct** sibling of the
        type name — so we iterate ``type_node.children`` directly and
        pick out the specifier kind. Non-heritage siblings such as
        `type_parameters` (generic parameters on the source),
        `type_constraints` (`where` clauses), the `class_body` /
        `enum_class_body` / `protocol_body`, and the `:` / `,`
        punctuation tokens are all skipped by the type-filter.
        """
        bases: list[str] = []
        for child in type_node.children:
            if child.type != "inheritance_specifier":
                continue
            name = cls._inheritance_specifier_name(child)
            if name is not None:
                bases.append(name)
        return bases

    @classmethod
    def _inheritance_specifier_name(cls, specifier: Node) -> str | None:
        """Extract the base type name from one `inheritance_specifier` node.

        The specifier wraps a single `user_type` child that carries the
        dotted path (and optional generic arguments). Delegate to
        :meth:`_user_type_name` to flatten it; ignore stray tokens.
        """
        for child in specifier.children:
            if child.type == "user_type":
                return cls._user_type_name(child)
        return None

    @classmethod
    def _user_type_name(cls, node: Node) -> str | None:
        """Flatten a Swift ``user_type`` node to a dotted name.

        The Swift grammar represents a scoped type as a flat sequence
        of ``type_identifier`` + ``.`` tokens under the ``user_type``
        node (e.g. ``pkg.Outer.Inner`` → three ``type_identifier``
        children interleaved with ``.`` tokens). An optional
        ``type_arguments`` child carries the generic arguments and
        must be ignored so ``Container<String>`` emits ``Container``,
        not ``Container<…>`` nor ``String``.

        Nested ``user_type`` children inside ``type_arguments`` are
        also implicitly ignored because only direct ``type_identifier``
        siblings are collected — the edge tracks the outer base, never
        the type-argument substitution.

        (The Kotlin parser uses ``identifier`` here; Swift's grammar
        names the same role ``type_identifier``.)
        """
        parts: list[str] = []
        for child in node.children:
            if child.type == "type_identifier" and child.text:
                parts.append(child.text.decode("utf-8", errors="replace"))
            # Skip:
            # - ``.`` tokens (punctuation)
            # - ``type_arguments`` (strips generic parameters)
            # - nested ``user_type`` under ``type_arguments`` (unreachable
            #   via a direct-child iteration that only collects
            #   ``type_identifier``)
        if not parts:
            return None
        return ".".join(parts)
