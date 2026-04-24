"""Tests for the `ctx registry ls` CLI group (v0.8.32)."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest
import yaml
from apps.cli.main import app
from typer.testing import CliRunner


def _seed_cache(root: Path) -> None:
    ctx = root / ".context"
    ctx.mkdir(parents=True, exist_ok=True)
    db = ctx / "cache.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE retrieval_traces ("
        "trace_id TEXT, timestamp REAL, mode TEXT, coverage TEXT, trace_json TEXT)"
    )
    conn.execute(
        "INSERT INTO retrieval_traces VALUES (?, ?, ?, ?, ?)",
        ("t0", time.time(), "navigate", "high", "{}"),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    real = tmp_path / "X5_BM"
    transient = tmp_path / "LV_DCP" / ".claude" / "worktrees" / "v0.8.32-abc"
    _seed_cache(real)
    transient.mkdir(parents=True)
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "projects": [
                    {"root": str(real), "registered_at_iso": "2026-04-24T00:00:00Z"},
                    {"root": str(transient), "registered_at_iso": "2026-04-24T00:00:00Z"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(path))
    return path


def test_registry_ls_text_default(cfg: Path) -> None:
    result = CliRunner().invoke(app, ["registry", "ls"])
    assert result.exit_code == 0, result.stdout
    assert "X5_BM" in result.stdout
    assert "v0.8.32-abc" in result.stdout
    assert "real" in result.stdout
    assert "transient" in result.stdout


def test_registry_ls_json_shape(cfg: Path) -> None:
    result = CliRunner().invoke(app, ["registry", "ls", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert len(payload) == 2
    kinds = {row["kind"] for row in payload}
    assert kinds == {"real", "transient"}
    for row in payload:
        for key in ("name", "root", "kind", "scanned", "packs_7d", "packs_total"):
            assert key in row


def test_registry_ls_kind_filter_real(cfg: Path) -> None:
    result = CliRunner().invoke(app, ["registry", "ls", "--kind", "real", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert len(payload) == 1
    assert payload[0]["kind"] == "real"


def test_registry_ls_kind_filter_transient(cfg: Path) -> None:
    result = CliRunner().invoke(app, ["registry", "ls", "--kind", "transient", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert len(payload) == 1
    assert payload[0]["kind"] == "transient"


def test_registry_ls_rejects_invalid_kind(cfg: Path) -> None:
    result = CliRunner().invoke(app, ["registry", "ls", "--kind", "bogus"])
    assert result.exit_code == 2
    assert "must be 'real', 'transient', or 'all'" in result.stdout or "must be" in (
        result.stderr or ""
    )


def test_registry_ls_stale_surfaces_dormant_entries(cfg: Path) -> None:
    # The transient `v0.8.32-abc` has zero packs and was registered "today"
    # in the fixture, but its `.context/cache.db` is absent → never scanned
    # path → is_stale=True (never-scanned branch).
    result = CliRunner().invoke(app, ["registry", "ls", "--stale", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    names = {row["name"] for row in payload}
    assert "v0.8.32-abc" in names
    # X5_BM has 1 pack → NOT stale.
    assert "X5_BM" not in names
