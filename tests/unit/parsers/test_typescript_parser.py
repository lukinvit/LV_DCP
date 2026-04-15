"""Tests for TypeScript / JavaScript parser."""

from __future__ import annotations

from libs.core.entities import RelationType, SymbolType
from libs.parsers.typescript import TypeScriptParser

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TS_CODE = b"""\
import { Foo } from './foo';
import * as path from 'path';

interface Greeter {
  greet(): string;
}

type ID = string | number;

enum Color {
  Red,
  Green,
  Blue,
}

const MAX_RETRIES = 5;
const API_URL = "https://example.com";

class MyService implements Greeter {
  greet(): string {
    return "hello";
  }

  private helper(x: number): number {
    return x + 1;
  }
}

function main(args: string[]): void {
  console.log("hello");
}
"""

JS_CODE = b"""\
import express from 'express';

const PORT = 3000;

class App {
  start() {
    console.log("started");
  }
}

function run() {
  const app = new App();
  app.start();
}
"""

EMPTY_CODE = b""

TEST_FILE_CODE = b"""\
function testHelper() {}
"""

DTSFILE_CODE = b"""\
export declare function foo(): void;
"""


# ---------------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------------


class TestSymbolExtraction:
    def test_extracts_class(self) -> None:
        parser = TypeScriptParser()
        result = parser.parse(file_path="src/service.ts", data=TS_CODE)
        classes = [s for s in result.symbols if s.name == "MyService"]
        assert len(classes) == 1
        assert classes[0].symbol_type == SymbolType.CLASS

    def test_extracts_function(self) -> None:
        parser = TypeScriptParser()
        result = parser.parse(file_path="src/service.ts", data=TS_CODE)
        funcs = [
            s for s in result.symbols if s.name == "main" and s.symbol_type == SymbolType.FUNCTION
        ]
        assert len(funcs) == 1

    def test_extracts_interface(self) -> None:
        parser = TypeScriptParser()
        result = parser.parse(file_path="src/service.ts", data=TS_CODE)
        ifaces = [s for s in result.symbols if s.name == "Greeter"]
        assert len(ifaces) == 1
        assert ifaces[0].symbol_type == SymbolType.CLASS

    def test_extracts_enum(self) -> None:
        parser = TypeScriptParser()
        result = parser.parse(file_path="src/service.ts", data=TS_CODE)
        enums = [s for s in result.symbols if s.name == "Color"]
        assert len(enums) == 1
        assert enums[0].symbol_type == SymbolType.CLASS

    def test_extracts_type_alias(self) -> None:
        parser = TypeScriptParser()
        result = parser.parse(file_path="src/service.ts", data=TS_CODE)
        types = [s for s in result.symbols if s.name == "ID"]
        assert len(types) == 1
        assert types[0].symbol_type == SymbolType.CLASS

    def test_extracts_methods(self) -> None:
        parser = TypeScriptParser()
        result = parser.parse(file_path="src/service.ts", data=TS_CODE)
        methods = [s for s in result.symbols if s.symbol_type == SymbolType.METHOD]
        method_names = {m.name for m in methods}
        assert "greet" in method_names
        assert "helper" in method_names

    def test_extracts_constants(self) -> None:
        parser = TypeScriptParser()
        result = parser.parse(file_path="src/service.ts", data=TS_CODE)
        consts = [s for s in result.symbols if s.symbol_type == SymbolType.CONSTANT]
        const_names = {c.name for c in consts}
        assert "MAX_RETRIES" in const_names
        assert "API_URL" in const_names

    def test_symbol_types_correct(self) -> None:
        parser = TypeScriptParser()
        result = parser.parse(file_path="src/service.ts", data=TS_CODE)
        sym_map = {s.name: s.symbol_type for s in result.symbols}
        assert sym_map["MyService"] == SymbolType.CLASS
        assert sym_map["main"] == SymbolType.FUNCTION
        assert sym_map["Greeter"] == SymbolType.CLASS
        assert sym_map["Color"] == SymbolType.CLASS
        assert sym_map["MAX_RETRIES"] == SymbolType.CONSTANT


# ---------------------------------------------------------------------------
# Import relations
# ---------------------------------------------------------------------------


class TestImportRelations:
    def test_records_import_relations(self) -> None:
        parser = TypeScriptParser()
        result = parser.parse(file_path="src/service.ts", data=TS_CODE)
        imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
        refs = {r.dst_ref for r in imports}
        assert "./foo" in refs
        assert "path" in refs

    def test_import_dst_type_module(self) -> None:
        parser = TypeScriptParser()
        result = parser.parse(file_path="src/service.ts", data=TS_CODE)
        imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
        for imp in imports:
            assert imp.dst_type == "module"


# ---------------------------------------------------------------------------
# Role detection
# ---------------------------------------------------------------------------


class TestRoleDetection:
    def test_source_role(self) -> None:
        parser = TypeScriptParser()
        result = parser.parse(file_path="src/service.ts", data=TS_CODE)
        assert result.role == "source"

    def test_test_role_test_ts(self) -> None:
        parser = TypeScriptParser()
        result = parser.parse(file_path="src/service.test.ts", data=TEST_FILE_CODE)
        assert result.role == "test"

    def test_test_role_spec_ts(self) -> None:
        parser = TypeScriptParser()
        result = parser.parse(file_path="src/service.spec.ts", data=TEST_FILE_CODE)
        assert result.role == "test"

    def test_test_role_tests_dir(self) -> None:
        parser = TypeScriptParser()
        result = parser.parse(file_path="src/__tests__/service.ts", data=TEST_FILE_CODE)
        assert result.role == "test"

    def test_config_role_dts(self) -> None:
        parser = TypeScriptParser()
        result = parser.parse(file_path="types/global.d.ts", data=DTSFILE_CODE)
        assert result.role == "config"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_file(self) -> None:
        parser = TypeScriptParser()
        result = parser.parse(file_path="empty.ts", data=EMPTY_CODE)
        assert result.symbols == ()
        assert result.errors == ()

    def test_js_code_works(self) -> None:
        parser = TypeScriptParser()
        parser.language = "javascript"
        result = parser.parse(file_path="src/app.js", data=JS_CODE)
        names = {s.name for s in result.symbols}
        assert "App" in names
        assert "run" in names
        assert "PORT" in names

    def test_js_extracts_import(self) -> None:
        parser = TypeScriptParser()
        parser.language = "javascript"
        result = parser.parse(file_path="src/app.js", data=JS_CODE)
        imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
        refs = {r.dst_ref for r in imports}
        assert "express" in refs


# ---------------------------------------------------------------------------
# tests_for inference (Phase 7a follow-up)
# ---------------------------------------------------------------------------


TEST_WITH_ALIAS_IMPORT = b"""\
import { LLMManager } from '@/lib/chat/llm-manager';
import type { LLMRequest } from '@/types/llm';
import { describe, it, expect } from 'vitest';
"""

TEST_WITH_RELATIVE_IMPORT = b"""\
import { BusinessFlow } from '../business-flow';
import { FlowEngine } from './flow-engine';
import { describe, it, expect } from 'vitest';
"""

TEST_WITH_EXTERNAL_ONLY = b"""\
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
"""


class TestTestsForInference:
    def test_alias_import_in_unit_test_produces_tests_for(self) -> None:
        parser = TypeScriptParser()
        result = parser.parse(
            file_path="tests/unit/chat/llm-manager.test.ts",
            data=TEST_WITH_ALIAS_IMPORT,
        )
        tests_for = [r for r in result.relations if r.relation_type == RelationType.TESTS_FOR]
        dsts = {r.dst_ref for r in tests_for}
        assert "src/lib/chat/llm-manager.ts" in dsts

    def test_relative_import_resolved_against_source_dir(self) -> None:
        parser = TypeScriptParser()
        result = parser.parse(
            file_path="src/lib/chat/flows/__tests__/business-flow.test.ts",
            data=TEST_WITH_RELATIVE_IMPORT,
        )
        tests_for = [r for r in result.relations if r.relation_type == RelationType.TESTS_FOR]
        dsts = {r.dst_ref for r in tests_for}
        assert "src/lib/chat/flows/business-flow.ts" in dsts
        assert "src/lib/chat/flows/__tests__/flow-engine.ts" in dsts

    def test_external_packages_skipped(self) -> None:
        parser = TypeScriptParser()
        result = parser.parse(
            file_path="tests/unit/foo.test.ts",
            data=TEST_WITH_EXTERNAL_ONLY,
        )
        tests_for = [r for r in result.relations if r.relation_type == RelationType.TESTS_FOR]
        assert tests_for == []

    def test_source_file_gets_no_tests_for(self) -> None:
        """Non-test files must never produce TESTS_FOR relations."""
        parser = TypeScriptParser()
        result = parser.parse(
            file_path="src/lib/chat/llm-manager.ts",
            data=TEST_WITH_ALIAS_IMPORT,
        )
        tests_for = [r for r in result.relations if r.relation_type == RelationType.TESTS_FOR]
        assert tests_for == []
