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
