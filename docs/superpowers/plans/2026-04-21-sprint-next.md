# Sprint backlog — ближайший спринт (после Phase 7c)

**Created:** 2026-04-21
**Context:** после 4 раундов gap-closing (G1/G2/G5/G6, R2-A/B, R2-E/F, R2-C),
все зелёные гейты, 797 тестов, 10 MCP tools, push в public repo выполнен.
Roadmap research identified 9 остающихся gaps. Этот файл фиксирует порядок.

## Priority 1 — маленькие wins (дни)

### S1. Accepted memory → pack retrieval integration
**Size:** S (1-2 hours)
**Why:** Замыкает цикл R2-C. Сейчас принятая память лежит на диске, но не
попадает в `lvdcp_pack`. Без этого память — только архив, не рабочий
инструмент.
**What:** Прочитать `status=accepted` memory при построении navigate pack и
добавить секцию "Approved memories" перед "Top files". Тест на то, что
отклонённые и proposed в pack не попадают.
**Touches:** `libs/context_pack/builder.py`, `libs/memory/store.py`,
`tests/unit/context_pack/`.
**Acceptance:** навigate pack содержит accepted memory bodies; rejected и
proposed не содержит; отдельный тест.

### S2. `devctx-bench` pip package extraction
**Size:** S (1 day)
**Why:** Нет публичного retrieval-only бенчмарка для кода. Первопроходство:
если мы ещё не поздно, можно задать индустриальный стандарт. `libs/eval`
уже reusable после round-3, остаётся только packaging + README + curated
queries.
**What:**
- Отдельный `pyproject.toml` в `bench/` с названием `devctx-bench`.
- `devctx_bench/__init__.py` re-exporting `libs.eval.*`.
- `devctx_bench/cli.py` — standalone entrypoint без LV_DCP зависимостей.
- 3 curated OSS queries.yaml (одна Python, одна TS, одна Go).
- README с "how to run vs Aider / claude-context baselines".
**Acceptance:** `pip install devctx-bench && devctx-bench --queries
./queries.yaml /repo/path` работает.

### S3. Encrypted at-rest SQLite (optional)
**Size:** S (1 day)
**Why:** Cursor 3 рекламирует encrypted index. Для team-share (S6) критично.
Для одиночного пользования — nice-to-have.
**What:** Поддержка SQLCipher через `pysqlcipher3` или переключение на
`sqlite3` с attached key. Feature-flag в `config.yaml`.
**Acceptance:** `cache.db` нечитаем без ключа; все существующие тесты
зелёные; миграция с plaintext cache на encrypted задокументирована.

## Priority 2 — средние (1-3 дня)

### S4. Local embeddings (no OpenAI)
**Size:** M (2-3 days)
**Why:** Vector search сейчас требует `OPENAI_API_KEY`. Стоимость + приватность.
Тренд 2026 — "privacy-first local-first". Continue и Cursor оба рекламируют
on-device embeddings.
**What:**
- Adapter для `sentence-transformers/all-MiniLM-L6-v2` (384-dim).
- Adapter для BGE-small (опционально, 512-dim).
- Переключение через `~/.lvdcp/config.yaml` `embedding.provider`.
- Кэш first-run (model download).
**Acceptance:** `ctx scan` с `embedding.provider=local` работает без API-ключа;
eval показывает что vector signal не хуже чем с OpenAI на 100+ файлах.

### S5. MCP Tasks support for `ctx scan`
**Size:** M (2-3 days, ждём SDK)
**Why:** `lvdcp_scan` на 1700-файловом проекте блокирует Claude Code на 20
секунд. MCP 2026 roadmap определил SEP-1686 (Tasks) как async primitive.
**What:** Когда MCP SDK выпустит Tasks в stable:
- Переписать `lvdcp_scan` как `Task`, возвращать task_id сразу.
- `lvdcp_scan_status(task_id)` как poll-point.
- Кнопка "cancel" через MCP task interrupt.
**Blocker:** MCP Python SDK ещё не опубликовал Tasks. Следить за changelog.

## Priority 3 — большие (недели)

### S6. SCIP precision layer (Python first)
**Size:** L (1-2 weeks)
**Why:** `lvdcp_neighbors` сейчас эвристический (tree-sitter). SCIP даст
compiler-accurate refs. Критично для больших рефакторов ("переименуй
session.rotate всюду"). Design документ готов:
`docs/superpowers/specs/2026-04-21-scip-precision-layer-design.md`.
**What:**
- `libs/scip/reader.py` — парсер `.scip` protobuf файлов.
- `libs/scip/enricher.py` — merging SCIP refs в existing graph с
  `provenance="scip"`.
- `lvdcp_precise_refs(symbol)` MCP tool.
- Feature-flag `scip.enabled: false` по default, пользователь ставит
  `scip-python` отдельно.
- Test fixture: `.scip` файл + проверка парсера.

### S7. Shared-team context export/import
**Size:** L (1-2 weeks)
**Why:** LV_DCP сейчас single-user. Каждый новый entrant (ByteRover, Cursor 3,
Continue) имеет team-story. Без shared context LV_DCP не может перейти из
solo → team.
**What:**
- `ctx pack-export <project>` — zip `.context/cache.db` + `memory/` + meta.
- `ctx pack-import <zip>` — merge в local index.
- Privacy filter: exclude files matching `privacy.exclude_patterns`.
- Optional: store exported pack на GitHub как CI artifact.
**Acceptance:** two machines sharing one project produce identical retrieval
results after import.

### S8. Versioned reviewable memory (full ByteRover-parity)
**Size:** L (2 weeks)
**Why:** Текущая R2-C — single-user memory list. ByteRover 2.0 делает
git-integrated reviewable memory с merge conflicts, audit log, team review.
Мы already используем markdown-файлы — `.context/memory/` можно коммитить
в git. Формализовать.
**What:**
- `.context/memory/.lvdcp-memory.log.jsonl` — audit trail (who accepted,
  when, why).
- `ctx memory diff <mem_id>` — показать proposed vs current.
- Git-aware `ctx memory sync` — merge memory changes from git pull.
- Integration с GitHub PR workflow для review via PR comments.

### S9. IDE integration за пределами VS Code
**Size:** L (~1 week per editor)
**Why:** VS Code extension — MVP. JetBrains users, Neovim users, Zed users
не могут пока использовать LV_DCP полноценно. Нужно выбрать target.
**Candidates:** JetBrains, Neovim, Zed.
**Recommendation:** Start with JetBrains (largest user base).

## Sequencing

```
Week 1: S1 (memory → pack) + S2 (devctx-bench) + S3 (encrypted SQLite)
Week 2: S4 (local embeddings)
Week 3-4: S6 (SCIP Python spike)
Week 5+: S7 (team share) OR S9 (IDE target) — зависит от user feedback
S5 (MCP Tasks): параллельно, ждём SDK
S8 (full memory): откладывается, частичное покрытие через S1
```

## Что НЕ делаем в ближайший спринт

- **Полная versioned memory (S8)** — частично покрыто S1. Возвращаемся,
  если user запросит.
- **Multi-editor IDE (S9)** — ждём user feedback какой IDE нужен первым.
- **R2-D MCP Apps UI** — слишком эксперементально, ждём SDK + Claude Code
  support.
- **G3 SCIP TypeScript / Go / Rust** — только после Python spike валидирует
  подход.

## Success metrics to track

- Test count: > 800 by end of sprint.
- MCP tool count: stable at 10 (no new tools expected — focus on quality).
- Retrieval eval: recall@5 ≥ 0.95, precision@3 ≥ 0.70 on sample_repo.
- `ctx eval` run-time на 1000-файловом проекте: < 30 секунд.
- Daemon uptime: без crashes на user workflow 1 неделя.
