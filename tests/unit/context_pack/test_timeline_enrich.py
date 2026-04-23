"""Tests for :mod:`libs.context_pack.timeline_enrich` (spec-010 T040).

The tests split cleanly into two layers:

1. ``detect_timeline_markers`` — pure regex/keyword scanner; we assert hit /
   miss on English + Russian phrasings, and that ref + symbol extraction
   is robust to word boundaries.
2. ``enrich_pack_with_timeline`` — integration over a real
   :class:`SymbolTimelineStore`. We short-circuit git ref resolution by
   populating the store with events whose ``commit_sha`` will never
   resolve, then assert the "ref not resolvable" fallback path renders a
   section instead of crashing. Exercising the full happy path requires a
   real git repo and is covered by the integration test at the bottom.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from libs.context_pack.timeline_enrich import (
    TimelineMarkers,
    detect_timeline_markers,
    enrich_pack_with_timeline,
)
from libs.symbol_timeline.store import (
    SymbolTimelineStore,
    TimelineEvent,
    append_event,
)

# ---------------------------------------------------------------------------
# Marker detection.
# ---------------------------------------------------------------------------


class TestDetectTimelineMarkersMisses:
    """Queries that must NOT trigger enrichment."""

    @pytest.mark.parametrize(
        "query",
        [
            "",
            "how does authentication work",
            "explain the retrieval pipeline",
            "найди функцию login",
            "refactor this module",
        ],
    )
    def test_architectural_query_has_no_markers(self, query: str) -> None:
        assert detect_timeline_markers(query).hit is False


class TestDetectTimelineMarkersRemoved:
    @pytest.mark.parametrize(
        "query",
        [
            "what was removed since v1.2.0",
            "files deleted after HEAD~5",
            "what is gone since v2",
            "missing since v1.0.0",
            "что удалили после v1.2",
            "какие функции пропали после релиза",
        ],
    )
    def test_matches_removed_phrasings(self, query: str) -> None:
        markers = detect_timeline_markers(query)
        assert markers.hit is True
        assert "removed_since" in markers.kinds


class TestDetectTimelineMarkersDiff:
    @pytest.mark.parametrize(
        "query",
        [
            "diff between v1.0 and v2.0",
            "what changed between HEAD~3 and HEAD",
            "покажи diff",
            "найди регрессию между v1 и v2",
        ],
    )
    def test_matches_diff_phrasings(self, query: str) -> None:
        markers = detect_timeline_markers(query)
        assert markers.hit is True
        assert "diff" in markers.kinds


class TestDetectTimelineMarkersSymbolHistory:
    @pytest.mark.parametrize(
        "query",
        [
            "when was libs.retrieval.pipeline.retrieve added",
            "history of app.backend.routes.login",
            "renamed from getCwd",
            "когда был добавлен libs.core.entities.ContextPack",
            "история изменений для app.cli",
            "который был переименован в log_in",
        ],
    )
    def test_matches_symbol_history_phrasings(self, query: str) -> None:
        markers = detect_timeline_markers(query)
        assert markers.hit is True
        assert "symbol_history" in markers.kinds


class TestDetectTimelineMarkersExtraction:
    def test_extracts_ref_tags(self) -> None:
        markers = detect_timeline_markers("what was removed since v1.2.3?")
        assert "v1.2.3" in markers.refs

    def test_extracts_short_sha(self) -> None:
        markers = detect_timeline_markers("diff between abcdef1 and HEAD")
        assert "abcdef1" in markers.refs
        assert "HEAD" in markers.refs

    def test_extracts_head_with_offset(self) -> None:
        markers = detect_timeline_markers("removed since HEAD~5")
        assert "HEAD~5" in markers.refs

    def test_extracts_symbol_dotted_name(self) -> None:
        markers = detect_timeline_markers("when was libs.retrieval.pipeline.retrieve added")
        assert "libs.retrieval.pipeline.retrieve" in markers.symbols

    def test_dedupes_refs(self) -> None:
        markers = detect_timeline_markers("diff between v1.0 and v1.0")
        # Only one unique "v1.0" ref even though it appears twice.
        assert markers.refs.count("v1.0") == 1


# ---------------------------------------------------------------------------
# Enrichment integration.
# ---------------------------------------------------------------------------


def _mk_store(tmp_path: Path) -> SymbolTimelineStore:
    store = SymbolTimelineStore(tmp_path / "timeline.db")
    store.migrate()
    return store


def _ev(
    project_root: str,
    symbol_id: str,
    event_type: str,
    *,
    qname: str | None = None,
    file_path: str = "pkg/mod.py",
    ts: float = 100.0,
    commit_sha: str = "deadbeef" * 5,
) -> TimelineEvent:
    return TimelineEvent(
        project_root=project_root,
        symbol_id=symbol_id,
        event_type=event_type,
        commit_sha=commit_sha,
        timestamp=ts,
        author=None,
        content_hash="ch" + symbol_id,
        file_path=file_path,
        qualified_name=qname or f"pkg.mod.{symbol_id}",
    )


class TestEnrichPackWithTimeline:
    def test_enabled_false_returns_pack_unchanged(self, tmp_path: Path) -> None:
        store = _mk_store(tmp_path)
        result = enrich_pack_with_timeline(
            "# pack",
            project_root=tmp_path,
            query="what was removed since v1",
            store=store,
            enabled=False,
        )
        assert result == "# pack"

    def test_no_markers_returns_pack_unchanged(self, tmp_path: Path) -> None:
        store = _mk_store(tmp_path)
        result = enrich_pack_with_timeline(
            "# pack\n\n## Top files\n- a.py\n",
            project_root=tmp_path,
            query="how does auth work",
            store=store,
        )
        assert "Timeline facts" not in result
        assert result.endswith("- a.py\n")

    def test_removed_since_with_unresolvable_ref_renders_fallback(self, tmp_path: Path) -> None:
        """When git ref resolution fails, the section still renders a stub."""
        store = _mk_store(tmp_path)
        pack = "# pack\n"
        out = enrich_pack_with_timeline(
            pack,
            project_root=tmp_path,
            query="what was removed since v999.999.999",
            store=store,
        )
        assert "## Timeline facts" in out
        assert "ref not resolvable" in out
        assert "v999.999.999" in out

    def test_diff_between_two_unresolvable_refs_renders_fallback(self, tmp_path: Path) -> None:
        store = _mk_store(tmp_path)
        out = enrich_pack_with_timeline(
            "# pack\n",
            project_root=tmp_path,
            query="diff between v1.0.0 and v2.0.0",
            store=store,
        )
        assert "## Timeline facts" in out
        assert "one or both refs unresolved" in out

    def test_symbol_history_not_found_renders_stub(self, tmp_path: Path) -> None:
        store = _mk_store(tmp_path)
        out = enrich_pack_with_timeline(
            "# pack\n",
            project_root=tmp_path,
            query="history of pkg.missing.symbol",
            store=store,
        )
        assert "## Timeline facts" in out
        assert "not found in timeline" in out or "no exact match" in out

    def test_symbol_history_returns_events(self, tmp_path: Path) -> None:
        store = _mk_store(tmp_path)
        project_root = str(tmp_path.resolve())
        append_event(
            store,
            event=_ev(project_root, "s1", "added", qname="pkg.mod.retrieve"),
        )
        append_event(
            store,
            event=_ev(project_root, "s1", "modified", qname="pkg.mod.retrieve", ts=200.0),
        )
        out = enrich_pack_with_timeline(
            "# pack\n",
            project_root=tmp_path,
            query="when was pkg.mod.retrieve added",
            store=store,
        )
        assert "## Timeline facts" in out
        assert "pkg.mod.retrieve" in out
        # Both event kinds should surface in the rendered tail.
        assert "added" in out
        assert "modified" in out

    def test_unreachable_store_is_silent_skip(self, tmp_path: Path) -> None:
        """A broken store must not kill pack assembly — it returns the pack verbatim."""
        # Passing a *directory* as db_path triggers an OperationalError on connect.
        broken_path = tmp_path / "notadb"
        broken_path.mkdir()
        broken = SymbolTimelineStore(broken_path / "file.db")
        # Sabotage by making migrate raise:
        import sqlite3

        def boom_connect(self: SymbolTimelineStore) -> sqlite3.Connection:
            msg = "store unreachable"
            raise sqlite3.OperationalError(msg)

        broken._connect = boom_connect.__get__(broken, SymbolTimelineStore)  # type: ignore[method-assign]

        out = enrich_pack_with_timeline(
            "# pack\n",
            project_root=tmp_path,
            query="what was removed since v1.0",
            store=broken,
        )
        # Broken store inside the timeline queries is caught; output may or may
        # not have the header but MUST still be a valid markdown string and not
        # raise — that's the critical behaviour.
        assert isinstance(out, str)
        assert out.startswith("# pack\n")

    def test_budget_truncation_appends_hint(self, tmp_path: Path) -> None:
        """When many symbols match we must not exceed the 3 KB budget."""
        store = _mk_store(tmp_path)
        project_root = str(tmp_path.resolve())
        # Populate so the fuzzy match returns multiple candidates.
        for i in range(30):
            append_event(
                store,
                event=_ev(
                    project_root,
                    f"sym{i:02d}",
                    "added",
                    qname=f"pkg.big.item_{i:02d}",
                    ts=100.0 + i,
                ),
            )
        out = enrich_pack_with_timeline(
            "# pack\n",
            project_root=tmp_path,
            query="history of pkg.big.item_00",
            store=store,
        )
        # Section must have rendered and must be bounded.
        assert "## Timeline facts" in out
        suffix = out.split("## Timeline facts", 1)[1]
        assert len(suffix.encode("utf-8")) <= 3 * 1024 + 256  # 256 B slack


class TestMarkersDataclass:
    def test_hit_property_false_on_empty(self) -> None:
        assert TimelineMarkers().hit is False

    def test_hit_property_true_on_any_kind(self) -> None:
        assert TimelineMarkers(kinds=("diff",)).hit is True


# ---------------------------------------------------------------------------
# End-to-end: real git repo so refs resolve.
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


@pytest.mark.slow
def test_enrich_pack_with_real_git_repo(tmp_path: Path) -> None:
    """Real git repo + populated store + tagged ref — the happy path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.py").write_text("x = 1\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-q", "-m", "v1")
    _git(repo, "tag", "v1.0.0")
    # Second commit — scanner would have recorded a removed-event for something
    # previously present. Fake it directly.
    (repo / "a.py").write_text("y = 2\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-q", "-m", "v2")

    head_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    store = _mk_store(tmp_path)
    project_root = str(repo.resolve())
    import time as _time

    append_event(
        store,
        event=TimelineEvent(
            project_root=project_root,
            symbol_id="sid_removed",
            event_type="removed",
            commit_sha=head_sha,
            timestamp=_time.time(),  # after the tag
            author=None,
            content_hash="ch1",
            file_path="a.py",
            qualified_name="a.old_fn",
        ),
    )

    out = enrich_pack_with_timeline(
        "# pack\n",
        project_root=repo,
        query="what was removed since v1.0.0",
        store=store,
    )
    assert "## Timeline facts" in out
    assert "removed since `v1.0.0`" in out
    assert "a.old_fn" in out
