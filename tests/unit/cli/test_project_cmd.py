"""Tests for the `ctx project` CLI group (spec-011)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from apps.cli.main import app
from libs.scanning.scanner import scan_project
from typer.testing import CliRunner


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect both LVDCP_CONFIG_PATH and ``~`` at a tmp dir with Qdrant off.

    Several primitives (scanner, embedder) still hard-code
    ``Path.home() / ".lvdcp" / "config.yaml"`` — overriding ``HOME`` is
    the only way to keep the tests offline.
    """
    home = tmp_path / "home"
    (home / ".lvdcp").mkdir(parents=True)
    cfg = home / ".lvdcp" / "config.yaml"
    cfg.write_text(yaml.safe_dump({"qdrant": {"enabled": False}}))
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda _cls: home))


def _seed_project(root: Path) -> None:
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "auth.py").write_text(
        "def login() -> bool:\n    return True\n", encoding="utf-8"
    )


def test_check_on_empty_dir_prints_not_scanned(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    runner = CliRunner()
    result = runner.invoke(app, ["project", "check", str(proj)])
    assert result.exit_code == 0, result.stdout
    assert "scanned:         False" in result.stdout
    assert "not_scanned" in result.stdout


def test_check_json_flag_parses(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)
    scan_project(proj, mode="full")

    runner = CliRunner()
    result = runner.invoke(app, ["project", "check", str(proj), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["scanned"] is True
    assert payload["files"] >= 1


def test_refresh_runs_scan_and_skips_wiki_with_flag(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)

    runner = CliRunner()
    result = runner.invoke(app, ["project", "refresh", str(proj), "--no-wiki"])
    assert result.exit_code == 0, result.stdout
    assert "refreshed=False" in result.stdout
    # The scan should have run.
    assert (proj / ".context" / "cache.db").exists()


def test_wiki_subcommand_read_only_without_refresh(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)
    scan_project(proj, mode="full")

    runner = CliRunner()
    result = runner.invoke(app, ["project", "wiki", str(proj)])
    assert result.exit_code == 0, result.stdout
    assert "wiki present:" in result.stdout


def test_wiki_subcommand_json_shape_is_check_report(tmp_path: Path) -> None:
    """Pin the read-only ``ctx project wiki --json`` contract.

    The read-only path emits a full :class:`CopilotCheckReport`; scripts
    that want a stable schema should call ``ctx project check --json``.
    This test documents the current contract so a future change must
    update it deliberately.
    """
    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)
    scan_project(proj, mode="full")

    runner = CliRunner()
    result = runner.invoke(app, ["project", "wiki", str(proj), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    # Shape is CopilotCheckReport — must carry these keys.
    for key in (
        "project_root",
        "project_name",
        "scanned",
        "wiki_present",
        "wiki_dirty_modules",
        "qdrant_enabled",
        "degraded_modes",
    ):
        assert key in payload, f"missing check-report key: {key}"
    # And must NOT carry refresh-only keys.
    assert "wiki_refreshed" not in payload
    assert "scan_files" not in payload


def test_ask_rejects_invalid_mode(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)
    scan_project(proj, mode="full")

    runner = CliRunner()
    result = runner.invoke(app, ["project", "ask", str(proj), "q", "--mode", "bogus"])
    # Rejection is the only contract — `typer.echo(..., err=True)` lands
    # on stderr and the exit code must be 2. The exact message lives on
    # stderr (output varies between CliRunner versions).
    assert result.exit_code == 2


def test_ask_not_scanned_hard_degrade(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()

    runner = CliRunner()
    result = runner.invoke(app, ["project", "ask", str(proj), "anything"])
    assert result.exit_code == 0, result.stdout
    assert "coverage: unavailable" in result.stdout
    assert "not_scanned" in result.stdout or "not scanned" in result.stdout.lower()


def test_ask_happy_path_prints_pack_and_suggestions(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)
    scan_project(proj, mode="full")

    runner = CliRunner()
    result = runner.invoke(app, ["project", "ask", str(proj), "login"])
    assert result.exit_code == 0, result.stdout
    # Pack markdown contains a canonical header.
    assert "Context pack" in result.stdout or "context pack" in result.stdout.lower()
    # Qdrant is off via _isolated_config → we should see the hint.
    assert "trace_id" in result.stdout


def test_refresh_wiki_background_flag_spawns_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ctx project refresh --wiki-background`` must not run the sync wiki path."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)

    def _boom_wiki(*_a: object, **_kw: object) -> None:  # pragma: no cover — defensive
        raise AssertionError("sync wiki must not run with --wiki-background")

    monkeypatch.setattr("libs.copilot.orchestrator._run_wiki_update_in_process", _boom_wiki)

    from libs.copilot import wiki_background

    class _StubPopen:
        def __init__(self, args: list[str], **_kw: object) -> None:
            self.args = args
            self.pid = 55551

    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr("libs.copilot.wiki_background.subprocess.Popen", _StubPopen)

    runner = CliRunner()
    result = runner.invoke(app, ["project", "refresh", str(proj), "--wiki-background"])
    assert result.exit_code == 0, result.stdout
    assert "bg_started=True" in result.stdout
    assert "refreshed=False" in result.stdout
    assert (proj / ".context" / "wiki" / ".refresh.lock").exists()


def test_check_shows_bg_refresh_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``ctx project check`` surfaces ``bg_refresh=true (...)`` when lock is live."""
    import json as _json
    import time as _time

    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)
    scan_project(proj, mode="full")

    wiki_dir = proj / ".context" / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / ".refresh.lock").write_text(
        _json.dumps({"pid": 11111, "started_at": _time.time(), "all_modules": False}),
        encoding="utf-8",
    )
    from libs.copilot import wiki_background

    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: True)

    runner = CliRunner()
    result = runner.invoke(app, ["project", "check", str(proj)])
    assert result.exit_code == 0, result.stdout
    assert "bg_refresh=true" in result.stdout
    assert "pid=11111" in result.stdout


def test_check_shows_progress_when_runner_emitted_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the runner has already written progress, check surfaces N/M + current module."""
    import json as _json
    import time as _time

    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)
    scan_project(proj, mode="full")

    wiki_dir = proj / ".context" / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / ".refresh.lock").write_text(
        _json.dumps(
            {
                "pid": 22222,
                "started_at": _time.time(),
                "all_modules": False,
                "phase": "generating",
                "modules_total": 12,
                "modules_done": 3,
                "current_module": "libs/foo",
            }
        ),
        encoding="utf-8",
    )
    from libs.copilot import wiki_background

    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: True)

    runner = CliRunner()
    result = runner.invoke(app, ["project", "check", str(proj)])
    assert result.exit_code == 0, result.stdout
    assert "generating 3/12" in result.stdout
    assert '"libs/foo"' in result.stdout
    assert "pid=22222" in result.stdout


def test_wiki_stop_sends_sigterm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``ctx project wiki <path> --stop`` sends SIGTERM and reports the PID."""
    import json as _json
    import signal
    import time as _time

    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)

    wiki_dir = proj / ".context" / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / ".refresh.lock").write_text(
        _json.dumps({"pid": 33333, "started_at": _time.time(), "all_modules": False}),
        encoding="utf-8",
    )

    from libs.copilot import wiki_background

    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: True)
    kills: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "libs.copilot.wiki_background.os.kill",
        lambda pid, sig: kills.append((pid, sig)),
    )

    runner = CliRunner()
    result = runner.invoke(app, ["project", "wiki", str(proj), "--stop"])
    assert result.exit_code == 0, result.stdout
    assert (33333, signal.SIGTERM) in kills
    assert "SIGTERM sent to pid=33333" in result.stdout


def test_wiki_stop_no_refresh_running_is_noop(tmp_path: Path) -> None:
    """``--stop`` on an idle project must print a clean message, not crash."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)

    runner = CliRunner()
    result = runner.invoke(app, ["project", "wiki", str(proj), "--stop"])
    assert result.exit_code == 0, result.stdout
    assert "none running" in result.stdout


def test_check_watch_idle_emits_one_snapshot_and_exits(tmp_path: Path) -> None:
    """With no refresh running, --watch prints once and returns fast."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)
    scan_project(proj, mode="full")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["project", "check", str(proj), "--watch", "--interval", "0.3", "--max-duration", "5"],
    )
    assert result.exit_code == 0, result.stdout
    # Exactly one "project:" header — no repeated snapshot.
    assert result.stdout.count("project: proj") == 1
    assert "bg_refresh=false" in result.stdout


def test_check_watch_polls_until_lock_disappears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live-tail path: lock goes away on the second sleep → 3 snapshots printed."""
    import json as _json
    import time as _time

    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)
    scan_project(proj, mode="full")

    lock = proj / ".context" / "wiki" / ".refresh.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(
        _json.dumps(
            {
                "pid": 81881,
                "started_at": _time.time(),
                "all_modules": False,
                "phase": "generating",
                "modules_total": 2,
                "modules_done": 1,
                "current_module": "libs/foo",
            }
        ),
        encoding="utf-8",
    )
    from libs.copilot import wiki_background

    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: True)

    sleep_calls = {"n": 0}

    def _fake_sleep(_sec: float) -> None:
        sleep_calls["n"] += 1
        if sleep_calls["n"] == 2:
            lock.unlink()  # runner "finished"

    # CLI uses orchestrator's time.sleep by default — patch it at the source.
    monkeypatch.setattr("libs.copilot.orchestrator.time.sleep", _fake_sleep)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "project",
            "check",
            str(proj),
            "--watch",
            "--interval",
            "0.2",
            "--max-duration",
            "5",
        ],
    )
    assert result.exit_code == 0, result.stdout
    # Three snapshots: running, running, idle.
    assert result.stdout.count("project: proj") == 3
    # First + second render the progress line; the last renders bg_refresh=false.
    assert 'generating 1/2 "libs/foo"' in result.stdout
    assert "bg_refresh=false" in result.stdout
    assert sleep_calls["n"] == 2


# ---- _render_bg_refresh last-run formatting (v0.8.4) ----------------------


def _minimal_report(**overrides: object):  # type: ignore[no-untyped-def]
    """Build a minimal ``CopilotCheckReport`` for renderer unit tests.

    Only the fields ``_render_bg_refresh`` consults are worth setting;
    the rest take Pydantic defaults so the factory stays compact.
    """
    from libs.copilot import CopilotCheckReport

    base: dict[str, object] = {
        "project_root": "/tmp/p",
        "project_name": "p",
        "scanned": True,
        "stale": False,
        "wiki_present": True,
        "qdrant_enabled": False,
    }
    base.update(overrides)
    return CopilotCheckReport(**base)  # type: ignore[arg-type]


def test_render_bg_refresh_idle_without_last_run_returns_false() -> None:
    from apps.cli.commands.project_cmd import _render_bg_refresh

    assert _render_bg_refresh(_minimal_report()) == "false"


def test_render_bg_refresh_idle_with_clean_last_run() -> None:
    import time as _time

    from apps.cli.commands.project_cmd import _render_bg_refresh

    now = _time.time()
    report = _minimal_report(
        wiki_last_refresh_completed_at=now - 200.0,
        wiki_last_refresh_exit_code=0,
        wiki_last_refresh_modules_updated=12,
        wiki_last_refresh_elapsed_seconds=47.0,
    )
    rendered = _render_bg_refresh(report)
    assert rendered.startswith("false (last: ok 12 modules 47s,")
    assert "min ago" in rendered  # 200s → "3 min ago"


def test_render_bg_refresh_idle_with_crashed_last_run() -> None:
    import time as _time

    from apps.cli.commands.project_cmd import _render_bg_refresh

    now = _time.time()
    report = _minimal_report(
        wiki_last_refresh_completed_at=now - 5.0,
        wiki_last_refresh_exit_code=1,
        wiki_last_refresh_modules_updated=3,
        wiki_last_refresh_elapsed_seconds=12.0,
    )
    rendered = _render_bg_refresh(report)
    assert "FAILED exit=1" in rendered
    assert "see .refresh.log" in rendered


def test_render_bg_refresh_idle_with_sigterm_last_run() -> None:
    import time as _time

    from apps.cli.commands.project_cmd import _render_bg_refresh

    now = _time.time()
    report = _minimal_report(
        wiki_last_refresh_completed_at=now - 5.0,
        wiki_last_refresh_exit_code=143,
        wiki_last_refresh_modules_updated=3,
        wiki_last_refresh_elapsed_seconds=12.0,
    )
    rendered = _render_bg_refresh(report)
    assert "cancelled after 3 modules 12s" in rendered


def test_render_bg_refresh_running_ignores_last_run() -> None:
    """While a refresh is in progress, we only show live progress."""
    from apps.cli.commands.project_cmd import _render_bg_refresh

    report = _minimal_report(
        wiki_refresh_in_progress=True,
        wiki_refresh_phase="generating",
        wiki_refresh_modules_total=12,
        wiki_refresh_modules_done=3,
        wiki_refresh_pid=1234,
        wiki_last_refresh_completed_at=1_700_000_000.0,
        wiki_last_refresh_exit_code=1,
        wiki_last_refresh_modules_updated=4,
        wiki_last_refresh_elapsed_seconds=7.0,
    )
    rendered = _render_bg_refresh(report)
    assert rendered.startswith("true (generating")
    assert "last:" not in rendered  # live view supersedes the last-run hint


# ---- log tail rendering (v0.8.5) ------------------------------------------


def test_check_renders_log_tail_on_failed_run(tmp_path: Path) -> None:
    """A crashed last-run surfaces indented ``log tail:`` lines in ``ctx project check``."""
    from libs.copilot import write_last_refresh

    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)
    scan_project(proj, mode="full")
    (proj / ".context" / "wiki").mkdir(parents=True, exist_ok=True)
    write_last_refresh(
        proj,
        exit_code=1,
        modules_updated=2,
        elapsed_seconds=1.5,
        log_tail=[
            "Traceback (most recent call last):",
            '  File "x.py", line 10, in _run',
            "RuntimeError: boom",
        ],
    )

    runner = CliRunner()
    result = runner.invoke(app, ["project", "check", str(proj)])
    assert result.exit_code == 0, result.stdout
    assert "FAILED exit=1" in result.stdout
    assert "log tail:" in result.stdout
    assert "RuntimeError: boom" in result.stdout


def test_check_does_not_render_log_tail_on_clean_run(tmp_path: Path) -> None:
    """Clean last-run → no ``log tail:`` block even if someone persisted one."""
    from libs.copilot import write_last_refresh

    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)
    scan_project(proj, mode="full")
    (proj / ".context" / "wiki").mkdir(parents=True, exist_ok=True)
    write_last_refresh(
        proj,
        exit_code=0,
        modules_updated=3,
        elapsed_seconds=2.0,
    )

    runner = CliRunner()
    result = runner.invoke(app, ["project", "check", str(proj)])
    assert result.exit_code == 0, result.stdout
    assert "log tail:" not in result.stdout


def test_check_does_not_render_log_tail_on_sigterm(tmp_path: Path) -> None:
    """SIGTERM last-run → no ``log tail:`` block (cancel label suffices)."""
    from libs.copilot import write_last_refresh

    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)
    scan_project(proj, mode="full")
    (proj / ".context" / "wiki").mkdir(parents=True, exist_ok=True)
    # A SIGTERM path shouldn't have persisted a tail, but even if one snuck
    # through, the renderer suppresses it.
    write_last_refresh(
        proj,
        exit_code=143,
        modules_updated=1,
        elapsed_seconds=0.5,
        log_tail=["something that should not render"],
    )

    runner = CliRunner()
    result = runner.invoke(app, ["project", "check", str(proj)])
    assert result.exit_code == 0, result.stdout
    assert "cancelled" in result.stdout
    assert "log tail:" not in result.stdout
