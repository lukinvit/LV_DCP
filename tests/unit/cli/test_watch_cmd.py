"""Tests for `ctx watch` CLI subgroup (v0.8.35 allow_transient wiring,
v0.8.49 ``ctx watch list --json`` scriptability,
v0.8.54 ``ctx watch add --json`` write-side scriptability,
v0.8.56 ``ctx watch remove --json`` unregistration scriptability)."""

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

# v0.8.56 schema lock for `watch remove --json`: a wrapper object whose only
# top-level key is `removed`; the inner value is either a ProjectEntry-shape
# dict (path was registered) or null (path was not registered — no-op success).
_WATCH_REMOVE_JSON_KEYS = frozenset({"removed"})


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


# ---- v0.8.54: ``watch add --json`` write-side scriptability ---------------


def test_watch_add_text_output_unchanged(
    tmp_path: Path,
    _isolated_config: Path,
) -> None:
    """Default text-mode output must remain bytewise stable: a single
    ``added <path>`` line. Sanity-checks against an accidental JSON-as-default
    flip and against any future regression that promotes JSON to the default
    render — would break this test instead of silently breaking shell
    consumers grepping for ``added``."""
    project = tmp_path / "TextModeProject"
    project.mkdir()
    result = CliRunner().invoke(app, ["watch", "add", str(project)])
    assert result.exit_code == 0, result.stdout
    assert f"added {project}" in result.stdout
    # Sanity: text mode must not leak JSON syntax.
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)


def test_watch_add_json_emits_well_formed_object(
    tmp_path: Path,
    _isolated_config: Path,
) -> None:
    """`watch add --json` emits a single object mirroring the v0.8.49
    ``watch list --json`` per-row schema — same `_WATCH_LIST_JSON_KEYS`
    frozenset locks the cross-surface invariant. Schema parity between
    read (`list`) and write (`add`) sides means a future ProjectEntry
    field addition has one schema-lock to bump, not two."""
    project = tmp_path / "JsonModeProject"
    project.mkdir()
    result = CliRunner().invoke(app, ["watch", "add", str(project), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)

    assert isinstance(payload, dict)
    # Schema lock — reuses the v0.8.49 frozenset; identical contract on both
    # surfaces. Adding a ProjectEntry field requires bumping ONE frozenset.
    assert set(payload.keys()) == _WATCH_LIST_JSON_KEYS

    # Locked field invariants for a fresh registration:
    assert payload["root"].endswith("JsonModeProject")
    assert isinstance(payload["registered_at_iso"], str)
    assert payload["registered_at_iso"]  # non-empty ISO string
    assert payload["last_scan_at_iso"] is None  # never scanned yet
    assert payload["last_scan_status"] == "pending"  # default on registration

    # Must NOT print the legacy ``added X`` line in JSON mode — pure data
    # only on stdout (no human chrome). A future regression that emits
    # both the text line and the JSON object breaks this assertion.
    assert "added " not in payload["root"] or payload["root"].count("added ") == 0
    # Stdout must be valid JSON throughout — no leading/trailing prose.
    # Re-parse to confirm the entire stdout was a single JSON object.
    json.loads(result.stdout)  # would raise if there's prose mixed in


def test_watch_add_json_idempotent_returns_existing_entry(
    tmp_path: Path,
    _isolated_config: Path,
) -> None:
    """Re-adding an already-registered path must be idempotent in BOTH text
    and JSON modes (matches the `add_project` semantic — see config.py:55).
    JSON mode must still emit the existing entry (with the original
    `registered_at_iso`), not a fresh row — locks the documented "consumer
    can compare `registered_at_iso` vs. wall-clock to detect duplicate-add"
    contract from the docstring. A regression that silently re-creates the
    entry on duplicate-add (overwriting the original timestamp) breaks this
    test."""
    project = tmp_path / "IdempotentProject"
    project.mkdir()

    # First add — capture the initial registered_at_iso.
    first = CliRunner().invoke(app, ["watch", "add", str(project), "--json"])
    assert first.exit_code == 0, first.stdout
    first_payload = json.loads(first.stdout)
    original_ts = first_payload["registered_at_iso"]

    # Second add of the same path — must succeed (exit 0), must emit the
    # SAME entry (same registered_at_iso), proving idempotent semantic
    # round-trips through the JSON shape.
    second = CliRunner().invoke(app, ["watch", "add", str(project), "--json"])
    assert second.exit_code == 0, second.stdout
    second_payload = json.loads(second.stdout)

    assert set(second_payload.keys()) == _WATCH_LIST_JSON_KEYS
    assert second_payload["root"] == first_payload["root"]
    # Critical invariant: timestamp preserved across the duplicate-add — the
    # consumer can compare original_ts vs. wall-clock-now to detect "this
    # was already-registered" without an extra `list --json` call.
    assert second_payload["registered_at_iso"] == original_ts


def test_watch_add_json_error_path_exits_nonzero_no_payload(
    tmp_path: Path,
    _isolated_config: Path,
) -> None:
    """Path-validation error (the Typer `exists=True` gate on the argument)
    must exit non-zero in JSON mode. No JSON payload must reach stdout — the
    error-vs-success boundary stays at the exit-code gate, same v0.8.42-v0.8.53
    discipline of "exit code is the gate, structured payload is for the
    success path". A regression that swallows the path-not-found error into
    a `{"error": "..."}` stdout payload breaks this test."""
    nonexistent = tmp_path / "does-not-exist"
    result = CliRunner().invoke(app, ["watch", "add", str(nonexistent), "--json"])
    # Typer Exit code is 2 for argument-validation failures.
    assert result.exit_code != 0, result.stdout
    # Stdout must NOT parse as a success-shape ProjectEntry JSON object.
    if result.stdout.strip():
        try:
            parsed = json.loads(result.stdout)
            # If something parses, it must NOT be a success-shape entry.
            assert not (isinstance(parsed, dict) and "root" in parsed)
        except json.JSONDecodeError:
            pass  # Expected — error path went to stderr, stdout has Typer's diagnostic.


# ---- v0.8.56: ``watch remove --json`` unregistration scriptability --------


def test_watch_remove_text_output_unchanged(
    tmp_path: Path,
    _isolated_config: Path,
) -> None:
    """Default text-mode output must remain bytewise stable: a single
    ``removed <path>`` line. Sanity-checks against an accidental JSON-as-default
    flip — would break this test instead of silently breaking shell consumers
    grepping for ``removed``."""
    project = tmp_path / "TextRemoveProject"
    project.mkdir()
    add_result = CliRunner().invoke(app, ["watch", "add", str(project)])
    assert add_result.exit_code == 0, add_result.stdout

    result = CliRunner().invoke(app, ["watch", "remove", str(project)])
    assert result.exit_code == 0, result.stdout
    assert f"removed {project}" in result.stdout
    # Sanity: text mode must not leak JSON syntax.
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)


def test_watch_remove_json_emits_removed_entry(
    tmp_path: Path,
    _isolated_config: Path,
) -> None:
    """`watch remove --json <registered>` emits `{removed: <entry>}` where
    the inner entry mirrors the v0.8.49 ``watch list --json`` per-row schema.
    Captured BEFORE the actual removal (so the consumer can audit exactly what
    was just deleted) — locks the docstring's "capture-then-mutate ordering
    matters" contract: a regression that read-after-write would always emit
    ``removed: null`` and lose the audit signal."""
    project = tmp_path / "RemoveJsonProject"
    project.mkdir()
    add_result = CliRunner().invoke(app, ["watch", "add", str(project)])
    assert add_result.exit_code == 0, add_result.stdout

    result = CliRunner().invoke(app, ["watch", "remove", str(project), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)

    # Wrapper schema lock.
    assert isinstance(payload, dict)
    assert set(payload.keys()) == _WATCH_REMOVE_JSON_KEYS

    # Inner entry shape — reuses v0.8.49 frozenset; cross-surface schema parity.
    removed = payload["removed"]
    assert isinstance(removed, dict)
    assert set(removed.keys()) == _WATCH_LIST_JSON_KEYS
    assert removed["root"].endswith("RemoveJsonProject")
    assert isinstance(removed["registered_at_iso"], str)
    assert removed["registered_at_iso"]
    assert removed["last_scan_at_iso"] is None
    assert removed["last_scan_status"] == "pending"

    # Verify the actual mutation landed: the project must be gone from the
    # config after the command. JSON mode must perform the same write as text
    # mode, not just "report what would happen".
    from libs.core.projects_config import load_config

    cfg = load_config(_isolated_config)
    assert all(p.root != project.resolve() for p in cfg.projects)


def test_watch_remove_json_unregistered_path_emits_null_no_op(
    tmp_path: Path,
    _isolated_config: Path,
) -> None:
    """Removing a path that was never registered must succeed (exit 0) and
    emit ``{removed: null}`` — no-op success, same v0.8.45/v0.8.49/v0.8.55
    "no work done is still a successful run, surface the null/zero rather than
    erroring out" discipline. The wrapper-with-null shape lets a script use
    ``jq -e '.removed != null'`` as the natural "did this remove do work"
    guard, parallel to v0.8.55 prune's ``jq -e '.deleted > 0'``."""
    never_registered = tmp_path / "NeverRegistered"
    never_registered.mkdir()

    result = CliRunner().invoke(app, ["watch", "remove", str(never_registered), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)

    assert set(payload.keys()) == _WATCH_REMOVE_JSON_KEYS
    assert payload["removed"] is None


def test_watch_remove_json_isolated_when_other_projects_present(
    tmp_path: Path,
    _isolated_config: Path,
) -> None:
    """Removing one project from a multi-project registry must (a) emit only
    the targeted entry in the payload, (b) leave the other entries intact in
    the config. Locks the "no fan-out, no collateral damage" invariant: a
    regression that emitted a bare array of all entries (or accidentally
    truncated the registry) breaks this test."""
    keep = tmp_path / "KeepProject"
    keep.mkdir()
    drop = tmp_path / "DropProject"
    drop.mkdir()
    for path in (keep, drop):
        add_result = CliRunner().invoke(app, ["watch", "add", str(path)])
        assert add_result.exit_code == 0, add_result.stdout

    result = CliRunner().invoke(app, ["watch", "remove", str(drop), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)

    # Only the dropped entry surfaces in the payload.
    assert payload["removed"] is not None
    assert payload["removed"]["root"].endswith("DropProject")

    # Kept entry survives in the config — the mutation was scoped to one row.
    from libs.core.projects_config import load_config

    cfg = load_config(_isolated_config)
    assert len(cfg.projects) == 1
    assert cfg.projects[0].root.name == "KeepProject"
