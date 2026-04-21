# Integrations: MCP, Obsidian, UX

10 идей — как LV_DCP интегрируется с экосистемой и как пользователь им пользуется.

---

## 1. FastMCP 2.x для всех MCP-серверов

- **Что даёт:** FastAPI-подобный фреймворк поверх MCP-SDK. `@mcp.tool()` декораторы, middleware, in-process `Client` для тестов, `mount()` композиция.
- **Проблема:** наш `lvdcp_pack` уже MCP-shaped. Без FastMCP — boilerplate-код на каждом tool. С FastMCP — несколько сотен строк закрывают retrieval + graph + policies servers.
- **Где:** `apps/mcp/` (новый) или `apps/backend/mcp_mount.py`.
- **Влияние:** **H** — открывает весь рынок IDE (Claude Desktop, Cursor, Zed, Goose).
- **Срок:** **2–3 дня**.
- **Источник:** jlowin/fastmcp (12k★).

---

## 2. MCP memory-server schema alignment

- **Что даёт:** Anthropic reference memory-server использует entities / relations / observations. Если наш граф совместим, получаем бесплатный интероп с клиентами MCP.
- **Проблема:** наша schema разрабатывалась в изоляции. Выровнять дёшево и даст совместимость.
- **Где:** `libs/graph/schema.py`.
- **Влияние:** **M**.
- **Срок:** **1–2 дня**.
- **Источник:** modelcontextprotocol/servers.

---

## 3. Reference MCP servers — cherry-pick

- **Что даёт:** не писать своё там, где Anthropic дал reference:
  - `mcp-server-filesystem` — read-only raw access.
  - `mcp-server-git` — git-intel бесплатно.
  - `mcp-server-sequential-thinking` — meta-tool для декомпозиции.
- **Где:** `deploy/mcp-gateway/` — композиция серверов.
- **Влияние:** **M**.
- **Срок:** **1–2 дня**.
- **Источник:** modelcontextprotocol/servers (35k★).

---

## 4. repomix-style XML-pack с TOC + token preview

- **Что даёт:**
  - XML-структура `<file_summary>`, `<directory_structure>`, `<files>` — LLM-friendly границы.
  - Token count preview с diff «что вошло / что отрезано».
  - Compression flags (`--remove-comments`, `--remove-empty-lines`) — до −30% токенов.
- **Проблема:** текущий pack — plain text. XML даёт Claude ясные границы и снижает hallucination файлов вне pack.
- **Где:** `libs/retrieval/pack_format.py`, CLI `ctx pack --dry-run`.
- **Влияние:** **M-H** (adherence к grounded answers).
- **Срок:** **0.5 дня**.
- **Источник:** yamadashy/repomix (18k★).

---

## 5. Context pins + per-mode sticky models

- **Что даёт:**
  - `ctx pin <path>` / `ctx drop <path>` — пользователь явно закрепляет файлы в pack, агент их не вытесняет.
  - Sticky models per mode: plan на Opus, act на Haiku. Экономия cost без потери качества.
- **Проблема:** при long-running tasks важные файлы теряются в retrieval noise. Pins решают это.
- **Где:** `libs/memory/pins.py`, CLI `apps/cli/pin.py`, `libs/config/modes.py`.
- **Влияние:** **M-H** (UX + cost).
- **Срок:** **2 дня** pins + **1 день** model routing.
- **Источник:** Plandex, Roo Code custom modes.

---

## 6. Obsidian local-rest-api для 2-way sync

- **Что даёт:** двусторонний sync: backend пишет summaries в vault, пользователь правит вручную, правки уважаются при re-generate. ETag-based atomic writes.
- **Проблема:** текущий `libs/obsidian` — one-way dump. Пользователь не может добавить ручные заметки без потери их при следующем rebuild.
- **Где:** `libs/obsidian/sync.py`, `libs/obsidian/client.py`.
- **Влияние:** **M** — Obsidian становится editable surface.
- **Срок:** **3–5 дней**.
- **Источник:** coddingtonbear/obsidian-local-rest-api.

---

## 7. Obsidian Dataview frontmatter schema (dashboards)

- **Что даёт:** стандартный frontmatter в публикуемых summary: `project_id`, `importance`, `revision`, `last_indexed`, `symbol_count`. Пользователи пишут Dataview-запросы внутри Obsidian — dashboards без кастомного UI.
- **Проблема:** админка `apps/web` откладывается. Dataview закрывает 80% dashboards бесплатно.
- **Где:** `libs/obsidian/frontmatter.py` — стандартизация схемы.
- **Влияние:** **M** — откладывает разработку web UI.
- **Срок:** **1–2 дня**.
- **Источник:** blacksmithgu/obsidian-dataview (9k★).

---

## 8. Quartz — публичный KB site

- **Что даёт:** статический site-generator из Obsidian vault. `make publish-kb` — сайт на GitHub Pages.
- **Проблема:** команды хотят делиться knowledge base с коллегами без Obsidian. Quartz делает это одной командой.
- **Где:** `deploy/quartz/`, `Makefile`.
- **Влияние:** **L-M** (teamwork).
- **Срок:** **1–2 дня**.
- **Источник:** jackyzha0/quartz (9k★).

---

## 9. Jinja templates для pack-форматов

- **Что даёт:** pack-builder использует шаблоны `libs/retrieval/templates/navigate.j2`, `edit.j2`, `impact.j2`. Пользователи кастомизируют формат без PR в ядро.
- **Проблема:** формат pack захардкожен. Разные пользователи хотят разные разметки.
- **Где:** `libs/retrieval/templates/`.
- **Влияние:** **M** (extensibility).
- **Срок:** **1 день**.
- **Источник:** code2prompt (mufeedvh).

---

## 10. Pack providers plugin API (Continue.dev style)

- **Что даёт:** плагинная модель для расширения pack-сборки: `@file`, `@folder`, `@diff`, `@url`, `@symbol`. Пользователи пишут свои providers.
- **Проблема:** сейчас pack-assembly монолитна. Для разных задач нужны разные источники (git diff, terminal output, URL).
- **Где:** `libs/retrieval/providers/`.
- **Влияние:** **M**.
- **Срок:** **3 дня**.
- **Источник:** Continue.dev context providers, Zed slash-commands.

---

## Отвергнутые или отложенные

- **obsidian-smart-connections** — overlap с нашим retrieval, не тащим.
- **Logseq** — только как референс для block-level references.
- **SilverBullet** — reference-only.
- **Hammerspoon** — не Python-native, не подходит архитектурно.
- **mcp-agent как framework** — паттерны полезны (Router/Parallel/Orchestrator), но сам фреймворк тяжёл; реализуем свои async-примитивы.
