# Post-scan wiki hook — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Status:** Implemented 2026-04-13

**Goal:** After every daemon scan, automatically generate wiki articles for dirty modules in a background thread when `dirty_count >= configurable threshold`.

**Architecture:** `scan_project()` returns `wiki_dirty_count` via `ScanResult`. `process_pending_events` submits `run_wiki_update` to a bounded `ThreadPoolExecutor` when threshold is met. `wiki_worker.py` opens its own SQLite connection and calls existing generator functions directly.

**Tech Stack:** Python 3.12, `concurrent.futures.ThreadPoolExecutor`, `sqlite3`, `libs.wiki.*`, `libs.core.projects_config.WikiConfig`, `watchdog`

---

## File map

| File | Change |
|------|--------|
| `libs/core/projects_config.py` | Add `dirty_threshold: int = 3`, `max_workers: int = 1` to `WikiConfig` |
| `libs/scanning/scanner.py` | Add `wiki_dirty_count: int = 0` to `ScanResult`; capture return of `update_dirty_state` |
| `apps/agent/wiki_worker.py` | **New** — `run_wiki_update(project_path, config)` background task |
| `apps/agent/daemon.py` | Import `ThreadPoolExecutor`; add pool to `run_daemon`; pass pool to `process_pending_events` |
| `tests/unit/agent/test_wiki_worker.py` | **New** — unit tests with mocked Claude CLI |
| `tests/integration/test_ctx_watch.py` | Extend: verify `process_pending_events` submits wiki task when threshold met |

---

## Task 1: Extend WikiConfig and ScanResult

**Files:**
- Modify: `libs/core/projects_config.py:77-81`
- Modify: `libs/scanning/scanner.py:38-46`
- Test: `tests/unit/core/test_projects_config.py`

- [x] **Step 1: Write failing tests**

```python
# tests/unit/core/test_projects_config.py  — add to existing file
def test_wiki_config_dirty_threshold_default() -> None:
    cfg = WikiConfig()
    assert cfg.dirty_threshold == 3

def test_wiki_config_max_workers_default() -> None:
    cfg = WikiConfig()
    assert cfg.max_workers == 1

def test_wiki_config_from_dict() -> None:
    cfg = WikiConfig.model_validate({"dirty_threshold": 5, "max_workers": 2})
    assert cfg.dirty_threshold == 5
    assert cfg.max_workers == 2
```

- [x] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/core/test_projects_config.py -k "dirty_threshold or max_workers" -v
```
Expected: `AttributeError: 'WikiConfig' object has no attribute 'dirty_threshold'`

- [x] **Step 3: Add fields to WikiConfig**

In `libs/core/projects_config.py`, change `WikiConfig`:
```python
class WikiConfig(BaseModel):
    enabled: bool = False
    auto_update_after_scan: bool = False
    max_modules_per_run: int = 10
    article_max_tokens: int = 2000
    dirty_threshold: int = 3    # min dirty modules to trigger background update
    max_workers: int = 1        # max concurrent wiki update tasks
```

- [x] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/core/test_projects_config.py -k "dirty_threshold or max_workers" -v
```
Expected: `3 passed`

- [x] **Step 5: Add wiki_dirty_count to ScanResult**

In `libs/scanning/scanner.py`, change `ScanResult`:
```python
@dataclass
class ScanResult:
    files_scanned: int
    files_reparsed: int
    stale_files_removed: int
    symbols_extracted: int
    relations_reparsed: int
    relations_cached: int
    elapsed_seconds: float
    wiki_dirty_count: int = 0  # modules marked dirty in this scan
```

- [x] **Step 6: Capture update_dirty_state return in scanner**

In `libs/scanning/scanner.py`, find the wiki dirty tracking block (around line 278) and change:
```python
        # Wiki dirty tracking (best-effort, never blocks scan)
        _wiki_dirty_count = 0
        try:
            from libs.wiki.state import ensure_wiki_table, update_dirty_state  # noqa: PLC0415

            wiki_conn = cache._connect()
            ensure_wiki_table(wiki_conn)
            _wiki_dirty_count = update_dirty_state(wiki_conn, files_processed)
            wiki_conn.commit()
        except Exception:
            pass  # Best-effort: wiki tracking must never kill a scan
```

Then find where `ScanResult` is constructed (end of `scan_project`) and add `wiki_dirty_count=_wiki_dirty_count`. The construction looks like:
```python
        return ScanResult(
            files_scanned=...,
            files_reparsed=...,
            stale_files_removed=...,
            symbols_extracted=...,
            relations_reparsed=...,
            relations_cached=...,
            elapsed_seconds=...,
            wiki_dirty_count=_wiki_dirty_count,
        )
```

- [x] **Step 7: Run full scan tests**

```bash
uv run pytest tests/unit/ tests/integration/test_cli_scan.py -q
```
Expected: all pass, no regressions

- [x] **Step 8: Commit**

```bash
git add libs/core/projects_config.py libs/scanning/scanner.py tests/unit/core/test_projects_config.py
git commit -m "feat(wiki): WikiConfig dirty_threshold/max_workers + ScanResult.wiki_dirty_count"
```

---

## Task 2: Create wiki_worker.py

**Files:**
- Create: `apps/agent/wiki_worker.py`
- Create: `tests/unit/agent/test_wiki_worker.py`

- [x] **Step 1: Write failing tests**

```python
# tests/unit/agent/test_wiki_worker.py
"""Tests for apps/agent/wiki_worker.py — background wiki update task."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from apps.agent.wiki_worker import run_wiki_update
from libs.core.projects_config import WikiConfig
from libs.wiki.state import ensure_wiki_table, mark_dirty


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Minimal project with cache.db, wiki dir, and one dirty module."""
    ctx = tmp_path / ".context"
    ctx.mkdir()
    wiki = ctx / "wiki"
    wiki.mkdir()
    (wiki / "modules").mkdir()

    db = ctx / "cache.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            language TEXT NOT NULL DEFAULT 'python',
            role TEXT NOT NULL DEFAULT 'source',
            is_generated INTEGER NOT NULL DEFAULT 0,
            is_binary INTEGER NOT NULL DEFAULT 0,
            has_secrets INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fq_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            symbol_type TEXT NOT NULL DEFAULT 'function'
        );
        CREATE TABLE IF NOT EXISTS relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            src_ref TEXT NOT NULL,
            dst_ref TEXT NOT NULL,
            relation_type TEXT NOT NULL DEFAULT 'imports'
        );
    """)
    ensure_wiki_table(conn)
    conn.execute(
        "INSERT INTO files (path, content_hash, size_bytes) VALUES (?, ?, ?)",
        ("libs/core/entities.py", "abc123", 500),
    )
    mark_dirty(conn, "libs/core", "hash_old")
    conn.commit()
    conn.close()
    return tmp_path


def test_calls_generate_for_dirty_modules(project: Path) -> None:
    config = WikiConfig(auto_update_after_scan=True, article_max_tokens=500)
    with patch("apps.agent.wiki_worker.generate_wiki_article", return_value="# libs/core\n\n## Purpose\nCore module.\n") as mock_gen:
        with patch("apps.agent.wiki_worker.write_index") as mock_idx:
            run_wiki_update(project, config)
    mock_gen.assert_called_once()
    call_kwargs = mock_gen.call_args.kwargs
    assert call_kwargs["module_path"] == "libs/core"
    assert call_kwargs["project_name"] == project.name
    mock_idx.assert_called_once()


def test_writes_article_file(project: Path) -> None:
    config = WikiConfig()
    article_text = "# libs/core\n\n## Purpose\nCore module.\n"
    with patch("apps.agent.wiki_worker.generate_wiki_article", return_value=article_text):
        with patch("apps.agent.wiki_worker.write_index"):
            run_wiki_update(project, config)
    article_path = project / ".context" / "wiki" / "modules" / "libs-core.md"
    assert article_path.exists()
    assert article_path.read_text() == article_text


def test_continues_on_module_error(project: Path, tmp_path: Path) -> None:
    """Error on one module must not abort others."""
    # Add second dirty module
    db = project / ".context" / "cache.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO files (path, content_hash, size_bytes) VALUES (?, ?, ?)",
        ("libs/scanning/scanner.py", "def456", 800),
    )
    mark_dirty(conn, "libs/scanning", "hash_scan")
    conn.commit()
    conn.close()

    results: list[str] = []
    def fake_generate(**kwargs: object) -> str:
        mod = kwargs["module_path"]
        if mod == "libs/core":
            raise RuntimeError("Claude CLI timeout")
        results.append(str(mod))
        return f"# {mod}\n\n## Purpose\nDoes things.\n"

    config = WikiConfig()
    with patch("apps.agent.wiki_worker.generate_wiki_article", side_effect=fake_generate):
        with patch("apps.agent.wiki_worker.write_index"):
            run_wiki_update(project, config)

    assert "libs/scanning" in results


def test_no_op_when_no_cache_db(tmp_path: Path) -> None:
    """Must return silently if cache.db does not exist."""
    config = WikiConfig()
    with patch("apps.agent.wiki_worker.generate_wiki_article") as mock_gen:
        run_wiki_update(tmp_path, config)
    mock_gen.assert_not_called()


def test_no_op_when_no_dirty_modules(project: Path) -> None:
    """If all modules current, generate must not be called."""
    db = project / ".context" / "cache.db"
    conn = sqlite3.connect(str(db))
    # Mark the module current so it's not dirty
    conn.execute("UPDATE wiki_state SET status = 'current' WHERE module_path = 'libs/core'")
    conn.commit()
    conn.close()

    config = WikiConfig()
    with patch("apps.agent.wiki_worker.generate_wiki_article") as mock_gen:
        with patch("apps.agent.wiki_worker.write_index"):
            run_wiki_update(project, config)
    mock_gen.assert_not_called()


def test_respects_max_modules_per_run(project: Path) -> None:
    """Only max_modules_per_run modules are processed per call."""
    db = project / ".context" / "cache.db"
    conn = sqlite3.connect(str(db))
    for i in range(5):
        conn.execute(
            "INSERT OR IGNORE INTO files (path, content_hash, size_bytes) VALUES (?, ?, ?)",
            (f"libs/mod{i}/a.py", f"hash{i}", 100),
        )
        mark_dirty(conn, f"libs/mod{i}", f"hash{i}")
    conn.commit()
    conn.close()

    config = WikiConfig(max_modules_per_run=2)
    generated: list[str] = []

    def fake_gen(**kwargs: object) -> str:
        generated.append(str(kwargs["module_path"]))
        return "# mod\n\n## Purpose\nDoes things.\n"

    with patch("apps.agent.wiki_worker.generate_wiki_article", side_effect=fake_gen):
        with patch("apps.agent.wiki_worker.write_index"):
            run_wiki_update(project, config)

    assert len(generated) <= 2
```

- [x] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/agent/test_wiki_worker.py -v
```
Expected: `ModuleNotFoundError: No module named 'apps.agent.wiki_worker'`

- [x] **Step 3: Implement wiki_worker.py**

```python
# apps/agent/wiki_worker.py
"""Background wiki update task — runs in ThreadPoolExecutor after daemon scan."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from libs.core.projects_config import WikiConfig
from libs.wiki.generator import generate_wiki_article
from libs.wiki.index_builder import write_index
from libs.wiki.state import ensure_wiki_table, get_dirty_modules, mark_current

logger = logging.getLogger(__name__)


def run_wiki_update(project_path: Path, config: WikiConfig) -> None:
    """Generate wiki articles for all dirty modules.

    Designed to run in a background thread. Errors per-module are caught
    and logged; remaining modules continue. Never raises.
    """
    db_path = project_path / ".context" / "cache.db"
    if not db_path.exists():
        return

    wiki_dir = project_path / ".context" / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "modules").mkdir(parents=True, exist_ok=True)
    project_name = project_path.name

    try:
        conn = sqlite3.connect(str(db_path))
        try:
            ensure_wiki_table(conn)
            conn.commit()
            modules = get_dirty_modules(conn)
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("wiki_worker: cannot read dirty modules %s: %s", project_path, exc)
        return

    if not modules:
        return

    modules = modules[: config.max_modules_per_run]
    logger.info("wiki_worker: updating %d module(s) for %s", len(modules), project_name)

    for mod in modules:
        module_path = mod["module_path"]
        try:
            # Fresh connection per module to avoid DB lock conflicts with daemon
            conn = sqlite3.connect(str(db_path))
            try:
                file_rows = conn.execute(
                    "SELECT path FROM files WHERE path LIKE ? OR path = ?",
                    (f"{module_path}/%", module_path),
                ).fetchall()
                mod_files = [r[0] for r in file_rows]

                sym_rows = conn.execute(
                    "SELECT fq_name FROM symbols WHERE file_path LIKE ? OR file_path = ?",
                    (f"{module_path}/%", module_path),
                ).fetchall()
                mod_symbols = [r[0] for r in sym_rows[:20]]

                dep_rows = conn.execute(
                    "SELECT DISTINCT dst_ref FROM relations "
                    "WHERE src_ref LIKE ? OR src_ref = ?",
                    (f"{module_path}/%", module_path),
                ).fetchall()
                deps = sorted({
                    "/".join(r[0].split("/")[:2]) if "/" in r[0] else r[0]
                    for r in dep_rows
                    if not r[0].startswith(module_path)
                })

                dep_on_rows = conn.execute(
                    "SELECT DISTINCT src_ref FROM relations "
                    "WHERE dst_ref LIKE ? OR dst_ref = ?",
                    (f"{module_path}/%", module_path),
                ).fetchall()
                dependents = sorted({
                    "/".join(r[0].split("/")[:2]) if "/" in r[0] else r[0]
                    for r in dep_on_rows
                    if not r[0].startswith(module_path)
                })
            finally:
                conn.close()

            safe_name = module_path.replace("/", "-").replace("\\", "-")
            article_file = wiki_dir / "modules" / f"{safe_name}.md"
            existing_article = (
                article_file.read_text(encoding="utf-8") if article_file.exists() else ""
            )

            article = generate_wiki_article(
                project_root=project_path,
                project_name=project_name,
                module_path=module_path,
                file_list=mod_files,
                symbols=mod_symbols,
                deps=deps,
                dependents=dependents,
                existing_article=existing_article,
                max_tokens=config.article_max_tokens,
            )
            article_file.write_text(article, encoding="utf-8")

            conn = sqlite3.connect(str(db_path))
            try:
                ensure_wiki_table(conn)
                mark_current(conn, module_path, f"modules/{safe_name}.md", mod["source_hash"])
                conn.commit()
            finally:
                conn.close()

            logger.info("wiki_worker: generated %s / %s", project_name, module_path)

        except Exception as exc:
            logger.warning(
                "wiki_worker: failed %s / %s: %s", project_name, module_path, exc
            )
            continue

    try:
        write_index(wiki_dir, project_name)
    except Exception as exc:
        logger.warning("wiki_worker: write_index failed for %s: %s", project_name, exc)
```

- [x] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/agent/test_wiki_worker.py -v
```
Expected: `6 passed`

- [x] **Step 5: Lint check**

```bash
uv run ruff check apps/agent/wiki_worker.py tests/unit/agent/test_wiki_worker.py
```
Expected: `All checks passed!`

- [x] **Step 6: Commit**

```bash
git add apps/agent/wiki_worker.py tests/unit/agent/test_wiki_worker.py
git commit -m "feat(wiki): background wiki update worker for daemon post-scan hook"
```

---

## Task 3: Wire pool into daemon

**Files:**
- Modify: `apps/agent/daemon.py`
- Test: `tests/integration/test_ctx_watch.py`

- [x] **Step 1: Write failing test**

Add to `tests/integration/test_ctx_watch.py`:

```python
def test_process_pending_events_submits_wiki_task_when_threshold_met(
    tmp_path: Path,
) -> None:
    """Wiki update task is submitted when dirty_count >= threshold."""
    from concurrent.futures import ThreadPoolExecutor
    from unittest.mock import MagicMock, patch

    from apps.agent.daemon import process_pending_events
    from apps.agent.handler import DebounceBuffer
    from libs.core.projects_config import WikiConfig

    buffer = DebounceBuffer(debounce_seconds=0.0)
    buffer.add(tmp_path, "libs/core/a.py", "modified")

    mock_result = MagicMock()
    mock_result.files_reparsed = 1
    mock_result.wiki_dirty_count = 5  # above default threshold of 3

    wiki_config = WikiConfig(auto_update_after_scan=True, dirty_threshold=3)
    pool = ThreadPoolExecutor(max_workers=1)
    submitted: list = []

    try:
        with patch("apps.agent.daemon.scan_project", return_value=mock_result):
            with patch("apps.agent.daemon.run_wiki_update") as mock_worker:
                pool_spy = MagicMock(wraps=pool)
                process_pending_events(
                    buffer,
                    wiki_pool=pool_spy,
                    wiki_config=wiki_config,
                )
                pool_spy.submit.assert_called_once()
                assert pool_spy.submit.call_args.args[1] == tmp_path  # correct project root
    finally:
        pool.shutdown(wait=False)


def test_process_pending_events_no_wiki_task_below_threshold(tmp_path: Path) -> None:
    """Wiki task not submitted when dirty_count < threshold."""
    from concurrent.futures import ThreadPoolExecutor
    from unittest.mock import MagicMock, patch

    from apps.agent.daemon import process_pending_events
    from apps.agent.handler import DebounceBuffer
    from libs.core.projects_config import WikiConfig

    buffer = DebounceBuffer(debounce_seconds=0.0)
    buffer.add(tmp_path, "libs/core/a.py", "modified")

    mock_result = MagicMock()
    mock_result.files_reparsed = 1
    mock_result.wiki_dirty_count = 1  # below threshold of 3

    wiki_config = WikiConfig(auto_update_after_scan=True, dirty_threshold=3)
    pool = ThreadPoolExecutor(max_workers=1)

    try:
        with patch("apps.agent.daemon.scan_project", return_value=mock_result):
            pool_spy = MagicMock(wraps=pool)
            process_pending_events(
                buffer,
                wiki_pool=pool_spy,
                wiki_config=wiki_config,
            )
            pool_spy.submit.assert_not_called()
    finally:
        pool.shutdown(wait=False)
```

- [x] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_ctx_watch.py -k "wiki_task" -v
```
Expected: `TypeError: process_pending_events() got unexpected keyword argument 'wiki_pool'`

- [x] **Step 3: Update daemon.py — imports**

At the top of `apps/agent/daemon.py`, add:
```python
from concurrent.futures import ThreadPoolExecutor

from apps.agent.wiki_worker import run_wiki_update
from libs.core.projects_config import WikiConfig, load_config
```

- [x] **Step 4: Update process_pending_events signature**

Change the function signature to:
```python
def process_pending_events(
    buffer: DebounceBuffer,
    logger: typing.Callable[[str], None] = lambda msg: None,
    *,
    config_path: Path | None = None,
    wiki_pool: ThreadPoolExecutor | None = None,
    wiki_config: WikiConfig | None = None,
) -> dict[Path, int]:
```

- [x] **Step 5: Add wiki submission after scan in process_pending_events**

In the `if modified:` block, after `results[project_root] = result.files_reparsed`, add:
```python
            if modified:
                result = scan_project(project_root, mode="incremental", only=modified)
                results[project_root] = result.files_reparsed
                logger(f"[scan] {project_root.name}: {result.files_reparsed} reparsed")

                # Post-scan wiki hook (best-effort, never blocks daemon)
                if (
                    wiki_pool is not None
                    and wiki_config is not None
                    and result.wiki_dirty_count >= wiki_config.dirty_threshold
                ):
                    wiki_pool.submit(run_wiki_update, project_root, wiki_config)
                    logger(
                        f"[wiki] {project_root.name}: "
                        f"{result.wiki_dirty_count} dirty modules, update queued"
                    )
```

- [x] **Step 6: Update run_daemon to init pool and pass to process_pending_events**

Replace the `run_daemon` body with:
```python
def run_daemon(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> None:
    """Main daemon entry point."""
    buffer = DebounceBuffer(debounce_seconds=2.0)
    observer = Observer()
    stop_event = Event()

    cfg = load_config(config_path)
    wiki_pool = ThreadPoolExecutor(max_workers=cfg.wiki.max_workers)

    def handle_signal(signum: int, frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    projects = list_projects(config_path)
    for entry in projects:
        root = entry.root
        if not root.exists():
            print(f"[warn] project does not exist: {root}", file=sys.stderr)
            continue
        handler = DaemonEventHandler(root, buffer)
        observer.schedule(handler, str(root), recursive=True)
        print(f"[info] watching {root}")

    if not projects:
        print("[warn] no projects registered; daemon will idle")

    observer.start()

    try:
        while not stop_event.is_set():
            time.sleep(buffer.debounce_seconds)
            process_pending_events(
                buffer,
                logger=print,
                config_path=config_path,
                wiki_pool=wiki_pool if cfg.wiki.auto_update_after_scan else None,
                wiki_config=cfg.wiki if cfg.wiki.auto_update_after_scan else None,
            )
    finally:
        observer.stop()
        observer.join()
        wiki_pool.shutdown(wait=False)
```

- [x] **Step 7: Run all daemon + integration tests**

```bash
uv run pytest tests/integration/test_ctx_watch.py tests/unit/agent/ -v
```
Expected: all pass

- [x] **Step 8: Full suite smoke check**

```bash
uv run pytest tests/unit/ -q
```
Expected: all pass, no regressions

- [x] **Step 9: Lint**

```bash
uv run ruff check apps/agent/daemon.py
```
Expected: `All checks passed!`

- [x] **Step 10: Commit**

```bash
git add apps/agent/daemon.py
git commit -m "feat(wiki): wire ThreadPoolExecutor post-scan wiki hook into daemon"
```

---

## Task 4: Enable in config + enable docs

**Files:**
- No code changes — just verify config YAML works end-to-end

- [x] **Step 1: Enable in local config**

Add to `~/.lvdcp/config.yaml` under the `wiki:` section:
```yaml
wiki:
  enabled: true
  auto_update_after_scan: true
  dirty_threshold: 3
  max_workers: 1
  max_modules_per_run: 10
  article_max_tokens: 2000
```

- [x] **Step 2: Verify config loads correctly**

```bash
uv run python -c "
from pathlib import Path
from libs.core.projects_config import load_config
cfg = load_config(Path.home() / '.lvdcp' / 'config.yaml')
print('auto_update_after_scan:', cfg.wiki.auto_update_after_scan)
print('dirty_threshold:', cfg.wiki.dirty_threshold)
print('max_workers:', cfg.wiki.max_workers)
"
```
Expected:
```
auto_update_after_scan: True
dirty_threshold: 3
max_workers: 1
```

- [x] **Step 3: Commit config (if tracked)**

```bash
git add ~/.lvdcp/config.yaml 2>/dev/null || true
# Note: personal config is not in repo — no commit needed
```

---

## Task 5: Final verification

- [x] **Step 1: Run full test suite**

```bash
uv run pytest tests/unit/ tests/integration/ -q --ignore=tests/eval
```
Expected: all pass, 0 failures

- [x] **Step 2: Lint full project**

```bash
uv run ruff check libs/scanning/scanner.py libs/core/projects_config.py apps/agent/
```
Expected: `All checks passed!`

- [x] **Step 3: Typecheck changed files**

```bash
uv run mypy libs/scanning/scanner.py libs/core/projects_config.py apps/agent/daemon.py apps/agent/wiki_worker.py --ignore-missing-imports
```
Expected: `Success: no issues found`

- [x] **Step 4: Final commit**

```bash
git add libs/scanning/scanner.py libs/core/projects_config.py
git commit -m "feat(wiki): post-scan wiki hook — daemon auto-generates articles when dirty_count >= threshold

- WikiConfig: dirty_threshold (default 3), max_workers (default 1)
- ScanResult: wiki_dirty_count field
- apps/agent/wiki_worker.py: background task, sqlite3 direct, per-module error isolation
- daemon: ThreadPoolExecutor, submits task post-scan when threshold met

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

- [x] **Step 5: Push**

```bash
git push origin main
```
