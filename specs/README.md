# Specs — Top-9 из ideas-bank

Следуем методологии [spec-kit](https://github.com/github/spec-kit): для каждой идеи → `spec.md` (что и почему) → `plan.md` (как) → `tasks.md` (конкретные шаги).

Источник: [docs/research/ideas-bank/01-top10.md](../docs/research/ideas-bank/01-top10.md).

Скоуп: пункты 1–9 (все High-impact). Пункт 10 (Langfuse, M-H) отложен.

| # | Папка | Название | Статус |
|---|-------|----------|--------|
| 1 | [001-bge-m3-unified-embedder/](001-bge-m3-unified-embedder/) | bge-m3: dense + sparse + multivector | spec + plan + tasks |
| 2 | [002-bge-reranker-v2-m3/](002-bge-reranker-v2-m3/) | bge-reranker-v2-m3 на финальной стадии | spec |
| 3 | [003-matryoshka-binary-quant/](003-matryoshka-binary-quant/) | Matryoshka + binary quantization | spec |
| 4 | [004-watchfiles-watcher/](004-watchfiles-watcher/) | `watchfiles` вместо `watchdog` | spec |
| 5 | [005-gitleaks-detect-secrets/](005-gitleaks-detect-secrets/) | gitleaks + detect-secrets privacy | spec |
| 6 | [006-ragas-promptfoo-eval/](006-ragas-promptfoo-eval/) | RAGAS + promptfoo eval harness | spec |
| 7 | [007-personalized-pagerank/](007-personalized-pagerank/) | Personalized PageRank для graph expansion | spec |
| 8 | [008-shadow-git-checkpoints/](008-shadow-git-checkpoints/) | Shadow-git checkpoints (Phase 2) | spec |
| 9 | [009-search-replace-edit-format/](009-search-replace-edit-format/) | Search/replace edit format | spec |

## Порядок реализации (критический путь)

1. **#6 eval harness** — без метрик остальные изменения слепые.
2. **#1 bge-m3** — foundational для retrieval.
3. **#2 reranker** — поверх #1.
4. **#3 quant** — оптимизация #1, может идти параллельно с #2.
5. **#4 watchfiles** — независимо, критично для стабильности Phase 1.
6. **#5 privacy** — блокер production-use, независим от #1–4.
7. **#7 PPR** — зависит от наличия #6 для валидации.
8. **#9 search/replace** — foundational для Phase 2 edits.
9. **#8 shadow-git** — требует #9.
