# Phase 6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand LV_DCP from Python-centric to polyglot: tree-sitter parsers for TS/JS/Go/Rust, Qdrant vector store, Obsidian vault sync, VS Code extension MVP, and cross-project patterns.

**Architecture:** Each new parser extends a shared `TreeSitterParser` base class in `libs/parsers/`. Qdrant integration lives in new `libs/embeddings/` module, gated by config flag. Obsidian sync is `libs/obsidian/` generating Jinja2-templated markdown. VS Code extension in `apps/vscode/` communicates via CLI subprocess. All follow existing `FileParser` protocol and `ParseResult` contract.

**Tech Stack:** tree-sitter (TS/JS/Go/Rust grammars), qdrant-client (async), OpenAI embeddings API, Jinja2 (Obsidian templates), TypeScript (VS Code extension)

---

## File Structure

### New files

```
libs/parsers/treesitter_base.py      — shared tree-sitter parser base class
libs/parsers/typescript.py            — TS/JS parser
libs/parsers/golang.py                — Go parser
libs/parsers/rust.py                  — Rust parser
libs/embeddings/__init__.py           — package init
libs/embeddings/adapter.py            — EmbeddingAdapter protocol + OpenAI impl
libs/embeddings/qdrant_store.py       — Qdrant client wrapper (4 collections)
libs/embeddings/chunker.py            — code-aware chunking
libs/obsidian/__init__.py             — package init
libs/obsidian/publisher.py            — vault sync orchestrator
libs/obsidian/templates.py            — Jinja2 page templates
libs/obsidian/models.py               — VaultConfig, SyncState, SyncReport
libs/patterns/__init__.py             — package init
libs/patterns/detector.py             — cross-project pattern detection
apps/cli/commands/obsidian_cmd.py     — ctx obsidian sync/status
apps/vscode/                          — VS Code extension (TypeScript)
tests/unit/parsers/test_treesitter_base.py
tests/unit/parsers/test_typescript_parser.py
tests/unit/parsers/test_go_parser.py
tests/unit/parsers/test_rust_parser.py
tests/unit/embeddings/test_adapter.py
tests/unit/embeddings/test_qdrant_store.py
tests/unit/embeddings/test_chunker.py
tests/unit/obsidian/test_publisher.py
tests/unit/obsidian/test_templates.py
tests/unit/patterns/test_detector.py
tests/eval/typescript_queries.yaml
tests/eval/go_queries.yaml
tests/eval/rust_queries.yaml
```

### Modified files

```
libs/parsers/registry.py:9-37        — add new extensions + parsers
libs/core/entities.py:50              — add language string values
libs/retrieval/pipeline.py:151-246    — add optional vector stage + RRF fusion
libs/scanning/scanner.py:146-297     — add optional embedding step post-parse
apps/cli/main.py:1-68                — add obsidian subcommand
pyproject.toml:11-31                  — add new dependencies
```

---

## Group A: Cross-Language Parsers

### Task 1: TreeSitter base class

**Files:**
- Create: `libs/parsers/treesitter_base.py`
- Create: `tests/unit/parsers/test_treesitter_base.py`

- [ ] **Step 1: Write the test for the base class**

```python
# tests/unit/parsers/test_treesitter_base.py
"""Tests for TreeSitterParser base class."""
import tree_sitter_python as tspython
from tree_sitter import Language

from libs.core.entities import SymbolType
from libs.parsers.treesitter_base import TreeSitterParser


class DummyParser(TreeSitterParser):
    language = "python"

    def _get_ts_language(self) -> Language:
        return Language(tspython.language())

    def _symbol_type_map(self) -> dict[str, SymbolType]:
        return {"function_definition": SymbolType.FUNCTION, "class_definition": SymbolType.CLASS}

    def _import_node_types(self) -> set[str]:
        return {"import_from_statement", "import_statement"}

    def _detect_role(self, file_path: str) -> str:
        return "test" if "test" in file_path else "source"


SOURCE = b'''
class Foo:
    pass

def bar():
    pass
'''


def test_base_parser_extracts_symbols_from_tree() -> None:
    result = DummyParser().parse(file_path="example.py", data=SOURCE)
    names = {s.name for s in result.symbols}
    assert "Foo" in names
    assert "bar" in names


def test_base_parser_sets_language_and_role() -> None:
    result = DummyParser().parse(file_path="tests/test_x.py", data=SOURCE)
    assert result.language == "python"
    assert result.role == "test"


def test_base_parser_handles_empty_file() -> None:
    result = DummyParser().parse(file_path="empty.py", data=b"")
    assert result.symbols == ()
    assert result.errors == ()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/parsers/test_treesitter_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'libs.parsers.treesitter_base'`

- [ ] **Step 3: Implement TreeSitterParser base class**

```python
# libs/parsers/treesitter_base.py
"""Shared base class for tree-sitter language parsers.

Subclasses define language-specific queries and node type mappings.
Symbol extraction walks the tree using node type → SymbolType mapping.
Import extraction uses language-specific node types.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import tree_sitter
from tree_sitter import Language, Node

from libs.core.entities import Relation, RelationType, Symbol, SymbolType
from libs.parsers.base import ParseResult


class TreeSitterParser(ABC):
    """Base for all tree-sitter parsers.

    Subclass contract:
    - language: str class attribute
    - _get_ts_language() → Language
    - _symbol_type_map() → {node_type: SymbolType}
    - _import_node_types() → set of node types that represent imports
    - _detect_role(file_path) → role string
    """

    language: str

    def parse(self, *, file_path: str, data: bytes) -> ParseResult:
        ts_lang = self._get_ts_language()
        parser = tree_sitter.Parser(ts_lang)
        tree = parser.parse(data)

        symbols: list[Symbol] = []
        relations: list[Relation] = []

        module_fq = self._module_fq(file_path)
        self._walk_tree(tree.root_node, file_path, module_fq, data, symbols, relations)

        role = self._detect_role(file_path)
        return ParseResult(
            file_path=file_path,
            language=self.language,
            role=role,
            symbols=tuple(symbols),
            relations=tuple(relations),
        )

    def _walk_tree(
        self,
        node: Node,
        file_path: str,
        module_fq: str,
        data: bytes,
        symbols: list[Symbol],
        relations: list[Relation],
        scope_stack: list[str] | None = None,
    ) -> None:
        if scope_stack is None:
            scope_stack = [module_fq]

        sym_map = self._symbol_type_map()
        import_types = self._import_node_types()

        if node.type in sym_map:
            name = self._extract_name(node)
            if name:
                fq = f"{scope_stack[-1]}.{name}"
                symbols.append(
                    Symbol(
                        name=name,
                        fq_name=fq,
                        symbol_type=sym_map[node.type],
                        file_path=file_path,
                        start_line=node.start_point.row + 1,
                        end_line=node.end_point.row + 1,
                        parent_fq_name=scope_stack[-1],
                        docstring=self._extract_docstring(node, data),
                        signature=self._extract_signature(node, data),
                    )
                )
                relations.append(
                    Relation(
                        src_type="file",
                        src_ref=file_path,
                        dst_type="symbol",
                        dst_ref=fq,
                        relation_type=RelationType.DEFINES,
                    )
                )
                scope_stack.append(fq)
                for child in node.children:
                    self._walk_tree(child, file_path, module_fq, data, symbols, relations, scope_stack)
                scope_stack.pop()
                return

        if node.type in import_types:
            import_ref = self._extract_import_ref(node, data)
            if import_ref:
                relations.append(
                    Relation(
                        src_type="file",
                        src_ref=file_path,
                        dst_type="module",
                        dst_ref=import_ref,
                        relation_type=RelationType.IMPORTS,
                    )
                )

        for child in node.children:
            self._walk_tree(child, file_path, module_fq, data, symbols, relations, scope_stack)

    def _extract_name(self, node: Node) -> str | None:
        """Extract the identifier name from a definition node."""
        for child in node.children:
            if child.type in ("identifier", "name", "type_identifier", "property_identifier"):
                return child.text.decode("utf-8") if child.text else None
        return None

    def _extract_docstring(self, node: Node, data: bytes) -> str | None:
        """Override in subclass for language-specific docstring extraction."""
        return None

    def _extract_signature(self, node: Node, data: bytes) -> str | None:
        """Override in subclass for language-specific signature extraction."""
        return None

    def _extract_import_ref(self, node: Node, data: bytes) -> str | None:
        """Override in subclass for language-specific import parsing."""
        text = node.text
        if text:
            return text.decode("utf-8").strip()
        return None

    def _module_fq(self, file_path: str) -> str:
        """Derive module-level fq_name from file path."""
        posix = file_path.replace("\\", "/")
        # Remove common extension suffixes
        for ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"):
            if posix.endswith(ext):
                posix = posix[: -len(ext)]
                break
        # Remove /index suffix (common in TS/JS)
        if posix.endswith("/index"):
            posix = posix[: -len("/index")]
        return posix.replace("/", ".")

    @abstractmethod
    def _get_ts_language(self) -> Language: ...

    @abstractmethod
    def _symbol_type_map(self) -> dict[str, SymbolType]: ...

    @abstractmethod
    def _import_node_types(self) -> set[str]: ...

    @abstractmethod
    def _detect_role(self, file_path: str) -> str: ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/parsers/test_treesitter_base.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add libs/parsers/treesitter_base.py tests/unit/parsers/test_treesitter_base.py
git commit -m "feat(parsers): add TreeSitterParser base class for multi-language support"
```

---

### Task 2: TypeScript/JavaScript parser

**Files:**
- Create: `libs/parsers/typescript.py`
- Create: `tests/unit/parsers/test_typescript_parser.py`
- Modify: `libs/parsers/registry.py:9-37`
- Modify: `pyproject.toml:11-31`

- [ ] **Step 1: Add dependencies**

Add to `pyproject.toml` dependencies list:
```
"tree-sitter-typescript>=0.23",
"tree-sitter-javascript>=0.23",
```

Run: `uv sync`

- [ ] **Step 2: Write tests for TS parser**

```python
# tests/unit/parsers/test_typescript_parser.py
"""Tests for TypeScript/JavaScript parser."""
from libs.core.entities import RelationType, SymbolType
from libs.parsers.typescript import TypeScriptParser

TS_SOURCE = b'''
import { User } from "./models/user";
import express from "express";

const API_URL = "https://example.com";

interface UserService {
    getUser(id: string): Promise<User>;
}

class UserServiceImpl implements UserService {
    async getUser(id: string): Promise<User> {
        return fetch(API_URL);
    }
}

export function createApp(): express.Application {
    return express();
}

enum Status {
    Active = "active",
    Inactive = "inactive",
}
'''

JS_SOURCE = b'''
const express = require("express");

class Router {
    handle(req, res) {
        res.send("ok");
    }
}

function middleware(req, res, next) {
    next();
}

module.exports = { Router, middleware };
'''


def test_ts_extracts_classes_functions_interfaces() -> None:
    result = TypeScriptParser().parse(file_path="src/app.ts", data=TS_SOURCE)
    names = {s.name for s in result.symbols}
    assert "UserService" in names
    assert "UserServiceImpl" in names
    assert "createApp" in names
    assert "Status" in names
    assert "getUser" in names


def test_ts_records_import_relations() -> None:
    result = TypeScriptParser().parse(file_path="src/app.ts", data=TS_SOURCE)
    imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
    assert len(imports) >= 2


def test_ts_detects_test_role() -> None:
    result = TypeScriptParser().parse(file_path="src/__tests__/app.test.ts", data=b"export {};")
    assert result.role == "test"


def test_ts_detects_source_role() -> None:
    result = TypeScriptParser().parse(file_path="src/app.ts", data=TS_SOURCE)
    assert result.role == "source"


def test_ts_symbol_types_correct() -> None:
    result = TypeScriptParser().parse(file_path="src/app.ts", data=TS_SOURCE)
    by_name = {s.name: s for s in result.symbols}
    assert by_name["UserServiceImpl"].symbol_type == SymbolType.CLASS
    assert by_name["createApp"].symbol_type == SymbolType.FUNCTION
    assert by_name["getUser"].symbol_type == SymbolType.METHOD


def test_ts_handles_empty_file() -> None:
    result = TypeScriptParser().parse(file_path="empty.ts", data=b"")
    assert result.symbols == ()


def test_js_extracts_classes_and_functions() -> None:
    parser = TypeScriptParser()
    parser.language = "javascript"
    result = parser.parse(file_path="src/router.js", data=JS_SOURCE)
    names = {s.name for s in result.symbols}
    assert "Router" in names
    assert "middleware" in names
    assert "handle" in names


def test_ts_constant_extraction() -> None:
    result = TypeScriptParser().parse(file_path="src/app.ts", data=TS_SOURCE)
    names = {s.name for s in result.symbols}
    assert "API_URL" in names
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/parsers/test_typescript_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'libs.parsers.typescript'`

- [ ] **Step 4: Implement TypeScript parser**

```python
# libs/parsers/typescript.py
"""TypeScript and JavaScript parser using tree-sitter.

Handles both .ts/.tsx (TypeScript grammar) and .js/.jsx/.mjs/.cjs
(JavaScript grammar). Shared logic in TreeSitterParser base.
"""
from __future__ import annotations

import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
from tree_sitter import Language, Node

from libs.core.entities import Relation, RelationType, SymbolType
from libs.parsers.base import ParseResult
from libs.parsers.treesitter_base import TreeSitterParser

_TS_LANG = Language(tsts.language_typescript())
_JS_LANG = Language(tsjs.language())


class TypeScriptParser(TreeSitterParser):
    language = "typescript"

    def _get_ts_language(self) -> Language:
        return _TS_LANG if self.language == "typescript" else _JS_LANG

    def _symbol_type_map(self) -> dict[str, SymbolType]:
        return {
            "function_declaration": SymbolType.FUNCTION,
            "class_declaration": SymbolType.CLASS,
            "method_definition": SymbolType.METHOD,
            "interface_declaration": SymbolType.CLASS,
            "type_alias_declaration": SymbolType.CLASS,
            "enum_declaration": SymbolType.CLASS,
        }

    def _import_node_types(self) -> set[str]:
        return {"import_statement"}

    def _detect_role(self, file_path: str) -> str:
        fp = file_path.lower()
        if any(
            pat in fp
            for pat in (".test.", ".spec.", "__tests__/", "test/", "tests/")
        ):
            return "test"
        if fp.endswith(".d.ts"):
            return "config"
        return "source"

    def parse(self, *, file_path: str, data: bytes) -> ParseResult:
        result = super().parse(file_path=file_path, data=data)

        # Post-process: extract constants (top-level UPPER_CASE const/var)
        extra_symbols, extra_relations = self._extract_constants(file_path, data)

        return ParseResult(
            file_path=result.file_path,
            language=result.language,
            role=result.role,
            symbols=result.symbols + tuple(extra_symbols),
            relations=result.relations + tuple(extra_relations),
            errors=result.errors,
        )

    def _extract_constants(
        self, file_path: str, data: bytes
    ) -> tuple[list, list]:
        """Extract top-level UPPER_CASE const declarations."""
        from libs.core.entities import Symbol
        import tree_sitter

        ts_lang = self._get_ts_language()
        parser = tree_sitter.Parser(ts_lang)
        tree = parser.parse(data)
        module_fq = self._module_fq(file_path)

        symbols = []
        relations = []
        for child in tree.root_node.children:
            if child.type in ("lexical_declaration", "variable_declaration"):
                for decl in child.children:
                    if decl.type == "variable_declarator":
                        name_node = decl.child_by_field_name("name")
                        if name_node and name_node.text:
                            name = name_node.text.decode("utf-8")
                            if name.isupper() or (name.replace("_", "").isupper() and "_" in name):
                                fq = f"{module_fq}.{name}"
                                symbols.append(
                                    Symbol(
                                        name=name,
                                        fq_name=fq,
                                        symbol_type=SymbolType.CONSTANT,
                                        file_path=file_path,
                                        start_line=child.start_point.row + 1,
                                        end_line=child.end_point.row + 1,
                                        parent_fq_name=module_fq,
                                    )
                                )
                                relations.append(
                                    Relation(
                                        src_type="file",
                                        src_ref=file_path,
                                        dst_type="symbol",
                                        dst_ref=fq,
                                        relation_type=RelationType.DEFINES,
                                    )
                                )
        return symbols, relations

    def _extract_import_ref(self, node: Node, data: bytes) -> str | None:
        """Extract module specifier from import statement."""
        for child in node.children:
            if child.type == "string" or child.type == "string_fragment":
                text = child.text.decode("utf-8") if child.text else None
                if text:
                    return text.strip("'\"")
            # Recurse into from clause
            if child.type == "from":
                continue
            for grandchild in child.children:
                if grandchild.type in ("string", "string_fragment"):
                    text = grandchild.text.decode("utf-8") if grandchild.text else None
                    if text:
                        return text.strip("'\"")
        # Fallback: extract the source string from the whole node text
        text = node.text.decode("utf-8") if node.text else ""
        for quote in ('"', "'"):
            start = text.find(quote)
            if start >= 0:
                end = text.find(quote, start + 1)
                if end > start:
                    return text[start + 1 : end]
        return None
```

- [ ] **Step 5: Update registry with TS/JS extensions**

In `libs/parsers/registry.py`, add to `EXTENSION_TO_LANGUAGE`:
```python
".ts": "typescript",
".tsx": "typescript",
".js": "javascript",
".jsx": "javascript",
".mjs": "javascript",
".cjs": "javascript",
```

Add to `_PARSERS`:
```python
from libs.parsers.typescript import TypeScriptParser

# In _PARSERS dict:
"typescript": TypeScriptParser(),
"javascript": _make_js_parser(),
```

Add helper:
```python
def _make_js_parser() -> TypeScriptParser:
    p = TypeScriptParser()
    p.language = "javascript"
    return p
```

- [ ] **Step 6: Run all tests**

Run: `uv run pytest tests/unit/parsers/test_typescript_parser.py tests/unit/parsers/test_treesitter_base.py tests/unit/parsers/test_registry.py -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add libs/parsers/typescript.py tests/unit/parsers/test_typescript_parser.py libs/parsers/registry.py pyproject.toml
git commit -m "feat(parsers): add TypeScript/JavaScript tree-sitter parser"
```

---

### Task 3: Go parser

**Files:**
- Create: `libs/parsers/golang.py`
- Create: `tests/unit/parsers/test_go_parser.py`
- Modify: `libs/parsers/registry.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependency**

Add to `pyproject.toml`: `"tree-sitter-go>=0.23",`
Run: `uv sync`

- [ ] **Step 2: Write tests for Go parser**

```python
# tests/unit/parsers/test_go_parser.py
"""Tests for Go parser."""
from libs.core.entities import RelationType, SymbolType
from libs.parsers.golang import GoParser

GO_SOURCE = b'''
package handlers

import (
    "fmt"
    "net/http"
)

const MaxRetries = 3

type UserHandler struct {
    db *Database
}

func (h *UserHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
    fmt.Fprintf(w, "ok")
}

func NewUserHandler(db *Database) *UserHandler {
    return &UserHandler{db: db}
}

type Service interface {
    Start() error
    Stop() error
}
'''


def test_go_extracts_functions_and_types() -> None:
    result = GoParser().parse(file_path="handlers/user.go", data=GO_SOURCE)
    names = {s.name for s in result.symbols}
    assert "UserHandler" in names
    assert "ServeHTTP" in names
    assert "NewUserHandler" in names
    assert "Service" in names
    assert "MaxRetries" in names


def test_go_records_imports() -> None:
    result = GoParser().parse(file_path="handlers/user.go", data=GO_SOURCE)
    imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
    assert len(imports) >= 2


def test_go_detects_test_role() -> None:
    result = GoParser().parse(file_path="handlers/user_test.go", data=b"package handlers\n")
    assert result.role == "test"


def test_go_symbol_types() -> None:
    result = GoParser().parse(file_path="handlers/user.go", data=GO_SOURCE)
    by_name = {s.name: s for s in result.symbols}
    assert by_name["UserHandler"].symbol_type == SymbolType.CLASS
    assert by_name["NewUserHandler"].symbol_type == SymbolType.FUNCTION
    assert by_name["Service"].symbol_type == SymbolType.CLASS


def test_go_handles_empty_file() -> None:
    result = GoParser().parse(file_path="main.go", data=b"package main\n")
    assert result.errors == ()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/parsers/test_go_parser.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Implement Go parser**

```python
# libs/parsers/golang.py
"""Go parser using tree-sitter."""
from __future__ import annotations

import tree_sitter_go as tsgo
from tree_sitter import Language, Node

from libs.core.entities import SymbolType
from libs.parsers.treesitter_base import TreeSitterParser

_GO_LANG = Language(tsgo.language())


class GoParser(TreeSitterParser):
    language = "go"

    def _get_ts_language(self) -> Language:
        return _GO_LANG

    def _symbol_type_map(self) -> dict[str, SymbolType]:
        return {
            "function_declaration": SymbolType.FUNCTION,
            "method_declaration": SymbolType.METHOD,
            "type_declaration": SymbolType.CLASS,
            "type_spec": SymbolType.CLASS,
            "const_spec": SymbolType.CONSTANT,
        }

    def _import_node_types(self) -> set[str]:
        return {"import_spec"}

    def _detect_role(self, file_path: str) -> str:
        if file_path.endswith("_test.go"):
            return "test"
        return "source"

    def _extract_import_ref(self, node: Node, data: bytes) -> str | None:
        """Extract Go import path from import_spec node."""
        for child in node.children:
            if child.type == "interpreted_string_literal":
                text = child.text.decode("utf-8") if child.text else None
                if text:
                    return text.strip('"')
        return None

    def _module_fq(self, file_path: str) -> str:
        """Go uses directory-based package paths."""
        posix = file_path.replace("\\", "/")
        if posix.endswith(".go"):
            posix = posix[:-3]
        return posix.replace("/", ".")
```

- [ ] **Step 5: Update registry**

Add to `libs/parsers/registry.py`:
```python
".go": "go"
```
And to `_PARSERS`:
```python
from libs.parsers.golang import GoParser
"go": GoParser(),
```

- [ ] **Step 6: Run all Go tests + existing tests**

Run: `uv run pytest tests/unit/parsers/ -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add libs/parsers/golang.py tests/unit/parsers/test_go_parser.py libs/parsers/registry.py pyproject.toml
git commit -m "feat(parsers): add Go tree-sitter parser"
```

---

### Task 4: Rust parser

**Files:**
- Create: `libs/parsers/rust.py`
- Create: `tests/unit/parsers/test_rust_parser.py`
- Modify: `libs/parsers/registry.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependency**

Add to `pyproject.toml`: `"tree-sitter-rust>=0.23",`
Run: `uv sync`

- [ ] **Step 2: Write tests for Rust parser**

```python
# tests/unit/parsers/test_rust_parser.py
"""Tests for Rust parser."""
from libs.core.entities import RelationType, SymbolType
from libs.parsers.rust import RustParser

RUST_SOURCE = b'''
use std::collections::HashMap;
use crate::models::User;

const MAX_SIZE: usize = 1024;

pub struct Config {
    pub name: String,
    pub value: i32,
}

impl Config {
    pub fn new(name: String) -> Self {
        Config { name, value: 0 }
    }

    pub fn validate(&self) -> bool {
        !self.name.is_empty()
    }
}

pub trait Validator {
    fn validate(&self) -> bool;
}

pub enum Status {
    Active,
    Inactive,
}

pub fn create_config(name: &str) -> Config {
    Config::new(name.to_string())
}

mod tests {
    use super::*;

    fn test_helper() -> bool {
        true
    }
}
'''


def test_rust_extracts_structs_functions_traits() -> None:
    result = RustParser().parse(file_path="src/config.rs", data=RUST_SOURCE)
    names = {s.name for s in result.symbols}
    assert "Config" in names
    assert "new" in names
    assert "validate" in names
    assert "Validator" in names
    assert "Status" in names
    assert "create_config" in names
    assert "MAX_SIZE" in names


def test_rust_records_imports() -> None:
    result = RustParser().parse(file_path="src/config.rs", data=RUST_SOURCE)
    imports = [r for r in result.relations if r.relation_type == RelationType.IMPORTS]
    assert len(imports) >= 2


def test_rust_detects_test_role() -> None:
    result = RustParser().parse(file_path="tests/integration.rs", data=b"fn main() {}\n")
    assert result.role == "test"


def test_rust_symbol_types() -> None:
    result = RustParser().parse(file_path="src/config.rs", data=RUST_SOURCE)
    by_name = {s.name: s for s in result.symbols}
    assert by_name["Config"].symbol_type == SymbolType.CLASS
    assert by_name["create_config"].symbol_type == SymbolType.FUNCTION
    assert by_name["Validator"].symbol_type == SymbolType.CLASS
    assert by_name["Status"].symbol_type == SymbolType.CLASS


def test_rust_handles_empty_file() -> None:
    result = RustParser().parse(file_path="src/lib.rs", data=b"")
    assert result.errors == ()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/parsers/test_rust_parser.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Implement Rust parser**

```python
# libs/parsers/rust.py
"""Rust parser using tree-sitter."""
from __future__ import annotations

import tree_sitter_rust as tsrust
from tree_sitter import Language, Node

from libs.core.entities import SymbolType
from libs.parsers.treesitter_base import TreeSitterParser

_RUST_LANG = Language(tsrust.language())


class RustParser(TreeSitterParser):
    language = "rust"

    def _get_ts_language(self) -> Language:
        return _RUST_LANG

    def _symbol_type_map(self) -> dict[str, SymbolType]:
        return {
            "function_item": SymbolType.FUNCTION,
            "struct_item": SymbolType.CLASS,
            "enum_item": SymbolType.CLASS,
            "trait_item": SymbolType.CLASS,
            "const_item": SymbolType.CONSTANT,
            "static_item": SymbolType.CONSTANT,
            "mod_item": SymbolType.MODULE,
        }

    def _import_node_types(self) -> set[str]:
        return {"use_declaration"}

    def _detect_role(self, file_path: str) -> str:
        fp = file_path.lower()
        if fp.startswith("tests/") or fp.endswith("_test.rs") or "/tests/" in fp:
            return "test"
        return "source"

    def _extract_import_ref(self, node: Node, data: bytes) -> str | None:
        """Extract use path from Rust use_declaration."""
        # use_declaration children include a scoped_identifier or use_wildcard
        text = node.text.decode("utf-8") if node.text else ""
        # Strip "use " prefix and trailing ";"
        text = text.strip()
        if text.startswith("use "):
            text = text[4:]
        if text.endswith(";"):
            text = text[:-1]
        return text.strip() if text else None

    def _module_fq(self, file_path: str) -> str:
        """Rust module path uses :: separator convention."""
        posix = file_path.replace("\\", "/")
        if posix.endswith(".rs"):
            posix = posix[:-3]
        # src/handlers/auth.rs → crate.handlers.auth (using dots for internal consistency)
        if posix.startswith("src/"):
            posix = posix[4:]
        return posix.replace("/", ".")
```

- [ ] **Step 5: Update registry**

Add to `libs/parsers/registry.py`:
```python
".rs": "rust"
```
And to `_PARSERS`:
```python
from libs.parsers.rust import RustParser
"rust": RustParser(),
```

- [ ] **Step 6: Run all parser tests**

Run: `uv run pytest tests/unit/parsers/ -v`
Expected: All pass

- [ ] **Step 7: Run full test suite for regressions**

Run: `uv run pytest -x -q`
Expected: All existing tests still pass

- [ ] **Step 8: Commit**

```bash
git add libs/parsers/rust.py tests/unit/parsers/test_rust_parser.py libs/parsers/registry.py pyproject.toml
git commit -m "feat(parsers): add Rust tree-sitter parser"
```

---

## Group B: Qdrant Vector Store

### Task 5: Embedding adapter

**Files:**
- Create: `libs/embeddings/__init__.py`
- Create: `libs/embeddings/adapter.py`
- Create: `tests/unit/embeddings/__init__.py`
- Create: `tests/unit/embeddings/test_adapter.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add qdrant-client dependency**

Add to `pyproject.toml`: `"qdrant-client>=1.9",`
Run: `uv sync`

- [ ] **Step 2: Write adapter tests**

```python
# tests/unit/embeddings/test_adapter.py
"""Tests for embedding adapter."""
import pytest

from libs.embeddings.adapter import EmbeddingAdapter, FakeEmbeddingAdapter


def test_fake_adapter_returns_correct_dimension() -> None:
    adapter = FakeEmbeddingAdapter(dimension=128)
    assert adapter.dimension == 128
    assert adapter.model_name == "fake-128"


@pytest.mark.asyncio
async def test_fake_adapter_embed_batch() -> None:
    adapter = FakeEmbeddingAdapter(dimension=64)
    vectors = await adapter.embed_batch(["hello", "world"])
    assert len(vectors) == 2
    assert len(vectors[0]) == 64
    assert len(vectors[1]) == 64


@pytest.mark.asyncio
async def test_fake_adapter_deterministic_for_same_input() -> None:
    adapter = FakeEmbeddingAdapter(dimension=32)
    v1 = await adapter.embed_batch(["hello"])
    v2 = await adapter.embed_batch(["hello"])
    assert v1[0] == v2[0]


@pytest.mark.asyncio
async def test_fake_adapter_different_for_different_input() -> None:
    adapter = FakeEmbeddingAdapter(dimension=32)
    v1 = await adapter.embed_batch(["hello"])
    v2 = await adapter.embed_batch(["world"])
    assert v1[0] != v2[0]


def test_embedding_adapter_protocol_compliance() -> None:
    adapter = FakeEmbeddingAdapter()
    assert isinstance(adapter, EmbeddingAdapter)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/embeddings/test_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Implement adapter**

```python
# libs/embeddings/__init__.py
"""Embedding adapters and vector store integration."""

# libs/embeddings/adapter.py
"""Embedding adapter protocol and implementations."""
from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingAdapter(Protocol):
    @property
    def dimension(self) -> int: ...

    @property
    def model_name(self) -> str: ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbeddingAdapter:
    """Deterministic fake adapter for testing. No API calls."""

    def __init__(self, dimension: int = 1536) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return f"fake-{self._dimension}"

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._deterministic_vector(t) for t in texts]

    def _deterministic_vector(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).digest()
        # Expand hash to fill dimension
        raw: list[float] = []
        seed = int.from_bytes(h[:8], "little")
        for i in range(self._dimension):
            # Simple LCG-like deterministic float generation
            seed = (seed * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
            raw.append((seed >> 33) / (1 << 31) - 1.0)  # normalize to [-1, 1]
        # L2-normalize
        norm = sum(x * x for x in raw) ** 0.5
        if norm > 0:
            raw = [x / norm for x in raw]
        return raw


class OpenAIEmbeddingAdapter:
    """Uses OpenAI-compatible API for text-embedding-3-small."""

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._model = model
        self._dimension = 1536
        from openai import AsyncOpenAI  # noqa: PLC0415

        kwargs: dict = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**kwargs)

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
        )
        return [item.embedding for item in response.data]
```

- [ ] **Step 5: Create `__init__.py` files**

```python
# tests/unit/embeddings/__init__.py
# (empty)
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/unit/embeddings/test_adapter.py -v`
Expected: 5 passed

- [ ] **Step 7: Commit**

```bash
git add libs/embeddings/ tests/unit/embeddings/ pyproject.toml
git commit -m "feat(embeddings): add embedding adapter protocol with fake + OpenAI implementations"
```

---

### Task 6: Code-aware chunker

**Files:**
- Create: `libs/embeddings/chunker.py`
- Create: `tests/unit/embeddings/test_chunker.py`

- [ ] **Step 1: Write chunker tests**

```python
# tests/unit/embeddings/test_chunker.py
"""Tests for code-aware chunker."""
from libs.embeddings.chunker import Chunk, chunk_file


PYTHON_CODE = """
class UserService:
    def get_user(self, user_id: str):
        return self.db.find(user_id)

    def create_user(self, name: str):
        return self.db.insert(name)


def standalone_helper():
    return 42
"""


def test_chunk_file_returns_chunks() -> None:
    chunks = chunk_file("svc.py", PYTHON_CODE, max_tokens=50)
    assert len(chunks) >= 1
    assert all(isinstance(c, Chunk) for c in chunks)


def test_chunk_has_metadata() -> None:
    chunks = chunk_file("svc.py", PYTHON_CODE, max_tokens=50)
    for chunk in chunks:
        assert chunk.file_path == "svc.py"
        assert chunk.start_line >= 1
        assert chunk.end_line >= chunk.start_line
        assert len(chunk.text) > 0


def test_chunk_respects_max_tokens() -> None:
    # Very small max_tokens forces multiple chunks
    chunks = chunk_file("svc.py", PYTHON_CODE, max_tokens=20)
    assert len(chunks) >= 2


def test_empty_file_returns_empty() -> None:
    chunks = chunk_file("empty.py", "", max_tokens=100)
    assert chunks == []


def test_small_file_single_chunk() -> None:
    chunks = chunk_file("small.py", "x = 1\n", max_tokens=500)
    assert len(chunks) == 1
```

- [ ] **Step 2: Run tests to verify fail**

Run: `uv run pytest tests/unit/embeddings/test_chunker.py -v`
Expected: FAIL

- [ ] **Step 3: Implement chunker**

```python
# libs/embeddings/chunker.py
"""Code-aware chunking for vector store indexing.

Splits source files into chunks that respect symbol boundaries
(never splitting a function mid-body). Uses tiktoken for token counting.
"""
from __future__ import annotations

from dataclasses import dataclass

import tiktoken

_ENCODING = tiktoken.get_encoding("cl100k_base")


@dataclass(frozen=True)
class Chunk:
    file_path: str
    text: str
    start_line: int
    end_line: int


def _count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def chunk_file(
    file_path: str,
    content: str,
    *,
    max_tokens: int = 512,
) -> list[Chunk]:
    """Split a file into chunks respecting line boundaries.

    Strategy: accumulate lines until max_tokens is reached, then cut.
    Prefers cutting at blank lines (natural boundaries).
    """
    if not content.strip():
        return []

    lines = content.split("\n")
    chunks: list[Chunk] = []
    current_lines: list[str] = []
    current_start = 1

    for i, line in enumerate(lines, start=1):
        current_lines.append(line)
        current_text = "\n".join(current_lines)

        if _count_tokens(current_text) >= max_tokens:
            # Try to find a blank line to cut at (natural boundary)
            cut_idx = len(current_lines) - 1
            for j in range(len(current_lines) - 1, max(0, len(current_lines) - 10), -1):
                if current_lines[j].strip() == "":
                    cut_idx = j
                    break

            chunk_text = "\n".join(current_lines[: cut_idx + 1]).strip()
            if chunk_text:
                chunks.append(
                    Chunk(
                        file_path=file_path,
                        text=chunk_text,
                        start_line=current_start,
                        end_line=current_start + cut_idx,
                    )
                )

            # Remainder becomes start of next chunk
            remaining = current_lines[cut_idx + 1 :]
            current_lines = remaining
            current_start = current_start + cut_idx + 1

    # Flush remaining
    if current_lines:
        chunk_text = "\n".join(current_lines).strip()
        if chunk_text:
            chunks.append(
                Chunk(
                    file_path=file_path,
                    text=chunk_text,
                    start_line=current_start,
                    end_line=current_start + len(current_lines) - 1,
                )
            )

    return chunks
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/embeddings/test_chunker.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add libs/embeddings/chunker.py tests/unit/embeddings/test_chunker.py
git commit -m "feat(embeddings): add code-aware chunker with token-based splitting"
```

---

### Task 7: Qdrant store wrapper

**Files:**
- Create: `libs/embeddings/qdrant_store.py`
- Create: `tests/unit/embeddings/test_qdrant_store.py`

- [ ] **Step 1: Write Qdrant store tests (using fake/mock)**

```python
# tests/unit/embeddings/test_qdrant_store.py
"""Tests for Qdrant store wrapper.

Uses the in-memory Qdrant client (no server needed).
"""
import pytest

from libs.embeddings.adapter import FakeEmbeddingAdapter
from libs.embeddings.qdrant_store import COLLECTIONS, QdrantStore


@pytest.fixture
def store() -> QdrantStore:
    return QdrantStore(location=":memory:")


@pytest.fixture
def adapter() -> FakeEmbeddingAdapter:
    return FakeEmbeddingAdapter(dimension=64)


@pytest.mark.asyncio
async def test_ensure_collections_creates_all(store: QdrantStore, adapter: FakeEmbeddingAdapter) -> None:
    await store.ensure_collections(dimension=adapter.dimension)
    client = store._client
    collections = await client.get_collections()
    names = {c.name for c in collections.collections}
    for coll_name in COLLECTIONS:
        assert coll_name in names


@pytest.mark.asyncio
async def test_upsert_and_search(store: QdrantStore, adapter: FakeEmbeddingAdapter) -> None:
    await store.ensure_collections(dimension=adapter.dimension)
    vectors = await adapter.embed_batch(["test function for user auth"])
    await store.upsert_summaries(
        project_id="proj1",
        items=[
            {
                "id": "file1",
                "vector": vectors[0],
                "file_path": "src/auth.py",
                "content_hash": "abc123",
                "language": "python",
                "entity_type": "file",
            }
        ],
    )
    query_vec = (await adapter.embed_batch(["user authentication"]))[0]
    results = await store.search_summaries(
        vector=query_vec,
        project_id="proj1",
        limit=5,
    )
    assert len(results) >= 1
    assert results[0]["file_path"] == "src/auth.py"


@pytest.mark.asyncio
async def test_delete_by_project(store: QdrantStore, adapter: FakeEmbeddingAdapter) -> None:
    await store.ensure_collections(dimension=adapter.dimension)
    vectors = await adapter.embed_batch(["test"])
    await store.upsert_summaries(
        project_id="proj1",
        items=[{"id": "f1", "vector": vectors[0], "file_path": "a.py", "content_hash": "h1", "language": "python", "entity_type": "file"}],
    )
    await store.delete_by_project("proj1")
    query_vec = (await adapter.embed_batch(["test"]))[0]
    results = await store.search_summaries(vector=query_vec, project_id="proj1", limit=5)
    assert len(results) == 0
```

- [ ] **Step 2: Run tests to verify fail**

Run: `uv run pytest tests/unit/embeddings/test_qdrant_store.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Qdrant store**

```python
# libs/embeddings/qdrant_store.py
"""Qdrant client wrapper for LV_DCP vector store.

Constitution invariant 7: fixed collections with payload isolation.
Collections: devctx_summaries, devctx_symbols, devctx_chunks, devctx_patterns.
"""
from __future__ import annotations

import uuid

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

COLLECTIONS = (
    "devctx_summaries",
    "devctx_symbols",
    "devctx_chunks",
    "devctx_patterns",
)

_PAYLOAD_INDEXES = ("project_id", "language", "entity_type", "privacy_mode")


class QdrantStore:
    def __init__(
        self,
        *,
        url: str | None = None,
        api_key: str | None = None,
        location: str | None = None,
    ) -> None:
        if location == ":memory:":
            self._client = AsyncQdrantClient(location=":memory:")
        else:
            self._client = AsyncQdrantClient(url=url, api_key=api_key)

    async def ensure_collections(self, *, dimension: int) -> None:
        existing = await self._client.get_collections()
        existing_names = {c.name for c in existing.collections}
        for name in COLLECTIONS:
            if name not in existing_names:
                await self._client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
                )
                for field in _PAYLOAD_INDEXES:
                    await self._client.create_payload_index(
                        collection_name=name,
                        field_name=field,
                        field_schema=PayloadSchemaType.KEYWORD,
                    )

    async def upsert_summaries(
        self,
        *,
        project_id: str,
        items: list[dict],
    ) -> None:
        points = [
            PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{project_id}/{item['file_path']}")),
                vector=item["vector"],
                payload={
                    "project_id": project_id,
                    "file_path": item["file_path"],
                    "content_hash": item["content_hash"],
                    "language": item.get("language", ""),
                    "entity_type": item.get("entity_type", "file"),
                },
            )
            for item in items
        ]
        if points:
            await self._client.upsert(collection_name="devctx_summaries", points=points)

    async def search_summaries(
        self,
        *,
        vector: list[float],
        project_id: str,
        limit: int = 10,
    ) -> list[dict]:
        results = await self._client.query_points(
            collection_name="devctx_summaries",
            query=vector,
            query_filter=Filter(
                must=[FieldCondition(key="project_id", match=MatchValue(value=project_id))]
            ),
            limit=limit,
        )
        return [
            {
                "file_path": point.payload.get("file_path", "") if point.payload else "",
                "score": point.score if hasattr(point, "score") else 0.0,
            }
            for point in results.points
        ]

    async def delete_by_project(self, project_id: str) -> None:
        for name in COLLECTIONS:
            await self._client.delete(
                collection_name=name,
                points_selector=Filter(
                    must=[FieldCondition(key="project_id", match=MatchValue(value=project_id))]
                ),
            )

    async def close(self) -> None:
        await self._client.close()
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/embeddings/test_qdrant_store.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add libs/embeddings/qdrant_store.py tests/unit/embeddings/test_qdrant_store.py
git commit -m "feat(embeddings): add Qdrant store wrapper with 4 fixed collections"
```

---

### Task 8: Hybrid retrieval (vector stage + RRF fusion)

**Files:**
- Modify: `libs/retrieval/pipeline.py:151-246`
- Modify: `tests/unit/retrieval/test_pipeline.py`

- [ ] **Step 1: Write test for RRF fusion**

Add to `tests/unit/retrieval/test_pipeline.py`:

```python
from libs.retrieval.pipeline import rrf_fuse


def test_rrf_fuse_combines_rankings() -> None:
    r1 = {"a.py": 3.0, "b.py": 2.0, "c.py": 1.0}
    r2 = {"b.py": 3.0, "c.py": 2.0, "d.py": 1.0}
    fused = rrf_fuse([r1, r2])
    # b.py appears in both rankings and should score highest
    sorted_fused = sorted(fused.items(), key=lambda x: -x[1])
    assert sorted_fused[0][0] == "b.py"
    assert "d.py" in fused


def test_rrf_fuse_empty_rankings() -> None:
    fused = rrf_fuse([{}, {}])
    assert fused == {}


def test_rrf_fuse_single_ranking() -> None:
    r1 = {"a.py": 3.0, "b.py": 1.0}
    fused = rrf_fuse([r1])
    assert set(fused.keys()) == {"a.py", "b.py"}
```

- [ ] **Step 2: Run tests to verify fail**

Run: `uv run pytest tests/unit/retrieval/test_pipeline.py::test_rrf_fuse_combines_rankings -v`
Expected: FAIL — `ImportError: cannot import name 'rrf_fuse'`

- [ ] **Step 3: Add rrf_fuse to pipeline.py**

Add after `_apply_score_decay` function at the bottom of `libs/retrieval/pipeline.py`:

```python
def rrf_fuse(
    rankings: list[dict[str, float]],
    k: int = 60,
) -> dict[str, float]:
    """Reciprocal Rank Fusion across multiple score dictionaries."""
    fused: dict[str, float] = {}
    for ranking in rankings:
        sorted_items = sorted(ranking.items(), key=lambda x: -x[1])
        for rank, (key, _) in enumerate(sorted_items):
            fused[key] = fused.get(key, 0.0) + 1.0 / (k + rank + 1)
    return fused
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/retrieval/test_pipeline.py -v`
Expected: All pass (old + new)

- [ ] **Step 5: Commit**

```bash
git add libs/retrieval/pipeline.py tests/unit/retrieval/test_pipeline.py
git commit -m "feat(retrieval): add RRF fusion function for hybrid retrieval"
```

---

## Group C: Obsidian Vault Sync

### Task 9: Obsidian models and templates

**Files:**
- Create: `libs/obsidian/__init__.py`
- Create: `libs/obsidian/models.py`
- Create: `libs/obsidian/templates.py`
- Create: `tests/unit/obsidian/__init__.py`
- Create: `tests/unit/obsidian/test_templates.py`

- [ ] **Step 1: Write template tests**

```python
# tests/unit/obsidian/test_templates.py
"""Tests for Obsidian page templates."""
from libs.obsidian.templates import render_home_page, render_module_page


def test_render_home_page_has_title() -> None:
    md = render_home_page(
        project_name="LV_DCP",
        languages=["python", "typescript"],
        file_count=150,
        symbol_count=800,
        scan_date="2026-04-13",
    )
    assert "LV_DCP" in md
    assert "python" in md
    assert "150" in md


def test_render_home_page_has_frontmatter() -> None:
    md = render_home_page(
        project_name="LV_DCP",
        languages=["python"],
        file_count=10,
        symbol_count=50,
        scan_date="2026-04-13",
    )
    assert md.startswith("---\n")
    assert "title:" in md
    assert "updated:" in md


def test_render_module_page() -> None:
    md = render_module_page(
        module_name="libs/retrieval",
        project_name="LV_DCP",
        file_count=8,
        symbol_count=45,
        top_symbols=["RetrievalPipeline", "FtsIndex", "SymbolIndex"],
        dependencies=["libs/core", "libs/graph"],
        dependents=["apps/mcp", "apps/cli"],
        scan_date="2026-04-13",
    )
    assert "libs/retrieval" in md
    assert "RetrievalPipeline" in md
    assert "[[libs/core]]" in md or "libs/core" in md
```

- [ ] **Step 2: Run tests to verify fail**

Run: `uv run pytest tests/unit/obsidian/test_templates.py -v`
Expected: FAIL

- [ ] **Step 3: Implement models**

```python
# libs/obsidian/__init__.py
"""Obsidian vault sync for LV_DCP."""

# libs/obsidian/models.py
"""Obsidian sync data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class VaultConfig:
    vault_path: Path
    sync_mode: str = "manual"  # manual | on_scan
    include_symbols: bool = True
    max_symbol_pages: int = 50


@dataclass
class SyncReport:
    project_name: str
    pages_written: int = 0
    pages_deleted: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Implement templates**

```python
# libs/obsidian/templates.py
"""Jinja2-free template functions for Obsidian vault pages.

Uses simple string formatting to avoid adding template complexity.
Each function returns a complete markdown page as a string.
"""
from __future__ import annotations


def render_home_page(
    *,
    project_name: str,
    languages: list[str],
    file_count: int,
    symbol_count: int,
    scan_date: str,
) -> str:
    langs = ", ".join(languages) if languages else "unknown"
    return f"""---
title: "{project_name}"
project: {project_name}
updated: {scan_date}
type: project-home
---

# {project_name}

| Metric | Value |
|---|---|
| Languages | {langs} |
| Files | {file_count} |
| Symbols | {symbol_count} |
| Last Scan | {scan_date} |

## Modules

See [[Modules/]] for detailed module pages.

## Navigation

- [[Architecture]]
- [[Recent Changes]]
- [[Tech Debt]]
"""


def render_module_page(
    *,
    module_name: str,
    project_name: str,
    file_count: int,
    symbol_count: int,
    top_symbols: list[str],
    dependencies: list[str],
    dependents: list[str],
    scan_date: str,
) -> str:
    symbols_md = "\n".join(f"- `{s}`" for s in top_symbols) if top_symbols else "- (none)"
    deps_md = "\n".join(f"- [[{d}]]" for d in dependencies) if dependencies else "- (none)"
    depts_md = "\n".join(f"- [[{d}]]" for d in dependents) if dependents else "- (none)"
    return f"""---
title: "{module_name}"
project: {project_name}
updated: {scan_date}
type: module
---

# {module_name}

| Metric | Value |
|---|---|
| Files | {file_count} |
| Symbols | {symbol_count} |

## Key Symbols

{symbols_md}

## Dependencies

{deps_md}

## Dependents

{depts_md}
"""


def render_recent_changes(
    *,
    project_name: str,
    changes: list[dict],
    scan_date: str,
) -> str:
    rows = ""
    for c in changes[:20]:
        rows += f"| `{c['path']}` | {c.get('date', 'unknown')} | {c.get('author', 'unknown')} |\n"
    return f"""---
title: "Recent Changes"
project: {project_name}
updated: {scan_date}
type: changes
---

# Recent Changes

| File | Date | Author |
|---|---|---|
{rows}"""


def render_tech_debt(
    *,
    project_name: str,
    hotspots: list[dict],
    scan_date: str,
) -> str:
    rows = ""
    for h in hotspots[:10]:
        rows += f"| `{h['path']}` | {h.get('fan_in', 0)} | {h.get('churn', 0)} | {'yes' if h.get('has_tests') else 'no'} | {h.get('score', 0):.1f} |\n"
    return f"""---
title: "Tech Debt"
project: {project_name}
updated: {scan_date}
type: tech-debt
---

# Tech Debt — Hotspots

| File | Fan-in | Churn (30d) | Tests | Score |
|---|---|---|---|---|
{rows}"""
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/obsidian/test_templates.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add libs/obsidian/ tests/unit/obsidian/
git commit -m "feat(obsidian): add models and page templates for vault sync"
```

---

### Task 10: Obsidian publisher + CLI command

**Files:**
- Create: `libs/obsidian/publisher.py`
- Create: `tests/unit/obsidian/test_publisher.py`
- Create: `apps/cli/commands/obsidian_cmd.py`
- Modify: `apps/cli/main.py:1-68`

- [ ] **Step 1: Write publisher tests**

```python
# tests/unit/obsidian/test_publisher.py
"""Tests for Obsidian publisher."""
import tempfile
from pathlib import Path

from libs.obsidian.models import VaultConfig
from libs.obsidian.publisher import ObsidianPublisher


def test_publisher_creates_project_directory(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config = VaultConfig(vault_path=vault)
    publisher = ObsidianPublisher(config)

    report = publisher.sync_project(
        project_name="TestProject",
        files=[],
        symbols=[],
        modules={},
        hotspots=[],
        recent_changes=[],
        languages=["python"],
    )

    project_dir = vault / "Projects" / "TestProject"
    assert project_dir.exists()
    assert (project_dir / "Home.md").exists()
    assert report.pages_written >= 1


def test_publisher_writes_module_pages(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config = VaultConfig(vault_path=vault)
    publisher = ObsidianPublisher(config)

    publisher.sync_project(
        project_name="TestProject",
        files=[],
        symbols=[],
        modules={
            "libs/core": {"file_count": 5, "symbol_count": 20, "top_symbols": ["File", "Symbol"], "dependencies": [], "dependents": []},
        },
        hotspots=[],
        recent_changes=[],
        languages=["python"],
    )

    module_page = vault / "Projects" / "TestProject" / "Modules" / "libs_core.md"
    assert module_page.exists()
    content = module_page.read_text()
    assert "libs/core" in content


def test_publisher_returns_report(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config = VaultConfig(vault_path=vault)
    publisher = ObsidianPublisher(config)

    report = publisher.sync_project(
        project_name="TestProject",
        files=[],
        symbols=[],
        modules={},
        hotspots=[],
        recent_changes=[],
        languages=["python"],
    )

    assert report.project_name == "TestProject"
    assert report.pages_written >= 1
    assert report.duration_seconds >= 0
```

- [ ] **Step 2: Run tests to verify fail**

Run: `uv run pytest tests/unit/obsidian/test_publisher.py -v`
Expected: FAIL

- [ ] **Step 3: Implement publisher**

```python
# libs/obsidian/publisher.py
"""Obsidian vault sync orchestrator.

Generates markdown pages from indexed project data and writes them
to the configured Obsidian vault path. Atomic writes via tmp+rename.
"""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path

from libs.obsidian.models import SyncReport, VaultConfig
from libs.obsidian.templates import (
    render_home_page,
    render_module_page,
    render_recent_changes,
    render_tech_debt,
)


class ObsidianPublisher:
    def __init__(self, config: VaultConfig) -> None:
        self._config = config

    def sync_project(
        self,
        *,
        project_name: str,
        files: list,
        symbols: list,
        modules: dict[str, dict],
        hotspots: list[dict],
        recent_changes: list[dict],
        languages: list[str],
    ) -> SyncReport:
        start = time.perf_counter()
        scan_date = date.today().isoformat()
        project_dir = self._config.vault_path / "Projects" / project_name
        modules_dir = project_dir / "Modules"

        project_dir.mkdir(parents=True, exist_ok=True)
        modules_dir.mkdir(parents=True, exist_ok=True)

        pages_written = 0

        # Home page
        home_md = render_home_page(
            project_name=project_name,
            languages=languages,
            file_count=len(files),
            symbol_count=len(symbols),
            scan_date=scan_date,
        )
        self._atomic_write(project_dir / "Home.md", home_md)
        pages_written += 1

        # Module pages
        for mod_name, mod_data in modules.items():
            mod_md = render_module_page(
                module_name=mod_name,
                project_name=project_name,
                file_count=mod_data.get("file_count", 0),
                symbol_count=mod_data.get("symbol_count", 0),
                top_symbols=mod_data.get("top_symbols", []),
                dependencies=mod_data.get("dependencies", []),
                dependents=mod_data.get("dependents", []),
                scan_date=scan_date,
            )
            safe_name = mod_name.replace("/", "_").replace("\\", "_")
            self._atomic_write(modules_dir / f"{safe_name}.md", mod_md)
            pages_written += 1

        # Recent Changes
        if recent_changes:
            changes_md = render_recent_changes(
                project_name=project_name,
                changes=recent_changes,
                scan_date=scan_date,
            )
            self._atomic_write(project_dir / "Recent Changes.md", changes_md)
            pages_written += 1

        # Tech Debt
        if hotspots:
            debt_md = render_tech_debt(
                project_name=project_name,
                hotspots=hotspots,
                scan_date=scan_date,
            )
            self._atomic_write(project_dir / "Tech Debt.md", debt_md)
            pages_written += 1

        elapsed = time.perf_counter() - start
        return SyncReport(
            project_name=project_name,
            pages_written=pages_written,
            duration_seconds=elapsed,
        )

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        """Write atomically: write to .tmp, then rename."""
        tmp = path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.rename(path)
```

- [ ] **Step 4: Implement CLI command**

```python
# apps/cli/commands/obsidian_cmd.py
"""`ctx obsidian` subcommands — vault sync and status."""
from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(help="Obsidian vault sync commands")


@app.command()
def sync(
    path: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Path to project root directory",
    ),
    vault: Path = typer.Option(
        ...,
        "--vault",
        help="Path to Obsidian vault root",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
) -> None:
    """Sync a scanned project to Obsidian vault."""
    from libs.obsidian.models import VaultConfig
    from libs.obsidian.publisher import ObsidianPublisher
    from libs.storage.sqlite_cache import SqliteCache

    cache_path = path / ".context" / "cache.db"
    if not cache_path.exists():
        typer.echo(f"No .context/cache.db found in {path}. Run `ctx scan` first.", err=True)
        raise typer.Exit(1)

    cache = SqliteCache(cache_path)
    try:
        cache.migrate()
        files = list(cache.iter_files())
        symbols = list(cache.iter_symbols())

        # Group by top-level module (first 2 path segments)
        modules: dict[str, dict] = {}
        for f in files:
            parts = f.path.split("/")
            mod_name = "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
            if mod_name not in modules:
                modules[mod_name] = {"file_count": 0, "symbol_count": 0, "top_symbols": [], "dependencies": [], "dependents": []}
            modules[mod_name]["file_count"] += 1

        for sym in symbols:
            parts = sym.file_path.split("/")
            mod_name = "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
            if mod_name in modules:
                modules[mod_name]["symbol_count"] += 1
                if len(modules[mod_name]["top_symbols"]) < 10:
                    modules[mod_name]["top_symbols"].append(sym.name)

        languages = sorted({f.language for f in files})

        config = VaultConfig(vault_path=vault)
        publisher = ObsidianPublisher(config)
        report = publisher.sync_project(
            project_name=path.name,
            files=files,
            symbols=symbols,
            modules=modules,
            hotspots=[],
            recent_changes=[],
            languages=languages,
        )

        typer.echo(
            f"Synced {report.project_name}: "
            f"{report.pages_written} pages written "
            f"in {report.duration_seconds:.2f}s"
        )
    finally:
        cache.close()


@app.command()
def status(
    vault: Path = typer.Option(
        ...,
        "--vault",
        help="Path to Obsidian vault root",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
) -> None:
    """Show sync status for projects in vault."""
    projects_dir = vault / "Projects"
    if not projects_dir.exists():
        typer.echo("No Projects/ directory in vault.")
        return
    for project_dir in sorted(projects_dir.iterdir()):
        if project_dir.is_dir():
            home = project_dir / "Home.md"
            status_str = "synced" if home.exists() else "missing Home.md"
            typer.echo(f"  {project_dir.name}: {status_str}")
```

- [ ] **Step 5: Wire CLI command into main.py**

Add to `apps/cli/main.py`:
```python
from apps.cli.commands import obsidian_cmd
app.add_typer(obsidian_cmd.app, name="obsidian")
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/unit/obsidian/ -v`
Expected: All pass

- [ ] **Step 7: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add libs/obsidian/publisher.py apps/cli/commands/obsidian_cmd.py apps/cli/main.py tests/unit/obsidian/test_publisher.py
git commit -m "feat(obsidian): add vault sync publisher + ctx obsidian CLI commands"
```

---

## Group D: Cross-Project Patterns

### Task 11: Pattern detector

**Files:**
- Create: `libs/patterns/__init__.py`
- Create: `libs/patterns/detector.py`
- Create: `tests/unit/patterns/__init__.py`
- Create: `tests/unit/patterns/test_detector.py`

- [ ] **Step 1: Write pattern detector tests**

```python
# tests/unit/patterns/test_detector.py
"""Tests for cross-project pattern detection."""
from libs.patterns.detector import PatternEntry, detect_dependency_patterns, detect_structural_patterns


def test_detect_common_dependencies() -> None:
    project_deps = {
        "proj1": ["fastapi", "pydantic", "sqlalchemy", "redis"],
        "proj2": ["fastapi", "pydantic", "celery"],
        "proj3": ["fastapi", "pydantic", "django"],
    }
    patterns = detect_dependency_patterns(project_deps, min_projects=2)
    dep_names = {p.name for p in patterns}
    assert "fastapi" in dep_names
    assert "pydantic" in dep_names


def test_detect_structural_patterns() -> None:
    project_dirs = {
        "proj1": ["src/models", "src/routes", "src/services", "tests"],
        "proj2": ["src/models", "src/routes", "src/handlers", "tests"],
        "proj3": ["lib/models", "lib/routes", "lib/services"],
    }
    patterns = detect_structural_patterns(project_dirs, min_projects=2)
    # "models" and "routes" should appear as common structural patterns
    dir_names = {p.name for p in patterns}
    assert any("models" in d for d in dir_names)


def test_pattern_entry_has_projects() -> None:
    project_deps = {
        "p1": ["fastapi"],
        "p2": ["fastapi"],
    }
    patterns = detect_dependency_patterns(project_deps, min_projects=2)
    for p in patterns:
        assert len(p.projects) >= 2


def test_no_patterns_below_threshold() -> None:
    project_deps = {
        "p1": ["fastapi"],
        "p2": ["django"],
    }
    patterns = detect_dependency_patterns(project_deps, min_projects=2)
    assert len(patterns) == 0
```

- [ ] **Step 2: Run tests to verify fail**

Run: `uv run pytest tests/unit/patterns/test_detector.py -v`
Expected: FAIL

- [ ] **Step 3: Implement pattern detector**

```python
# libs/patterns/__init__.py
"""Cross-project pattern detection."""

# libs/patterns/detector.py
"""Cross-project pattern detection.

Phase 6 scope: dependency and structural patterns only.
Code-level pattern detection is Phase 7+.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class PatternEntry:
    name: str
    pattern_type: str  # "dependency" | "structural"
    projects: tuple[str, ...]
    confidence: float  # projects_with_pattern / total_projects


def detect_dependency_patterns(
    project_deps: dict[str, list[str]],
    *,
    min_projects: int = 2,
) -> list[PatternEntry]:
    """Find dependencies shared across multiple projects."""
    total = len(project_deps)
    if total < min_projects:
        return []

    dep_counter: Counter[str] = Counter()
    dep_projects: dict[str, list[str]] = {}

    for project, deps in project_deps.items():
        for dep in deps:
            dep_counter[dep] += 1
            dep_projects.setdefault(dep, []).append(project)

    patterns: list[PatternEntry] = []
    for dep, count in dep_counter.most_common():
        if count >= min_projects:
            patterns.append(
                PatternEntry(
                    name=dep,
                    pattern_type="dependency",
                    projects=tuple(dep_projects[dep]),
                    confidence=count / total,
                )
            )
    return patterns


def detect_structural_patterns(
    project_dirs: dict[str, list[str]],
    *,
    min_projects: int = 2,
) -> list[PatternEntry]:
    """Find common directory structure patterns across projects."""
    total = len(project_dirs)
    if total < min_projects:
        return []

    # Normalize: extract leaf directory names
    dir_counter: Counter[str] = Counter()
    dir_projects: dict[str, list[str]] = {}

    for project, dirs in project_dirs.items():
        seen: set[str] = set()
        for d in dirs:
            leaf = d.rstrip("/").rsplit("/", 1)[-1]
            if leaf not in seen:
                seen.add(leaf)
                dir_counter[leaf] += 1
                dir_projects.setdefault(leaf, []).append(project)

    patterns: list[PatternEntry] = []
    for dirname, count in dir_counter.most_common():
        if count >= min_projects:
            patterns.append(
                PatternEntry(
                    name=dirname,
                    pattern_type="structural",
                    projects=tuple(dir_projects[dirname]),
                    confidence=count / total,
                )
            )
    return patterns
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/patterns/test_detector.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add libs/patterns/ tests/unit/patterns/
git commit -m "feat(patterns): add cross-project dependency and structural pattern detection"
```

---

## Group E: VS Code Extension

### Task 12: VS Code extension MVP

**Files:**
- Create: `apps/vscode/package.json`
- Create: `apps/vscode/src/extension.ts`
- Create: `apps/vscode/src/ctxClient.ts`
- Create: `apps/vscode/src/packProvider.ts`
- Create: `apps/vscode/tsconfig.json`
- Create: `apps/vscode/.vscodeignore`

- [ ] **Step 1: Create package.json**

```json
{
    "name": "lv-dcp",
    "displayName": "LV_DCP — Developer Context Platform",
    "description": "Context packs and impact analysis for your codebase",
    "version": "0.6.0",
    "engines": { "vscode": "^1.85.0" },
    "categories": ["Other"],
    "activationEvents": ["onStartupFinished"],
    "main": "./out/extension.js",
    "contributes": {
        "commands": [
            { "command": "lvdcp.getPack", "title": "LV_DCP: Get Context Pack" },
            { "command": "lvdcp.showImpact", "title": "LV_DCP: Show Impact" }
        ],
        "viewsContainers": {
            "activitybar": [
                { "id": "lvdcp", "title": "LV_DCP", "icon": "$(symbol-structure)" }
            ]
        },
        "views": {
            "lvdcp": [
                { "id": "lvdcp.packResults", "name": "Context Pack" }
            ]
        }
    },
    "scripts": {
        "compile": "tsc -p ./",
        "package": "npx @vscode/vsce package --no-dependencies"
    },
    "devDependencies": {
        "@types/vscode": "^1.85.0",
        "@types/node": "^20.0.0",
        "typescript": "^5.4.0",
        "@vscode/vsce": "^2.22.0"
    }
}
```

- [ ] **Step 2: Create tsconfig.json**

```json
{
    "compilerOptions": {
        "module": "commonjs",
        "target": "ES2022",
        "outDir": "out",
        "lib": ["ES2022"],
        "sourceMap": true,
        "rootDir": "src",
        "strict": true
    },
    "exclude": ["node_modules"]
}
```

- [ ] **Step 3: Create ctxClient.ts**

```typescript
// apps/vscode/src/ctxClient.ts
import { execFile } from "child_process";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

export interface PackResult {
    files: string[];
    symbols: string[];
    coverage: string;
    markdown: string;
}

export async function getContextPack(
    projectPath: string,
    query: string,
    mode: "navigate" | "edit" = "navigate"
): Promise<PackResult> {
    const { stdout } = await execFileAsync("ctx", [
        "pack", projectPath,
        "--query", query,
        "--mode", mode,
        "--format", "json",
    ], { timeout: 30000 });

    return JSON.parse(stdout);
}

export async function getInspect(projectPath: string): Promise<string> {
    const { stdout } = await execFileAsync("ctx", [
        "inspect", projectPath,
    ], { timeout: 15000 });
    return stdout;
}
```

- [ ] **Step 4: Create packProvider.ts**

```typescript
// apps/vscode/src/packProvider.ts
import * as vscode from "vscode";
import { PackResult } from "./ctxClient";

export class PackTreeItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly filePath?: string,
    ) {
        super(label, vscode.TreeItemCollapsibleState.None);
        if (filePath) {
            this.command = {
                command: "vscode.open",
                title: "Open File",
                arguments: [vscode.Uri.file(filePath)],
            };
            this.iconPath = new vscode.ThemeIcon("file");
        } else {
            this.iconPath = new vscode.ThemeIcon("symbol-method");
        }
    }
}

export class PackProvider implements vscode.TreeDataProvider<PackTreeItem> {
    private _onDidChangeTreeData = new vscode.EventEmitter<PackTreeItem | undefined>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

    private items: PackTreeItem[] = [];

    update(result: PackResult, projectRoot: string): void {
        this.items = [];
        // Files section
        for (const file of result.files) {
            this.items.push(new PackTreeItem(
                file,
                `${projectRoot}/${file}`,
            ));
        }
        // Symbols section
        for (const sym of result.symbols.slice(0, 15)) {
            this.items.push(new PackTreeItem(`⟡ ${sym}`));
        }
        this._onDidChangeTreeData.fire(undefined);
    }

    getTreeItem(element: PackTreeItem): PackTreeItem {
        return element;
    }

    getChildren(): PackTreeItem[] {
        return this.items;
    }
}
```

- [ ] **Step 5: Create extension.ts**

```typescript
// apps/vscode/src/extension.ts
import * as vscode from "vscode";
import { getContextPack } from "./ctxClient";
import { PackProvider } from "./packProvider";

let statusBarItem: vscode.StatusBarItem;

export function activate(context: vscode.ExtensionContext) {
    const packProvider = new PackProvider();
    vscode.window.registerTreeDataProvider("lvdcp.packResults", packProvider);

    // Status bar
    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
    statusBarItem.text = "$(symbol-structure) LV_DCP";
    statusBarItem.tooltip = "LV_DCP Developer Context Platform";
    statusBarItem.command = "lvdcp.getPack";
    statusBarItem.show();
    context.subscriptions.push(statusBarItem);

    // Get Context Pack command
    context.subscriptions.push(
        vscode.commands.registerCommand("lvdcp.getPack", async () => {
            const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
            if (!workspaceFolder) {
                vscode.window.showErrorMessage("No workspace folder open.");
                return;
            }

            const query = await vscode.window.showInputBox({
                prompt: "Enter your context query",
                placeHolder: "e.g., how does authentication work?",
            });
            if (!query) { return; }

            try {
                statusBarItem.text = "$(loading~spin) LV_DCP...";
                const result = await getContextPack(
                    workspaceFolder.uri.fsPath,
                    query,
                );
                packProvider.update(result, workspaceFolder.uri.fsPath);
                statusBarItem.text = `$(symbol-structure) LV_DCP [${result.files.length} files]`;
            } catch (err: any) {
                vscode.window.showErrorMessage(`LV_DCP: ${err.message}`);
                statusBarItem.text = "$(symbol-structure) LV_DCP";
            }
        })
    );

    // Show Impact command
    context.subscriptions.push(
        vscode.commands.registerCommand("lvdcp.showImpact", async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) {
                vscode.window.showErrorMessage("No active file.");
                return;
            }
            const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
            if (!workspaceFolder) { return; }

            const relativePath = vscode.workspace.asRelativePath(editor.document.uri);
            try {
                const result = await getContextPack(
                    workspaceFolder.uri.fsPath,
                    `impact analysis for ${relativePath}`,
                    "edit",
                );
                packProvider.update(result, workspaceFolder.uri.fsPath);
            } catch (err: any) {
                vscode.window.showErrorMessage(`LV_DCP: ${err.message}`);
            }
        })
    );
}

export function deactivate() {
    statusBarItem?.dispose();
}
```

- [ ] **Step 6: Create .vscodeignore**

```
.vscode/
src/
tsconfig.json
node_modules/
```

- [ ] **Step 7: Verify TypeScript compiles**

```bash
cd apps/vscode && npm install && npm run compile && cd ../..
```
Expected: `out/` directory created with compiled JS

- [ ] **Step 8: Commit**

```bash
git add apps/vscode/
git commit -m "feat(vscode): add VS Code extension MVP — context pack sidebar + status bar"
```

---

## Group F: Integration + Polish

### Task 13: Version bump + final test run

**Files:**
- Modify: `pyproject.toml:2`
- Modify: `libs/core/entities.py:50` (if needed)

- [ ] **Step 1: Update version**

In `pyproject.toml`, change `version = "0.5.0"` to `version = "0.6.0"`.

- [ ] **Step 2: Run lint + typecheck**

Run: `uv run ruff check . && uv run ruff format --check .`
Fix any issues.

Run: `uv run mypy --strict libs/parsers/treesitter_base.py libs/parsers/typescript.py libs/parsers/golang.py libs/parsers/rust.py libs/embeddings/ libs/obsidian/ libs/patterns/`
Fix any type errors.

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All tests pass, 0 failures

- [ ] **Step 4: Run eval harness**

Run: `uv run pytest tests/eval/ -v`
Expected: All eval thresholds pass, no regressions

- [ ] **Step 5: Commit version bump**

```bash
git add pyproject.toml
git commit -m "chore: bump version to 0.6.0 for Phase 6"
```

---

### Task 14: Update README + memory

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README roadmap section**

Update the roadmap/phases section to reflect Phase 6 completion:
- Phase 5: Done (v0.5.0)
- Phase 6: Done (v0.6.0) — cross-language parsers (TS/JS/Go/Rust), Qdrant vector store, Obsidian sync, VS Code extension, cross-project patterns

- [ ] **Step 2: Update memory file**

Update `project_phase_plan.md` memory to reflect Phase 6 completion.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update README roadmap to Phase 6 complete"
```

- [ ] **Step 4: Tag release**

```bash
git tag phase-6-complete
```
