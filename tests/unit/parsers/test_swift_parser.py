"""Tests for the Swift parser (v0.8.22)."""

from __future__ import annotations

from libs.core.entities import RelationType, SymbolType
from libs.parsers.base import ParseResult
from libs.parsers.registry import detect_language, get_parser
from libs.parsers.swift import SwiftParser

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SWIFT_CODE = b"""\
import Foundation
import UIKit
import class Foundation.NSData
import struct Foundation.URL
import func Swift.print

public struct User {
    let id: Int
    var name: String

    init(id: Int, name: String) {
        self.id = id
        self.name = name
    }

    func greet() -> String {
        return "Hello, \\(name)"
    }
}

public class ViewController: UIViewController {
    override func viewDidLoad() {
        super.viewDidLoad()
    }

    private func handleTap() {
        print("tapped")
    }
}

public enum Status {
    case active
    case inactive(reason: String)

    func label() -> String {
        switch self {
        case .active: return "on"
        case .inactive: return "off"
        }
    }
}

public protocol Drawable {
    func draw()
    var size: Int { get }
}

extension User: CustomStringConvertible {
    public var description: String { return name }

    func prettyPrint() -> String {
        return description.uppercased()
    }
}

public actor Counter {
    var value: Int = 0

    func increment() {
        value += 1
    }
}

let MAX_SIZE: Int = 1024
public let greeting = "hi"
static let SHARED_INSTANCE = Counter()

public func topLevelFunction(x: Int) -> Int {
    return x * 2
}
"""

MINIMAL_SWIFT = b"""\
func main() {
    print("hello")
}
"""

EMPTY_SWIFT = b""

TEST_SWIFT = b"""\
import XCTest

class UserTests: XCTestCase {
    func testGreet() {
        XCTAssertEqual(1, 1)
    }
}
"""


# ---------------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------------


class TestSymbolExtraction:
    def _parse(
        self, code: bytes = SWIFT_CODE, path: str = "Sources/MyLib/Foo.swift"
    ) -> ParseResult:
        return SwiftParser().parse(file_path=path, data=code)

    def test_extracts_struct_as_class(self) -> None:
        result = self._parse()
        user = [s for s in result.symbols if s.name == "User" and s.symbol_type == SymbolType.CLASS]
        assert len(user) >= 1  # one for the struct, plus one for each extension

    def test_extracts_class(self) -> None:
        result = self._parse()
        vc = [s for s in result.symbols if s.name == "ViewController"]
        assert len(vc) == 1
        assert vc[0].symbol_type == SymbolType.CLASS

    def test_extracts_enum_as_class(self) -> None:
        result = self._parse()
        status = [s for s in result.symbols if s.name == "Status"]
        assert len(status) == 1
        assert status[0].symbol_type == SymbolType.CLASS

    def test_extracts_protocol_as_class(self) -> None:
        result = self._parse()
        drawable = [s for s in result.symbols if s.name == "Drawable"]
        assert len(drawable) == 1
        assert drawable[0].symbol_type == SymbolType.CLASS

    def test_extracts_actor_as_class(self) -> None:
        result = self._parse()
        counter = [
            s for s in result.symbols if s.name == "Counter" and s.symbol_type == SymbolType.CLASS
        ]
        assert len(counter) == 1

    def test_extension_emits_duplicate_class_symbol(self) -> None:
        """Extensions compile as distinct AST nodes with the extended type's name.

        v1 design: accept the apparent duplicate. It's semantically correct —
        the graph now records every file that touches `User`, and methods
        inside each extension correctly associate with the extended type
        via `parent_fq_name`.
        """
        result = self._parse()
        user_classes = [
            s for s in result.symbols if s.name == "User" and s.symbol_type == SymbolType.CLASS
        ]
        # One from `struct User`, one from `extension User: ...`
        assert len(user_classes) == 2

    def test_extracts_top_level_function_as_method(self) -> None:
        result = self._parse()
        tlf = [s for s in result.symbols if s.name == "topLevelFunction"]
        assert len(tlf) == 1
        assert tlf[0].symbol_type == SymbolType.METHOD

    def test_extracts_method_inside_class(self) -> None:
        result = self._parse()
        vdl = [s for s in result.symbols if s.name == "viewDidLoad"]
        assert len(vdl) == 1
        assert vdl[0].symbol_type == SymbolType.METHOD
        parent = vdl[0].parent_fq_name
        assert parent is not None
        assert parent.endswith("ViewController")

    def test_extracts_init_as_method(self) -> None:
        result = self._parse()
        inits = [s for s in result.symbols if s.name == "init"]
        assert len(inits) >= 1
        assert all(s.symbol_type == SymbolType.METHOD for s in inits)
        # The init inside struct User should carry parent_fq_name ending in User.
        for s in inits:
            assert s.parent_fq_name is not None
            assert s.parent_fq_name.endswith("User")

    def test_extracts_protocol_method(self) -> None:
        result = self._parse()
        draw = [s for s in result.symbols if s.name == "draw"]
        assert len(draw) == 1
        assert draw[0].symbol_type == SymbolType.METHOD
        parent = draw[0].parent_fq_name
        assert parent is not None
        assert parent.endswith("Drawable")

    def test_extracts_property_as_variable(self) -> None:
        result = self._parse()
        name_props = [
            s for s in result.symbols if s.name == "name" and s.symbol_type == SymbolType.VARIABLE
        ]
        assert len(name_props) >= 1

    def test_extracts_top_level_property(self) -> None:
        result = self._parse()
        max_size = [s for s in result.symbols if s.name == "MAX_SIZE"]
        assert len(max_size) == 1
        assert max_size[0].symbol_type == SymbolType.VARIABLE

    def test_static_let_maps_to_variable(self) -> None:
        """Static / const properties map to VARIABLE uniformly in v1.

        Parity with Java `static final` → VARIABLE and Kotlin `const val`
        → VARIABLE. Locks the v1 behaviour so a future promotion to
        SymbolType.CONSTANT becomes an explicit contract break.
        """
        result = self._parse()
        shared = [s for s in result.symbols if s.name == "SHARED_INSTANCE"]
        assert len(shared) == 1
        assert shared[0].symbol_type == SymbolType.VARIABLE

    def test_extension_method_parent_is_extended_type(self) -> None:
        """Methods inside `extension User { ... }` land with parent_fq_name ending in User."""
        result = self._parse()
        pp = [s for s in result.symbols if s.name == "prettyPrint"]
        assert len(pp) == 1
        parent = pp[0].parent_fq_name
        assert parent is not None
        assert parent.endswith("User")

    def test_enum_method_nesting(self) -> None:
        result = self._parse()
        label = [s for s in result.symbols if s.name == "label"]
        assert len(label) == 1
        parent = label[0].parent_fq_name
        assert parent is not None
        assert parent.endswith("Status")


# ---------------------------------------------------------------------------
# Import relations
# ---------------------------------------------------------------------------


class TestImportRelations:
    def _parse(
        self, code: bytes = SWIFT_CODE, path: str = "Sources/MyLib/Foo.swift"
    ) -> ParseResult:
        return SwiftParser().parse(file_path=path, data=code)

    def test_plain_import_surfaces_module(self) -> None:
        result = self._parse()
        refs = {r.dst_ref for r in result.relations if r.relation_type == RelationType.IMPORTS}
        assert "Foundation" in refs
        assert "UIKit" in refs

    def test_scoped_import_surfaces_full_path(self) -> None:
        """`import class Foundation.NSData` surfaces the full `Foundation.NSData`.

        Matches the Java v1 decision to surface `java.util.Arrays.asList` for
        static imports rather than trimming to the module. Graph consumers
        still see the dependency; scoped / symbol imports convey more
        specific information and that extra precision is preserved.
        """
        result = self._parse()
        refs = {r.dst_ref for r in result.relations if r.relation_type == RelationType.IMPORTS}
        assert "Foundation.NSData" in refs
        assert "Foundation.URL" in refs
        assert "Swift.print" in refs

    def test_import_dst_type_is_module(self) -> None:
        result = self._parse()
        imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
        assert len(imports) >= 5
        assert all(r.dst_type == "module" for r in imports)


# ---------------------------------------------------------------------------
# Role detection
# ---------------------------------------------------------------------------


class TestRoleDetection:
    def test_spm_sources_is_source(self) -> None:
        assert (
            SwiftParser().parse(file_path="Sources/MyLib/Foo.swift", data=MINIMAL_SWIFT).role
            == "source"
        )

    def test_bare_repo_root_is_source(self) -> None:
        assert SwiftParser().parse(file_path="Foo.swift", data=MINIMAL_SWIFT).role == "source"

    def test_spm_tests_dir_is_test(self) -> None:
        assert (
            SwiftParser().parse(file_path="Tests/MyLibTests/FooTests.swift", data=TEST_SWIFT).role
            == "test"
        )

    def test_spm_tests_dir_anywhere_is_test(self) -> None:
        assert (
            SwiftParser()
            .parse(file_path="modules/foo/Tests/MyLibTests/FooTests.swift", data=TEST_SWIFT)
            .role
            == "test"
        )

    def test_lowercase_tests_dir_is_test(self) -> None:
        assert SwiftParser().parse(file_path="tests/FooTests.swift", data=TEST_SWIFT).role == "test"

    def test_test_suffix_is_test(self) -> None:
        assert (
            SwiftParser().parse(file_path="app/src/ConfigTest.swift", data=TEST_SWIFT).role
            == "test"
        )

    def test_tests_suffix_is_test(self) -> None:
        assert (
            SwiftParser().parse(file_path="app/src/ConfigTests.swift", data=TEST_SWIFT).role
            == "test"
        )

    def test_test_prefix_is_test(self) -> None:
        assert (
            SwiftParser().parse(file_path="app/src/TestUser.swift", data=TEST_SWIFT).role == "test"
        )

    def test_xcode_appname_tests_dir_is_test(self) -> None:
        assert (
            SwiftParser().parse(file_path="MyAppTests/FooTests.swift", data=TEST_SWIFT).role
            == "test"
        )

    def test_source_wins_without_test_signal(self) -> None:
        """A Swift file named `Foo.swift` in a non-Test/ path stays source."""
        assert (
            SwiftParser().parse(file_path="Sources/MyLib/Utils.swift", data=MINIMAL_SWIFT).role
            == "source"
        )


# ---------------------------------------------------------------------------
# Module FQ derivation
# ---------------------------------------------------------------------------


class TestModuleFq:
    def test_spm_sources_strips_target(self) -> None:
        assert SwiftParser._module_fq("Sources/MyLib/Parser.swift") == "Parser"

    def test_spm_tests_strips_target(self) -> None:
        assert SwiftParser._module_fq("Tests/MyLibTests/FooTests.swift") == "FooTests"

    def test_spm_sources_nested_subdir(self) -> None:
        assert SwiftParser._module_fq("Sources/MyLib/Utils/Parser.swift") == "Utils.Parser"

    def test_nested_multi_package_layout(self) -> None:
        assert SwiftParser._module_fq("modules/foo/Sources/MyLib/Parser.swift") == "Parser"

    def test_sources_file_directly_no_target(self) -> None:
        """`Sources/Parser.swift` — no target subdir, file directly under Sources."""
        assert SwiftParser._module_fq("Sources/Parser.swift") == "Parser"

    def test_bare_dotted_path(self) -> None:
        """Xcode / flat layout: no Sources/ or Tests/ marker, dot the path."""
        assert SwiftParser._module_fq("MyApp/Foo.swift") == "MyApp.Foo"

    def test_bare_root_file(self) -> None:
        assert SwiftParser._module_fq("Foo.swift") == "Foo"

    def test_strips_swift_extension(self) -> None:
        assert SwiftParser._module_fq("Package.swift") == "Package"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_minimal_file(self) -> None:
        result = SwiftParser().parse(file_path="Sources/Mini/Main.swift", data=MINIMAL_SWIFT)
        names = [s.name for s in result.symbols]
        assert "main" in names

    def test_empty_file(self) -> None:
        result = SwiftParser().parse(file_path="Sources/Mini/Empty.swift", data=EMPTY_SWIFT)
        assert list(result.symbols) == []
        assert list(result.relations) == []

    def test_parse_result_language(self) -> None:
        result = SwiftParser().parse(file_path="Sources/MyLib/Foo.swift", data=MINIMAL_SWIFT)
        assert result.language == "swift"


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


class TestRegistryWiring:
    def test_extension_detection_bare(self) -> None:
        assert detect_language("Foo.swift") == "swift"

    def test_extension_detection_spm(self) -> None:
        assert detect_language("Sources/MyLib/Parser.swift") == "swift"

    def test_get_parser_returns_swift_parser(self) -> None:
        parser = get_parser("swift")
        assert parser is not None
        assert isinstance(parser, SwiftParser)

    def test_swift_parser_language_attr(self) -> None:
        assert SwiftParser().language == "swift"
