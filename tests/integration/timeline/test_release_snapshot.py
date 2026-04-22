"""Integration test for the tag_watcher → release snapshot pipeline (spec-010 T031).

End-to-end: real git repo with real ``git tag`` calls drives
:func:`libs.gitintel.tag_watcher.poll_tags` which emits
:class:`TagEvent` instances, each applied through
:func:`libs.symbol_timeline.snapshot.handle_tag_event` to write an
immutable row into ``symbol_timeline_snapshots``.

Covers spec FR-005 acceptance:

* fresh tag → ``kind="created"`` → new snapshot row (``tag_invalidated=0``)
* second tick with no repo changes → no events
* ``git tag -d && git tag`` at a new commit → ``kind="moved"`` →
  prior row flipped to ``tag_invalidated=1`` + fresh row inserted at the
  new ``head_sha``
* each snapshot's ``symbol_count`` / ``checksum`` reflect the real
  scanner-produced symbol set (sidecar read path)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from libs.gitintel.tag_watcher import TagEvent, poll_tags
from libs.scanning.scanner import scan_project
from libs.symbol_timeline.sinks import SqliteTimelineSink
from libs.symbol_timeline.snapshot import handle_tag_event
from libs.symbol_timeline.store import SymbolTimelineStore


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True)


def _git_out(repo: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return res.stdout.strip()


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _write_mod(repo: Path, funcs: dict[str, int]) -> None:
    body = "\n\n".join(
        f"def {name}() -> int:\n    return {value}\n" for name, value in funcs.items()
    )
    (repo / "pkg" / "mod.py").write_text(body + "\n")


@pytest.fixture
def repo_with_two_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, SymbolTimelineStore]:
    """Real git repo with tags v1 + v2 and a populated scanner sidecar."""
    monkeypatch.setenv("LVDCP_TIMELINE_DB", str(tmp_path / "timeline.db"))

    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")

    (repo / "pkg").mkdir()
    (repo / "pkg" / "__init__.py").write_text("")

    store = SymbolTimelineStore(tmp_path / "timeline.db")
    store.migrate()

    # v1
    _write_mod(repo, {"alpha": 0, "beta": 1})
    _commit_all(repo, "v1")
    _git(repo, "tag", "v1")
    scan_project(repo, mode="full", timeline_sink=SqliteTimelineSink(store=store))

    # v2 — different symbol set so the new snapshot checksum must differ
    _write_mod(repo, {"alpha": 0, "beta": 1, "gamma": 2})
    _commit_all(repo, "v2")
    _git(repo, "tag", "v2")
    scan_project(repo, mode="full", timeline_sink=SqliteTimelineSink(store=store))

    return repo, store


def _snapshot_rows(store: SymbolTimelineStore, project_root: str) -> list[tuple]:  # type: ignore[type-arg]
    return store._connect().execute(
        "SELECT snapshot_id, tag, head_sha, symbol_count, checksum, "
        "tag_invalidated, ref_kind "
        "FROM symbol_timeline_snapshots "
        "WHERE project_root = ? "
        "ORDER BY id ASC",
        (project_root,),
    ).fetchall()


def test_poll_tags_emits_created_events_for_fresh_repo(
    repo_with_two_tags: tuple[Path, SymbolTimelineStore],
) -> None:
    """First poll against an empty ``known`` dict emits both tags as created."""
    repo, _store = repo_with_two_tags
    current, events = poll_tags(repo, known={})

    assert set(current.keys()) == {"v1", "v2"}
    assert {e.kind for e in events} == {"created"}
    assert {e.tag for e in events} == {"v1", "v2"}


def test_handle_tag_event_writes_immutable_snapshot(
    repo_with_two_tags: tuple[Path, SymbolTimelineStore],
) -> None:
    """Each created event writes one row reflecting the sidecar symbol set."""
    repo, store = repo_with_two_tags
    project_root = str(repo)

    _current, events = poll_tags(repo, known={})
    for ev in events:
        handle_tag_event(
            store, project_root=project_root, event=ev, sidecar_root=repo
        )

    rows = _snapshot_rows(store, project_root)
    assert len(rows) == 2
    for _sid, _tag, _sha, count, checksum, invalidated, ref_kind in rows:
        assert count > 0, "snapshot must have fingerprinted some symbols"
        assert len(checksum) == 64, "checksum is full sha256"
        assert invalidated == 0
        assert ref_kind == "git_tag"

    # Each tag's head_sha must match the git tag — the raw git truth is what
    # we just stored. (We do NOT assert v1/v2 checksum divergence: the
    # sidecar is always the latest-scan state, so post-hoc polling of both
    # tags reads the same symbol set; the real-life tag_watcher fires right
    # after each scan and wouldn't see this.)
    by_tag = {tag: (sid, sha) for sid, tag, sha, _cnt, _cs, _inv, _rk in rows}
    assert by_tag["v1"][1] == _git_out(repo, "rev-parse", "v1^{commit}")
    assert by_tag["v2"][1] == _git_out(repo, "rev-parse", "v2^{commit}")


def test_poll_tags_quiet_on_unchanged_tick(
    repo_with_two_tags: tuple[Path, SymbolTimelineStore],
) -> None:
    """After we hand ``current`` back as ``known``, the next tick is silent."""
    repo, _store = repo_with_two_tags
    current, first_events = poll_tags(repo, known={})
    assert first_events  # sanity

    _current2, events2 = poll_tags(repo, known=current)
    assert events2 == []


def test_tag_move_emits_moved_and_invalidates_prior_snapshot(
    repo_with_two_tags: tuple[Path, SymbolTimelineStore],
) -> None:
    """``git tag -d v2 && git tag v2 <new-sha>`` → moved event → old row flipped."""
    repo, store = repo_with_two_tags
    project_root = str(repo)

    # Seed both snapshots first.
    current, initial_events = poll_tags(repo, known={})
    for ev in initial_events:
        handle_tag_event(store, project_root=project_root, event=ev, sidecar_root=repo)

    pre_rows = _snapshot_rows(store, project_root)
    pre_v2 = [r for r in pre_rows if r[1] == "v2"]
    assert len(pre_v2) == 1
    old_v2_sha = pre_v2[0][2]

    # Move v2 to a newer commit.
    _write_mod(repo, {"alpha": 99, "beta": 1, "gamma": 2})
    _commit_all(repo, "v2-move-target")
    new_head = _git_out(repo, "rev-parse", "HEAD")
    assert new_head != old_v2_sha  # sanity
    _git(repo, "tag", "-d", "v2")
    _git(repo, "tag", "v2")
    # Re-scan so the sidecar reflects the new symbol set at the new head.
    scan_project(repo, mode="full", timeline_sink=SqliteTimelineSink(store=store))

    next_current, move_events = poll_tags(repo, known=current)
    assert len(move_events) == 1
    moved = move_events[0]
    assert moved.tag == "v2"
    assert moved.kind == "moved"
    assert moved.head_sha == new_head
    assert moved.previous_sha == old_v2_sha

    handle_tag_event(
        store, project_root=project_root, event=moved, sidecar_root=repo
    )

    post_rows = _snapshot_rows(store, project_root)
    v2_rows = [r for r in post_rows if r[1] == "v2"]
    assert len(v2_rows) == 2, "old + new v2 coexist; old is marked invalidated"

    # Old v2 row flipped to invalidated; new v2 row alive.
    old_rows = [r for r in v2_rows if r[2] == old_v2_sha]
    new_rows = [r for r in v2_rows if r[2] == new_head]
    assert len(old_rows) == 1 and old_rows[0][5] == 1
    assert len(new_rows) == 1 and new_rows[0][5] == 0

    # v1 must be untouched by a v2 move.
    v1_rows = [r for r in post_rows if r[1] == "v1"]
    assert len(v1_rows) == 1 and v1_rows[0][5] == 0

    # next tick is silent (caller persisted next_current as the new known).
    _c3, tail_events = poll_tags(repo, known=next_current)
    assert tail_events == []


def test_handle_tag_event_is_idempotent(
    repo_with_two_tags: tuple[Path, SymbolTimelineStore],
) -> None:
    """Re-applying the same ``TagEvent`` never creates a duplicate row."""
    repo, store = repo_with_two_tags
    project_root = str(repo)
    v1_sha = _git_out(repo, "rev-parse", "v1^{commit}")

    ev = TagEvent(tag="v1", head_sha=v1_sha, kind="created")
    first = handle_tag_event(
        store, project_root=project_root, event=ev, sidecar_root=repo
    )
    second = handle_tag_event(
        store, project_root=project_root, event=ev, sidecar_root=repo
    )

    assert first.snapshot_id == second.snapshot_id
    rows = [r for r in _snapshot_rows(store, project_root) if r[1] == "v1"]
    assert len(rows) == 1
