# Post-scan wiki hook — design spec

**Date:** 2026-04-13  
**Status:** Implemented 2026-04-13  
**Scope:** Phase 7 — automatic wiki update after daemon scan

---

## Problem

Wiki articles are generated manually via `ctx wiki update`. The daemon marks modules
dirty after every scan (via `update_dirty_state`), but never triggers generation.
Result: wiki goes stale silently; `lvdcp_pack` injects outdated articles into context.

Vectors (`embed_project_files`) already run best-effort at the end of every
`scan_project` — no new work needed there.

---

## Solution

Add a bounded `ThreadPoolExecutor` to the daemon. After every `scan_project` call,
if the number of newly-dirty modules meets a configurable threshold, submit a
background wiki-update task. The daemon continues processing filesystem events
without blocking.

---

## Architecture

```
process_pending_events() in daemon.py
  └─ scan_project(root) → dirty_count          ← scanner returns this (currently None)
  └─ if dirty_count >= cfg.wiki_dirty_threshold
        and cfg.post_scan_wiki:
          _wiki_pool.submit(_wiki_update_task, root)
```

```
_wiki_update_task(project_path: Path)           ← new apps/agent/wiki_worker.py
  1. open cache.db
  2. ensure_wiki_table()
  3. get_dirty_modules() → list
  4. for each module:
       generate_wiki_article(...) → write file → mark_current()
  5. write_index(wiki_dir, project_name)
  6. on any error: log warning, continue next module
```

---

## Files changed

| File | Change |
|------|--------|
| `libs/scanning/scanner.py` | `scan_project()` returns `int` (dirty_count) instead of `None` |
| `libs/core/projects_config.py` | extend `DaemonConfig` with 3 new fields |
| `apps/agent/daemon.py` | init pool, read config, submit task post-scan |
| `apps/agent/wiki_worker.py` | **new** — background wiki update task |
| `tests/unit/agent/test_wiki_worker.py` | **new** — unit tests with mocked Claude CLI |

---

## Config schema

Added to `DaemonConfig` (persisted in `~/.lvdcp/config.yaml`):

```yaml
daemon:
  post_scan_wiki: true          # enable/disable entirely
  wiki_dirty_threshold: 3       # min dirty modules to trigger update
  wiki_max_workers: 1           # max concurrent wiki update tasks
```

Defaults are conservative: threshold=3 avoids triggering on single-file edits;
max_workers=1 prevents parallel Claude CLI calls for the same project.

---

## `scan_project` return value

Currently `scan_project()` returns `None`. Change signature to return `int`:
the number of modules marked dirty in this scan (from `update_dirty_state`).

If the wiki dirty-tracking block fails (existing `except Exception: pass`), return 0
so the daemon does not attempt wiki update on an unknown dirty state.

---

## Daemon lifecycle

```python
# run_daemon() startup
_wiki_pool = ThreadPoolExecutor(max_workers=cfg.wiki_max_workers)

# run_daemon() shutdown (finally block)
_wiki_pool.shutdown(wait=False)   # don't block SIGTERM/Ctrl+C
```

`wait=False` means in-progress wiki tasks are abandoned on daemon shutdown.
This is safe: dirty state persists in SQLite, next scan re-triggers the update.

---

## wiki_worker.py design

```python
def run_wiki_update(project_path: Path) -> None:
    """Background task: generate wiki articles for all dirty modules."""
    # Opens its own DB connection via sqlite3.connect() directly
    # (avoids cache._connect() private API — known antipattern in wiki_cmd.py)
    # Mirrors logic from apps/cli/commands/wiki_cmd.py:update()
    # Errors per-module are caught and logged; other modules continue
    # Does NOT regenerate architecture.md (too expensive for background)
    # DOES rebuild INDEX.md after all modules processed
```

Architecture page regeneration is excluded from the background task — it requires
summarising the full module list and is expensive. It remains a manual operation
via `ctx wiki update --all`.

---

## Concurrency / edge cases

| Scenario | Handling |
|----------|----------|
| Scan fires again while wiki task running | Task queued (pool bounded); processes after current task completes |
| Daemon stops mid-wiki-generation | `shutdown(wait=False)` — task abandoned; dirty state preserved; next scan re-triggers |
| Claude CLI unavailable | `RuntimeError` caught per-module; logged as warning; other modules continue |
| DB locked (scan + wiki concurrent writes) | SQLite default journal handles; wiki_worker opens separate connection |
| dirty_count < threshold | Task never submitted; no log noise |
| `post_scan_wiki: false` | Task never submitted regardless of dirty_count |

---

## Testing

`tests/unit/agent/test_wiki_worker.py`:

- `test_runs_for_dirty_modules` — mocks `generate_wiki_article`, verifies it's called for each dirty module
- `test_skips_clean_modules` — verifies clean modules are not regenerated
- `test_continues_on_module_error` — verifies single module error doesn't abort others
- `test_rebuilds_index_after_run` — verifies `write_index` called exactly once at end
- `test_no_architecture_page` — verifies architecture.md is NOT generated in background task

Integration: extend `tests/integration/test_ctx_watch.py` to verify `process_pending_events`
submits wiki task when `dirty_count >= threshold`.

---

## Out of scope

- Retry logic / exponential backoff for Claude CLI failures (future)
- Architecture page background generation (too expensive)
- Windows/Linux daemon support (already out of scope per CLAUDE.md)
- Per-project threshold override (global config sufficient for now)
