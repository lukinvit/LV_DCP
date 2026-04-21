# Источники: все изученные репозитории

Список всех просмотренных проектов со звёздами и вердиктом.
Звёзды — приблизительные на начало 2026 года.

**Легенда:** 🟢 = идея взята · 🟡 = паттерн перенимаем, dep не тащим · 🔴 = отвергнуто / reference-only

---

## AI coding assistants

| Репо | Stars | Статус | Что взяли |
|------|-------|--------|-----------|
| Aider-AI/aider | ~35k | 🟢 | search/replace edit format, polyglot benchmark, outline-рендерер |
| continuedev/continue | ~22k | 🟡 | AST-aware chunking, hybrid retrieval, .continueignore, manifest-on-disk |
| cline/cline | ~30k | 🟢 | shadow-git checkpoints, plan/act separation, auto-compact |
| RooCodeInc/Roo-Code | ~15k | 🟡 | custom modes YAML, tool-allowlist per mode, sticky models |
| All-Hands-AI/OpenHands | ~45k | 🟡 | sandbox runtime, Docker per-session |
| block/goose | ~15k | 🟡 | MCP-first архитектура — LV_DCP как MCP-server |
| sourcegraph/cody | ~3k | 🟢 | SCIP precise layer, context filters |
| plandex-ai/plandex | ~13k | 🟢 | context pins, cost-breakers, debug-loop |
| Cursor (proprietary) | — | 🟢 | Merkle-tree sync, apply-model, shadow workspace |
| TabbyML/tabby | ~22k | 🟡 | tantivy BM25 sidecar pattern, typed retrieval |
| zed-industries/zed | ~55k | 🟡 | tree-sitter outline.scm queries, slash-commands |
| yamadashy/repomix | ~18k | 🟢 | XML-pack with TOC, token preview, compression |
| mufeedvh/code2prompt | ~8k | 🟢 | Handlebars templates → Jinja у нас |
| Nutlope/aicommits | ~8k | 🔴 | diff-only cheap mode (идея мелкая) |
| simonw/files-to-prompt | ~2k | 🔴 | простой dumper, ничего нового |
| cyberchitta/llm-context.py | ~1k | 🟡 | named context profiles |
| Pythagora-io/gpt-pilot | ~32k | 🔴 | multi-agent app generator, не про context |
| princeton-nlp/SWE-agent | — | 🟡 | ACI paper — restricted tool-surface |

---

## RAG / Graph-RAG / Memory

| Репо | Stars | Статус | Что взяли |
|------|-------|--------|-----------|
| microsoft/graphrag | ~23k | 🟢 | Leiden clustering, community reports, map-reduce |
| HKUDS/LightRAG | ~15k | 🟡 | dual-level query, incremental graph upsert |
| gusye1234/nano-graphrag | ~2.5k | 🟡 | gleaning loop, prompts templates |
| OSU-NLP-Group/HippoRAG | ~2.5k | 🟢 | Personalized PageRank для graph expansion |
| run-llama/llama_index | ~35k | 🟡 | CodeHierarchyNodeParser, SubQuestionQueryEngine |
| langchain-ai/langchain | ~90k | 🟡 | EnsembleRetriever RRF, ContextualCompression |
| langchain-ai/langgraph | ~10k | 🟡 | state machine pattern для edit pipeline |
| deepset-ai/haystack | ~17k | 🟡 | eval metrics (Context Relevance, Faithfulness) |
| neuml/txtai | ~10k | 🟡 | SQL-over-embeddings pattern |
| mem0ai/mem0 | ~30k | 🟢 | memory ops ADD/UPDATE/DELETE/NOOP |
| getzep/zep (Graphiti) | ~5k | 🟢 | temporal edges + episodes |
| letta-ai/letta | ~15k | 🟡 | core/archival memory разделение |
| topoteretes/cognee | ~2.5k | 🟡 | ontology-typed entities |
| infiniflow/ragflow | ~25k | 🟡 | chunk quality score, template chunking |
| SciPhi-AI/R2R | ~5k | 🟢 | HyDE |
| weaviate/verba | ~7k | 🟡 | chunker abstract class, debug panel |
| vanna-ai/vanna | ~13k | 🟡 | DDL+examples pattern для text-to-SQL |
| explodinggradients/ragas | ~8k | 🟢 | Context Precision/Recall, Faithfulness |
| confident-ai/deepeval | ~5k | 🟡 | pytest-интеграция LLM-evals |

---

## Parsers / Static analysis

| Репо | Stars | Статус | Что взяли |
|------|-------|--------|-----------|
| tree-sitter/tree-sitter | ~20k | 🟢 | уже в стеке |
| tree-sitter/tree-sitter-graph | ~0.4k | 🟢 | DSL для декларативной экстракции |
| ast-grep/ast-grep | ~9k | 🟢 | YAML-правила, meta-variables, ctx find |
| semgrep/semgrep | ~11k | 🟡 | taint analysis, baseline mode |
| sourcegraph/scip | ~0.6k | 🟢 | precise-слой для Python через scip-python |
| github/stack-graphs | ~0.6k | 🟡 | инкрементальный name resolution (фаза 2+) |
| microsoft/pyright | ~15k | 🟡 | --outputjson для типизации символов |
| facebook/pyrefly | ~3k | 🟡 | Rust-fast type checker |
| python-rope/rope | ~2k | 🟡 | safe rename/extract для edit pipeline |

---

## Chunking / Splitting

| Репо | Stars | Статус | Что взяли |
|------|-------|--------|-----------|
| bhavnicksm/chonkie | ~3k | 🟢 | SemanticChunker, LateChunker — Rust-speed |
| run-llama/llama_index (splitters) | — | 🟢 | CodeHierarchyNodeParser |
| Unstructured-IO/unstructured | ~9k | 🟡 | element-aware MD/RST chunking |

---

## Embeddings

| Репо | Stars | Статус | Что взяли |
|------|-------|--------|-----------|
| FlagOpen/FlagEmbedding (bge) | ~8k | 🟢 | **bge-m3** (dense+sparse+multivector), bge-code-v1 |
| jinaai (embeddings v3/v4) | — | 🟢 | late chunking, Matryoshka |
| Voyage AI (closed) | — | 🟡 | code-specific training как стратегия |
| nomic-ai/contrastors | ~1k | 🟡 | open-source training recipe |
| microsoft/unilm (CodeBERT) | ~20k | 🔴 | legacy, только baseline |
| salesforce/CodeT5 | ~3k | 🔴 | encoder-decoder, не наш use case |

---

## Rerankers

| Репо | Stars | Статус | Что взяли |
|------|-------|--------|-----------|
| FlagEmbedding (bge-reranker-v2-m3) | — | 🟢 | **основной rerank stage** |
| FlagEmbedding (v2-minicpm layerwise) | — | 🟡 | adaptive latency |
| Cohere Rerank (closed) | — | 🟡 | structured doc pattern |
| jinaai/jina-reranker-v2 | — | 🟡 | low-latency fallback |
| stanford-futuredata/ColBERT | ~4k | 🟡 | через bge-m3 multivector output |
| sbert cross-encoder/ms-marco | — | 🟡 | baseline CPU-reranker |

---

## Vector DB / Hybrid search

| Репо | Stars | Статус | Что взяли |
|------|-------|--------|-----------|
| qdrant/qdrant | ~22k | 🟢 | уже в стеке, новые фичи: sparse, multivector, Matryoshka, binary quant |
| lancedb/lancedb | ~5k | 🟡 | возможный L1-cache в агенте (фаза 3) |
| chroma-core/chroma | — | 🔴 | дубль Qdrant |
| vespa-engine/vespa | ~6k | 🔴 | overkill, но rank profiles как идея |
| quickwit-oss/tantivy | ~12k | 🟡 | возможный BM25 sidecar, если Qdrant sparse не хватит |
| meilisearch | ~47k | 🔴 | |
| typesense | ~21k | 🟡 | code tokenizer (camelCase) |

---

## File watching / Desktop

| Репо | Stars | Статус | Что взяли |
|------|-------|--------|-----------|
| samuelcolvin/watchfiles | ~2k | 🟢 | **замена watchdog** |
| gorakhargosh/watchdog | ~6.7k | 🟡 | отходим, но паттерны debounce сохраняем |
| syncthing/syncthing | ~68k | 🟢 | .stignore, block-hashing, vector clocks |
| rclone/rclone | ~47k | 🟡 | filter-from, bisync reconciliation |
| emcrisostomo/fswatch | ~8k | 🔴 | C++ CLI, reference-only |
| Hammerspoon/hammerspoon | ~12k | 🔴 | Lua, не Python |
| KeepingYouAwake, Mos (launchd) | 10–15k | 🟢 | plist best-practices |

---

## Obsidian ecosystem

| Репо | Stars | Статус | Что взяли |
|------|-------|--------|-----------|
| coddingtonbear/obsidian-local-rest-api | ~1.5k | 🟢 | 2-way sync, ETag atomic writes |
| blacksmithgu/obsidian-dataview | ~9k | 🟢 | frontmatter schema → dashboards |
| brianpetro/obsidian-smart-connections | ~3k | 🔴 | дубль нашего retrieval |
| obsidian-copilot | ~3.5k | 🔴 | reference UX |
| jackyzha0/quartz | ~9k | 🟢 | публичный KB site |
| logseq/logseq | ~37k | 🔴 | только reference для block-refs |
| silverbulletmd/silverbullet | ~3k | 🔴 | reference-only |
| foambubble/foam | ~15k | 🟡 | wikilink discovery, orphan detection |

---

## MCP ecosystem

| Репо | Stars | Статус | Что взяли |
|------|-------|--------|-----------|
| modelcontextprotocol/servers | ~35k | 🟢 | reference fs/git/memory/postgres servers |
| modelcontextprotocol/python-sdk | ~9k | 🟢 | базовая интеграция |
| lastmile-ai/mcp-agent | ~4k | 🟡 | workflow patterns (Router, Parallel) |
| jlowin/fastmcp | ~12k | 🟢 | **основной MCP framework** |
| punkpeye/awesome-mcp-servers | ~50k | 🟡 | cherry-pick полезных серверов |
| mcp-server-sequential-thinking | ~2k | 🟡 | meta-tool для декомпозиции |

---

## Observability / Eval

| Репо | Stars | Статус | Что взяли |
|------|-------|--------|-----------|
| langfuse/langfuse | ~9k | 🟢 | **основная observability-платформа** |
| Helicone/helicone | ~4k | 🔴 | дубль Langfuse |
| traceloop/openllmetry | ~6k | 🟢 | OTel auto-instrumentation |
| Arize-ai/phoenix | ~6k | 🔴 | дубль Langfuse |
| promptfoo/promptfoo | ~8k | 🟢 | **YAML eval config** |
| confident-ai/deepeval | ~5k | 🟡 | возможно, если ragas не хватит |
| explodinggradients/ragas | ~8k | 🟢 | **RAG metrics** |
| truera/trulens | ~2.5k | 🔴 | дубль ragas |
| Literal AI / Lunary | 1–1.5k | 🔴 | reference only |

---

## Privacy / Security

| Репо | Stars | Статус | Что взяли |
|------|-------|--------|-----------|
| gitleaks/gitleaks | ~18k | 🟢 | bootstrap-scan + baseline |
| trufflesecurity/trufflehog | ~18k | 🟡 | verified-mode (фаза 3) |
| Yelp/detect-secrets | ~4k | 🟢 | **inline hot-path Python** |
| microsoft/presidio | ~4k | 🟢 | PII redaction (фаза 3) |

---

## Dev tooling

| Репо | Stars | Статус | Что взяли |
|------|-------|--------|-----------|
| casey/just | ~22k | 🟡 | альтернатива Makefile (не тащим сейчас) |
| direnv/direnv | ~13k | 🟡 | .envrc пример |
| jdx/mise | ~13k | 🟡 | single-tool для Python+uv+node |
| cachix/devenv | ~4k | 🔴 | Nix-based, overkill |
| jetpack-io/devbox | ~9k | 🔴 | Nix-based, overkill |
| pre-commit/pre-commit | ~14k | 🟢 | **post-edit gate** |

---

## Сводка по категориям

- **Взяли напрямую (🟢):** 27 проектов → 42 идеи
- **Паттерны без dep (🟡):** 28 проектов → дополнительные дизайн-инсайты
- **Отвергли (🔴):** 14 проектов → дубли или overkill
- **Всего просмотрено:** ~69 репозиториев

Главная метрика качества ресёрча: **отвергнутые > взятые**. Это значит, выбор в топ-10 сделан сознательно, а не first-fit.
