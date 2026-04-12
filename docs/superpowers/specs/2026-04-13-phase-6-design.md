# Phase 6 — Cross-Language Parsers, Qdrant Vector Store, VS Code Extension, Obsidian Sync

**Status:** Draft 2026-04-13
**Owner:** Vladimir Lukin
**Follows:** Phase 5 complete (`phase-5-complete` tag, version 0.5.0)
**Version target:** 0.6.0

## 1. Goal

Expand LV_DCP from a Python-centric local tool to a **polyglot engineering memory platform**. Four pillars:

1. **Cross-language parsing** — TypeScript/JS, Go, Rust via tree-sitter, each with full eval.
2. **Qdrant vector store** — semantic retrieval layer on top of existing FTS+graph pipeline.
3. **VS Code extension** — daily-use integration calling existing MCP/API.
4. **Obsidian vault sync** — human-readable knowledge base projection.

**Litmus test:** A mixed TS+Python+Go project (e.g., a real user project) must produce quality retrieval results with recall@5 >= 0.60, and Obsidian vault must render navigable project knowledge.

## 2. Scope — 8 weeks, 5 deliverable groups

| Week | Deliverable | Key metric |
|---|---|---|
| 1 | TypeScript/JS tree-sitter parser | TS project recall@5 >= 0.55 |
| 2 | Go tree-sitter parser | Go project recall@5 >= 0.55 |
| 3 | Rust tree-sitter parser | Rust project recall@5 >= 0.50 |
| 4 | Qdrant integration — embedding + indexing pipeline | Vector retrieval MRR@5 >= 0.40 |
| 5 | Qdrant integration — hybrid retrieval (FTS+graph+vector) | Combined recall@5 >= 0.95 on LV_DCP |
| 6 | Obsidian vault sync | Vault renders for 3+ projects |
| 7 | VS Code extension MVP | Extension loads, pack displayed in sidebar |
| 8 | Buffer / cross-project patterns / eval gate / polish | All eval thresholds pass, v0.6.0 |

## 3. Week 1 — TypeScript/JS Parser

### 3.1 tree-sitter parser architecture

**New module:** `libs/parsers/treesitter_base.py`

A generic tree-sitter parser base that all non-Python languages will use. This avoids duplicating tree-walking logic per language.

```python
# libs/parsers/treesitter_base.py
from __future__ import annotations

import tree_sitter
from libs.core.entities import Relation, RelationType, Symbol, SymbolType
from libs.parsers.base import FileParser, ParseResult


class TreeSitterParser:
    """Base for tree-sitter language parsers.

    Subclasses define:
    - language: str
    - _get_language(): tree_sitter.Language
    - _symbol_queries: list of S-expression queries
    - _import_queries: list of S-expression queries
    - _role_heuristics: mapping for file role detection
    """

    language: str

    def parse(self, *, file_path: str, data: bytes) -> ParseResult:
        parser = tree_sitter.Parser(self._get_language())
        tree = parser.parse(data)
        symbols = self._extract_symbols(tree, file_path)
        relations = self._extract_relations(tree, file_path, data)
        role = self._detect_role(file_path)
        return ParseResult(
            file_path=file_path,
            language=self.language,
            role=role,
            symbols=tuple(symbols),
            relations=tuple(relations),
        )

    def _get_language(self) -> tree_sitter.Language: ...
    def _extract_symbols(self, tree, file_path) -> list[Symbol]: ...
    def _extract_relations(self, tree, file_path, data) -> list[Relation]: ...
    def _detect_role(self, file_path: str) -> str: ...
```

### 3.2 TypeScript/JS parser

**New module:** `libs/parsers/typescript.py`

**Dependencies:** `tree-sitter-typescript>=0.23`, `tree-sitter-javascript>=0.23`

**Extracted symbols:**
- `function` declarations → `SymbolType.FUNCTION`
- `class` declarations → `SymbolType.CLASS`
- `method_definition` → `SymbolType.METHOD`
- `interface_declaration` → `SymbolType.CLASS` (with tag)
- `type_alias_declaration` → `SymbolType.CLASS` (with tag)
- `enum_declaration` → `SymbolType.CLASS`
- `export_statement` + variable with arrow function → `SymbolType.FUNCTION`
- Module-level `const` UPPER_CASE → `SymbolType.CONSTANT`

**Extracted relations:**
- `import_statement` → `RelationType.IMPORTS` (both named and default imports)
- `export_statement` → `RelationType.DEFINES`
- `class_heritage` (extends/implements) → `RelationType.INHERITS`
- Same-file calls within function bodies → `RelationType.SAME_FILE_CALLS` (confidence 0.7 — lower than Python due to dynamic dispatch)

**File role detection:**
- `*.test.ts`, `*.spec.ts`, `__tests__/*` → `"test"`
- `*.d.ts` → `"config"` (type declarations)
- Otherwise → `"source"`

**Registry extension:**
```python
EXTENSION_TO_LANGUAGE update:
    ".ts": "typescript"
    ".tsx": "typescript"
    ".js": "javascript"
    ".jsx": "javascript"
    ".mjs": "javascript"
    ".cjs": "javascript"
```

TypeScript and JavaScript share the same parser class (tree-sitter-typescript handles both via separate language objects). The parser selects the correct tree-sitter language based on extension (`.ts`/`.tsx` → TypeScript, `.js`/`.jsx`/`.mjs`/`.cjs` → JavaScript).

### 3.3 tests_for inference for TS/JS

Same pattern as Python: if file role is `"test"`, scan its imports and promote internal imports to `TESTS_FOR` relations. Internal detection heuristic: import path starts with `./`, `../`, `@/`, `~/`, or matches `src/` prefix.

### 3.4 Eval fixture

**New:** `tests/eval/typescript_queries.yaml`

3-5 queries against a real TS project (e.g., TG_RUSCOFFEE_ADMIN_BOT or similar). Gate: recall@5 >= 0.55.

## 4. Week 2 — Go Parser

### 4.1 Go tree-sitter parser

**New module:** `libs/parsers/golang.py`

**Dependency:** `tree-sitter-go>=0.23`

**Extracted symbols:**
- `function_declaration` → `SymbolType.FUNCTION`
- `method_declaration` (with receiver) → `SymbolType.METHOD`
- `type_declaration` (struct/interface) → `SymbolType.CLASS`
- `const_declaration` → `SymbolType.CONSTANT`
- `var_declaration` (package-level) → `SymbolType.VARIABLE`

**Extracted relations:**
- `import_declaration` → `RelationType.IMPORTS`
- Method receiver type → `RelationType.DEFINES` (method belongs to type)
- Interface embedding → `RelationType.INHERITS`
- Same-file function calls → `RelationType.SAME_FILE_CALLS` (confidence 0.8 — Go is explicit)

**File role detection:**
- `*_test.go` → `"test"`
- `cmd/*/main.go` → `"source"` (entrypoint)
- Otherwise → `"source"`

**Registry extension:**
```python
".go": "go"
```

### 4.2 Go-specific: package as module

Go organizes by packages, not files. The `fq_name` for Go symbols uses the directory-based package path: `cmd/server/main.HandleRequest`. The parser derives this from the file path, not from `package` declarations (to avoid parsing ambiguity with tests in same package).

### 4.3 Eval fixture

`tests/eval/go_queries.yaml` — 3-5 queries. Gate: recall@5 >= 0.55.

## 5. Week 3 — Rust Parser

### 5.1 Rust tree-sitter parser

**New module:** `libs/parsers/rust.py`

**Dependency:** `tree-sitter-rust>=0.23`

**Extracted symbols:**
- `function_item` → `SymbolType.FUNCTION`
- `impl_item` methods → `SymbolType.METHOD`
- `struct_item`, `enum_item`, `trait_item` → `SymbolType.CLASS`
- `const_item`, `static_item` → `SymbolType.CONSTANT`
- `mod_item` → `SymbolType.MODULE`

**Extracted relations:**
- `use_declaration` → `RelationType.IMPORTS`
- `impl_item` for type → `RelationType.DEFINES`
- Trait bounds / supertraits → `RelationType.INHERITS`
- Same-file calls → `RelationType.SAME_FILE_CALLS` (confidence 0.75)

**File role detection:**
- `tests/*.rs`, `*_test.rs`, files with `#[cfg(test)]` → `"test"`
- `src/main.rs`, `src/lib.rs` → `"source"` (entrypoints)
- Otherwise → `"source"`

**Registry extension:**
```python
".rs": "rust"
```

### 5.2 Rust-specific: mod hierarchy as fq_name

Rust modules map to file paths. `fq_name` uses `::` separator: `crate::handlers::auth::login`. The parser derives module path from file path relative to `src/`.

### 5.3 Eval fixture

`tests/eval/rust_queries.yaml` — 3-5 queries. Gate: recall@5 >= 0.50 (lower threshold — Rust projects tend to be smaller in our corpus).

## 6. Week 4 — Qdrant Vector Store: Indexing Pipeline

### 6.1 Architecture decision

**Constitution invariant 7:** Fixed collections with payload isolation. We implement exactly:

| Collection | Content | Vector dim | Distance |
|---|---|---|---|
| `devctx_summaries` | File/module/project summaries | 1536 (text-embedding-3-small) | Cosine |
| `devctx_symbols` | Symbol docstrings + signatures | 1536 | Cosine |
| `devctx_chunks` | Raw code chunks (512 tokens max) | 1536 | Cosine |
| `devctx_patterns` | Cross-project patterns (Phase 6 Week 8) | 1536 | Cosine |

**Payload schema (all collections):**
```json
{
    "project_id": "string (indexed)",
    "file_path": "string",
    "language": "string (indexed)",
    "entity_type": "string (indexed)",
    "importance": "float",
    "revision": "string",
    "content_hash": "string",
    "privacy_mode": "string (indexed)"
}
```

### 6.2 Embedding adapter

**New module:** `libs/embeddings/adapter.py`

```python
class EmbeddingAdapter(Protocol):
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
    @property
    def dimension(self) -> int: ...
    @property
    def model_name(self) -> str: ...

class OpenAIEmbeddingAdapter:
    """Uses text-embedding-3-small via OpenAI-compatible API."""
    model: str = "text-embedding-3-small"
    dimension: int = 1536

class LocalEmbeddingAdapter:
    """Uses Ollama or compatible local endpoint."""
    ...
```

Default: OpenAI `text-embedding-3-small` ($0.02/1M tokens, 1536 dimensions). Local adapter optional for privacy_mode=`local_only`. Dimension is adapter-specific — `QdrantStore.ensure_collections()` reads it from the active adapter at startup.

### 6.3 Qdrant client wrapper

**New module:** `libs/embeddings/qdrant_store.py`

```python
class QdrantStore:
    def __init__(self, url: str, api_key: str | None = None): ...
    async def ensure_collections(self) -> None: ...
    async def upsert_points(self, collection: str, points: list[PointStruct]) -> None: ...
    async def search(self, collection: str, vector: list[float],
                     filter: Filter, limit: int = 10) -> list[ScoredPoint]: ...
    async def delete_by_project(self, project_id: str) -> None: ...
    async def delete_by_file(self, project_id: str, file_path: str) -> None: ...
```

**Dependency:** `qdrant-client>=1.9` (async client).

**Incrementality:** On scan, only embed files whose `content_hash` changed. Delete stale points by `file_path` before upserting new ones. This respects constitution invariant 2.

### 6.4 Embedding pipeline integration

**Modify:** `libs/scanning/scanner.py`

After parsing + FTS indexing + graph building, new step:
1. Collect changed files' summaries, symbols, and chunks.
2. Batch embed via adapter.
3. Upsert to Qdrant with payload.

**Gating:** Embedding runs only if `qdrant_enabled: true` in config. Default: `false` (constitution says system must work without vector layer). If Qdrant unavailable, log warning and continue — degraded mode per ТЗ §28.

### 6.5 Chunking strategy

**New module:** `libs/embeddings/chunker.py`

- Split files into chunks of max 512 tokens (tiktoken `cl100k_base`).
- Chunk boundaries respect symbol boundaries (never split a function mid-body).
- Each chunk carries metadata: file_path, start_line, end_line, symbols_in_chunk.
- Priority: symbol-level embeddings (docstring + signature) > file summary > raw chunks.

## 7. Week 5 — Hybrid Retrieval (FTS + Graph + Vector)

### 7.1 Vector retrieval stage

**Modify:** `libs/retrieval/pipeline.py`

New stage `_vector_retrieval` inserted after `_graph_expansion`, before `_apply_role_weights`:

```python
VECTOR_WEIGHT = 0.25  # relative to FTS (1.0) and graph (configurable)

async def _vector_retrieval(
    query: str,
    project_id: str,
    qdrant: QdrantStore,
    adapter: EmbeddingAdapter,
    limit: int = 20,
) -> dict[str, float]:
    """Embed query → search Qdrant → return file_path → score mapping."""
    query_vec = (await adapter.embed_batch([query]))[0]
    results = await qdrant.search(
        collection="devctx_summaries",
        vector=query_vec,
        filter=Filter(must=[FieldCondition(key="project_id", match=MatchValue(value=project_id))]),
        limit=limit,
    )
    # Also search symbols collection
    sym_results = await qdrant.search(
        collection="devctx_symbols",
        vector=query_vec,
        filter=Filter(must=[FieldCondition(key="project_id", match=MatchValue(value=project_id))]),
        limit=limit,
    )
    # Merge results, deduplicate by file_path, take max score
    ...
```

### 7.2 Score fusion

Reciprocal Rank Fusion (RRF) across three sources:
1. **FTS+symbol** (existing pipeline) — weight 1.0
2. **Graph expansion** (existing) — weight 0.5
3. **Vector retrieval** (new) — weight 0.25

```python
def rrf_fuse(rankings: list[dict[str, float]], k: int = 60) -> dict[str, float]:
    """Reciprocal Rank Fusion."""
    fused: dict[str, float] = {}
    for ranking in rankings:
        sorted_items = sorted(ranking.items(), key=lambda x: -x[1])
        for rank, (key, _) in enumerate(sorted_items):
            fused[key] = fused.get(key, 0.0) + 1.0 / (k + rank + 1)
    return fused
```

**Fallback:** If Qdrant unavailable, skip vector stage silently. Pipeline must never fail due to missing vector layer (constitution + ТЗ §28).

### 7.3 Eval update

Extend eval harness with:
- `vector_mrr@5` — Mean Reciprocal Rank from vector-only retrieval
- `hybrid_recall@5` — Combined pipeline recall

Gate: `hybrid_recall@5 >= 0.95` on LV_DCP (up from 0.964 baseline — must not regress).

## 8. Week 6 — Obsidian Vault Sync

### 8.1 Architecture

**New module:** `libs/obsidian/`

```
libs/obsidian/
    __init__.py
    publisher.py      # main sync orchestrator
    templates.py      # Jinja2 templates for vault pages
    models.py         # VaultConfig, SyncState
    wikilinks.py      # wikilink resolver
```

**ТЗ §8.11 vault structure:**
```
Projects/
  <ProjectName>/
    Home.md           # project summary, languages, stats
    Architecture.md   # module summaries, dependency overview
    Modules/
      <module>.md     # per top-level directory
    Symbols/
      <symbol>.md     # top-50 symbols by importance/fan-in
    Recent Changes.md # last 20 changed files with dates
    Tech Debt.md      # hotspot analysis, untested high-fan-in
    Graph Index.md    # text-based adjacency list for Obsidian graph
```

### 8.2 Publisher

```python
class ObsidianPublisher:
    def __init__(self, vault_path: Path, config: VaultConfig): ...

    async def sync_project(self, project_slug: str, db_path: Path) -> SyncReport:
        """Full incremental sync of one project to vault."""
        # 1. Load project data from .context/cache.db
        # 2. Generate/update each page via templates
        # 3. Track which files were written (for cleanup)
        # 4. Remove orphaned pages (deleted modules/symbols)
        # 5. Return report: pages_written, pages_deleted, duration

    async def sync_all(self, projects: list[ProjectConfig]) -> list[SyncReport]: ...
```

### 8.3 Page generation rules (from ТЗ)

- Notes must be **readable**, not dump artifacts.
- Use `[[wikilinks]]` for cross-references between project pages.
- Include source paths as `code` references.
- Include last-updated date in YAML frontmatter.
- Include confidence/freshness indicator (based on scan recency).

**Frontmatter example:**
```yaml
---
title: "libs/retrieval/pipeline"
project: LV_DCP
updated: 2026-04-13
scan_version: "0.6.0"
freshness: "current"  # current | stale | outdated
---
```

### 8.4 Sync modes

Per ТЗ §8.11, four modes:
1. **manual** — `ctx obsidian sync <project>` CLI command
2. **on_scan** — triggered after `ctx scan` completes
3. **debounced** — after file changes, wait 30s of quiet, then sync changed modules only
4. **nightly** — consolidate run (full re-render of all pages)

Phase 6 implements **manual** and **on_scan** only. Debounced and nightly are Phase 7+.

### 8.5 Configuration

```yaml
# .context/config.yaml addition
obsidian:
  enabled: false
  vault_path: ""  # e.g., /Users/you/Documents/Obsidian/MainVault
  sync_mode: manual  # manual | on_scan
  include_symbols: true
  max_symbol_pages: 50
```

### 8.6 CLI integration

```bash
ctx obsidian sync <project>       # sync one project
ctx obsidian sync --all           # sync all registered projects
ctx obsidian status               # show sync state per project
```

## 9. Week 7 — VS Code Extension MVP

### 9.1 Architecture

The extension is a **thin client** that calls the existing MCP server or CLI. Per ТЗ §23.1: "extension не должна дублировать retrieval logic."

**Separate directory:** `apps/vscode/` (TypeScript, not published to marketplace in Phase 6)

**Capabilities:**
1. **Context Pack sidebar** — input query, show pack results in a tree view
2. **File annotations** — show fan-in/fan-out/hotspot score in gutter
3. **Impact preview** — on save, show impacted files in a panel
4. **Status bar** — project name, scan freshness, file count

### 9.2 Communication

Extension communicates via **CLI subprocess** (`ctx pack <query> --json`) for MVP. This avoids requiring the backend server to be running. Future: switch to MCP stdio or local HTTP API.

### 9.3 Extension structure

```
apps/vscode/
  package.json
  src/
    extension.ts        # activation, commands
    packProvider.ts     # TreeDataProvider for pack results
    impactProvider.ts   # Impact panel
    statusBar.ts        # Status bar item
    ctxClient.ts        # wrapper around ctx CLI subprocess
  tsconfig.json
  .vscodeignore
```

### 9.4 Minimal feature set

- Command: `LV_DCP: Get Context Pack` → opens input box → calls `ctx pack` → shows results in sidebar
- Command: `LV_DCP: Show Impact` → calls `ctx inspect --impact <current_file>` → shows panel
- Status bar: shows project name + "N files indexed" + freshness indicator
- On file save: if `impact_on_save` enabled, auto-run impact analysis

### 9.5 No marketplace publish

Phase 6 delivers a `.vsix` that can be installed locally via `code --install-extension`. Marketplace publishing is Phase 7+.

## 10. Week 8 — Cross-Project Patterns + Polish

### 10.1 Cross-project pattern detection

**New module:** `libs/patterns/detector.py`

Cross-project patterns are reusable architectural elements found across multiple indexed projects:

- **Common dependencies** — which libraries appear in 3+ projects
- **Structural patterns** — similar module layouts (e.g., `services/` + `routes/` + `models/`)
- **Code patterns** — similar function signatures or class hierarchies

**Storage:** `devctx_patterns` Qdrant collection. Each pattern has:
- `pattern_type`: `"dependency"` | `"structural"` | `"code"`
- `projects`: list of project_ids where pattern found
- `description`: human-readable summary
- `confidence`: how many projects share this pattern / total projects

**Phase 6 scope:** Only `dependency` and `structural` patterns. Code-level pattern detection requires AST similarity which is Phase 7+.

### 10.2 Version + tag

- `pyproject.toml`: `0.5.0` → `0.6.0`
- Git tag: `phase-6-complete` on HEAD main (if all eval thresholds pass)

## 11. Architecture — Files Changed

```
libs/
  parsers/
    treesitter_base.py    [NEW — shared tree-sitter parser base]
    typescript.py          [NEW — TS/JS parser]
    golang.py              [NEW — Go parser]
    rust.py                [NEW — Rust parser]
    registry.py            [MODIFY — add new languages + parsers]
  embeddings/
    __init__.py            [NEW]
    adapter.py             [NEW — embedding adapter protocol + OpenAI impl]
    qdrant_store.py        [NEW — Qdrant client wrapper]
    chunker.py             [NEW — code-aware chunking]
  obsidian/
    __init__.py            [NEW]
    publisher.py           [NEW — vault sync orchestrator]
    templates.py           [NEW — Jinja2 page templates]
    models.py              [NEW — VaultConfig, SyncState, SyncReport]
    wikilinks.py           [NEW — wikilink resolver]
  retrieval/
    pipeline.py            [MODIFY — add vector stage + RRF fusion]
  patterns/
    __init__.py            [NEW]
    detector.py            [NEW — cross-project pattern detection]
  core/
    entities.py            [MODIFY — add language values to File.language]

apps/
  cli/commands/
    obsidian_cmd.py        [NEW — ctx obsidian sync/status]
    pack_cmd.py            [MODIFY — add --json output for VS Code]
  vscode/                  [NEW — entire VS Code extension]
    package.json
    src/extension.ts
    src/packProvider.ts
    src/impactProvider.ts
    src/statusBar.ts
    src/ctxClient.ts

tests/
  unit/parsers/
    test_typescript_parser.py  [NEW]
    test_go_parser.py          [NEW]
    test_rust_parser.py        [NEW]
    test_treesitter_base.py    [NEW]
  unit/embeddings/
    test_adapter.py            [NEW]
    test_qdrant_store.py       [NEW]
    test_chunker.py            [NEW]
  unit/obsidian/
    test_publisher.py          [NEW]
    test_templates.py          [NEW]
    test_wikilinks.py          [NEW]
  unit/patterns/
    test_detector.py           [NEW]
  unit/retrieval/
    test_pipeline.py           [MODIFY — test vector stage + RRF]
  eval/
    typescript_queries.yaml    [NEW]
    go_queries.yaml            [NEW]
    rust_queries.yaml          [NEW]
```

## 12. Files NOT Touched

- `libs/parsers/python.py` — Python parser unchanged, it uses stdlib AST (more accurate for Python)
- `libs/parsers/text_parsers.py` — Markdown/YAML/JSON/TOML parsers unchanged
- `libs/gitintel/*` — git intelligence unchanged
- `libs/impact/*` — impact analysis unchanged (auto-benefits from new parsers)
- `libs/summaries/*` — summary layer unchanged
- `libs/graph/builder.py` — graph builder unchanged (consumes Relations from any parser)
- `apps/mcp/server.py` — MCP server unchanged (auto-picks up pipeline changes)
- `apps/ui/*` — dashboard unchanged

## 13. Dependencies

**New required:**
- `tree-sitter-typescript>=0.23` — TypeScript/JS grammar
- `tree-sitter-javascript>=0.23` — JavaScript grammar (separate from TS)
- `tree-sitter-go>=0.23` — Go grammar
- `tree-sitter-rust>=0.23` — Rust grammar
- `qdrant-client>=1.9` — async Qdrant client

**Already present:**
- `tree-sitter>=0.23` — core library
- `openai>=1.50` — for embedding API (text-embedding-3-small)
- `tiktoken>=0.7` — for chunking token count
- `jinja2>=3.1` — for Obsidian page templates

**VS Code extension (npm, not Python):**
- `@types/vscode` — VS Code API types
- `esbuild` — bundler

**ADR consideration:** `qdrant-client` is a new technology dependency. Per constitution §V, this requires an ADR. However, Qdrant has been in the approved stack since ТЗ §9.3 and is mentioned in constitution invariant 7. The ADR should document the activation decision, not the technology choice.

## 14. Risks

**R1 — tree-sitter grammar version mismatch.**
Different `tree-sitter-*` packages may require different core `tree-sitter` versions. Mitigation: pin all to `>=0.23` (same major), test import compatibility before implementation.

**R2 — Embedding cost on large projects.**
A 1500-file project with ~500 symbols could generate ~2000 embeddings. At $0.02/1M tokens, that's ~$0.02 per full scan. Mitigation: incremental embedding (only changed files). Budget: $0.10/month max per project.

**R3 — Qdrant not running = broken scan.**
Mitigation: embedding is gated by `qdrant_enabled` config flag (default: false). Pipeline never fails on Qdrant absence. Degraded mode per constitution.

**R4 — Obsidian vault corruption on concurrent writes.**
Mitigation: publisher uses atomic writes (write to `.tmp`, rename). Single-writer model (only `ctx obsidian sync` writes, never concurrent).

**R5 — VS Code extension maintenance burden.**
Mitigation: MVP is minimal (4 files, ~300 lines TS). Communication via CLI subprocess avoids API coupling. No marketplace publish means no support burden.

**R6 — Cross-language import resolution is imprecise.**
Tree-sitter gives syntax, not semantics. Import `from "../../utils"` in TS can't be resolved to an exact file without knowing tsconfig paths. Mitigation: best-effort resolution with confidence < 1.0. FTS and vector retrieval compensate.

**R7 — pymorphy3 + tree-sitter + qdrant-client increases install size significantly.**
Mitigation: Qdrant client is optional (`[vector]` extra). Tree-sitter grammars are ~5MB each. Total install grows by ~40MB. Acceptable for desktop tool.

## 15. Non-goals

Phase 6 does NOT do:
- Java, Kotlin, Swift, C# parsers — Phase 7+ per ТЗ §8.5 v2 roadmap
- LLM-based rerank — not needed given hybrid approach
- Obsidian debounced/nightly sync modes — Phase 7+
- VS Code marketplace publishing — Phase 7+
- Real-time collaborative editing — never
- Neo4j migration — constitutionally prohibited
- Collection-per-project in Qdrant — constitutionally prohibited

## 16. Eval Gate

Phase 6 closes when ALL pass:

1. LV_DCP synthetic recall@5 >= 0.92 (no regression)
2. LV_DCP real recall@5 >= 0.80 (no regression)
3. LV_DCP hybrid_recall@5 >= 0.95
4. TypeScript project recall@5 >= 0.55
5. Go project recall@5 >= 0.55
6. Rust project recall@5 >= 0.50
7. Vector MRR@5 >= 0.40 on LV_DCP
8. `make lint typecheck test` green
9. Obsidian vault renders for 3+ projects
10. VS Code extension installs and displays pack results
11. Cross-project patterns detected for 2+ projects
12. Dogfood report `docs/dogfood/phase-6.md` committed

**If all pass:** version 0.6.0, tag `phase-6-complete`.
**If eval fails:** iterate on parser queries / embedding model / retrieval weights. Max 3 calibration rounds.

## 17. Estimate

| Week | Deliverable | Days |
|---|---|---|
| 1 | TypeScript/JS tree-sitter parser + eval | 5 |
| 2 | Go tree-sitter parser + eval | 4 |
| 3 | Rust tree-sitter parser + eval | 4 |
| 4 | Qdrant integration — embedding + indexing | 5 |
| 5 | Hybrid retrieval + eval gate | 5 |
| 6 | Obsidian vault sync | 5 |
| 7 | VS Code extension MVP | 5 |
| 8 | Cross-project patterns + polish + dogfood | 3-5 |
| **Total** | | **~36-38 working days** |
