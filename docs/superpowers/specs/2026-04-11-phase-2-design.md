# Phase 2 Design — Native Integration & Retrieval Completeness

**Date:** 2026-04-11
**Status:** Accepted (brainstorm complete, ready for implementation plan)
**Supersedes:** original Phase 2 scope from `docs/superpowers/plans/2026-04-10-phase-0-1-foundation.md` §43 (LLM enrichment). That scope is deferred to Phase 3.

---

## 1. Mission

After Phase 2, Claude (or any MCP-aware LLM client) must **automatically** use LV_DCP whenever it works on a Python project that has the tool installed — without the user having to remind it, and without the user manually running `ctx scan` before each question.

The measurable one-sentence target:

> **A fresh Claude Code session in a previously-registered Python project answers an architectural question or starts an edit task by calling `lvdcp_pack` first, reads the returned 2–20 KB context pack, and proceeds — the user never types `ctx` themselves during normal work.**

And the quality invariant that distinguishes Phase 2 from Phase 1:

> **When the user says "change login validation," the pack returned by `lvdcp_pack --mode edit` includes the handler, the service function, the tests that import them, and the config files that configure them — not only files matching "login" or "validation" by keyword. Impact discovered via graph traversal, not keyword matching.**

This is the operational meaning of the user's stated goal: *"ничего из контекста не должно утекать"* — no relevant context escapes my attention.

---

## 2. What this design explicitly is NOT

Crossed-out scope from the original Phase 2. These are **Phase 3 or later**:

- ❌ LLM summarization (Claude API content-hash cache, `file_summary` / `module_summary` / `architecture_summary`)
- ❌ Vector embeddings and semantic retrieval (sqlite-vss, pgvector, reranking)
- ❌ Multi-stage retrieval with LLM-generated query expansion
- ❌ Postgres backend or any networked service
- ❌ TypeScript / Go / Rust parsers
- ❌ Cross-project pattern search
- ❌ Any feature that sends data outside the user's machine

Deferring these is a direct trade: we accept that Phase 2 will not understand queries like "доменная логика безопасности" (no keywords match the code) in exchange for shipping a **working, native, completeness-safe** tool three weeks earlier. Phase 1 retrieval already clears recall@5 ≥ 0.917 on deterministic queries; the practical gap worth closing first is not "understand natural language" but "don't miss impacted tests and configs when I explicitly name the thing."

---

## 3. Architecture overview

Three new structural components on top of Phase 1:

```
┌───────────────────────────────────────────────────────────────┐
│                    Claude Code / Cursor / Zed                 │
│                    (MCP client, stdio transport)              │
└───────────────────────────────────────────────────────────────┘
                             ↕ stdio
┌───────────────────────────────────────────────────────────────┐
│  apps/mcp/server.py         MCP server (FastMCP, stdio)       │
│   tools: lvdcp_scan, lvdcp_pack, lvdcp_inspect, lvdcp_explain │
│   resources: project overview, symbol index (optional)        │
└───────────────────────────────────────────────────────────────┘
                             ↕ shared in-process call
┌───────────────────────────────────────────────────────────────┐
│  libs/project_index/index.py     ProjectIndex wrapper         │
│   open(root) → cache + fts + symbols + graph + retrieval      │
│   one import point for CLI, MCP, daemon, eval adapter         │
└───────────────────────────────────────────────────────────────┘
                             ↕
┌───────────────────────────────────────────────────────────────┐
│  libs/retrieval/pipeline.py    RetrievalPipeline (enhanced)   │
│   Stage 1: symbol match + FTS (Phase 1)                       │
│   Stage 2: NEW — graph expansion (depth=2, decay=0.5)         │
│   Stage 3: NEW — RetrievalTrace + coverage warning            │
└───────────────────────────────────────────────────────────────┘
                             ↕
┌───────────────────────────────────────────────────────────────┐
│  apps/agent/daemon.py        launchd daemon (macOS)           │
│   watchdog + FSEventsObserver + debounce                      │
│   incremental scan on change, periodic full sweep             │
└───────────────────────────────────────────────────────────────┘
```

Three things to notice from this layout:

1. The daemon is a **separate process** from the MCP server. This is intentional. The MCP server is stateless per invocation — Claude Code spawns it for the duration of a session and kills it when the session ends. The daemon is long-running and owns file-watching concerns. They share state through the SQLite cache on disk (via `ProjectIndex`), not through IPC.

2. **`ProjectIndex` is the single entry point** for opening a project index. Phase 1 had three independent construction paths (CLI `scan`, CLI `pack`, `retrieval_adapter.py`), flagged in the final review as duplication. Phase 2 consolidates them into one wrapper. The MCP server tools, the CLI commands, the daemon, and the eval adapter all go through `ProjectIndex.open(root)`.

3. **No network, no auth, no TCP port.** MCP stdio transport is literally stdin/stdout between Claude Code and the server subprocess. The daemon is local to the user's machine, talks to nobody. The only I/O boundary is the file system inside projects the user has explicitly registered.

---

## 4. Components

### 4.1 MCP server (`apps/mcp/server.py`)

**Framework:** `mcp.server.fastmcp.FastMCP` (high-level decorator API). Rejected alternative: low-level `mcp.server.Server` — more ceremony, no benefit for our tool set.

**Transport:** stdio only. No HTTP, no SSE, no network.

**Tools exposed:**

| Tool | Input | Output | When called |
|---|---|---|---|
| `lvdcp_scan` | `path: str` | `{files: int, symbols: int, relations: int, timing_seconds: float}` | Rarely — only on demand, usually when daemon is off or user wants fresh full rescan |
| `lvdcp_pack` | `path: str, query: str, mode: Literal["navigate", "edit"] = "navigate", limit: int = 10` | `{markdown: str, trace_id: str, coverage: Literal["high", "medium", "ambiguous"], retrieved_files: list[str], retrieved_symbols: list[str]}` | **Most-called tool.** Before answering any non-trivial question about a Python project |
| `lvdcp_inspect` | `path: str` | `{project_name: str, files: int, symbols: int, relations: int, languages: dict[str, int]}` | Occasional — when Claude wants a quick sanity check of index state |
| `lvdcp_explain` | `trace_id: str` | `{stages: list[stage_result], dropped_candidates: list[candidate], final_scores: dict[str, float]}` | On demand, when a pack result looks suspicious and Claude wants to see *why* |

**Tool descriptions (critical — this is how I decide to call them):**

Each tool's docstring in FastMCP becomes its MCP manifest description. Claude sees these and decides when to call. They must be **imperative, specific, and trigger-oriented**. Example for the main tool:

```python
@mcp.tool()
def lvdcp_pack(
    path: str,
    query: str,
    mode: Literal["navigate", "edit"] = "navigate",
    limit: int = 10,
) -> PackResult:
    """Retrieve a compact markdown context pack for a natural-language question
    about a Python project.

    CALL THIS BEFORE:
    - Reading multiple files in a project to understand "how does X work"
    - Starting any edit task ("change X", "add Y to Z", "fix bug in W")
    - Answering architectural questions ("which module handles A")

    DO NOT CALL FOR:
    - Simple syntax questions unrelated to the current project
    - Questions the user already provided full context for

    Returns 2-20 KB of ranked files and symbols pulled from an index built
    by `ctx scan`. For edit tasks, use mode="edit" to get files grouped by
    role (target/tests/configs) with impacted files surfaced via graph
    expansion. Much cheaper than grep-walking the repo.
    """
```

This wording is load-bearing. The MCP runtime passes it to Claude as part of the tool's schema. Claude uses it to decide when to invoke. Phase 2 acceptance tests include a prompt-engineering eval: given a sample question, does Claude call the tool? (See §8.)

**CLI entry point:** `ctx mcp serve` runs the server via stdio. This is what the MCP client actually executes. Users do not run this manually.

**Scope discovery:** When `lvdcp_pack` receives a `path` argument, the server must verify that the path has a `.context/cache.db` — if not, it returns a structured error with `code: "not_indexed"` and a hint to call `lvdcp_scan` first. This prevents silent empty packs (the Phase 1 bug we already fixed for CLI pack).

### 4.2 `ProjectIndex` wrapper (`libs/project_index/index.py`)

A thin orchestration layer that holds references to the four per-project objects:

```python
class ProjectIndex:
    def __init__(
        self,
        root: Path,
        cache: SqliteCache,
        fts: FtsIndex,
        symbols: SymbolIndex,
        graph: Graph,
    ) -> None: ...

    @classmethod
    def open(cls, root: Path, *, create: bool = False) -> "ProjectIndex":
        """Open an existing .context/ or fail if not found (create=True to bootstrap)."""

    @classmethod
    def for_scan(cls, root: Path) -> "ProjectIndex":
        """Open or bootstrap — used by ctx scan to always work."""

    def retrieve(self, query: str, mode: str, limit: int) -> RetrievalResult: ...

    def pack(self, query: str, mode: str, limit: int) -> ContextPack: ...

    def close(self) -> None: ...

    def __enter__(self) -> "ProjectIndex": ...
    def __exit__(self, *args: object) -> None: ...
```

**Why this exists:** Phase 1 had scan.py, pack.py, and retrieval_adapter.py all independently assembling cache + fts + symbols. They drifted subtly (different error handling, different "is cache missing" checks, different FTS population points). Phase 2 has **four** consumers (CLI × 3, MCP × 4 tools, daemon, eval adapter, bench script) and cannot afford that drift.

**Responsibility split:**
- `ProjectIndex` does not own scanning logic — that lives in `libs/scanning/scanner.py` (extracted from `apps/cli/commands/scan.py` in Task 1.12)
- `ProjectIndex` owns index lifecycle: open, close, retrieve, pack, and graph loading from cache on open

**Graph loading:** On `open()`, the wrapper loads all rows from `cache.relations` into an in-memory `Graph` object. For 1500 relations this is ~1ms. For a hypothetical 100K-relation monorepo it would be ~70ms — still acceptable for a per-tool-call cost. If this ever becomes a bottleneck (Phase 5+), we switch to lazy graph loading with SQL-backed expansion.

### 4.3 Retrieval pipeline with graph expansion (`libs/retrieval/pipeline.py`)

The Phase 1 pipeline does: symbol match → FTS → merge → rank → top-N. Phase 2 adds two new stages **after** merging and **before** final ranking.

**New stage: graph expansion**

```
initial_candidates = merge(symbol_hits, fts_hits)       # Phase 1 logic
seeds = top-K files from initial_candidates (K=5)       # small seed set
expanded = seeds ∪ graph.expand(seeds, depth=2)         # forward edges
expanded ∪= graph.expand(seeds, depth=2, reverse=True)  # reverse edges
for each expanded node not in initial_candidates:
    assign decayed_score = parent_score * 0.5 ** hop_distance
    add to candidates with tag "graph_expanded"
```

**What edges count:**
- `imports`: "X imports Y" → Y is used by X → reverse walk finds X when seeded on Y
- `defines`: "file F defines symbol S" → lookups transit file↔symbol freely
- `same_file_calls`: already local, contributes less to expansion (same file already in candidates)

**Decay factor 0.5 and depth 2:** Empirically chosen. Depth 1 misses transitive test files (test imports helper imports target). Depth 3 explodes into noise (every stdlib import gets pulled in). Decay 0.5 means hop-1 nodes weigh half, hop-2 nodes weigh quarter. Final rank combines direct-match score and expansion score; most expanded-only files rank below matched files unless they have multiple expansion paths reinforcing them.

**New stage: RetrievalTrace construction**

Every call to `pipeline.retrieve()` produces a `RetrievalTrace`:

```python
@dataclass(frozen=True)
class RetrievalTrace:
    trace_id: str                           # UUID4
    query: str
    mode: str
    timestamp: datetime
    stages: list[StageResult]
    initial_candidates: list[Candidate]
    expanded_via_graph: list[Candidate]
    dropped_by_score_decay: list[Candidate]
    final_ranking: list[Candidate]
    coverage: Literal["high", "medium", "ambiguous"]
```

`coverage` is a heuristic that looks at the gap between top-3 scores and the tail:

- `high`: clear winner, top score ≥ 2× fourth-place score
- `medium`: ranked cleanly, some tail uncertainty
- `ambiguous`: flat distribution, many files with similar scores — caller should re-query or expand limit

Traces are persisted in a new SQLite table `retrieval_traces` for `lvdcp_explain` tool lookup (keyed by `trace_id`). Old traces are purged on a rolling basis (keep last 100 per project).

**Why persist traces:** If I call `lvdcp_pack` and the result looks wrong, my follow-up is `lvdcp_explain(trace_id)`. Without persistence, traces are lost between tool calls (each MCP tool call is a fresh function invocation). Persisting them in SQL is cheap and lets me debug retrieval in real time without replaying the query.

### 4.4 launchd daemon (`apps/agent/daemon.py`)

**Purpose:** watch registered project directories for file changes, run incremental re-scans on the affected files, keep `.context/` caches fresh without user intervention.

**Stack:**
- `watchdog.observers.fsevents.FSEventsObserver` on macOS (native, efficient, no polling)
- `watchdog.observers.polling.PollingObserver` fallback for non-macOS dev envs
- `watchdog.events.PatternMatchingEventHandler` with patterns `["*.py", "*.md", "*.markdown", "*.yaml", "*.yml", "*.json", "*.toml"]` and `ignore_directories=True`

**Lifecycle:**

1. At launch, daemon reads `~/.lvdcp/config.yaml` (new file, see §4.5) for the list of registered projects
2. For each project, schedules one `FSEventsObserver` watching the project root recursively
3. On event, queues `(project_root, file_path, event_type)` into a debounce buffer
4. Every 2 seconds, flushes the buffer: groups events by project, deduplicates by path, and runs `ProjectIndex.for_scan(root).scan_incremental(changed_files=deduped)`
5. Mass-change detection: if > 50 events for one project in 5s (e.g., git checkout), drop the buffer and run a full incremental sweep instead
6. On SIGTERM/SIGINT: stop all observers, flush any pending debounce, write shutdown marker to log

**Registration command:**

```bash
ctx watch add /abs/path/to/project          # adds to ~/.lvdcp/config.yaml
ctx watch remove /abs/path/to/project       # removes
ctx watch list                              # prints all registered
ctx watch status                            # reports daemon state + last scan per project
```

**Install command:**

```bash
ctx watch install     # writes ~/Library/LaunchAgents/tech.lvdcp.agent.plist + bootstraps
ctx watch uninstall   # bootout + removes plist
```

The plist points at a wrapper script (installed into `~/.lvdcp/bin/lvdcp-agent`) that activates the uv project environment and runs `python -m apps.agent.daemon`. This way the plist doesn't hardcode the LV_DCP install path — user can `git pull` or rebase without the daemon breaking.

**Graceful degradation:** if the daemon is not running, everything still works manually. `ctx scan` / MCP `lvdcp_scan` / MCP `lvdcp_pack` all function independently. The daemon is a convenience layer, not a critical path.

**Incremental scan algorithm:**

When the daemon (or `ctx scan` with no `--full` flag) processes a file:

1. Compute `content_hash` of file on disk
2. `existing = cache.get_file(rel)` — if exists and `existing.content_hash == new_hash`, skip entirely
3. Otherwise, parse the file, compute new symbols/relations, call `cache.put_file` + `replace_symbols` + `replace_relations` (these are already idempotent)
4. After the loop, compute stale paths (existing in cache, not visited) and `cache.delete_file` them — logic from C1 fix in Phase 1 cleanup

The only novelty is the hash short-circuit. Phase 1 re-parses every file every scan.

### 4.5 Configuration: `~/.lvdcp/config.yaml`

A new, small config file for daemon state. This is the first time LV_DCP writes anything outside the project's own `.context/` directory — which is why it needs its own file rather than being crammed into `.context/`.

```yaml
version: 1
projects:
  - root: /abs/path/to/project-a
    registered_at: 2026-04-11T09:30:00Z
    last_scan_at: 2026-04-11T10:15:00Z
    last_scan_status: ok
  - root: /abs/path/to/project-b
    registered_at: 2026-04-11T09:31:00Z
    last_scan_at: null
    last_scan_status: pending
```

**Why not in `.context/`:** Because `.context/` is per-project and git-ignored. The daemon needs a cross-project list of what to watch, which logically lives in the user's home directory.

**Schema evolution:** pydantic model with `version: Literal[1]`. Bumping requires a migration function and a new ADR.

**Privacy:** this file contains paths only, no file contents or code. Still, it is user-local, created with `0o600` permissions, never transmitted.

### 4.6 CLAUDE.md auto-injection

This is the most politically fraught component, because it modifies the user's global `~/.claude/CLAUDE.md`. Done carefully, it is what makes Claude *automatically* call `lvdcp_pack` without per-project prompting. Done badly, it's spam in someone's personal config file.

**Rule:** `ctx mcp-install --scope user` (default) appends a clearly-marked, idempotent section to `~/.claude/CLAUDE.md`. The section is delimited by HTML comments so it can be found and replaced/removed cleanly:

```markdown
<!-- LV_DCP-managed-section:start:v1 -->
<!-- This section is managed by `ctx mcp-install`. Edit via `ctx mcp-install --reconfigure` or remove with `ctx mcp-uninstall`. -->

## LV_DCP context discipline

When working in a Python project that has `.context/cache.db` at its root
(a project indexed by LV_DCP), your default is to call the `lvdcp_pack`
MCP tool **before** reading multiple files to understand the codebase.

- For questions of the form "how does X work", "where is Y", "what does Z do":
  call `lvdcp_pack(path=<project_root>, query=<user's question>, mode="navigate")`.
- For edit tasks ("change X", "add Y", "fix Z"):
  call `lvdcp_pack(path=<project_root>, query=<task description>, mode="edit")`.

The returned `markdown` field is 2-20 KB of ranked relevant files and
symbols pulled from a pre-built index. Reading this pack replaces a
repo-wide `grep` or reading many files blind.

If the pack's `coverage` field is `ambiguous`, either expand `limit`,
rephrase the query with more specific keywords, or ask the user to
clarify — do not proceed with a low-confidence pack on edit tasks.

If `lvdcp_pack` returns `not_indexed`, call `lvdcp_scan(path)` first.

This discipline does not apply to: trivial single-file tasks, syntax-only
questions, or projects without `.context/cache.db`.

<!-- LV_DCP-managed-section:end:v1 -->
```

**Uninstall:** `ctx mcp-uninstall` finds the managed block by sentinels and removes it. If the file no longer exists or the block is missing, it's a no-op.

**Safety rails:**
- Before writing, the installer reads the file and checks for an existing managed block with the same version. If found, it replaces; if found with older version, it replaces; if user has edited within the block, the installer aborts with an error asking the user to remove manually
- The installer creates a backup at `~/.claude/CLAUDE.md.lvdcp-backup-<timestamp>` before any modification
- If `~/.claude/CLAUDE.md` does not exist, the installer creates it with just the managed block
- `--scope project` puts the block into `./CLAUDE.md` (or `./.claude/CLAUDE.md` if that exists) instead
- `--scope local` puts it into `./.claude/settings.local.json`'s custom claudemd field — but this is advisory only and does not work reliably across clients

**Testing the behavioral rule:** We can't fully verify that "Claude actually calls the tool after installation" without a real Claude Code session. But we can test:
1. The file is modified correctly (unit test with a temp HOME)
2. The tool descriptions are loaded by FastMCP (unit test with `FastMCP.list_tools()`)
3. In a smoke test, the MCP handshake completes and the tools are enumerable
4. Manual acceptance: run `claude-code` in a scanned project, ask an architectural question, observe whether `lvdcp_pack` gets called — documented in Phase 2 dogfood report

### 4.7 Secret filter

Phase 1 ignores `.env` files and `.pem` keys by extension via default ignore rules (we already have `*.key`, `*.pem` in ignore, and `.env*` should be added). But a file called `config/production.yaml` might legitimately contain a Stripe secret or an AWS access key that someone committed by mistake. Phase 2 adds a post-scan filter:

**Scan-time filter:**
- Expand `DEFAULT_IGNORE_PATTERNS` in `libs/core/paths.py` with `.env`, `.env.*` (but not `.env.example`), `secrets/`, `*.credentials.json`
- New function `contains_secret_pattern(bytes) -> bool` in `libs/core/secrets.py` using regex for the most common forms (AWS keys `AKIA[0-9A-Z]{16}`, Stripe `sk_live_[0-9a-zA-Z]{24,}`, OpenAI `sk-[a-zA-Z0-9]{20,}`, JWT `eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.`)
- Files where `contains_secret_pattern` returns True are **still indexed metadata-wise** (path, size, language) but **content is not fed into FTS** and the file is marked `has_secrets=True` in the `File` entity

**Pack-time filter:**
- When assembling a pack that references a `has_secrets=True` file, the pack shows the path and symbol name but with a `⚠ file contains secret patterns, content excluded` annotation
- `lvdcp_explain` shows secret-exclusion events so debugging is transparent

**Why keep metadata even for secret files:** Because not indexing them at all would hide them from symbol discovery entirely. If a file defines class `StripeClient` and also happens to contain a leaked test key, I still need to know that `StripeClient` exists in `app/integrations/stripe.py` — I just won't ship the file content into any LLM-visible context.

**Test fixtures:** We add `tests/eval/fixtures/sample_repo/app/integrations/fake_stripe.py` with a plausible-looking fake key, confirm the scanner marks it `has_secrets=True`, and verify that packs don't leak its content.

---

## 5. Impact queries and eval completeness metric

### 5.1 New query class

Add 12 new queries to `tests/eval/queries.yaml` with `mode: edit` and expected lists that include files only findable via graph walk:

```yaml
- id: q21-impact-session-storage
  text: "change how session tokens are stored"
  mode: edit
  expected:
    files:
      - app/models/session.py           # direct keyword match
      - app/services/auth.py            # imports Session (keyword "auth" helps, but token is the connector)
      - app/workers/cleanup.py          # imports Session, no keyword "session" in the query alone
      - tests/test_cleanup.py           # imports cleanup module (graph-only)
    symbols:
      - app.models.session.Session
      - app.services.auth.issue_tokens
      - app.services.auth.refresh_access_token
      - app.workers.cleanup.cleanup_expired_sessions

- id: q22-impact-password-validation
  text: "tighten password hashing requirements"
  mode: edit
  expected:
    files:
      - app/services/auth.py            # hash_password is here
      - app/handlers/auth.py            # login imports authenticate
      - tests/test_auth.py              # tests hash_password
    symbols:
      - app.services.auth.hash_password
      - app.services.auth.authenticate
      - app.handlers.auth.login
```

(Ten more in the same spirit — see plan for the full list.)

**Key property:** every impact query has at least one expected file that **does not match the query by keyword**, only by graph relation. This is what makes `impact_recall@k` differentiate Phase 2 from Phase 1.

### 5.2 New metric

Add `impact_recall_at_k(retrieved, expected, k)` to `tests/eval/metrics.py`. It's literally `recall_at_k` — same math — but applied only to the `edit`-mode queries flagged as impact queries. We use a separate name because we want the phase thresholds to distinguish:

- `recall_at_5_files`: keyword-first retrieval quality, all 32 queries (20 Phase 1 + 12 impact)
- `impact_recall_at_5`: graph-aware retrieval quality, 12 impact queries only

A pipeline with graph expansion disabled would get high `recall_at_5_files` (because keyword matching still works) but low `impact_recall_at_5` (because graph-only files are missed). This is what makes the metric load-bearing.

### 5.3 New thresholds for phase 2

In `tests/eval/thresholds.yaml`:

```yaml
phases:
  "2":
    description: "Native integration + graph expansion"
    recall_at_5_files: 0.85        # must not regress, soft upper
    precision_at_3_files: 0.60     # may dip slightly due to expansion noise — acceptable
    recall_at_5_symbols: 0.80      # graph helps symbol recall too
    impact_recall_at_5: 0.75       # NEW — graph-dependent completeness
```

**Why allow precision to dip:** graph expansion introduces extra candidates. Some will be noise. We trade some top-3 precision for the impact_recall gain. This is an explicit, documented, eval-tested trade.

**Active phase switch:** `active_phase: 2` — flipped at the end of Phase 2 implementation, just like Phase 1 did.

---

## 6. File structure

```
apps/
  mcp/                     NEW
    __init__.py
    server.py              FastMCP server, tool registrations
    install.py             ctx mcp-install / mcp-uninstall logic
  agent/                   NEW
    __init__.py
    daemon.py              launchd-compatible long-running process
    config.py              ~/.lvdcp/config.yaml read/write
    plist_template.py      plist XML generator
    commands.py            ctx watch add/remove/list/status/install/uninstall
  cli/
    commands/
      scan.py              refactored to delegate to libs/scanning/scanner.py
      pack.py              refactored to delegate to ProjectIndex
      inspect.py           refactored to delegate to ProjectIndex
      mcp.py               NEW — ctx mcp serve, ctx mcp-install, ctx mcp-uninstall
      watch.py             NEW — ctx watch subcommands
libs/
  core/
    secrets.py             NEW — contains_secret_pattern + patterns list
  project_index/           NEW
    __init__.py
    index.py               ProjectIndex wrapper class
  retrieval/
    pipeline.py            ENHANCED — graph expansion stage + RetrievalTrace
    trace.py               NEW — RetrievalTrace dataclass + persistence
    coverage.py            NEW — coverage heuristic for pack results
  scanning/                NEW
    __init__.py
    scanner.py             extracted from apps/cli/commands/scan.py
                           — supports incremental and full modes
  storage/
    sqlite_cache.py        ENHANCED — schema v3 with has_secrets column,
                           retrieval_traces table, bump SCHEMA_VERSION = 3
tests/
  eval/
    queries.yaml           ENHANCED — +12 impact queries
    thresholds.yaml        ENHANCED — phase 2 thresholds
    metrics.py             ENHANCED — impact_recall_at_k function
  unit/
    mcp/                   NEW
      test_server.py       FastMCP tool listing, schema check
      test_install.py      claudemd patching round-trip
    agent/                 NEW
      test_config.py       ~/.lvdcp/config.yaml schema round-trip
      test_daemon.py       unit-level test with a fake observer
    project_index/         NEW
      test_index.py        open/close/retrieve/pack lifecycle
    retrieval/
      test_graph_expansion.py   NEW — pipeline-level test on a synthetic graph
      test_trace.py             NEW — trace persistence + lookup
      test_coverage.py          NEW — coverage heuristic edge cases
    scanning/              NEW
      test_incremental.py  hash short-circuit behavior
    core/
      test_secrets.py      NEW — secret pattern detection
  integration/
    test_mcp_handshake.py  NEW — full stdio MCP session spins up, tools listed
    test_ctx_watch.py      NEW — daemon watches a tmp project, incremental update
    test_dogfood_phase2.py NEW — dogfood on LV_DCP itself with daemon running

docs/
  adr/
    004-phase-2-pivot.md   NEW — reprioritization from LLM to native+completeness
    005-completeness-invariant.md   NEW — graph expansion is mandatory in edit mode
  dogfood/
    phase-2.md             NEW — phase 2 dogfood report

scripts/
  bench_mcp.py             NEW — measure end-to-end MCP tool call latency
```

**New external dependencies:**
- `mcp` (the Python SDK, from `modelcontextprotocol/python-sdk`, current version 1.12.x)
- `watchdog` (already in Phase 1's indirect dep list via pytest? No — check. Needs explicit add.)

---

## 7. Data model changes

### 7.1 New SQLite tables

```sql
-- added in schema v3, migration from v2
ALTER TABLE files ADD COLUMN has_secrets INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS retrieval_traces (
    trace_id    TEXT PRIMARY KEY,
    project     TEXT NOT NULL,
    query       TEXT NOT NULL,
    mode        TEXT NOT NULL,
    timestamp   REAL NOT NULL,
    coverage    TEXT NOT NULL,
    trace_json  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traces_timestamp ON retrieval_traces(timestamp);
```

- `has_secrets` on the `files` table is new. Existing rows get `0` by default.
- `retrieval_traces` is a separate table from anything Phase 1 had. Purge policy: keep last 100 per project, delete older on every new trace insert.

### 7.2 Schema migration

We already have the migration dispatcher from Task I2. Phase 2 adds a new migration step:

```python
def _migrate_v1_to_v2(conn): ...    # FK cascade (done in Phase 1 cleanup)
def _migrate_v2_to_v3(conn):        # NEW
    conn.execute("ALTER TABLE files ADD COLUMN has_secrets INTEGER NOT NULL DEFAULT 0")
    conn.executescript(RETRIEVAL_TRACES_SCHEMA)
```

`migrate()` runs steps in order based on current `PRAGMA user_version`.

### 7.3 New entity fields

`libs/core/entities.py`:

```python
class File(Immutable):
    # existing fields...
    has_secrets: bool = False   # NEW
```

**Ripple effect:** SqliteCache's `put_file` / `get_file` / `iter_files` all need to read/write the new column. The existing `File` model is frozen, so adding a field with a default is backward-compatible for construction.

### 7.4 RetrievalResult enhancement

`libs/retrieval/pipeline.py`:

```python
@dataclass(frozen=True)
class RetrievalResult:
    files: list[str]
    symbols: list[str]
    scores: dict[str, float]
    trace: RetrievalTrace          # NEW
    coverage: Literal["high", "medium", "ambiguous"]   # NEW
```

`ContextPack` (`libs/core/entities.py`) gets an analogous `trace_id` and `coverage` field. `build_navigate_pack` / `build_edit_pack` render the coverage annotation into the markdown.

---

## 8. Success metrics — when is Phase 2 "done"

All five must hold simultaneously on the final commit:

1. **All make gates green:** `make lint`, `make typecheck`, `make test`, `make eval`
2. **Eval thresholds at active_phase: 2** — recall@5 files ≥ 0.85, precision@3 files ≥ 0.60, recall@5 symbols ≥ 0.80, **impact_recall@5 ≥ 0.75**
3. **MCP handshake integration test passes:** `tests/integration/test_mcp_handshake.py` spins up the server, completes an `initialize` handshake over a pair of in-memory pipes, lists tools, calls `lvdcp_pack` on the fixture repo, validates the returned schema
4. **Daemon integration test passes:** `tests/integration/test_ctx_watch.py` starts a subprocess daemon (foreground mode), creates files, verifies incremental scan updates the cache within 5 seconds end-to-end
5. **Phase 2 dogfood report:** real `claude` session opened in LV_DCP repo itself, with MCP server installed and daemon running, documents:
   - Whether Claude spontaneously called `lvdcp_pack` for three prepared questions (architectural, navigation, edit)
   - Timing of each end-to-end call
   - Any cases where Claude should have called but didn't (blocker if > 1 of 3)
   - Any cases where pack results were misleading (blocker if impact files are missing for an edit query)

The dogfood is **not** a pass/fail binary test in CI — it's a qualitative confirmation. The user asked for a 90% confidence level on phase completion. My interpretation: 4 of 5 criteria green + dogfood shows clear "Claude uses the tool by default" signal = ship. If dogfood shows Claude ignoring the tool in >1 of 3 scenarios, we revise the CLAUDE.md instruction wording and the tool descriptions until it works.

---

## 9. What can break, and the mitigations

**Risk 1: MCP SDK API drift.** The SDK is at version 1.12 but moving fast. The `FastMCP` decorator API could change between the docs I read and the day we implement. Mitigation: pin to a specific version in pyproject.toml (`"mcp>=1.12,<2"`), add an integration test that exercises a real handshake, treat any API-level breakage as a Phase 2 blocker.

**Risk 2: watchdog FSEvents edge cases on macOS.** Known issues with FSEvents include duplicate events, missed events during mount/unmount, and delayed delivery during heavy filesystem pressure. Mitigation: debounce (already in plan), periodic full sweep every 10 minutes as safety net, `--foreground` mode with verbose logging for debugging.

**Risk 3: launchd plist fragility.** Wrong permissions, wrong paths, wrong `RunAtLoad` timing — all classic failures. Mitigation: use a wrapper script approach (plist calls a fixed path to a wrapper, wrapper handles environment setup), start with `ctx watch start --foreground` for dev iteration, only wrap in launchd once the foreground path is rock solid, tests include a dry-run of plist generation.

**Risk 4: Graph expansion over-expands.** Depth=2 with decay=0.5 might pull in too many files for large codebases. Mitigation: the eval harness is the final judge — if `precision@3_files` drops below 0.55, we either reduce depth, increase decay, or add a per-file score floor. This is the exact scenario the eval harness exists for.

**Risk 5: CLAUDE.md injection breaks user's personal config.** The managed-section pattern is intended to prevent this, but a malformed section could persist. Mitigation: always-create-backup + abort-if-inconsistent + `ctx mcp-uninstall` that works even if the file is corrupted (remove block by sentinels, fall back to "remove any lines between sentinels" search).

**Risk 6: "Claude doesn't actually use the tool" after all our work.** The one risk that invalidates the entire phase. The tool descriptions might be wrong, the CLAUDE.md instructions might be too weak, Claude might decide the user's question is "too simple" and skip the tool. Mitigation: the dogfood in §8 is the acceptance test. If it fails, we iterate on tool descriptions and CLAUDE.md wording in a tight loop until it works, **before** claiming the phase is done. Prompt engineering is part of Phase 2 scope.

**Risk 7: Secret filter regex false positives.** A legitimate UUID or base64 string gets flagged as a secret, content is excluded, retrieval degrades. Mitigation: unit tests with known false positives (UUIDs, git commit hashes, long base64-encoded constants), conservative patterns (prefix anchors like `sk_live_`, `AKIA`), `--no-secret-filter` escape hatch on `ctx scan` for debugging.

---

## 10. Non-goals and deferrals summary

| Feature | Deferred to | Why |
|---|---|---|
| LLM summaries | Phase 3 | Separate large scope, not blocking native integration |
| Vector search | Phase 3 | Same |
| Multi-language parsers | Phase 5 | Single-language focus preserves velocity |
| Cross-project search | Phase 5 | Requires global index + multi-project retrieval |
| IDE extensions (VS Code, Cursor plugin) | Phase 6+ | MCP makes these unnecessary in the near term |
| Network-based secret scanning service | Never | Violates privacy invariant |
| Cloud sync of `.context/` | Phase 4+ behind explicit opt-in | Not a goal |
| Real-time collaborative retrieval | Never | Out of scope entirely, violates single-writer constraint |

---

## 11. Estimated scope and timeline

Rough decomposition (detail in the plan document that will follow):

| Block | Tasks | Time |
|---|---|---|
| ADR + spec writing | 2 | 0.5 day |
| `ProjectIndex` refactor + scanner extract | 4 | 1.5 days |
| Incremental scan with hash short-circuit | 2 | 0.5 day |
| Graph expansion + RetrievalTrace + coverage | 6 | 3 days |
| Impact queries + new eval metric + thresholds | 4 | 1 day |
| MCP server (FastMCP) + tool definitions + ctx mcp serve | 4 | 2 days |
| `ctx mcp-install` / `ctx mcp-uninstall` + CLAUDE.md patching | 3 | 1 day |
| launchd daemon (foreground first, then plist) | 6 | 3 days |
| `ctx watch` CLI subcommands + ~/.lvdcp/config.yaml | 3 | 1 day |
| Secret filter + fixtures + pack annotation | 3 | 1 day |
| Dogfood + prompt eng iteration | 2 | 1 day |
| Phase 2 checkpoint + tag | 1 | 0.5 day |

**Total: ~16 days of implementation + ~1 day ADR/spec + ~1 day dogfood/review = ~18 working days.** Matches the ~20 day estimate from the earlier discussion, within 10% uncertainty.

Risk budget: +30% for unknowns (MCP SDK surprises, launchd issues, prompt engineering iteration). Target ship date ~25 working days from start.

---

## 12. Open questions explicitly decided by user

These are the decisions the user made during the brainstorm, captured here so they can't silently drift during implementation:

1. **MCP scope default:** `--scope user` (one install, all projects)
2. **Graph expansion params:** `depth=2, decay=0.5`, tune via eval if needed
3. **Impact queries count:** 12, mixed complexity
4. **Phase 2 threshold for impact:** `impact_recall@5 ≥ 0.75`
5. **Cross-file calls for Python:** accept `from X import Y` heuristic with `confidence=0.7`, proper static analysis deferred to Phase 4
6. **Variant choice:** C (full native + completeness + graph + eval)
7. **Autonomy:** implementation proceeds without per-task user approval — only final review and dogfood gate

Any deviation from these requires an ADR or a plan revision commit, not a silent decision.
