# Phase 3a — Stabilize & Cleanup

**Status:** Approved 2026-04-11
**Owner:** Vladimir Lukin
**Follows:** Phase 2 complete (`phase-2-complete` tag)
**Precedes:** Phase 3b (Project status dashboard), Phase 3c (LLM enrichment + vector search)

## 1. Цель и философия

Устранить накопившийся post-Phase-2 tech debt, сделать install/doctor story пригодным для регулярного использования на 2-3 sibling-проектах без ручной правки конфигов. Phase 3a — это **не новый feature work**, это перевод LV_DCP из "works on my exact setup" в "works on sibling projects on the same machine". Любые соблазны расширения scope'а отвергаются.

Фаза декомпозирована из исходной "Phase 3 (LLM + Dashboard + Cleanup)" в brainstorm-сессии 2026-04-11. Обоснование декомпозиции: исходный scope ≈ 5-7 недель, три независимых pillar'а с разным профилем риска, не помещается в единый spec без потери фокуса.

## 2. Scope — 16 items в 4 категориях

### A. Install / MCP story (core unblocker)

- **M7** — CLI абсолютный path в выводе `ctx scan`. Сейчас `uv run --directory` меняет cwd, пользователь не видит, что реально просканировано. Fix: после завершения scan'а печатать `scanned N files in <absolute-resolved-path>`. Документировать `--project <path>` как canonical способ указания.
- **M8** — `ctx mcp install` через `claude mcp add --scope user`, delegate-only без fallback. Pre-flight check: `which claude` + `claude --version`, при отсутствии — exit 1 с инструкцией и подсказкой `--dry-run`. Флаг `--dry-run` печатает JSON-snippet для manual копирования (dotfiles sync use case). Поддержка `--scope {user,project,local}` с default `user`. НЕ пишет в `~/.claude/settings.json`, НЕ трогает `~/.claude.json` напрямую. Побочные эффекты install'а: (а) создаёт `~/.lvdcp/config.yaml` с дефолтами `{projects: []}`, если файла нет; (б) пишет/обновляет managed-section в `~/.claude/CLAUDE.md` с version tag `<!-- lvdcp-managed: vX.Y.Z -->`, где version читается из `libs/core/__version__`.
- **M9** — `ctx mcp uninstall --legacy-clean`. Детектирует и удаляет остатки старого broken install из `~/.claude/settings.json` (ключ `mcpServers` или аналогичный мусор, который не принадлежит permissions). Операция идемпотентна, безопасна при повторном запуске.
- **M10** — `ctx mcp doctor` с 7 checks:
  1. `claude` CLI present (WARN)
  2. `claude mcp list` contains `lvdcp` (FAIL)
  3. MCP server subprocess handshake — `python -m apps.mcp_server` → stdio initialize → response within 3s (FAIL)
  4. `~/.lvdcp/config.yaml` readable & valid (FAIL на malformed YAML или schema mismatch; "file not exists" тоже FAIL, потому что `ctx mcp install` обязан был его создать)
  5. Registered projects all have `.context/cache.db` (WARN per missing, empty projects list — PASS)
  6. `~/.claude/CLAUDE.md` managed-section present с version tag, совпадающим с installed `libs/core/__version__` (WARN если отсутствует или mismatch)
  7. Legacy pollution в `~/.claude/settings.json` (WARN, подсказка `--legacy-clean`)

  Exit codes: 0 all PASS, 1 any WARN, 2 any FAIL. По умолчанию report-only. Флаг `--fix` применим только к подмножеству (4, 6, 7). Формат вывода — table по умолчанию, `--json` для machine-readable (переиспользуемо в Phase 3b `lvdcp_status` ресурсе).
- **I3** — `ctx watch install-service` / `ctx watch uninstall-service`. Подкоманды, которые пишут `~/Library/LaunchAgents/tech.lvdcp.agent.plist` (через существующий `apps/agent/plist.py`) и выполняют `launchctl bootstrap gui/$UID <plist>` (install) / `launchctl bootout gui/$UID/tech.lvdcp.agent` (uninstall). Идемпотентны. Ограничение GUI session (`bootstrap gui/$UID` требует активной GUI) документировано в help.
- **M4** — `ctx mcp install` при успешной установке печатает WARN: `"Installed with absolute Python path <...>. If you sync dotfiles across machines, this path may be invalid on other hosts — run 'ctx mcp install' again on each host."`

### B. Daemon & runtime

- **Daemon `last_scan_at_iso` fix.** В `apps/agent/daemon.py` hook `on_scan_complete` обязан обновлять `~/.lvdcp/config.yaml:projects[<path>].last_scan_at_iso = <utcnow().isoformat()>`. Сейчас write отсутствует, field остаётся stale после incremental scan'ов. Prereq для Phase 3b health cards.
- **I2** — удалить `ctx watch start --background` флаг полностью. Canonical способ бэкграунда — `ctx watch install-service` (launchd). Причина: YAGNI, дубликат функциональности, fork-based daemon требует PID file / stale detection / logrotate — tech debt ради use case, который launchd решает лучше.
- **M1** — `ScanResult.relations_extracted` → `relations_reparsed`, добавить `total_relations_cached`. Изменить summary вывод `ctx scan` чтобы показывать оба поля: `"reparsed X relations (Y cached)"`. Устраняет UX weirdness "0 relations" при incremental scan с 0 changed files.

### C. Review items (quality)

- **I1** — `Graph.has_node(name: str) -> bool` публичный метод в `libs/graph/graph.py`. Заменить прямой доступ `graph._fwd` / `graph._rev` в `libs/retrieval/graph_expansion.py` на `graph.has_node(...)`. Grep'нуть на другие места нарушения encapsulation, поправить пакетно.
- **I4** — `.env.*` prefix-check в ignore list. Заменить явный список `{".env", ".env.local", ".env.production", ".env.staging", ".env.development"}` на: `basename == ".env" or (basename.startswith(".env.") and basename != ".env.example")`. Точное место — `libs/policies/scan.py` или `libs/parsers/walker.py`, определит exploration перед edit.
- **M2** — 4-6 targeted unit tests для `_walk_mixed` sub-walks A (file→own-symbol→caller) и B (file→imported-symbol→defining-file) в `tests/test_graph_expansion.py` или новом файле. Минимальные фикстуры (4-5 символов, 3 файла), детерминированный expected result. Это load-bearing algorithm для `impact_recall@5`, отсутствие dedicated тестов — риск regression при любом рефакторинге graph модуля.
- **M3** — runtime-build test secret patterns в `tests/test_secrets.py`. JWT test value сейчас self-flag'ится `has_secrets=True` при self-scan. Fix как уже сделан для Stripe в конце Phase 2: собирать regex на runtime из fragments. Альтернатива — live with it, но убираем UX weirdness.
- **M5** — `Pipeline._stage_graph` bare `assert self._graph is not None` → `raise RuntimeError("...")` ИЛИ change signature `_stage_graph(graph: Graph, ...)` non-optional. Предпочтительно второе (честнее типам), но определит exploration caller'ов.

### D. Documentation & governance

- **I5** — `docs/adr/001-budgets.md`: удалить stale строку "Phase 2 (с LLM summaries): 45s/90s". LLM summaries уехали в Phase 3c per ADR-004 pivot. Keep Phase 1 deterministic budget. Добавить комментарий про status.
- **I6** — `docs/constitution.md §IV` merge. Заменить пункты IV.3 + IV.4 одним:
  ```
  3. **Dogfood report** в docs/dogfood/phase-N.md, который одновременно выступает
     как Phase CHANGELOG: обязан содержать cost/latency на канареечном репо
     (LV_DCP сам), eval метрики, changed surface, known issues.
  ```
  Сдвинуть последующие пункты (§IV.4 был "обновлённая конституция или ADR", становится IV.4). Inline edit без нового ADR. Обоснование: dogfood report уже богаче типичного CHANGELOG, две артефакта с пересекающимся содержимым = рассинхронизация через 3 фазы, single source of truth.

## 3. Архитектурные изменения

Phase 3a **не создаёт новых поддоменов**, только трогает существующие + добавляет два CLI subcommand group.

| Новый/изменённый code surface | Файлы |
|---|---|
| `ctx mcp doctor` command | `apps/cli/mcp.py` (новая подкоманда), `libs/mcp_ops/doctor.py` (новый модуль — checks) |
| `ctx mcp install` rewrite | `apps/cli/mcp.py`, `libs/mcp_ops/install.py` (новый — `claude mcp add` wrapper) |
| `ctx mcp uninstall --legacy-clean` | `apps/cli/mcp.py`, `libs/mcp_ops/uninstall.py` (новый) |
| `ctx watch install-service` / `uninstall-service` | `apps/cli/watch.py`, переиспользует существующий `apps/agent/plist.py` |
| `ctx watch start` — remove `--background` | `apps/cli/watch.py`, `apps/agent/daemon.py` |
| Daemon `last_scan_at_iso` update | `apps/agent/daemon.py` — добавить config.yaml write в `on_scan_complete` hook |
| `ctx scan` abs-path output | `apps/cli/scan.py` |
| Ignore list prefix | `libs/policies/scan.py` или `libs/parsers/walker.py` |
| Graph public API | `libs/graph/graph.py`, `libs/retrieval/graph_expansion.py` |
| ScanResult rename | `libs/core/types.py` (или эквивалент), callers across parser/pipeline |
| Test secrets runtime build | `tests/test_secrets.py` |
| Pipeline assert fix | `libs/retrieval/pipeline.py` |
| Constitution/ADR edits | `docs/constitution.md`, `docs/adr/001-budgets.md` |

**Новый suite `libs/mcp_ops/`** — малый модуль, три файла: `install.py`, `uninstall.py`, `doctor.py`. Зависит от stdlib + pydantic + subprocess. Никаких зависимостей на `apps/*`. Переиспользуется в Phase 3b `lvdcp_status` MCP resource (часть `doctor.to_json()` snapshot'а).

**Нулевые изменения** в: eval harness, Qdrant/vector (ещё нет), MCP tool handlers (`lvdcp_pack`/`explain`/`inspect`/`scan` остаются как есть), parsers, retrieval algorithm. Это важно: Phase 3a **не может регрессировать** метрики Phase 2, потому что не трогает retrieval pipeline.

## 4. Data flow

Без изменений. Single-writer model, layering `apps/*` → `libs/*`, constitution discipline — всё сохраняется. Никаких новых данных. `~/.lvdcp/config.yaml` schema не меняется кроме того, что поле `projects[*].last_scan_at_iso` начинает реально обновляться daemon'ом (field уже задекларирован в схеме).

## 5. Error handling

- **`ctx mcp install` fails** (no `claude` CLI или non-zero exit from `claude mcp add`) → exit 1, stderr с инструкцией + suggest `--dry-run` для manual копирования JSON snippet. Никакого silent fallback.
- **`ctx mcp doctor` any FAIL** → exit 2, каждый fail указывает remediation command.
- **`ctx mcp doctor` any WARN, zero FAIL** → exit 1, warn-level hint.
- **`ctx watch install-service` launchctl error** → exit 3, логируем stderr launchctl verbatim, НЕ откатываем plist (идемпотентность — повторный запуск исправит после устранения причины).
- **`ctx watch install-service` running в headless session (no GUI)** → launchctl вернёт non-zero, читаемый error в stderr: `"launchctl bootstrap requires an active GUI session; run this from Terminal.app on the desktop"`.
- **Daemon config.yaml write failure** (read-only FS, etc) → WARN в daemon structlog log (поля `project_id`, `stage=config_update`), scan не падает (config update — best-effort, не critical path).

## 6. Testing strategy

- **Unit** для новых модулей (`libs/mcp_ops/doctor.py`, `libs/mcp_ops/install.py`, `libs/mcp_ops/uninstall.py`): mock subprocess, mock filesystem (`tmp_path`, `monkeypatch` `HOME`), проверка exit codes + формата вывода (table и `--json`).
- **Integration** для install/uninstall: tmp `HOME` с fake `~/.claude.json`, real subprocess для `claude mcp add` **заскипан под маркер** `@pytest.mark.requires_claude_cli` — эти тесты запускаются только на dev машине, не в CI (CI может не иметь claude CLI). Marker зарегистрирован в `pyproject.toml`.
- **M2 unit**: 4-6 тестов `_walk_mixed` sub-walks A/B. Фикстура — минимальный graph (4-5 символов, 3 файла), детерминированный expected result. Тесты идут в `tests/test_graph_expansion.py` или новом `tests/test_walk_mixed.py`.
- **Regression gate**: весь существующий `make test` должен остаться зелёным (Phase 2 закрылся с 157 тестами). Никакого пропуска существующих тестов.
- **I4 ignore list**: unit test что `.env.test`, `.env.backup`, `.env.prod`, `.env.staging.custom` все игнорируются; `.env.example` — allowed.
- **M1 ScanResult rename**: compile-time (mypy) gate + grep для старого имени = 0 хитов.
- **Dogfood**: `scripts/phase-3a-dogfood.sh` — 7-step exit criterion, запускается на {LV_DCP, Project_Medium_A, Project_Medium_B}, результат — `docs/dogfood/phase-3a.md`.

## 7. Exit criteria

Phase 3a считается закрытой когда ВСЕ выполнено:

1. Все 16 items из scope landed в main.
2. `make lint typecheck test` зелёный, >= 157 тестов + новые M2 + новые тесты для `mcp_ops` + I4 тест. Target >= 175 тестов.
3. Eval harness: `recall@5 files >= 0.85`, `precision@3 files >= 0.60`, `recall@5 symbols >= 0.80`, **`impact_recall@5 >= 0.75`** (Phase 2 thresholds не регрессированы). Желательно не упасть ниже фактических Phase 2 closing numbers (0.891 / 0.620 / 0.833 / 0.819).
4. `phase-3a-dogfood.sh` проходит 7/7 на всех 3 проектах, лог сохранён в `docs/dogfood/phase-3a.md`.
5. Constitution §IV обновлен (I6), ADR-001 обновлен (I5).
6. Git tag `phase-3a-complete` на HEAD main.

### Dogfood 7-step exit criterion

Воспроизводимый bash script, для каждого project P ∈ {LV_DCP, Project_Medium_A, Project_Medium_B}:

```
1. ctx mcp install                     → exit 0, `claude mcp list` shows lvdcp Connected
2. ctx mcp doctor                      → 7/7 PASS (zero WARN on fresh install)
3. ctx scan <P>                        → exit 0, prints absolute path, creates .context/cache.db
4. ctx watch install-service           → plist written, launchctl reports loaded
5. lvdcp_pack через MCP from Claude    → non-empty markdown pack (test through `claude -p` headless или MCP stdio handshake из doctor check 3)
6. ctx mcp uninstall --legacy-clean    → reverses (1), cleans legacy pollution
7. Zero manual edits to ~/.claude.json or ~/.lvdcp/config.yaml anywhere in flow
```

## 8. Риски и non-goals

### Риски

- **R1** — `claude mcp add` поведение различается в разных версиях Claude Code CLI. Митигация: doctor check 1 логирует версию; если `claude mcp add` сломается на старой версии — юзер увидит clear stderr, не silent corruption. Нет hard version gate (чтобы не blocker'ить на minor bumps).
- **R2** — `launchctl bootstrap gui/$UID` требует active GUI session. Не работает через SSH из headless. Митигация: `install-service` документирует ограничение, return non-zero с clear message.
- **R3** — Integration тесты `requires_claude_cli` могут гнить без CI-прогона. Митигация: manual run перед каждым phase tag, в README документирован маркер.
- **R4** — Renaming `ScanResult.relations_extracted` — backwards-incompatible для любых внешних consumers. Митигация: grep'ом проверить callers, API LV_DCP сейчас не публичный (single-dev tool), breakage local-only.
- **R5** — Phase 3a может затянуться при попытке расширить scope. Митигация: scope гвоздями прибит в этом spec'е, любое добавление требует amendment с явным отодвиганием exit.
- **R6** — `ctx mcp doctor` check 3 (MCP handshake) может тормозить стартап (fork + JSON-RPC round-trip ~100-500ms). Митигация: timeout 3s, можно скипнуть через `--skip-slow`.

### Non-goals (явный отказ)

- Новые MCP tools — не в 3a (уже 4 рабочих tools Phase 2, добавления идут в 3b/3c).
- Dashboard / UI — Phase 3b.
- LLM enrichment / summaries — Phase 3c.
- Vector search / embeddings — Phase 3c.
- TypeScript/Go/Rust parsers — Phase 5.
- Qdrant integration — Phase 5 (если 3c's sqlite-vss/pgvector хватит — никогда).
- Cross-project patterns — Phase 5.
- Refactor retrieval algorithm — forbidden in 3a, иначе рискуем eval регрессией.
- VS Code extension — Phase 6.
- Obsidian sync — Phase 3+.

## 9. Agents & workflow

Исполнение — subagent-driven-development в текущей сессии (как Phase 2 Variant C), с final review в конце.

| Agent | Where |
|---|---|
| **system-analyst** | Перед трогать `apps/cli/mcp.py` (M8/M9/M10 пересекаются — impact analysis обязателен). |
| **test-runner** | M2 sub-walk тесты + `mcp_ops` unit tests + I4 ignore list test. |
| **devops-deployer** | I3 (launchd plist install flow, launchctl bootstrap invocation). |
| **code-reviewer** | Перед merge/tag каждой из 4 категорий (A/B/C/D — как gate, не per-commit). |
| **fastapi-architect** | НЕ используется (нет API изменений). |
| **db-expert** | НЕ используется (нет schema changes). |

## 10. Оценка объёма и сроков

| Категория | Estimated work |
|---|---|
| A. Install/MCP story (M7, M8, M9, M10, I3, M4) | 3-4 рабочих дня (M8/M10 нетривиальны, остальное — 30 мин каждое) |
| B. Daemon & runtime (last_scan_at, I2, M1) | 1 рабочий день |
| C. Review items (I1, I4, M2, M3, M5) | 1-2 рабочих дня |
| D. Docs & governance (I5, I6) | 0.5 рабочего дня |
| Integration tests + dogfood script + phase-3a.md writeup | 1-2 рабочих дня |
| **Итого** | **7-10 рабочих дней**, upper bound 2 календарные недели |

## 11. Dependencies на Phase 3b/3c

Phase 3a закладывает фундамент для следующих подфаз:

- **Для Phase 3b**: daemon `last_scan_at_iso` работает → health cards F1.C имеют real data; `libs/mcp_ops/doctor.py:to_json()` переиспользуется в `lvdcp_status` MCP ресурсе; `ctx mcp doctor` — диагностика dashboard'а.
- **Для Phase 3c**: стабильный install story → юзер может чистым образом поднимать новые eval runs; `ctx watch install-service` → daemon стабильно держит инкрементные scan'ы, на которых Phase 3c будет мерить cost/latency summary pipeline'а.

Phase 3b/3c **не заблокированы** Phase 3a технически, но начинать их раньше = строить на unstable foundation.

## 12. Open questions

Нет на момент approval'а. Все design points закрыты в brainstorm-сессии 2026-04-11.

---

## Approval log

- 2026-04-11 — brainstorm session with Vladimir Lukin. Design points closed:
  - Decomposition Phase 3 → 3a/3b/3c: approved
  - I2 Variant A (remove `--background`): approved
  - M8 delegate-only + scope `user` + no version gate: approved
  - M10 7 checks + report-only default + `--fix` subset: approved
  - I6 Variant A (dogfood = Phase CHANGELOG, inline constitution edit): approved
  - Dogfood projects {LV_DCP, Project_Medium_A, Project_Medium_B} + 7-step exit: approved
  - Full design preview: approved
