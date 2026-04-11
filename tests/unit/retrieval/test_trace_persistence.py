from __future__ import annotations

import time
from pathlib import Path

from libs.retrieval.trace import RetrievalTrace, query_traces_since, save_trace
from libs.storage.sqlite_cache import SqliteCache


def _make_trace(trace_id: str, timestamp: float, project: str = "p") -> RetrievalTrace:
    return RetrievalTrace(
        trace_id=trace_id,
        project=project,
        query="q",
        mode="navigate",
        timestamp=timestamp,
        coverage="high",
    )


def test_retention_keeps_traces_within_30_days(tmp_path: Path) -> None:
    cache = SqliteCache(tmp_path / "cache.db")
    cache.migrate()
    now = time.time()
    save_trace(cache, _make_trace("t-fresh", now))
    save_trace(cache, _make_trace("t-29d", now - 29 * 86400))
    save_trace(cache, _make_trace("t-31d", now - 31 * 86400))

    traces = query_traces_since(cache, project="p", since_ts=0)
    ids = {t.trace_id for t in traces}
    assert "t-fresh" in ids
    assert "t-29d" in ids
    assert "t-31d" not in ids, "trace older than 30 days should be purged"


def test_retention_caps_at_2000_rows(tmp_path: Path) -> None:
    cache = SqliteCache(tmp_path / "cache.db")
    cache.migrate()
    now = time.time()
    for i in range(2010):
        save_trace(cache, _make_trace(f"t-{i}", now - i))
    traces = query_traces_since(cache, project="p", since_ts=0)
    assert len(traces) == 2000, f"expected 2000-row cap, got {len(traces)}"


def test_query_traces_since_filters_by_timestamp(tmp_path: Path) -> None:
    cache = SqliteCache(tmp_path / "cache.db")
    cache.migrate()
    now = time.time()
    save_trace(cache, _make_trace("old", now - 3 * 86400))
    save_trace(cache, _make_trace("new", now - 1 * 86400))
    two_days_ago = now - 2 * 86400
    traces = query_traces_since(cache, project="p", since_ts=two_days_ago)
    ids = {t.trace_id for t in traces}
    assert "new" in ids
    assert "old" not in ids


def test_query_traces_since_filters_by_project(tmp_path: Path) -> None:
    cache = SqliteCache(tmp_path / "cache.db")
    cache.migrate()
    now = time.time()
    save_trace(cache, _make_trace("t-a", now, project="proj-a"))
    save_trace(cache, _make_trace("t-b", now, project="proj-b"))
    a_traces = query_traces_since(cache, project="proj-a", since_ts=0)
    assert {t.trace_id for t in a_traces} == {"t-a"}
