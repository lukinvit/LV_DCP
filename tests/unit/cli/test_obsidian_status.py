"""Tests for `ctx obsidian status` (text + v0.8.50 ``--json`` scriptability)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from apps.cli.main import app
from typer.testing import CliRunner

# Schema lock for the JSON shape — keeps consumers safe when the vault
# state contract grows new fields. Any divergence here forces an explicit,
# reviewed update to both the helper and this frozenset.
_OBSIDIAN_STATUS_JSON_KEYS = frozenset({"vault", "projects_dir", "projects_dir_exists", "projects"})


def test_obsidian_status_text_unchanged_no_projects_dir(tmp_path: Path) -> None:
    """Text-mode behaviour for a vault without ``Projects/`` must remain the
    legacy "No Projects/ directory found" sentinel — JSON mode is the new
    surface, not a replacement of the existing UX."""
    vault = tmp_path / "vault"
    vault.mkdir()

    result = CliRunner().invoke(app, ["obsidian", "status", "--vault", str(vault)])
    assert result.exit_code == 0, result.stdout
    assert "No Projects/ directory found" in result.stdout
    # Sanity: text mode must not leak JSON syntax.
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)


def test_obsidian_status_text_unchanged_empty_projects_dir(tmp_path: Path) -> None:
    """Text-mode with an empty ``Projects/`` directory keeps the legacy
    "No project directories found." sentinel."""
    vault = tmp_path / "vault"
    (vault / "Projects").mkdir(parents=True)

    result = CliRunner().invoke(app, ["obsidian", "status", "--vault", str(vault)])
    assert result.exit_code == 0, result.stdout
    assert "No project directories found." in result.stdout


def test_obsidian_status_text_unchanged_populated(tmp_path: Path) -> None:
    """Text-mode with two project subdirectories renders the legacy
    indented bullet list with the count header — bytewise stable."""
    vault = tmp_path / "vault"
    projects = vault / "Projects"
    projects.mkdir(parents=True)
    (projects / "AlphaProject").mkdir()
    (projects / "BetaProject").mkdir()
    # A loose file at the projects root must NOT be reported as a project.
    (projects / "loose.md").write_text("not a project", encoding="utf-8")

    result = CliRunner().invoke(app, ["obsidian", "status", "--vault", str(vault)])
    assert result.exit_code == 0, result.stdout
    assert "Projects in vault (2):" in result.stdout
    assert "  - AlphaProject" in result.stdout
    assert "  - BetaProject" in result.stdout
    # No JSON leak in the text path.
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)


def test_obsidian_status_json_no_projects_dir(tmp_path: Path) -> None:
    """JSON mode with no ``Projects/`` directory: the tri-state contract
    surfaces ``projects_dir_exists=False`` and an empty ``projects`` array,
    not the text-mode sentinel string. Exit 0 — a missing ``Projects/`` is
    a valid vault configuration (no syncs yet), not an error."""
    vault = tmp_path / "vault"
    vault.mkdir()

    result = CliRunner().invoke(app, ["obsidian", "status", "--vault", str(vault), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)

    assert isinstance(payload, dict)
    assert set(payload.keys()) == _OBSIDIAN_STATUS_JSON_KEYS
    assert payload["projects_dir_exists"] is False
    assert payload["projects"] == []
    assert payload["vault"].endswith("vault")
    assert payload["projects_dir"].endswith("vault/Projects")


def test_obsidian_status_json_empty_projects_dir(tmp_path: Path) -> None:
    """JSON mode with an empty ``Projects/`` directory: the tri-state
    contract is ``projects_dir_exists=True`` and ``projects=[]`` — distinct
    from the missing-dir case so consumers can tell "vault is configured
    but no projects synced" apart from "vault was never set up"."""
    vault = tmp_path / "vault"
    (vault / "Projects").mkdir(parents=True)

    result = CliRunner().invoke(app, ["obsidian", "status", "--vault", str(vault), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)

    assert isinstance(payload, dict)
    assert set(payload.keys()) == _OBSIDIAN_STATUS_JSON_KEYS
    assert payload["projects_dir_exists"] is True
    assert payload["projects"] == []


def test_obsidian_status_json_emits_well_formed_object(tmp_path: Path) -> None:
    """JSON mode with two registered projects emits the schema-locked
    object: array of sorted directory names, vault and projects_dir paths
    stringified, loose files at the projects root excluded."""
    vault = tmp_path / "vault"
    projects = vault / "Projects"
    projects.mkdir(parents=True)
    (projects / "BetaProject").mkdir()
    (projects / "AlphaProject").mkdir()
    # Loose file must be excluded from the projects list.
    (projects / "loose.md").write_text("not a project", encoding="utf-8")

    result = CliRunner().invoke(app, ["obsidian", "status", "--vault", str(vault), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)

    assert isinstance(payload, dict)
    assert set(payload.keys()) == _OBSIDIAN_STATUS_JSON_KEYS
    assert payload["projects_dir_exists"] is True
    # Sorted alphabetically — locks ordering so consumers can rely on
    # stable iteration without re-sorting.
    assert payload["projects"] == ["AlphaProject", "BetaProject"]
    assert isinstance(payload["vault"], str)
    assert isinstance(payload["projects_dir"], str)
