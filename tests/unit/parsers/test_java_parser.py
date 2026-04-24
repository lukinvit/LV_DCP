"""Tests for the Java parser (v0.8.20)."""

from __future__ import annotations

from libs.core.entities import RelationType, SymbolType
from libs.parsers.java import JavaParser

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

JAVA_CODE = b"""\
package com.example.app;

import java.util.List;
import java.util.Map;
import java.util.*;
import static java.util.Arrays.asList;

public class Config {
    private String name;
    public static final int MAX_SIZE = 1024;

    public Config(String n) {
        this.name = n;
    }

    public void process() {
    }

    public int get(String k) {
        return 0;
    }
}

interface Processor {
    void run();
}

enum Status {
    ACTIVE,
    INACTIVE;

    public boolean isActive() {
        return this == ACTIVE;
    }
}

public @interface MyAnno {
    String value() default "";
}

record Point(int x, int y) {}
"""

MINIMAL_JAVA = b"""\
package demo;

public class Hello {
    public static void main(String[] args) {
    }
}
"""

TEST_JAVA = b"""\
package com.example.app;

import org.junit.jupiter.api.Test;

public class ConfigTest {
    @Test
    void checksSomething() {
    }
}
"""

EMPTY_JAVA = b""


# ---------------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------------


class TestSymbolExtraction:
    def test_extracts_class(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="src/main/java/com/example/app/Config.java", data=JAVA_CODE)
        # Filter by type — the constructor also has ``name="Config"``,
        # but it's a METHOD symbol, not a CLASS.
        classes = [
            s for s in result.symbols if s.name == "Config" and s.symbol_type == SymbolType.CLASS
        ]
        assert len(classes) == 1

    def test_extracts_interface(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="src/main/java/com/example/app/Config.java", data=JAVA_CODE)
        ifaces = [s for s in result.symbols if s.name == "Processor"]
        assert len(ifaces) == 1
        assert ifaces[0].symbol_type == SymbolType.CLASS

    def test_extracts_enum(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="src/main/java/com/example/app/Config.java", data=JAVA_CODE)
        enums = [s for s in result.symbols if s.name == "Status"]
        assert len(enums) == 1
        assert enums[0].symbol_type == SymbolType.CLASS

    def test_extracts_annotation_type(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="src/main/java/com/example/app/Config.java", data=JAVA_CODE)
        anno = [s for s in result.symbols if s.name == "MyAnno"]
        assert len(anno) == 1
        assert anno[0].symbol_type == SymbolType.CLASS

    def test_extracts_record(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="src/main/java/com/example/app/Config.java", data=JAVA_CODE)
        rec = [s for s in result.symbols if s.name == "Point"]
        assert len(rec) == 1
        assert rec[0].symbol_type == SymbolType.CLASS

    def test_extracts_method(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="src/main/java/com/example/app/Config.java", data=JAVA_CODE)
        methods = [
            s for s in result.symbols if s.name == "process" and s.symbol_type == SymbolType.METHOD
        ]
        assert len(methods) == 1
        # Method nested inside class — fq_name must carry the class.
        assert methods[0].fq_name.endswith("Config.process")

    def test_extracts_constructor(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="src/main/java/com/example/app/Config.java", data=JAVA_CODE)
        ctors = [
            s for s in result.symbols if s.name == "Config" and s.symbol_type == SymbolType.METHOD
        ]
        assert len(ctors) == 1

    def test_extracts_interface_method(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="src/main/java/com/example/app/Config.java", data=JAVA_CODE)
        run_methods = [
            s for s in result.symbols if s.name == "run" and s.symbol_type == SymbolType.METHOD
        ]
        assert len(run_methods) == 1

    def test_extracts_field(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="src/main/java/com/example/app/Config.java", data=JAVA_CODE)
        fields = [s for s in result.symbols if s.name == "name"]
        assert len(fields) == 1
        assert fields[0].symbol_type == SymbolType.VARIABLE

    def test_extracts_static_final_field(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="src/main/java/com/example/app/Config.java", data=JAVA_CODE)
        # v1 scope: static final fields are still mapped to VARIABLE.
        # Promoting them to CONSTANT requires modifier inspection; tracked
        # as a follow-up. This test locks in the v1 behaviour so a future
        # change is an explicit contract break rather than a silent flip.
        const_fields = [s for s in result.symbols if s.name == "MAX_SIZE"]
        assert len(const_fields) == 1
        assert const_fields[0].symbol_type == SymbolType.VARIABLE

    def test_enum_method_is_nested(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="src/main/java/com/example/app/Config.java", data=JAVA_CODE)
        # Enums have bodies too — methods inside them should still be METHOD.
        is_active = [
            s for s in result.symbols if s.name == "isActive" and s.symbol_type == SymbolType.METHOD
        ]
        assert len(is_active) == 1
        # And the parent_fq_name should carry the enum declaration.
        parent = is_active[0].parent_fq_name
        assert parent is not None
        assert parent.endswith("Status")


# ---------------------------------------------------------------------------
# Import relations
# ---------------------------------------------------------------------------


class TestImportRelations:
    def test_records_scoped_imports(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="src/main/java/com/example/app/Config.java", data=JAVA_CODE)
        imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
        refs = {r.dst_ref for r in imports}
        assert "java.util.List" in refs
        assert "java.util.Map" in refs

    def test_records_wildcard_import_as_package(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="src/main/java/com/example/app/Config.java", data=JAVA_CODE)
        imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
        refs = {r.dst_ref for r in imports}
        # ``import java.util.*;`` lands as the package path without the
        # trailing ``.*`` — downstream graph consumers care about the
        # module, not whether every symbol is pulled.
        assert "java.util" in refs

    def test_records_static_import(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="src/main/java/com/example/app/Config.java", data=JAVA_CODE)
        imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
        refs = {r.dst_ref for r in imports}
        # ``import static java.util.Arrays.asList;`` surfaces the
        # fully-qualified symbol path as a module ref.
        assert "java.util.Arrays.asList" in refs

    def test_import_dst_type_is_module(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="src/main/java/com/example/app/Config.java", data=JAVA_CODE)
        imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
        # At least the known scoped imports exist.
        assert len(imports) >= 4
        for imp in imports:
            assert imp.dst_type == "module"


# ---------------------------------------------------------------------------
# Role detection
# ---------------------------------------------------------------------------


class TestRoleDetection:
    def test_source_role_maven_main(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="src/main/java/com/example/Foo.java", data=MINIMAL_JAVA)
        assert result.role == "source"

    def test_source_role_bare_repo_root(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="Foo.java", data=MINIMAL_JAVA)
        assert result.role == "source"

    def test_test_role_src_test_java(self) -> None:
        parser = JavaParser()
        result = parser.parse(
            file_path="src/test/java/com/example/app/ConfigTest.java", data=TEST_JAVA
        )
        assert result.role == "test"

    def test_test_role_tests_dir(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="tests/ConfigTest.java", data=TEST_JAVA)
        assert result.role == "test"

    def test_test_role_Test_suffix(self) -> None:
        parser = JavaParser()
        # Outside of a tests/ dir — filename-only classification.
        result = parser.parse(file_path="app/src/ConfigTest.java", data=TEST_JAVA)
        assert result.role == "test"

    def test_test_role_Tests_suffix(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="app/src/ConfigTests.java", data=TEST_JAVA)
        assert result.role == "test"

    def test_test_role_Test_prefix_junit3(self) -> None:
        parser = JavaParser()
        # JUnit 3 convention — class name starts with Test.
        result = parser.parse(file_path="app/src/TestConfig.java", data=TEST_JAVA)
        assert result.role == "test"


# ---------------------------------------------------------------------------
# Module FQ derivation
# ---------------------------------------------------------------------------


class TestModuleFq:
    def test_strips_maven_main_root(self) -> None:
        assert (
            JavaParser._module_fq("src/main/java/com/example/app/Config.java")
            == "com.example.app.Config"
        )

    def test_strips_maven_test_root(self) -> None:
        assert (
            JavaParser._module_fq("src/test/java/com/example/app/ConfigTest.java")
            == "com.example.app.ConfigTest"
        )

    def test_nested_maven_root_is_stripped(self) -> None:
        # Gradle multi-module projects: ``foo/src/main/java/com/…``
        assert (
            JavaParser._module_fq("modules/foo/src/main/java/com/example/Bar.java")
            == "com.example.Bar"
        )

    def test_bare_path_falls_back_to_dotted(self) -> None:
        assert JavaParser._module_fq("com/example/Foo.java") == "com.example.Foo"

    def test_strips_java_extension(self) -> None:
        assert JavaParser._module_fq("Foo.java") == "Foo"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_minimal_file(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="demo/Hello.java", data=MINIMAL_JAVA)
        names = {s.name for s in result.symbols}
        assert "Hello" in names
        assert "main" in names

    def test_empty_file(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="Empty.java", data=EMPTY_JAVA)
        assert result.symbols == ()
        # Empty file is syntactically valid Java (it's just an empty
        # compilation unit), so tree-sitter shouldn't flag errors.
        assert result.errors == ()

    def test_parse_result_language(self) -> None:
        parser = JavaParser()
        result = parser.parse(file_path="Foo.java", data=MINIMAL_JAVA)
        assert result.language == "java"


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


class TestRegistryWiring:
    def test_detect_language_java(self) -> None:
        from libs.parsers.registry import detect_language

        assert detect_language("Foo.java") == "java"
        assert detect_language("src/main/java/com/example/Foo.java") == "java"

    def test_get_parser_returns_java_parser(self) -> None:
        from libs.parsers.registry import get_parser

        parser = get_parser("java")
        assert parser is not None
        assert isinstance(parser, JavaParser)

    def test_java_parser_language_attr(self) -> None:
        parser = JavaParser()
        assert parser.language == "java"


# ---------------------------------------------------------------------------
# INHERITS edges (v0.8.23)
# ---------------------------------------------------------------------------


INHERITS_CODE = b"""\
package com.example;

public class Child extends Parent {}

public class Multi extends Parent implements Alpha, Beta, Gamma {}

public class GenericHeir extends Container<String> implements Iterable<Integer> {}

public class Scoped extends pkg.inner.Deep {}

public class ScopedGeneric extends pkg.Box<Integer> {}

public interface IKind extends IAlpha, IBeta {}

public enum Mode implements Serializable, Cloneable {
    ON,
    OFF
}

public record Coord(int x, int y) implements Comparable<Coord> {}

public class Plain {}

public @interface Marker {}

public class Outer {
    public class Inner extends InnerBase implements InnerMarker {}

    public static class Static extends StaticBase {}
}
"""


class TestInheritsEdges:
    """v0.8.23 — INHERITS edges for extends / implements clauses."""

    @staticmethod
    def _inherits(code: bytes, path: str = "Types.java") -> list[tuple[str, str]]:
        result = JavaParser().parse(file_path=path, data=code)
        return [
            (r.src_ref, r.dst_ref)
            for r in result.relations
            if r.relation_type == RelationType.INHERITS
        ]

    def test_class_extends_single_base(self) -> None:
        edges = self._inherits(INHERITS_CODE)
        assert ("Types.Child", "Parent") in edges

    def test_class_extends_plus_implements_multiple(self) -> None:
        edges = self._inherits(INHERITS_CODE)
        assert ("Types.Multi", "Parent") in edges
        assert ("Types.Multi", "Alpha") in edges
        assert ("Types.Multi", "Beta") in edges
        assert ("Types.Multi", "Gamma") in edges

    def test_generic_type_arguments_stripped(self) -> None:
        """``extends Container<String>`` surfaces as ``Container`` only."""
        edges = self._inherits(INHERITS_CODE)
        assert ("Types.GenericHeir", "Container") in edges
        assert ("Types.GenericHeir", "Iterable") in edges
        # The type-argument identifiers must never surface as bases.
        assert not any(base in {"String", "Integer"} for _, base in edges)

    def test_scoped_base_preserves_full_path(self) -> None:
        """``extends pkg.inner.Deep`` surfaces as the full dotted path."""
        edges = self._inherits(INHERITS_CODE)
        assert ("Types.Scoped", "pkg.inner.Deep") in edges

    def test_scoped_generic_strips_arguments(self) -> None:
        """``extends pkg.Box<Integer>`` surfaces as ``pkg.Box`` only."""
        edges = self._inherits(INHERITS_CODE)
        assert ("Types.ScopedGeneric", "pkg.Box") in edges
        assert not any(base == "Integer" for _, base in edges)

    def test_interface_extends_multiple(self) -> None:
        """Interface ``extends`` clause produces one edge per parent."""
        edges = self._inherits(INHERITS_CODE)
        assert ("Types.IKind", "IAlpha") in edges
        assert ("Types.IKind", "IBeta") in edges

    def test_enum_implements_multiple(self) -> None:
        edges = self._inherits(INHERITS_CODE)
        assert ("Types.Mode", "Serializable") in edges
        assert ("Types.Mode", "Cloneable") in edges

    def test_record_implements(self) -> None:
        """``record Coord(int x, int y) implements Comparable<Coord>``."""
        edges = self._inherits(INHERITS_CODE)
        assert ("Types.Coord", "Comparable") in edges

    def test_plain_class_emits_no_inherits(self) -> None:
        """A class with no heritage clauses emits zero INHERITS edges."""
        edges = self._inherits(INHERITS_CODE)
        assert not any(src == "Types.Plain" for src, _ in edges)

    def test_annotation_type_never_source(self) -> None:
        """``@interface`` declarations cannot have heritage; never appear as src."""
        edges = self._inherits(INHERITS_CODE)
        assert not any(src == "Types.Marker" for src, _ in edges)

    def test_nested_inner_class_uses_outer_fq(self) -> None:
        """Inner class INHERITS edge's src_ref matches its symbol fq_name."""
        edges = self._inherits(INHERITS_CODE)
        # fq for ``Outer.Inner`` (non-static) — matches the symbol fq
        # produced by the main walker's scope stack.
        assert ("Types.Outer.Inner", "InnerBase") in edges
        assert ("Types.Outer.Inner", "InnerMarker") in edges

    def test_nested_static_class_uses_outer_fq(self) -> None:
        """Static nested classes share the same fq convention as non-static."""
        edges = self._inherits(INHERITS_CODE)
        assert ("Types.Outer.Static", "StaticBase") in edges

    def test_inherits_src_ref_matches_symbol_fq(self) -> None:
        """Every INHERITS src_ref resolves against a symbol in the same file."""
        result = JavaParser().parse(file_path="Types.java", data=INHERITS_CODE)
        fq_names = {s.fq_name for s in result.symbols}
        for rel in result.relations:
            if rel.relation_type == RelationType.INHERITS:
                assert rel.src_ref in fq_names, (
                    f"INHERITS src_ref {rel.src_ref} does not resolve to a "
                    f"symbol in the same file (symbols: {sorted(fq_names)})"
                )

    def test_inherits_relation_shape(self) -> None:
        """INHERITS edges use ``src_type=symbol``, ``dst_type=symbol``."""
        result = JavaParser().parse(file_path="Types.java", data=INHERITS_CODE)
        inherits = [r for r in result.relations if r.relation_type == RelationType.INHERITS]
        assert inherits, "sanity: the fixture should produce edges"
        for rel in inherits:
            assert rel.src_type == "symbol"
            assert rel.dst_type == "symbol"

    def test_inherits_respects_maven_module_fq(self) -> None:
        """When a Maven layout is present the module_fq is the Java package path."""
        edges = self._inherits(
            b"package com.example;\nclass Foo extends Bar {}\n",
            path="src/main/java/com/example/Foo.java",
        )
        assert ("com.example.Foo.Foo", "Bar") in edges

    def test_inherits_empty_file_emits_nothing(self) -> None:
        edges = self._inherits(b"")
        assert edges == []

    def test_inherits_plain_fixture_has_none(self) -> None:
        """The pre-v0.8.23 JAVA_CODE fixture has no extends/implements clauses."""
        edges = self._inherits(JAVA_CODE, path="src/main/java/com/example/app/Config.java")
        assert edges == []
