"""Tests for the `ctx timeline` CLI group (spec-010 T034)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from apps.cli.commands import timeline_cmd as timeline_module
from apps.cli.main import app
from libs.symbol_timeline.reconcile import ReconcileReport
from libs.symbol_timeline.store import (
    SymbolTimelineStore,
    TimelineEvent,
    append_event,
    upsert_scan_state,
)
from typer.testing import CliRunner

# Schema-locked surface for `ctx timeline reconcile --json`. Adding a key
# requires bumping this set + `_reconcile_report_to_json` at the same time.
_RECONCILE_JSON_KEYS = frozenset(
    {
        "project_root",
        "git_available",
        "reachable_commit_count",
        "orphaned_newly_flagged",
        "orphaned_by_event_type",
    }
)

# Schema-locked surface for `ctx timeline prune --json` (v0.8.55). Round-trips
# the invocation parameters so a script can verify the call without parsing
# argv, then surfaces the raw `deleted` count for `jq -e '.deleted > 0'`.
# Mirrors the v0.8.38 `registry prune --json` "1:1 of what the command did"
# discipline. Adding a key requires bumping this frozenset + the inline dict
# in `apps/cli/commands/timeline_cmd.py::prune_cmd` at the same time.
_TIMELINE_PRUNE_JSON_KEYS = frozenset(
    {"project_root", "store_path", "older_than_days", "include_live", "deleted"}
)

# Schema-locked surface for `ctx timeline enable --json` (v0.8.59) — and
# the future v0.8.60 ``disable --json`` which renders the same shape with
# ``enabled: false``. Mirror of v0.8.57/v0.8.58 single-object precedent.
# Adding a key requires bumping this frozenset + ``_flag_to_json`` in
# ``apps/cli/commands/timeline_cmd.py`` at the same time.
_TIMELINE_FLAG_JSON_KEYS = frozenset({"project_root", "enabled", "flag_path"})


@pytest.fixture
def timeline_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "timeline.db"
    monkeypatch.setenv("LVDCP_TIMELINE_DB", str(db))
    store = SymbolTimelineStore(db)
    store.migrate()
    store.close()
    return db


def _seed_events(db: Path, project_root: str) -> None:
    store = SymbolTimelineStore(db)
    for i, et in enumerate(["added", "added", "modified", "removed"]):
        append_event(
            store,
            event=TimelineEvent(
                project_root=project_root,
                symbol_id=f"s{i}",
                event_type=et,
                commit_sha="sha-gone" if et == "removed" else "sha-alive",
                timestamp=float(100 + i),
                author=None,
                content_hash=None,
                file_path="pkg/mod.py",
                orphaned=(et == "removed"),
            ),
        )
    upsert_scan_state(
        store,
        project_root=project_root,
        last_scan_commit_sha="sha-alive",
        last_scan_ts=200.0,
    )
    store.close()


def test_enable_disable_writes_flag_file(tmp_path: Path, timeline_db: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["timeline", "disable", "--project", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert (tmp_path / ".context" / "timeline.enabled").read_text().strip() == "off"

    result = runner.invoke(app, ["timeline", "enable", "--project", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / ".context" / "timeline.enabled").read_text().strip() == "on"


def test_status_text_output_shows_counts(tmp_path: Path, timeline_db: Path) -> None:
    _seed_events(timeline_db, str(tmp_path.resolve()))
    runner = CliRunner()
    result = runner.invoke(app, ["timeline", "status", "--project", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    out = result.stdout
    assert "total events:     4" in out
    assert "added" in out
    assert "orphaned events:  1" in out
    assert "last scan sha:    sha-alive" in out


def test_status_json_output_is_machine_readable(tmp_path: Path, timeline_db: Path) -> None:
    _seed_events(timeline_db, str(tmp_path.resolve()))
    runner = CliRunner()
    result = runner.invoke(app, ["timeline", "status", "--project", str(tmp_path), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["total_events"] == 4
    assert payload["orphaned_events"] == 1
    assert payload["last_scan_commit_sha"] == "sha-alive"
    assert payload["event_counts"]["added"] == 2
    assert payload["enabled"] is True


def test_status_reports_disabled_after_disable(tmp_path: Path, timeline_db: Path) -> None:
    runner = CliRunner()
    runner.invoke(app, ["timeline", "disable", "--project", str(tmp_path)])
    result = runner.invoke(app, ["timeline", "status", "--project", str(tmp_path), "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["enabled"] is False


def test_prune_default_removes_only_orphaned(tmp_path: Path, timeline_db: Path) -> None:
    project_root = str(tmp_path.resolve())
    _seed_events(timeline_db, project_root)
    runner = CliRunner()
    # Very small --older-than so the 100-second timestamps count as "old".
    now = time.time()
    # Move the events to be 10 days old so --older-than=1 catches them.
    store = SymbolTimelineStore(timeline_db)
    store._connect().execute(
        "UPDATE symbol_timeline_events SET timestamp = ? WHERE project_root = ?",
        (now - 10 * 86400, project_root),
    )
    store._connect().commit()
    store.close()

    result = runner.invoke(
        app,
        ["timeline", "prune", "--older-than", "1", "--project", str(tmp_path)],
    )
    assert result.exit_code == 0, result.stdout
    assert "deleted 1 events" in result.stdout  # only the one orphaned
    assert "orphaned only" in result.stdout


def test_prune_include_live_removes_everything(tmp_path: Path, timeline_db: Path) -> None:
    project_root = str(tmp_path.resolve())
    _seed_events(timeline_db, project_root)
    now = time.time()
    store = SymbolTimelineStore(timeline_db)
    store._connect().execute(
        "UPDATE symbol_timeline_events SET timestamp = ? WHERE project_root = ?",
        (now - 10 * 86400, project_root),
    )
    store._connect().commit()
    store.close()

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "timeline",
            "prune",
            "--older-than",
            "1",
            "--include-live",
            "--project",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0
    assert "deleted 4 events" in result.stdout


def test_prune_rejects_non_positive(tmp_path: Path, timeline_db: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["timeline", "prune", "--older-than", "0", "--project", str(tmp_path)],
    )
    assert result.exit_code == 2
    assert "must be positive" in result.output


def test_reconcile_reports_git_unavailable(
    tmp_path: Path, timeline_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # tmp_path is not a git repo, and we'd normally fall through to system git;
    # force PATH empty so `git` is not found → git_available=False.
    monkeypatch.setenv("PATH", "/nonexistent")
    runner = CliRunner()
    result = runner.invoke(app, ["timeline", "reconcile", "--project", str(tmp_path)])
    assert result.exit_code == 1
    assert "git unavailable" in result.output


def test_reconcile_json_emits_report_payload(
    tmp_path: Path,
    timeline_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--json` returns a 1:1 mirror of the `ReconcileReport` dataclass."""
    fake = ReconcileReport(
        project_root=str(tmp_path.resolve()),
        git_available=True,
        reachable_commit_count=42,
        orphaned_newly_flagged=3,
        orphaned_by_event_type={"removed": 2, "modified": 1},
    )
    monkeypatch.setattr(
        timeline_module,
        "reconcile",
        lambda store, *, project_root, git_root: fake,
    )
    runner = CliRunner()
    result = runner.invoke(app, ["timeline", "reconcile", "--project", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    assert set(payload.keys()) == _RECONCILE_JSON_KEYS
    assert payload["project_root"] == str(tmp_path.resolve())
    assert payload["git_available"] is True
    assert payload["reachable_commit_count"] == 42
    assert payload["orphaned_newly_flagged"] == 3
    assert payload["orphaned_by_event_type"] == {"modified": 1, "removed": 2}


def test_reconcile_json_git_unavailable_does_not_emit_error_json(
    tmp_path: Path, timeline_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--json` never swallows the error into a stdout JSON payload.

    Same discipline as v0.8.42 / v0.8.43 / v0.8.44: scripts gate on exit
    code (`set -e`), the human message is on stderr, stdout never carries
    a `{"error": "..."}` payload so a `json.loads(stdout)` consumer
    doesn't have to branch on `if .error` keys. CliRunner merges stderr
    into `result.output` by default — we assert exit 1, the message
    surfaces, and no JSON object is emitted (no leading `{`, no quoted
    `"error"` key, `json.loads` raises on the merged output).
    """
    monkeypatch.setenv("PATH", "/nonexistent")
    runner = CliRunner()
    result = runner.invoke(app, ["timeline", "reconcile", "--project", str(tmp_path), "--json"])
    assert result.exit_code == 1
    assert "git unavailable" in result.output
    assert '"error"' not in result.output
    assert not result.output.lstrip().startswith("{")
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.output)


def test_reconcile_json_orphaned_by_event_type_is_alphabetically_sorted(
    tmp_path: Path,
    timeline_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`orphaned_by_event_type` keys land alphabetically — locks the contract.

    The dataclass `dict[str, int]` carries whatever insertion order the
    SQL `GROUP BY` emits (implementation-dependent). The CLI helper
    explicitly sorts so consumers can `jq -r '.orphaned_by_event_type | keys[]'`
    without an explicit `sort` filter — the script-side ergonomic that
    matches v0.8.43's `most_common()` ordering for inspect counts.
    """
    fake = ReconcileReport(
        project_root=str(tmp_path.resolve()),
        git_available=True,
        reachable_commit_count=1,
        orphaned_newly_flagged=4,
        # Insertion order intentionally not alphabetical.
        orphaned_by_event_type={"removed": 1, "added": 2, "modified": 1},
    )
    monkeypatch.setattr(
        timeline_module,
        "reconcile",
        lambda store, *, project_root, git_root: fake,
    )
    runner = CliRunner()
    result = runner.invoke(app, ["timeline", "reconcile", "--project", str(tmp_path), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    keys = list(payload["orphaned_by_event_type"].keys())
    assert keys == sorted(keys), keys


def test_backfill_prints_scan_hint(tmp_path: Path, timeline_db: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["timeline", "backfill", "--project", str(tmp_path)])
    assert result.exit_code == 0
    assert "ctx scan" in result.stdout
    assert str(tmp_path.resolve()) in result.stdout


# ---- v0.8.55: `timeline prune --json` write-side scriptability -------------


def _age_events(timeline_db: Path, project_root: str, days_old: int) -> None:
    """Push every seeded event to ``days_old`` days in the past so the
    prune cutoff catches them. Local helper because the existing
    `test_prune_*` tests inline this block — the new `--json` tests
    benefit from the same time-machine without copy-paste drift."""
    now = time.time()
    store = SymbolTimelineStore(timeline_db)
    store._connect().execute(
        "UPDATE symbol_timeline_events SET timestamp = ? WHERE project_root = ?",
        (now - days_old * 86400, project_root),
    )
    store._connect().commit()
    store.close()


def test_prune_text_output_unchanged(tmp_path: Path, timeline_db: Path) -> None:
    """Default text-mode output must remain bytewise stable: a single
    ``prune: deleted N events (orphaned only, older than Nd)`` line.
    Sanity-checks against an accidental JSON-as-default flip and against
    any future regression that promotes JSON to the default render —
    would break this test instead of silently breaking shell consumers
    grepping for ``deleted``."""
    project_root = str(tmp_path.resolve())
    _seed_events(timeline_db, project_root)
    _age_events(timeline_db, project_root, days_old=10)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["timeline", "prune", "--older-than", "1", "--project", str(tmp_path)],
    )
    assert result.exit_code == 0, result.stdout
    assert "deleted 1 events" in result.stdout  # one orphaned in the seed
    assert "orphaned only" in result.stdout
    # Sanity: text mode must not leak JSON syntax.
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)


def test_prune_json_emits_well_formed_object(tmp_path: Path, timeline_db: Path) -> None:
    """`timeline prune --json` emits a single object with the schema-locked
    five-key set. Round-trips invocation parameters so a script can confirm
    `older_than_days`, `include_live`, `project_root`, and `store_path` —
    same v0.8.48-v0.8.54 "round-trip the actual input to catch typos"
    precedent. `deleted` is the canonical "did this prune do work" signal
    matching the `jq -e '.deleted > 0'` CI gate from the helptext."""
    project_root = str(tmp_path.resolve())
    _seed_events(timeline_db, project_root)
    _age_events(timeline_db, project_root, days_old=10)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "timeline",
            "prune",
            "--older-than",
            "1",
            "--project",
            str(tmp_path),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)

    assert isinstance(payload, dict)
    assert set(payload.keys()) == _TIMELINE_PRUNE_JSON_KEYS

    # Locked invariants for the orphaned-only default mode:
    assert payload["project_root"] == project_root
    assert isinstance(payload["store_path"], str)
    assert payload["store_path"]  # non-empty resolved path
    assert payload["older_than_days"] == 1
    assert payload["include_live"] is False
    assert payload["deleted"] == 1  # one orphaned event in the seed

    # Stdout must be valid JSON throughout — no leading/trailing prose.
    json.loads(result.stdout)  # would raise if there's prose mixed in


def test_prune_json_include_live_round_trips_flag_and_count(
    tmp_path: Path, timeline_db: Path
) -> None:
    """`--include-live --json` round-trips the boolean flag (locks the
    schema-as-source-of-truth contract — a regression that drops the flag
    from the payload would silently lose the "this prune included live
    events" signal that drives the destructive-vs-routine distinction in
    audit logs) and reports the full deletion count (4 events, not just
    the 1 orphaned). Cross-checks the v0.8.55 schema against the existing
    `test_prune_include_live_removes_everything` text-mode invariant."""
    project_root = str(tmp_path.resolve())
    _seed_events(timeline_db, project_root)
    _age_events(timeline_db, project_root, days_old=10)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "timeline",
            "prune",
            "--older-than",
            "1",
            "--include-live",
            "--project",
            str(tmp_path),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)

    assert set(payload.keys()) == _TIMELINE_PRUNE_JSON_KEYS
    assert payload["include_live"] is True
    assert payload["deleted"] == 4  # all four seeded events


def test_prune_json_validation_error_exits_two_no_payload(
    tmp_path: Path, timeline_db: Path
) -> None:
    """Non-positive `--older-than` must exit 2 in JSON mode with no JSON
    payload on stdout — same v0.8.42-v0.8.54 discipline of "exit code is
    the gate, structured payload is for the success path". A regression
    that swallows the validation error into a `{"error": "..."}` stdout
    payload breaks this test."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "timeline",
            "prune",
            "--older-than",
            "0",
            "--project",
            str(tmp_path),
            "--json",
        ],
    )
    assert result.exit_code == 2, result.output
    assert "must be positive" in result.output
    # Stdout must NOT parse as a success-shape JSON object.
    if result.stdout.strip():
        try:
            parsed = json.loads(result.stdout)
            # If something parses, it must NOT be a success-shape entry.
            assert not (isinstance(parsed, dict) and "deleted" in parsed)
        except json.JSONDecodeError:
            pass  # Expected — error path went to stderr, stdout has no payload.


# ---- v0.8.59: `timeline enable --json` flag-mutation scriptability ---------


def test_timeline_enable_text_output_unchanged(tmp_path: Path, timeline_db: Path) -> None:
    """Default text-mode output must remain bytewise stable: a single
    ``timeline: enabled for <root>`` line. Sanity-checks against an
    accidental JSON-as-default flip — would break this test instead of
    silently breaking shell consumers grepping for ``enabled``."""
    runner = CliRunner()
    result = runner.invoke(app, ["timeline", "enable", "--project", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert f"timeline: enabled for {tmp_path.resolve()}" in result.stdout
    # Sanity: text mode must not leak JSON syntax.
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)


def test_timeline_enable_json_emits_well_formed_object(tmp_path: Path, timeline_db: Path) -> None:
    """`timeline enable --json` emits a single object with the schema-locked
    three-key set. Round-trips ``project_root`` + ``flag_path`` so a script
    can verify the call without re-deriving from argv, and surfaces the
    post-mutation ``enabled: true`` for `jq -e '.enabled == true'`
    confirmation. Cross-checks the on-disk flag file matches the emitted
    payload — if a future regression decoupled the in-memory state from the
    actual file write, this test would catch it."""
    runner = CliRunner()
    result = runner.invoke(app, ["timeline", "enable", "--project", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)

    assert isinstance(payload, dict)
    assert set(payload.keys()) == _TIMELINE_FLAG_JSON_KEYS

    # Locked invariants for the post-mutation enable state:
    assert payload["project_root"] == str(tmp_path.resolve())
    assert payload["enabled"] is True
    expected_flag = tmp_path.resolve() / ".context" / "timeline.enabled"
    assert payload["flag_path"] == str(expected_flag)

    # Cross-check: on-disk flag file matches the emitted state.
    assert expected_flag.read_text().strip() == "on"

    # Stdout must be valid JSON throughout — no leading/trailing prose.
    json.loads(result.stdout)  # would raise if there's prose mixed in


def test_timeline_enable_json_idempotent_re_enable(tmp_path: Path, timeline_db: Path) -> None:
    """Calling ``enable --json`` twice emits the same payload both times
    — there's no state-machine guard on already-enabled, the second call
    is a no-op-on-state-but-write-on-disk that returns the same shape.
    Mirrors v0.8.57 ``test_memory_accept_json_idempotent_re_accept``:
    locks the "render switch, not a semantic change" contract and proves
    a script can safely re-run ``enable --json`` without branching on
    "was it already on"."""
    runner = CliRunner()
    first = runner.invoke(app, ["timeline", "enable", "--project", str(tmp_path), "--json"])
    assert first.exit_code == 0
    payload_first = json.loads(first.stdout)

    second = runner.invoke(app, ["timeline", "enable", "--project", str(tmp_path), "--json"])
    assert second.exit_code == 0
    payload_second = json.loads(second.stdout)

    # Identical payloads — same shape, same values, both calls.
    assert payload_first == payload_second
    assert payload_second["enabled"] is True
    assert set(payload_second.keys()) == _TIMELINE_FLAG_JSON_KEYS


def test_timeline_enable_json_overrides_disabled_state(tmp_path: Path, timeline_db: Path) -> None:
    """``disable`` then ``enable --json`` flips the flag cleanly with a
    stable ``flag_path`` (no fresh file path, just an in-place rewrite).
    Mirror of v0.8.58 ``test_memory_reject_json_overrides_accepted_status``
    cross-state flip — proves ``enable`` mutates the existing on-disk
    marker rather than creating a duplicate, and the JSON payload reflects
    the post-mutation ``enabled: true`` regardless of prior state."""
    runner = CliRunner()
    # Set the flag to off via the existing disable command.
    disable_result = runner.invoke(app, ["timeline", "disable", "--project", str(tmp_path)])
    assert disable_result.exit_code == 0
    flag_path = tmp_path.resolve() / ".context" / "timeline.enabled"
    assert flag_path.read_text().strip() == "off"

    # Now flip it back via enable --json.
    enable_result = runner.invoke(app, ["timeline", "enable", "--project", str(tmp_path), "--json"])
    assert enable_result.exit_code == 0, enable_result.stdout
    payload = json.loads(enable_result.stdout)

    assert payload["enabled"] is True
    assert payload["flag_path"] == str(flag_path)
    # Stable path — same on-disk artifact rewritten in place.
    assert flag_path.read_text().strip() == "on"
