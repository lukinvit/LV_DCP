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

Explicit non-goals (v1):
- No `INHERITS` edges for `class Foo: Bar` / `struct User: CustomStringConvertible`
  / `protocol P: Q` — the `inheritance_specifier` node is visible in the
  AST but emitting graph edges requires a dedicated walker. Java and
  Kotlin have the same v1 gap.
- No `SAME_FILE_CALLS` edges — matches Go / Rust / Java / Kotlin shape;
  only the Python parser emits call-graph edges today.
- No separate symbols for `enum_case_declaration`. Cases live inside
  enum bodies; graph lookup for the enum still succeeds.
- No typealias extraction. Future sub-increment.
"""

from __future__ import annotations

import tree_sitter_swift as tsswift
from tree_sitter import Language, Node

from libs.core.entities import SymbolType
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
