"""Tests for Rust parser."""

from __future__ import annotations

from libs.core.entities import RelationType, SymbolType
from libs.parsers.rust import RustParser

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RUST_CODE = b"""\
use std::collections::HashMap;
use serde::Deserialize;

const MAX_SIZE: usize = 1024;

static GLOBAL_FLAG: bool = true;

struct Config {
    name: String,
    value: i32,
}

enum Status {
    Active,
    Inactive,
}

trait Processor {
    fn process(&self) -> bool;
}

impl Processor for Config {
    fn process(&self) -> bool {
        true
    }
}

fn main() {
    let cfg = Config { name: "test".into(), value: 42 };
    cfg.process();
}

mod helpers {
    pub fn util() -> i32 { 0 }
}
"""

MINIMAL_RUST = b"""\
fn hello() {}
"""

TEST_RUST = b"""\
#[cfg(test)]
mod tests {
    #[test]
    fn test_it() {
        assert_eq!(1, 1);
    }
}
"""

EMPTY_RUST = b""


# ---------------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------------


class TestSymbolExtraction:
    def test_extracts_function(self) -> None:
        parser = RustParser()
        result = parser.parse(file_path="src/main.rs", data=RUST_CODE)
        funcs = [
            s for s in result.symbols if s.name == "main" and s.symbol_type == SymbolType.FUNCTION
        ]
        assert len(funcs) == 1

    def test_extracts_struct(self) -> None:
        parser = RustParser()
        result = parser.parse(file_path="src/main.rs", data=RUST_CODE)
        structs = [s for s in result.symbols if s.name == "Config"]
        assert len(structs) == 1
        assert structs[0].symbol_type == SymbolType.CLASS

    def test_extracts_enum(self) -> None:
        parser = RustParser()
        result = parser.parse(file_path="src/main.rs", data=RUST_CODE)
        enums = [s for s in result.symbols if s.name == "Status"]
        assert len(enums) == 1
        assert enums[0].symbol_type == SymbolType.CLASS

    def test_extracts_trait(self) -> None:
        parser = RustParser()
        result = parser.parse(file_path="src/main.rs", data=RUST_CODE)
        traits = [s for s in result.symbols if s.name == "Processor"]
        assert len(traits) == 1
        assert traits[0].symbol_type == SymbolType.CLASS

    def test_extracts_const(self) -> None:
        parser = RustParser()
        result = parser.parse(file_path="src/main.rs", data=RUST_CODE)
        consts = [s for s in result.symbols if s.name == "MAX_SIZE"]
        assert len(consts) == 1
        assert consts[0].symbol_type == SymbolType.CONSTANT

    def test_extracts_static(self) -> None:
        parser = RustParser()
        result = parser.parse(file_path="src/main.rs", data=RUST_CODE)
        statics = [s for s in result.symbols if s.name == "GLOBAL_FLAG"]
        assert len(statics) == 1
        assert statics[0].symbol_type == SymbolType.CONSTANT

    def test_extracts_mod(self) -> None:
        parser = RustParser()
        result = parser.parse(file_path="src/main.rs", data=RUST_CODE)
        mods = [s for s in result.symbols if s.name == "helpers"]
        assert len(mods) == 1
        assert mods[0].symbol_type == SymbolType.MODULE

    def test_symbol_types_correct(self) -> None:
        parser = RustParser()
        result = parser.parse(file_path="src/main.rs", data=RUST_CODE)
        sym_map = {s.name: s.symbol_type for s in result.symbols}
        assert sym_map["main"] == SymbolType.FUNCTION
        assert sym_map["Config"] == SymbolType.CLASS
        assert sym_map["Status"] == SymbolType.CLASS
        assert sym_map["Processor"] == SymbolType.CLASS
        assert sym_map["MAX_SIZE"] == SymbolType.CONSTANT
        assert sym_map["helpers"] == SymbolType.MODULE


# ---------------------------------------------------------------------------
# Import relations
# ---------------------------------------------------------------------------


class TestImportRelations:
    def test_records_imports(self) -> None:
        parser = RustParser()
        result = parser.parse(file_path="src/main.rs", data=RUST_CODE)
        imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
        refs = {r.dst_ref for r in imports}
        assert "std::collections::HashMap" in refs
        assert "serde::Deserialize" in refs

    def test_import_dst_type(self) -> None:
        parser = RustParser()
        result = parser.parse(file_path="src/main.rs", data=RUST_CODE)
        imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
        for imp in imports:
            assert imp.dst_type == "module"


# ---------------------------------------------------------------------------
# Role detection
# ---------------------------------------------------------------------------


class TestRoleDetection:
    def test_source_role(self) -> None:
        parser = RustParser()
        result = parser.parse(file_path="src/main.rs", data=RUST_CODE)
        assert result.role == "source"

    def test_test_role_tests_dir(self) -> None:
        parser = RustParser()
        result = parser.parse(file_path="tests/integration.rs", data=TEST_RUST)
        assert result.role == "test"

    def test_test_role_suffix(self) -> None:
        parser = RustParser()
        result = parser.parse(file_path="src/main_test.rs", data=TEST_RUST)
        assert result.role == "test"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_minimal_file(self) -> None:
        parser = RustParser()
        result = parser.parse(file_path="src/lib.rs", data=MINIMAL_RUST)
        names = {s.name for s in result.symbols}
        assert "hello" in names

    def test_empty_file(self) -> None:
        parser = RustParser()
        result = parser.parse(file_path="src/empty.rs", data=EMPTY_RUST)
        assert result.symbols == ()
        assert result.errors == ()

    def test_module_fq_strips_src(self) -> None:
        assert RustParser._module_fq("src/parser/lexer.rs") == "parser.lexer"

    def test_module_fq_mod_rs(self) -> None:
        assert RustParser._module_fq("src/parser/mod.rs") == "parser"
