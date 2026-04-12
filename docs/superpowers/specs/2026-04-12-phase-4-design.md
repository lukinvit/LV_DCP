# Phase 4 — Retrieval Quality, Git Intelligence, Impact Analysis

**Status:** Draft 2026-04-12
**Owner:** Vladimir Lukin
**Follows:** Phase 3 complete (`phase-3c2-complete` tag, version 0.3.4)
**Version target:** 0.4.0

## 1. Goal

Make LV_DCP genuinely useful on real multi-language projects (not just its own codebase). Fix Russian FTS, add git intelligence for hotspot/impact analysis, make the dashboard interactive and self-service. **Litmus test: TG_APP_COLLECT** (1544 files, mixed ru/en) must produce quality retrieval results.

## 2. Scope — 6 weeks, 5 deliverable groups

| Week | Deliverable | Key metric |
|---|---|---|
| 1 | Retrieval quality fix (pymorphy3 + ignore + eval) | TG_APP_COLLECT recall@5 ≥ 0.60 |
| 2 | Adaptive graph clustering + UI project management | 6 projects visible, graph usable on 1500-file project |
| 3 | Git intelligence infrastructure (churn + blame) | git_stats populated for all 6 projects |
| 4 | Static impact analysis + hotspot widget | Impact API + top-10 hotspot table |
| 5 | Edit pack v2 (diff-aware) + multi-project eval gate | All eval thresholds pass |
| 6 | Buffer / calibration / polish | Dogfood report, version 0.4.0, tag |

## 3. Week 1 — Retrieval Quality Fix

### 3.1 pymorphy3 stemmer integration

**New module:** `libs/retrieval/stemmer.py`

**Indexing (ctx scan):** each token normalized via `pymorphy3.MorphAnalyzer().normal_forms()[0]` before FTS5 insertion. Original text also indexed — dual-column approach: `content` (original) + `content_stemmed` (normalized). FTS5 searches both columns, stemmed matches get weight 1.0, original matches get weight 0.8 (stemmed is primary).

**Query time:** query text normalized through same stemmer before FTS search. "подключениями" → "подключение" matches indexed "подключение" from source code.

**Language detection:** simple heuristic — if token contains Cyrillic characters, apply pymorphy3. Otherwise leave as-is (FTS5 unicode61 handles English).

**Dependency:** `pymorphy3` + `pymorphy3-dicts-ru` added to `pyproject.toml` as required dependency (~15MB installed). Performance: ~100K words/sec normalization. TG_APP_COLLECT scan overhead: +2-5 seconds.

**Implementation:**

```python
# libs/retrieval/stemmer.py
from __future__ import annotations

import re
from functools import lru_cache

_CYRILLIC = re.compile(r"[а-яёА-ЯЁ]")
_analyzer = None


def _get_analyzer():
    global _analyzer
    if _analyzer is None:
        import pymorphy3
        _analyzer = pymorphy3.MorphAnalyzer()
    return _analyzer


def normalize_token(token: str) -> str:
    if not _CYRILLIC.search(token):
        return token.lower()
    morph = _get_analyzer()
    parsed = morph.parse(token.lower())
    return parsed[0].normal_form if parsed else token.lower()


def normalize_query(query: str) -> str:
    return " ".join(normalize_token(t) for t in query.split())
```

**FTS integration:** modify `libs/retrieval/fts.py`:
- `FtsIndex.add_file()` now stores both original content and stemmed content
- `FtsIndex.search()` normalizes query through stemmer before executing
- FTS5 table schema: `CREATE VIRTUAL TABLE fts USING fts5(path, content, content_stemmed)`

### 3.2 Ignore patterns

**Modify:** `libs/policies/ignore.py`

Add to `DEFAULT_IGNORE_DIRS`:
- `.playwright-mcp`
- `.superpowers`

Add to `DEFAULT_IGNORE_FILENAME_PATTERNS`:
- `*.min.js`
- `*.min.css`

Add to `DEFAULT_IGNORE_FILENAME_EXACT`:
- `.claude/settings.local.json`
- `.claude/settings.json`

Add size-based ignore: skip files > 100KB with extension `.json` (data dumps). Implement as a check in scanner, not in ignore policy (policy is path-based only).

### 3.3 Multi-project eval fixture

**New file:** `tests/eval/multiproject_queries.yaml`

```yaml
version: 1
description: Real queries across multiple registered projects.
projects:
  TG_APP_COLLECT:
    root: /Users/v.lukin/Nextcloud/lukinvit.tech/projects/TG_APP_COLLECT
    queries:
      - id: tc01-telegram-client
        text: "telegram client connection and rate limiting"
        mode: navigate
        expected:
          files: [src/telegram/client.py, src/telegram/rate_limiter.py]
      - id: tc02-telegram-scraping-ru
        text: "сбор данных из телеграм каналов"
        mode: navigate
        expected:
          files: [src/telegram/client.py, src/telegram/client_pool.py]
      - id: tc03-add-source
        text: "add new telegram scraping source"
        mode: edit
        expected:
          files: [src/telegram/client.py, src/telegram/client_pool.py]
```

(3-5 queries per project, total ~25 queries across 6 projects. Full list determined during implementation based on each project's structure.)

**Eval runner extension:** `tests/eval/run_multiproject_eval.py` — scans each project, runs queries, reports per-project recall@5.

**Week 1 eval gate:** TG_APP_COLLECT recall@5 ≥ 0.60 on tc01-tc03.

## 4. Week 2 — Adaptive Graph + UI Project Management

### 4.1 Graph clustering by modules

**Modify:** `libs/status/aggregator.py` (`_build_graph_dump`) + `libs/status/models.py` + `apps/ui/static/js/dashboard.js`

**Backend data model:**

```python
# libs/status/models.py — new/modified
class GraphCluster(BaseModel):
    id: str              # directory path, e.g. "libs/retrieval"
    label: str           # display name
    role: str            # dominant role in cluster
    children_count: int  # total files in directory
    total_degree: int    # sum of degrees of all files in cluster
    files: list[GraphNode]  # top files by degree (max 20)

class GraphDump(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    clusters: list[GraphCluster]  # NEW
```

**Clustering algorithm in `_build_graph_dump`:**
1. Group all files by first 2 path segments (e.g., `libs/retrieval/pipeline.py` → cluster `libs/retrieval`)
2. For each cluster: compute total_degree (sum of all file degrees within)
3. Sort clusters by total_degree descending
4. Take top 50 clusters as supernodes
5. Within each cluster: sort files by degree, take top 20
6. Edges: both intra-cluster (file→file within) and inter-cluster (cluster→cluster derived from file edges)

**Frontend (D3):**
- Initial state: supernodes only. Size = sqrt(total_degree). Color = dominant role.
- Click supernode → expand to show top-20 files. Transition animation.
- Click background → collapse all.
- d3-zoom for pan + zoom (mouse wheel + drag).
- Tooltip on hover: cluster name + file count + total connections.

**Limits:** 50 clusters × 20 files = 1000 max visible nodes. Canvas 2D handles this.

### 4.2 UI project management

**New:** `apps/ui/routes/projects.py`

**Endpoints:**
- `POST /api/projects/add` — body: `{"path": "/abs/path"}` → validates path, adds to config.yaml via `apps/agent/config.add_project()`, triggers `scan_project()`, returns project card HTML (HTMX swap)
- `DELETE /api/projects/{slug}/remove` — removes from config.yaml via `apps/agent/config.remove_project()`, returns empty (HTMX swap removes card)

**UI:**
- "+" button in Overview page header → HTMX modal:
  ```html
  <form hx-post="/api/projects/add" hx-target="#project-list" hx-swap="beforeend">
    <input name="path" placeholder="/path/to/project" required>
    <button type="submit">Add & Scan</button>
  </form>
  ```
- "×" button on each project card → `hx-delete="/api/projects/{slug}/remove"` with confirm

**Validation:**
- Path must exist and be a directory
- Path not already registered (no duplicates)
- Path must contain at least 1 file (not empty)

**Auto-register on scan:** modify `apps/cli/commands/scan_cmd.py` — after successful scan, check if project is in config.yaml. If not, add it automatically.

## 5. Week 3 — Git Intelligence Infrastructure

### 5.1 Git data extraction

**New module:** `libs/gitintel/extractor.py`

**Data model:**

```python
# libs/gitintel/models.py
class GitFileStats(BaseModel):
    file_path: str
    commit_count: int
    churn_30d: int
    last_modified_ts: float
    age_days: int
    authors: list[str]
    primary_author: str
    last_author: str
```

**Extraction via subprocess:**
- `git log --format="%H %aI %aN" --follow -- <file>` → commit_count, last_modified, age, authors
- `git blame --porcelain <file>` → line-level authorship → primary_author, last_author
- Batch mode: `git log --name-only --format="%H %aI %aN"` for all files at once (one git call, not per-file)

**No new dependencies.** Pure subprocess + parsing.

**Storage:** new table `git_stats` in `.context/cache.db`:

```sql
CREATE TABLE IF NOT EXISTS git_stats (
    file_path TEXT PRIMARY KEY,
    commit_count INTEGER NOT NULL DEFAULT 0,
    churn_30d INTEGER NOT NULL DEFAULT 0,
    last_modified_ts REAL,
    age_days INTEGER NOT NULL DEFAULT 0,
    authors_json TEXT NOT NULL DEFAULT '[]',
    primary_author TEXT NOT NULL DEFAULT '',
    last_author TEXT NOT NULL DEFAULT '',
    computed_at_ts REAL NOT NULL
);
```

**Integration with scan:** `libs/scanning/scanner.py` — after file+symbol parsing, call `extract_git_stats()` for changed files. Full git extraction on `--full` scan.

**Incrementality:** only recompute git stats for files whose `content_hash` changed since last scan. `computed_at_ts` tracks freshness.

### 5.2 Retrieval boost from git signals

**Modify:** `libs/retrieval/pipeline.py` — new function `_apply_git_boost`

```python
GIT_CHURN_BOOST = 1.10      # file changed in last 30 days
GIT_NEW_FILE_BOOST = 1.05   # file created in last 30 days

def _apply_git_boost(
    file_scores: dict[str, float],
    git_stats: dict[str, GitFileStats],
) -> None:
    for path in list(file_scores):
        stats = git_stats.get(path)
        if stats is None:
            continue
        if stats.churn_30d > 0:
            file_scores[path] *= GIT_CHURN_BOOST
        if stats.age_days < 30:
            file_scores[path] *= GIT_NEW_FILE_BOOST
```

**Pipeline integration:** called after `_apply_role_weights`, before `_apply_score_decay`. Requires loading git_stats lazily (same pattern as `_get_file_roles`).

**Calibration:** multipliers are conservative (5-10%). Eval must show no regression on LV_DCP synthetic fixture. If regression detected, reduce multipliers.

## 6. Week 4 — Static Impact Analysis + Hotspot Widget

### 6.1 Impact analysis

**New module:** `libs/impact/analyzer.py`

```python
class ImpactReport(BaseModel):
    target: str                    # file being changed
    direct_dependents: list[str]   # files that import from target
    transitive_dependents: list[str]  # reachable via BFS depth 4
    affected_tests: list[str]      # subset of dependents with role="test"
    risk_score: float              # fan_out × fan_in × (1 + churn_30d/10)

def analyze_impact(
    target_file: str,
    graph: Graph,
    git_stats: dict[str, GitFileStats],
    file_roles: dict[str, str],
) -> ImpactReport:
    ...
```

**Algorithm:**
1. `direct_dependents` = `graph.reverse_neighbors(target)` — who imports target
2. `transitive_dependents` = BFS from target in reverse graph, depth 4
3. `affected_tests` = filter transitive by `role == "test"`
4. `risk_score` = `len(direct_dependents) × len(graph.neighbors(target)) × (1 + git_stats.churn_30d / 10)`

**API endpoint:** `GET /api/project/{slug}/impact?file=<path>` → ImpactReport JSON

**MCP integration:** extend `lvdcp_inspect` tool with `mode="impact"` — for Claude to call before edit tasks.

### 6.2 Hotspot analysis

**New module:** `libs/impact/hotspots.py`

```python
class HotspotEntry(BaseModel):
    file_path: str
    fan_in: int
    fan_out: int
    churn_30d: int
    has_tests: bool
    hotspot_score: float

def compute_hotspots(
    graph: Graph,
    git_stats: dict[str, GitFileStats],
    file_roles: dict[str, str],
    limit: int = 10,
) -> list[HotspotEntry]:
    ...
```

**Score formula:** `hotspot_score = fan_in × (1 + churn_30d) × (2.0 if not has_tests else 1.0)`

High fan_in (many dependents) + high churn (frequently changed) + no tests = hotspot.

**Dashboard widget:**
- New section "Hotspots" on project page, below dependency graph
- HTML table with sortable columns: File, Fan-in, Fan-out, Churn (30d), Tests, Score
- Color coding: score > 50 red, > 20 yellow, else green
- HTMX partial: `apps/ui/templates/partials/hotspots.html.j2`

### 6.3 Impact visualization in graph

**Modify:** `apps/ui/static/js/dashboard.js`

- Click on a node → fetch `/api/project/{slug}/impact?file=<path>`
- Highlight transitive dependents in orange (semi-transparent)
- Show sidebar panel with ImpactReport summary: direct deps count, transitive count, affected tests, risk score
- Click elsewhere → dismiss panel

## 7. Week 5 — Edit Pack v2 + Eval Gate

### 7.1 Diff-aware edit packs

**Modify:** `libs/context_pack/builder.py`

**New function:**

```python
def _git_changed_files(project_root: Path) -> list[str]:
    """Return files with uncommitted changes (staged + unstaged)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=project_root, capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return []
        return [f.strip() for f in result.stdout.splitlines() if f.strip()]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
```

**Integration in build_pack():**
- When `mode="edit"`: call `_git_changed_files(project_root)`
- Add changed files to retrieval seed set with boost score (same as symbol match weight)
- In pack markdown output: new section `## Currently Modified` listing changed files with `git diff --stat` summary

**Fallback:** if git not available or not a repo, skip silently.

### 7.2 Multi-project eval gate

**New:** `tests/eval/run_multiproject_eval.py` + `scripts/multiproject-eval-report.sh`

**Process per project:**
1. `scan_project(root, mode="full")` — ensures fresh index
2. Run queries from `multiproject_queries.yaml`
3. Compute recall@5 per project

**Phase 4 eval thresholds:**

| Metric | Target | Notes |
|---|---|---|
| LV_DCP synthetic recall@5 | ≥ 0.92 | No regression from Phase 3c.2 |
| LV_DCP real recall@5 | ≥ 0.80 | No regression |
| TG_APP_COLLECT recall@5 | ≥ 0.60 | Litmus test |
| Cross-project average recall@5 | ≥ 0.50 | Across all 6 projects |
| LV_DCP impact_recall@5 | ≥ 0.85 | No regression |

### 7.3 Version + tag

- `pyproject.toml`: `0.3.4` → `0.4.0`
- Git tag: `phase-4-complete` on HEAD main (if all eval thresholds pass)
- Dogfood report: `docs/dogfood/phase-4.md` — before/after for all 6 projects

## 8. Architecture

```
libs/
  retrieval/
    stemmer.py          [NEW — pymorphy3 normalization]
    pipeline.py         [MODIFY — git boost pass]
    fts.py              [MODIFY — stemmed column]
  gitintel/
    extractor.py        [NEW — git log/blame parsing]
    models.py           [NEW — GitFileStats]
  impact/
    analyzer.py         [NEW — per-file impact analysis]
    hotspots.py         [NEW — hotspot scoring]
  status/
    aggregator.py       [MODIFY — graph clustering]
    models.py           [MODIFY — GraphCluster model]
  context_pack/
    builder.py          [MODIFY — diff-aware packs]
  policies/
    ignore.py           [MODIFY — new ignore patterns]
  storage/
    sqlite_cache.py     [MODIFY — git_stats table]

apps/
  ui/
    routes/
      projects.py       [NEW — add/remove project endpoints]
      api.py            [MODIFY — impact endpoint]
    templates/partials/
      add_project.html.j2   [NEW]
      hotspots.html.j2      [NEW]
    static/js/
      dashboard.js      [MODIFY — clustering + zoom + impact viz]
  cli/commands/
    scan_cmd.py         [MODIFY — auto-register]

tests/
  eval/
    multiproject_queries.yaml  [NEW]
    run_multiproject_eval.py   [NEW]
  unit/
    retrieval/test_stemmer.py  [NEW]
    gitintel/test_extractor.py [NEW]
    impact/test_analyzer.py    [NEW]
    impact/test_hotspots.py    [NEW]
```

## 9. Files NOT Touched

- `libs/llm/*` — LLM infrastructure from Phase 3c.1 untouched
- `libs/summaries/*` — summary store untouched
- `libs/graph/builder.py` — graph building untouched, only consumed
- `libs/retrieval/graph_expansion.py` — graph walk untouched
- `apps/mcp/server.py` — MCP server untouched (auto-picks up pipeline changes)
- `apps/agent/*` — daemon untouched

## 10. Dependencies

**New:**
- `pymorphy3` — Russian morphological analyzer
- `pymorphy3-dicts-ru` — Russian dictionary for pymorphy3

**No other new dependencies.** Git intelligence uses subprocess, not gitpython.

## 11. Risks

**R1 — pymorphy3 slows scan significantly on large projects.**
Mitigation: lazy initialization (first call only), normalize only during FTS indexing (not during symbol/relation extraction). Benchmark on TG_APP_COLLECT: must stay under +10 seconds.

**R2 — Git blame on large repos is slow.**
Mitigation: batch mode (`git log --name-only` for churn, single pass). Blame only for files that changed. Full blame run only on `--full` scan. Timeout: 30s per project, skip gracefully.

**R3 — Graph clustering loses inter-file detail.**
Mitigation: click-to-expand preserves file-level view. Cluster edges show aggregate connections. Top-20 files by degree inside each cluster ensures important files always visible.

**R4 — Git boost multipliers hurt retrieval precision.**
Mitigation: conservative values (1.05-1.10). Eval gate catches regressions. Easy to disable (set multipliers to 1.0).

**R5 — pymorphy3 dictionary adds 15MB to install size.**
Accepted. Local-first tool, not a microservice. 15MB is negligible for desktop install.

**R6 — Multi-project eval hardcodes absolute paths.**
Mitigation: eval fixture uses project names, resolver maps to current machine paths at runtime from config.yaml.

## 12. Non-goals

Phase 4 does NOT do:
- Vector search / embeddings — deferred, may never be needed
- LLM-based rerank — not needed given deterministic improvements
- Cross-project retrieval ("find pattern across all projects") — Phase 5+
- VS Code extension — Phase 6
- Qdrant integration — Phase 5+
- Obsidian sync — Phase 6
- Multi-language tree-sitter (TypeScript, Go, Rust) — Phase 5
- Query expansion via LLM — too expensive for local tool
- Real-time file watching with git hooks — daemon handles this

## 13. Eval gate

Phase 4 closes when ALL pass:

1. LV_DCP synthetic recall@5 ≥ 0.92
2. LV_DCP real recall@5 ≥ 0.80
3. LV_DCP impact_recall@5 ≥ 0.85
4. TG_APP_COLLECT recall@5 ≥ 0.60
5. Cross-project average recall@5 ≥ 0.50
6. `make lint typecheck test` green
7. Hotspot widget renders for all 6 projects
8. Impact API returns valid data for all 6 projects
9. Graph clustering works on TG_APP_COLLECT (1544 files)
10. Dogfood report `docs/dogfood/phase-4.md` committed

**If all pass:** version 0.4.0, tag `phase-4-complete`.
**If eval fails:** iterate on multipliers / stemmer / ignore patterns. Max 3 calibration rounds.

## 14. Estimate

| Week | Deliverable | Days |
|---|---|---|
| 1 | pymorphy3 + ignore + eval fixture | 5 |
| 2 | Graph clustering + UI project management | 5 |
| 3 | Git intelligence (extractor + retrieval boost) | 5 |
| 4 | Impact analysis + hotspot widget | 5 |
| 5 | Edit pack v2 + multi-project eval gate | 5 |
| 6 | Buffer / calibration / polish / dogfood | 3-5 |
| **Total** | | **~28-30 working days** |
