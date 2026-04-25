"""Tests for `ctx watch` CLI subgroup (v0.8.35 allow_transient wiring,
v0.8.49 ``ctx watch list --json`` scriptability)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from apps.cli.main import app
from typer.testing import CliRunner

# Schema lock for the JSON shape — keeps consumers safe when ProjectEntry
# grows new fields. Any divergence here forces an explicit, reviewed update.
_WATCH_LIST_JSON_KEYS = frozenset(
    {"root", "registered_at_iso", "last_scan_at_iso", "last_scan_status"}
)


@pytest.fixture
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect DEFAULT_CONFIG_PATH so tests never touch the real registry."""
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr("apps.cli.commands.watch_cmd.DEFAULT_CONFIG_PATH", config_path)
    return config_path


def test_watch_add_registers_worktree_path_explicitly(
    tmp_path: Path,
    _isolated_config: Path,
) -> None:
    """`ctx watch add <worktree>` is explicit user intent — the CLI must pass
    ``allow_transient=True`` so the transient filter in ``add_project`` does
    not silently drop the registration. Without this wiring the user would
    type `ctx watch add ./.claude/worktrees/...` and see no entry in
    ``ctx registry ls`` — a confusing silent no-op regression.
    """
    worktree = tmp_path / ".claude" / "worktrees" / "v0.8.35-wt"
    worktree.mkdir(parents=True)

    result = CliRunner().invoke(app, ["watch", "add", str(worktree)])
    assert result.exit_code == 0, result.stdout

    from libs.core.projects_config import load_config

    cfg = load_config(_isolated_config)
    assert len(cfg.projects) == 1
    assert str(cfg.projects[0].root).endswith("v0.8.35-wt")


def test_watch_add_registers_normal_project(
    tmp_path: Path,
    _isolated_config: Path,
) -> None:
    """Baseline: normal paths must still register via `ctx watch add`."""
    project = tmp_path / "MyProject"
    project.mkdir()

    result = CliRunner().invoke(app, ["watch", "add", str(project)])
    assert result.exit_code == 0, result.stdout

    from libs.core.projects_config import load_config

    cfg = load_config(_isolated_config)
    assert len(cfg.projects) == 1
    assert cfg.projects[0].root.name == "MyProject"


def test_watch_list_text_output_unchanged_empty_registry(
    _isolated_config: Path,
) -> None:
    """Text-mode output for an empty registry must remain the human-friendly
    "no projects registered" sentinel — JSON mode is the *new* surface,
    not a replacement of the existing UX."""
    result = CliRunner().invoke(app, ["watch", "list"])
    assert result.exit_code == 0, result.stdout
    assert "no projects registered" in result.stdout


def test_watch_list_text_output_unchanged_with_projects(
    tmp_path: Path,
    _isolated_config: Path,
) -> None:
    """Text-mode output with registered projects must remain the indented
    path list — adding ``--json`` must not regress the default render."""
    project = tmp_path / "AlphaProject"
    project.mkdir()
    add_result = CliRunner().invoke(app, ["watch", "add", str(project)])
    assert add_result.exit_code == 0, add_result.stdout

    result = CliRunner().invoke(app, ["watch", "list"])
    assert result.exit_code == 0, result.stdout
    assert "AlphaProject" in result.stdout
    # Sanity: text mode must not leak JSON syntax.
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)


def test_watch_list_json_empty_registry_returns_empty_array(
    _isolated_config: Path,
) -> None:
    """Empty registry under ``--json`` returns ``[]`` (not the text sentinel)
    so consumers can rely on the array shape unconditionally."""
    result = CliRunner().invoke(app, ["watch", "list", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload == []


def test_watch_list_json_emits_well_formed_array(
    tmp_path: Path,
    _isolated_config: Path,
) -> None:
    """Two registered projects → bare JSON array, two objects, schema-locked
    keys, ``root`` stringified, timestamps preserved as ISO strings."""
    project_a = tmp_path / "AlphaProject"
    project_a.mkdir()
    project_b = tmp_path / "BetaProject"
    project_b.mkdir()
    for path in (project_a, project_b):
        add_result = CliRunner().invoke(app, ["watch", "add", str(path)])
        assert add_result.exit_code == 0, add_result.stdout

    result = CliRunner().invoke(app, ["watch", "list", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert len(payload) == 2
    for row in payload:
        assert isinstance(row, dict)
        assert set(row.keys()) == _WATCH_LIST_JSON_KEYS
        assert isinstance(row["root"], str)
        # registered_at_iso is required and never null.
        assert isinstance(row["registered_at_iso"], str)
        assert row["registered_at_iso"]
        # last_scan_at_iso is None until the first scan completes;
        # last_scan_status defaults to "pending" on registration.
        assert row["last_scan_at_iso"] is None
        assert row["last_scan_status"] == "pending"
    roots = {row["root"] for row in payload}
    assert any(r.endswith("AlphaProject") for r in roots)
    assert any(r.endswith("BetaProject") for r in roots)
