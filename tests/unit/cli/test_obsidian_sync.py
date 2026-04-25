"""Tests for `ctx obsidian sync` (text + v0.8.53 ``--json`` scriptability)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from apps.cli.main import app
from libs.scanning.scanner import scan_project
from typer.testing import CliRunner

# Schema lock for the JSON shape — mirrors the SyncReport dataclass plus
# the invocation-parameter round-trip fields (vault, project). Any
# divergence here forces an explicit, reviewed update to both the helper
# and this frozenset.
_SYNC_JSON_KEYS = frozenset(
    {
        "vault",
        "project",
        "project_name",
        "pages_written",
        "pages_deleted",
        "duration_seconds",
        "errors",
    }
)


@pytest.fixture
def indexed_project(tmp_path: Path) -> Path:
    """A real scanned project — sync command requires `.context/cache.db`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "core").mkdir()
    (repo / "core" / "main.py").write_text(
        "def hello(name: str) -> str:\n    return f'hello, {name}'\n",
        encoding="utf-8",
    )
    scan_project(repo, mode="full")
    return repo


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    v = tmp_path / "vault"
    v.mkdir()
    return v


def test_obsidian_sync_text_unchanged(indexed_project: Path, vault: Path) -> None:
    """Default text-mode behaviour must remain bytewise stable — JSON mode
    is the new surface, not a replacement of the existing UX. Locks the
    "Synced X to Y / Pages written: N / Duration: ..." three-line footer
    so a future regression that promotes JSON to default would break this
    test instead of silently breaking shell consumers."""
    result = CliRunner().invoke(
        app,
        ["obsidian", "sync", "--vault", str(vault), str(indexed_project)],
    )
    assert result.exit_code == 0, result.stdout
    assert f"Synced {indexed_project.name} to {vault}" in result.stdout
    assert "Pages written:" in result.stdout
    assert "Duration:" in result.stdout
    # Sanity: text mode must not leak JSON syntax — guards against an
    # accidental JSON-as-default flip.
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)


def test_obsidian_sync_json_emits_well_formed_payload(indexed_project: Path, vault: Path) -> None:
    """``ctx obsidian sync ... --json`` emits a single object mirroring
    the SyncReport dataclass: invocation parameters (vault, project) +
    project_name + pages_written + pages_deleted + duration_seconds +
    errors. All keys are schema-locked via the frozenset at module top."""
    result = CliRunner().invoke(
        app,
        ["obsidian", "sync", "--vault", str(vault), str(indexed_project), "--json"],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)

    assert isinstance(payload, dict)
    assert set(payload.keys()) == _SYNC_JSON_KEYS

    # Round-tripped invocation parameters — confirm what this run actually
    # synced without reconstructing it from --vault / project_path.
    assert payload["vault"] == str(vault)
    assert payload["project"] == str(indexed_project)
    assert payload["project_name"] == indexed_project.name

    # SyncReport scalar fields — types locked, but the actual counts
    # depend on the publisher's page set so we only assert shape +
    # non-negative invariants.
    assert isinstance(payload["pages_written"], int)
    assert payload["pages_written"] >= 0
    assert isinstance(payload["pages_deleted"], int)
    assert payload["pages_deleted"] >= 0
    assert isinstance(payload["duration_seconds"], float)
    assert payload["duration_seconds"] >= 0.0

    # Errors is always an array (never null) — `jq -e '.errors == []'`
    # works as the CI gate without a None-guard.
    assert isinstance(payload["errors"], list)
    assert payload["errors"] == []  # clean sync on a fresh fixture


def test_obsidian_sync_json_clean_run_reports_pages_written(
    indexed_project: Path, vault: Path
) -> None:
    """A first-time sync against an empty vault must produce
    ``pages_written > 0`` — locks the canonical "did this sync actually
    do work" signal that ``jq -e '.pages_written > 0'`` will gate on in
    CI scripts. Regression-protects against a future change that
    accidentally short-circuits the publisher into a no-op."""
    result = CliRunner().invoke(
        app,
        ["obsidian", "sync", "--vault", str(vault), str(indexed_project), "--json"],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["pages_written"] > 0
    # And the publisher must actually have written files to disk —
    # cross-check that JSON's ``pages_written`` claim is grounded in
    # the filesystem (not just a bookkeeping number).
    assert (vault / "Projects" / indexed_project.name).is_dir()


def test_obsidian_sync_json_missing_cache_exits_1_and_does_not_emit_json(
    tmp_path: Path, vault: Path
) -> None:
    """``cache.db`` missing is the documented error path: exit 1, message
    on stderr, NO JSON payload on stdout. The ``--json`` flag must NOT
    swallow this hard-error case into a "fake clean" payload — the
    error-vs-success boundary stays at the exit-code gate, same as the
    text mode."""
    plain = tmp_path / "plain"
    plain.mkdir()
    result = CliRunner().invoke(
        app,
        ["obsidian", "sync", "--vault", str(vault), str(plain), "--json"],
    )
    assert result.exit_code == 1
    # CliRunner merges stderr into output by default; either channel
    # must carry the diagnostic.
    combined = result.output + (result.stderr or "")
    assert "cache.db" in combined
    # Stdout must NOT parse as a success-shape SyncReport JSON object —
    # the gate is exit code 1 + stderr message, not a swallowed payload.
    if result.stdout.strip():
        try:
            parsed = json.loads(result.stdout)
            assert not (isinstance(parsed, dict) and "pages_written" in parsed)
        except json.JSONDecodeError:
            pass  # Expected — error path went to stderr, stdout is clean.
