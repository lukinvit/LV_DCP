# Phase 3b — Project Status Dashboard

**Status:** Approved 2026-04-11
**Owner:** Vladimir Lukin
**Follows:** Phase 3a complete (`phase-3a-complete` tag, 0.0.0 → bump 0.3.1 in 3b)
**Precedes:** Phase 3c (LLM enrichment + vector search + rerank)

## 1. Цель

Дать single-dev разработчику с 20+ Python проектами на macOS одним взглядом: "какие проекты проиндексированы, где всё работает, где что-то сломалось, и сколько моего Claude Code weekly budget я уже сжёг". Plus programmatic access к тем же данным через MCP resource для Claude.

## 2. Context и источники

Brainstorm 2026-04-11 закрыл все design points:
- Subscription: Max plan (Usage Report API недоступен → F1.D через per-project `~/.claude/projects/<encoded>/*.jsonl` reading)
- Routing: Variant C hybrid (`ctx ui` → multi-project index, `ctx ui <path>` → project detail view)
- Graph library: **D3.js** (user preference — future Phase 5+ viz reuse)
- MCP resource: **Shape 1** (один `lvdcp_status` с optional `path` argument, graph только в detail mode)
- F1.B source: **Variant C** (persist RetrievalTrace + scan_history, reuse existing instrumentation вместо building new)
- Upgrade: git pull + uv sync + doctor self-heal, no auto-update
- Version scheme: phase-based (0.3.1 = Phase 3b)

## 3. Scope — 4 deliverables

### D1 — `ctx ui` FastAPI+HTMX server

- **Routing (Variant C hybrid)**:
  - `ctx ui` без args → запускает сервер, открывает index page `/` — multi-project grid со всеми зарегистрированными проектами из `~/.lvdcp/config.yaml`
  - `ctx ui <path>` → запускает сервер, сразу открывает `/project/<slug>` detail view этого проекта
- **Binding**: strictly `127.0.0.1:8787` (default port), `--port N` optional flag, `--no-browser` optional flag to skip auto-open
- **No auth**: single-dev local tool, localhost-only, no TLS, no session management
- **Stack**: FastAPI + Jinja2 templates + HTMX (partials) + D3.js v7 (vendored offline, not CDN)
- **Refresh**: manual (header "refresh" link); no HTMX polling, no SSE. User смотрит dashboard раз в сессию, auto-refresh overkill

### D2 — 4 F1 секции

**F1.A — Dependency graph (detail view only)**
- D3 force-directed, canvas rendering via `d3-selection` + manual `canvas` tick loop (SVG would lag beyond ~500 edges)
- Node/edge data from existing `libs/graph/builder.py:Graph` (sqlite relations → Graph construction via `libs/project_index`)
- Cap: 200 visible nodes; projects with more show top-200 by degree + "show +N hidden" toggle that re-renders with different cap
- Node color by file role: `code` (blue), `test` (green), `config` (yellow), `docs` (gray)
- Click node → side panel shows file path, imported symbols, relations count (in/out)
- Layout: `d3-force` with `forceManyBody(-30)`, `forceLink.distance(50)`, `forceCenter`, `alphaDecay(0.02)` for fast settle
- Controls: zoom (wheel), pan (drag background), click (select), double-click (highlight neighbourhood)

**F1.B — Timeline sparklines (detail view only)**
- 4 sparklines stacked vertically, rolling 7d / 30d toggle (default 7d)
- Data source: new `~/.lvdcp/traces.db` (RetrievalTrace persistence) + `scan_history` table (daemon events)
- Metrics:
  1. **Queries per day** — count of `RetrievalTrace` rows per day
  2. **Scans per day** — count of `scan_history` rows per day (daemon + manual `ctx scan`)
  3. **Pack latency p95** — `percentile(sum(trace.stages.elapsed_ms), 95)` per day
  4. **Avg coverage** — `mean(trace.coverage.score)` per day, where `coverage.score` is derived from `Coverage.label` (covered=1.0, partial=0.5, ambiguous=0.25, missing=0.0)
- Rendering: D3 `d3-scale-linear` + `d3-axis` + `d3-line`, ~80x20 px sparklines inline
- Empty state: "No data yet — run a few `ctx pack` commands to populate history"

**Daemon status detection**: `libs/status/daemon_probe.py` вызывает `launchctl list tech.lvdcp.agent` subprocess, exit code 0 + stdout row = running (green), exit 113 = not loaded (gray), other non-zero = error (red, display stderr in tooltip).

**F1.C — Health cards (index view, condensed in detail view header)**
- Per-project card displaying:
  - Name (from project root basename)
  - File count / symbol count / relation count (from `.context/cache.db` via existing `ProjectIndex`)
  - Last scan: relative time ("5m ago") from `config.yaml:projects[*].last_scan_at_iso`
  - Daemon status indicator: green dot = `launchctl list tech.lvdcp.agent` returns row, gray = not loaded, red = `last_scan_status == "error"`
  - Stale flag: red border if `last_scan_at` > 24h AND project has recent file modifications (stat filesystem for mtime check)
  - Quick actions: "open detail", "rescan" (HTMX POST to `/api/project/<slug>/scan`)
- Grid layout, 3-column on desktop (>1200px), 2-column (768-1200px), 1-column (<768px)

**F1.D — Claude usage (both views, global aggregate in header)**
- Source: `~/.claude/projects/<encoded>/*.jsonl` — for each session file, iterate records of type `assistant`, sum `message.usage.{input_tokens, cache_creation_input_tokens, cache_read_input_tokens, output_tokens}`
- Path encoding: replace `/` → `-`, strip leading `/` (matches observed `.claude/projects/` structure)
- Aggregation windows:
  - Rolling 7d (primary, matches Claude Code limit window)
  - Rolling 30d (broader context)
- Display in header: `7d: 1.2M in / 80K out / 5.1M cache | 30d: 4.8M in / 320K out`
- Relative comparison below: `vs 30d median: +40%` (колир: green <100%, yellow 100-150%, red >150%)
- Per-project breakdown in detail view: same metrics filtered to that project's encoded folder only
- NO "% of limit" — Claude Code Max limits opaque, не обещаем то чего не знаем
- Cache: `~/.lvdcp/claude_usage.db` with `(session_file_path, last_offset, computed_totals)` rows — incremental read, не reparse'им уже прочитанные JSONL files

### D3 — `lvdcp_status` MCP resource (Shape 1)

Один resource, registered alongside existing 4 tools:

```python
@tool(name="lvdcp_status")
async def lvdcp_status(path: str | None = None) -> StatusResponse: ...
```

**When `path=None`** — global workspace + projects array:
```json
{
    "workspace": {
        "projects_count": 5,
        "total_files": 672, "total_symbols": 4821, "total_relations": 11230,
        "claude_usage_7d": {"input_tokens": 1200000, "output_tokens": 80000, "cache_read": 5100000, "cache_creation": 120000},
        "claude_usage_30d": {...},
        "daemon_running": true, "daemon_last_error": null
    },
    "projects": [
        {
            "root": "/abs/path", "name": "LV_DCP", "slug": "lv-dcp",
            "files": 176, "symbols": 1332, "relations": 3193,
            "last_scan_at_iso": "2026-04-11T17:00:00Z", "last_scan_status": "ok",
            "stale": false,
            "coverage_last_7d_avg": 0.82,
            "queries_last_7d": 42,
            "claude_usage_7d": {"input_tokens": 800000, "output_tokens": 50000, "cache_read": 3200000, "cache_creation": 80000}
        }
    ]
}
```

**When `path="/abs/path"`** — same shape, но `projects` array содержит только этот проект, + добавляется top-level `"graph": {"nodes": [...], "edges": [...]}` с полным graph dump (cap 1000 nodes for MCP payload budget).

**Payload budget**: global view ~5-10 KB JSON на 20 проектов (без графов). Detail view ~50-80 KB с графом для 200-node проекта. Больше 20 KB (target для packs) допустимо потому что resource — это **data**, не **summary**, budget relax'ится.

### D4 — Data infrastructure

**D4.1 — `libs/trace_store/` — RetrievalTrace persistence**
- Sqlite db at `~/.lvdcp/traces.db`
- Schema: `traces(trace_id TEXT PRIMARY KEY, project_root TEXT, query TEXT, mode TEXT, timestamp REAL, elapsed_ms_total REAL, coverage_label TEXT, coverage_score REAL, stages_json TEXT, created_at REAL)`
- Retention: rolling 30 days, daily prune job (run at startup + every N hours if daemon)
- Write path: hook в `Pipeline.retrieve()` return — после успешного retrieve, async `asyncio.to_thread(store.persist_trace, trace)` fire-and-forget
- Read path: `store.traces_since(project_root, since_ts) -> list[TraceRow]` для aggregator
- Per-project filter: match `project_root` field

**D4.2 — `scan_history` table — daemon scan event log**
- Sqlite db at `~/.lvdcp/scan_history.db` (separate от traces.db для independent retention)
- Schema: `scan_history(id INTEGER PRIMARY KEY, project_root TEXT, timestamp REAL, files_reparsed INTEGER, files_scanned INTEGER, duration_ms REAL, status TEXT, source TEXT)` — `source` = "daemon" | "manual"
- Retention: rolling 90 days
- Write path: hook в `apps/agent/daemon.py:process_pending_events` (after existing `update_last_scan` call); also hook в `libs/scanning/scanner.py:scan_project` for manual `ctx scan` events
- Read path: `store.events_since(project_root, since_ts) -> list[ScanEvent]`

**D4.3 — `libs/claude_usage/` — `~/.claude/projects/*.jsonl` reader + cache**
- Reader: iterate JSONL files in `~/.claude/projects/<encoded>/`, parse records, extract `usage` from `type=="assistant"` records, return `UsageEvent(timestamp, session_id, input_tokens, cache_creation_input_tokens, cache_read_input_tokens, output_tokens)` stream
- Cache db at `~/.lvdcp/claude_usage.db`
- Schema: `session_offsets(encoded_path TEXT PRIMARY KEY, last_byte_offset INTEGER, last_processed_at REAL, cached_totals_json TEXT)`
- Incremental read: на каждый dashboard load, для каждого `.jsonl` file compare `st_size` with `last_byte_offset`, read only the tail, update cache
- Aggregator: `UsageAggregator.rolling_window(project_root, window=timedelta(days=7))` → `TokenTotals`
- Path encoding: `_encode_project_path(abs_path) -> str` — replace `/` with `-`, strip leading `-` (exact algorithm reverse-engineered from observed `.claude/projects/` listings)

**D4.4 — `libs/status/aggregator.py` — shared data layer**
- Central `build_status(path: Path | None = None) -> WorkspaceStatus | ProjectStatus`
- Consumed by both FastAPI routes AND MCP resource handler — zero duplication
- Sub-functions:
  - `load_projects_from_config() -> list[ProjectEntry]`
  - `build_project_card(root) -> HealthCard` — reads `.context/cache.db` counts, config.yaml last_scan, daemon status
  - `build_project_detail(root) -> ProjectStatus` — HealthCard + sparkline data + graph
  - `build_workspace_aggregate() -> WorkspaceAggregate` — sums across all projects + global claude_usage
- Returns pydantic DTOs (models in `libs/status/models.py`)

## 4. Архитектура и data flow

```
  Browser                         FastAPI (ctx ui)             MCP Client (Claude)
     │                                    │                            │
     │  GET /                             │                            │
     ├───────────────────────────────────▶│                            │
     │                                    │                            │
     │                                    │  aggregator.build_status() │
     │                                    ├──────┬──────────────────┐  │
     │                                    │      │                  │  │
     │                                    │      ▼                  ▼  │
     │                                    │  ~/.lvdcp/       ~/.claude/│
     │                                    │  ├ config.yaml   projects/ │
     │                                    │  ├ traces.db     <enc>/    │
     │                                    │  ├ scan_history  *.jsonl   │
     │                                    │  ├ claude_usage            │
     │                                    │  └ <proj>/.context/        │
     │                                    │          cache.db          │
     │                                    │      │                     │
     │  Jinja render + HTMX partials      │◀─────┘                     │
     │◀───────────────────────────────────┤                            │
     │                                    │                            │
     │  GET /api/proj/<slug>/graph.json   │                            │
     ├───────────────────────────────────▶│                            │
     │                                    │  aggregator.build_graph()  │
     │◀───── JSON {nodes, edges} ─────────┤                            │
     │                                    │                            │
     │                                    │◀───────────────────────────┤
     │                                    │   lvdcp_status(path=None)  │
     │                                    │                            │
     │                                    │  aggregator.build_status() │
     │                                    │       (SAME CODE PATH)     │
     │                                    │                            │
     │                                    ├───────────────────────────▶│
     │                                    │   JSON snapshot            │
```

**Write side**:
```
ctx pack <query>
  └─ Pipeline.retrieve()
       └─ (existing) build RetrievalTrace
       └─ (NEW) asyncio.to_thread(trace_store.persist, trace)

ctx scan <path> | daemon flush
  └─ scan_project()
       └─ (existing) write .context/cache.db
       └─ (NEW) scan_history_store.append(event)
```

## 5. Новые файлы / модули

```
apps/
  cli/commands/
    ui.py                               # `ctx ui` Typer command
  ui/                                   # FastAPI app
    __init__.py
    main.py                             # app factory + lifespan + static mount
    routes/
      index.py                          # GET /
      project.py                        # GET /project/<slug>, POST /api/project/<slug>/scan
      api.py                            # GET /api/project/<slug>/graph.json, /api/project/<slug>/sparklines.json
    templates/
      base.html.j2
      index.html.j2                     # multi-project grid
      project.html.j2                   # detail view
      partials/
        health_card.html.j2
        sparkline_row.html.j2
        usage_widget.html.j2
        graph_panel.html.j2
    static/
      css/base.css
      js/dashboard.js                   # D3 graph + sparkline rendering
      vendor/d3.v7.min.js               # vendored offline
libs/
  status/
    __init__.py
    aggregator.py                       # build_status(path) — central
    models.py                           # pydantic DTOs
    health.py                           # per-project health card builder
    daemon_probe.py                     # launchctl-based daemon status check
  trace_store/
    __init__.py
    store.py                            # RetrievalTrace persistence
    schema.sql
  scan_history/
    __init__.py
    store.py                            # scan event log
    schema.sql
  claude_usage/
    __init__.py
    reader.py                           # JSONL scan + UsageEvent stream
    aggregator.py                       # rolling window TokenTotals
    cache.py                            # incremental offset cache
    path_encoding.py                    # project root → .claude/projects/<encoded>
libs/retrieval/
  pipeline.py                           # + async hook to trace_store.persist
apps/agent/
  daemon.py                             # + hook to scan_history.append
apps/mcp/
  tools.py                              # + lvdcp_status registration
```

## 6. Testing strategy

- **Unit**:
  - `libs/status/aggregator` — mock filesystem + fake sqlite dbs, verify `build_status(None)` vs `build_status(path)` return expected DTOs
  - `libs/trace_store` — persist + query roundtrip, retention prune, async write non-blocking
  - `libs/scan_history` — same pattern, simpler schema
  - `libs/claude_usage/reader` — fixtures with synthetic `.jsonl` files, verify rolling window aggregation
  - `libs/claude_usage/cache` — incremental offset correctness (full rebuild vs delta)
  - `libs/claude_usage/path_encoding` — round-trip `abs_path → encoded → abs_path` on 10+ real project paths
- **Integration**:
  - FastAPI app via `httpx.AsyncClient`: GET /, GET /project/<slug>, GET /api/graph.json — verify HTML rendering + JSON schema
  - `lvdcp_status` MCP resource: extend `tests/integration/test_mcp_handshake.py` to list + call `lvdcp_status` with and without path
  - End-to-end: spawn `ctx ui` as subprocess on tmp workspace, HTTP GET index, assert valid HTML + <script> tag + no 500s
- **No visual / browser tests** — Phase 3b uses manual dogfood + screenshots. Phase 5+ may introduce Playwright if complexity grows.
- **Regression**:
  - Eval harness must remain green (RetrievalTrace persistence must NOT alter retrieve() return value)
  - All 225 tests from Phase 3a + new tests green
  - Target ≥ 280 tests after 3b

## 7. Exit criteria

Phase 3b закрывается при ВСЕХ выполненных:

1. `ctx ui` поднимает сервер на `127.0.0.1:8787`, index показывает N проектов из `~/.lvdcp/config.yaml` с F1.C health cards + F1.D global usage header
2. `ctx ui <path>` открывается сразу с detail view для указанного проекта
3. Detail view рендерит F1.A D3 graph (canvas, up to 200 nodes visible), F1.B 4 sparklines (7d/30d toggle), F1.C extended health, F1.D per-project token usage
4. `lvdcp_status` MCP resource зарегистрирован, handshake test видит его в `list_tools()`, `call_tool("lvdcp_status", {})` возвращает valid DTO, `call_tool("lvdcp_status", {"path": <P>})` возвращает расширенный DTO с graph
5. `libs/trace_store/` persists RetrievalTrace на каждый `Pipeline.retrieve` call (async, non-blocking)
6. `scan_history` пишет row на каждый scan event (daemon + manual `ctx scan`)
7. `~/.lvdcp/claude_usage.db` cache работает incrementally (manually verified: первый load ~2s, subsequent loads <200ms)
8. `make lint typecheck test` зелёный, ≥ 280 tests
9. Eval harness не регрессирует (recall@5 files ≥ 0.891, precision@3 ≥ 0.620, recall@5 symbols ≥ 0.833, impact_recall@5 ≥ 0.819)
10. `pyproject.toml` version bumped `0.0.0` → `0.3.1`
11. README.md updated с Phase 3b features + `ctx ui` screenshot
12. Dogfood report `docs/dogfood/phase-3b.md` содержит screenshots of index view, detail view с graph, all 4 sparklines, health cards, usage widget на LV_DCP canary + 2 sibling projects
13. Upgrade smoke test (from `phase-3a-complete` state): `git pull` → `uv sync` → `ctx mcp doctor` shows WARN "version mismatch: 0.3.0 → 0.3.1" → `ctx mcp install` → doctor clean → `ctx ui` → все секции работают
14. Fresh-install smoke test: clean clone → `uv sync` → `ctx mcp install` → `ctx ui` → все секции работают
15. Git tag `phase-3b-complete` на HEAD main

## 8. Non-goals (Phase 3b НЕ делает)

- Settings UI (add/remove projects через UI) — остаётся `ctx watch add/remove` CLI
- Multi-user / auth / network exposure — strict localhost
- Charts beyond F1.B sparklines (Sankey / heatmaps / histograms) — Phase 5+
- iOS / mobile layout — desktop only
- Dark mode — nice-to-have, если влезет в budget, но не обязательно в exit criteria
- Claude Code limit percentage display — limits opaque, не обещаем
- Alerts / notifications — Phase 5+
- Query history search / filter in UI — просто sparkline counts
- Background trace ingestion from historical `.jsonl` sessions — трейсы пишутся только с момента deploy
- Historical scan event backfill — scan_history пишется только с момента deploy
- Auto-update checker / upstream version ping — git pull manual
- Dependency PyPI publish — LV_DCP stays source-installed via git clone + uv sync
- Real-time dashboard polling (HTMX SSE, websockets) — manual refresh

## 9. Риски

- **R1** — D3 canvas rendering для 200+ nodes может тормозить на слабых машинах. Митигация: cap force simulation steps (`alphaDecay(0.02)`), disable tick rendering when velocity < threshold, "+N hidden" fallback для >200 nodes.
- **R2** — `~/.claude/projects/*.jsonl` файлы большие (5+ MB per session), чтение на каждый dashboard load — slow. Митигация: incremental offset cache в `~/.lvdcp/claude_usage.db`, full rebuild ~2-3s, incremental ~200ms.
- **R3** — trace persistence добавляет write на каждый `ctx pack`. Митигация: async `asyncio.to_thread`, WAL mode sqlite, fire-and-forget (errors logged, не re-raise).
- **R4** — D3 learning curve + force tuning overrun. Митигация: start with minimal defaults, tune только если unusable. Cap на scope (2 days budgeted for graph, including tuning).
- **R5** — Path encoding algorithm для `.claude/projects/` — hand-reverse-engineered, может не совпасть в edge cases (paths с unicode, trailing slash). Митигация: unit tests на 10+ real paths из `~/.claude/projects/` listing, fallback — skip projects где encoding mismatch, WARN in dashboard footer.
- **R6** — Claude usage aggregation может включать unrelated (other)sessions если `.claude/projects/<encoded>/` переиспользуется. Митигация: per-session project_root verification from JSONL session header records.
- **R7** — First dashboard load after fresh upgrade — пустой F1.B (нет persisted traces ещё). Митигация: empty state messaging "no data yet, use ctx pack to populate".

## 10. Agents

| Agent | Scope |
|---|---|
| **fastapi-architect** | D1 routes + templates layout + lifespan + static mount |
| **db-expert** | D4.1 trace_store schema + D4.2 scan_history + D4.3 claude_usage cache schema |
| **system-analyst** | Impact analysis перед D4.1 hook в `Pipeline.retrieve` (hot path touch, eval regression risk) |
| **test-runner** | All new libs + FastAPI integration tests |
| **code-reviewer** | Gate между D4 infrastructure landing и D2 UI work |

## 11. Upgrade path

Phase 3b — incremental upgrade из Phase 3a. Нет breaking changes в existing data stores. Три слоя:

### 11.1 Code upgrade

```bash
cd /path/to/LV_DCP
git pull origin main
uv sync
```

Новые команды (`ctx ui`) и новый MCP resource (`lvdcp_status`) появляются автоматически. MCP re-install **не требуется** — Claude Code переспрашивает `list_tools`/`list_resources` при старте сессии, получает текущий набор.

### 11.2 State migration

- **Existing `.context/cache.db`** (per project) — untouched. Schema v3 compatible. Zero migration.
- **Existing `~/.lvdcp/config.yaml`** — поля не добавляются. Zero migration.
- **New `~/.lvdcp/traces.db`** — auto-created on first `Pipeline.retrieve` after upgrade. Initially empty, fills up as user packs. **Исторические traces теряются** — F1.B sparklines начнут показывать data через 1-2 дня normal use.
- **New `~/.lvdcp/scan_history.db`** — auto-created on first scan event after upgrade. Same semantics as traces.db.
- **New `~/.lvdcp/claude_usage.db`** — auto-created on first dashboard load. Initial full scan of `~/.claude/projects/*.jsonl` (~2-3s on 20 projects), subsequent loads incremental.

### 11.3 Discoverability

- **README.md** — updated with Phase 3b features + `ctx ui` screenshot in the commit that bumps version to 0.3.1
- **`ctx mcp doctor` check 6** — после bump version в `libs/core/version.py`, user'ы с устаревшим managed section в `~/.claude/CLAUDE.md` получат WARN "version mismatch: 0.3.0 → 0.3.1, re-run `ctx mcp install`". Self-healing.
- **NO upstream checker** — single-dev tool, no HTTP calls to GitHub API, no privacy concern

## 12. Versioning scheme

**Phase-based semver (agreed 2026-04-11)**:
- `pyproject.toml` bump `0.0.0` → `0.3.1` в первом коммите Phase 3b
- Phase 3a ретроспективно соответствует `0.3.0` (но bump происходит только в 3b, tag `phase-3a-complete` остаётся на 0.0.0 commit)
- Phase 3c → `0.3.2`
- Phase 4 → `0.4.0`
- First non-phase release (если будет) → `1.0.0`

## 13. Оценка объёма

| Component | Days |
|---|---|
| D4.1 trace_store (schema + store + hook в Pipeline + tests) | 1.0 |
| D4.2 scan_history (schema + store + hook в daemon + manual scan + tests) | 0.5 |
| D4.3 claude_usage (reader + aggregator + cache + path_encoding + tests) | 1.0 |
| D3 libs/status/aggregator + models + daemon_probe + tests | 1.0 |
| D1 FastAPI app shell + routes + Jinja templates + HTMX wiring | 1.0 |
| D2.A F1.A D3 force-directed graph + canvas rendering + controls | 2.0 |
| D2.B F1.B 4 sparklines (D3) + data wiring + tests | 0.5 |
| D2.C F1.C health cards + daemon status probe + stale detection | 0.5 |
| D2.D F1.D usage widget (header global + per-project detail) | 0.5 |
| lvdcp_status MCP resource (tools.py + handshake test) | 0.5 |
| CSS / layout polish / dark mode (if budget allows) | 0.5 |
| pyproject.toml version bump + README update + phase-3b.md dogfood writeup + screenshots | 0.5 |
| **Итого** | **9.5 дней ≈ 2 календарные недели** |

Budget немного растяжется с 1 недели (backlog estimate) до 2 из-за D3 graph rendering complexity + incremental claude_usage cache. Accepted в brainstorm.

## 14. Dependencies on Phase 3c

Phase 3b закладывает фундамент для Phase 3c:

- **trace_store + scan_history** — Phase 3c LLM enrichment / rerank нуждается в measurement infrastructure для tracking cost per query / per scan. Phase 3b persists traces, Phase 3c добавит `cost_usd` field и будет query'ить тот же store для budget monitoring.
- **aggregator pattern** — Phase 3c может расширить `lvdcp_status` / dashboard with new metrics (`llm_cost_7d`, `vector_search_hits`) без новых resource'ов — просто extend DTO.
- **claude_usage cache** — Phase 3c uses same cache для tracking fine-grained cost attribution.

Phase 3c **не заблокирован** Phase 3b технически, но начинать его раньше = строить без инструментов измерения.

## 15. Approval log

- 2026-04-11 — brainstorm session with Vladimir Lukin. Design points closed:
  - Subscription tier Max → F1.D из per-project `.claude/projects/*.jsonl`: approved
  - Routing Variant C hybrid: approved
  - D3.js graph library (over cytoscape) — future viz reuse: approved
  - `lvdcp_status` Shape 1 (single resource, optional path): approved
  - F1.B Variant C (persist RetrievalTrace + scan_history): approved
  - Upgrade path (git pull + uv sync, doctor self-heal, no auto-update): approved
  - Phase-based versioning scheme (0.3.1 for 3b): approved
  - Full design preview: approved
