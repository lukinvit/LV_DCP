# Retrieval: эмбеддинги, ранжирование, чанкинг, query

11 идей, сгруппированы по стадиям pipeline: embedding → hybrid search → rerank → chunking → query understanding → quality.

---

## 1. bge-m3: унифицированный эмбеддер (dense + sparse + multivector)

- **Что даёт:** одна модель выдаёт три представления за один forward. Dense — семантика, sparse — токенное совпадение (BM25-подобное), multivector — ColBERT-style late interaction. Все три можно положить как named vectors в одну Qdrant-точку.
- **Проблема:** чистый dense плохо работает на symbol-поиск (`find UUID_REGEX`), а отдельный BM25-сайдкар усложняет инфру.
- **Где:** `libs/embeddings/bge_m3.py`, миграция Qdrant-коллекций.
- **Влияние:** **H** (+20–30% NDCG@10).
- **Срок:** **2–3 дня**.
- **Источник:** FlagOpen/FlagEmbedding.

---

## 2. bge-reranker-v2-m3: cross-encoder на финальной стадии

- **Что даёт:** маленький 568M cross-encoder переранжирует топ-100 кандидатов в топ-20. Layerwise-режим (v2-minicpm) — адаптивный exit по сложности запроса.
- **Проблема:** vector-search даёт шум в топ-30. Cross-encoder смотрит на пару целиком и чистит его.
- **Где:** `libs/retrieval/rerank.py`.
- **Влияние:** **H** (+10–25% NDCG@10).
- **Срок:** **1–2 дня**.
- **Источник:** FlagEmbedding, Continue.dev LLMReranker.

---

## 3. Matryoshka + binary quantization

- **Что даёт:** обрезание вектора до 256 dim (Matryoshka) + 1-битное квантование. Two-stage search: binary rough → full precision top-50. 32× экономия памяти, <2% потерь recall.
- **Проблема:** ADR-001 жёстко лимитирует память; 1M символов в full precision — гигабайты.
- **Где:** конфиг Qdrant-коллекций, `libs/embeddings/quant.py`.
- **Влияние:** **H**.
- **Срок:** **1 день**.
- **Источник:** Qdrant docs, Jina v3.

---

## 4. Sparse vectors (BM42/SPLADE) нативно в Qdrant

- **Что даёт:** BM25-подобный сигнал как отдельный named vector, без отдельного tantivy/Meilisearch. SPLADE даёт term expansion через BERT, BM42 — классический BM25 поверх токенайзера.
- **Проблема:** keyword-queries («найти `JWT_SECRET`», «где используется `SessionLocal`») плохо ищутся чистым dense.
- **Где:** `libs/retrieval/sparse.py`.
- **Влияние:** **H** (+15–25% recall на symbol/identifier queries).
- **Срок:** **2 дня**.
- **Источник:** Qdrant docs, LightRAG.

---

## 5. Late chunking через bge-m3

- **Что даёт:** эмбеддим весь файл целиком, потом mean-pool по границам чанков. Каждый чанк «помнит» контекст всего модуля. Особенно помогает коротким методам, бесполезным без контекста класса.
- **Проблема:** при обычном chunk-then-embed короткий метод без contextа класса даёт почти нулевой сигнал.
- **Где:** `libs/embeddings/late_chunking.py`.
- **Влияние:** **M-H** (+5–15% NDCG).
- **Срок:** **3 дня**.
- **Источник:** Jina embeddings v3.

---

## 6. AST-aware chunking / CodeHierarchyNodeParser

- **Что даёт:** чанки строго по границам AST (функция/класс целиком). Hierarchy: класс → parent-chunk, методы → children. В parent тела методов заменяются на `# method body omitted, see child` — экономия ~40% токенов в summaries.
- **Проблема:** текущий symbol-level embedding хорош, но для vector-стадии чанки режутся по токенам — соседи бывают мусорными.
- **Где:** `libs/parsers/chunkers/code_hierarchy.py`.
- **Влияние:** **H** (качество + экономия токенов).
- **Срок:** **3–5 дней**.
- **Источник:** Continue.dev, LlamaIndex CodeHierarchyNodeParser.

---

## 7. Contextual compression (LLM-filter последней стадии)

- **Что даёт:** LLM-compressor идёт по top-20 chunks и оставляет только строки, релевантные query. Итоговый pack сжимается в 3–5 раз по токенам.
- **Проблема:** raw snippets раздувают pack. Много строк попадает «паровозом» и никогда не читается LLM.
- **Где:** `libs/retrieval/compressor.py`.
- **Влияние:** **H** (экономия токенов для пользователя).
- **Срок:** **2–3 дня**.
- **Источник:** LangChain ContextualCompressionRetriever.

---

## 8. HyDE + query decomposition

- **Что даёт:** (а) HyDE — дешёвая модель генерит гипотетический docstring/код для NL-запроса, эмбеддинг этого результата используется вместо raw query; (б) query decomposition — сложный вопрос разбивается на 3–5 под-вопросов, каждый ищется отдельно, результаты объединяются.
- **Проблема:** запрос «как валидируется email» плохо матчится по вектору на сырой код (нет слова «валидируется» в коде). HyDE закрывает этот разрыв.
- **Где:** `libs/retrieval/hyde.py`, `libs/retrieval/decompose.py`.
- **Влияние:** **M-H** (+10–20% MRR на NL-запросах).
- **Срок:** **3–4 дня** суммарно, LLM-вызов кэшируется по query-hash.
- **Источник:** R2R, arxiv 2212.10496.

---

## 9. doc2query offline enrichment

- **Что даёт:** для каждого символа один раз за revision генерируем 5–10 гипотетических вопросов («как использовать `Session.execute`?», «откуда берётся `config.database_url`?»), эмбеддим их и кладём в payload. При query-time обычный vector-search находит их легче, чем сырой код.
- **Проблема:** **главный recall-гап code search** — NL↔code vocabulary mismatch.
- **Где:** `apps/worker/pipelines/doc2query.py`.
- **Влияние:** **H** (+15–30% recall на NL).
- **Срок:** **4–5 дней** + ≈$1–5 на проект за LLM-генерацию.
- **Источник:** castorini/docTTTTTquery.

---

## 10. Code tokenizer (camelCase/snake_case split)

- **Что даёт:** препроцессор, который `getUserById` → `get user by id`, `USER_ID` → `user id`. Подаётся в sparse-индекс.
- **Проблема:** запрос «user by id» не находит `getUserById`, если токенайзер не знает про camelCase.
- **Где:** `libs/parsers/tokenizer.py`.
- **Влияние:** **M** (+5–10% recall на keyword queries).
- **Срок:** **2 часа**.
- **Источник:** tantivy, typesense токенайзеры.

---

## 11. Chunk quality score + template-specific chunking

- **Что даёт:** каждому chunk ставим оценку (длина, информативность, документирован ли, tested ли). При retrieval boost качественных. Плюс разные стратегии chunking для `.py` / `.md` / `.yaml` / `.sql`.
- **Проблема:** все chunks равны, но функция с docstring и тестами должна попадать в pack первой.
- **Где:** `libs/parsers/quality.py`.
- **Влияние:** **M**.
- **Срок:** **2–3 дня** quality score; **1 неделя** template chunkers.
- **Источник:** RAGFlow (infiniflow).

---

## Суммарный эффект на retrieval

Сценарий после внедрения 1+2+3+4+5 (≈10 дней работы):

| Метрика | Baseline | Ожидаемо |
|---------|----------|----------|
| NDCG@10 code retrieval | X | **X + 40–60%** |
| Memory footprint индекса | Y | **Y / 4–8** |
| Latency p50 retrieval | Z | **Z × 1.0–1.2** (незначительно хуже из-за rerank) |
| Recall на symbol queries | W | **W + 25%** |
| Recall на NL queries (+8,9) | V | **V + 30%** |

Цифры — консервативные ориентиры по публикациям (Qdrant benchmarks, Jina/BGE papers, Continue.dev, Cursor blog).
