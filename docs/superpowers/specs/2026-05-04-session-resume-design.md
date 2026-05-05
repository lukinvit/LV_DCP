# Session Resume — Phase 7 Slice

**Status:** Designed 2026-05-04, awaiting implementation plan
**Owner:** Vladimir Lukin
**Follows:** Phase 6 (Qdrant + Obsidian + cross-language parsers, v0.6.x)
**Version target:** 0.7.0 (initial); recall threshold tightened in 0.7.x patches
**Brainstorm session:** 2026-05-04 (CLAUDE worktree adoring-darwin-e6d9c4)

---

## 1. Goal

Provide continuity of engineering context across Claude Code sessions, so a
new session — same account or another account on the same machine — can
resume work without the user having to re-explain what was happening.

**Litmus test:** Author runs `lvdcp_pack` and edits files for 30 minutes in
project X under CC session A. Session A dies (rate limit, crash, restart,
account switch). Author starts CC session B in any account, runs
`lvdcp_resume`, and within 30 seconds knows: which branch and dirty files,
which plan was active, which queries had just been asked, which files were
hot, which test was failing.

This is **A2 with γ-writer + α-hook** from the brainstorm. **A3 (CC
transcript reconstruction) is explicitly deferred**.

---

## 2. Problem

LV_DCP today indexes code state but does not track *engineering activity
state*. When a CC session ends:

- A new session has no idea what the previous one was doing
- The user re-explains context manually (slow, error-prone)
- TodoWrite lists, recent queries, recent file foci are lost
- Multi-project users with several active threads have no quick "what was I
  doing on each" overview

The original user request also asked for cross-account "session swap" via
direct manipulation of CC private session files. That is rejected as
out-of-scope: it violates LV_DCP constitution invariant #6 (single-writer)
and invariant from `project_out_of_scope.md` ("Reinventing Claude Code
infrastructure"), and is a likely Anthropic ToS violation.

The right primitive is **context handoff via LV_DCP's own data store**,
which is exactly LV_DCP's mandate as the engineering memory layer.

---

## 3. Scope

### 3.1 In scope (Phase 7 slice)

- New `libs/breadcrumbs/` lib (single-writer, agent-owned, mirrors
  `libs/scan_history` pattern: SQLite at `~/.lvdcp/breadcrumbs.db`,
  schema via `_SCHEMA` constant + `migrate()` method, no Alembic)
- Side-effect breadcrumb writes from `lvdcp_pack` and `lvdcp_status`
- Opt-in CC hooks (`SessionStart`, `Stop`, `PreCompact`, `SubagentStop`)
- New MCP tool `lvdcp_resume(path?, scope?, limit?, format?)`
- New CLI commands: `ctx resume`, `ctx breadcrumb {capture,list,prune,purge}`
- `ctx mcp install --hooks=resume[:no-inject][:no-schedule]` extension
- A1 snapshot generator (git state + scan + plan + eval, fresh per call)
- Multi-user safety (`os_user`, `cc_account_email` scoping)
- Secret redaction at write time (pattern-based)
- 14-day TTL with bundled launchd-scheduled prune
- 11 eval scenarios + baseline metrics + CI gate
- `recover-cc-session` standalone utility — built alongside but **not
  included in LV_DCP package**; lives in `~/bin/`, see §10

### 3.2 Out of scope (deferred or rejected)

- **A3 — CC transcript JSONL parsing** for richer reconstruction. Couples
  LV_DCP to undocumented format. Reconsider in Phase 8+ as opt-in
  `--enrich-from-transcript` flag if Phase 7 proves insufficient.
- **Cross-machine sync** of breadcrumbs. Schema field `privacy_mode` is
  written correctly for future enablement, but no sync pipeline in this
  slice.
- **Encrypted at rest** for breadcrumbs. Plaintext in SQLite/Postgres,
  protected only by filesystem permissions. Reconsider if pattern-redactor
  proves insufficient.
- **Cross-account session pooling.** Hard rejected — see §2.
- **LLM-driven focus inference / rerank.** Phase 7 resume is purely
  deterministic, no LLM calls, $0 cost per resume.
- **Multi-tenant / team mode.** Out of LV_DCP scope per constitution.
- **TUI / Textual interactive picker.** Overkill for current usage
  patterns.

---

## 4. Architecture overview

```
                 CC session                            CC session
                    (A)                                   (B)
                     │                                     │
                     │ MCP                                 │ MCP / Hook
                     ▼                                     ▼
          ┌────────────────────┐                ┌────────────────────┐
          │  lvdcp_pack        │                │  lvdcp_resume      │
          │  lvdcp_status      │                │  ctx resume        │
          │  ctx breadcrumb    │                │  SessionStart hook │
          │     capture (hooks)│                │                    │
          └─────────┬──────────┘                └─────────┬──────────┘
                    │ writes                              │ reads
                    ▼                                     │
          ┌────────────────────────────────────────────┐  │
          │       libs/breadcrumbs (single writer)     │◄─┘
          │   ┌────────────┬────────────┬────────────┐ │
          │   │  writer    │  reader    │  privacy   │ │
          │   ├────────────┼────────────┼────────────┤ │
          │   │  prune     │  snapshot  │  cc_id     │ │
          │   │            │  (A1 gen)  │  (read-only│ │
          │   │            │            │   parser)  │ │
          │   └────────────┴────────────┴────────────┘ │
          └─────────┬───────────────────────┬──────────┘
                    │                       │
                    ▼                       ▼
            local cache.db          Postgres backend
            (SQLite, agent)         (full_sync only;
                                     not synced this slice)
```

Two writers (CC sessions A and B) share one breadcrumb store. The store is
LV_DCP-owned, never CC-owned. CC session files (`~/Library/Application
Support/Claude/...`) are touched **read-only** in exactly one place
(extracting `cc_account_email`).

---

## 5. Section 1 — Data model

### 5.1 New lib `libs/breadcrumbs/`

```
libs/breadcrumbs/
  __init__.py
  store.py         # SQLite store: connection + _SCHEMA + migrate()
                   #               (mirrors libs/scan_history/store.py)
  models.py        # frozen dataclasses: Breadcrumb, BreadcrumbView
  writer.py        # write_pack_event / write_status_event /
                   #       write_hook_event (sync — wrapped fire-and-forget
                   #       at call site via asyncio.create_task)
  reader.py        # load_recent / load_session_grouped /
                   #       load_cross_project
  snapshot.py      # A1Snapshot generator + LRU caches (no persistence)
  prune.py         # TTL + LRU sweeper
  privacy.py       # local_only / full_sync filter, secret redactor
  cc_identity.py   # read-only parser for CC account email
  views.py         # ProjectResumePack, ProjectDigestEntry, FocusGuess
  renderer.py      # markdown renderer (full + inject modes)
```

Dependency rule: `libs/breadcrumbs` imports only stdlib. Other libs (e.g.
`libs/retrieval/pack`) may import `libs/breadcrumbs.writer`. No reverse
imports.

### 5.2 Schema — `breadcrumbs` table (SQLite at `~/.lvdcp/breadcrumbs.db`)

```sql
CREATE TABLE IF NOT EXISTS breadcrumbs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_root      TEXT    NOT NULL,
    timestamp         REAL    NOT NULL,
    source            TEXT    NOT NULL,
    cc_session_id     TEXT,
    os_user           TEXT    NOT NULL,
    cc_account_email  TEXT,
    query             TEXT,
    mode              TEXT,
    paths_touched     TEXT,             -- JSON-encoded list[str], top-5
    todo_snapshot     TEXT,             -- JSON-encoded list[dict]
    turn_summary      TEXT,
    privacy_mode      TEXT    NOT NULL DEFAULT 'local_only'
);
CREATE INDEX IF NOT EXISTS ix_breadcrumbs_root_ts
    ON breadcrumbs (project_root, timestamp);
CREATE INDEX IF NOT EXISTS ix_breadcrumbs_user_root_ts
    ON breadcrumbs (os_user, project_root, timestamp);
CREATE INDEX IF NOT EXISTS ix_breadcrumbs_session
    ON breadcrumbs (cc_session_id);
```

`source` is a TEXT column constrained at the writer level to:
`pack | status | hook_stop | hook_pre_compact | hook_subagent_stop | manual`.
`privacy_mode` is `local_only | full_sync` — `full_sync` is reserved for
Phase 8+; the column exists for forward compatibility but no sync
pipeline reads it in this slice.

Project identification uses `project_root` (TEXT, the absolute project
path) — same pattern as `libs/scan_history.scan_events`. There is no
`projects` FK because LV_DCP currently has no `projects` SQL table; the
project registry lives in `~/.lvdcp/config.yaml`.

### 5.3 A1 snapshot generator

`libs/breadcrumbs/snapshot.py`. Pure function, **no persistence**, called
on every `lvdcp_resume`:

```python
@dataclass(frozen=True)
class A1Snapshot:
    branch: str
    upstream: str | None
    ahead: int
    behind: int
    last_commits: list[CommitRef]      # last 5
    dirty_files: list[FileChange]      # git status
    staged_files: list[FileChange]
    active_plan: PlanRef | None        # max(mtime) docs/superpowers/plans/
    last_scan: ScanSummary             # from libs/scan_history
    last_eval: EvalSummary | None      # from eval_history if recent
```

Caching — explicit two-tier:

| Field | TTL | Source |
|---|---|---|
| `branch`, `dirty`, `staged`, `last_commits`, `upstream`, `ahead/behind` | none, fresh per call | `git status --porcelain`, `git rev-parse`, `git log -5`, `asyncio.create_subprocess_exec` |
| `last_scan` | in-memory LRU 5 min | `libs/scan_history.read_latest(project_id)` |
| `active_plan` | in-memory LRU 5 min | walk `docs/superpowers/plans/` |
| `last_eval` | in-memory LRU 30 min | `libs/eval/history` |

Latency target for full A1 generation: p95 ≤ 200ms.

### 5.4 ResumePack output type

```python
@dataclass(frozen=True)
class ResumePack:
    generated_at: datetime
    scope: Literal["project", "cross_project"]
    project_pack: ProjectResumePack | None
    digest: list[ProjectDigestEntry] | None

@dataclass(frozen=True)
class ProjectResumePack:
    project_root: str
    snapshot: A1Snapshot
    recent_breadcrumbs: list[BreadcrumbView]
    inferred_focus: FocusGuess
    open_questions: list[str]
    breadcrumbs_empty: bool

@dataclass(frozen=True)
class FocusGuess:
    last_query: str | None
    hot_files: list[Path]              # top-5 by frequency in window
    hot_symbols: list[SymbolRef]       # joined with libs/graph
    last_mode: Literal["navigate", "edit"] | None
```

### 5.5 Activity window and caps

- **Window:** last 12 hours per project (covers full workday with break)
- **Cap per resume:** 100 breadcrumbs in window
- **Cross-project digest:** top-5 projects by `max(ts)` over last 24h

### 5.6 Disk footprint estimate

~200 pack-calls/day · ~500B per row JSONB → ~100KB/day per project. With
14-day TTL: ~1.5MB steady state per project. Hard cap 10000 rows/project
(see §7.4). Negligible.

---

## 6. Section 2 — Triggers, API, hooks

### 6.1 MCP tool surface

**One new tool**, no overload of existing tools:

```python
async def lvdcp_resume(
    path: str | None = None,
    scope: Literal["auto", "project", "cross_project"] = "auto",
    limit: int = 10,
    format: Literal["markdown", "json"] = "markdown",
) -> ResumeResult:
    """
    Resume context for previously active work.

    path=None  → auto-detect (cwd → project / cross_project digest)
    scope=auto → resolve based on path
    limit      → cap on breadcrumbs (project) or projects (cross_project)
    format     → markdown for CC paste-ready / JSON for tooling
    """
```

`lvdcp_pack` and `lvdcp_status` signatures **unchanged**. Both gain a
fire-and-forget breadcrumb write (see §6.4).

### 6.2 CLI surface

```
ctx resume [--path PATH] [--all|-a] [--inject] [--json] [--limit N]
ctx breadcrumb capture --source=<hook_name> [--cc-session-id=ID]
                       [--todo-file=PATH] [--summary=TEXT]
                       [--summary-from-stdin]
ctx breadcrumb list [--path PATH] [--since 12h] [--limit 50]
                    [--include-other-users]
ctx breadcrumb prune [--older-than 14d] [--dry-run] [--project PATH]
ctx breadcrumb purge --project PATH
ctx breadcrumb privacy --project PATH --mode {local_only|full_sync}
```

All commands exit 0 on empty result. Stale lock on `cache.db` → retry once
after 500ms, then skip with stderr warning. **Never blocks CC.**

### 6.3 CC hooks (opt-in)

| Event | Command | Records |
|---|---|---|
| `SessionStart` | `ctx resume --inject --quiet` | (reads, doesn't write) |
| `Stop` | `ctx breadcrumb capture --source=hook_stop` | `todo_snapshot` if available |
| `PreCompact` | `ctx breadcrumb capture --source=hook_pre_compact --summary-from-stdin` | `turn_summary` |
| `SubagentStop` | `ctx breadcrumb capture --source=hook_subagent_stop` | `todo_snapshot` |

The `--cc-session-id` flag is appended automatically by the writer when
CC's session-id env var is present (exact var name —
`CLAUDE_SESSION_ID` or equivalent — to be verified at implementation
time against current CC hooks contract).

Hook contracts:
- Hard timeout 5s
- Stderr only on critical failure
- Always exit 0 (CC never sees LV_DCP failures)
- Never write to `~/Library/Application Support/Claude/`
- Never log secret-bearing fields

Installation:
```
ctx mcp install --hooks=resume                   # all 4 hooks + auto-inject
                                                  # + scheduled prune (default)
ctx mcp install --hooks=resume:no-inject         # skip SessionStart inject
ctx mcp install --hooks=resume:no-schedule       # skip launchd prune
ctx mcp uninstall --hooks=resume                 # full removal
```

Hooks merged into `~/.claude/settings.json` via append-only merge (does
not clobber existing user/other-plugin hooks).

**Default for v0.7.x:** SessionStart auto-inject is **ON**. Documented as
experimental in release notes. Opt-out via `:no-inject` suffix.

### 6.4 Side-effect writers on existing tools

```python
# libs/retrieval/pack.py  (illustrative)
async def pack(req: PackRequest) -> PackResponse:
    response = await _build_pack(req)
    asyncio.create_task(
        breadcrumbs.write_pack_event(
            project_id=req.project_id,
            cc_session_id=_extract_cc_session_id(req),
            query=req.query,
            mode=req.mode,
            paths_touched=[f.path for f in response.files[:5]],
        )
    )
    return response
```

`asyncio.create_task` — fire-and-forget. Writer catches and logs all
exceptions, never propagates. Acceptable trade-off: a breadcrumb may be
lost on backend crash mid-write (this is observability, not source of
truth). Hot-path overhead p95 ≤ 5ms.

### 6.5 `lvdcp_resume(path=None)` auto-detection

Resolution order:
1. ENV `LVDCP_PROJECT_PATH` → use it
2. cwd matches one registered project → use it
3. cwd is nested inside ≥2 registered projects (e.g., worktrees) → longest
   matching path (most-specific)
4. cwd doesn't match any → switch to `scope=cross_project`, return digest
5. No activity in any project for 24h → empty ResumePack +
   `available_projects=[...]`

`limit` interpretation:
- `scope=project`: cap on `recent_breadcrumbs`
- `scope=cross_project`: number of projects in digest
- `scope=auto`: resolved post-detection

### 6.6 Markdown output schema

Target sizes: ≤2KB for `--inject`, ≤10KB for normal call.

```markdown
## Resume: <project name> @ <branch> (<ahead> ahead, <behind> behind)

**Last activity:** <relative-time> · <session count> sessions ·
<count> breadcrumbs in last 12h

### What you were doing
Last query: "<text>"
Last mode: <mode>
Hot files: <top-5 paths>
Hot symbols: <top-5 symbol refs>

### Filesystem state
- Branch: <branch> (vs <upstream>: <ahead> ahead, <behind> behind)
- Dirty: <count> files (<sample>)
- Staged: <count> files
- Last commits:
  - <relative-time>: "<message>"
  - …

### Active plan
[<plan path>](docs/superpowers/plans/...) — last edited <rel-time>.
Inferred step: <N> of <total>.

### Open questions
- pytest <test path> — failing
- <unresolved errors from turn_summary>
```

`--inject` mode keeps only "What you were doing" + collapsed
"Filesystem state". Hard cap 2KB.

### 6.7 Failure modes (explicit table)

| Scenario | Behavior |
|---|---|
| Backend unavailable (CLI) | A1Snapshot only, exit 0, stderr warning |
| `cache.db` locked | Retry 1×500ms, skip with warning |
| Git not in repo | Empty A1, ResumePack returns breadcrumbs only |
| Hook timeout (5s) | Killed, exit 0, doesn't block CC |
| `--inject` with no data | Empty stdout, exit 0, CC injects nothing |
| `cc_session_id` missing | Breadcrumb written without it; FocusGuess works on project+ts |
| `cc_account_email` discovery fails | Logged once per process; column NULL; scoping degrades to `os_user` only |

---

## 7. Section 3 — Privacy, multi-user, retention

### 7.1 Multi-physical-user scoping

Real-world: multiple humans share the laptop with separate CC accounts.
Their breadcrumbs **must not mix**.

Two scope fields, filter at read:

```sql
SELECT * FROM breadcrumbs
WHERE project_id = :pid
  AND ts > now() - interval '12h'
  AND os_user = :current_os_user
  AND (cc_account_email IS NULL OR cc_account_email = :current_cc_email)
ORDER BY ts DESC LIMIT :limit;
```

- `os_user`: from `getpass.getuser()`, always populated
- `cc_account_email`: from read-only parse of CC's
  `~/Library/Application Support/Claude/local-agent-mode-sessions/<accountId>/<orgId>/local_*.json`
  (newest by mtime). Single small parser in
  `libs/breadcrumbs/cc_identity.py` (~80 LOC). Fail-soft to NULL on any
  error; warning logged once per process.

Override: `ctx breadcrumb list --include-other-users` for advanced debug.

### 7.2 Privacy mode inheritance

The `privacy_mode` column accepts `local_only | full_sync`. In this
slice, **only `local_only` is written** — all breadcrumbs stay in
`~/.lvdcp/breadcrumbs.db`. The `full_sync` value is reserved for a
future cross-machine sync pipeline (Phase 8+ ADR) and is not exercised
by any code path in this slice.

`ctx breadcrumb privacy --project PATH --mode {local_only|full_sync}`
exposes the toggle for forward compatibility, but currently writes only
the `local_only` value (CLI rejects `full_sync` with "not implemented in
v0.7.x").

### 7.3 Secret redaction at write

`libs/breadcrumbs/privacy.py`. Pattern-based, deterministic, no LLM.
Applies to `query` and `turn_summary` (NOT `paths_touched` — those are
filesystem paths, not values).

Initial pattern set:

```python
SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("openai",    re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("stripe",    re.compile(r"sk_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("anthropic", re.compile(r"sk-ant-[A-Za-z0-9_-]{40,}")),
    ("github",    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("slack",     re.compile(r"xox[abprs]-[A-Za-z0-9-]{20,}")),
    ("aws",       re.compile(r"AKIA[0-9A-Z]{16}")),
    ("jwt",       re.compile(
        r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    )),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("hex64",     re.compile(r"\b[0-9a-fA-F]{64}\b")),
    ("conn_string", re.compile(
        r"(?:postgres|postgresql|mysql|mongodb|redis|rediss|amqp)"
        r"://[^@\s]*:[^@\s]+@"
    )),
    ("kv_secret", re.compile(
        r"(?:password|passwd|pwd|secret|token|api[_-]?key|"
        r"access[_-]?token|auth)\s*[=:]\s*[\"']?([^\s\"'&]+)",
        re.IGNORECASE,
    )),
]

def redact(text: str) -> str:
    for kind, pat in SECRET_PATTERNS:
        text = pat.sub(f"[REDACTED:{kind}]", text)
    return text
```

User allowlist in `~/.lvdcp/config.yaml`:

```yaml
breadcrumbs:
  redactor_allowlist:
    - "sk-test-DUMMY"
    - "AKIAIOSFODNN7EXAMPLE"
```

Each pattern has a positive test (matches expected secret) and negative
test (does not match plain code/identifiers). False positives → add to
allowlist; do not weaken regex.

### 7.4 Retention

| Type | Default | Configured at |
|---|---|---|
| Breadcrumbs (any source) | 14 days | `breadcrumbs.retention_days` |
| Per-project override | — | `projects.<id>.breadcrumbs_retention_days` |
| Hard cap per project | 10000 rows | `breadcrumbs.max_per_project` |
| Hard cap total | 100000 rows | warning + manual prune required |

Pruning triggers (in order of reliability):
1. **Manual:** `ctx breadcrumb prune` always available
2. **Scheduled:** launchd entry installed by default with `--hooks=resume`
   (see §6.3); runs daily at 04:00 local time, logs to
   `~/Library/Logs/lvdcp/prune.log`
3. **Lazy on-write:** every 100th write per project triggers
   fire-and-forget cap check (no TTL prune at this trigger; only LRU drop
   on cap exceeded)

Read-side pruning (during `lvdcp_resume`) is **explicitly not done** — it
creates surprise side-effects.

### 7.5 launchd entry

```xml
<key>Label</key><string>com.lukinvit.lvdcp.breadcrumb-prune</string>
<key>StartCalendarInterval</key><dict>
  <key>Hour</key><integer>4</integer>
  <key>Minute</key><integer>0</integer>
</dict>
<key>ProgramArguments</key><array>
  <string>{{HOME}}/bin/ctx</string>
  <string>breadcrumb</string>
  <string>prune</string>
  <string>--older-than=14d</string>
</array>
<key>StandardErrorPath</key>
<string>{{HOME}}/Library/Logs/lvdcp/prune.log</string>
```

Installed via `ctx mcp install --hooks=resume` (default-on, opt-out
`:no-schedule`). Removed via `ctx mcp uninstall --hooks=resume`.

### 7.6 Telemetry

Reuses `libs/telemetry`:

- Counter `breadcrumbs.write{source, privacy_mode, redacted}`
- Counter `breadcrumbs.read{scope, hit, empty}`
- Histogram `breadcrumbs.write_latency_ms`
- Counter `breadcrumbs.prune{trigger, deleted}`
- Gauge `breadcrumbs.total_rows`

structlog fields: `project_id`, `os_user`, `cc_session_id`, `source`.
**`query` and `turn_summary` are never logged in plaintext.**

---

## 8. Section 4 — Eval criteria, budgets, acceptance

### 8.1 Eval scenarios (11 total)

All in `tests/eval/resume/`, runnable via `make eval-resume`.

| ID | Scenario | Expected signal |
|---|---|---|
| E1 | Mid-plan: last 3 breadcrumbs at step 3 of 7 | `inferred_step==3`, plan ref in top |
| E2 | Mid-debug: failing test + 2 edits | `open_questions` has test path; `hot_files[0]==edited_src` |
| E3 | Cross-project switch: A 8h ago, B 2h ago | digest order: B, A; B first |
| E4 | Multi-day gap: activity 3 days ago | `breadcrumbs_empty=true` + full A1 + suggestion `--since=7d` |
| E5 | Cold start: new project, no breadcrumbs | A1 only + `breadcrumbs_empty=true` |
| E6 | Hook missed (CC crash): only pack events | FocusGuess from pack-only; A1 complete |
| E7 | Multi-user isolation: A writes 50, B reads | B sees **0** of A's records |
| E8 | Secret redaction: query with `sk-live-...` + conn string | DB and output: **0** plaintext secrets |
| E9 | Auto-inject latency: SessionStart → resume --inject | p95 ≤ 500ms |
| E10 | Cross-project digest accuracy: 10 projects with distinct ts | top-5 sorted correctly |
| E11 | Worktree resolution: cwd in `.claude/worktrees/...` | `project_id == parent`; breadcrumbs of parent visible; git state from worktree |

### 8.2 Aggregate metrics (baseline.json)

```json
{
  "resume_recall_at_5": 0.95,
  "resume_p50_latency_ms": 180,
  "resume_p95_latency_ms": 420,
  "inject_p95_latency_ms": 350,
  "pack_size_bytes_p50": 1800,
  "pack_size_bytes_p95": 4200,
  "secret_leak_count": 0,
  "cross_user_leak_count": 0
}
```

CI gates:
- `resume_recall_at_5 ≥ 0.90` (tighten to 0.95 in v0.7.x once stable)
- `resume_p95_latency_ms ≤ 1500`
- `secret_leak_count == 0` (hard)
- `cross_user_leak_count == 0` (hard)

Regression > 5% drop vs previous baseline → PR warning, requires explicit
"accept regression" in commit message.

### 8.3 Latency budgets

| Operation | p50 | p95 | Hard cap |
|---|---|---|---|
| `lvdcp_resume(scope=project)` | ≤ 300ms | ≤ 1000ms | 3000ms |
| `lvdcp_resume(scope=cross_project)` | ≤ 500ms | ≤ 1500ms | 3000ms |
| `lvdcp_resume(--inject)` | ≤ 200ms | ≤ 500ms | 5000ms (hook) |
| Breadcrumb writer (sync path) | ≤ 5ms | ≤ 20ms | 100ms |
| Pack overhead from breadcrumb write | ≤ 1ms | ≤ 5ms | — |
| `ctx breadcrumb capture` (hook entry) | ≤ 50ms | ≤ 200ms | 5000ms |

### 8.4 Cost budget

- LLM calls per resume: **0**
- Embedding calls per resume: **0**
- Backend CPU: < 10ms p95

Phase 7 resume is purely deterministic. LLM-driven enrichment requires a
new ADR if proposed.

### 8.5 Resource budget

| Resource | Steady state | Hard cap |
|---|---|---|
| Disk per project (cache.db) | ~1.5MB | TTL prune 14d |
| SQLite rows per project | <3000 typical | 10000 (LRU drop) |
| SQLite rows total | <100k | 100000 (warning + manual) |
| Backend memory overhead | <50MB | LRU caches sized |

### 8.6 Test coverage

- `libs/breadcrumbs/`: ≥ 90%
- `apps/cli/breadcrumb*`: ≥ 85%
- Hook installer: ≥ 80% + e2e test against tmp `~/.claude/settings.json`

### 8.7 Eval harness layout

```
tests/eval/resume/
  __init__.py
  conftest.py                 # synthetic breadcrumbs + fake git repos
  test_e1_mid_plan.py
  test_e2_mid_debug.py
  test_e3_cross_project.py
  test_e4_multi_day_gap.py
  test_e5_cold_start.py
  test_e6_hook_missed.py
  test_e7_multi_user.py
  test_e8_redaction.py
  test_e9_inject_latency.py
  test_e10_digest_order.py
  test_e11_worktree_resolution.py
  baseline.json
```

Make targets:
- `make eval-resume` — only resume scenarios
- `make eval` — all (existing eval + resume)
- `make eval-resume-update` — overwrite `baseline.json` after intentional
  improvement

### 8.8 Acceptance criteria (definition of done)

Phase 7 slice merges only when **all** are true:

1. All 11 eval scenarios pass
2. `resume_recall_at_5 ≥ 0.90` on baseline
3. `secret_leak_count = 0`, `cross_user_leak_count = 0`
4. All latency budgets in green on CI runner
5. `libs/breadcrumbs/` coverage ≥ 90%
6. `mypy --strict` clean on new code
7. `ruff check` clean
8. **Manual smoke test:** install hooks → 30-min real session →
   kill → `ctx resume` returns non-trivial pack (invariant #11 dogfood)
9. Release notes describe experimental status of auto-inject + opt-out
10. Spec + ADR (if needed) committed before merge

---

## 9. Out of scope (explicit)

- A3 transcript JSONL parsing (Phase 8+ if needed)
- Cross-machine sync of breadcrumbs (Phase 8+ ADR)
- Encrypted at rest (depends on redactor sufficiency)
- Multi-tenant / team mode (constitution)
- LLM rerank / focus inference (separate ADR)
- TUI mode (overkill for usage pattern)
- Auto-inject of cross-project digest into SessionStart (only
  project-scoped inject; cross-project requires explicit `ctx resume -a`)
- Editing CC private files for any reason (constitution + ToS)

---

## 10. Appendix — `recover-cc-session` (out of LV_DCP repo)

This standalone utility lives in `~/bin/recover-cc-session` and is **not
part of LV_DCP**. It exists to recover the user's own CC sessions after
Cowork/Dispatch failures. Documented here only to clarify the full
solution to the original request.

### 10.1 Form

- File: `~/bin/recover-cc-session` (no extension, like `~/bin/ctx`)
- Language: Python 3.12+ via PEP 723 inline script metadata
- Self-bootstrapping shebang: `#!/usr/bin/env -S uv run --script`
- Dependencies (inline): `typer >= 0.12`, `rich >= 13.7`
- Size target: ~250 LOC

### 10.2 Subcommands

```
recover-cc-session list               # both folders, mtimes, accountIds
recover-cc-session diff               # missing/extra in each folder
recover-cc-session backup [--out PATH] # tarball of both folders
recover-cc-session restore --from=cs --to=lams
                          [--id ID] [--all-missing]
                          [--dry-run] [--no-backup]
recover-cc-session undo [--snapshot TS]
recover-cc-session snapshots [--limit 10]
recover-cc-session snapshots prune --older-than 30d
```

### 10.3 Versioned snapshot system

Every mutating operation creates a snapshot at:

```
~/Library/Application Support/Claude/.lv-recover-snapshots/
  <YYYY-MM-DDTHH-MM-SS>/
    claude-code-sessions/...           # full pre-mutation copy
    local-agent-mode-sessions/...
    metadata.json                       # command, args, timestamp
```

`undo` restores from the most recent (or specified) snapshot. `undo`
itself creates a snapshot — every operation is reversible.

Auto-prune: every 5th invocation lazily drops snapshots older than 30
days. Hard cap 50 snapshots (LRU).

Append-only audit log at `.lv-recover-snapshots/audit.log` (JSONL).

### 10.4 Hard safety rules

1. Backup before any write (auto). `--no-backup` requires
   `--i-know-what-im-doing`.
2. Operates only on `~/Library/Application Support/Claude/...` under
   current `whoami`.
3. **Never modifies** `accountName`, `emailAddress`, `accountId`,
   `orgId`. This is what separates B from rejected option C.
4. `--dry-run` is default for `restore`. Real write requires `--apply`.
5. Conflict resolution always interactive or via explicit
   `--skip-existing` / `--overwrite`.
6. Zero network calls.

### 10.5 Out of scope for `recover-cc-session`

- Editing identity fields in session JSON (option C)
- Touching `~/.claude/settings.json`
- Parsing transcript JSONL
- Integration with LV_DCP
- Running from cron / launchd / hook
- Publishing to LV_DCP repo or any public location

### 10.6 Build budget

~60 minutes total: ~30 min for typer/rich CLI shell, ~20 min for snapshot
system, ~10 min for live testing on real CC session folders.

---

## 11. Open questions / future work

- **Cross-machine sync** — whose `os_user` and `cc_account_email` win on
  conflict? Needs ADR before implementation.
- **A3 transcript reading** — if Phase 7 resume turns out to need richer
  conversation context, design a feature-flagged read-only parser as
  optional enricher.
- **`turn_summary` source** — Phase 7 fills this only from
  `PreCompact` hook payload. If CC adds richer hook payloads in future,
  enrich without breaking schema.
- **Plan step inference** — current heuristic walks `## Step N` headings
  in plan markdown and counts breadcrumbs since last edit. May need
  refinement after dogfood.
- **Hot symbol resolution** — joined with `libs/graph/symbols`; if symbol
  table is stale, hot_symbols may be empty. Acceptable degradation.
