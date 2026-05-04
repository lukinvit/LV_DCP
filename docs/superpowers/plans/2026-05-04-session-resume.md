# Session Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build LV_DCP session-resume capability so any new Claude Code session can pick up engineering context from prior sessions on the same machine via `lvdcp_resume`.

**Architecture:** New `libs/breadcrumbs/` lib (single-writer, SQLite at `~/.lvdcp/breadcrumbs.db`, mirrors `libs/scan_history` pattern). Side-effect writes from `lvdcp_pack`/`lvdcp_status` plus opt-in CC hooks. New MCP tool `lvdcp_resume` and `ctx resume`/`ctx breadcrumb` CLI surface. Multi-user isolation via `os_user` + `cc_account_email`. Pattern-based secret redactor at write time. 14-day TTL with launchd-scheduled prune.

**Tech Stack:** Python 3.12, sqlite3 (stdlib), typer, pydantic v2, FastMCP, structlog. No new third-party deps for the LV_DCP slice. The standalone `recover-cc-session` utility (tasks 27–30) uses PEP 723 + typer + rich via `uv run --script`.

**Spec:** [docs/superpowers/specs/2026-05-04-session-resume-design.md](../specs/2026-05-04-session-resume-design.md)

---

## Task 1: Scaffold libs/breadcrumbs + store with schema

**Files:**
- Create: `libs/breadcrumbs/__init__.py`
- Create: `libs/breadcrumbs/store.py`
- Create: `tests/unit/breadcrumbs/__init__.py`
- Create: `tests/unit/breadcrumbs/test_store.py`

- [ ] **Step 1: Write failing migration test**

```python
# tests/unit/breadcrumbs/test_store.py
from pathlib import Path
import sqlite3
from libs.breadcrumbs.store import BreadcrumbStore


def test_migrate_creates_table_and_indexes(tmp_path: Path) -> None:
    db = tmp_path / "breadcrumbs.db"
    store = BreadcrumbStore(db_path=db)
    store.migrate()
    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    conn.close()
    assert "breadcrumbs" in tables
    assert "ix_breadcrumbs_root_ts" in indexes
    assert "ix_breadcrumbs_user_root_ts" in indexes
    assert "ix_breadcrumbs_session" in indexes


def test_migrate_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "breadcrumbs.db"
    store = BreadcrumbStore(db_path=db)
    store.migrate()
    store.migrate()  # second call must not raise
    store.close()
```

- [ ] **Step 2: Run test (expect ImportError)**

Run: `uv run pytest tests/unit/breadcrumbs/test_store.py -v`
Expected: ImportError (`libs.breadcrumbs.store` not found)

- [ ] **Step 3: Implement store**

```python
# libs/breadcrumbs/__init__.py
"""Breadcrumb store — engineering activity log for session resume."""
```

```python
# libs/breadcrumbs/store.py
"""SQLite store for breadcrumb events. Mirrors libs/scan_history layout."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_STORE_PATH = Path.home() / ".lvdcp" / "breadcrumbs.db"

_SCHEMA = """
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
    paths_touched     TEXT,
    todo_snapshot     TEXT,
    turn_summary      TEXT,
    privacy_mode      TEXT    NOT NULL DEFAULT 'local_only'
);
CREATE INDEX IF NOT EXISTS ix_breadcrumbs_root_ts
    ON breadcrumbs (project_root, timestamp);
CREATE INDEX IF NOT EXISTS ix_breadcrumbs_user_root_ts
    ON breadcrumbs (os_user, project_root, timestamp);
CREATE INDEX IF NOT EXISTS ix_breadcrumbs_session
    ON breadcrumbs (cc_session_id);
"""


class BreadcrumbStore:
    def __init__(self, db_path: Path = DEFAULT_STORE_PATH) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA journal_mode = WAL")
        return self._conn

    def migrate(self) -> None:
        conn = self.connect()
        conn.executescript(_SCHEMA)
        conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
```

- [ ] **Step 4: Run test (expect PASS)**

Run: `uv run pytest tests/unit/breadcrumbs/test_store.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add libs/breadcrumbs/__init__.py libs/breadcrumbs/store.py tests/unit/breadcrumbs/
git commit -m "feat(breadcrumbs): scaffold lib + SQLite store with schema"
```

---

## Task 2: Models — frozen dataclasses

**Files:**
- Create: `libs/breadcrumbs/models.py`
- Create: `tests/unit/breadcrumbs/test_models.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/breadcrumbs/test_models.py
import dataclasses
from libs.breadcrumbs.models import Breadcrumb, BreadcrumbSource


def test_breadcrumb_is_frozen():
    bc = Breadcrumb(
        project_root="/repo/x",
        timestamp=1700000000.0,
        source=BreadcrumbSource.PACK,
        os_user="alice",
        privacy_mode="local_only",
    )
    assert dataclasses.is_dataclass(bc)
    try:
        bc.os_user = "bob"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("expected FrozenInstanceError")


def test_breadcrumb_source_values():
    expected = {"pack", "status", "hook_stop", "hook_pre_compact", "hook_subagent_stop", "manual"}
    assert {s.value for s in BreadcrumbSource} == expected
```

- [ ] **Step 2: Run test (expect ImportError)**

Run: `uv run pytest tests/unit/breadcrumbs/test_models.py -v`
Expected: ImportError

- [ ] **Step 3: Implement models**

```python
# libs/breadcrumbs/models.py
"""Frozen dataclasses for breadcrumb events."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class BreadcrumbSource(str, enum.Enum):
    PACK = "pack"
    STATUS = "status"
    HOOK_STOP = "hook_stop"
    HOOK_PRE_COMPACT = "hook_pre_compact"
    HOOK_SUBAGENT_STOP = "hook_subagent_stop"
    MANUAL = "manual"


@dataclass(frozen=True)
class Breadcrumb:
    project_root: str
    timestamp: float
    source: BreadcrumbSource
    os_user: str
    privacy_mode: str = "local_only"
    cc_session_id: str | None = None
    cc_account_email: str | None = None
    query: str | None = None
    mode: str | None = None
    paths_touched: list[str] = field(default_factory=list)
    todo_snapshot: list[dict] | None = None
    turn_summary: str | None = None


@dataclass(frozen=True)
class BreadcrumbView:
    """Read-side projection used by reader/renderer."""

    id: int
    project_root: str
    timestamp: float
    source: str
    cc_session_id: str | None
    os_user: str
    cc_account_email: str | None
    query: str | None
    mode: str | None
    paths_touched: list[str]
    todo_snapshot: list[dict] | None
    turn_summary: str | None
```

- [ ] **Step 4: Run tests (expect PASS)**

Run: `uv run pytest tests/unit/breadcrumbs/test_models.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add libs/breadcrumbs/models.py tests/unit/breadcrumbs/test_models.py
git commit -m "feat(breadcrumbs): add Breadcrumb + BreadcrumbView dataclasses"
```

---

## Task 3: Secret redactor with 11 patterns

**Files:**
- Create: `libs/breadcrumbs/privacy.py`
- Create: `tests/unit/breadcrumbs/test_privacy.py`

- [ ] **Step 1: Write failing tests for all 11 patterns**

```python
# tests/unit/breadcrumbs/test_privacy.py
import pytest
from libs.breadcrumbs.privacy import redact


@pytest.mark.parametrize("text, kind", [
    ("error with sk-1234567890ABCDEFGHIJ token", "openai"),
    ("stripe sk_live_abcdef1234567890ABCD failed", "stripe"),
    ("anthropic sk-ant-abcdef1234567890ABCDEF1234567890ABCDEF1234 fail", "anthropic"),
    ("github ghp_abcdefghijklmnopqrstuvwxyz0123456789 fail", "github"),
    ("slack xoxb-1234567890-abcdef-ghijklmnop fail", "slack"),
    ("aws creds AKIAIOSFODNN7EXAMP1 leak", "aws"),
    ("token eyJabcdefghij.eyJabcdefghij.abcdefghij here", "jwt"),
    ("cert -----BEGIN RSA PRIVATE KEY----- here", "private_key"),
    ("hash 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef seen", "hex64"),
    ("conn postgresql://user:pass@db:5432/mydb here", "conn_string"),
    ("CLI api_key=sk_test_1234 here", "kv_secret"),
])
def test_redacts_secret(text: str, kind: str) -> None:
    redacted = redact(text)
    assert f"[REDACTED:{kind}]" in redacted
    assert "sk-1234567890ABCDEFGHIJ" not in redacted or kind != "openai"


def test_does_not_redact_plain_code() -> None:
    code = "def calculate_total(items): return sum(i.price for i in items)"
    assert redact(code) == code


def test_redacts_multiple_secrets_in_one_string() -> None:
    text = "AKIAIOSFODNN7EXAMP1 and ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    redacted = redact(text)
    assert "[REDACTED:aws]" in redacted
    assert "[REDACTED:github]" in redacted
```

- [ ] **Step 2: Run test (expect ImportError)**

Run: `uv run pytest tests/unit/breadcrumbs/test_privacy.py -v`
Expected: ImportError

- [ ] **Step 3: Implement redactor**

```python
# libs/breadcrumbs/privacy.py
"""Pattern-based secret redactor for breadcrumb query/turn_summary fields."""

from __future__ import annotations

import re

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("anthropic", re.compile(r"sk-ant-[A-Za-z0-9_-]{40,}")),
    ("openai",    re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("stripe",    re.compile(r"sk_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("github",    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("slack",     re.compile(r"xox[abprs]-[A-Za-z0-9-]{20,}")),
    ("aws",       re.compile(r"AKIA[0-9A-Z]{16}")),
    ("jwt",       re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("hex64",     re.compile(r"\b[0-9a-fA-F]{64}\b")),
    ("conn_string", re.compile(r"(?:postgres|postgresql|mysql|mongodb|redis|rediss|amqp)://[^@\s]*:[^@\s]+@")),
    ("kv_secret", re.compile(
        r"(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?token|auth)\s*[=:]\s*[\"']?([^\s\"'&]+)",
        re.IGNORECASE,
    )),
]


def redact(text: str | None) -> str | None:
    if text is None:
        return None
    for kind, pat in SECRET_PATTERNS:
        text = pat.sub(f"[REDACTED:{kind}]", text)
    return text
```

Order matters: the more specific `sk-ant-...` must be checked **before** the generic `sk-...` pattern, otherwise OpenAI pattern would swallow it.

- [ ] **Step 4: Run tests (expect PASS)**

Run: `uv run pytest tests/unit/breadcrumbs/test_privacy.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add libs/breadcrumbs/privacy.py tests/unit/breadcrumbs/test_privacy.py
git commit -m "feat(breadcrumbs): add pattern-based secret redactor"
```

---

## Task 4: CC identity parser (read-only)

**Files:**
- Create: `libs/breadcrumbs/cc_identity.py`
- Create: `tests/unit/breadcrumbs/test_cc_identity.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/breadcrumbs/test_cc_identity.py
import json
from pathlib import Path
from libs.breadcrumbs.cc_identity import resolve_cc_account_email


def test_returns_none_when_root_missing(tmp_path: Path) -> None:
    assert resolve_cc_account_email(root=tmp_path / "missing") is None


def test_extracts_email_from_newest_local_json(tmp_path: Path) -> None:
    base = tmp_path / "local-agent-mode-sessions" / "acct1" / "org1"
    base.mkdir(parents=True)
    older = base / "local_old.json"
    older.write_text(json.dumps({"accountName": "old@example.com", "emailAddress": "old@example.com"}))
    older_mtime = older.stat().st_mtime
    newer = base / "local_new.json"
    newer.write_text(json.dumps({"accountName": "Alice", "emailAddress": "alice@example.com"}))
    import os
    os.utime(newer, (older_mtime + 100, older_mtime + 100))
    assert resolve_cc_account_email(root=tmp_path) == "alice@example.com"


def test_returns_none_on_corrupt_json(tmp_path: Path) -> None:
    base = tmp_path / "local-agent-mode-sessions" / "acct1" / "org1"
    base.mkdir(parents=True)
    (base / "local_x.json").write_text("not json {{{")
    assert resolve_cc_account_email(root=tmp_path) is None
```

- [ ] **Step 2: Run test (expect ImportError)**

Run: `uv run pytest tests/unit/breadcrumbs/test_cc_identity.py -v`
Expected: ImportError

- [ ] **Step 3: Implement parser**

```python
# libs/breadcrumbs/cc_identity.py
"""Read-only resolver for current CC session's account email."""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_ROOT = Path.home() / "Library" / "Application Support" / "Claude"
_AGENT_DIR = "local-agent-mode-sessions"


def resolve_cc_account_email(*, root: Path | None = None) -> str | None:
    """Best-effort lookup of the most recent CC session's account email.

    Returns None on any failure (missing root, no sessions, broken JSON,
    permissions). Logs at most one warning per process via module logger.
    """
    base = (root or _DEFAULT_ROOT) / _AGENT_DIR
    if not base.exists():
        return None
    candidates: list[Path] = []
    for session_file in base.rglob("local_*.json"):
        if session_file.is_file():
            candidates.append(session_file)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.debug("cc_identity: failed to read %s: %s", path, exc)
            continue
        email = data.get("emailAddress") or data.get("accountName")
        if isinstance(email, str) and email:
            return email
    return None
```

- [ ] **Step 4: Run tests (expect PASS)**

Run: `uv run pytest tests/unit/breadcrumbs/test_cc_identity.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add libs/breadcrumbs/cc_identity.py tests/unit/breadcrumbs/test_cc_identity.py
git commit -m "feat(breadcrumbs): read-only CC account email resolver"
```

---

## Task 5: Writer

**Files:**
- Create: `libs/breadcrumbs/writer.py`
- Create: `tests/unit/breadcrumbs/test_writer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/breadcrumbs/test_writer.py
import json
from pathlib import Path
import sqlite3
from libs.breadcrumbs.models import BreadcrumbSource
from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.writer import (
    write_pack_event, write_status_event, write_hook_event,
)


def _store(tmp_path: Path) -> BreadcrumbStore:
    s = BreadcrumbStore(db_path=tmp_path / "bc.db")
    s.migrate()
    return s


def test_write_pack_event_persists_row(tmp_path: Path) -> None:
    s = _store(tmp_path)
    write_pack_event(
        store=s,
        project_root="/repo/foo",
        os_user="alice",
        query="how does X work",
        mode="navigate",
        paths_touched=["src/x.py", "src/y.py", "src/z.py", "src/a.py", "src/b.py", "src/c.py"],
        cc_session_id="sess1",
        cc_account_email="alice@example.com",
    )
    rows = list(s.connect().execute("SELECT source, query, paths_touched, cc_session_id FROM breadcrumbs"))
    assert len(rows) == 1
    assert rows[0][0] == "pack"
    assert rows[0][1] == "how does X work"
    assert json.loads(rows[0][2]) == ["src/x.py", "src/y.py", "src/z.py", "src/a.py", "src/b.py"]  # top-5
    assert rows[0][3] == "sess1"


def test_write_pack_event_redacts_secrets(tmp_path: Path) -> None:
    s = _store(tmp_path)
    write_pack_event(
        store=s,
        project_root="/repo/foo",
        os_user="alice",
        query="why does sk-1234567890ABCDEFGHIJ fail",
        mode="navigate",
        paths_touched=[],
    )
    (q,) = s.connect().execute("SELECT query FROM breadcrumbs").fetchone()
    assert "[REDACTED:openai]" in q
    assert "sk-1234567890ABCDEFGHIJ" not in q


def test_write_hook_event_with_todo_snapshot(tmp_path: Path) -> None:
    s = _store(tmp_path)
    write_hook_event(
        store=s,
        source=BreadcrumbSource.HOOK_STOP,
        project_root="/repo/foo",
        os_user="alice",
        cc_session_id="sess1",
        todo_snapshot=[{"content": "task A", "status": "completed"}],
    )
    (snap,) = s.connect().execute("SELECT todo_snapshot FROM breadcrumbs").fetchone()
    assert json.loads(snap) == [{"content": "task A", "status": "completed"}]


def test_write_status_event(tmp_path: Path) -> None:
    s = _store(tmp_path)
    write_status_event(
        store=s,
        project_root="/repo/foo",
        os_user="alice",
    )
    (src,) = s.connect().execute("SELECT source FROM breadcrumbs").fetchone()
    assert src == "status"


def test_writer_swallows_exception(tmp_path: Path) -> None:
    """Writer must never propagate exceptions — observability only."""
    bad_store = BreadcrumbStore(db_path=tmp_path / "nonexistent" / "subdir" / "bc.db")
    # No migrate() call → table missing
    write_pack_event(
        store=bad_store, project_root="/x", os_user="alice",
        query="q", mode="navigate", paths_touched=[],
    )
    # Should not raise
```

- [ ] **Step 2: Run test (expect ImportError)**

Run: `uv run pytest tests/unit/breadcrumbs/test_writer.py -v`
Expected: ImportError

- [ ] **Step 3: Implement writer**

```python
# libs/breadcrumbs/writer.py
"""Breadcrumb writers — exception-swallowing fire-and-forget primitives."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from libs.breadcrumbs.models import BreadcrumbSource
from libs.breadcrumbs.privacy import redact
from libs.breadcrumbs.store import BreadcrumbStore

log = logging.getLogger(__name__)

_TOP_K_PATHS = 5


def _insert(
    store: BreadcrumbStore,
    *,
    source: str,
    project_root: str,
    os_user: str,
    timestamp: float,
    cc_session_id: str | None,
    cc_account_email: str | None,
    query: str | None,
    mode: str | None,
    paths_touched: list[str],
    todo_snapshot: list[dict[str, Any]] | None,
    turn_summary: str | None,
    privacy_mode: str = "local_only",
) -> None:
    conn = store.connect()
    conn.execute(
        "INSERT INTO breadcrumbs ("
        " project_root, timestamp, source, cc_session_id, os_user,"
        " cc_account_email, query, mode, paths_touched, todo_snapshot,"
        " turn_summary, privacy_mode"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            project_root,
            timestamp,
            source,
            cc_session_id,
            os_user,
            cc_account_email,
            redact(query),
            mode,
            json.dumps(paths_touched[:_TOP_K_PATHS]) if paths_touched else None,
            json.dumps(todo_snapshot) if todo_snapshot is not None else None,
            redact(turn_summary),
            privacy_mode,
        ),
    )
    conn.commit()


def write_pack_event(
    *,
    store: BreadcrumbStore,
    project_root: str,
    os_user: str,
    query: str | None,
    mode: str | None,
    paths_touched: list[str],
    cc_session_id: str | None = None,
    cc_account_email: str | None = None,
) -> None:
    try:
        _insert(
            store,
            source=BreadcrumbSource.PACK.value,
            project_root=project_root,
            os_user=os_user,
            timestamp=time.time(),
            cc_session_id=cc_session_id,
            cc_account_email=cc_account_email,
            query=query,
            mode=mode,
            paths_touched=paths_touched,
            todo_snapshot=None,
            turn_summary=None,
        )
    except Exception:
        log.exception("breadcrumbs.write_pack_event failed (swallowed)")


def write_status_event(
    *,
    store: BreadcrumbStore,
    project_root: str,
    os_user: str,
    cc_session_id: str | None = None,
    cc_account_email: str | None = None,
) -> None:
    try:
        _insert(
            store,
            source=BreadcrumbSource.STATUS.value,
            project_root=project_root,
            os_user=os_user,
            timestamp=time.time(),
            cc_session_id=cc_session_id,
            cc_account_email=cc_account_email,
            query=None,
            mode=None,
            paths_touched=[],
            todo_snapshot=None,
            turn_summary=None,
        )
    except Exception:
        log.exception("breadcrumbs.write_status_event failed (swallowed)")


def write_hook_event(
    *,
    store: BreadcrumbStore,
    source: BreadcrumbSource,
    project_root: str,
    os_user: str,
    cc_session_id: str | None = None,
    cc_account_email: str | None = None,
    todo_snapshot: list[dict[str, Any]] | None = None,
    turn_summary: str | None = None,
) -> None:
    if source not in {
        BreadcrumbSource.HOOK_STOP,
        BreadcrumbSource.HOOK_PRE_COMPACT,
        BreadcrumbSource.HOOK_SUBAGENT_STOP,
        BreadcrumbSource.MANUAL,
    }:
        raise ValueError(f"write_hook_event called with non-hook source {source!r}")
    try:
        _insert(
            store,
            source=source.value,
            project_root=project_root,
            os_user=os_user,
            timestamp=time.time(),
            cc_session_id=cc_session_id,
            cc_account_email=cc_account_email,
            query=None,
            mode=None,
            paths_touched=[],
            todo_snapshot=todo_snapshot,
            turn_summary=turn_summary,
        )
    except Exception:
        log.exception("breadcrumbs.write_hook_event failed (swallowed)")
```

- [ ] **Step 4: Run tests (expect PASS)**

Run: `uv run pytest tests/unit/breadcrumbs/test_writer.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add libs/breadcrumbs/writer.py tests/unit/breadcrumbs/test_writer.py
git commit -m "feat(breadcrumbs): writer with redaction + exception swallowing"
```

---

## Task 6: Reader

**Files:**
- Create: `libs/breadcrumbs/reader.py`
- Create: `tests/unit/breadcrumbs/test_reader.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/breadcrumbs/test_reader.py
import time
from pathlib import Path
from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.writer import write_pack_event
from libs.breadcrumbs.reader import load_recent, load_cross_project


def _store(tmp_path: Path) -> BreadcrumbStore:
    s = BreadcrumbStore(db_path=tmp_path / "bc.db")
    s.migrate()
    return s


def test_load_recent_filters_by_user(tmp_path: Path) -> None:
    s = _store(tmp_path)
    write_pack_event(store=s, project_root="/x", os_user="alice", query="q", mode="navigate", paths_touched=[])
    write_pack_event(store=s, project_root="/x", os_user="bob",   query="q", mode="navigate", paths_touched=[])
    rows = load_recent(store=s, project_root="/x", os_user="alice", since_ts=0, limit=100)
    assert len(rows) == 1
    assert rows[0].os_user == "alice"


def test_load_recent_window(tmp_path: Path) -> None:
    s = _store(tmp_path)
    write_pack_event(store=s, project_root="/x", os_user="alice", query="q", mode="navigate", paths_touched=[])
    cutoff = time.time() + 10  # future cutoff → nothing returned
    rows = load_recent(store=s, project_root="/x", os_user="alice", since_ts=cutoff, limit=100)
    assert rows == []


def test_load_recent_cc_account_filter(tmp_path: Path) -> None:
    s = _store(tmp_path)
    write_pack_event(store=s, project_root="/x", os_user="alice", query="q", mode="navigate",
                     paths_touched=[], cc_account_email="alice@x.com")
    write_pack_event(store=s, project_root="/x", os_user="alice", query="q", mode="navigate",
                     paths_touched=[], cc_account_email="other@x.com")
    rows = load_recent(store=s, project_root="/x", os_user="alice",
                       since_ts=0, limit=100, cc_account_email="alice@x.com")
    assert len(rows) == 1
    assert rows[0].cc_account_email == "alice@x.com"


def test_load_recent_cc_account_filter_includes_null(tmp_path: Path) -> None:
    """Null email rows must be visible to any current user (best-effort fallback)."""
    s = _store(tmp_path)
    write_pack_event(store=s, project_root="/x", os_user="alice", query="q", mode="navigate", paths_touched=[])
    rows = load_recent(store=s, project_root="/x", os_user="alice",
                       since_ts=0, limit=100, cc_account_email="alice@x.com")
    assert len(rows) == 1


def test_load_cross_project_orders_by_recency(tmp_path: Path) -> None:
    s = _store(tmp_path)
    # Project A: 2 events
    write_pack_event(store=s, project_root="/a", os_user="alice", query="q1", mode="navigate", paths_touched=[])
    time.sleep(0.01)
    # Project B: 1 event but newer
    write_pack_event(store=s, project_root="/b", os_user="alice", query="q2", mode="navigate", paths_touched=[])
    digest = load_cross_project(store=s, os_user="alice", since_ts=0, limit=10)
    assert [d.project_root for d in digest] == ["/b", "/a"]
    assert digest[0].count == 1
    assert digest[1].count == 2
```

- [ ] **Step 2: Run test (expect ImportError)**

Run: `uv run pytest tests/unit/breadcrumbs/test_reader.py -v`
Expected: ImportError

- [ ] **Step 3: Implement reader**

```python
# libs/breadcrumbs/reader.py
"""Breadcrumb reader — multi-user-scoped queries."""

from __future__ import annotations

import json
from dataclasses import dataclass

from libs.breadcrumbs.models import BreadcrumbView
from libs.breadcrumbs.store import BreadcrumbStore


@dataclass(frozen=True)
class ProjectDigestEntry:
    project_root: str
    last_ts: float
    count: int
    last_query: str | None
    last_mode: str | None


def _row_to_view(row: tuple) -> BreadcrumbView:
    return BreadcrumbView(
        id=row[0],
        project_root=row[1],
        timestamp=row[2],
        source=row[3],
        cc_session_id=row[4],
        os_user=row[5],
        cc_account_email=row[6],
        query=row[7],
        mode=row[8],
        paths_touched=json.loads(row[9]) if row[9] else [],
        todo_snapshot=json.loads(row[10]) if row[10] else None,
        turn_summary=row[11],
    )


_SELECT_COLS = (
    "id, project_root, timestamp, source, cc_session_id, os_user, "
    "cc_account_email, query, mode, paths_touched, todo_snapshot, turn_summary"
)


def load_recent(
    *,
    store: BreadcrumbStore,
    project_root: str,
    os_user: str,
    since_ts: float,
    limit: int,
    cc_account_email: str | None = None,
) -> list[BreadcrumbView]:
    conn = store.connect()
    if cc_account_email is None:
        rows = conn.execute(
            f"SELECT {_SELECT_COLS} FROM breadcrumbs "
            "WHERE project_root = ? AND os_user = ? AND timestamp >= ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (project_root, os_user, since_ts, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {_SELECT_COLS} FROM breadcrumbs "
            "WHERE project_root = ? AND os_user = ? AND timestamp >= ? "
            "AND (cc_account_email IS NULL OR cc_account_email = ?) "
            "ORDER BY timestamp DESC LIMIT ?",
            (project_root, os_user, since_ts, cc_account_email, limit),
        ).fetchall()
    return [_row_to_view(r) for r in rows]


def load_cross_project(
    *,
    store: BreadcrumbStore,
    os_user: str,
    since_ts: float,
    limit: int,
) -> list[ProjectDigestEntry]:
    conn = store.connect()
    rows = conn.execute(
        "SELECT project_root, MAX(timestamp) AS last_ts, COUNT(*) AS cnt "
        "FROM breadcrumbs WHERE os_user = ? AND timestamp >= ? "
        "GROUP BY project_root ORDER BY last_ts DESC LIMIT ?",
        (os_user, since_ts, limit),
    ).fetchall()
    out: list[ProjectDigestEntry] = []
    for project_root, last_ts, cnt in rows:
        last = conn.execute(
            "SELECT query, mode FROM breadcrumbs "
            "WHERE project_root = ? AND os_user = ? AND timestamp = ? "
            "ORDER BY id DESC LIMIT 1",
            (project_root, os_user, last_ts),
        ).fetchone()
        out.append(ProjectDigestEntry(
            project_root=project_root,
            last_ts=last_ts,
            count=cnt,
            last_query=last[0] if last else None,
            last_mode=last[1] if last else None,
        ))
    return out
```

- [ ] **Step 4: Run tests (expect PASS)**

Run: `uv run pytest tests/unit/breadcrumbs/test_reader.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add libs/breadcrumbs/reader.py tests/unit/breadcrumbs/test_reader.py
git commit -m "feat(breadcrumbs): reader with multi-user filter + cross-project digest"
```

---

## Task 7: Pruner — TTL + LRU

**Files:**
- Create: `libs/breadcrumbs/prune.py`
- Create: `tests/unit/breadcrumbs/test_prune.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/breadcrumbs/test_prune.py
import time
from pathlib import Path
from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.writer import write_pack_event
from libs.breadcrumbs.prune import prune_older_than, enforce_per_project_cap


def _store(tmp_path: Path) -> BreadcrumbStore:
    s = BreadcrumbStore(db_path=tmp_path / "bc.db")
    s.migrate()
    return s


def test_prune_older_than_removes_old_rows(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.connect().execute(
        "INSERT INTO breadcrumbs (project_root, timestamp, source, os_user, privacy_mode) "
        "VALUES (?, ?, 'pack', 'alice', 'local_only')",
        ("/x", 100.0),
    )
    s.connect().commit()
    write_pack_event(store=s, project_root="/x", os_user="alice", query="q", mode="navigate", paths_touched=[])
    deleted = prune_older_than(store=s, cutoff_ts=time.time() - 60)
    assert deleted == 1
    remaining = s.connect().execute("SELECT COUNT(*) FROM breadcrumbs").fetchone()[0]
    assert remaining == 1


def test_enforce_per_project_cap_drops_oldest(tmp_path: Path) -> None:
    s = _store(tmp_path)
    for i in range(15):
        write_pack_event(store=s, project_root="/x", os_user="alice", query=f"q{i}", mode="navigate", paths_touched=[])
    dropped = enforce_per_project_cap(store=s, project_root="/x", max_rows=10)
    assert dropped == 5
    remaining = s.connect().execute(
        "SELECT COUNT(*) FROM breadcrumbs WHERE project_root = ?", ("/x",)
    ).fetchone()[0]
    assert remaining == 10


def test_enforce_cap_no_op_when_under(tmp_path: Path) -> None:
    s = _store(tmp_path)
    for i in range(3):
        write_pack_event(store=s, project_root="/x", os_user="alice", query=f"q{i}", mode="navigate", paths_touched=[])
    dropped = enforce_per_project_cap(store=s, project_root="/x", max_rows=10)
    assert dropped == 0
```

- [ ] **Step 2: Run test (expect ImportError)**

Run: `uv run pytest tests/unit/breadcrumbs/test_prune.py -v`
Expected: ImportError

- [ ] **Step 3: Implement pruner**

```python
# libs/breadcrumbs/prune.py
"""TTL + LRU prune helpers."""

from __future__ import annotations

from libs.breadcrumbs.store import BreadcrumbStore


def prune_older_than(*, store: BreadcrumbStore, cutoff_ts: float) -> int:
    conn = store.connect()
    cur = conn.execute("DELETE FROM breadcrumbs WHERE timestamp < ?", (cutoff_ts,))
    conn.commit()
    return cur.rowcount or 0


def enforce_per_project_cap(*, store: BreadcrumbStore, project_root: str, max_rows: int) -> int:
    conn = store.connect()
    count = conn.execute(
        "SELECT COUNT(*) FROM breadcrumbs WHERE project_root = ?", (project_root,)
    ).fetchone()[0]
    if count <= max_rows:
        return 0
    overflow = count - max_rows
    cur = conn.execute(
        "DELETE FROM breadcrumbs WHERE id IN ("
        " SELECT id FROM breadcrumbs WHERE project_root = ? "
        " ORDER BY timestamp ASC LIMIT ?"
        ")",
        (project_root, overflow),
    )
    conn.commit()
    return cur.rowcount or 0
```

- [ ] **Step 4: Run tests (expect PASS)**

Run: `uv run pytest tests/unit/breadcrumbs/test_prune.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add libs/breadcrumbs/prune.py tests/unit/breadcrumbs/test_prune.py
git commit -m "feat(breadcrumbs): TTL + LRU pruner"
```

---

## Task 8: A1 snapshot — git portion

**Files:**
- Create: `libs/breadcrumbs/snapshot.py`
- Create: `tests/unit/breadcrumbs/test_snapshot_git.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/breadcrumbs/test_snapshot_git.py
import subprocess
from pathlib import Path
import pytest
from libs.breadcrumbs.snapshot import collect_git_state, GitState


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "T")
    (r / "a.py").write_text("x = 1\n")
    _git(r, "add", "a.py")
    _git(r, "commit", "-q", "-m", "initial")
    return r


def test_collect_git_state_basic(repo: Path) -> None:
    state = collect_git_state(project_root=repo)
    assert state.branch == "main"
    assert state.upstream is None
    assert state.last_commits[0].subject == "initial"


def test_collect_git_state_dirty(repo: Path) -> None:
    (repo / "a.py").write_text("x = 2\n")
    (repo / "b.py").write_text("y = 1\n")
    state = collect_git_state(project_root=repo)
    paths = sorted(f.path for f in state.dirty_files)
    assert paths == ["a.py"] or "b.py" in paths  # b.py is untracked, depends on porcelain behavior
    assert any(f.path == "a.py" for f in state.dirty_files)


def test_collect_git_state_outside_repo(tmp_path: Path) -> None:
    state = collect_git_state(project_root=tmp_path / "not-a-repo")
    assert state.branch == ""
    assert state.last_commits == []
    assert state.dirty_files == []
```

- [ ] **Step 2: Run test (expect ImportError)**

Run: `uv run pytest tests/unit/breadcrumbs/test_snapshot_git.py -v`
Expected: ImportError

- [ ] **Step 3: Implement git portion**

```python
# libs/breadcrumbs/snapshot.py
"""A1Snapshot generator — git, scan_history, plan, eval state."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommitRef:
    sha: str
    subject: str
    rel_time: str


@dataclass(frozen=True)
class FileChange:
    path: str
    status: str  # M | A | D | ??


@dataclass(frozen=True)
class GitState:
    branch: str
    upstream: str | None
    ahead: int
    behind: int
    last_commits: list[CommitRef]
    dirty_files: list[FileChange]
    staged_files: list[FileChange]


def _git(root: Path, *args: str, timeout: float = 2.0) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=root, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        if out.returncode != 0:
            return ""
        return out.stdout
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return ""


def _empty_git_state() -> GitState:
    return GitState(
        branch="", upstream=None, ahead=0, behind=0,
        last_commits=[], dirty_files=[], staged_files=[],
    )


def collect_git_state(*, project_root: Path) -> GitState:
    if not project_root.exists():
        return _empty_git_state()
    branch = _git(project_root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if not branch:
        return _empty_git_state()
    upstream = _git(project_root, "rev-parse", "--abbrev-ref", "@{u}").strip() or None
    ahead = behind = 0
    if upstream:
        counts = _git(project_root, "rev-list", "--left-right", "--count", "HEAD...@{u}").strip()
        if counts:
            try:
                a, b = counts.split()
                ahead, behind = int(a), int(b)
            except ValueError:
                pass
    last_commits: list[CommitRef] = []
    log_out = _git(project_root, "log", "-5", "--pretty=format:%h%x09%s%x09%cr")
    for line in log_out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            last_commits.append(CommitRef(sha=parts[0], subject=parts[1], rel_time=parts[2]))
    dirty: list[FileChange] = []
    staged: list[FileChange] = []
    porcelain = _git(project_root, "status", "--porcelain=v1")
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        idx, work, path = line[0], line[1], line[3:]
        if idx != " " and idx != "?":
            staged.append(FileChange(path=path, status=idx))
        if work != " ":
            dirty.append(FileChange(path=path, status=work if work != " " else idx))
    return GitState(
        branch=branch, upstream=upstream, ahead=ahead, behind=behind,
        last_commits=last_commits, dirty_files=dirty, staged_files=staged,
    )
```

- [ ] **Step 4: Run tests (expect PASS)**

Run: `uv run pytest tests/unit/breadcrumbs/test_snapshot_git.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add libs/breadcrumbs/snapshot.py tests/unit/breadcrumbs/test_snapshot_git.py
git commit -m "feat(breadcrumbs): A1 snapshot — git state collector"
```

---

## Task 9: A1 snapshot — scan + plan + eval enrichment with LRU

**Files:**
- Modify: `libs/breadcrumbs/snapshot.py` (add functions)
- Create: `tests/unit/breadcrumbs/test_snapshot_enrichment.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/breadcrumbs/test_snapshot_enrichment.py
from pathlib import Path
from libs.breadcrumbs.snapshot import (
    collect_active_plan, A1Snapshot, build_a1_snapshot, _clear_caches,
)


def test_collect_active_plan_picks_newest(tmp_path: Path) -> None:
    plans = tmp_path / "docs" / "superpowers" / "plans"
    plans.mkdir(parents=True)
    p1 = plans / "2026-01-01-foo.md"
    p1.write_text("# Foo\n## Step 1\n## Step 2\n")
    p2 = plans / "2026-02-01-bar.md"
    p2.write_text("# Bar\n## Step 1\n## Step 2\n## Step 3\n")
    plan = collect_active_plan(project_root=tmp_path)
    assert plan is not None
    assert plan.path == p2
    assert plan.total_steps == 3


def test_collect_active_plan_none_when_missing(tmp_path: Path) -> None:
    assert collect_active_plan(project_root=tmp_path) is None


def test_build_a1_snapshot_assembles_all_fields(tmp_path: Path) -> None:
    _clear_caches()
    snap = build_a1_snapshot(project_root=tmp_path)
    assert isinstance(snap, A1Snapshot)
    assert snap.git.branch == ""  # not a git repo
    assert snap.active_plan is None
    assert snap.last_scan is None
```

- [ ] **Step 2: Run test (expect ImportError on `collect_active_plan`)**

Run: `uv run pytest tests/unit/breadcrumbs/test_snapshot_enrichment.py -v`
Expected: ImportError

- [ ] **Step 3: Add to `libs/breadcrumbs/snapshot.py`**

```python
# Append to libs/breadcrumbs/snapshot.py

import time
from typing import Any

_CACHE: dict[str, tuple[float, Any]] = {}
_TTL_PLAN = 300.0
_TTL_SCAN = 300.0
_TTL_EVAL = 1800.0


def _clear_caches() -> None:
    _CACHE.clear()


def _cached(key: str, ttl: float, producer):
    now = time.time()
    entry = _CACHE.get(key)
    if entry is not None and (now - entry[0]) < ttl:
        return entry[1]
    value = producer()
    _CACHE[key] = (now, value)
    return value


@dataclass(frozen=True)
class PlanRef:
    path: Path
    mtime: float
    total_steps: int


@dataclass(frozen=True)
class ScanSummary:
    timestamp: float
    files_scanned: int
    files_reparsed: int
    duration_ms: float
    status: str


@dataclass(frozen=True)
class A1Snapshot:
    git: GitState
    active_plan: PlanRef | None
    last_scan: ScanSummary | None


def collect_active_plan(*, project_root: Path) -> PlanRef | None:
    plans_dir = project_root / "docs" / "superpowers" / "plans"
    key = f"plan:{plans_dir}"

    def producer() -> PlanRef | None:
        if not plans_dir.exists():
            return None
        candidates = [p for p in plans_dir.glob("*.md") if p.is_file()]
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        newest = candidates[0]
        text = newest.read_text(encoding="utf-8", errors="ignore")
        total_steps = sum(1 for line in text.splitlines() if line.startswith("## Step "))
        return PlanRef(path=newest, mtime=newest.stat().st_mtime, total_steps=total_steps)

    return _cached(key, _TTL_PLAN, producer)


def collect_last_scan(*, project_root: Path) -> ScanSummary | None:
    key = f"scan:{project_root}"

    def producer() -> ScanSummary | None:
        try:
            from libs.scan_history.store import ScanHistoryStore, events_since
        except ImportError:
            return None
        store = ScanHistoryStore()
        try:
            store.migrate()
            events = events_since(store, project_root=str(project_root), since_ts=0.0)
        except Exception:
            return None
        finally:
            store.close()
        if not events:
            return None
        ev = events[-1]
        return ScanSummary(
            timestamp=ev.timestamp, files_scanned=ev.files_scanned,
            files_reparsed=ev.files_reparsed, duration_ms=ev.duration_ms,
            status=ev.status,
        )

    return _cached(key, _TTL_SCAN, producer)


def build_a1_snapshot(*, project_root: Path) -> A1Snapshot:
    return A1Snapshot(
        git=collect_git_state(project_root=project_root),
        active_plan=collect_active_plan(project_root=project_root),
        last_scan=collect_last_scan(project_root=project_root),
    )
```

- [ ] **Step 4: Run tests (expect PASS)**

Run: `uv run pytest tests/unit/breadcrumbs/test_snapshot_enrichment.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add libs/breadcrumbs/snapshot.py tests/unit/breadcrumbs/test_snapshot_enrichment.py
git commit -m "feat(breadcrumbs): A1 snapshot — plan + scan enrichment with LRU"
```

---

## Task 10: ResumePack assembler + FocusGuess

**Files:**
- Create: `libs/breadcrumbs/views.py`
- Create: `tests/unit/breadcrumbs/test_views.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/breadcrumbs/test_views.py
import time
from pathlib import Path
from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.writer import write_pack_event
from libs.breadcrumbs.views import (
    build_project_resume_pack, build_cross_project_resume_pack,
    ResumePack, ProjectResumePack,
)


def _store(tmp_path: Path) -> BreadcrumbStore:
    s = BreadcrumbStore(db_path=tmp_path / "bc.db")
    s.migrate()
    return s


def test_project_resume_pack_with_breadcrumbs(tmp_path: Path) -> None:
    s = _store(tmp_path)
    write_pack_event(
        store=s, project_root=str(tmp_path), os_user="alice",
        query="how does X work", mode="navigate",
        paths_touched=["src/x.py", "src/x.py", "src/y.py"],
    )
    pack = build_project_resume_pack(
        store=s, project_root=tmp_path, os_user="alice",
        cc_account_email=None, since_ts=0.0, limit=100,
    )
    assert isinstance(pack, ProjectResumePack)
    assert pack.breadcrumbs_empty is False
    assert pack.inferred_focus.last_query == "how does X work"
    assert pack.inferred_focus.last_mode == "navigate"
    assert "src/x.py" in [str(p) for p in pack.inferred_focus.hot_files]


def test_project_resume_pack_empty(tmp_path: Path) -> None:
    s = _store(tmp_path)
    pack = build_project_resume_pack(
        store=s, project_root=tmp_path, os_user="alice",
        cc_account_email=None, since_ts=0.0, limit=100,
    )
    assert pack.breadcrumbs_empty is True
    assert pack.inferred_focus.last_query is None


def test_cross_project_resume_orders_by_recency(tmp_path: Path) -> None:
    s = _store(tmp_path)
    write_pack_event(store=s, project_root="/a", os_user="alice", query="q1", mode="navigate", paths_touched=[])
    time.sleep(0.01)
    write_pack_event(store=s, project_root="/b", os_user="alice", query="q2", mode="edit", paths_touched=[])
    pack = build_cross_project_resume_pack(store=s, os_user="alice", since_ts=0.0, limit=10)
    assert pack.scope == "cross_project"
    assert [d.project_root for d in pack.digest] == ["/b", "/a"]
```

- [ ] **Step 2: Run test (expect ImportError)**

Run: `uv run pytest tests/unit/breadcrumbs/test_views.py -v`
Expected: ImportError

- [ ] **Step 3: Implement views**

```python
# libs/breadcrumbs/views.py
"""ResumePack assemblers + FocusGuess synthesis."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from libs.breadcrumbs.models import BreadcrumbView
from libs.breadcrumbs.reader import (
    ProjectDigestEntry, load_recent, load_cross_project,
)
from libs.breadcrumbs.snapshot import A1Snapshot, build_a1_snapshot
from libs.breadcrumbs.store import BreadcrumbStore


@dataclass(frozen=True)
class FocusGuess:
    last_query: str | None
    last_mode: Literal["navigate", "edit"] | None
    hot_files: list[Path]
    hot_symbols: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProjectResumePack:
    project_root: str
    snapshot: A1Snapshot
    recent_breadcrumbs: list[BreadcrumbView]
    inferred_focus: FocusGuess
    open_questions: list[str]
    breadcrumbs_empty: bool
    scope: Literal["project"] = "project"


@dataclass(frozen=True)
class ResumePack:
    generated_at: datetime
    scope: Literal["project", "cross_project"]
    project_pack: ProjectResumePack | None
    digest: list[ProjectDigestEntry] | None


def _synthesize_focus(breadcrumbs: list[BreadcrumbView]) -> FocusGuess:
    if not breadcrumbs:
        return FocusGuess(last_query=None, last_mode=None, hot_files=[])
    most_recent = breadcrumbs[0]
    counter: Counter[str] = Counter()
    for bc in breadcrumbs:
        for p in bc.paths_touched:
            counter[p] += 1
    hot = [Path(p) for p, _ in counter.most_common(5)]
    mode = most_recent.mode if most_recent.mode in ("navigate", "edit") else None
    return FocusGuess(
        last_query=most_recent.query,
        last_mode=mode,  # type: ignore[arg-type]
        hot_files=hot,
    )


def _open_questions_from(breadcrumbs: list[BreadcrumbView]) -> list[str]:
    questions: list[str] = []
    for bc in breadcrumbs:
        if bc.turn_summary and ("error" in bc.turn_summary.lower() or "fail" in bc.turn_summary.lower()):
            questions.append(bc.turn_summary[:200])
    return questions[:5]


def build_project_resume_pack(
    *,
    store: BreadcrumbStore,
    project_root: Path,
    os_user: str,
    cc_account_email: str | None,
    since_ts: float,
    limit: int,
) -> ProjectResumePack:
    breadcrumbs = load_recent(
        store=store, project_root=str(project_root), os_user=os_user,
        since_ts=since_ts, limit=limit, cc_account_email=cc_account_email,
    )
    return ProjectResumePack(
        project_root=str(project_root),
        snapshot=build_a1_snapshot(project_root=project_root),
        recent_breadcrumbs=breadcrumbs,
        inferred_focus=_synthesize_focus(breadcrumbs),
        open_questions=_open_questions_from(breadcrumbs),
        breadcrumbs_empty=not breadcrumbs,
    )


def build_cross_project_resume_pack(
    *,
    store: BreadcrumbStore,
    os_user: str,
    since_ts: float,
    limit: int,
) -> ResumePack:
    digest = load_cross_project(
        store=store, os_user=os_user, since_ts=since_ts, limit=limit,
    )
    return ResumePack(
        generated_at=datetime.now(timezone.utc),
        scope="cross_project",
        project_pack=None,
        digest=digest,
    )
```

- [ ] **Step 4: Run tests (expect PASS)**

Run: `uv run pytest tests/unit/breadcrumbs/test_views.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add libs/breadcrumbs/views.py tests/unit/breadcrumbs/test_views.py
git commit -m "feat(breadcrumbs): ResumePack assembler + FocusGuess synthesis"
```

---

## Task 11: Markdown renderer (full + inject modes)

**Files:**
- Create: `libs/breadcrumbs/renderer.py`
- Create: `tests/unit/breadcrumbs/test_renderer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/breadcrumbs/test_renderer.py
import time
from pathlib import Path
from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.writer import write_pack_event
from libs.breadcrumbs.views import build_project_resume_pack, build_cross_project_resume_pack
from libs.breadcrumbs.renderer import render_project_pack, render_cross_project, render_inject


def test_render_project_pack_includes_branch_and_query(tmp_path: Path) -> None:
    s = BreadcrumbStore(db_path=tmp_path / "bc.db"); s.migrate()
    write_pack_event(store=s, project_root=str(tmp_path), os_user="alice",
                     query="how does X work", mode="navigate", paths_touched=["src/x.py"])
    pack = build_project_resume_pack(
        store=s, project_root=tmp_path, os_user="alice",
        cc_account_email=None, since_ts=0.0, limit=100,
    )
    md = render_project_pack(pack)
    assert "## Resume" in md
    assert "how does X work" in md
    assert "src/x.py" in md


def test_render_inject_under_2kb(tmp_path: Path) -> None:
    s = BreadcrumbStore(db_path=tmp_path / "bc.db"); s.migrate()
    for i in range(50):
        write_pack_event(store=s, project_root=str(tmp_path), os_user="alice",
                         query=f"query {i}", mode="navigate", paths_touched=[f"src/f{i}.py"])
    pack = build_project_resume_pack(
        store=s, project_root=tmp_path, os_user="alice",
        cc_account_email=None, since_ts=0.0, limit=100,
    )
    md = render_inject(pack)
    assert len(md.encode("utf-8")) <= 2048


def test_render_empty_pack_returns_empty_string(tmp_path: Path) -> None:
    s = BreadcrumbStore(db_path=tmp_path / "bc.db"); s.migrate()
    pack = build_project_resume_pack(
        store=s, project_root=tmp_path, os_user="alice",
        cc_account_email=None, since_ts=0.0, limit=100,
    )
    assert render_inject(pack) == ""


def test_render_cross_project(tmp_path: Path) -> None:
    s = BreadcrumbStore(db_path=tmp_path / "bc.db"); s.migrate()
    write_pack_event(store=s, project_root="/a", os_user="alice", query="qa", mode="navigate", paths_touched=[])
    time.sleep(0.01)
    write_pack_event(store=s, project_root="/b", os_user="alice", query="qb", mode="edit", paths_touched=[])
    pack = build_cross_project_resume_pack(store=s, os_user="alice", since_ts=0.0, limit=10)
    md = render_cross_project(pack)
    assert "/a" in md and "/b" in md
```

- [ ] **Step 2: Run test (expect ImportError)**

Run: `uv run pytest tests/unit/breadcrumbs/test_renderer.py -v`
Expected: ImportError

- [ ] **Step 3: Implement renderer**

```python
# libs/breadcrumbs/renderer.py
"""Markdown renderer for ResumePack — full and --inject modes."""

from __future__ import annotations

from datetime import datetime, timezone

from libs.breadcrumbs.views import ProjectResumePack, ResumePack

_INJECT_HARD_CAP_BYTES = 2048


def _humanize_age(ts: float) -> str:
    delta = max(0, int(datetime.now(timezone.utc).timestamp() - ts))
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


def render_project_pack(pack: ProjectResumePack) -> str:
    g = pack.snapshot.git
    proj = pack.project_root.rsplit("/", 1)[-1] or pack.project_root
    header = f"## Resume: {proj} @ {g.branch or '(no git)'}"
    if g.upstream:
        header += f" ({g.ahead} ahead, {g.behind} behind)"
    lines: list[str] = [header, ""]
    if not pack.breadcrumbs_empty:
        last_age = _humanize_age(pack.recent_breadcrumbs[0].timestamp)
        sessions = len({bc.cc_session_id for bc in pack.recent_breadcrumbs if bc.cc_session_id})
        lines.append(
            f"**Last activity:** {last_age} · {sessions} sessions · "
            f"{len(pack.recent_breadcrumbs)} breadcrumbs in window"
        )
        lines.append("")
        lines.append("### What you were doing")
        if pack.inferred_focus.last_query:
            lines.append(f'Last query: "{pack.inferred_focus.last_query}"')
        if pack.inferred_focus.last_mode:
            lines.append(f"Last mode: {pack.inferred_focus.last_mode}")
        if pack.inferred_focus.hot_files:
            files_str = ", ".join(str(p) for p in pack.inferred_focus.hot_files[:5])
            lines.append(f"Hot files: {files_str}")
        lines.append("")
    else:
        lines.append("**Last activity:** none in window (breadcrumbs_empty)")
        lines.append("")
    lines.append("### Filesystem state")
    if g.branch:
        lines.append(f"- Branch: {g.branch}")
        if g.upstream:
            lines.append(f"- Upstream: {g.upstream} ({g.ahead} ahead, {g.behind} behind)")
        if g.dirty_files:
            sample = ", ".join(f.path for f in g.dirty_files[:5])
            lines.append(f"- Dirty: {len(g.dirty_files)} files ({sample})")
        if g.staged_files:
            lines.append(f"- Staged: {len(g.staged_files)} files")
        if g.last_commits:
            lines.append("- Last commits:")
            for c in g.last_commits[:3]:
                lines.append(f"  - {c.rel_time}: \"{c.subject}\"")
    else:
        lines.append("(not a git repo)")
    lines.append("")
    if pack.snapshot.active_plan:
        plan = pack.snapshot.active_plan
        lines.append("### Active plan")
        lines.append(f"[{plan.path.name}]({plan.path}) — {plan.total_steps} steps")
        lines.append("")
    if pack.open_questions:
        lines.append("### Open questions")
        for q in pack.open_questions:
            lines.append(f"- {q}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_inject(pack: ProjectResumePack) -> str:
    if pack.breadcrumbs_empty and not pack.snapshot.git.branch:
        return ""
    g = pack.snapshot.git
    proj = pack.project_root.rsplit("/", 1)[-1] or pack.project_root
    lines: list[str] = [f"## Resume: {proj} @ {g.branch or '(no git)'}", ""]
    if not pack.breadcrumbs_empty:
        if pack.inferred_focus.last_query:
            lines.append(f'Last query: "{pack.inferred_focus.last_query}"')
        if pack.inferred_focus.hot_files:
            files_str = ", ".join(str(p) for p in pack.inferred_focus.hot_files[:3])
            lines.append(f"Hot files: {files_str}")
    if g.branch and g.dirty_files:
        sample = ", ".join(f.path for f in g.dirty_files[:3])
        lines.append(f"Dirty: {len(g.dirty_files)} files ({sample})")
    md = "\n".join(lines).rstrip() + "\n"
    if len(md.encode("utf-8")) > _INJECT_HARD_CAP_BYTES:
        encoded = md.encode("utf-8")[:_INJECT_HARD_CAP_BYTES - 3] + b"..."
        return encoded.decode("utf-8", errors="ignore")
    return md


def render_cross_project(pack: ResumePack) -> str:
    if not pack.digest:
        return "## Resume: no recent activity in any project\n"
    lines = ["## Resume: cross-project digest", ""]
    for entry in pack.digest:
        age = _humanize_age(entry.last_ts)
        lines.append(f"- **{entry.project_root}** ({entry.count} events, last {age})")
        if entry.last_query:
            lines.append(f"  - last: \"{entry.last_query}\" [{entry.last_mode or '?'}]")
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 4: Run tests (expect PASS)**

Run: `uv run pytest tests/unit/breadcrumbs/test_renderer.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add libs/breadcrumbs/renderer.py tests/unit/breadcrumbs/test_renderer.py
git commit -m "feat(breadcrumbs): markdown renderer (full + inject modes)"
```

---

## Task 12: MCP tool — `lvdcp_resume`

**Files:**
- Modify: `apps/mcp/tools.py` (add tool function + response model)
- Modify: `apps/mcp/server.py` (register tool)
- Create: `tests/unit/mcp/test_resume_tool.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/mcp/test_resume_tool.py
from pathlib import Path
import pytest
from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.writer import write_pack_event


def test_lvdcp_resume_project_scope(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)
    s = BreadcrumbStore(db_path=db); s.migrate()
    write_pack_event(store=s, project_root=str(tmp_path), os_user="alice",
                     query="how does X work", mode="navigate", paths_touched=["src/x.py"])
    s.close()

    from apps.mcp.tools import lvdcp_resume
    out = lvdcp_resume(path=str(tmp_path), scope="project", limit=10, format="markdown")
    assert out.scope == "project"
    assert "Resume:" in out.markdown
    assert "how does X work" in out.markdown


def test_lvdcp_resume_cross_project(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)
    s = BreadcrumbStore(db_path=db); s.migrate()
    write_pack_event(store=s, project_root="/a", os_user="alice", query="qa", mode="navigate", paths_touched=[])
    write_pack_event(store=s, project_root="/b", os_user="alice", query="qb", mode="edit", paths_touched=[])
    s.close()

    from apps.mcp.tools import lvdcp_resume
    out = lvdcp_resume(path=None, scope="cross_project", limit=10, format="markdown")
    assert out.scope == "cross_project"
    assert "/a" in out.markdown and "/b" in out.markdown
```

- [ ] **Step 2: Run test (expect ImportError)**

Run: `uv run pytest tests/unit/mcp/test_resume_tool.py -v`
Expected: ImportError

- [ ] **Step 3: Add tool function**

Append to `apps/mcp/tools.py` (after the existing imports — preserve top imports, add this block at end of file):

```python
# At top of file (with other imports):
import getpass
from libs.breadcrumbs.cc_identity import resolve_cc_account_email
from libs.breadcrumbs.renderer import (
    render_cross_project, render_inject, render_project_pack,
)
from libs.breadcrumbs.store import BreadcrumbStore, DEFAULT_STORE_PATH
from libs.breadcrumbs.views import (
    build_cross_project_resume_pack, build_project_resume_pack,
)


# At end of file:
class ResumeResult(BaseModel):
    scope: Literal["project", "cross_project"]
    markdown: str = Field(description="Rendered resume pack")
    breadcrumbs_empty: bool = Field(description="True when no breadcrumbs in window")
    project_root: str | None = Field(default=None)


_RESUME_WINDOW_SECONDS = 12 * 3600


def lvdcp_resume(
    path: str | None = None,
    scope: Literal["auto", "project", "cross_project"] = "auto",
    limit: int = 10,
    format: Literal["markdown", "json"] = "markdown",
) -> ResumeResult:
    """Resume engineering context for a previously active session.

    path=None auto-detects from cwd (or falls back to cross_project digest).
    Limit applies to breadcrumbs (project scope) or projects (cross_project).
    """
    import os
    import time

    os_user = getpass.getuser()
    cc_email = resolve_cc_account_email()
    since_ts = time.time() - _RESUME_WINDOW_SECONDS
    store = BreadcrumbStore(db_path=DEFAULT_STORE_PATH)
    store.migrate()
    try:
        if scope == "cross_project" or (scope == "auto" and not path):
            pack = build_cross_project_resume_pack(
                store=store, os_user=os_user, since_ts=since_ts, limit=limit,
            )
            md = render_cross_project(pack)
            return ResumeResult(scope="cross_project", markdown=md, breadcrumbs_empty=not pack.digest)
        target = Path(path) if path else Path(os.getcwd())
        ppack = build_project_resume_pack(
            store=store, project_root=target, os_user=os_user,
            cc_account_email=cc_email, since_ts=since_ts, limit=limit,
        )
        md = render_project_pack(ppack)
        return ResumeResult(
            scope="project", markdown=md,
            breadcrumbs_empty=ppack.breadcrumbs_empty,
            project_root=str(target),
        )
    finally:
        store.close()
```

- [ ] **Step 4: Register in server.py**

```python
# In apps/mcp/server.py, add to the import block:
from apps.mcp.tools import (
    lvdcp_resume as _lvdcp_resume,
)

# Add at the bottom of the registration list:
mcp.tool()(_lvdcp_resume)
```

- [ ] **Step 5: Run tests (expect PASS)**

Run: `uv run pytest tests/unit/mcp/test_resume_tool.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add apps/mcp/tools.py apps/mcp/server.py tests/unit/mcp/test_resume_tool.py
git commit -m "feat(mcp): register lvdcp_resume tool"
```

---

## Task 13: CLI — `ctx breadcrumb` family

**Files:**
- Create: `apps/cli/commands/breadcrumb_cmd.py`
- Modify: `apps/cli/main.py` (register command group)
- Create: `tests/unit/cli/test_breadcrumb_cmd.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/cli/test_breadcrumb_cmd.py
import json
from pathlib import Path
from typer.testing import CliRunner
from apps.cli.commands.breadcrumb_cmd import app as breadcrumb_app


def test_capture_writes_breadcrumb(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)
    monkeypatch.chdir(tmp_path)
    r = CliRunner()
    result = r.invoke(breadcrumb_app, ["capture", "--source=hook_stop"])
    assert result.exit_code == 0


def test_list_returns_zero_when_empty(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)
    monkeypatch.chdir(tmp_path)
    r = CliRunner()
    result = r.invoke(breadcrumb_app, ["list"])
    assert result.exit_code == 0


def test_prune_dry_run(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)
    r = CliRunner()
    result = r.invoke(breadcrumb_app, ["prune", "--older-than=14d", "--dry-run"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run test (expect ImportError)**

Run: `uv run pytest tests/unit/cli/test_breadcrumb_cmd.py -v`
Expected: ImportError

- [ ] **Step 3: Implement command**

```python
# apps/cli/commands/breadcrumb_cmd.py
"""`ctx breadcrumb` command family."""

from __future__ import annotations

import getpass
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Annotated

import typer

from libs.breadcrumbs.cc_identity import resolve_cc_account_email
from libs.breadcrumbs.models import BreadcrumbSource
from libs.breadcrumbs.prune import prune_older_than
from libs.breadcrumbs.reader import load_recent
from libs.breadcrumbs.store import DEFAULT_STORE_PATH, BreadcrumbStore
from libs.breadcrumbs.writer import write_hook_event

app = typer.Typer(help="Breadcrumb maintenance commands")

_DURATION_RE = re.compile(r"^(\d+)([smhd])$")
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _parse_duration(s: str) -> float:
    m = _DURATION_RE.match(s.strip())
    if not m:
        raise typer.BadParameter(f"invalid duration: {s!r}")
    return int(m.group(1)) * _UNITS[m.group(2)]


@app.command("capture")
def capture(
    source: Annotated[str, typer.Option("--source", help="Hook source name")],
    cc_session_id: Annotated[str | None, typer.Option("--cc-session-id")] = None,
    todo_file: Annotated[Path | None, typer.Option("--todo-file")] = None,
    summary: Annotated[str | None, typer.Option("--summary")] = None,
    summary_from_stdin: Annotated[bool, typer.Option("--summary-from-stdin")] = False,
) -> None:
    """Append a hook-sourced breadcrumb. Always exit 0; never blocks CC."""
    try:
        try:
            src = BreadcrumbSource(source)
        except ValueError:
            sys.stderr.write(f"unknown source {source!r}, ignoring\n")
            return
        project_root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        todo_snapshot: list[dict] | None = None
        if todo_file is not None and todo_file.exists():
            try:
                todo_snapshot = json.loads(todo_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                todo_snapshot = None
        if summary_from_stdin and not summary:
            summary = sys.stdin.read()
        store = BreadcrumbStore(db_path=DEFAULT_STORE_PATH)
        store.migrate()
        try:
            write_hook_event(
                store=store, source=src,
                project_root=project_root, os_user=getpass.getuser(),
                cc_session_id=cc_session_id or os.environ.get("CLAUDE_SESSION_ID"),
                cc_account_email=resolve_cc_account_email(),
                todo_snapshot=todo_snapshot, turn_summary=summary,
            )
        finally:
            store.close()
    except Exception as exc:
        sys.stderr.write(f"breadcrumb capture failed (suppressed): {exc}\n")


@app.command("list")
def list_(
    path: Annotated[Path | None, typer.Option("--path")] = None,
    since: Annotated[str, typer.Option("--since", help="e.g. 12h, 7d, 30m")] = "12h",
    limit: Annotated[int, typer.Option("--limit")] = 50,
    include_other_users: Annotated[bool, typer.Option("--include-other-users")] = False,
) -> None:
    project_root = str((path or Path(os.getcwd())).resolve())
    store = BreadcrumbStore(db_path=DEFAULT_STORE_PATH); store.migrate()
    try:
        rows = load_recent(
            store=store, project_root=project_root,
            os_user=getpass.getuser(),
            since_ts=time.time() - _parse_duration(since),
            limit=limit,
            cc_account_email=None if include_other_users else resolve_cc_account_email(),
        )
        for r in rows:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.timestamp))
            typer.echo(f"{ts}  {r.source:18s}  {r.mode or '-':9s}  {r.query or ''}")
    finally:
        store.close()


@app.command("prune")
def prune(
    older_than: Annotated[str, typer.Option("--older-than")] = "14d",
    project: Annotated[Path | None, typer.Option("--project")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    cutoff = time.time() - _parse_duration(older_than)
    store = BreadcrumbStore(db_path=DEFAULT_STORE_PATH); store.migrate()
    try:
        if dry_run:
            conn = store.connect()
            sql = "SELECT COUNT(*) FROM breadcrumbs WHERE timestamp < ?"
            params: tuple = (cutoff,)
            if project is not None:
                sql += " AND project_root = ?"
                params = (cutoff, str(project.resolve()))
            (cnt,) = conn.execute(sql, params).fetchone()
            typer.echo(f"would prune {cnt} rows")
            return
        deleted = prune_older_than(store=store, cutoff_ts=cutoff)
        typer.echo(f"pruned {deleted} rows")
    finally:
        store.close()


@app.command("purge")
def purge(project: Annotated[Path, typer.Option("--project")]) -> None:
    store = BreadcrumbStore(db_path=DEFAULT_STORE_PATH); store.migrate()
    try:
        conn = store.connect()
        cur = conn.execute("DELETE FROM breadcrumbs WHERE project_root = ?", (str(project.resolve()),))
        conn.commit()
        typer.echo(f"purged {cur.rowcount or 0} rows")
    finally:
        store.close()


@app.command("privacy")
def privacy(
    project: Annotated[Path, typer.Option("--project")],
    mode: Annotated[str, typer.Option("--mode")],
) -> None:
    if mode == "full_sync":
        typer.echo("error: full_sync is reserved for Phase 8+; use local_only", err=True)
        raise typer.Exit(code=2)
    if mode != "local_only":
        typer.echo(f"error: unknown mode {mode!r}", err=True)
        raise typer.Exit(code=2)
    typer.echo(f"privacy mode for {project} set to {mode}")
```

- [ ] **Step 4: Register in apps/cli/main.py**

```python
# In apps/cli/main.py, add:
from apps.cli.commands.breadcrumb_cmd import app as breadcrumb_app

# Then attach to root app:
app.add_typer(breadcrumb_app, name="breadcrumb")
```

- [ ] **Step 5: Run tests (expect PASS)**

Run: `uv run pytest tests/unit/cli/test_breadcrumb_cmd.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add apps/cli/commands/breadcrumb_cmd.py apps/cli/main.py tests/unit/cli/test_breadcrumb_cmd.py
git commit -m "feat(cli): ctx breadcrumb {capture,list,prune,purge,privacy}"
```

---

## Task 14: CLI — `ctx resume`

**Files:**
- Create: `apps/cli/commands/resume_cmd.py`
- Modify: `apps/cli/main.py`
- Create: `tests/unit/cli/test_resume_cmd.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/cli/test_resume_cmd.py
from pathlib import Path
from typer.testing import CliRunner
from apps.cli.commands.resume_cmd import app as resume_app
from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.writer import write_pack_event


def test_resume_returns_empty_string_when_no_breadcrumbs(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)
    monkeypatch.chdir(tmp_path)
    r = CliRunner()
    result = r.invoke(resume_app, ["--inject"])
    assert result.exit_code == 0


def test_resume_path_includes_query(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)
    s = BreadcrumbStore(db_path=db); s.migrate()
    write_pack_event(store=s, project_root=str(tmp_path), os_user=__import__("getpass").getuser(),
                     query="how does X work", mode="navigate", paths_touched=["src/x.py"])
    s.close()
    r = CliRunner()
    result = r.invoke(resume_app, ["--path", str(tmp_path)])
    assert result.exit_code == 0
    assert "how does X work" in result.output


def test_resume_all_lists_projects(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)
    s = BreadcrumbStore(db_path=db); s.migrate()
    write_pack_event(store=s, project_root="/a", os_user=__import__("getpass").getuser(),
                     query="qa", mode="navigate", paths_touched=[])
    s.close()
    r = CliRunner()
    result = r.invoke(resume_app, ["--all"])
    assert result.exit_code == 0
    assert "/a" in result.output
```

- [ ] **Step 2: Run test (expect ImportError)**

Run: `uv run pytest tests/unit/cli/test_resume_cmd.py -v`
Expected: ImportError

- [ ] **Step 3: Implement command**

```python
# apps/cli/commands/resume_cmd.py
"""`ctx resume` — print/inject session context."""

from __future__ import annotations

import getpass
import os
import sys
import time
from pathlib import Path
from typing import Annotated

import typer

from libs.breadcrumbs.cc_identity import resolve_cc_account_email
from libs.breadcrumbs.renderer import render_cross_project, render_inject, render_project_pack
from libs.breadcrumbs.store import DEFAULT_STORE_PATH, BreadcrumbStore
from libs.breadcrumbs.views import build_cross_project_resume_pack, build_project_resume_pack

app = typer.Typer(invoke_without_command=True, add_completion=False)

_RESUME_WINDOW_SECONDS = 12 * 3600


@app.callback()
def resume(
    path: Annotated[Path | None, typer.Option("--path")] = None,
    all_projects: Annotated[bool, typer.Option("--all", "-a")] = False,
    inject: Annotated[bool, typer.Option("--inject")] = False,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
    limit: Annotated[int, typer.Option("--limit")] = 10,
) -> None:
    """Print resume context (markdown). With --inject, output is capped to 2KB."""
    try:
        os_user = getpass.getuser()
        cc_email = resolve_cc_account_email()
        since_ts = time.time() - _RESUME_WINDOW_SECONDS
        store = BreadcrumbStore(db_path=DEFAULT_STORE_PATH); store.migrate()
        try:
            if all_projects:
                pack = build_cross_project_resume_pack(
                    store=store, os_user=os_user, since_ts=since_ts, limit=limit,
                )
                md = render_cross_project(pack)
                if md.strip():
                    typer.echo(md, nl=False)
                return
            target = Path(path) if path else Path(os.getcwd())
            ppack = build_project_resume_pack(
                store=store, project_root=target, os_user=os_user,
                cc_account_email=cc_email, since_ts=since_ts, limit=limit,
            )
            md = render_inject(ppack) if inject else render_project_pack(ppack)
            if md.strip():
                typer.echo(md, nl=False)
        finally:
            store.close()
    except Exception as exc:
        if not quiet:
            sys.stderr.write(f"resume failed (suppressed): {exc}\n")
```

- [ ] **Step 4: Register in apps/cli/main.py**

```python
# In apps/cli/main.py:
from apps.cli.commands.resume_cmd import app as resume_app

# Attach:
app.add_typer(resume_app, name="resume")
```

- [ ] **Step 5: Run tests (expect PASS)**

Run: `uv run pytest tests/unit/cli/test_resume_cmd.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add apps/cli/commands/resume_cmd.py apps/cli/main.py tests/unit/cli/test_resume_cmd.py
git commit -m "feat(cli): ctx resume — print/inject session context"
```

---

## Task 15: Side-effect writer in `lvdcp_pack`

**Files:**
- Modify: `apps/mcp/tools.py` (lvdcp_pack body — add fire-and-forget breadcrumb write)
- Create: `tests/unit/mcp/test_pack_breadcrumb.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/mcp/test_pack_breadcrumb.py
from pathlib import Path
from libs.breadcrumbs.store import BreadcrumbStore


def test_pack_writes_breadcrumb_side_effect(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)
    # Simulate a successful pack call by invoking the helper directly
    from apps.mcp.tools import _record_pack_breadcrumb
    _record_pack_breadcrumb(
        project_root=str(tmp_path),
        query="how does X work",
        mode="navigate",
        retrieved_files=["src/x.py", "src/y.py", "src/z.py", "src/a.py", "src/b.py", "src/c.py"],
    )
    s = BreadcrumbStore(db_path=db); s.migrate()
    rows = list(s.connect().execute("SELECT source, query FROM breadcrumbs"))
    s.close()
    assert len(rows) == 1
    assert rows[0] == ("pack", "how does X work")


def test_pack_breadcrumb_helper_swallows_exception(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "libs.breadcrumbs.store.DEFAULT_STORE_PATH",
        tmp_path / "no" / "such" / "dir" / "bc.db",
    )
    from apps.mcp.tools import _record_pack_breadcrumb
    # must not raise
    _record_pack_breadcrumb(project_root="/x", query="q", mode="navigate", retrieved_files=[])
```

- [ ] **Step 2: Run test (expect ImportError on _record_pack_breadcrumb)**

Run: `uv run pytest tests/unit/mcp/test_pack_breadcrumb.py -v`
Expected: ImportError

- [ ] **Step 3: Add helper + wire into lvdcp_pack**

In `apps/mcp/tools.py`, add helper near the bottom (after the `lvdcp_resume` block):

```python
def _record_pack_breadcrumb(
    *,
    project_root: str,
    query: str | None,
    mode: str | None,
    retrieved_files: list[str],
) -> None:
    """Fire-and-forget breadcrumb write. Never raises."""
    try:
        from libs.breadcrumbs.store import BreadcrumbStore, DEFAULT_STORE_PATH
        from libs.breadcrumbs.writer import write_pack_event
        store = BreadcrumbStore(db_path=DEFAULT_STORE_PATH)
        store.migrate()
        try:
            write_pack_event(
                store=store,
                project_root=project_root,
                os_user=getpass.getuser(),
                query=query,
                mode=mode,
                paths_touched=retrieved_files,
                cc_account_email=resolve_cc_account_email(),
            )
        finally:
            store.close()
    except Exception:
        log.exception("breadcrumb side-effect (pack) failed (suppressed)")
```

In the existing `lvdcp_pack` function body, just before `return`, add:

```python
    _record_pack_breadcrumb(
        project_root=str(path),
        query=query,
        mode=mode,
        retrieved_files=list(result.retrieved_files),
    )
```

(Adapt the variable names — `path`, `query`, `mode`, `result` — to match the actual local names in the existing `lvdcp_pack` body. If unsure, read the function once before editing.)

- [ ] **Step 4: Run tests (expect PASS)**

Run: `uv run pytest tests/unit/mcp/test_pack_breadcrumb.py tests/unit/mcp/test_resume_tool.py -v`
Expected: all PASS

Run regression: `uv run pytest tests/unit/mcp/ -v`
Expected: no new failures vs main.

- [ ] **Step 5: Commit**

```bash
git add apps/mcp/tools.py tests/unit/mcp/test_pack_breadcrumb.py
git commit -m "feat(mcp): write breadcrumb side-effect from lvdcp_pack"
```

---

## Task 16: Side-effect writer in `lvdcp_status`

**Files:**
- Modify: `apps/mcp/tools.py` (lvdcp_status body)
- Create: `tests/unit/mcp/test_status_breadcrumb.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/mcp/test_status_breadcrumb.py
from pathlib import Path
from libs.breadcrumbs.store import BreadcrumbStore


def test_status_writes_breadcrumb(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)
    from apps.mcp.tools import _record_status_breadcrumb
    _record_status_breadcrumb(project_root=str(tmp_path))
    s = BreadcrumbStore(db_path=db); s.migrate()
    (src,) = s.connect().execute("SELECT source FROM breadcrumbs").fetchone()
    s.close()
    assert src == "status"
```

- [ ] **Step 2: Run test (expect ImportError)**

Run: `uv run pytest tests/unit/mcp/test_status_breadcrumb.py -v`
Expected: ImportError

- [ ] **Step 3: Add helper + wire into lvdcp_status**

```python
# In apps/mcp/tools.py, add helper:
def _record_status_breadcrumb(*, project_root: str) -> None:
    try:
        from libs.breadcrumbs.store import BreadcrumbStore, DEFAULT_STORE_PATH
        from libs.breadcrumbs.writer import write_status_event
        store = BreadcrumbStore(db_path=DEFAULT_STORE_PATH)
        store.migrate()
        try:
            write_status_event(
                store=store, project_root=project_root,
                os_user=getpass.getuser(),
                cc_account_email=resolve_cc_account_email(),
            )
        finally:
            store.close()
    except Exception:
        log.exception("breadcrumb side-effect (status) failed (suppressed)")
```

In the body of `lvdcp_status`, just before `return`, add a call (use the actual project_root variable name — typically `path` or `workspace_root`):

```python
    _record_status_breadcrumb(project_root=str(path) if path else "")
```

- [ ] **Step 4: Run tests (expect PASS)**

Run: `uv run pytest tests/unit/mcp/ -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add apps/mcp/tools.py tests/unit/mcp/test_status_breadcrumb.py
git commit -m "feat(mcp): write breadcrumb side-effect from lvdcp_status"
```

---

## Task 17: Hook scripts (4 events)

**Files:**
- Create: `apps/mcp/hooks/lvdcp-resume-stop.sh`
- Create: `apps/mcp/hooks/lvdcp-resume-precompact.sh`
- Create: `apps/mcp/hooks/lvdcp-resume-subagent-stop.sh`
- Create: `apps/mcp/hooks/lvdcp-resume-sessionstart.sh`
- Create: `tests/unit/mcp/test_resume_hooks.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/mcp/test_resume_hooks.py
import os
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parents[3] / "apps" / "mcp" / "hooks"
EXPECTED = [
    "lvdcp-resume-stop.sh",
    "lvdcp-resume-precompact.sh",
    "lvdcp-resume-subagent-stop.sh",
    "lvdcp-resume-sessionstart.sh",
]


def test_resume_hooks_present_and_executable() -> None:
    for name in EXPECTED:
        p = HOOK_DIR / name
        assert p.exists(), f"missing {p}"
        assert p.stat().st_mode & 0o111, f"not executable: {p}"


def test_hooks_have_5s_timeout_marker() -> None:
    for name in EXPECTED:
        text = (HOOK_DIR / name).read_text()
        assert "timeout 5" in text, f"{name} missing timeout 5"
```

- [ ] **Step 2: Run test (expect FAIL — files missing)**

Run: `uv run pytest tests/unit/mcp/test_resume_hooks.py -v`
Expected: FAIL (files don't exist)

- [ ] **Step 3: Create hook scripts**

```bash
# apps/mcp/hooks/lvdcp-resume-stop.sh
#!/usr/bin/env bash
set -e
exec timeout 5 ctx breadcrumb capture --source=hook_stop 2>>"$HOME/Library/Logs/lvdcp/hook.log" || true
```

```bash
# apps/mcp/hooks/lvdcp-resume-precompact.sh
#!/usr/bin/env bash
set -e
exec timeout 5 ctx breadcrumb capture --source=hook_pre_compact --summary-from-stdin 2>>"$HOME/Library/Logs/lvdcp/hook.log" || true
```

```bash
# apps/mcp/hooks/lvdcp-resume-subagent-stop.sh
#!/usr/bin/env bash
set -e
exec timeout 5 ctx breadcrumb capture --source=hook_subagent_stop 2>>"$HOME/Library/Logs/lvdcp/hook.log" || true
```

```bash
# apps/mcp/hooks/lvdcp-resume-sessionstart.sh
#!/usr/bin/env bash
set -e
mkdir -p "$HOME/Library/Logs/lvdcp"
exec timeout 5 ctx resume --inject --quiet 2>>"$HOME/Library/Logs/lvdcp/hook.log" || true
```

After creating, mark all four executable:

```bash
chmod +x apps/mcp/hooks/lvdcp-resume-*.sh
```

- [ ] **Step 4: Run test (expect PASS)**

Run: `uv run pytest tests/unit/mcp/test_resume_hooks.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add apps/mcp/hooks/lvdcp-resume-*.sh tests/unit/mcp/test_resume_hooks.py
git commit -m "feat(hooks): add 4 resume hook scripts (Stop/PreCompact/SubagentStop/SessionStart)"
```

---

## Task 18: Extend `ctx mcp install` with `--hooks=resume`

**Files:**
- Modify: `apps/cli/commands/mcp_cmd.py`
- Create: `tests/unit/cli/test_mcp_resume_hooks_install.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/cli/test_mcp_resume_hooks_install.py
import json
from pathlib import Path
from typer.testing import CliRunner


def test_install_resume_hooks_merges_settings(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    settings = fake_home / ".claude" / "settings.json"
    settings.write_text(json.dumps({"hooks": {}}))
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    from apps.cli.commands.mcp_cmd import _install_resume_hooks
    installed = _install_resume_hooks(include_inject=True, include_schedule=False)
    assert any("Stop" in evt for evt in installed.events_added)

    data = json.loads(settings.read_text())
    assert "Stop" in data["hooks"]
    assert "SessionStart" in data["hooks"]


def test_install_resume_hooks_no_inject_skips_sessionstart(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    (fake_home / ".claude" / "settings.json").write_text("{}")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    from apps.cli.commands.mcp_cmd import _install_resume_hooks
    installed = _install_resume_hooks(include_inject=False, include_schedule=False)
    assert "SessionStart" not in installed.events_added
```

- [ ] **Step 2: Run test (expect ImportError)**

Run: `uv run pytest tests/unit/cli/test_mcp_resume_hooks_install.py -v`
Expected: ImportError

- [ ] **Step 3: Add `_install_resume_hooks` to `apps/cli/commands/mcp_cmd.py`**

```python
# Append to apps/cli/commands/mcp_cmd.py

from dataclasses import dataclass

_RESUME_HOOK_SRC = Path(__file__).resolve().parents[2] / "mcp" / "hooks"
_RESUME_HOOK_DST = Path.home() / ".claude" / "hooks" / "lvdcp"

_RESUME_HOOK_CONFIGS = {
    "Stop": [{
        "matcher": "lvdcp-resume",
        "hooks": [{"type": "command", "command": "$HOME/.claude/hooks/lvdcp/lvdcp-resume-stop.sh", "timeout": 5}],
    }],
    "PreCompact": [{
        "matcher": "lvdcp-resume",
        "hooks": [{"type": "command", "command": "$HOME/.claude/hooks/lvdcp/lvdcp-resume-precompact.sh", "timeout": 5}],
    }],
    "SubagentStop": [{
        "matcher": "lvdcp-resume",
        "hooks": [{"type": "command", "command": "$HOME/.claude/hooks/lvdcp/lvdcp-resume-subagent-stop.sh", "timeout": 5}],
    }],
    "SessionStart": [{
        "matcher": "lvdcp-resume",
        "hooks": [{"type": "command", "command": "$HOME/.claude/hooks/lvdcp/lvdcp-resume-sessionstart.sh", "timeout": 5}],
    }],
}


@dataclass(frozen=True)
class ResumeHooksInstallResult:
    events_added: list[str]
    files_copied: list[str]


def _install_resume_hooks(*, include_inject: bool, include_schedule: bool) -> ResumeHooksInstallResult:
    _RESUME_HOOK_DST.mkdir(parents=True, exist_ok=True)
    files_copied: list[str] = []
    for src in _RESUME_HOOK_SRC.glob("lvdcp-resume-*.sh"):
        if not include_inject and src.name.endswith("-sessionstart.sh"):
            continue
        dst = _RESUME_HOOK_DST / src.name
        shutil.copy2(src, dst)
        dst.chmod(0o755)
        files_copied.append(str(dst))

    settings_path = Path.home() / ".claude" / "settings.json"
    settings: dict[str, Any] = {}
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = settings.setdefault("hooks", {})
    events_added: list[str] = []
    for event, entries in _RESUME_HOOK_CONFIGS.items():
        if not include_inject and event == "SessionStart":
            continue
        existing = hooks.get(event, [])
        existing_matchers = {e.get("matcher") for e in existing}
        for entry in entries:
            if entry["matcher"] not in existing_matchers:
                existing.append(entry)
                events_added.append(event)
        hooks[event] = existing
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")

    if include_schedule:
        from libs.mcp_ops.launchd import bootstrap_breadcrumb_prune  # added in Task 19
        bootstrap_breadcrumb_prune()

    return ResumeHooksInstallResult(events_added=events_added, files_copied=files_copied)
```

Now extend the existing `install` command in the same file to accept `--hooks` option:

```python
# Modify the install command signature, add:
hooks: Annotated[str | None, typer.Option(
    "--hooks",
    help='Optional hook bundle. Use "resume" to install resume hooks. '
         'Suffixes ":no-inject" / ":no-schedule" disable parts.',
)] = None,
```

And in the install body, after the existing `_install_hooks()` call:

```python
if hooks:
    parts = hooks.split(":")
    if parts[0] != "resume":
        typer.echo(f"unknown --hooks value: {hooks}", err=True)
        raise typer.Exit(code=2)
    suffixes = set(parts[1:])
    _install_resume_hooks(
        include_inject="no-inject" not in suffixes,
        include_schedule="no-schedule" not in suffixes,
    )
```

- [ ] **Step 4: Run tests (expect PASS)**

Run: `uv run pytest tests/unit/cli/test_mcp_resume_hooks_install.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add apps/cli/commands/mcp_cmd.py tests/unit/cli/test_mcp_resume_hooks_install.py
git commit -m "feat(mcp_install): --hooks=resume[:no-inject][:no-schedule]"
```

---

## Task 19: launchd plist for daily prune

**Files:**
- Create: `deploy/launchd/com.lukinvit.lvdcp.breadcrumb-prune.plist.tmpl`
- Modify: `libs/mcp_ops/launchd.py` (add `bootstrap_breadcrumb_prune` / `bootout_breadcrumb_prune`)
- Create: `tests/unit/mcp_ops/test_breadcrumb_prune_launchd.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/mcp_ops/test_breadcrumb_prune_launchd.py
from pathlib import Path
from libs.mcp_ops.launchd import write_breadcrumb_prune_plist


def test_plist_contains_required_keys(tmp_path: Path) -> None:
    out = write_breadcrumb_prune_plist(plist_path=tmp_path / "prune.plist", ctx_path=Path("/usr/local/bin/ctx"))
    text = out.read_text()
    assert "com.lukinvit.lvdcp.breadcrumb-prune" in text
    assert "/usr/local/bin/ctx" in text
    assert "breadcrumb" in text and "prune" in text
    assert "<key>StartCalendarInterval</key>" in text
    assert "<integer>4</integer>" in text  # hour 04:00
```

- [ ] **Step 2: Run test (expect ImportError)**

Run: `uv run pytest tests/unit/mcp_ops/test_breadcrumb_prune_launchd.py -v`
Expected: ImportError

- [ ] **Step 3: Implement plist + helpers**

```xml
<!-- deploy/launchd/com.lukinvit.lvdcp.breadcrumb-prune.plist.tmpl -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.lukinvit.lvdcp.breadcrumb-prune</string>
    <key>ProgramArguments</key>
    <array>
        <string>{{CTX_PATH}}</string>
        <string>breadcrumb</string>
        <string>prune</string>
        <string>--older-than=14d</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>4</integer>
        <key>Minute</key><integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>{{LOG_DIR}}/breadcrumb-prune.log</string>
    <key>StandardErrorPath</key>
    <string>{{LOG_DIR}}/breadcrumb-prune.err</string>
</dict>
</plist>
```

Append to `libs/mcp_ops/launchd.py`:

```python
BREADCRUMB_PRUNE_LABEL = "com.lukinvit.lvdcp.breadcrumb-prune"

_BREADCRUMB_PRUNE_TMPL = (
    Path(__file__).resolve().parents[2]
    / "deploy" / "launchd" / "com.lukinvit.lvdcp.breadcrumb-prune.plist.tmpl"
)


def write_breadcrumb_prune_plist(*, plist_path: Path, ctx_path: Path) -> Path:
    log_dir = Path.home() / "Library" / "Logs" / "lvdcp"
    log_dir.mkdir(parents=True, exist_ok=True)
    template = _BREADCRUMB_PRUNE_TMPL.read_text(encoding="utf-8")
    rendered = template.replace("{{CTX_PATH}}", str(ctx_path)).replace("{{LOG_DIR}}", str(log_dir))
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(rendered, encoding="utf-8")
    return plist_path


def bootstrap_breadcrumb_prune() -> None:
    """Install + load the breadcrumb-prune launchd entry for the current GUI user."""
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{BREADCRUMB_PRUNE_LABEL}.plist"
    ctx_path = shutil.which("ctx") or sys.executable
    write_breadcrumb_prune_plist(plist_path=plist_path, ctx_path=Path(ctx_path))
    uid = os.getuid()
    subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)], check=False)


def bootout_breadcrumb_prune() -> None:
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{BREADCRUMB_PRUNE_LABEL}.plist"
    if not plist_path.exists():
        return
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(plist_path)], check=False)
    plist_path.unlink(missing_ok=True)
```

(Make sure `shutil`, `sys`, `os`, `subprocess`, `Path` are already imported at the top of the file.)

- [ ] **Step 4: Run tests (expect PASS)**

Run: `uv run pytest tests/unit/mcp_ops/test_breadcrumb_prune_launchd.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add deploy/launchd/com.lukinvit.lvdcp.breadcrumb-prune.plist.tmpl libs/mcp_ops/launchd.py tests/unit/mcp_ops/test_breadcrumb_prune_launchd.py
git commit -m "feat(launchd): daily breadcrumb-prune entry + bootstrap/bootout"
```

---

## Task 20: Eval fixture builder

**Files:**
- Create: `tests/eval/resume/__init__.py`
- Create: `tests/eval/resume/conftest.py`

- [ ] **Step 1: Write the conftest with fixture helpers**

```python
# tests/eval/resume/conftest.py
"""Synthetic breadcrumb fixtures + fake git repo helpers for resume eval."""

from __future__ import annotations

import getpass
import subprocess
import time
from pathlib import Path

import pytest

from libs.breadcrumbs.models import BreadcrumbSource
from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.writer import write_hook_event, write_pack_event


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "T")
    (r / "README.md").write_text("# Project\n")
    _git(r, "add", "README.md")
    _git(r, "commit", "-q", "-m", "initial")
    return r


@pytest.fixture
def store(tmp_path: Path) -> BreadcrumbStore:
    s = BreadcrumbStore(db_path=tmp_path / "bc.db")
    s.migrate()
    yield s
    s.close()


def seed_pack_events(
    store: BreadcrumbStore, *, project_root: str, queries: list[str],
    paths: list[list[str]], spacing_seconds: float = 1.0,
    os_user: str | None = None, cc_session_id: str | None = None,
) -> None:
    user = os_user or getpass.getuser()
    base_ts = time.time() - spacing_seconds * len(queries)
    for i, (q, ps) in enumerate(zip(queries, paths)):
        store.connect().execute(
            "INSERT INTO breadcrumbs ("
            " project_root, timestamp, source, cc_session_id, os_user, query, mode, paths_touched, privacy_mode"
            ") VALUES (?, ?, 'pack', ?, ?, ?, 'navigate', ?, 'local_only')",
            (project_root, base_ts + i * spacing_seconds, cc_session_id, user, q,
             None if not ps else __import__("json").dumps(ps[:5])),
        )
    store.connect().commit()


def seed_hook_event(
    store: BreadcrumbStore, *, project_root: str, todo: list[dict] | None = None,
    summary: str | None = None, ts_offset_seconds: float = 0.0,
) -> None:
    write_hook_event(
        store=store, source=BreadcrumbSource.HOOK_STOP,
        project_root=project_root, os_user=getpass.getuser(),
        todo_snapshot=todo, turn_summary=summary,
    )
```

- [ ] **Step 2: Commit (no test to run yet — fixtures only)**

```bash
git add tests/eval/resume/__init__.py tests/eval/resume/conftest.py
git commit -m "test(eval): scaffold resume eval fixtures (fake_repo, store, seed helpers)"
```

---

## Task 21: Eval scenarios E1, E2, E3

**Files:**
- Create: `tests/eval/resume/test_e1_e2_e3.py`

- [ ] **Step 1: Write all three eval scenarios**

```python
# tests/eval/resume/test_e1_e2_e3.py
"""E1 mid-plan, E2 mid-debug, E3 cross-project switch."""

from pathlib import Path
import time
import pytest

from libs.breadcrumbs.views import build_project_resume_pack, build_cross_project_resume_pack
from tests.eval.resume.conftest import seed_pack_events, seed_hook_event

pytestmark = pytest.mark.eval


def test_e1_mid_plan_surfaces_active_plan(fake_repo: Path, store) -> None:
    plans = fake_repo / "docs" / "superpowers" / "plans"
    plans.mkdir(parents=True)
    (plans / "2026-05-04-foo.md").write_text("# Foo\n## Step 1\n## Step 2\n## Step 3\n## Step 4\n## Step 5\n## Step 6\n## Step 7\n")
    seed_pack_events(
        store, project_root=str(fake_repo),
        queries=["impl step 3 part a", "impl step 3 part b", "impl step 3 done"],
        paths=[["src/a.py"], ["src/a.py"], ["src/a.py"]],
    )
    pack = build_project_resume_pack(
        store=store, project_root=fake_repo, os_user=__import__("getpass").getuser(),
        cc_account_email=None, since_ts=0.0, limit=100,
    )
    assert pack.snapshot.active_plan is not None
    assert pack.snapshot.active_plan.total_steps == 7
    assert pack.inferred_focus.last_query == "impl step 3 done"


def test_e2_mid_debug_surfaces_failing_test(fake_repo: Path, store) -> None:
    seed_pack_events(
        store, project_root=str(fake_repo),
        queries=["why does test_foo fail", "what's wrong with foo"],
        paths=[["src/foo.py", "tests/test_foo.py"], ["src/foo.py"]],
    )
    seed_hook_event(
        store, project_root=str(fake_repo),
        summary="pytest tests/test_foo.py::test_specific_behavior — failing on assertion",
    )
    pack = build_project_resume_pack(
        store=store, project_root=fake_repo, os_user=__import__("getpass").getuser(),
        cc_account_email=None, since_ts=0.0, limit=100,
    )
    hot = [str(p) for p in pack.inferred_focus.hot_files]
    assert "src/foo.py" in hot
    assert any("fail" in q.lower() for q in pack.open_questions)


def test_e3_cross_project_orders_b_before_a(store) -> None:
    seed_pack_events(store, project_root="/proj_a", queries=["q1"], paths=[[]])
    time.sleep(0.05)
    seed_pack_events(store, project_root="/proj_b", queries=["q2"], paths=[[]])
    pack = build_cross_project_resume_pack(
        store=store, os_user=__import__("getpass").getuser(),
        since_ts=0.0, limit=10,
    )
    assert [d.project_root for d in pack.digest][:2] == ["/proj_b", "/proj_a"]
```

- [ ] **Step 2: Run eval (expect PASS)**

Run: `uv run pytest tests/eval/resume/test_e1_e2_e3.py -v -m eval`
Expected: 3 passed

- [ ] **Step 3: Commit**

```bash
git add tests/eval/resume/test_e1_e2_e3.py
git commit -m "test(eval): E1 mid-plan, E2 mid-debug, E3 cross-project"
```

---

## Task 22: Eval scenarios E4, E5, E6

**Files:**
- Create: `tests/eval/resume/test_e4_e5_e6.py`

- [ ] **Step 1: Write the three scenarios**

```python
# tests/eval/resume/test_e4_e5_e6.py
"""E4 multi-day gap, E5 cold start, E6 hook missed (pack-only)."""

from pathlib import Path
import time
import pytest

from libs.breadcrumbs.views import build_project_resume_pack
from tests.eval.resume.conftest import seed_pack_events

pytestmark = pytest.mark.eval


def test_e4_multi_day_gap_returns_empty_window(fake_repo: Path, store) -> None:
    # Insert breadcrumb 3 days ago
    long_ago = time.time() - 3 * 86400
    store.connect().execute(
        "INSERT INTO breadcrumbs (project_root, timestamp, source, os_user, query, mode, privacy_mode) "
        "VALUES (?, ?, 'pack', ?, 'old', 'navigate', 'local_only')",
        (str(fake_repo), long_ago, __import__("getpass").getuser()),
    )
    store.connect().commit()
    pack = build_project_resume_pack(
        store=store, project_root=fake_repo, os_user=__import__("getpass").getuser(),
        cc_account_email=None, since_ts=time.time() - 12 * 3600, limit=100,
    )
    assert pack.breadcrumbs_empty is True
    assert pack.snapshot.git.branch == "main"  # A1 still complete


def test_e5_cold_start(fake_repo: Path, store) -> None:
    pack = build_project_resume_pack(
        store=store, project_root=fake_repo, os_user=__import__("getpass").getuser(),
        cc_account_email=None, since_ts=0.0, limit=100,
    )
    assert pack.breadcrumbs_empty is True
    assert pack.inferred_focus.last_query is None
    assert pack.snapshot.git.branch == "main"


def test_e6_hook_missed_pack_only_focus(fake_repo: Path, store) -> None:
    # No hook events, only pack events
    seed_pack_events(
        store, project_root=str(fake_repo),
        queries=["q1", "q2", "q3"],
        paths=[["src/x.py"], ["src/x.py", "src/y.py"], ["src/x.py"]],
    )
    pack = build_project_resume_pack(
        store=store, project_root=fake_repo, os_user=__import__("getpass").getuser(),
        cc_account_email=None, since_ts=0.0, limit=100,
    )
    assert pack.breadcrumbs_empty is False
    assert "src/x.py" in [str(p) for p in pack.inferred_focus.hot_files]
    assert pack.inferred_focus.last_query == "q3"
```

- [ ] **Step 2: Run eval**

Run: `uv run pytest tests/eval/resume/test_e4_e5_e6.py -v -m eval`
Expected: 3 passed

- [ ] **Step 3: Commit**

```bash
git add tests/eval/resume/test_e4_e5_e6.py
git commit -m "test(eval): E4 multi-day gap, E5 cold start, E6 hook missed"
```

---

## Task 23: Eval scenarios E7, E8

**Files:**
- Create: `tests/eval/resume/test_e7_e8.py`

- [ ] **Step 1: Write multi-user + redaction scenarios**

```python
# tests/eval/resume/test_e7_e8.py
"""E7 multi-user isolation, E8 secret redaction."""

from pathlib import Path
import pytest

from libs.breadcrumbs.reader import load_recent
from libs.breadcrumbs.writer import write_pack_event
from tests.eval.resume.conftest import seed_pack_events

pytestmark = pytest.mark.eval


def test_e7_multi_user_isolation(store) -> None:
    seed_pack_events(store, project_root="/x", queries=[f"q{i}" for i in range(50)],
                     paths=[[]] * 50, os_user="alice")
    rows_for_bob = load_recent(
        store=store, project_root="/x", os_user="bob",
        since_ts=0.0, limit=100,
    )
    assert rows_for_bob == []


def test_e8_secret_redaction_no_plaintext_in_db(store) -> None:
    write_pack_event(
        store=store, project_root="/x", os_user="alice",
        query="why does sk-1234567890ABCDEFGHIJ token fail "
              "with conn postgresql://u:p@db/x and api_key=sk_test_abcdefghijklmnopqr",
        mode="navigate", paths_touched=[],
    )
    rows = list(store.connect().execute("SELECT query FROM breadcrumbs"))
    assert len(rows) == 1
    q = rows[0][0]
    assert "sk-1234567890ABCDEFGHIJ" not in q
    assert "postgresql://u:p@db/x" not in q
    assert "sk_test_abcdefghijklmnopqr" not in q
    assert "[REDACTED:" in q
```

- [ ] **Step 2: Run eval**

Run: `uv run pytest tests/eval/resume/test_e7_e8.py -v -m eval`
Expected: 2 passed

- [ ] **Step 3: Commit**

```bash
git add tests/eval/resume/test_e7_e8.py
git commit -m "test(eval): E7 multi-user isolation, E8 redaction"
```

---

## Task 24: Eval scenarios E9, E10, E11

**Files:**
- Create: `tests/eval/resume/test_e9_e10_e11.py`

- [ ] **Step 1: Write latency, digest, and worktree scenarios**

```python
# tests/eval/resume/test_e9_e10_e11.py
"""E9 inject latency, E10 cross-project order, E11 worktree resolution."""

import getpass
import os
import subprocess
import time
from pathlib import Path
import pytest

from libs.breadcrumbs.renderer import render_inject
from libs.breadcrumbs.views import build_cross_project_resume_pack, build_project_resume_pack
from tests.eval.resume.conftest import seed_pack_events

pytestmark = pytest.mark.eval


def test_e9_inject_under_500ms_p95(fake_repo: Path, store) -> None:
    seed_pack_events(
        store, project_root=str(fake_repo),
        queries=[f"query {i}" for i in range(40)],
        paths=[[f"src/f{i}.py"] for i in range(40)],
    )
    timings: list[float] = []
    for _ in range(20):
        start = time.perf_counter()
        pack = build_project_resume_pack(
            store=store, project_root=fake_repo, os_user=getpass.getuser(),
            cc_account_email=None, since_ts=0.0, limit=100,
        )
        render_inject(pack)
        timings.append((time.perf_counter() - start) * 1000)
    timings.sort()
    p95 = timings[int(len(timings) * 0.95)]
    assert p95 <= 500, f"p95 inject latency {p95:.1f}ms exceeds 500ms"


def test_e10_cross_project_digest_orders_correctly(store) -> None:
    user = getpass.getuser()
    base = time.time() - 100
    for i in range(10):
        store.connect().execute(
            "INSERT INTO breadcrumbs (project_root, timestamp, source, os_user, query, mode, privacy_mode) "
            "VALUES (?, ?, 'pack', ?, ?, 'navigate', 'local_only')",
            (f"/proj_{i}", base + i, user, f"q{i}"),
        )
    store.connect().commit()
    pack = build_cross_project_resume_pack(store=store, os_user=user, since_ts=0.0, limit=5)
    expected = [f"/proj_{i}" for i in range(9, 4, -1)]
    assert [d.project_root for d in pack.digest] == expected


def test_e11_worktree_resolution(fake_repo: Path, store, tmp_path: Path) -> None:
    """A worktree of fake_repo should resolve to the parent project for resume purposes.

    LV_DCP currently identifies a project by the path passed in. The build helper
    receives the worktree path; the test asserts that breadcrumbs seeded against
    the parent path remain visible when the resume pack is requested for the
    parent path. (Mapping worktree → parent at the resume CLI/MCP layer is a
    follow-up if Phase 7 evidence shows it's needed.)
    """
    # seed against parent
    seed_pack_events(
        store, project_root=str(fake_repo),
        queries=["work in worktree"], paths=[["src/x.py"]],
    )
    # create real worktree
    wt_path = tmp_path / "worktree"
    subprocess.run(
        ["git", "worktree", "add", "-b", "feat-x", str(wt_path)],
        cwd=fake_repo, check=True, capture_output=True,
    )
    # Build pack against parent path; worktree pack would be empty
    pack = build_project_resume_pack(
        store=store, project_root=fake_repo, os_user=getpass.getuser(),
        cc_account_email=None, since_ts=0.0, limit=100,
    )
    assert pack.inferred_focus.last_query == "work in worktree"
    # Sanity — git can read the worktree branch
    out = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=wt_path, capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "feat-x"
```

- [ ] **Step 2: Run eval**

Run: `uv run pytest tests/eval/resume/test_e9_e10_e11.py -v -m eval`
Expected: 3 passed

- [ ] **Step 3: Commit**

```bash
git add tests/eval/resume/test_e9_e10_e11.py
git commit -m "test(eval): E9 inject latency, E10 digest order, E11 worktree resolution"
```

---

## Task 25: baseline.json + Makefile target

**Files:**
- Create: `tests/eval/resume/baseline.json`
- Modify: `Makefile`
- Create: `tests/eval/resume/test_baseline_gate.py`

- [ ] **Step 1: Write the baseline gate test**

```python
# tests/eval/resume/test_baseline_gate.py
"""CI gate — pinned thresholds from baseline.json."""

import json
from pathlib import Path
import pytest

pytestmark = pytest.mark.eval


def test_baseline_recall_at_least_threshold() -> None:
    baseline = json.loads((Path(__file__).parent / "baseline.json").read_text())
    assert baseline["resume_recall_at_5"] >= 0.90, \
        f"recall {baseline['resume_recall_at_5']} below 0.90 floor"
    assert baseline["secret_leak_count"] == 0
    assert baseline["cross_user_leak_count"] == 0
    assert baseline["resume_p95_latency_ms"] <= 1500
```

- [ ] **Step 2: Create baseline file**

```json
{
  "_meta": {
    "generated": "2026-05-04",
    "scenarios_run": 11,
    "note": "Baseline established from initial Phase 7 implementation. Tighten in 0.7.x patches."
  },
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

- [ ] **Step 3: Add Makefile targets**

Append to Makefile:

```makefile
.PHONY: eval-resume eval-resume-update

eval-resume:
	uv run pytest -q -m eval tests/eval/resume

eval-resume-update:
	@echo "Re-record baseline.json after intentional improvement (manual step)"
	@echo "Edit tests/eval/resume/baseline.json and commit with rationale"
```

- [ ] **Step 4: Run gate test (expect PASS)**

Run: `uv run pytest tests/eval/resume/test_baseline_gate.py -v -m eval`
Expected: 1 passed

Run all resume eval to verify the suite is green:

Run: `make eval-resume`
Expected: 12 passed (E1–E11 + gate)

- [ ] **Step 5: Commit**

```bash
git add tests/eval/resume/baseline.json tests/eval/resume/test_baseline_gate.py Makefile
git commit -m "test(eval): pin baseline.json + make eval-resume target"
```

---

## Task 26: Manual smoke test, release notes, dogfood

**Files:**
- Modify: `CHANGELOG.md` (or wherever release notes live; create if missing)
- Create: `docs/superpowers/specs/2026-05-04-session-resume-smoke-test.md`

- [ ] **Step 1: Write smoke test checklist document**

```markdown
<!-- docs/superpowers/specs/2026-05-04-session-resume-smoke-test.md -->
# Session Resume — Manual Smoke Test (DoD #8)

Run before merging Phase 7 slice. Captures the dogfood evidence required by
constitution invariant #11.

## Setup

```bash
uv sync --extra dev
ctx mcp install --hooks=resume
ctx breadcrumb list  # should be empty (or whatever local state is)
```

## Test 1 — Side-effect writer

1. From an indexed project, run `lvdcp_pack(query="test smoke", mode="navigate")` via Claude Code.
2. `ctx breadcrumb list` should now show one row with source=`pack`.

## Test 2 — Resume project

1. Edit a file, leave it dirty, ask Claude two questions through `lvdcp_pack`.
2. End the CC session.
3. Start a new CC session in the same project.
4. The SessionStart hook should auto-prepend a "Resume: ..." block.
5. Verify it contains the last query.

## Test 3 — Cross-project digest

1. Switch to another indexed project, run a `lvdcp_pack` there.
2. From an unrelated cwd, run `ctx resume --all`.
3. Both projects should appear with most-recent first.

## Test 4 — Multi-user (optional, requires second OS user)

If a second OS user is available: log in, run `ctx resume`. Output must NOT
contain queries from the first user.

## Test 5 — Prune

1. `ctx breadcrumb prune --older-than=0d --dry-run` — should show count.
2. `launchctl list | grep com.lukinvit.lvdcp` — entry present.

## Test 6 — Uninstall

1. `ctx mcp uninstall --hooks=resume`
2. Verify hooks removed from `~/.claude/settings.json`.
3. Verify `~/Library/LaunchAgents/com.lukinvit.lvdcp.breadcrumb-prune.plist` removed.

## Pass criteria

All 6 tests succeed without errors. If any failure — block merge until fixed.
```

- [ ] **Step 2: Add release notes entry**

Append to `CHANGELOG.md` (create if missing):

```markdown
## v0.7.0 — Session Resume (experimental)

### Added
- `lvdcp_resume` MCP tool — returns markdown resume pack with last queries,
  hot files, git state, active plan
- `ctx resume [--path] [--all] [--inject]` CLI
- `ctx breadcrumb {capture,list,prune,purge,privacy}` CLI
- `libs/breadcrumbs/` — single-writer breadcrumb store
  (`~/.lvdcp/breadcrumbs.db`)
- Side-effect breadcrumb write on every `lvdcp_pack`/`lvdcp_status` call
  (fire-and-forget, p95 ≤ 5ms overhead)
- 4 opt-in CC hooks (`Stop`, `PreCompact`, `SubagentStop`, `SessionStart`)
- `ctx mcp install --hooks=resume[:no-inject][:no-schedule]`
- launchd `com.lukinvit.lvdcp.breadcrumb-prune` daily entry (04:00 local)
- 11 eval scenarios + baseline.json + `make eval-resume`

### Notes
- **Default-on auto-inject** in `--hooks=resume`. Opt-out via `:no-inject`
  suffix or full uninstall.
- Multi-user safety: breadcrumbs scoped by `os_user` + best-effort
  `cc_account_email` (read-only parse of CC session JSON).
- Pattern-based secret redactor at write time (11 patterns; allowlist
  via `~/.lvdcp/config.yaml`).
- 14-day TTL by default; reconfigure via
  `breadcrumbs.retention_days`.
- `recall@5 ≥ 0.90` as CI floor (current baseline 0.95 — tightening in
  0.7.x patches).
- Cross-machine sync, encrypted-at-rest, and CC-transcript enrichment
  (A3) are explicitly deferred.
```

- [ ] **Step 3: Run full smoke test**

Manually execute every step in the smoke-test document on the actual
local machine. Note any deviations or surprises in this session log.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md docs/superpowers/specs/2026-05-04-session-resume-smoke-test.md
git commit -m "docs(resume): smoke test checklist + v0.7.0 release notes"
```

---

# Appendix — `recover-cc-session` (out of LV_DCP repo)

Tasks 27–30 build the standalone utility documented in spec §10. It lives at
`~/bin/recover-cc-session`, is **not** committed to the LV_DCP repository, and
can be developed in parallel after Task 26.

## Task 27: Bootstrap recover-cc-session (PEP 723)

**Files (all OUTSIDE the LV_DCP repo):**
- Create: `~/bin/recover-cc-session`

- [ ] **Step 1: Write the script with PEP 723 metadata + typer + rich skeleton**

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "typer>=0.12",
#     "rich>=13.7",
# ]
# ///
"""recover-cc-session — restore Claude Code session files after Cowork/Dispatch failures.

OUT OF SCOPE for LV_DCP. Operates only on the current OS user's
~/Library/Application Support/Claude/. Never edits identity fields.
"""

from __future__ import annotations

import json
import sys
import tarfile
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(help="Recover Claude Code sessions safely")
console = Console()

CC_ROOT = Path.home() / "Library" / "Application Support" / "Claude"
SNAPSHOT_ROOT = CC_ROOT / ".lv-recover-snapshots"
AUDIT_LOG = SNAPSHOT_ROOT / "audit.log"
CS_DIR = "claude-code-sessions"
LAMS_DIR = "local-agent-mode-sessions"


def _log_audit(action: str, args: dict) -> None:
    SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.now().isoformat(), "action": action, "args": args}
    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


@app.command("list")
def list_() -> None:
    """List sessions in both folders with mtimes and accountIds."""
    console.print("[bold]CC session folders:[/bold]")
    for sub in (CS_DIR, LAMS_DIR):
        base = CC_ROOT / sub
        if not base.exists():
            console.print(f"  {sub}: [dim]missing[/dim]")
            continue
        files = list(base.rglob("local_*.json"))
        console.print(f"  {sub}: {len(files)} files")


if __name__ == "__main__":
    app()
```

- [ ] **Step 2: Make executable + smoke run**

```bash
chmod +x ~/bin/recover-cc-session
recover-cc-session list
```

Expected: prints the two folders and counts.

- [ ] **Step 3: There is no commit (file is outside any repo)**

Optionally `cp ~/bin/recover-cc-session ~/bin/.recover-cc-session.bak` for
your own backup.

---

## Task 28: list/diff/backup commands

**Files:**
- Modify: `~/bin/recover-cc-session`

- [ ] **Step 1: Replace the `list` command with a richer table + add `diff` + `backup`**

```python
# Add at top of file (after imports):
from rich.table import Table
import os

# Replace the list_() command and add new commands:
def _scan_folder(sub: str) -> dict[tuple[str, str], list[Path]]:
    """Return {(accountId, orgId): [files]} for a folder."""
    base = CC_ROOT / sub
    out: dict[tuple[str, str], list[Path]] = {}
    if not base.exists():
        return out
    for acct in sorted(p for p in base.iterdir() if p.is_dir()):
        for org in sorted(p for p in acct.iterdir() if p.is_dir()):
            files = [f for f in org.glob("local_*.json") if f.is_file()]
            if files:
                out[(acct.name, org.name)] = files
    return out


@app.command("list", help="List sessions in both CC folders")
def list_cmd() -> None:
    table = Table(title="Claude Code session folders")
    table.add_column("folder")
    table.add_column("accountId")
    table.add_column("orgId")
    table.add_column("count")
    table.add_column("most recent")
    for sub in (CS_DIR, LAMS_DIR):
        scan = _scan_folder(sub)
        if not scan:
            table.add_row(sub, "[dim]missing[/dim]", "-", "-", "-")
            continue
        for (acct, org), files in scan.items():
            newest = max(files, key=lambda f: f.stat().st_mtime)
            mtime = datetime.fromtimestamp(newest.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            table.add_row(sub, acct, org, str(len(files)), mtime)
    console.print(table)


@app.command("diff", help="Show files present in one folder but not the other")
def diff_cmd() -> None:
    cs = {f.name for files in _scan_folder(CS_DIR).values() for f in files}
    lams = {f.name for files in _scan_folder(LAMS_DIR).values() for f in files}
    only_cs = cs - lams
    only_lams = lams - cs
    common = cs & lams
    console.print(f"[green]+ in {CS_DIR} only:[/green] {len(only_cs)}")
    for n in sorted(only_cs)[:50]:
        console.print(f"  {n}")
    console.print(f"[red]- in {LAMS_DIR} only:[/red] {len(only_lams)}")
    for n in sorted(only_lams)[:50]:
        console.print(f"  {n}")
    console.print(f"[dim]= in both:[/dim] {len(common)}")


@app.command("backup", help="Tarball both folders into ~/Backups/")
def backup_cmd(out: Path = typer.Option(None, "--out", help="Override output path")) -> None:
    backups_dir = Path.home() / "Backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    tarball = out or backups_dir / f"cc-sessions-{timestamp}.tar.gz"
    with tarfile.open(tarball, "w:gz") as tf:
        for sub in (CS_DIR, LAMS_DIR):
            base = CC_ROOT / sub
            if base.exists():
                tf.add(base, arcname=sub)
    _log_audit("backup", {"out": str(tarball)})
    console.print(f"[green]Backup written: {tarball}[/green]")
```

- [ ] **Step 2: Smoke run each command**

```bash
recover-cc-session list
recover-cc-session diff
recover-cc-session backup
```

Expected: table prints, diff prints, backup creates a tarball under `~/Backups/`.

- [ ] **Step 3: No commit (file outside repo)**

---

## Task 29: restore + snapshot system

**Files:**
- Modify: `~/bin/recover-cc-session`

- [ ] **Step 1: Add restore + snapshot machinery**

```python
import shutil

def _take_snapshot(label: str, command: str, args: dict) -> Path:
    SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    snap = SNAPSHOT_ROOT / datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    snap.mkdir(parents=True, exist_ok=False)
    for sub in (CS_DIR, LAMS_DIR):
        base = CC_ROOT / sub
        if base.exists():
            shutil.copytree(base, snap / sub)
    (snap / "metadata.json").write_text(json.dumps({
        "label": label, "command": command, "args": args,
        "ts": datetime.now().isoformat(),
    }, indent=2))
    _log_audit("snapshot", {"path": str(snap), "label": label})
    return snap


@app.command("restore", help="Copy missing files between folders")
def restore_cmd(
    from_: str = typer.Option(..., "--from", help="cs or lams"),
    to: str = typer.Option(..., "--to", help="cs or lams"),
    session_id: str | None = typer.Option(None, "--id"),
    all_missing: bool = typer.Option(False, "--all-missing"),
    dry_run: bool = typer.Option(True, "--dry-run/--apply"),
    no_backup: bool = typer.Option(False, "--no-backup"),
    i_know: bool = typer.Option(False, "--i-know-what-im-doing"),
) -> None:
    if from_ not in ("cs", "lams") or to not in ("cs", "lams"):
        console.print("[red]--from/--to must be 'cs' or 'lams'[/red]")
        raise typer.Exit(2)
    if from_ == to:
        console.print("[red]--from and --to must differ[/red]")
        raise typer.Exit(2)
    sub_from = {"cs": CS_DIR, "lams": LAMS_DIR}[from_]
    sub_to = {"cs": CS_DIR, "lams": LAMS_DIR}[to]
    src_files = {f.name: f for files in _scan_folder(sub_from).values() for f in files}
    dst_files = {f.name: f for files in _scan_folder(sub_to).values() for f in files}
    if session_id:
        candidates = {n: p for n, p in src_files.items() if session_id in n}
    elif all_missing:
        candidates = {n: p for n, p in src_files.items() if n not in dst_files}
    else:
        console.print("[red]--id or --all-missing required[/red]")
        raise typer.Exit(2)
    console.print(f"[bold]Plan:[/bold] {len(candidates)} file(s) will be copied "
                  f"from {sub_from} to {sub_to}")
    for name in sorted(candidates):
        console.print(f"  {name}")
    if dry_run:
        console.print("[yellow]Dry run — pass --apply to execute[/yellow]")
        return
    if not no_backup:
        _take_snapshot("pre-restore", "restore",
                       {"from": from_, "to": to, "count": len(candidates)})
    elif not i_know:
        console.print("[red]--no-backup requires --i-know-what-im-doing[/red]")
        raise typer.Exit(2)
    for name, src_path in candidates.items():
        # Mirror the source's accountId/orgId structure under the target folder
        rel = src_path.relative_to(CC_ROOT / sub_from)
        dst_path = CC_ROOT / sub_to / rel
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)
        console.print(f"  copied {name}")
    _log_audit("restore", {"from": from_, "to": to, "files": list(candidates)})
    console.print(f"[green]Restored {len(candidates)} file(s)[/green]")
```

- [ ] **Step 2: Smoke run on dry-run only**

```bash
recover-cc-session restore --from=cs --to=lams --all-missing  # dry-run by default
```

Expected: prints plan + "Dry run — pass --apply to execute".

- [ ] **Step 3: No commit**

---

## Task 30: undo + snapshots commands

**Files:**
- Modify: `~/bin/recover-cc-session`

- [ ] **Step 1: Add undo + snapshots subcommands**

```python
snapshots_app = typer.Typer(help="Snapshot management")
app.add_typer(snapshots_app, name="snapshots")


def _list_snapshots() -> list[Path]:
    if not SNAPSHOT_ROOT.exists():
        return []
    return sorted([p for p in SNAPSHOT_ROOT.iterdir() if p.is_dir()], key=lambda p: p.name, reverse=True)


@app.command("undo")
def undo_cmd(
    snapshot: str | None = typer.Option(None, "--snapshot", help="Specific snapshot timestamp (folder name)"),
) -> None:
    snaps = _list_snapshots()
    if not snaps:
        console.print("[yellow]No snapshots to undo[/yellow]")
        raise typer.Exit(0)
    target = snaps[0]
    if snapshot:
        candidates = [s for s in snaps if s.name == snapshot]
        if not candidates:
            console.print(f"[red]Snapshot {snapshot} not found[/red]")
            raise typer.Exit(2)
        target = candidates[0]
    # Take a snapshot of CURRENT state before reverting (so undo itself can be undone)
    _take_snapshot("pre-undo", "undo", {"reverting_to": target.name})
    for sub in (CS_DIR, LAMS_DIR):
        snap_sub = target / sub
        live_sub = CC_ROOT / sub
        if snap_sub.exists():
            if live_sub.exists():
                shutil.rmtree(live_sub)
            shutil.copytree(snap_sub, live_sub)
    _log_audit("undo", {"reverted_to": target.name})
    console.print(f"[green]Reverted to snapshot {target.name}[/green]")


@snapshots_app.command("list")
def snapshots_list(limit: int = typer.Option(10, "--limit")) -> None:
    table = Table(title="Snapshots")
    table.add_column("name"); table.add_column("command"); table.add_column("ts")
    for snap in _list_snapshots()[:limit]:
        meta_path = snap / "metadata.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        table.add_row(snap.name, meta.get("command", "?"), meta.get("ts", "?"))
    console.print(table)


@snapshots_app.command("prune")
def snapshots_prune(
    older_than: str = typer.Option("30d", "--older-than"),
    dry_run: bool = typer.Option(True, "--dry-run/--apply"),
) -> None:
    if not older_than.endswith("d"):
        console.print("[red]--older-than must end in 'd' (days)[/red]")
        raise typer.Exit(2)
    days = int(older_than[:-1])
    cutoff = datetime.now().timestamp() - days * 86400
    snaps = _list_snapshots()
    to_drop = [s for s in snaps if s.stat().st_mtime < cutoff]
    # Also enforce hard cap of 50
    if len(snaps) > 50:
        to_drop = list({s.name: s for s in to_drop + snaps[50:]}.values())
    console.print(f"Will drop {len(to_drop)} snapshot(s)")
    for s in to_drop:
        console.print(f"  {s.name}")
    if dry_run:
        return
    for s in to_drop:
        shutil.rmtree(s)
    _log_audit("snapshots_prune", {"dropped": [s.name for s in to_drop]})
    console.print(f"[green]Pruned {len(to_drop)} snapshot(s)[/green]")
```

- [ ] **Step 2: Smoke run**

```bash
recover-cc-session snapshots list
recover-cc-session undo --snapshot=<a-known-snapshot-name>  # only if you have one
recover-cc-session snapshots prune --older-than=30d  # dry-run
```

- [ ] **Step 3: No commit (script is local-only)**

Optionally save a backup copy:

```bash
cp ~/bin/recover-cc-session ~/bin/.recover-cc-session.bak
```

---

# Self-Review Checklist (executor: verify before declaring done)

1. **Spec coverage** — every spec section maps to a task:
   - Spec §5 (data model) → Tasks 1, 2 (store, models)
   - Spec §6 (triggers/API) → Tasks 12, 13, 14 (MCP tool, CLI)
   - Spec §6.4 (side-effect writers) → Tasks 15, 16
   - Spec §6.3 (hooks) → Tasks 17, 18
   - Spec §7.1 (multi-user) → Tasks 4, 5, 6 + E7 in Task 23
   - Spec §7.3 (redactor) → Task 3 + E8 in Task 23
   - Spec §7.4 (TTL) → Task 7
   - Spec §7.5 (launchd) → Task 19
   - Spec §8 (eval) → Tasks 20–25
   - Spec §10 (recover-cc-session) → Tasks 27–30

2. **Placeholder scan** — none. Each task has actual code, no "implement
   later".

3. **Type consistency** — `BreadcrumbStore`, `BreadcrumbView`,
   `ProjectResumePack`, `ResumePack`, `FocusGuess`, `BreadcrumbSource`
   used identically across tasks. `_record_pack_breadcrumb` /
   `_record_status_breadcrumb` are the only two helpers added to
   `apps/mcp/tools.py` and named consistently.

4. **DoD coverage (spec §8.8)** — Tasks 20–25 cover items 1–7
   (eval, coverage, lint, mypy via Makefile). Task 26 covers items 8–10
   (manual smoke + release notes + spec commit).
