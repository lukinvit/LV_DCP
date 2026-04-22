"""Unit tests for libs/symbol_timeline/reconcile.py (spec-010 T033)."""

from __future__ import annotations

from pathlib import Path

import pytest
from libs.symbol_timeline.reconcile import (
    list_reachable_commits,
    prune_events,
    reconcile,
)
from libs.symbol_timeline.store import (
    SymbolTimelineStore,
    TimelineEvent,
    append_event,
)

PROJECT = "/abs/proj"


def _store(tmp_path: Path) -> SymbolTimelineStore:
    s = SymbolTimelineStore(tmp_path / "t.db")
    s.migrate()
    return s


def _ev(
    sid: str,
    etype: str,
    sha: str | None,
    ts: float,
    *,
    orphaned: bool = False,
) -> TimelineEvent:
    return TimelineEvent(
        project_root=PROJECT,
        symbol_id=sid,
        event_type=etype,
        commit_sha=sha,
        timestamp=ts,
        author=None,
        content_hash=None,
        file_path="pkg/mod.py",
        qualified_name=f"pkg.mod.{sid}",
        orphaned=orphaned,
    )


def test_list_reachable_commits_merges_rev_list_and_reflog(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(args: list[str]) -> str:
        calls.append(args)
        if args[:2] == ["rev-list", "--all"]:
            return "aaa\nbbb\n"
        if args[:1] == ["reflog"]:
            return "bbb\nccc\n"  # bbb duplicate, ccc reflog-only
        raise AssertionError(f"unexpected args {args}")

    shas = list_reachable_commits(tmp_path, git_runner=runner)
    assert shas == {"aaa", "bbb", "ccc"}
    assert calls[0][:2] == ["rev-list", "--all"]


def test_list_reachable_commits_git_missing_returns_none(tmp_path: Path) -> None:
    def runner(_args: list[str]) -> str:
        raise OSError("git: command not found")

    assert list_reachable_commits(tmp_path, git_runner=runner) is None


def test_list_reachable_commits_reflog_failure_falls_back_to_rev_list(
    tmp_path: Path,
) -> None:
    import subprocess

    def runner(args: list[str]) -> str:
        if args[:2] == ["rev-list", "--all"]:
            return "aaa\nbbb\n"
        if args[:1] == ["reflog"]:
            raise subprocess.CalledProcessError(1, args)
        raise AssertionError(f"unexpected args {args}")

    shas = list_reachable_commits(tmp_path, git_runner=runner)
    # reflog failure is best-effort — we keep rev-list commits.
    assert shas == {"aaa", "bbb"}


def test_reconcile_flags_stale_events_and_groups_by_event_type(tmp_path: Path) -> None:
    store = _store(tmp_path)
    # alive — sha in reachable
    append_event(store, event=_ev("s1", "added", "sha-alive", 100.0))
    # stale of multiple types
    append_event(store, event=_ev("s2", "added", "sha-stale-1", 110.0))
    append_event(store, event=_ev("s3", "modified", "sha-stale-1", 111.0))
    append_event(store, event=_ev("s4", "removed", "sha-stale-2", 112.0))
    # null sha — never flagged
    append_event(store, event=_ev("s5", "added", None, 120.0))

    def runner(args: list[str]) -> str:
        if args[:2] == ["rev-list", "--all"]:
            return "sha-alive\n"
        if args[:1] == ["reflog"]:
            return ""
        raise AssertionError

    report = reconcile(
        store, project_root=PROJECT, git_root=tmp_path, git_runner=runner
    )
    assert report.git_available is True
    assert report.reachable_commit_count == 1
    assert report.orphaned_newly_flagged == 3  # s2, s3, s4
    assert report.orphaned_by_event_type == {
        "added": 1,
        "modified": 1,
        "removed": 1,
    }


def test_reconcile_is_idempotent_on_second_call(tmp_path: Path) -> None:
    store = _store(tmp_path)
    append_event(store, event=_ev("s1", "added", "sha-alive", 100.0))
    append_event(store, event=_ev("s2", "added", "sha-stale", 110.0))

    def runner(args: list[str]) -> str:
        if args[:2] == ["rev-list", "--all"]:
            return "sha-alive\n"
        if args[:1] == ["reflog"]:
            return ""
        raise AssertionError

    first = reconcile(
        store, project_root=PROJECT, git_root=tmp_path, git_runner=runner
    )
    second = reconcile(
        store, project_root=PROJECT, git_root=tmp_path, git_runner=runner
    )
    assert first.orphaned_newly_flagged == 1
    assert second.orphaned_newly_flagged == 0
    assert second.orphaned_by_event_type == first.orphaned_by_event_type


def test_reconcile_git_unavailable_returns_empty_report(tmp_path: Path) -> None:
    store = _store(tmp_path)
    append_event(store, event=_ev("s1", "added", "sha", 100.0, orphaned=True))

    def runner(_args: list[str]) -> str:
        raise OSError("git: no")

    report = reconcile(
        store, project_root=PROJECT, git_root=tmp_path, git_runner=runner
    )
    assert report.git_available is False
    assert report.orphaned_newly_flagged == 0
    # Still reports existing orphans so status output stays useful.
    assert report.orphaned_by_event_type == {"added": 1}


def test_prune_events_only_deletes_orphaned_by_default(tmp_path: Path) -> None:
    store = _store(tmp_path)
    append_event(store, event=_ev("s1", "added", "x", 100.0, orphaned=True))
    append_event(store, event=_ev("s2", "added", "y", 100.0, orphaned=False))
    append_event(store, event=_ev("s3", "added", "z", 200.0, orphaned=True))

    deleted = prune_events(store, project_root=PROJECT, older_than_ts=150.0)
    assert deleted == 1  # s1 only — s2 is alive, s3 is newer than cutoff

    rows = store._connect().execute(
        "SELECT symbol_id FROM symbol_timeline_events WHERE project_root = ? "
        "ORDER BY symbol_id",
        (PROJECT,),
    ).fetchall()
    assert [r[0] for r in rows] == ["s2", "s3"]


def test_prune_events_only_orphaned_false_deletes_live_too(tmp_path: Path) -> None:
    store = _store(tmp_path)
    append_event(store, event=_ev("s1", "added", "x", 100.0, orphaned=True))
    append_event(store, event=_ev("s2", "added", "y", 100.0, orphaned=False))

    deleted = prune_events(
        store,
        project_root=PROJECT,
        older_than_ts=150.0,
        only_orphaned=False,
    )
    assert deleted == 2


def test_reconcile_isolated_per_project(tmp_path: Path) -> None:
    store = _store(tmp_path)
    append_event(
        store,
        event=TimelineEvent(
            project_root="/proj-a",
            symbol_id="a",
            event_type="added",
            commit_sha="stale-a",
            timestamp=100.0,
            author=None,
            content_hash=None,
            file_path="x.py",
        ),
    )
    append_event(
        store,
        event=TimelineEvent(
            project_root="/proj-b",
            symbol_id="b",
            event_type="added",
            commit_sha="stale-b",
            timestamp=100.0,
            author=None,
            content_hash=None,
            file_path="x.py",
        ),
    )

    def runner_a(args: list[str]) -> str:
        if args[:2] == ["rev-list", "--all"]:
            return ""  # nothing reachable in proj-a
        return ""

    report_a = reconcile(
        store, project_root="/proj-a", git_root=tmp_path, git_runner=runner_a
    )
    assert report_a.orphaned_newly_flagged == 1

    # proj-b is untouched — still alive.
    rows = store._connect().execute(
        "SELECT orphaned FROM symbol_timeline_events WHERE project_root = ?",
        ("/proj-b",),
    ).fetchall()
    assert rows == [(0,)]


@pytest.fixture
def real_git_repo(tmp_path: Path) -> Path:
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "t@t"], check=True
    )
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "a.txt").write_text("hello\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "c1"], check=True)
    return repo


def test_list_reachable_commits_real_git_sanity(real_git_repo: Path) -> None:
    shas = list_reachable_commits(real_git_repo)
    assert shas is not None
    assert len(shas) >= 1
    for sha in shas:
        assert len(sha) == 40
