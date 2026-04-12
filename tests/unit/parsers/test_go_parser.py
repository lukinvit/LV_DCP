"""Tests for Go parser."""

from __future__ import annotations

from libs.core.entities import RelationType, SymbolType
from libs.parsers.golang import GoParser

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GO_CODE = b"""\
package main

import (
\t"fmt"
\t"net/http"
)

const MaxRetries = 10

type Server struct {
\tAddr string
}

func (s *Server) Start() error {
\treturn http.ListenAndServe(s.Addr, nil)
}

func main() {
\tfmt.Println("hello")
}
"""

MINIMAL_GO = b"""\
package main

func hello() {}
"""

TEST_GO = b"""\
package main

import "testing"

func TestHello(t *testing.T) {}
"""

EMPTY_GO = b""


# ---------------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------------


class TestSymbolExtraction:
    def test_extracts_function(self) -> None:
        parser = GoParser()
        result = parser.parse(file_path="cmd/main.go", data=GO_CODE)
        funcs = [
            s for s in result.symbols if s.name == "main" and s.symbol_type == SymbolType.FUNCTION
        ]
        assert len(funcs) == 1

    def test_extracts_method(self) -> None:
        parser = GoParser()
        result = parser.parse(file_path="cmd/main.go", data=GO_CODE)
        methods = [s for s in result.symbols if s.symbol_type == SymbolType.METHOD]
        assert len(methods) == 1
        assert methods[0].name == "Start"

    def test_extracts_type(self) -> None:
        parser = GoParser()
        result = parser.parse(file_path="cmd/main.go", data=GO_CODE)
        types = [s for s in result.symbols if s.name == "Server"]
        assert len(types) == 1
        assert types[0].symbol_type == SymbolType.CLASS

    def test_extracts_constant(self) -> None:
        parser = GoParser()
        result = parser.parse(file_path="cmd/main.go", data=GO_CODE)
        consts = [s for s in result.symbols if s.symbol_type == SymbolType.CONSTANT]
        assert len(consts) == 1
        assert consts[0].name == "MaxRetries"

    def test_symbol_types_correct(self) -> None:
        parser = GoParser()
        result = parser.parse(file_path="cmd/main.go", data=GO_CODE)
        sym_map = {s.name: s.symbol_type for s in result.symbols}
        assert sym_map["main"] == SymbolType.FUNCTION
        assert sym_map["Start"] == SymbolType.METHOD
        assert sym_map["Server"] == SymbolType.CLASS
        assert sym_map["MaxRetries"] == SymbolType.CONSTANT


# ---------------------------------------------------------------------------
# Import relations
# ---------------------------------------------------------------------------


class TestImportRelations:
    def test_records_imports(self) -> None:
        parser = GoParser()
        result = parser.parse(file_path="cmd/main.go", data=GO_CODE)
        imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
        refs = {r.dst_ref for r in imports}
        assert "fmt" in refs
        assert "net/http" in refs

    def test_import_dst_type(self) -> None:
        parser = GoParser()
        result = parser.parse(file_path="cmd/main.go", data=GO_CODE)
        imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
        for imp in imports:
            assert imp.dst_type == "module"


# ---------------------------------------------------------------------------
# Role detection
# ---------------------------------------------------------------------------


class TestRoleDetection:
    def test_source_role(self) -> None:
        parser = GoParser()
        result = parser.parse(file_path="cmd/main.go", data=GO_CODE)
        assert result.role == "source"

    def test_test_role(self) -> None:
        parser = GoParser()
        result = parser.parse(file_path="cmd/main_test.go", data=TEST_GO)
        assert result.role == "test"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_minimal_file(self) -> None:
        parser = GoParser()
        result = parser.parse(file_path="cmd/hello.go", data=MINIMAL_GO)
        names = {s.name for s in result.symbols}
        assert "hello" in names

    def test_empty_file(self) -> None:
        parser = GoParser()
        result = parser.parse(file_path="cmd/empty.go", data=EMPTY_GO)
        assert result.symbols == ()
        assert result.errors == ()

    def test_module_fq(self) -> None:
        assert GoParser._module_fq("pkg/server/main.go") == "pkg.server.main"
