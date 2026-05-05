"""Tests for _install_resume_hooks helper added in T18."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_install_resume_hooks_merges_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    settings = fake_home / ".claude" / "settings.json"
    settings.write_text(json.dumps({"hooks": {}}))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    from apps.cli.commands.mcp_cmd import _install_resume_hooks

    installed = _install_resume_hooks(include_inject=True, include_schedule=False)
    assert any("Stop" in evt for evt in installed.events_added)

    data = json.loads(settings.read_text())
    assert "Stop" in data["hooks"]
    assert "SessionStart" in data["hooks"]


def test_install_resume_hooks_no_inject_skips_sessionstart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    (fake_home / ".claude" / "settings.json").write_text("{}")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    from apps.cli.commands.mcp_cmd import _install_resume_hooks

    installed = _install_resume_hooks(include_inject=False, include_schedule=False)
    assert "SessionStart" not in installed.events_added
