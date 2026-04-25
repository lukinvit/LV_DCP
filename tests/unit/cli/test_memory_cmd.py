"""Tests for the `ctx memory` CLI group."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from apps.cli.main import app
from libs.memory.store import accept_memory, propose_memory
from typer.testing import CliRunner

# Schema-locked surface for `ctx memory list --json`. Adding a key requires
# bumping this set + the helper in `apps/cli/commands/memory_cmd.py`. Mirrors
# the `Memory` dataclass minus `body` (recoverable via the `path` field).
_MEMORY_LIST_JSON_KEYS = frozenset(
    {"id", "status", "topic", "tags", "created_at_iso", "created_by", "path"}
)


@pytest.fixture
def project_with_memory(tmp_path: Path) -> tuple[Path, str]:
    m = propose_memory(tmp_path, topic="Auth flow", body="JWT rotation notes.")
    return tmp_path, m.id


def test_memory_list_shows_proposed(project_with_memory: tuple[Path, str]) -> None:
    project, mem_id = project_with_memory
    runner = CliRunner()
    result = runner.invoke(app, ["memory", "list", "--project", str(project)])
    assert result.exit_code == 0, result.stdout
    assert mem_id in result.stdout
    assert "proposed" in result.stdout


def test_memory_list_status_filter(project_with_memory: tuple[Path, str]) -> None:
    project, _ = project_with_memory
    runner = CliRunner()
    accepted = runner.invoke(
        app, ["memory", "list", "--project", str(project), "--status", "accepted"]
    )
    assert accepted.exit_code == 0
    # No accepted memories yet — listing must say so.
    assert "(no memories)" in accepted.stdout


def test_memory_accept_flips_status(project_with_memory: tuple[Path, str]) -> None:
    project, mem_id = project_with_memory
    runner = CliRunner()
    result = runner.invoke(app, ["memory", "accept", mem_id, "--project", str(project)])
    assert result.exit_code == 0, result.stdout
    assert "accepted" in result.stdout.lower()
    # Verify via list filter.
    listed = runner.invoke(
        app, ["memory", "list", "--project", str(project), "--status", "accepted"]
    )
    assert mem_id in listed.stdout


def test_memory_reject_flips_status(project_with_memory: tuple[Path, str]) -> None:
    project, mem_id = project_with_memory
    runner = CliRunner()
    result = runner.invoke(app, ["memory", "reject", mem_id, "--project", str(project)])
    assert result.exit_code == 0, result.stdout
    assert "rejected" in result.stdout.lower()


def test_memory_accept_unknown_id_exits_nonzero(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["memory", "accept", "mem_unknown_id", "--project", str(tmp_path)],
    )
    assert result.exit_code == 2


def test_memory_list_json_emits_well_formed_array(
    project_with_memory: tuple[Path, str],
) -> None:
    """`--json` returns a bare JSON array; each entry mirrors the locked schema."""
    project, mem_id = project_with_memory
    runner = CliRunner()
    result = runner.invoke(app, ["memory", "list", "--project", str(project), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert len(payload) == 1
    entry = payload[0]
    assert set(entry.keys()) == _MEMORY_LIST_JSON_KEYS
    assert entry["id"] == mem_id
    assert entry["status"] == "proposed"
    assert entry["topic"] == "Auth flow"
    # `tags` must be a JSON array even if the Memory dataclass stores it as
    # a tuple — locks the serializer behaviour for downstream consumers.
    assert isinstance(entry["tags"], list)
    # `path` is the absolute on-disk markdown path so scripts can `cat` it
    # to recover the (intentionally omitted) `body`.
    assert entry["path"].endswith(".md")


def test_memory_list_json_empty_returns_bare_list(tmp_path: Path) -> None:
    """No memories → `[]`, never `null` and never the prose `(no memories)` marker."""
    runner = CliRunner()
    result = runner.invoke(app, ["memory", "list", "--project", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload == []
    # Prose marker from the human-readable path must NOT leak into JSON output.
    assert "(no memories)" not in result.stdout


def test_memory_list_json_composes_with_status_filter(
    project_with_memory: tuple[Path, str],
) -> None:
    """`--json` and `--status` compose: only matching entries land in the array."""
    project, mem_id = project_with_memory
    runner = CliRunner()

    # Before accept: filter for accepted yields `[]` (not the `proposed` row).
    accepted_before = runner.invoke(
        app,
        ["memory", "list", "--project", str(project), "--status", "accepted", "--json"],
    )
    assert accepted_before.exit_code == 0, accepted_before.stdout
    assert json.loads(accepted_before.stdout) == []

    # Flip the status, then re-query — the row should now show up under accepted
    # and disappear from proposed.
    accept_memory(project, mem_id)

    accepted_after = runner.invoke(
        app,
        ["memory", "list", "--project", str(project), "--status", "accepted", "--json"],
    )
    assert accepted_after.exit_code == 0, accepted_after.stdout
    payload = json.loads(accepted_after.stdout)
    assert len(payload) == 1
    assert payload[0]["id"] == mem_id
    assert payload[0]["status"] == "accepted"

    proposed_after = runner.invoke(
        app,
        ["memory", "list", "--project", str(project), "--status", "proposed", "--json"],
    )
    assert proposed_after.exit_code == 0, proposed_after.stdout
    assert json.loads(proposed_after.stdout) == []
