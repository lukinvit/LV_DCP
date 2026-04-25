"""Tests for the `ctx memory` CLI group (v0.8.44 list --json,
v0.8.57 accept --json mutation scriptability,
v0.8.58 reject --json closes the memory-review operator surface)."""

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


# ---- v0.8.57: ``memory accept --json`` mutation scriptability -------------


def test_memory_accept_text_output_unchanged(
    project_with_memory: tuple[Path, str],
) -> None:
    """Default text-mode output must remain bytewise stable: a single
    `accepted: <id>  <topic>` line. Sanity-checks against an accidental
    JSON-as-default flip — would break this test instead of silently
    breaking shell consumers grepping for `accepted:`."""
    project, mem_id = project_with_memory
    result = CliRunner().invoke(app, ["memory", "accept", mem_id, "--project", str(project)])
    assert result.exit_code == 0, result.stdout
    assert f"accepted: {mem_id}" in result.stdout
    # Sanity: text mode must not leak JSON syntax.
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)


def test_memory_accept_json_emits_well_formed_object(
    project_with_memory: tuple[Path, str],
) -> None:
    """`memory accept --json` emits a single object mirroring the v0.8.44
    `memory list --json` per-row schema — same `_MEMORY_LIST_JSON_KEYS`
    frozenset locks the cross-surface invariant. Schema parity between read
    (`list`) and write (`accept`) sides means a future `Memory` field
    addition has one schema-lock to bump, not two.

    The post-mutation `status` field round-trips as `"accepted"` — locks
    the documented "consumer can confirm the state transition landed
    without a follow-up `list --json` call" contract from the docstring.
    """
    project, mem_id = project_with_memory
    result = CliRunner().invoke(
        app, ["memory", "accept", mem_id, "--project", str(project), "--json"]
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)

    assert isinstance(payload, dict)
    # Schema lock — reuses the v0.8.44 frozenset; identical contract on both
    # surfaces. Adding a Memory field requires bumping ONE frozenset.
    assert set(payload.keys()) == _MEMORY_LIST_JSON_KEYS

    # Locked field invariants for the accepted entry:
    assert payload["id"] == mem_id
    # Critical: post-mutation status must round-trip as "accepted" — proves
    # the mutation landed AND was reflected in the emitted payload (not a
    # stale read of the pre-mutation state).
    assert payload["status"] == "accepted"
    assert payload["topic"] == "Auth flow"
    assert isinstance(payload["tags"], list)
    assert payload["path"].endswith(".md")

    # Cross-check via `list --json` — the on-disk state must match the
    # emitted payload. A regression that emitted "accepted" but failed to
    # mutate the file would fail this follow-up read.
    listed = CliRunner().invoke(
        app, ["memory", "list", "--project", str(project), "--status", "accepted", "--json"]
    )
    assert listed.exit_code == 0, listed.stdout
    assert any(row["id"] == mem_id for row in json.loads(listed.stdout))


def test_memory_accept_json_unknown_id_exits_nonzero_no_payload(
    tmp_path: Path,
) -> None:
    """Unknown memory id must exit non-zero in JSON mode (same exit-code 2
    as text mode — `--json` is a render switch, not a semantic change). No
    JSON success-shape payload must reach stdout — the error-vs-success
    boundary stays at the exit-code gate, same v0.8.42-v0.8.56 discipline.

    A regression that swallows `MemoryNotFoundError` into a `{"error": ...}`
    stdout payload (or that exits 0 with `null` stdout) breaks this test.
    """
    result = CliRunner().invoke(
        app,
        ["memory", "accept", "mem_unknown_id", "--project", str(tmp_path), "--json"],
    )
    assert result.exit_code == 2, result.stdout
    # Stdout must NOT parse as a success-shape Memory JSON object.
    if result.stdout.strip():
        try:
            parsed = json.loads(result.stdout)
            # If something parses, it must NOT be a success-shape entry.
            assert not (isinstance(parsed, dict) and "id" in parsed and "status" in parsed)
        except json.JSONDecodeError:
            pass  # Expected — error path went to stderr, stdout has Typer's diagnostic.


def test_memory_accept_json_idempotent_re_accept_returns_accepted_entry(
    project_with_memory: tuple[Path, str],
) -> None:
    """Re-accepting an already-accepted memory must succeed (exit 0) and
    emit the same accepted entry — locks the `accept_memory` library
    semantic that idempotency is the contract (see store.py — accept_memory
    just rewrites the status field, not a state-machine guard). A regression
    that flipped accept_memory into a "must-be-proposed" guard would break
    this test by raising MemoryNotFoundError-style or exiting non-zero on
    the second accept."""
    project, mem_id = project_with_memory

    # First accept — flip the status.
    first = CliRunner().invoke(
        app, ["memory", "accept", mem_id, "--project", str(project), "--json"]
    )
    assert first.exit_code == 0, first.stdout
    first_payload = json.loads(first.stdout)
    assert first_payload["status"] == "accepted"

    # Second accept of the same memory — must succeed and emit the same
    # entry (still accepted). Idempotency check.
    second = CliRunner().invoke(
        app, ["memory", "accept", mem_id, "--project", str(project), "--json"]
    )
    assert second.exit_code == 0, second.stdout
    second_payload = json.loads(second.stdout)
    assert set(second_payload.keys()) == _MEMORY_LIST_JSON_KEYS
    assert second_payload["id"] == mem_id
    assert second_payload["status"] == "accepted"
    # The path must remain stable across the idempotent re-accept — the
    # on-disk file is the same one, not a fresh write to a new location.
    assert second_payload["path"] == first_payload["path"]


# ---- v0.8.58: ``memory reject --json`` closes the memory-review surface ---


def test_memory_reject_text_output_unchanged(
    project_with_memory: tuple[Path, str],
) -> None:
    """Default text-mode output must remain bytewise stable: a single
    `rejected: <id>  <topic>` line. Sanity-checks against an accidental
    JSON-as-default flip — would break this test instead of silently
    breaking shell consumers grepping for `rejected:`."""
    project, mem_id = project_with_memory
    result = CliRunner().invoke(app, ["memory", "reject", mem_id, "--project", str(project)])
    assert result.exit_code == 0, result.stdout
    assert f"rejected: {mem_id}" in result.stdout
    # Sanity: text mode must not leak JSON syntax.
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)


def test_memory_reject_json_emits_well_formed_object(
    project_with_memory: tuple[Path, str],
) -> None:
    """`memory reject --json` emits a single object mirroring the v0.8.44
    `memory list --json` per-row schema and the v0.8.57 `memory accept --json`
    single-object shape — same `_MEMORY_LIST_JSON_KEYS` frozenset locks the
    cross-surface invariant across THREE surfaces (list / accept / reject).

    The post-mutation `status` field round-trips as `"rejected"` — locks
    the symmetric mirror of v0.8.57 accept's `"accepted"` round-trip.
    """
    project, mem_id = project_with_memory
    result = CliRunner().invoke(
        app, ["memory", "reject", mem_id, "--project", str(project), "--json"]
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)

    assert isinstance(payload, dict)
    # Schema lock — reuses the v0.8.44 frozenset; identical contract on three
    # surfaces (list rows, accept emission, reject emission). Adding a Memory
    # field requires bumping ONE frozenset.
    assert set(payload.keys()) == _MEMORY_LIST_JSON_KEYS

    # Locked field invariants for the rejected entry:
    assert payload["id"] == mem_id
    # Critical: post-mutation status must round-trip as "rejected" — proves
    # the mutation landed AND was reflected in the emitted payload (not a
    # stale read of the pre-mutation state).
    assert payload["status"] == "rejected"
    assert payload["topic"] == "Auth flow"
    assert isinstance(payload["tags"], list)
    assert payload["path"].endswith(".md")

    # Cross-check via `list --json` — the on-disk state must match the
    # emitted payload. A regression that emitted "rejected" but failed to
    # mutate the file would fail this follow-up read.
    listed = CliRunner().invoke(
        app, ["memory", "list", "--project", str(project), "--status", "rejected", "--json"]
    )
    assert listed.exit_code == 0, listed.stdout
    assert any(row["id"] == mem_id for row in json.loads(listed.stdout))


def test_memory_reject_json_unknown_id_exits_nonzero_no_payload(
    tmp_path: Path,
) -> None:
    """Unknown memory id must exit non-zero in JSON mode (same exit-code 2
    as text mode — `--json` is a render switch, not a semantic change). No
    JSON success-shape payload must reach stdout — the error-vs-success
    boundary stays at the exit-code gate, same v0.8.42-v0.8.57 discipline."""
    result = CliRunner().invoke(
        app,
        ["memory", "reject", "mem_unknown_id", "--project", str(tmp_path), "--json"],
    )
    assert result.exit_code == 2, result.stdout
    if result.stdout.strip():
        try:
            parsed = json.loads(result.stdout)
            assert not (isinstance(parsed, dict) and "id" in parsed and "status" in parsed)
        except json.JSONDecodeError:
            pass  # Expected — error path went to stderr.


def test_memory_reject_json_overrides_accepted_status(
    project_with_memory: tuple[Path, str],
) -> None:
    """Rejecting an already-accepted memory must succeed and flip the status
    to "rejected" — locks the `reject_memory` library semantic that there
    is no state-machine guard (rejection is a status overwrite, not a
    proposed-only operation). Mirrors v0.8.57's idempotent re-accept lock
    but cross-state: accept-then-reject must land cleanly. A regression
    that gated reject behind "must-be-proposed" would break this test by
    raising MemoryNotFoundError-style or exiting non-zero on the reject."""
    project, mem_id = project_with_memory

    # First flip to accepted.
    accept_result = CliRunner().invoke(
        app, ["memory", "accept", mem_id, "--project", str(project), "--json"]
    )
    assert accept_result.exit_code == 0, accept_result.stdout
    accepted_payload = json.loads(accept_result.stdout)
    assert accepted_payload["status"] == "accepted"

    # Now reject the already-accepted memory — must succeed and emit
    # `status: "rejected"` with the SAME path (no fresh on-disk write).
    reject_result = CliRunner().invoke(
        app, ["memory", "reject", mem_id, "--project", str(project), "--json"]
    )
    assert reject_result.exit_code == 0, reject_result.stdout
    rejected_payload = json.loads(reject_result.stdout)

    assert set(rejected_payload.keys()) == _MEMORY_LIST_JSON_KEYS
    assert rejected_payload["id"] == mem_id
    assert rejected_payload["status"] == "rejected"
    # Path stable across the cross-state flip — the on-disk file is the
    # same one, not a fresh write.
    assert rejected_payload["path"] == accepted_payload["path"]
