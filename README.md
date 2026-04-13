# LV_DCP — Developer Context Platform

**Local-first engineering memory.** Turns projects on macOS into a queryable context layer for Claude, IDE agents, and humans. Supports Python, TypeScript/JS, Go, and Rust. Reduces token cost of repeated code reading, builds a relation graph, and makes agent edits safer.

[![Phase 6 Complete](https://img.shields.io/badge/phase-6%20complete-green)](docs/superpowers/specs/2026-04-13-phase-6-design.md)
[![Version 0.6.1](https://img.shields.io/badge/version-0.6.1-blue)](pyproject.toml)
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

**Stabilization release 0.6.1 (2026-04-13)** — Phase 6 feature work is now backed by mandatory GitHub Actions quality gates, repository-wide green `ruff` / `mypy`, and warning-free runtime hardening for embeddings and Qdrant.

Phase 6 remains complete: cross-language parsers (TS/JS/Go/Rust), Qdrant vector store, Obsidian vault sync, VS Code extension MVP, cross-project patterns, wiki knowledge module.

Release note: [docs/release/2026-04-13-v0.6.1-stabilization.md](docs/release/2026-04-13-v0.6.1-stabilization.md)

### Retrieval quality (LV_DCP synthetic, 32 queries)

| Metric | Value | Threshold | Delta from Phase 2 |
|---|---|---|---|
| recall@5 files | **0.964** | ≥ 0.92 | +0.073 |
| precision@3 files | **0.682** | ≥ 0.63 | +0.062 |
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
| 6.1 | **0.6.1** | **Done** | Stabilization pass: mandatory CI quality gates, green `ruff` + `mypy`, async/Qdrant runtime hardening, 653 CI-gated tests passing |

### Test suite

653 CI-gated tests, 0 failures. Current green baseline: 651 non-eval + 2 eval. Eval harness: 32 synthetic queries; multi-project eval currently covers 9 advisory queries across 4 registered projects.

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

After this, restart your Claude Code session (or VS Code if using the extension). Claude will now see `lvdcp_pack`, `lvdcp_scan`, `lvdcp_inspect`, `lvdcp_explain` as available tools and will call them automatically per the behavioral rules in `~/.claude/CLAUDE.md`.

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
| `ctx pack <path> "<query>" [--mode navigate\|edit]` | Build a retrieval pack. Navigate mode for questions, edit mode for changes. |
| `ctx inspect <path>` | Print index statistics (file count, symbols, relations by type). |
| `ctx mcp serve` | Run the MCP server via stdio (called by Claude Code, not humans). |
| `ctx mcp install --scope {user\|project\|local}` | Patch `~/.claude/CLAUDE.md` with a behavioral rule (⚠ currently writes to wrong file — see Phase 3 backlog M8). Use `claude mcp add` directly for now. |
| `ctx watch add/remove/list/start` | Manage the auto-indexing daemon (watchdog + FSEvents, incremental scan on file change). |

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

Stabilization 0.6.1: 653 CI-gated tests passing (651 non-eval + 2 eval), eval harness with 32 synthetic queries, plus 9 advisory multi-project queries. Phase 6 feature baseline remains tagged `phase-6-complete`.

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
- **Stabilization 0.6.1** (done) — GitHub Actions quality gates, repository-wide green `ruff` / `mypy`, warning-free embeddings and Qdrant runtime, 653 CI-gated tests.
- **Phase 7** (next) — Java/Kotlin/Swift parsers, Obsidian debounced/nightly sync, VS Code marketplace, LLM-based rerank, vector retrieval eval tuning.

## Contributing

This is a personal-scale project. Issues and discussion are welcome. See [CLAUDE.md](CLAUDE.md) for project conventions before sending pull requests.

## License

Apache License 2.0 — see [LICENSE](LICENSE) for the full text.

Copyright 2026 Vitaly Lukin.
