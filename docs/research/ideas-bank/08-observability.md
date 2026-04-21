# Observability + Evaluation

4 идеи — закрывают ADR-001 (budgets) и ADR-002 (eval as contract).

---

## 1. Langfuse self-hosted

- **Что даёт:** единое UI/API для:
  - **Traces** — каждый retrieval-pipeline виден как дерево spans с token/cost/latency.
  - **Datasets + Eval runs** — прогоняем наши labeled queries, сравниваем метрики между commits.
  - **Prompt registry** — versioned prompts, A/B, rollback без деплоя.
  - **Cost tracking** — per-project, per-user, per-feature.
- **Проблема:** сейчас observability = structlog. Не видно cost-per-project, prompts размазаны по коду, нет diff между eval-прогонами.
- **Где:**
  - `libs/telemetry/langfuse.py` — клиент.
  - `libs/summarization/prompts/` → переезд в Langfuse registry.
  - `deploy/docker-compose/langfuse.yml` — self-hosted сервис.
- **Влияние:** **H** — закрывает ADR-001 как инфру.
- **Срок:** **3–5 дней**.
- **Источник:** langfuse/langfuse (9k★).

---

## 2. promptfoo + ragas как eval stack

- **Что даёт:**
  - **promptfoo** — YAML-декларации тестов с assertion-types (`contains-any`, `is-json`, `llm-rubric`). CI-интеграция: fail build на деградации.
  - **ragas** — RAG-метрики: **Context Precision@K, Context Recall@K, Faithfulness, Answer Relevancy**. LLM-as-judge под капотом, reference-free режим.
- **Проблема:** ADR-002 требует retrieval quality как контракт, но без метрик все улучшения слепые. Synthetic test-set (ragas умеет генерировать из codebase) закрывает начальный data gap.
- **Где:**
  - `libs/eval/metrics.py` — обёртка ragas.
  - `tests/eval/promptfoo/` — YAML-сьют.
  - `Makefile` (`make eval`).
- **Влияние:** **H** — без этого всё остальное слепое.
- **Срок:** **2–3 дня**.
- **Источники:** promptfoo/promptfoo (8k★), explodinggradients/ragas (8k★).

---

## 3. OpenLLMetry auto-instrumentation

- **Что даёт:** OTel-совместимые трейсы для Anthropic SDK, Qdrant, SQLAlchemy, FastAPI, Redis — без ручной обвязки. Semantic conventions для LLM (`gen_ai.request.model`, `gen_ai.usage.input_tokens`).
- **Проблема:** ручное trace-wrapping LLM-вызовов — boilerplate. OpenLLMetry даёт это бесплатно, плюс совместимость с любым OTel-backend (Jaeger, Tempo, Langfuse).
- **Где:** `libs/telemetry/otel.py` — инициализация, auto-instrumentors.
- **Влияние:** **M** — удобно + standard-совместимо.
- **Срок:** **2 дня**.
- **Источник:** traceloop/openllmetry (6k★).

---

## 4. Aider polyglot benchmark

- **Что даёт:** воспроизводимый benchmark — 225+ exercism-задач на многих языках с unit-тестами. Метрика — pass@1 end-to-end (наш retrieval → Claude edit → tests pass).
- **Проблема:** ragas меряет retrieval-качество, но не edit-качество. Polyglot закрывает end-to-end контракт для фазы 2.
- **Где:** `tests/eval/polyglot/`, `Makefile` (`make eval-edit`).
- **Влияние:** **M-H** для фазы 2.
- **Срок:** **1 неделя**.
- **Источник:** Aider benchmarks.

---

## Архитектура observability (рекомендуемая)

```
┌─────────────────┐   ┌─────────────────┐
│ apps/backend    │   │ apps/worker     │
│ FastAPI routes  │   │ Dramatiq tasks  │
└────────┬────────┘   └────────┬────────┘
         │ OTel traces          │ OTel traces
         │ (auto-instrumented   │ (auto-instrumented via
         │  via OpenLLMetry)    │  OpenLLMetry)
         └──────────┬───────────┘
                    │
            ┌───────▼────────┐
            │  Langfuse      │  ← self-hosted, Docker
            │  - traces UI   │
            │  - cost dash   │
            │  - prompt reg  │
            │  - eval runs   │
            └───────┬────────┘
                    │
            ┌───────▼────────┐
            │  pytest + ragas│  ← CI gate
            │  pytest +      │
            │   promptfoo    │
            └────────────────┘
```

## Отвергнутые (дубли или overkill)

- **Helicone** — дубль Langfuse, но proxy-based. Хорош для быстрого старта, но Langfuse — более мощный для нашего use case.
- **Arize Phoenix** — хороший, но дубль Langfuse функционально.
- **TruLens** — дубль ragas.
- **DeepEval** — промежуточный между promptfoo и ragas; если promptfoo+ragas хватит, DeepEval не нужен.

## Golden-метрики для quarterly review

- Context Precision@5 ≥ 0.85 (ADR-002)
- Context Recall@20 ≥ 0.90
- End-to-end edit pass@1 на polyglot ≥ 40% (baseline Aider + Sonnet)
- Retrieval latency p95 ≤ 600ms (ADR-001)
- Token cost per pack p95 ≤ 5000 tokens
- Faithfulness score ≥ 0.80
