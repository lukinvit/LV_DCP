"""Unit tests for ``libs.copilot.refresh_project`` and ``refresh_wiki``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from libs.copilot import refresh_project, refresh_wiki


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    (home / ".lvdcp").mkdir(parents=True)
    cfg = home / ".lvdcp" / "config.yaml"
    cfg.write_text(yaml.safe_dump({"qdrant": {"enabled": False}}))
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda _cls: home))


def _seed_project(root: Path) -> None:
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "a.py").write_text("def a() -> int:\n    return 1\n", encoding="utf-8")
    (root / "pkg" / "b.py").write_text("def b() -> int:\n    return 2\n", encoding="utf-8")


def test_refresh_no_wiki_short_circuit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_project(tmp_path)
    # Ensure the wiki path is never touched when refresh_wiki_after=False.
    called: dict[str, int] = {"wiki": 0}

    def _boom(*_a: Any, **_kw: Any) -> None:  # pragma: no cover — defensive
        called["wiki"] += 1
        raise AssertionError("refresh_wiki must not be called")

    monkeypatch.setattr("libs.copilot.orchestrator.refresh_wiki", _boom)
    report = refresh_project(tmp_path, full=False, refresh_wiki_after=False)
    assert report.scanned is True
    assert report.wiki_refreshed is False
    assert report.scan_files >= 1
    assert called["wiki"] == 0


def test_refresh_wiki_skipped_when_not_scanned(tmp_path: Path) -> None:
    report = refresh_wiki(tmp_path, all_modules=False)
    assert report.scanned is False
    assert report.wiki_refreshed is False
    assert any("not scanned" in m for m in report.messages)


def test_refresh_project_then_wiki_noop_on_clean_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a fresh scan, dirty modules exist; the wiki refresh should touch them.

    We stub ``generate_wiki_article`` so this test stays offline (no LLM call).
    """
    _seed_project(tmp_path)

    def _stub_article(**kw: Any) -> str:
        return f"# {kw['module_path']}\n\nstubbed wiki body.\n"

    # `generate_wiki_article` is imported lazily inside
    # `_run_wiki_update_in_process`, so the only patch target that actually
    # takes effect is the source module.
    monkeypatch.setattr(
        "libs.wiki.generator.generate_wiki_article",
        _stub_article,
    )
    report = refresh_project(tmp_path, full=True, refresh_wiki_after=True)
    assert report.scanned is True
    assert report.scan_files >= 2
    assert report.wiki_refreshed is True
    # A fresh scan marks every module dirty; at least one should have been updated.
    assert report.wiki_modules_updated >= 1


def test_refresh_project_wiki_background_spawns_subprocess_and_returns_fast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``wiki_background=True`` must not invoke the synchronous wiki path."""
    _seed_project(tmp_path)

    def _boom_wiki(*_a: Any, **_kw: Any) -> None:  # pragma: no cover — defensive
        raise AssertionError("in-process wiki must not run when wiki_background=True")

    monkeypatch.setattr("libs.copilot.orchestrator._run_wiki_update_in_process", _boom_wiki)

    # Stub the subprocess so no real fork happens.
    from libs.copilot import wiki_background

    class _StubPopen:
        def __init__(self, args: list[str], **_kw: Any) -> None:
            self.args = args
            self.pid = 77771

    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr("libs.copilot.wiki_background.subprocess.Popen", _StubPopen)

    report = refresh_project(tmp_path, full=False, refresh_wiki_after=True, wiki_background=True)
    assert report.scanned is True
    assert report.wiki_refreshed is False
    assert report.wiki_refresh_background_started is True
    assert any("background refresh started" in m for m in report.messages)


def test_refresh_wiki_background_flag_sets_bg_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``refresh_wiki(root, background=True)`` returns ``bg_started=True`` and spawns."""
    _seed_project(tmp_path)
    # A scan is required for refresh_wiki to do anything beyond the skip-branch.
    from libs.scanning.scanner import scan_project

    scan_project(tmp_path, mode="full")

    from libs.copilot import wiki_background

    class _StubPopen:
        def __init__(self, args: list[str], **_kw: Any) -> None:
            self.args = args
            self.pid = 66661

    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr("libs.copilot.wiki_background.subprocess.Popen", _StubPopen)

    report = refresh_wiki(tmp_path, background=True)
    assert report.scanned is True
    assert report.wiki_refreshed is False
    assert report.wiki_refresh_background_started is True


def test_run_wiki_update_fires_on_progress_at_every_module_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_run_wiki_update_in_process must call on_progress before + after each module.

    Sequence for N modules should be:
      (0, N, "pkg"), (1, N, "pkg2"?), …, (N, N, None)
    """
    from libs.copilot.orchestrator import _run_wiki_update_in_process
    from libs.scanning.scanner import scan_project

    _seed_project(tmp_path)
    scan_project(tmp_path, mode="full")

    def _stub_article(**kw: Any) -> str:
        return f"# {kw['module_path']}\n\nstubbed.\n"

    monkeypatch.setattr("libs.wiki.generator.generate_wiki_article", _stub_article)

    events: list[tuple[int, int, str | None]] = []

    def _on_progress(*, done: int, total: int, current: str | None, **_kw: Any) -> None:
        events.append((done, total, current))

    updated, _messages = _run_wiki_update_in_process(
        tmp_path, all_modules=True, on_progress=_on_progress
    )
    assert updated >= 1
    assert events, "on_progress must fire at least once"
    total = events[0][1]
    assert total >= 1
    # Sequence discipline: `done` is monotonic; final event resets `current=None`.
    dones = [e[0] for e in events]
    assert dones == sorted(dones)
    assert events[-1] == (total, total, None)
    # No event should report done > total.
    assert all(d <= total for d in dones)


def test_run_wiki_update_on_progress_noop_when_no_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Short-circuit path (no dirty modules) must still emit one "0/0" event.

    Gives the UI a way to render "done" even when there was nothing to do.
    """
    from libs.copilot.orchestrator import _run_wiki_update_in_process
    from libs.scanning.scanner import scan_project
    from libs.storage.sqlite_cache import SqliteCache
    from libs.wiki.state import ensure_wiki_table, mark_current

    _seed_project(tmp_path)
    scan_project(tmp_path, mode="full")
    # Mark every dirty module as current so the second call sees 0 dirty modules.
    db = tmp_path / ".context" / "cache.db"
    with SqliteCache(db) as cache:
        conn = cache._connect()
        ensure_wiki_table(conn)
        from libs.wiki.state import get_dirty_modules

        for mod in get_dirty_modules(conn):
            mark_current(conn, mod["module_path"], "fake.md", mod["source_hash"])
        conn.commit()

    events: list[tuple[int, int, str | None]] = []
    _run_wiki_update_in_process(
        tmp_path,
        all_modules=False,
        on_progress=lambda **kw: events.append((kw["done"], kw["total"], kw["current"])),
    )
    assert events == [(0, 0, None)]
