"""Tests for the Kotlin parser (v0.8.21)."""

from __future__ import annotations

from libs.core.entities import RelationType, SymbolType
from libs.parsers.kotlin import KotlinParser

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

KOTLIN_CODE = b"""\
package com.example.app

import java.util.List
import java.util.Map
import java.util.Map.*
import com.example.Foo as FooAlias

class Config(val name: String) {
    companion object {
        const val MAX_SIZE: Int = 1024
        fun fromString(s: String): Config = Config(s)
    }
    val count: Int = 0
    fun process(): Unit {}
}

interface Processor {
    fun run()
}

enum class Status {
    ACTIVE, INACTIVE;

    fun isActive(): Boolean = this == ACTIVE
}

object Singleton {
    fun doWork() {}
}

annotation class MyAnno(val value: String = "")

data class Point(val x: Int, val y: Int)

sealed class State {
    object Loading : State()
    data class Loaded(val v: Int) : State()
}

fun topLevelFn(): String = "hello"
val TOP_LEVEL_VAL = 42
"""

MINIMAL_KOTLIN = b"""\
package demo

fun main(args: Array<String>) {
}
"""

TEST_KOTLIN = b"""\
package com.example.app

import org.junit.jupiter.api.Test

class ConfigTest {
    @Test
    fun checksSomething() {
    }
}
"""

EMPTY_KOTLIN = b""


# ---------------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------------


class TestSymbolExtraction:
    def test_extracts_class(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        # Filter explicitly to CLASS — Kotlin maps several node kinds onto
        # CLASS so there's more than one "Config"-ish symbol without the
        # filter.
        classes = [
            s for s in result.symbols if s.name == "Config" and s.symbol_type == SymbolType.CLASS
        ]
        assert len(classes) == 1

    def test_extracts_interface(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        ifaces = [s for s in result.symbols if s.name == "Processor"]
        assert len(ifaces) == 1
        assert ifaces[0].symbol_type == SymbolType.CLASS

    def test_extracts_enum_class(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        enums = [s for s in result.symbols if s.name == "Status"]
        assert len(enums) == 1
        assert enums[0].symbol_type == SymbolType.CLASS

    def test_extracts_annotation_class(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        anno = [s for s in result.symbols if s.name == "MyAnno"]
        assert len(anno) == 1
        assert anno[0].symbol_type == SymbolType.CLASS

    def test_extracts_data_class(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        dc = [s for s in result.symbols if s.name == "Point"]
        assert len(dc) == 1
        assert dc[0].symbol_type == SymbolType.CLASS

    def test_extracts_sealed_class_and_nested(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        # ``sealed class State`` itself.
        state = [s for s in result.symbols if s.name == "State"]
        assert len(state) == 1
        # Its nested object + data class live inside and carry the
        # enclosing fq_name as their parent.
        loading = [s for s in result.symbols if s.name == "Loading"]
        assert len(loading) == 1
        assert loading[0].parent_fq_name is not None
        assert loading[0].parent_fq_name.endswith("State")

    def test_extracts_object_declaration(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        singletons = [s for s in result.symbols if s.name == "Singleton"]
        assert len(singletons) == 1
        # Named ``object`` declarations are runtime classes-with-one-
        # instance; map onto CLASS for graph purposes.
        assert singletons[0].symbol_type == SymbolType.CLASS

    def test_extracts_top_level_function(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        fns = [s for s in result.symbols if s.name == "topLevelFn"]
        assert len(fns) == 1
        assert fns[0].symbol_type == SymbolType.METHOD

    def test_extracts_method_inside_class(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        methods = [
            s for s in result.symbols if s.name == "process" and s.symbol_type == SymbolType.METHOD
        ]
        assert len(methods) == 1
        assert methods[0].fq_name.endswith("Config.process")

    def test_extracts_interface_method(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        runs = [s for s in result.symbols if s.name == "run" and s.symbol_type == SymbolType.METHOD]
        assert len(runs) == 1

    def test_extracts_property(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        props = [s for s in result.symbols if s.name == "count"]
        assert len(props) == 1
        assert props[0].symbol_type == SymbolType.VARIABLE

    def test_extracts_top_level_property(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        tlv = [s for s in result.symbols if s.name == "TOP_LEVEL_VAL"]
        assert len(tlv) == 1
        assert tlv[0].symbol_type == SymbolType.VARIABLE

    def test_extracts_const_val_inside_companion(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        # v1 scope: ``const val`` maps to VARIABLE uniformly, matching
        # Java's static-final handling. This test locks the behaviour so
        # a future promotion to CONSTANT is an explicit contract break.
        const = [s for s in result.symbols if s.name == "MAX_SIZE"]
        assert len(const) == 1
        assert const[0].symbol_type == SymbolType.VARIABLE

    def test_companion_members_parent_is_enclosing_class(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        # ``companion_object`` has no name in the Kotlin grammar so it
        # doesn't push a scope — children end up with the outer class
        # as their ``parent_fq_name``, matching Kotlin semantics where
        # companion members are addressed as ``EnclosingClass.member``.
        from_string = [s for s in result.symbols if s.name == "fromString"]
        assert len(from_string) == 1
        assert from_string[0].parent_fq_name is not None
        assert from_string[0].parent_fq_name.endswith("Config")

    def test_enum_method_is_nested(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        is_active = [
            s for s in result.symbols if s.name == "isActive" and s.symbol_type == SymbolType.METHOD
        ]
        assert len(is_active) == 1
        parent = is_active[0].parent_fq_name
        assert parent is not None
        assert parent.endswith("Status")


# ---------------------------------------------------------------------------
# Import relations
# ---------------------------------------------------------------------------


class TestImportRelations:
    def test_records_scoped_imports(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
        refs = {r.dst_ref for r in imports}
        assert "java.util.List" in refs
        assert "java.util.Map" in refs

    def test_records_wildcard_import_as_package(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
        refs = [r.dst_ref for r in imports]
        # ``import java.util.Map.*`` collapses to the module path — the
        # grammar places ``.*`` as sibling tokens after the
        # ``qualified_identifier``, so reading that naturally drops the
        # wildcard suffix.  Both the scoped ``import java.util.Map`` and
        # this wildcard form surface as the same ref — which is fine,
        # downstream graph consumers deduplicate by (src, dst, rel).
        assert "java.util.Map" in refs

    def test_records_alias_import_as_original_module(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
        refs = {r.dst_ref for r in imports}
        # ``import com.example.Foo as FooAlias`` surfaces as the
        # original module path — the graph tracks real dependencies,
        # not local aliases.
        assert "com.example.Foo" in refs

    def test_import_dst_type_is_module(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
        assert len(imports) >= 3
        for imp in imports:
            assert imp.dst_type == "module"


# ---------------------------------------------------------------------------
# Role detection
# ---------------------------------------------------------------------------


class TestRoleDetection:
    def test_source_role_gradle_main(self) -> None:
        parser = KotlinParser()
        result = parser.parse(file_path="src/main/kotlin/com/example/Foo.kt", data=MINIMAL_KOTLIN)
        assert result.role == "source"

    def test_source_role_bare_repo_root(self) -> None:
        parser = KotlinParser()
        result = parser.parse(file_path="Foo.kt", data=MINIMAL_KOTLIN)
        assert result.role == "source"

    def test_test_role_src_test_kotlin(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/test/kotlin/com/example/app/ConfigTest.kt",
            data=TEST_KOTLIN,
        )
        assert result.role == "test"

    def test_test_role_android_test(self) -> None:
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/androidTest/kotlin/com/example/app/ConfigTest.kt",
            data=TEST_KOTLIN,
        )
        assert result.role == "test"

    def test_test_role_kotlin_under_java_test_root(self) -> None:
        parser = KotlinParser()
        # Mixed Java/Kotlin projects put Kotlin tests under ``src/test/java``
        # as well — role detection accepts both.
        result = parser.parse(
            file_path="src/test/java/com/example/ConfigTest.kt",
            data=TEST_KOTLIN,
        )
        assert result.role == "test"

    def test_test_role_tests_dir(self) -> None:
        parser = KotlinParser()
        result = parser.parse(file_path="tests/ConfigTest.kt", data=TEST_KOTLIN)
        assert result.role == "test"

    def test_test_role_Test_suffix(self) -> None:
        parser = KotlinParser()
        # Outside of a tests/ dir — filename-only classification.
        result = parser.parse(file_path="app/src/ConfigTest.kt", data=TEST_KOTLIN)
        assert result.role == "test"

    def test_test_role_Tests_suffix(self) -> None:
        parser = KotlinParser()
        result = parser.parse(file_path="app/src/ConfigTests.kt", data=TEST_KOTLIN)
        assert result.role == "test"

    def test_test_role_Test_prefix(self) -> None:
        parser = KotlinParser()
        result = parser.parse(file_path="app/src/TestConfig.kt", data=TEST_KOTLIN)
        assert result.role == "test"

    def test_kts_gradle_script_role(self) -> None:
        parser = KotlinParser()
        # Gradle Kotlin DSL build scripts aren't tests — ``.kts`` under
        # a non-test directory should land as ``source`` so the file is
        # still indexed.
        result = parser.parse(file_path="app/build.gradle.kts", data=MINIMAL_KOTLIN)
        assert result.role == "source"


# ---------------------------------------------------------------------------
# Module FQ derivation
# ---------------------------------------------------------------------------


class TestModuleFq:
    def test_strips_gradle_main_kotlin_root(self) -> None:
        assert (
            KotlinParser._module_fq("src/main/kotlin/com/example/app/Config.kt")
            == "com.example.app.Config"
        )

    def test_strips_gradle_test_kotlin_root(self) -> None:
        assert (
            KotlinParser._module_fq("src/test/kotlin/com/example/app/ConfigTest.kt")
            == "com.example.app.ConfigTest"
        )

    def test_strips_android_test_kotlin_root(self) -> None:
        assert (
            KotlinParser._module_fq("src/androidTest/kotlin/com/example/Foo.kt")
            == "com.example.Foo"
        )

    def test_strips_java_root_in_mixed_project(self) -> None:
        # Kotlin files placed under ``src/main/java`` in mixed projects.
        assert KotlinParser._module_fq("src/main/java/com/example/Bar.kt") == "com.example.Bar"

    def test_nested_gradle_root_is_stripped(self) -> None:
        assert (
            KotlinParser._module_fq("modules/foo/src/main/kotlin/com/example/Bar.kt")
            == "com.example.Bar"
        )

    def test_bare_path_falls_back_to_dotted(self) -> None:
        assert KotlinParser._module_fq("com/example/Foo.kt") == "com.example.Foo"

    def test_strips_kt_extension(self) -> None:
        assert KotlinParser._module_fq("Foo.kt") == "Foo"

    def test_strips_kts_extension(self) -> None:
        assert KotlinParser._module_fq("build.gradle.kts") == "build.gradle"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_minimal_file(self) -> None:
        parser = KotlinParser()
        result = parser.parse(file_path="demo/Hello.kt", data=MINIMAL_KOTLIN)
        names = {s.name for s in result.symbols}
        assert "main" in names

    def test_empty_file(self) -> None:
        parser = KotlinParser()
        result = parser.parse(file_path="Empty.kt", data=EMPTY_KOTLIN)
        assert result.symbols == ()
        # Empty Kotlin file is a valid compilation unit.
        assert result.errors == ()

    def test_parse_result_language(self) -> None:
        parser = KotlinParser()
        result = parser.parse(file_path="Foo.kt", data=MINIMAL_KOTLIN)
        assert result.language == "kotlin"


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


class TestRegistryWiring:
    def test_detect_language_kotlin(self) -> None:
        from libs.parsers.registry import detect_language

        assert detect_language("Foo.kt") == "kotlin"
        assert detect_language("build.gradle.kts") == "kotlin"
        assert detect_language("src/main/kotlin/com/example/Foo.kt") == "kotlin"

    def test_get_parser_returns_kotlin_parser(self) -> None:
        from libs.parsers.registry import get_parser

        parser = get_parser("kotlin")
        assert parser is not None
        assert isinstance(parser, KotlinParser)

    def test_kotlin_parser_language_attr(self) -> None:
        parser = KotlinParser()
        assert parser.language == "kotlin"
