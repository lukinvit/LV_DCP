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


# ---------------------------------------------------------------------------
# tests_for inference
# ---------------------------------------------------------------------------


GO_TEST_WITH_INTERNAL_IMPORT = b"""\
package service

import (
\t"testing"
\t"github.com/google/uuid"
\t"github.com/x5/bm/services/voting-service/internal/repository"
\t"github.com/x5/bm/services/voting-service/internal/model"
)

func TestService_Create(t *testing.T) {
\t_ = uuid.New()
\t_ = repository.BallotRepository{}
\t_ = model.Voting{}
}
"""

GO_TEST_WITH_STDLIB_ONLY = b"""\
package helper

import (
\t"testing"
\t"fmt"
)

func TestHelper(t *testing.T) {
\tfmt.Println("x")
}
"""


class TestTestsForInference:
    def test_project_internal_import_produces_tests_for(self) -> None:
        """Test file importing `github.com/<org>/<repo>/<path>` → TESTS_FOR(<path>)."""
        parser = GoParser()
        result = parser.parse(
            file_path="services/voting-service/internal/service/voting_test.go",
            data=GO_TEST_WITH_INTERNAL_IMPORT,
        )
        tests_for = [r for r in result.relations if r.relation_type == RelationType.TESTS_FOR]
        dsts = {r.dst_ref for r in tests_for}
        # Package directory + <package_name>.go heuristic
        assert "services/voting-service/internal/repository/repository.go" in dsts
        assert "services/voting-service/internal/model/model.go" in dsts

    def test_stdlib_and_third_party_skipped(self) -> None:
        """Standard library and external third-party imports must not produce TESTS_FOR."""
        parser = GoParser()
        result = parser.parse(
            file_path="services/voting-service/internal/service/voting_test.go",
            data=GO_TEST_WITH_INTERNAL_IMPORT,
        )
        tests_for = [r for r in result.relations if r.relation_type == RelationType.TESTS_FOR]
        dsts = {r.dst_ref for r in tests_for}
        # `github.com/google/uuid` has no project-root segment after stripping — must skip
        assert not any("uuid" in d for d in dsts)
        assert not any(d.startswith("testing") for d in dsts)

    def test_source_file_produces_no_tests_for(self) -> None:
        """Non-_test.go files must never produce TESTS_FOR relations."""
        parser = GoParser()
        result = parser.parse(
            file_path="services/voting-service/internal/service/service.go",
            data=GO_TEST_WITH_INTERNAL_IMPORT,
        )
        tests_for = [r for r in result.relations if r.relation_type == RelationType.TESTS_FOR]
        assert tests_for == []

    def test_stdlib_only_test_produces_nothing(self) -> None:
        parser = GoParser()
        result = parser.parse(
            file_path="pkg/helper/helper_test.go",
            data=GO_TEST_WITH_STDLIB_ONLY,
        )
        tests_for = [r for r in result.relations if r.relation_type == RelationType.TESTS_FOR]
        assert tests_for == []
