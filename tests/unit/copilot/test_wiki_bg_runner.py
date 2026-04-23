"""Tests for ``libs.copilot._wiki_bg_runner`` — the detached runner.

These tests drive ``main()`` directly (no subprocess) and assert that
``.refresh.last`` is persisted on three exit shapes: clean success,
SIGTERM cancellation, and crash. Deferred imports inside ``main`` are
monkeypatched at the module they're resolved at: ``libs.copilot.orchestrator``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from libs.copilot import _wiki_bg_runner, wiki_background


def _make_project(root: Path) -> None:
    (root / ".context" / "wiki").mkdir(parents=True, exist_ok=True)


def _install_fake_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fake: Callable[..., Any],
) -> None:
    """Swap in ``_run_wiki_update_in_process`` so main() doesn't import the real stack."""
    import libs.copilot.orchestrator as orch

    monkeypatch.setattr(orch, "_run_wiki_update_in_process", fake)


def test_runner_writes_last_refresh_on_clean_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_project(tmp_path)

    def fake_update(
        _root: Path,
        *,
        all_modules: bool,
        on_progress: Callable[..., None],
    ) -> tuple[int, list[str]]:
        on_progress(done=2, total=2, current="pkg/a")
        return (2, [])

    _install_fake_orchestrator(monkeypatch, fake=fake_update)
    exit_code = _wiki_bg_runner.main([str(tmp_path)])
    assert exit_code == 0

    record = wiki_background.read_last_refresh(tmp_path)
    assert record is not None
    assert record.exit_code == 0
    assert record.modules_updated == 2
    assert record.elapsed_seconds >= 0.0


def test_runner_writes_last_refresh_on_sigterm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SIGTERM path: ``SystemExit`` from inside update still flows through finally."""
    _make_project(tmp_path)

    def fake_update(
        _root: Path,
        *,
        all_modules: bool,
        on_progress: Callable[..., None],
    ) -> tuple[int, list[str]]:
        on_progress(done=1, total=5, current="pkg/a")
        # Simulate SIGTERM mid-run — main() maps this to exit_code=143.
        raise SystemExit(143)

    _install_fake_orchestrator(monkeypatch, fake=fake_update)
    exit_code = _wiki_bg_runner.main([str(tmp_path)])
    assert exit_code == 143

    record = wiki_background.read_last_refresh(tmp_path)
    assert record is not None
    assert record.exit_code == 143
    # The on_progress callback ran once before the SystemExit, so the
    # last observed count (1) is what the record should reflect.
    assert record.modules_updated == 1


def test_runner_writes_last_refresh_on_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unexpected exception → exit_code=1 and ``.refresh.last`` still persists."""
    _make_project(tmp_path)

    def fake_update(
        _root: Path,
        *,
        all_modules: bool,
        on_progress: Callable[..., None],
    ) -> tuple[int, list[str]]:
        raise RuntimeError("boom")

    _install_fake_orchestrator(monkeypatch, fake=fake_update)
    exit_code = _wiki_bg_runner.main([str(tmp_path)])
    assert exit_code == 1

    record = wiki_background.read_last_refresh(tmp_path)
    assert record is not None
    assert record.exit_code == 1
    assert record.modules_updated == 0


# ---- log_tail capture on crash (v0.8.5) -----------------------------------


def test_runner_captures_log_tail_from_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crash path: ``.refresh.log`` content since run-start is captured.

    Since tests don't redirect stdout to ``.refresh.log`` like the real
    parent does, we seed the file ourselves between ``_initial_log_offset``
    and the finally-block capture — that's what a real parent
    would have written from the crashed runner's stderr.
    """
    _make_project(tmp_path)
    log_path = tmp_path / ".context" / "wiki" / ".refresh.log"
    # Pre-run content — the runner's offset capture must ignore this.
    log_path.write_text("old-run boilerplate\n", encoding="utf-8")

    def fake_update(
        _root: Path,
        *,
        all_modules: bool,
        on_progress: Callable[..., None],
    ) -> tuple[int, list[str]]:
        # Simulate crash output arriving in the log file mid-run.
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write("2026-04-24 [bg-wiki pid=1] Traceback (most recent call last):\n")
            fh.write('  File "x.py", line 10, in _run\n    raise RuntimeError("boom")\n')
            fh.write("RuntimeError: boom\n")
        raise RuntimeError("boom")

    _install_fake_orchestrator(monkeypatch, fake=fake_update)
    exit_code = _wiki_bg_runner.main([str(tmp_path)])
    assert exit_code == 1

    record = wiki_background.read_last_refresh(tmp_path)
    assert record is not None
    assert record.log_tail is not None
    tail = list(record.log_tail)
    # Pre-run line filtered out (offset).
    assert "old-run boilerplate" not in tail
    # Traceback surfaced.
    assert any("RuntimeError: boom" in line for line in tail)


def test_runner_log_tail_is_none_on_clean_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clean runs: no diagnostic tail persisted (keeps the record small)."""
    _make_project(tmp_path)
    # Even if .refresh.log has content, clean exit should not capture it.
    (tmp_path / ".context" / "wiki" / ".refresh.log").write_text("some line\n", encoding="utf-8")

    def fake_update(
        _root: Path,
        *,
        all_modules: bool,
        on_progress: Callable[..., None],
    ) -> tuple[int, list[str]]:
        on_progress(done=1, total=1, current="x")
        return (1, [])

    _install_fake_orchestrator(monkeypatch, fake=fake_update)
    exit_code = _wiki_bg_runner.main([str(tmp_path)])
    assert exit_code == 0
    record = wiki_background.read_last_refresh(tmp_path)
    assert record is not None
    assert record.log_tail is None


def test_runner_log_tail_is_none_on_sigterm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SIGTERM cancellations don't attach a tail — the 'cancelled' label suffices."""
    _make_project(tmp_path)
    (tmp_path / ".context" / "wiki" / ".refresh.log").write_text("irrelevant\n", encoding="utf-8")

    def fake_update(
        _root: Path,
        *,
        all_modules: bool,
        on_progress: Callable[..., None],
    ) -> tuple[int, list[str]]:
        raise SystemExit(143)

    _install_fake_orchestrator(monkeypatch, fake=fake_update)
    exit_code = _wiki_bg_runner.main([str(tmp_path)])
    assert exit_code == 143
    record = wiki_background.read_last_refresh(tmp_path)
    assert record is not None
    assert record.log_tail is None
