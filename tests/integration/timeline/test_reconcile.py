"""Integration test for the reconcile pipeline (spec-010 T036).

Exercises the full cycle:

1. Real git repo with three commits, scanner runs after each commit —
   events are captured with live ``commit_sha`` values.
2. ``git rebase`` collapses the last two commits into one, rewriting
   their SHAs; prior event rows now point at unreachable commits.
3. ``reconcile(...)`` walks ``git rev-list --all`` + ``git reflog``,
   flags the stale events as orphaned, and reports counts grouped by
   event type.
4. A follow-up scan captures the new (rewritten) commit; orphaned rows
   stay around but the live query surface is clean.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from libs.scanning.scanner import scan_project
from libs.symbol_timeline.reconcile import reconcile
from libs.symbol_timeline.sinks import SqliteTimelineSink
from libs.symbol_timeline.store import SymbolTimelineStore


def _inherit_env() -> dict[str, str]:
    """Return a copy of the parent env so git finds PATH/HOME."""
    return dict(os.environ)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True)


def _git_out(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _write_mod(repo: Path, funcs: dict[str, int]) -> None:
    body = "\n\n".join(
        f"def {name}() -> int:\n    return {v}\n" for name, v in funcs.items()
    )
    (repo / "pkg" / "mod.py").write_text(body + "\n")


@pytest.fixture
def rebased_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, SymbolTimelineStore, set[str]]:
    """Repo scanned after three commits, then rebase rewrites the last two.

    Returns ``(repo_path, store, old_shas_rewritten_by_rebase)``.
    """
    monkeypatch.setenv("LVDCP_TIMELINE_DB", str(tmp_path / "timeline.db"))
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    # Force the default branch name to avoid "init.defaultBranch" warnings.
    _git(repo, "checkout", "-q", "-b", "main")

    (repo / "pkg").mkdir()
    (repo / "pkg" / "__init__.py").write_text("")

    store = SymbolTimelineStore(tmp_path / "timeline.db")
    store.migrate()

    # c1
    _write_mod(repo, {"alpha": 0})
    _commit_all(repo, "c1")
    scan_project(repo, mode="full", timeline_sink=SqliteTimelineSink(store=store))
    # c2 — SHA will be rewritten by the rebase below
    _write_mod(repo, {"alpha": 0, "beta": 1})
    _commit_all(repo, "c2")
    scan_project(repo, mode="full", timeline_sink=SqliteTimelineSink(store=store))
    c2_old = _git_out(repo, "rev-parse", "HEAD")
    # c3 — also rewritten
    _write_mod(repo, {"alpha": 0, "beta": 1, "gamma": 2})
    _commit_all(repo, "c3")
    scan_project(repo, mode="full", timeline_sink=SqliteTimelineSink(store=store))
    c3_old = _git_out(repo, "rev-parse", "HEAD")

    # Force a rebase-like history rewrite: reset to c1, then re-commit the
    # same tree with overridden committer times so the resulting SHAs
    # differ from c2_old/c3_old (which used wall-clock times).
    _git(repo, "reset", "--hard", "HEAD~2")
    _write_mod(repo, {"alpha": 0, "beta": 1})
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-am", "c2-rewritten"],
        env={
            **_inherit_env(),
            "GIT_COMMITTER_DATE": "2026-04-22T01:00:00",
            "GIT_AUTHOR_DATE": "2026-04-22T01:00:00",
        },
        check=True,
    )
    _write_mod(repo, {"alpha": 0, "beta": 1, "gamma": 2})
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-am", "c3-rewritten"],
        env={
            **_inherit_env(),
            "GIT_COMMITTER_DATE": "2026-04-22T02:00:00",
            "GIT_AUTHOR_DATE": "2026-04-22T02:00:00",
        },
        check=True,
    )

    # Sanity: the old SHAs are no longer reachable from any branch,
    # though reflog still references them for ~90d.
    reachable = set(_git_out(repo, "rev-list", "--all").splitlines())
    assert c2_old not in reachable
    assert c3_old not in reachable

    return repo, store, {c2_old, c3_old}


def test_reconcile_flags_events_from_rewritten_commits(
    rebased_repo: tuple[Path, SymbolTimelineStore, set[str]],
) -> None:
    """Events attached to c2_old + c3_old must be flagged orphaned."""
    repo, store, rewritten_shas = rebased_repo
    project_root = str(repo)

    # Disable reflog so the walker really does see c2_old/c3_old as gone —
    # otherwise reflog would keep them "reachable" for 90 days.
    _git(repo, "reflog", "expire", "--expire=now", "--all")
    _git(repo, "gc", "--prune=now", "--quiet")

    report = reconcile(store, project_root=project_root, git_root=repo)
    assert report.git_available is True
    assert report.orphaned_newly_flagged > 0

    # Every row with a rewritten commit_sha must now be orphaned.
    conn = store._connect()
    still_live_rewritten = conn.execute(
        "SELECT COUNT(*) FROM symbol_timeline_events "
        "WHERE project_root = ? AND orphaned = 0 AND commit_sha IN "
        f"({','.join('?' for _ in rewritten_shas)})",
        (project_root, *rewritten_shas),
    ).fetchone()[0]
    assert still_live_rewritten == 0

    # And the c1 event must remain alive (its commit is still reachable).
    alive = conn.execute(
        "SELECT DISTINCT commit_sha FROM symbol_timeline_events "
        "WHERE project_root = ? AND orphaned = 0",
        (project_root,),
    ).fetchall()
    assert len(alive) >= 1
    for row in alive:
        assert row[0] not in rewritten_shas


def test_reconcile_second_call_is_idempotent(
    rebased_repo: tuple[Path, SymbolTimelineStore, set[str]],
) -> None:
    repo, store, _ = rebased_repo
    project_root = str(repo)
    _git(repo, "reflog", "expire", "--expire=now", "--all")
    _git(repo, "gc", "--prune=now", "--quiet")

    first = reconcile(store, project_root=project_root, git_root=repo)
    second = reconcile(store, project_root=project_root, git_root=repo)
    assert first.orphaned_newly_flagged >= 1
    assert second.orphaned_newly_flagged == 0
    # orphaned totals stay stable across calls
    assert second.orphaned_by_event_type == first.orphaned_by_event_type


def test_post_rebase_scan_captures_new_commits_and_reconcile_leaves_them_alone(
    rebased_repo: tuple[Path, SymbolTimelineStore, set[str]],
) -> None:
    """After rebase + reconcile, a fresh scan must populate live events."""
    repo, store, _ = rebased_repo
    project_root = str(repo)
    _git(repo, "reflog", "expire", "--expire=now", "--all")
    _git(repo, "gc", "--prune=now", "--quiet")
    reconcile(store, project_root=project_root, git_root=repo)

    # New scan under the rebased HEAD.
    new_head = _git_out(repo, "rev-parse", "HEAD")
    scan_project(repo, mode="full", timeline_sink=SqliteTimelineSink(store=store))

    # The fresh commit_sha is on live rows.
    live_shas = {
        r[0]
        for r in store._connect().execute(
            "SELECT DISTINCT commit_sha FROM symbol_timeline_events "
            "WHERE project_root = ? AND orphaned = 0 AND commit_sha IS NOT NULL",
            (project_root,),
        ).fetchall()
    }
    assert new_head in live_shas

    # Second reconcile after the fresh scan flips nothing new.
    r = reconcile(store, project_root=project_root, git_root=repo)
    assert r.orphaned_newly_flagged == 0
