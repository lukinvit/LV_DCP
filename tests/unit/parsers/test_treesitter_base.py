"""Tests for TreeSitterParser base class.

Uses a DummyParser subclass that wraps tree-sitter-python to exercise
the base class logic without needing a second language grammar.
"""

from __future__ import annotations

import tree_sitter_python as tspython
from libs.core.entities import RelationType, SymbolType
from libs.core.paths import is_test_path
from libs.parsers.base import FileParser, ParseResult
from libs.parsers.treesitter_base import TreeSitterParser
from tree_sitter import Language


class DummyPythonParser(TreeSitterParser):
    """Thin subclass wrapping tree-sitter-python for testing."""

    language = "python"

    def _get_ts_language(self) -> Language:
        return Language(tspython.language())

    def _symbol_type_map(self) -> dict[str, SymbolType]:
        return {
            "function_definition": SymbolType.FUNCTION,
            "class_definition": SymbolType.CLASS,
        }

    def _import_node_types(self) -> set[str]:
        return {"import_statement", "import_from_statement"}

    def _detect_role(self, file_path: str) -> str:
        return "test" if is_test_path(file_path) else "source"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SIMPLE_CODE = b"""\
import os
from pathlib import Path

class Foo:
    \"\"\"Foo docstring.\"\"\"

    def method(self, x):
        \"\"\"Method doc.\"\"\"
        return x

def top_func(a, b):
    pass
"""

CLASS_WITH_NESTED = b"""\
class Outer:
    class Inner:
        def nested_method(self):
            pass
"""

IMPORT_ONLY = b"""\
import json
from collections import OrderedDict
"""


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_implements_file_parser_protocol(self) -> None:
        parser = DummyPythonParser()
        assert isinstance(parser, FileParser)

    def test_has_language_attribute(self) -> None:
        parser = DummyPythonParser()
        assert parser.language == "python"


# ---------------------------------------------------------------------------
# parse() basics
# ---------------------------------------------------------------------------


class TestParseBasics:
    def test_returns_parse_result(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        assert isinstance(result, ParseResult)

    def test_file_path_preserved(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        assert result.file_path == "libs/example.py"

    def test_language_set(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        assert result.language == "python"

    def test_role_source(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        assert result.role == "source"

    def test_role_test(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="tests/test_foo.py", data=SIMPLE_CODE)
        assert result.role == "test"

    def test_no_errors_on_valid_code(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        assert result.errors == ()

    def test_errors_on_invalid_syntax(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="bad.py", data=b"def (broken:")
        assert len(result.errors) > 0
        assert "parse error" in result.errors[0].lower()


# ---------------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------------


class TestSymbolExtraction:
    def test_extracts_top_level_function(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        names = {s.name for s in result.symbols}
        assert "top_func" in names

    def test_extracts_class(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        classes = [s for s in result.symbols if s.symbol_type == SymbolType.CLASS]
        assert len(classes) == 1
        assert classes[0].name == "Foo"

    def test_method_detected_as_method(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        methods = [s for s in result.symbols if s.symbol_type == SymbolType.METHOD]
        assert len(methods) == 1
        assert methods[0].name == "method"

    def test_top_func_is_function_type(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        funcs = [
            s
            for s in result.symbols
            if s.symbol_type == SymbolType.FUNCTION and s.name == "top_func"
        ]
        assert len(funcs) == 1

    def test_fq_name_includes_module(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        foo = next(s for s in result.symbols if s.name == "Foo")
        assert foo.fq_name == "libs.example.Foo"

    def test_method_fq_name_includes_class(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        method = next(s for s in result.symbols if s.name == "method")
        assert method.fq_name == "libs.example.Foo.method"

    def test_nested_class(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/nested.py", data=CLASS_WITH_NESTED)
        inner = next(s for s in result.symbols if s.name == "Inner")
        assert inner.fq_name == "libs.nested.Outer.Inner"
        assert inner.symbol_type == SymbolType.CLASS

    def test_nested_method_parent(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/nested.py", data=CLASS_WITH_NESTED)
        nm = next(s for s in result.symbols if s.name == "nested_method")
        assert nm.parent_fq_name == "libs.nested.Outer.Inner"
        assert nm.symbol_type == SymbolType.METHOD

    def test_start_end_lines(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        foo = next(s for s in result.symbols if s.name == "Foo")
        # Class starts at line 4, method ends at line 9
        assert foo.start_line >= 4
        assert foo.end_line >= foo.start_line


# ---------------------------------------------------------------------------
# Docstring extraction
# ---------------------------------------------------------------------------


class TestDocstrings:
    def test_class_docstring(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        foo = next(s for s in result.symbols if s.name == "Foo")
        assert foo.docstring is not None
        assert "Foo docstring" in foo.docstring

    def test_method_docstring(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        method = next(s for s in result.symbols if s.name == "method")
        assert method.docstring is not None
        assert "Method doc" in method.docstring

    def test_no_docstring(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        func = next(s for s in result.symbols if s.name == "top_func")
        assert func.docstring is None


# ---------------------------------------------------------------------------
# Signature extraction
# ---------------------------------------------------------------------------


class TestSignatures:
    def test_function_signature(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        func = next(s for s in result.symbols if s.name == "top_func")
        assert func.signature is not None
        assert "top_func" in func.signature
        assert "a" in func.signature

    def test_method_signature(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        method = next(s for s in result.symbols if s.name == "method")
        assert method.signature is not None
        assert "self" in method.signature

    def test_class_has_no_signature(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        foo = next(s for s in result.symbols if s.name == "Foo")
        assert foo.signature is None


# ---------------------------------------------------------------------------
# Relations: DEFINES
# ---------------------------------------------------------------------------


class TestDefinesRelations:
    def test_defines_for_each_symbol(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        defines = [r for r in result.relations if r.relation_type == RelationType.DEFINES]
        defined_refs = {r.dst_ref for r in defines}
        assert "libs.example.Foo" in defined_refs
        assert "libs.example.Foo.method" in defined_refs
        assert "libs.example.top_func" in defined_refs

    def test_defines_src_is_file(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        defines = [r for r in result.relations if r.relation_type == RelationType.DEFINES]
        for d in defines:
            assert d.src_type == "file"
            assert d.src_ref == "libs/example.py"


# ---------------------------------------------------------------------------
# Relations: IMPORTS
# ---------------------------------------------------------------------------


class TestImportRelations:
    def test_plain_import(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=IMPORT_ONLY)
        imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
        refs = {r.dst_ref for r in imports}
        assert "json" in refs

    def test_from_import(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=IMPORT_ONLY)
        imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
        refs = {r.dst_ref for r in imports}
        assert "collections.OrderedDict" in refs

    def test_from_import_dst_type_symbol(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=IMPORT_ONLY)
        od_rel = next(
            r
            for r in result.relations
            if r.relation_type == RelationType.IMPORTS and r.dst_ref == "collections.OrderedDict"
        )
        assert od_rel.dst_type == "symbol"

    def test_plain_import_dst_type_module(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=IMPORT_ONLY)
        json_rel = next(
            r
            for r in result.relations
            if r.relation_type == RelationType.IMPORTS and r.dst_ref == "json"
        )
        assert json_rel.dst_type == "module"

    def test_mixed_code_imports(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
        refs = {r.dst_ref for r in imports}
        assert "os" in refs
        assert "pathlib.Path" in refs


# ---------------------------------------------------------------------------
# _module_fq
# ---------------------------------------------------------------------------


class TestModuleFq:
    def test_simple_python(self) -> None:
        assert TreeSitterParser._module_fq("libs/parsers/python.py") == "libs.parsers.python"

    def test_init_py(self) -> None:
        assert TreeSitterParser._module_fq("libs/core/__init__.py") == "libs.core"

    def test_typescript(self) -> None:
        assert TreeSitterParser._module_fq("src/utils/helper.ts") == "src.utils.helper"

    def test_go_file(self) -> None:
        assert TreeSitterParser._module_fq("pkg/server/main.go") == "pkg.server.main"

    def test_rust_mod(self) -> None:
        assert TreeSitterParser._module_fq("src/parser/mod.rs") == "src.parser"

    def test_backslash_normalized(self) -> None:
        assert TreeSitterParser._module_fq("libs\\core\\paths.py") == "libs.core.paths"


# ---------------------------------------------------------------------------
# Empty / edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_file(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="empty.py", data=b"")
        assert result.symbols == ()
        assert result.relations == ()
        assert result.errors == ()

    def test_comment_only(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="comment.py", data=b"# just a comment\n")
        assert result.symbols == ()

    def test_file_path_in_all_symbols(self) -> None:
        parser = DummyPythonParser()
        result = parser.parse(file_path="libs/example.py", data=SIMPLE_CODE)
        for sym in result.symbols:
            assert sym.file_path == "libs/example.py"
