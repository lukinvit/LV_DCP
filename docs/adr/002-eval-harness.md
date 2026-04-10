# ADR-002: Retrieval evaluation harness as contract

**Status:** Accepted
**Date:** 2026-04-10
**Supersedes:** —

## Context

Качество retrieval-системы — свойство, которое нельзя оценить чтением кода. Без формального способа измерить «стало лучше или хуже», любое изменение pipeline (новый парсер, новый ranker, смена embedding model, изменение промпта) превращается в vibes-based debugging. Опыт RAG-проектов однозначен: команды, начавшие с eval harness, итерируют в 3–5 раз быстрее и не откатывают релизы.

Конституция Раздел II.4 (Measurement before optimization) требует этого как инварианта. Этот ADR фиксирует **как именно**.

## Decision

### 1. Eval harness — обязательный артефакт Phase 0

Eval harness существует **до** первого retrieval-кода. Явная последовательность:

1. Phase 0: harness scaffold + fixture repo + query set + метрики
2. Phase 0: stub retrieval, возвращающий пусто → harness зелёный, метрики = 0.0
3. Phase 1+: каждое улучшение retrieval поднимает метрики, регрессии ловятся автоматически

### 2. Структура

```
tests/eval/
  fixtures/
    sample_repo/          # фикстурный мини-репо, ~30 файлов
      app/
      tests/
      docs/
      pyproject.toml
      README.md
  queries.yaml            # 20 запросов с expected targets
  run_eval.py             # runner — импортирует retrieval pipeline, запускает запросы
  metrics.py              # recall@k, precision@k, MRR
  test_eval_harness.py    # pytest wrapper, применяет пороги
```

### 3. Формат queries.yaml

```yaml
version: 1
queries:
  - id: q01-symbol-lookup
    text: "where is the User model defined"
    mode: navigate
    expected:
      files:
        - app/models/user.py
      symbols:
        - app.models.user.User
      min_rank: 1  # должен быть в top-1
  - id: q02-cross-file
    text: "which handlers use the User model"
    mode: navigate
    expected:
      files:
        - app/handlers/auth.py
        - app/handlers/profile.py
      min_rank: 3
```

### 4. Метрики

- **recall@k** — доля expected файлов, попавших в топ-k retrieval
- **precision@k** — доля топ-k, которые реально в expected
- **MRR** (mean reciprocal rank) — 1/rank первого корректного хита
- **files_vs_symbols** отдельно — retrieval может работать хуже на символах, чем на файлах; нужно видеть оба

### 5. Пороги (gated)

Пороги применяются через pytest markers и fail-fast в CI:

| Phase | recall@5 (files) | precision@3 (files) | recall@5 (symbols) |
|---|---|---|---|
| 0 | ≥ 0.0 (stub) | ≥ 0.0 | ≥ 0.0 |
| 1 | ≥ 0.70 | ≥ 0.55 | ≥ 0.60 |
| 2 | ≥ 0.85 | ≥ 0.70 | ≥ 0.75 |
| 3 | ≥ 0.85 | ≥ 0.70 | ≥ 0.75 (не регрессировать) |

Активная фаза указывается в `tests/eval/thresholds.yaml` и обновляется явным PR.

### 6. CI правила

- `make eval` (= `pytest -m eval`) — часть обязательного test suite
- Любой PR, меняющий файлы в `libs/retrieval/`, `libs/parsers/`, `libs/graph/`, `libs/embeddings/`, `libs/summarization/` — **обязан** прикреплять before/after eval таблицу в описание PR
- Если метрики регрессируют на ≥ 0.03 по любой из метрик — PR блокируется пока либо не исправлено, либо явно утверждено как trade-off с обоснованием

### 7. Запрещено

- Изменять `queries.yaml` или `fixtures/sample_repo/` в том же PR, который меняет retrieval-код. Иначе «улучшение» можно замаскировать переписыванием теста.
- Добавлять запросы, дублирующие существующие, чтобы искусственно поднять метрики.
- Запускать eval против LLM без фиксированных seed/temperature=0.

### 8. Dogfood eval (вторичный harness)

Параллельно с fixture repo eval, поддерживается **dogfood eval** — набор запросов против самого LV_DCP (когда он станет не пуст). Эти запросы не блокируют CI (метрики нестабильны, код меняется часто), но логируются и сравниваются между PR для качественного ощущения.

## Consequences

### Positive
- Retrieval становится объективно измеримым.
- Eval harness задаёт задачи — сначала понимаем, что хотим извлечь, потом строим как.
- Регрессии ловятся мгновенно, не через неделю.
- Дисциплина «before/after в PR» устраняет споры о качестве.

### Negative
- Поддержка queries.yaml требует времени при росте fixture repo.
- 20 запросов — мало; нужно расширять до 50–100 к Phase 2.
- Fixture repo нужно периодически обновлять, чтобы отражать реальный код (но не слишком часто — иначе пороги плавают).

### Operational
- Owner eval harness'а — автор (нет команды). Ревью изменений queries.yaml = ревью самим собой с задержкой (не меняй `queries.yaml` и retrieval в одном сеансе).

## Alternatives considered

1. **No harness, manual QA** — отвергнуто. Не масштабируется и несовместимо с конституцией Раздела II.4.
2. **Harness as optional CI stage** — отвергнуто. Optional = выключается при любом давлении.
3. **Real-repo-only eval** (без fixture) — отвергнуто. Неконтролируемо и нестабильно для порогов.
4. **LLM-based LLM-judge eval** (judge model оценивает правильность) — отвергнуто на старте как дорого и нестабильно. Может быть добавлено в Phase 5 как secondary signal.
