# LV_DCP — Developer Context Platform

**Local-first engineering memory.** Turns projects on macOS into a queryable context layer for Claude, IDE agents, and humans. Supports Python, TypeScript/JS, Go, and Rust. Reduces token cost of repeated code reading, builds a relation graph, and makes agent edits safer.

[![Phase 9 Complete](https://img.shields.io/badge/phase-9%20complete-green)](docs/release/2026-04-24-v0.8.7-dashboard-bg-refresh.md)
[![Version 0.8.7](https://img.shields.io/badge/version-0.8.7-blue)](pyproject.toml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue)](pyproject.toml)

## What it actually does

You ask a question in plain language — _"where is refresh token logic?"_ or _"change login validation"_ — and LV_DCP returns a **2–20 KB markdown pack** with the 2–5 most relevant files and symbols. Your LLM agent reads that pack instead of grep-walking the whole repository.

For edit tasks, the pack groups files by role — **target files**, **impacted tests**, **impacted configs** — and surfaces dependencies found through the relation graph, not just keyword matching. A test file gets included even if it doesn't contain the keywords, because the graph knows it imports the file you're changing.

```bash
$ ctx pack . "refresh token rotation" --mode edit

# Context pack — edit
**Project:** my-api
**Intent:** refresh token rotation
**Coverage:** high

## Target files
- app/services/auth.py (score 12.34)
- app/handlers/auth.py (score 8.21)

## Impacted tests
- tests/test_auth.py

## Impacted configs
- config/settings.yaml

## Candidate symbols
- app.services.auth.refresh_access_token
- app.services.auth.ACCESS_TTL
- app.handlers.auth.refresh

## Reminder: edit discipline
1. Build minimal plan before patching multiple files
2. Never touch write_protected_paths
3. Run lint + typecheck + tests after every change
4. Summarize the diff when done
```

## Core value proposition

- **10× fewer tokens** when Claude/Cursor/Cline works on a large Python codebase. The agent reads a 5 KB pack instead of 50–80 KB of raw files.
- **Automatic invocation via MCP.** Once `ctx mcp install` is run, Claude Code (CLI and VS Code extension) calls LV_DCP automatically before answering architectural or edit questions — zero ceremony for the user.
- **No context slips through.** Edit-mode packs include impacted tests and configs discovered via graph walk — the kind of files `grep` misses.
- **Local-only.** No network calls, no telemetry, no SaaS. Indexes live in `.context/` next to each project. Secrets in source files are detected by regex and excluded from the search index.
- **Deterministic and measurable.** A retrieval eval harness with 32 golden queries is a first-class citizen; every retrieval change must not regress the metrics.

## Status

**v0.8.7 (2026-04-24)** — Dashboard renders `wiki_refresh` panel. The FastAPI/HTMX per-project page (`/project/<slug>`) now draws a new "Wiki background refresh" section between scan coverage and the dependency graph: blue "Running" card with phase + progress bar + current module + pid when a refresh is in flight, green "clean", gray "cancelled (SIGTERM)", or red "FAILED" card (with collapsible log tail) otherwise. Hidden for projects that have never run a refresh. Closes the #1 known gap from v0.8.6: data model was ready, just needed rendering. No route change — `ProjectStatus.wiki_refresh` from v0.8.6 was already passed to the template; v0.8.7 adds one `{% include %}` plus a partial.

**v0.8.6 (2026-04-24)** — MCP `lvdcp_status` surfaces bg refresh state. `ProjectStatus` gains `wiki_refresh: WikiBackgroundRefresh | None` — a nested block that mirrors `CopilotCheckReport.wiki_refresh_*` / `wiki_last_refresh_*` (live progress + last-run outcome + crash tail). Agents calling `lvdcp_status(path=…)` now see the same bg-refresh state `ctx project check` shows on the CLI, so they can decide "refresh or pack" without shelling out. Lazy import of `libs.copilot` keeps non-wiki consumers from paying the cost. No new deps.

**v0.8.5 (2026-04-24)** — Error log tail. On a non-clean, non-SIGTERM exit the runner seeks past its startup offset in `.refresh.log` and persists the current run's last ~20 lines as `log_tail` in `.refresh.last`. `ctx project check` renders them as an indented `log tail:` block under the `FAILED exit=…` last-run hint, so diagnosing a crashed refresh no longer requires a second `cat .refresh.log` step. Suppressed on clean / SIGTERM exits and while a refresh is in progress. Closes the *"No error-tail surface"* gap from v0.8.4. No new deps.

**v0.8.4 (2026-04-24)** — `.refresh.last` outcome record. After every background wiki refresh finishes (cleanly, via SIGTERM, or crash), the runner's `finally` block writes `.context/wiki/.refresh.last` with `{completed_at, exit_code, modules_updated, elapsed_seconds}`. `ctx project check` then renders `bg_refresh=false (last: ok 12 modules 47s, 3 min ago)` — or `FAILED exit=1 … — see .refresh.log` for crashes. Closes the *"No transition-to-error surface"* gap from v0.8.3: the watcher now tells you *why* the refresh stopped, not just *that* it stopped. No new deps, no new process.

**v0.8.3 (2026-04-24)** — `ctx project check --watch`. Live-tail the background wiki refresh: re-prints the full `check` snapshot every `--interval` seconds (default 2 s) until the refresh transitions to idle, then exits. `--json` mode streams consecutive `CopilotCheckReport` objects separated by blank lines — grep- and `jq -c`-friendly. Closes the *"No live tail"* gap from v0.8.2. No new deps; generator-based polling, not threads.

**v0.8.2 (2026-04-24)** — Wiki background progress & cancellation. The `.refresh.lock` now carries `phase` + `modules_total`/`modules_done` + `current_module`; `ctx project check` renders it as `bg_refresh=true (generating 3/12 "libs/foo" pid=1234)`. New `ctx project wiki <path> --stop` sends SIGTERM, cleans up stale locks, and reports the PID. Closes both "Known gaps" called out in v0.8.1: binary-only status and no cancellation primitive. No new deps, no daemon — still a single atomic-write lock file.

**v0.8.1 (2026-04-24)** — Async wiki refresh. `ctx project refresh --wiki-background` (and `ctx project wiki --background --refresh`) detaches the wiki LLM pipeline into a subprocess so the CLI returns immediately on large projects. `ctx project check` surfaces `bg_refresh=<bool>`; the lock file is crash-safe (dead-PID and >1h age are auto-cleared). Closes the "sync wiki blocks the terminal for minutes" gap called out in the v0.8.0 release notes. No new deps.

**Phase 9 complete (2026-04-23, v0.8.0)** — Project Copilot Wrapper (spec-011): new `ctx project` command group (`check`, `refresh`, `wiki`, `ask`) that orchestrates the existing scan/pack/wiki/status primitives into single user-facing actions. Detects and explains the four canonical degraded modes — not scanned, stale index, wiki missing/stale, Qdrant off, ambiguous retrieval — so the common "is the index fresh enough for my question?" and "refresh everything and ask" flows become one command each. No new storage, queue, or LLM dependency — strictly a composition layer over the primitives from previous phases.

**Phase 8 complete (2026-04-23, v0.7.0)** — Symbol Timeline Index (spec-010): append-only event store answering "when was X implemented?", "what disappeared after release Y?", "what regressed between v1 and v2?" with indexed lookups instead of git-log walks. Four new MCP tools (`lvdcp_when`, `lvdcp_removed_since`, `lvdcp_diff`, `lvdcp_regressions`), new `ctx timeline` CLI, Claude Code hooks for auto-reconciliation after rebase/amend, release snapshots tied to git tags, context-pack enrichment with `## Timeline facts` section (≤ 3 KB, EN + RU marker detection). **SC-001** empirical: 31×–88× token-footprint savings vs `git log -p --follow`, well beyond the 15× target. **SC-003** perf-gated: scan overhead ≤ 10 %.

**Phase 7c complete (2026-04-21)** — PageRank centrality boost (Aider parity), adaptive vector/FTS fusion, disambiguation suggestions on ambiguous packs, Go `tests_for` inference, directory-aware ancestor path boost, recency-aware centrality, reusable `libs/eval` wheel package, Claude Code skill, ByteRover-style reviewable engineering memory (proposed → accepted lifecycle). Five new MCP tools (`lvdcp_neighbors`, `lvdcp_history`, `lvdcp_cross_project_patterns`, `lvdcp_memory_propose`, `lvdcp_memory_list`) + two new CLI commands (`ctx eval`, `ctx memory`).

**Phase 7b complete (2026-04-16)** — TypeScript/JS graph enrichment: `tests_for` relations, tighter path-filter rejecting unresolved module specifiers and npm subpaths. Verified on a 926-file Next.js codebase.

**Phase 7a complete (2026-04-13)** — Identifier-aware path retrieval ships path aliases into the FTS index (camelCase/snake_case tokenization), lifting precision@3 from 0.568 to 0.693. Wiki knowledge module gets a post-scan background hook. Cyrillic support in pack enrichment. Real-project eval harness added.

Stabilization 0.6.1 baseline: mandatory GitHub Actions quality gates, green `ruff` / `mypy`, runtime-hardened embeddings and Qdrant.

Release notes:
- [docs/release/2026-04-24-v0.8.7-dashboard-bg-refresh.md](docs/release/2026-04-24-v0.8.7-dashboard-bg-refresh.md) (v0.8.7 — Dashboard renders `wiki_refresh` panel)
- [docs/release/2026-04-24-v0.8.6-mcp-bg-refresh.md](docs/release/2026-04-24-v0.8.6-mcp-bg-refresh.md) (v0.8.6 — MCP `lvdcp_status` surfaces bg refresh state)
- [docs/release/2026-04-24-v0.8.5-log-tail.md](docs/release/2026-04-24-v0.8.5-log-tail.md) (v0.8.5 — Error log tail)
- [docs/release/2026-04-24-v0.8.4-last-refresh.md](docs/release/2026-04-24-v0.8.4-last-refresh.md) (v0.8.4 — `.refresh.last` outcome record)
- [docs/release/2026-04-24-v0.8.3-check-watch.md](docs/release/2026-04-24-v0.8.3-check-watch.md) (v0.8.3 — `ctx project check --watch`)
- [docs/release/2026-04-24-v0.8.2-wiki-progress-cancel.md](docs/release/2026-04-24-v0.8.2-wiki-progress-cancel.md) (v0.8.2 — Wiki Background Progress & Cancellation)
- [docs/release/2026-04-24-v0.8.1-async-wiki-refresh.md](docs/release/2026-04-24-v0.8.1-async-wiki-refresh.md) (v0.8.1 — Async Wiki Refresh)
- [docs/release/2026-04-23-v0.8.0-project-copilot-wrapper.md](docs/release/2026-04-23-v0.8.0-project-copilot-wrapper.md) (v0.8.0 — Project Copilot Wrapper)
- [docs/release/2026-04-23-v0.7.0-symbol-timeline.md](docs/release/2026-04-23-v0.7.0-symbol-timeline.md) (v0.7.0 — Symbol Timeline Index)
- [docs/release/2026-04-13-v0.6.1-stabilization.md](docs/release/2026-04-13-v0.6.1-stabilization.md) (v0.6.1 — Stabilization)

### Retrieval quality (LV_DCP synthetic, 32 queries)

| Metric | Value | Threshold | Delta from Phase 2 |
|---|---|---|---|
| recall@5 files | **0.964** | ≥ 0.92 | +0.073 |
| precision@3 files | **0.693** | ≥ 0.63 | +0.073 |
| recall@5 symbols | 0.880 | ≥ 0.80 | +0.047 |
| impact_recall@5 | **0.931** | ≥ 0.85 | +0.112 |

### Multi-project retrieval (9 advisory queries, 4 projects)

| Metric | Value |
|---|---|
| Global recall@5 | **0.500** |
| Large project (1200+ files) | 0.200 |
| Medium projects (100-500 files) | 0.750–1.000 |

> Multi-project retrieval on large projects needs further tuning in Phase 7.

### Roadmap

| Phase | Version | Status | Key deliverables |
|---|---|---|---|
| 0-1 | 0.1.x | Done | Foundation, deterministic retrieval, eval harness |
| 2 | 0.2.x | Done | MCP server, graph expansion, symbol index |
| 3a | 0.3.0 | Done | CLI cleanup, launchd service, install story |
| 3b | 0.3.1 | Done | Dashboard UI (D3 graph, sparklines, health cards) |
| 3c.1 | 0.3.3 | Done | LLM summaries, cost tracking, settings UI |
| 3c.2 | 0.3.4 | Done | Role-weighted fusion, config boost, graph depth tuning |
| 4 | 0.4.0 | Done | pymorphy3 stemmer, git intelligence, impact analysis, hotspots, adaptive graph clustering, UI project management, diff-aware edit packs |
| 5 | 0.5.0 | Done | Hook enforcement, dual-language retrieval, 5 new relation types (tests_for, inherits, specifies), value metrics dashboard, scan coverage, 457 tests passing |
| 6 | **0.6.0** | **Done** | Phase 6 feature release: cross-language parsers (TS/JS/Go/Rust), Qdrant vector store, Obsidian vault sync, VS Code extension MVP, cross-project patterns, wiki knowledge module |
| 6.1 | **0.6.1** | **Done** | Stabilization pass: mandatory CI quality gates, green `ruff` + `mypy`, async/Qdrant runtime hardening, 662 tests passing |
| 7a | — | **Done** | Identifier-aware path retrieval, wiki post-scan hook, real-project eval harness, precision@3 0.568→0.693 |
| 7b | — | **Done** | TS/JS `tests_for` + `inherits` relations, DDD/FSD alias resolution, path-filter tightening (reject `./`, `../`, `@/`, npm subpaths). Verified on three real projects: Next.js app (82 tests_for, 29 inherits), large TS monorepo (440 tests_for, 26 inherits), DDD frontend (131 tests_for) |
| 7c | — | **Done** | PageRank centrality boost (Aider parity), adaptive vector/FTS fusion weight, Go `tests_for` inference, `lvdcp_neighbors` graph follow-up tool, disambiguation suggestions on ambiguous packs, directory-aware ancestor path boost, `lvdcp_history` git-history MCP tool, recency-aware centrality, `ctx eval` CLI + reusable `libs/eval`, Claude Code skill. Round-4: `lvdcp_memory_propose` + `lvdcp_memory_list` MCP tools, `ctx memory` CLI, ByteRover-style reviewable engineering memory |
| 8 | **0.7.0** | **Done** | **Symbol Timeline Index (spec-010)**: append-only event store, 4 new MCP tools (`lvdcp_when` / `lvdcp_removed_since` / `lvdcp_diff` / `lvdcp_regressions`), `ctx timeline` CLI, Claude Code hooks, release snapshots, pack enrichment (3 KB `## Timeline facts` section), Prometheus metrics, doctor check. SC-001 empirical 31×–88× savings vs git-log walk. SC-003 scan overhead ≤ 10 %. 1049 tests |

### Test suite

1050 tests passing, 0 failures. Eval harness: 32 synthetic queries; multi-project eval currently covers 9 advisory queries across 4 registered projects.

For advisory real-project eval setup and report commands, see [docs/eval/real-project-eval.md](docs/eval/real-project-eval.md).

## Dashboard

Local project status dashboard:

```bash
uv run ctx ui                      # multi-project overview at http://127.0.0.1:8787
uv run ctx ui /path/to/project     # open a specific project detail view
```

Features:
- **Value metrics**: packs served, compression ratio, coverage quality
- **Multi-project grid** with add/remove buttons, file/symbol/relation counts
- **Adaptive dependency graph**: module clustering (click to expand), zoom+pan, hover tooltips
- **Hotspots table**: top-10 riskiest files (fan_in x churn x test coverage)
- **Scan coverage**: per-project symbol coverage %, language/relation breakdown
- **Sparklines**: queries/day, scans/day, pack latency p95, coverage (rolling 7 days)
- **Claude Code token usage** totals (rolling 7d + 30d)

The same data is available programmatically via the new `lvdcp_status` MCP resource:

```python
# From Claude Code:
lvdcp_status()                  # workspace summary across all registered projects
lvdcp_status(path="/abs/p")     # single project detail including dependency graph
```

Upgrading: `git pull && uv sync --extra dev && uv run ctx mcp install`.

## Phase 3c.1 — LLM Summaries (new in 0.3.2)

Pluggable LLM provider with file-level summaries:

```bash
# Configure provider (default: OpenAI)
export OPENAI_API_KEY=sk-...                  # or ANTHROPIC_API_KEY, etc.
uv run ctx ui                                  # open http://127.0.0.1:8787/settings
# toggle "Enable LLM summaries", save

# Generate summaries for a project
uv run ctx summarize /path/to/project
```

Summaries are cached in `~/.lvdcp/summaries.db` keyed on file content hash + prompt version + model name, so re-running on unchanged files has zero cost.

Supported providers out of the box:
- **OpenAI** (default): `gpt-4o-mini`, `gpt-5-mini`, `gpt-5`
- **Anthropic**: `claude-haiku-4-5`, `claude-sonnet-4-6`
- **Ollama** (local, zero-cost): `qwen2.5-coder:7b`, `qwen2.5-coder:32b`, `llama3.3:70b`

### Rate limits on OpenAI tier-1

OpenAI tier-1 accounts have a 200K TPM (tokens per minute) limit. Cold-scanning a
large project with the default concurrency (4) stays under this limit for most
projects. If you hit HTTP 429 errors, re-run `ctx summarize` — already-completed
files will be cached and only the failed ones will retry. Tier-2+ users can use
`--concurrency 10` for faster cold scans.

The `openai_client` adapter honors `Retry-After` headers automatically and retries
up to 3 times per file before giving up.

### Cost tracking

Dashboard topbar shows `$X.XX / $25 monthly` budget usage. `ctx mcp doctor` now runs 9 checks (was 7) — the new check 8 verifies provider connectivity, check 9 warns at 80% and fails at 100% of monthly budget.

### Settings UI

`/settings` page lets you switch provider, model, and budget without editing config files. API keys are stored as environment variables only — the UI displays the env var *name* and its set/unset status, never the key value itself.

See [docs/adr/006-llm-provider-abstraction.md](docs/adr/006-llm-provider-abstraction.md) for the pluggable design rationale.

Upgrading: `git pull && uv sync --extra dev && uv run ctx mcp install`.

## Prerequisites

- macOS (primary target) or Linux
- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (CLI and/or VS Code extension) — optional but the main use case

## Installation

### One-time setup

```bash
git clone https://github.com/lukinvit/LV_DCP.git
cd LV_DCP
uv sync --all-extras
make lint typecheck test  # verify toolchain
```

### Global `ctx` CLI (optional)

To run `ctx` from any directory without `uv run`:

```bash
mkdir -p ~/bin
ln -sf "$(pwd)/.venv/bin/ctx" ~/bin/ctx
# ensure ~/bin is on PATH (add to ~/.zshrc or ~/.bashrc if missing):
#   export PATH="$HOME/bin:$PATH"
```

Then from any project directory:

```bash
cd /path/to/your-project
ctx scan .                 # incremental index
ctx scan --full .          # full re-parse
ctx pack . "your question"
ctx inspect .              # index stats
ctx wiki update .          # refresh dirty wiki articles
```

Do **not** put `uv run` in front of a wrapper-installed `ctx` — the venv already
knows its interpreter, and `uv run` inside another project's directory will try
to resolve a non-existent local environment and recurse.

### Project onboarding

```bash
# One guided command for a new project
uv run ctx setup /absolute/path/to/your/project --open-ui
```

`ctx setup` reuses the existing install/scan/wiki/watch/UI primitives and ends
with a readiness summary:

- `base mode` = local scan/index/packs/UI baseline
- `full mode` = hybrid/vector retrieval quality

For `full mode`, LV_DCP requires:

- `Qdrant`
- a real embedding provider/API key (for example `OPENAI_API_KEY`)

For wiki generation, LV_DCP also requires:

- `claude` CLI on `PATH`

### Register with Claude Code (recommended)

```bash
# Register the MCP server so Claude Code calls it automatically
claude mcp add --scope user lvdcp -- \
  uv run --directory /absolute/path/to/LV_DCP python -m apps.mcp.server

# Verify
claude mcp list
# Should show: lvdcp: ... - ✓ Connected
```

Replace `/absolute/path/to/LV_DCP` with your actual clone path.

After this, restart your Claude Code session (or VS Code if using the extension). Claude will now see `lvdcp_pack`, `lvdcp_scan`, `lvdcp_inspect`, `lvdcp_explain`, `lvdcp_neighbors`, `lvdcp_history`, `lvdcp_cross_project_patterns`, `lvdcp_memory_propose`, `lvdcp_memory_list` as available tools and will call them automatically per the behavioral rules in `~/.claude/CLAUDE.md`.

## Usage

### Basic workflow

```bash
# Index a project (first time)
cd ~/dev/my-python-project
uv run --directory /path/to/LV_DCP ctx scan .

# Ask questions — get ranked file/symbol packs
uv run --directory /path/to/LV_DCP ctx pack . "authentication middleware"
uv run --directory /path/to/LV_DCP ctx pack . "add rate limit to login" --mode edit

# Inspect the index
uv run --directory /path/to/LV_DCP ctx inspect .
```

### Commands

| Command | Purpose |
|---|---|
| `ctx scan <path>` | Walk, parse, index. Incremental by default (skips unchanged files by content hash). Use `--full` to force reparse. |
| `ctx setup <path>` | One-command onboarding: scan, MCP/hooks best-effort install, wiki enablement/build attempt, readiness summary, optional UI launch. |
| `ctx pack <path> "<query>" [--mode navigate\|edit]` | Build a retrieval pack. Navigate mode for questions, edit mode for changes. |
| `ctx inspect <path>` | Print index statistics (file count, symbols, relations by type). |
| `ctx mcp serve` | Run the MCP server via stdio (called by Claude Code, not humans). |
| `ctx mcp install --scope {user\|project\|local}` | Patch `~/.claude/CLAUDE.md` with a behavioral rule (⚠ currently writes to wrong file — see Phase 3 backlog M8). Use `claude mcp add` directly for now. |
| `ctx watch add/remove/list/start` | Manage the auto-indexing daemon (watchdog + FSEvents, incremental scan on file change). |
| `ctx eval <path> [--queries <file>]` | Run the retrieval eval harness against a project and print recall/precision/MRR metrics. |
| `ctx memory list <path> [--status proposed\|accepted\|rejected]` | List reviewable engineering memories for a project. |
| `ctx memory propose <path> --topic <topic> --body <body>` | Persist a non-obvious project fact for human review. |

### What gets indexed

Supported languages:
- **Python** — via stdlib `ast`, extracts classes, functions, methods, constants, imports, same-file calls
- **TypeScript / JavaScript** — via tree-sitter, extracts classes, functions, interfaces, enums, imports, constants
- **Go** — via tree-sitter, extracts functions, methods, types, imports
- **Rust** — via tree-sitter, extracts functions, structs, traits, enums, use declarations
- **Markdown** — heading extraction as navigation anchors
- **YAML / JSON / TOML** — syntax validation, config role detection

Automatic ignore list: `.git/`, `.venv/`, `node_modules/`, `__pycache__/`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`, `dist/`, `build/`, `.context/`, `secrets/`, `credentials/`, plus `.env`, `.env.local/production/staging/development`, `credentials.json`, `secrets.json`.

### Privacy model

- **All processing is local.** LV_DCP never makes network calls on its own. The only outbound data is what your LLM client (e.g. Claude Code) sends to its own API — and LV_DCP reduces that payload rather than expanding it.
- **Secret pattern detection** — 12 regex patterns for AWS keys, OpenAI/Stripe/GitHub/Slack tokens, JWTs, PEM private key headers. Files matching these are indexed by path only; their content is excluded from the full-text index and context packs.
- **Deny list** — env files and credentials files are ignored at the path level before any content is read.
- **Nothing leaves the machine.** Indexes live in `.context/` directories inside each project root. Delete the directory to remove the index.

## Architecture in one diagram

```
┌─────────────────────────────────────────────────┐
│  Claude Code (CLI or VS Code extension)         │
└─────────────────────────────────────────────────┘
                   ↕ stdio (MCP)
┌─────────────────────────────────────────────────┐
│  apps/mcp/server.py — FastMCP server            │
│  Tools: scan, pack, inspect, explain            │
└─────────────────────────────────────────────────┘
                   ↕
┌─────────────────────────────────────────────────┐
│  libs/project_index — ProjectIndex wrapper      │
│  (consolidates cache + fts + symbols + graph)   │
└─────────────────────────────────────────────────┘
                   ↕
┌─────────────────────────────────────────────────┐
│  libs/retrieval/pipeline.py — 4-stage retrieval │
│   1. Symbol match (token scoring)               │
│   2. SQLite FTS5 (full-text)                    │
│   3. Graph expansion (depth 2, decay 0.7)       │
│   4. Score decay cutoff + final rank            │
└─────────────────────────────────────────────────┘
                   ↕ per-project SQLite
┌─────────────────────────────────────────────────┐
│  .context/cache.db   (files, symbols, relations,│
│                       retrieval_traces)         │
│  .context/fts.db     (FTS5 full-text index)     │
│  .context/project.md, symbol_index.md           │
└─────────────────────────────────────────────────┘

Parallel:
┌─────────────────────────────────────────────────┐
│  apps/agent/daemon.py — watchdog + debounce     │
│  Auto-rescan on FS changes (2s debounce)        │
│  Managed by launchd on macOS (plist generator)  │
└─────────────────────────────────────────────────┘
```

## Documentation

**Start here:**
- [docs/user-guide.md](docs/user-guide.md) — practical guide for end users (Phase 1 framing, to be updated for Phase 2)
- [docs/constitution.md](docs/constitution.md) — 12 immutable project invariants
- [docs/tz.md](docs/tz.md) — original 1842-line technical specification (reference, not contract)

**Architecture decisions:**
- [docs/adr/001-budgets.md](docs/adr/001-budgets.md) — cost/latency/resource budgets as hard contracts
- [docs/adr/002-eval-harness.md](docs/adr/002-eval-harness.md) — retrieval quality as CI-gated metric
- [docs/adr/003-single-writer-model.md](docs/adr/003-single-writer-model.md) — agent vs backend ownership protocol
- [docs/adr/004-phase-2-pivot.md](docs/adr/004-phase-2-pivot.md) — pivot from LLM-first to native-integration-first
- [docs/adr/005-completeness-invariant.md](docs/adr/005-completeness-invariant.md) — graph expansion as first-class invariant

**Plans and specs:**
- [docs/superpowers/specs/2026-04-11-phase-2-design.md](docs/superpowers/specs/2026-04-11-phase-2-design.md) — Phase 2 design doc
- [docs/superpowers/plans/2026-04-11-phase-2.md](docs/superpowers/plans/2026-04-11-phase-2.md) — Phase 2 implementation plan (14 tasks)
- [docs/dogfood/phase-2.md](docs/dogfood/phase-2.md) — Phase 2 dogfood report with real numbers

## Development

```bash
make install       # uv sync --all-extras
make lint          # ruff check + ruff format --check
make typecheck     # mypy strict
make test          # pytest, excluding eval and llm markers
make eval          # retrieval evaluation harness
```

Current: 798 tests (798 collected, 1 deselected), eval harness with 32 synthetic queries, plus 9 advisory multi-project queries. Phase 6 feature baseline tagged `phase-6-complete`.

### Running the daemon

```bash
# Register a project
uv run ctx watch add /absolute/path/to/your/project

# Start the daemon in foreground (for debugging)
uv run ctx watch start
```

The daemon uses `watchdog.observers.Observer` which auto-selects `FSEventsObserver` on macOS and `InotifyObserver` on Linux. Debounce window is 2 seconds; mass changes trigger a batched incremental scan rather than N individual ones.

## Roadmap

- **Phase 3** (done, v0.3.0–0.3.4) — LLM summaries with content-hash cache, dashboard UI (D3 graph, sparklines, health cards), cost tracking, settings UI, role-weighted retrieval fusion, config boost, graph depth tuning.
- **Phase 4** (done, v0.4.0) — pymorphy3 Russian stemmer, git intelligence (churn/blame), static impact analysis + hotspot widget, adaptive graph clustering, UI project management, diff-aware edit packs.
- **Phase 5** (done, v0.5.0) — Hook enforcement (PreToolUse/PostToolUse), dual-language retrieval (80+ ru↔en terms), 5 new relation types (tests_for, inherits, specifies), value metrics dashboard, scan coverage widget, 457 tests (0 failures).
- **Phase 6** (done, v0.6.0) — Cross-language parsers (TypeScript/JS, Go, Rust via tree-sitter), Qdrant vector store with hybrid retrieval (RRF fusion), Obsidian vault sync, VS Code extension MVP, cross-project pattern detection, wiki knowledge module (LLM-synthesized articles, lint, architecture page).
- **Stabilization 0.6.1** (done) — GitHub Actions quality gates, repository-wide green `ruff` / `mypy`, warning-free embeddings and Qdrant runtime, 684 tests at release.
- **Phase 7a** (done) — Identifier-aware path retrieval (path aliases in FTS index, camelCase/snake_case tokenization), wiki post-scan hook with ThreadPoolExecutor, Cyrillic tokenization in pack enrichment, real-project eval harness, precision@3 improved 0.568→0.693.
- **Phase 7b** (done) — TypeScript/JavaScript graph enrichment: `tests_for` and `inherits` relations ported from Python parser. TS module resolution supports `./`, `../`, `@/` alias, FSD-style `@shared/` / `@entities/` / `@widgets/` / `@features/` / `@app/` / `@pages/` / `@processes/` aliases, rooted paths, and DDD-style roots (`domains`, `services`, `backend`, `frontend`). Test-path heuristic extended for `.test.ts` / `.spec.tsx` / `__tests__/` conventions. Graph-expansion filter tightened to reject unresolved import specifiers and npm package subpaths (`./flow-engine`, `@/lib/foo`, `next-auth/jwt`, `@playwright/test`). Verified on three real projects: Next.js app (82 tests_for, 29 inherits), large TS monorepo (440 tests_for, 26 inherits), DDD frontend (131 tests_for via DDD heuristic).
- **Phase 7c** (done) — PageRank centrality boost, adaptive vector/FTS fusion, `lvdcp_neighbors` tool for agentic graph follow-ups, disambiguation suggestions on ambiguous packs, Go `tests_for` inference, directory-aware ancestor path boost, `lvdcp_history` git-history MCP tool, recency-aware centrality, `ctx eval` CLI + reusable `libs/eval` wheel package, Claude Code skill. Round-4: `lvdcp_memory_propose` + `lvdcp_memory_list` MCP tools, `ctx memory` CLI, ByteRover-style reviewable engineering memory (proposed → accepted lifecycle).
- **Phase 8** (done, v0.7.0) — Symbol Timeline Index (spec-010): append-only event store, 4 new MCP tools (`lvdcp_when` / `lvdcp_removed_since` / `lvdcp_diff` / `lvdcp_regressions`), `ctx timeline` CLI, Claude Code hooks, release snapshots, pack enrichment, Prometheus metrics, doctor check. SC-001: 31×–88× token savings vs git-log walk.
- **Phase 9** (done, v0.8.0) — Project Copilot Wrapper (spec-011): new `ctx project` CLI group (`check` / `refresh` / `wiki` / `ask`) that orchestrates existing primitives. Composition layer only — no new storage — so the user has a human-friendly surface above the low-level `lvdcp_*` tools.
- **v0.8.1** (done) — Async wiki refresh: `--wiki-background` detaches the wiki LLM pipeline into a subprocess so `ctx project refresh` returns immediately on large projects. Crash-safe lock file, `check` surfaces `bg_refresh=<bool>`. No new deps.
- **v0.8.2** (done) — Wiki background progress + cancellation. Lock payload carries `phase` / `modules_total`/`_done` / `current_module`; `ctx project check` renders `bg_refresh=true (generating 3/12 "libs/foo" pid=1234)`. New `--stop` flag sends SIGTERM and cleans up stale locks. Closes both known gaps from v0.8.1. No new deps.
- **v0.8.3** (done) — `ctx project check --watch`: generator-based live-tail that polls the lock and re-prints the snapshot until the refresh settles. `--json` mode streams consecutive reports separated by blank lines. Closes the "no live tail" gap from v0.8.2. No threads, no new deps.
- **v0.8.4** (done) — `.refresh.last` outcome record: the runner writes `{completed_at, exit_code, modules_updated, elapsed_seconds}` in its `finally` block (clean / SIGTERM / crash all covered), and `ctx project check` renders `bg_refresh=false (last: ok 12 modules 47s, 3 min ago)` or `FAILED exit=1 … — see .refresh.log`. Closes the "no transition-to-error surface" gap from v0.8.3. No new deps, no new process.
- **v0.8.5** (done) — Error log tail: on a non-clean, non-SIGTERM exit the runner captures the current run's last ~20 lines of `.refresh.log` into `.refresh.last.log_tail`, and `ctx project check` renders them as an indented block under the `FAILED exit=…` last-run hint — so diagnosing a crashed refresh no longer needs a second `cat .refresh.log`. Closes the "no error-tail surface" gap from v0.8.4. No new deps.
- **v0.8.6** (done) — MCP `lvdcp_status` surfaces bg refresh state. `ProjectStatus.wiki_refresh` (nested) mirrors the `CopilotCheckReport.wiki_refresh_*` / `wiki_last_refresh_*` fields so agents and dashboards see the same bg-refresh snapshot the CLI shows (live progress, last-run outcome, crash tail). Lazy import of `libs.copilot` keeps non-wiki consumers cost-free. No new deps.
- **v0.8.7** (done) — Dashboard renders `wiki_refresh` panel. New partial `apps/ui/templates/partials/wiki_refresh.html.j2` draws the v0.8.6 `ProjectStatus.wiki_refresh` field in four visually distinct shapes (running / clean / SIGTERM / FAILED-with-log-tail) on `/project/<slug>`. Hidden for projects that never ran a refresh. Closes the #1 known gap from v0.8.6 (data model ready, no UI). One `{% include %}`, no route change, no new deps.
- **Phase 10** (next) — Java/Kotlin/Swift parsers, VS Code marketplace, Obsidian nightly sync.

## Contributing

This is a personal-scale project. Issues and discussion are welcome. See [CLAUDE.md](CLAUDE.md) for project conventions before sending pull requests.

## License

Apache License 2.0 — see [LICENSE](LICENSE) for the full text.

Copyright 2026 Vitaly Lukin.
