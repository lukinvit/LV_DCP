# Phase 0 Research — RAGAS + Anthropic plumbing

**Date**: 2026-04-21
**Status**: Complete
**Prerequisites resolved**: T001 plumbing smoke done; plan.md / tasks.md updated to reflect actual API.

## Goals

Validate before writing 500+ LOC adapter:

1. RAGAS 0.4.x совместим с Anthropic-провайдером без adapter-слоёв?
2. Какие метрики `ragas.metrics` поддерживаются out-of-the-box для нашего use case?
3. Стоит ли использовать `LangchainLLMWrapper` (spec.md исходная гипотеза) или есть лучший путь?
4. Какой dataset schema у RAGAS 0.4.x для single-turn RAG eval?

## Findings

### Version lock

Installed and validated:

| Пакет | Версия | Назначение |
|-------|--------|-----------|
| `ragas` | `0.4.3` | LLM-judge metrics |
| `anthropic` | `0.94.0` | Claude SDK (уже был) |
| `instructor` | transitive | Structured output adapter |

**Решение**: `langchain-anthropic` **не нужен** — RAGAS 0.4.3 имеет первоклассный путь `provider='anthropic'`.

Обновление `pyproject.toml`:

```toml
eval = [
    "ragas>=0.4.3",
]
```

### API surface (что реально работает)

**Создание LLM**:

```python
from ragas.llms import llm_factory
from anthropic import Anthropic

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
llm = llm_factory("claude-haiku-4-5", provider="anthropic", client=client)
# → InstructorLLM (structured-output ready)
```

Под капотом: `instructor.from_anthropic(client)` — нативный Anthropic JSON-mode, не через langchain.

**Метрики** (новый import path; старый deprecated в v1.0):

```python
from ragas.metrics.collections import (
    context_precision,   # relevance of retrieved contexts vs query
    context_recall,      # coverage of reference answer by contexts
    faithfulness,        # answer grounded in contexts
    answer_relevancy,    # answer addresses query
)
for m in (context_precision, context_recall, faithfulness, answer_relevancy):
    m.llm = llm
```

**Dataset schema**:

```python
from ragas.dataset_schema import SingleTurnSample

sample = SingleTurnSample(
    user_input=query,
    response=answer,
    retrieved_contexts=[...],  # list[str]
    reference=gold_answer,     # optional, нужен для context_recall
)
```

### Что изменилось vs первоначальный plan.md

| В plan.md/tasks.md было | Реальный API |
|-------------------------|--------------|
| `langchain-anthropic>=0.2.0` в deps | **убрано** |
| `langchain_anthropic.ChatAnthropic` | `anthropic.Anthropic` (уже есть) |
| `LangchainLLMWrapper` | `llm_factory(provider='anthropic')` |
| `from ragas.metrics import ...` | `from ragas.metrics.collections import ...` |

### Что НЕ проверено (blocked without API key)

- Real-API call: `await context_precision.single_turn_ascore(sample)`. `ANTHROPIC_API_KEY` отсутствует в env → выполняется на pilot в T015.
- Determinism между двумя последовательными ранами с кэшем — требует реального API, проверка в T014/T015.
- Фактический cost на 32 queries × 4 метрики — оценка в plan.md (~$0.06 на Haiku) осталась, но свериться с реальным spend можно только на T015.

### Deprecation signals

RAGAS 0.4.3 показывает deprecation warnings (актуально к v1.0):

- `from ragas.metrics import X` → `from ragas.metrics.collections import X`
- `LangchainLLMWrapper` → `llm_factory(provider='...', client=...)`

Сразу пишем на нового API — не технический долг.

## Impact на plan.md / tasks.md

1. **pyproject.toml (T001)**: только `ragas>=0.4.3`; `langchain-anthropic` удалён.
2. **tasks.md T010 (RagasAdapter)**: использовать `llm_factory(provider='anthropic')` + `ragas.metrics.collections`.
3. **plan.md Risks**: риск «RAGAS + anthropic несовместимость» — **закрыт**, native provider работает.
4. **Риск InstructorLLM warning для openai clients** — не наш кейс (мы anthropic), игнорируется.

## Smoke-test команда (для reproducibility)

```bash
uv sync --extra eval
uv run python -c "
from ragas.llms import llm_factory
from ragas.metrics.collections import context_precision, context_recall, faithfulness, answer_relevancy
from ragas.dataset_schema import SingleTurnSample
from anthropic import Anthropic

llm = llm_factory('claude-haiku-4-5', provider='anthropic', client=Anthropic(api_key='dummy'))
for m in (context_precision, context_recall, faithfulness, answer_relevancy):
    m.llm = llm
print('OK')
"
```

## Next step

→ T002–T009 (EvalConfig, Makefile, `.gitignore`, `dataset_schema.py`, `cost_guard.py`, unit tests). После — T010+ (RagasAdapter).
