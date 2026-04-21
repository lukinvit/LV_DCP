# Roadmap: когда что делать

Разбивка 42 идей по 3 фазам. Приоритет внутри каждой фазы — по убыванию ROI.

---

## Фаза 1 (СЕЙЧАС) — Foundation + retrieval baseline

**Цель:** снять технический долг до того, как он закреплён тестами; получить измеримый retrieval baseline.

**~3 недели одного разработчика.**

### Обязательные (блокеры)

| Идея | Файл | Срок |
|------|------|------|
| `watchfiles` вместо `watchdog` | [06-agent-desktop.md](06-agent-desktop.md) #1 | 2–3 д |
| `gitleaks` + `detect-secrets` privacy-слой | [07-privacy.md](07-privacy.md) #1 | 2–3 д |
| `pre-commit` post-edit gate | [07-privacy.md](07-privacy.md) #4 | 0.5 д |
| `.dcpignore` в формате `.stignore` | [06-agent-desktop.md](06-agent-desktop.md) #4 | 2 ч |
| RAGAS + promptfoo eval harness | [08-observability.md](08-observability.md) #2 | 2–3 д |

### Retrieval core (главный ROI)

| Идея | Файл | Срок |
|------|------|------|
| `bge-m3` унифицированный эмбеддер | [03-retrieval.md](03-retrieval.md) #1 | 2–3 д |
| `bge-reranker-v2-m3` финальный rerank | [03-retrieval.md](03-retrieval.md) #2 | 1–2 д |
| Matryoshka + binary quantization | [03-retrieval.md](03-retrieval.md) #3 | 1 д |
| Sparse vectors BM42/SPLADE в Qdrant | [03-retrieval.md](03-retrieval.md) #4 | 2 д |
| Code tokenizer (camelCase/snake_case) | [03-retrieval.md](03-retrieval.md) #10 | 2 ч |
| Personalized PageRank graph expand | [04-graph.md](04-graph.md) #1 | 2–3 д |

### UX и инфраструктура

| Идея | Файл | Срок |
|------|------|------|
| Langfuse self-hosted | [08-observability.md](08-observability.md) #1 | 3–5 д |
| `repomix`-style XML-pack с TOC | [09-integrations.md](09-integrations.md) #4 | 0.5 д |
| Context pins (`ctx pin`/`ctx drop`) | [09-integrations.md](09-integrations.md) #5 | 1 д |
| MCP memory-server schema alignment | [09-integrations.md](09-integrations.md) #2 | 1–2 д |

---

## Фаза 2 — Intelligence + edit safety

**Цель:** граф становится полноценным; агент может безопасно писать код.

**~4–5 недель.**

### Retrieval advanced

| Идея | Файл | Срок |
|------|------|------|
| AST-aware chunking / CodeHierarchy | [03-retrieval.md](03-retrieval.md) #6 | 3 д |
| Late chunking через bge-m3 | [03-retrieval.md](03-retrieval.md) #5 | 3 д |
| Contextual compression (LLM-filter) | [03-retrieval.md](03-retrieval.md) #7 | 2–3 д |
| HyDE + query decomposition | [03-retrieval.md](03-retrieval.md) #8 | 3–4 д |
| doc2query offline enrichment | [03-retrieval.md](03-retrieval.md) #9 | 4–5 д |

### Graph

| Идея | Файл | Срок |
|------|------|------|
| Leiden communities + community reports | [04-graph.md](04-graph.md) #2 | 1–2 нед |
| Temporal edges + episodes | [04-graph.md](04-graph.md) #3 | 1 нед |
| SCIP precise layer (scip-python) | [04-graph.md](04-graph.md) #4 | 1–2 нед |

### Edit safety (критично)

| Идея | Файл | Срок |
|------|------|------|
| Shadow-git checkpoints | [05-edit-safety.md](05-edit-safety.md) #1 | 1 нед |
| Search/replace edit format | [05-edit-safety.md](05-edit-safety.md) #2 | 1–2 д |
| LangGraph-style state machine | [05-edit-safety.md](05-edit-safety.md) #3 | 3–5 д |
| Apply-model (Haiku) для diff | [05-edit-safety.md](05-edit-safety.md) #4 | 1 д |
| Memory ops enum (ADD/UPDATE/DELETE) | [05-edit-safety.md](05-edit-safety.md) #6 | 3–5 д |

### Observability advanced

| Идея | Файл | Срок |
|------|------|------|
| OpenLLMetry auto-instrumentation | [08-observability.md](08-observability.md) #3 | 2 д |
| Aider polyglot eval | [08-observability.md](08-observability.md) #4 | 1 нед |

### Desktop

| Идея | Файл | Срок |
|------|------|------|
| Merkle-tree sync agent↔backend | [06-agent-desktop.md](06-agent-desktop.md) #2 | 3–5 д |
| Block-level hashing | [06-agent-desktop.md](06-agent-desktop.md) #3 | 1–2 нед |
| launchd best-practice plist | [06-agent-desktop.md](06-agent-desktop.md) #5 | 1 д |

---

## Фаза 3 — Power user

**Цель:** внешние интеграции, dashboards, optional локальные модели.

### Integrations

| Идея | Файл | Срок |
|------|------|------|
| FastMCP 2.x для всех серверов | [09-integrations.md](09-integrations.md) #1 | 2–3 д |
| Obsidian local-rest-api 2-way sync | [09-integrations.md](09-integrations.md) #6 | 3–5 д |
| Obsidian Dataview schema (dashboards) | [09-integrations.md](09-integrations.md) #7 | 1–2 д |
| Quartz — публичный KB site | [09-integrations.md](09-integrations.md) #8 | 1–2 д |
| Shadow-workspace / overlay FS | [05-edit-safety.md](05-edit-safety.md) #5 | 1–2 нед |

### Privacy advanced

| Идея | Файл | Срок |
|------|------|------|
| Presidio PII redaction | [07-privacy.md](07-privacy.md) #3 | 3–5 д |
| Cody-style context filters | [07-privacy.md](07-privacy.md) #2 | 1–2 д |

### UX

| Идея | Файл | Срок |
|------|------|------|
| Jinja templates для pack-форматов | [09-integrations.md](09-integrations.md) #9 | 1 д |
| Chunk quality score | [03-retrieval.md](03-retrieval.md) #11 | 2–3 д |
| Pack providers plugin API | [09-integrations.md](09-integrations.md) #10 | 3 д |

---

## Визуальный roadmap

```
Фаза 1 (3 нед):  [watchfiles] [privacy] [eval] → [bge-m3 retrieval stack] → [PPR graph] → [Langfuse]
Фаза 2 (4-5 нед): [AST chunk + HyDE + doc2query] → [communities + temporal] → [shadow-git + edit format + state machine]
Фаза 3 (по мере спроса): [FastMCP + Obsidian 2-way + Quartz] → [overlay FS + presidio]
```

## Что НЕ делать

Прямые дубли и тяжёлые зависимости отвергнуты:
- **Chroma** — покрыто Qdrant
- **Vespa** как замена — overkill
- **LangChain целиком** — копируем паттерны, но не тащим dep
- **LlamaIndex целиком** — аналогично, только идеи
- **TruLens** — дубль RAGAS + DeepEval
- **Letta/MemGPT как framework** — слишком тяжёлый для нашей single-writer модели
- **SFR/NV-Embed** — 7B+ эмбеддеры, overkill по ADR-001 бюджетам
- **Legacy CodeBERT/UnixCoder** — только baseline для eval
