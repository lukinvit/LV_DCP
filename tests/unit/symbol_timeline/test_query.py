"""Unit tests for libs/symbol_timeline/query.py (spec-010 T016).

The git-ref resolver is exercised against a real ``tmp_git_repo`` fixture (one
commit is enough to have a valid ref); the rest of the tests stub
``resolve_git_ref`` via monkeypatch to keep them deterministic and offline.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from libs.symbol_timeline import query as query_module
from libs.symbol_timeline.query import (
    RemovedSinceResult,
    find_removed_since,
    resolve_git_ref,
)
from libs.symbol_timeline.store import (
    RenameEdgeRow,
    SymbolTimelineStore,
    TimelineEvent,
    append_event,
    append_rename_edge,
)

PROJECT = "/abs/proj"


def _event(
    *,
    symbol_id: str,
    event_type: str,
    timestamp: float,
    file_path: str = "libs/foo.py",
    qualified_name: str | None = None,
    commit_sha: str | None = "abcdef1",
) -> TimelineEvent:
    return TimelineEvent(
        project_root=PROJECT,
        symbol_id=symbol_id,
        event_type=event_type,
        commit_sha=commit_sha,
        timestamp=timestamp,
        author=None,
        content_hash="h",
        file_path=file_path,
        qualified_name=qualified_name,
    )


@pytest.fixture
def store(tmp_path: Path) -> SymbolTimelineStore:
    s = SymbolTimelineStore(tmp_path / "timeline.db")
    s.migrate()
    return s


@pytest.fixture
def stub_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``resolve_git_ref`` to a known (sha, ts=100.0) tuple."""

    def _stub(_root: Path, _ref: str, *, timeout: float = 5.0) -> tuple[str, float] | None:
        del timeout
        return ("deadbeef", 100.0)

    monkeypatch.setattr(query_module, "resolve_git_ref", _stub)


def test_ref_not_found_returns_typed_empty(tmp_path: Path, store: SymbolTimelineStore) -> None:
    """Unresolvable ref → ref_not_found=True, empty removed/renamed, no crash."""
    # tmp_path is not a git repo, and the ref is bogus.
    result = find_removed_since(
        store,
        project_root=str(tmp_path),
        ref="v999-nonexistent",
        git_root=tmp_path,
    )
    assert result.ref_not_found is True
    assert result.ref_resolved_sha is None
    assert result.removed == []
    assert result.renamed == []


def test_only_events_after_ref_are_returned(store: SymbolTimelineStore, stub_ref: None) -> None:
    """Events with timestamp ≤ ref_ts are filtered out (strictly after)."""
    del stub_ref  # fixture-only, injects the stub
    append_event(store, event=_event(symbol_id="old", event_type="removed", timestamp=50.0))
    append_event(store, event=_event(symbol_id="new", event_type="removed", timestamp=150.0))

    result = find_removed_since(store, project_root=PROJECT, ref="v1")

    assert [r.symbol_id for r in result.removed] == ["new"]
    assert result.ref_resolved_timestamp == 100.0


def test_ranking_uses_importance_then_recency(
    store: SymbolTimelineStore, stub_ref: None
) -> None:
    """Importance dominates; timestamp breaks ties; DESC."""
    del stub_ref
    append_event(
        store,
        event=_event(
            symbol_id="low-recent", event_type="removed", timestamp=200.0, qualified_name="a.low"
        ),
    )
    append_event(
        store,
        event=_event(
            symbol_id="high-old", event_type="removed", timestamp=110.0, qualified_name="a.high"
        ),
    )
    append_event(
        store,
        event=_event(
            symbol_id="mid", event_type="removed", timestamp=180.0, qualified_name="a.mid"
        ),
    )

    centrality = {"a.high": 0.9, "a.mid": 0.4, "a.low": 0.05}

    result = find_removed_since(
        store,
        project_root=PROJECT,
        ref="v1",
        importance_lookup=lambda q: centrality.get(q),
    )

    assert [r.symbol_id for r in result.removed] == ["high-old", "mid", "low-recent"]
    assert result.removed[0].importance == pytest.approx(0.9)


def test_limit_truncates_and_sets_flag(store: SymbolTimelineStore, stub_ref: None) -> None:
    """limit= caps the output and truncated reflects overflow."""
    del stub_ref
    for i in range(5):
        append_event(
            store,
            event=_event(
                symbol_id=f"s{i}",
                event_type="removed",
                timestamp=110.0 + i,
                qualified_name=f"x.s{i}",
            ),
        )

    result = find_removed_since(store, project_root=PROJECT, ref="v1", limit=3)

    assert len(result.removed) == 3
    assert result.total_before_limit == 5
    assert result.truncated is True


def test_include_renamed_false_hides_confirmed_renames(
    store: SymbolTimelineStore, stub_ref: None
) -> None:
    """Confirmed rename edge hides the removed event; candidate edge does not."""
    del stub_ref
    # Two pairs: confirmed + candidate
    append_event(
        store,
        event=_event(
            symbol_id="old-confirmed",
            event_type="removed",
            timestamp=120.0,
            qualified_name="pkg.old_confirmed",
        ),
    )
    append_event(
        store,
        event=_event(
            symbol_id="new-confirmed",
            event_type="added",
            timestamp=120.0,
            qualified_name="pkg.new_confirmed",
        ),
    )
    append_event(
        store,
        event=_event(
            symbol_id="old-cand",
            event_type="removed",
            timestamp=130.0,
            qualified_name="pkg.old_cand",
        ),
    )
    append_event(
        store,
        event=_event(
            symbol_id="new-cand",
            event_type="added",
            timestamp=130.0,
            qualified_name="pkg.new_cand",
        ),
    )
    append_rename_edge(
        store,
        edge=RenameEdgeRow(
            project_root=PROJECT,
            old_symbol_id="old-confirmed",
            new_symbol_id="new-confirmed",
            commit_sha="x",
            timestamp=120.0,
            confidence=0.95,
            is_candidate=False,
        ),
    )
    append_rename_edge(
        store,
        edge=RenameEdgeRow(
            project_root=PROJECT,
            old_symbol_id="old-cand",
            new_symbol_id="new-cand",
            commit_sha="y",
            timestamp=130.0,
            confidence=0.65,
            is_candidate=True,
        ),
    )

    # default include_renamed=False
    result = find_removed_since(store, project_root=PROJECT, ref="v1")
    remaining_ids = {r.symbol_id for r in result.removed}
    assert "old-confirmed" not in remaining_ids, "confirmed rename must hide the removed event"
    assert "old-cand" in remaining_ids, "candidate rename must NOT hide the removed event"
    # Both edges surface in `renamed` regardless
    rename_old = {p.old_symbol_id for p in result.renamed}
    assert rename_old == {"old-confirmed", "old-cand"}
    # Names enriched from added/removed events
    pair = next(p for p in result.renamed if p.old_symbol_id == "old-confirmed")
    assert pair.old_qualified_name == "pkg.old_confirmed"
    assert pair.new_qualified_name == "pkg.new_confirmed"


def test_include_renamed_true_keeps_all(store: SymbolTimelineStore, stub_ref: None) -> None:
    """With include_renamed=True, even confirmed renames remain in ``removed``."""
    del stub_ref
    append_event(
        store,
        event=_event(
            symbol_id="old", event_type="removed", timestamp=120.0, qualified_name="pkg.old"
        ),
    )
    append_event(
        store,
        event=_event(
            symbol_id="new", event_type="added", timestamp=120.0, qualified_name="pkg.new"
        ),
    )
    append_rename_edge(
        store,
        edge=RenameEdgeRow(
            project_root=PROJECT,
            old_symbol_id="old",
            new_symbol_id="new",
            commit_sha=None,
            timestamp=120.0,
            confidence=0.95,
            is_candidate=False,
        ),
    )

    result = find_removed_since(store, project_root=PROJECT, ref="v1", include_renamed=True)
    assert {r.symbol_id for r in result.removed} == {"old"}


def test_orphaned_events_are_excluded(store: SymbolTimelineStore, stub_ref: None) -> None:
    """Events marked orphaned never appear in removed."""
    del stub_ref
    append_event(
        store,
        event=TimelineEvent(
            project_root=PROJECT,
            symbol_id="stale",
            event_type="removed",
            commit_sha="gone-sha",
            timestamp=150.0,
            author=None,
            content_hash="h",
            file_path="libs/foo.py",
            qualified_name=None,
            orphaned=True,
        ),
    )
    append_event(
        store,
        event=_event(symbol_id="alive", event_type="removed", timestamp=150.0),
    )

    result = find_removed_since(store, project_root=PROJECT, ref="v1")
    assert {r.symbol_id for r in result.removed} == {"alive"}


def test_resolve_git_ref_against_real_repo(tmp_path: Path) -> None:
    """Real git subprocess — sanity-check resolve_git_ref on a one-commit repo."""
    import subprocess

    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "t@t"], check=True
    )
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "a.txt").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "a.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "c1"], check=True
    )

    resolved = resolve_git_ref(repo, "HEAD")
    assert resolved is not None
    sha, ts = resolved
    assert len(sha) == 40
    assert ts > 0

    # Nonexistent ref returns None (not raise).
    assert resolve_git_ref(repo, "does-not-exist") is None


def test_empty_result_type_shape(store: SymbolTimelineStore, stub_ref: None) -> None:
    """Ensure the RemovedSinceResult fields are correctly populated when empty."""
    del stub_ref
    result = find_removed_since(store, project_root=PROJECT, ref="v1")
    assert isinstance(result, RemovedSinceResult)
    assert result.ref == "v1"
    assert result.ref_resolved_sha == "deadbeef"
    assert result.ref_resolved_timestamp == 100.0
    assert result.ref_not_found is False
    assert result.removed == []
    assert result.renamed == []
    assert result.total_before_limit == 0
    assert result.truncated is False
