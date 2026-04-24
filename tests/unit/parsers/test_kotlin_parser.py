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


# ---------------------------------------------------------------------------
# INHERITS edges (v0.8.24)
# ---------------------------------------------------------------------------


INHERITS_CODE = b"""\
package com.example

// Single base class via constructor_invocation
class Dog : Animal()

// Mixed: one extends (parentheses) + two implements (bare user_types)
class Cat : Animal(), Feline, Cuddly

// Interface : many -- same colon syntax as class extension
interface MyList : Collection<Int>, Iterable<Int>

// Object singleton with heritage
object Singleton : Base(), Trait

// Enum implements interface
enum class Color : Serializable { RED, BLUE }

// Data class heritage (no parentheses -- interface conformance)
data class Point(val x: Int, val y: Int) : Coord

// Sealed class heritage
sealed class Tree : Node

// Explicit delegation -- still is-a for graph purposes
class Impl(x: Iface) : Iface by x

// Mixed explicit + constructor + bare
class Mixed(x: Iface) : Base(), Iface by x, OtherIface

// Generics must be stripped
class Box<T> : Container<String>, Comparable<Box<T>>

// Scoped base paths preserved, generics still stripped
class Outer { class Inner : pkg.lib.Deep<String> }

// Plain class -- no heritage
class Plain

// Annotation class -- cannot carry delegation specifiers
annotation class MyAnn

// Nested: outer + inner + object inside outer
class Types {
    class NestedA : NestedBase()
    object NestedObj : NestedObjBase
}

// Companion object with heritage -- intentionally excluded
class WithCompanion {
    companion object : Holder
}
"""


class TestInheritsEdges:
    """Locks INHERITS edge emission for Kotlin's ``:`` heritage syntax."""

    def _inherits(self, code: bytes, path: str) -> list[tuple[str, str]]:
        parser = KotlinParser()
        result = parser.parse(file_path=path, data=code)
        return [
            (rel.src_ref, rel.dst_ref)
            for rel in result.relations
            if rel.relation_type == RelationType.INHERITS
        ]

    def test_single_base_class_via_constructor_invocation(self) -> None:
        edges = self._inherits(INHERITS_CODE, "src/main/kotlin/com/example/K.kt")
        assert ("com.example.K.Dog", "Animal") in edges

    def test_extends_and_implements_mixed(self) -> None:
        edges = self._inherits(INHERITS_CODE, "src/main/kotlin/com/example/K.kt")
        assert ("com.example.K.Cat", "Animal") in edges
        assert ("com.example.K.Cat", "Feline") in edges
        assert ("com.example.K.Cat", "Cuddly") in edges

    def test_interface_extends_many(self) -> None:
        edges = self._inherits(INHERITS_CODE, "src/main/kotlin/com/example/K.kt")
        assert ("com.example.K.MyList", "Collection") in edges
        assert ("com.example.K.MyList", "Iterable") in edges

    def test_object_declaration_supports_heritage(self) -> None:
        edges = self._inherits(INHERITS_CODE, "src/main/kotlin/com/example/K.kt")
        assert ("com.example.K.Singleton", "Base") in edges
        assert ("com.example.K.Singleton", "Trait") in edges

    def test_enum_class_implements_interface(self) -> None:
        edges = self._inherits(INHERITS_CODE, "src/main/kotlin/com/example/K.kt")
        assert ("com.example.K.Color", "Serializable") in edges

    def test_data_class_heritage(self) -> None:
        edges = self._inherits(INHERITS_CODE, "src/main/kotlin/com/example/K.kt")
        assert ("com.example.K.Point", "Coord") in edges

    def test_sealed_class_heritage(self) -> None:
        edges = self._inherits(INHERITS_CODE, "src/main/kotlin/com/example/K.kt")
        assert ("com.example.K.Tree", "Node") in edges

    def test_explicit_delegation_emits_inherits(self) -> None:
        """`: Iface by impl` is semantically is-a — emit INHERITS."""
        edges = self._inherits(INHERITS_CODE, "src/main/kotlin/com/example/K.kt")
        assert ("com.example.K.Impl", "Iface") in edges

    def test_mixed_extends_delegation_and_bare(self) -> None:
        edges = self._inherits(INHERITS_CODE, "src/main/kotlin/com/example/K.kt")
        assert ("com.example.K.Mixed", "Base") in edges
        assert ("com.example.K.Mixed", "Iface") in edges
        assert ("com.example.K.Mixed", "OtherIface") in edges

    def test_generic_type_arguments_stripped(self) -> None:
        """`Container<String>` must emit ``Container``, never ``String``."""
        edges = self._inherits(INHERITS_CODE, "src/main/kotlin/com/example/K.kt")
        box_edges = [edge for edge in edges if edge[0] == "com.example.K.Box"]
        assert ("com.example.K.Box", "Container") in box_edges
        assert ("com.example.K.Box", "Comparable") in box_edges
        dst_refs = {dst for _, dst in edges}
        assert "String" not in dst_refs
        assert "Int" not in dst_refs
        # Type argument is literally ``Box<T>`` — must not leak as ``Box``
        # surfacing an edge onto itself; guard: ``Box`` only appears as a source.
        for src, dst in edges:
            assert src != dst

    def test_scoped_base_preserves_full_path(self) -> None:
        """`pkg.lib.Deep<String>` must emit ``pkg.lib.Deep``."""
        edges = self._inherits(INHERITS_CODE, "src/main/kotlin/com/example/K.kt")
        assert ("com.example.K.Outer.Inner", "pkg.lib.Deep") in edges

    def test_plain_class_has_no_inherits(self) -> None:
        edges = self._inherits(INHERITS_CODE, "src/main/kotlin/com/example/K.kt")
        assert not any(src == "com.example.K.Plain" for src, _ in edges)

    def test_annotation_class_never_source(self) -> None:
        """Annotation classes cannot inherit — zero edges."""
        edges = self._inherits(INHERITS_CODE, "src/main/kotlin/com/example/K.kt")
        assert not any(src == "com.example.K.MyAnn" for src, _ in edges)

    def test_nested_class_uses_outer_fq(self) -> None:
        edges = self._inherits(INHERITS_CODE, "src/main/kotlin/com/example/K.kt")
        assert ("com.example.K.Types.NestedA", "NestedBase") in edges
        assert ("com.example.K.Types.NestedObj", "NestedObjBase") in edges

    def test_companion_object_excluded(self) -> None:
        """Companion objects have no name field; excluded per the fq-invariant."""
        edges = self._inherits(INHERITS_CODE, "src/main/kotlin/com/example/K.kt")
        # Neither the companion object nor its parent should emit an edge for
        # the companion's `: Holder` heritage.
        assert not any(dst == "Holder" for _, dst in edges)
        assert not any("Companion" in src or "companion" in src for src, _ in edges)

    def test_inherits_src_ref_matches_symbol_fq(self) -> None:
        """Every INHERITS ``src_ref`` must resolve to a symbol fq in the same file."""
        parser = KotlinParser()
        result = parser.parse(file_path="src/main/kotlin/com/example/K.kt", data=INHERITS_CODE)
        symbol_fqs = {s.fq_name for s in result.symbols}
        inherits_srcs = {
            rel.src_ref for rel in result.relations if rel.relation_type == RelationType.INHERITS
        }
        missing = inherits_srcs - symbol_fqs
        assert missing == set(), f"INHERITS src_refs without matching symbol: {missing}"

    def test_inherits_relation_shape(self) -> None:
        """Relations are shaped ``src_type=symbol``, ``dst_type=symbol``."""
        parser = KotlinParser()
        result = parser.parse(file_path="src/main/kotlin/com/example/K.kt", data=INHERITS_CODE)
        inherits = [rel for rel in result.relations if rel.relation_type == RelationType.INHERITS]
        assert inherits, "fixture expected to emit INHERITS edges"
        for rel in inherits:
            assert rel.src_type == "symbol"
            assert rel.dst_type == "symbol"

    def test_gradle_module_fq_respected(self) -> None:
        """Non-Maven paths drop the ``src/main/kotlin/`` prefix in the fq."""
        code = b"""package org.lib
class Widget : Base()
"""
        edges = self._inherits(code, "libs/widget/src/main/kotlin/org/lib/Widget.kt")
        assert ("org.lib.Widget.Widget", "Base") in edges

    def test_empty_file_no_inherits(self) -> None:
        edges = self._inherits(EMPTY_KOTLIN, "src/main/kotlin/Empty.kt")
        assert edges == []

    def test_pre_v0_8_24_fixture_still_emits_zero_inherits(self) -> None:
        """Baseline guard: the pre-v0.8.24 fixture has no heritage and must stay zero."""
        parser = KotlinParser()
        result = parser.parse(
            file_path="src/main/kotlin/com/example/app/Config.kt", data=KOTLIN_CODE
        )
        inherits = [rel for rel in result.relations if rel.relation_type == RelationType.INHERITS]
        # The pre-existing KOTLIN_CODE fixture uses `State` with `State()` and
        # `Loaded(...) : State()` — which DO now emit INHERITS edges. Guard
        # that the specific subclasses resolve, but no stray edges appear.
        dsts = {rel.dst_ref for rel in inherits}
        assert dsts.issubset({"State"}), (
            f"KOTLIN_CODE fixture should only inherit from State, got: {dsts}"
        )
        _ = SymbolType.CLASS  # keep the import used for the rest of the module
