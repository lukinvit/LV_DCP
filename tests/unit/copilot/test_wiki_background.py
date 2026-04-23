"""Unit tests for ``libs.copilot.wiki_background``."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, ClassVar

import pytest
from libs.copilot import wiki_background


class _StubPopen:
    """Minimal ``subprocess.Popen``-shaped stub for tests.

    Captures the argv and returns a fake PID so ``start_background_refresh``
    can write a lock file without actually forking a process. Tests that
    want to assert "refresh is running" monkeypatch ``os.kill`` (via
    :func:`wiki_background._pid_alive`) to return True.
    """

    instances: ClassVar[list[_StubPopen]] = []

    def __init__(self, args: list[str], **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
        self.pid = 99991  # arbitrary sentinel
        _StubPopen.instances.append(self)


@pytest.fixture(autouse=True)
def _reset_stub_instances() -> None:
    _StubPopen.instances.clear()


def _make_project(root: Path) -> None:
    (root / ".context" / "wiki").mkdir(parents=True, exist_ok=True)


def test_read_status_returns_not_in_progress_when_no_lock(tmp_path: Path) -> None:
    _make_project(tmp_path)
    status = wiki_background.read_status(tmp_path)
    assert status.in_progress is False
    assert status.pid is None
    assert status.lock_path is None
    assert status.stale is False


def test_start_background_refresh_writes_lock_and_returns_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_project(tmp_path)
    # Pretend the stub PID is alive so read_status confirms in_progress.
    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: True)

    status = wiki_background.start_background_refresh(tmp_path, _popen=_StubPopen)  # type: ignore[arg-type]

    assert status.in_progress is True
    assert status.pid == 99991
    assert status.lock_path is not None and status.lock_path.exists()

    payload = json.loads(status.lock_path.read_text(encoding="utf-8"))
    assert payload["pid"] == 99991
    assert isinstance(payload["started_at"], float)
    assert payload["all_modules"] is False

    # Exactly one Popen was created.
    assert len(_StubPopen.instances) == 1
    argv = _StubPopen.instances[0].args
    assert argv[1:4] == ["-m", "libs.copilot._wiki_bg_runner", str(tmp_path.resolve())]
    assert "--all" not in argv


def test_start_background_refresh_passes_all_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_project(tmp_path)
    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: True)
    wiki_background.start_background_refresh(tmp_path, all_modules=True, _popen=_StubPopen)  # type: ignore[arg-type]
    assert _StubPopen.instances[0].args[-1] == "--all"


def test_start_background_refresh_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Second call returns the existing status and does not fork a new process."""
    _make_project(tmp_path)
    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: True)
    wiki_background.start_background_refresh(tmp_path, _popen=_StubPopen)  # type: ignore[arg-type]
    status_2 = wiki_background.start_background_refresh(tmp_path, _popen=_StubPopen)  # type: ignore[arg-type]

    assert status_2.in_progress is True
    # Exactly one Popen fired in total.
    assert len(_StubPopen.instances) == 1


def test_read_status_detects_stale_lock_by_dead_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lock file owned by a dead PID is reported as stale, not in-progress."""
    _make_project(tmp_path)
    lock = tmp_path / ".context" / "wiki" / ".refresh.lock"
    lock.write_text(
        json.dumps({"pid": 99991, "started_at": time.time(), "all_modules": False}),
        encoding="utf-8",
    )
    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: False)

    status = wiki_background.read_status(tmp_path)
    assert status.in_progress is False
    assert status.stale is True
    assert status.pid == 99991


def test_read_status_detects_stale_lock_by_age(tmp_path: Path) -> None:
    """Lock file older than 1 h is reported as stale even if its PID is alive."""
    _make_project(tmp_path)
    lock = tmp_path / ".context" / "wiki" / ".refresh.lock"
    very_old = time.time() - (wiki_background._STALE_LOCK_AFTER_SECONDS + 10)
    lock.write_text(
        json.dumps({"pid": os.getpid(), "started_at": very_old, "all_modules": False}),
        encoding="utf-8",
    )

    status = wiki_background.read_status(tmp_path)
    assert status.in_progress is False
    assert status.stale is True


def test_start_background_refresh_clears_stale_lock_before_relaunching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_project(tmp_path)
    lock = tmp_path / ".context" / "wiki" / ".refresh.lock"
    lock.write_text(
        json.dumps({"pid": 42, "started_at": time.time(), "all_modules": False}),
        encoding="utf-8",
    )
    # Dead PID → stale. A fresh call replaces the lock.
    monkeypatch.setattr(wiki_background, "_pid_alive", lambda pid: pid == 99991)
    status = wiki_background.start_background_refresh(tmp_path, _popen=_StubPopen)  # type: ignore[arg-type]

    assert status.in_progress is True
    payload = json.loads(lock.read_text(encoding="utf-8"))
    assert payload["pid"] == 99991  # the fresh PID, not 42


def test_is_refresh_in_progress_is_thin_wrapper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_project(tmp_path)
    assert wiki_background.is_refresh_in_progress(tmp_path) is False
    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: True)
    wiki_background.start_background_refresh(tmp_path, _popen=_StubPopen)  # type: ignore[arg-type]
    assert wiki_background.is_refresh_in_progress(tmp_path) is True


def test_start_writes_initial_phase_and_surfaces_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fresh spawn → phase='starting', 0 modules done, no current module."""
    _make_project(tmp_path)
    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: True)
    wiki_background.start_background_refresh(tmp_path, _popen=_StubPopen)  # type: ignore[arg-type]

    status = wiki_background.read_status(tmp_path)
    assert status.in_progress is True
    assert status.phase == wiki_background.PHASE_STARTING
    assert status.modules_total is None
    assert status.modules_done == 0
    assert status.current_module is None


def test_write_progress_merges_into_existing_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """write_progress must preserve pid/started_at and update progress fields."""
    _make_project(tmp_path)
    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: True)
    wiki_background.start_background_refresh(tmp_path, _popen=_StubPopen)  # type: ignore[arg-type]

    wiki_background.write_progress(
        tmp_path,
        phase=wiki_background.PHASE_GENERATING,
        modules_total=12,
        modules_done=3,
        current_module="libs/foo",
    )
    status = wiki_background.read_status(tmp_path)
    assert status.pid == 99991  # preserved
    assert status.phase == wiki_background.PHASE_GENERATING
    assert status.modules_total == 12
    assert status.modules_done == 3
    assert status.current_module == "libs/foo"


def test_write_progress_allows_resetting_current_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Passing current_module=None (e.g. between modules) must clear the field."""
    _make_project(tmp_path)
    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: True)
    wiki_background.start_background_refresh(tmp_path, _popen=_StubPopen)  # type: ignore[arg-type]
    wiki_background.write_progress(
        tmp_path,
        phase=wiki_background.PHASE_GENERATING,
        modules_total=5,
        modules_done=2,
        current_module="libs/foo",
    )
    wiki_background.write_progress(
        tmp_path,
        phase=wiki_background.PHASE_GENERATING,
        modules_total=5,
        modules_done=3,
        current_module=None,
    )
    status = wiki_background.read_status(tmp_path)
    assert status.modules_done == 3
    assert status.current_module is None


def test_write_progress_uses_atomic_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Confirm write_progress never leaves a torn lock on disk."""
    _make_project(tmp_path)
    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: True)
    wiki_background.start_background_refresh(tmp_path, _popen=_StubPopen)  # type: ignore[arg-type]
    lock = tmp_path / ".context" / "wiki" / ".refresh.lock"
    tmp_marker = lock.with_suffix(lock.suffix + ".tmp")

    wiki_background.write_progress(
        tmp_path,
        phase=wiki_background.PHASE_GENERATING,
        modules_total=3,
        modules_done=1,
        current_module="libs/foo",
    )
    # After a successful rename, no orphaned .tmp must remain.
    assert lock.exists()
    assert not tmp_marker.exists()


def test_cancel_sends_sigterm_to_live_pid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """cancel_background_refresh issues SIGTERM to the lock's PID."""
    import signal

    _make_project(tmp_path)
    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: True)
    wiki_background.start_background_refresh(tmp_path, _popen=_StubPopen)  # type: ignore[arg-type]

    kills: list[tuple[int, int]] = []

    def _fake_kill(pid: int, sig: int) -> None:
        kills.append((pid, sig))

    monkeypatch.setattr("libs.copilot.wiki_background.os.kill", _fake_kill)
    status = wiki_background.cancel_background_refresh(tmp_path)
    assert status.pid == 99991
    # The signal-0 liveness probe fires first (from read_status), then SIGTERM.
    assert (99991, signal.SIGTERM) in kills


def test_cancel_is_noop_when_no_refresh_running(tmp_path: Path) -> None:
    _make_project(tmp_path)
    status = wiki_background.cancel_background_refresh(tmp_path)
    assert status.in_progress is False
    assert status.pid is None


def test_cancel_clears_stale_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale lock (dead PID) left behind gets cleaned up by cancel()."""
    _make_project(tmp_path)
    lock = tmp_path / ".context" / "wiki" / ".refresh.lock"
    lock.write_text(
        json.dumps({"pid": 99991, "started_at": time.time(), "all_modules": False}),
        encoding="utf-8",
    )
    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: False)

    status = wiki_background.cancel_background_refresh(tmp_path)
    assert status.stale is True
    assert not lock.exists()
