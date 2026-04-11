import time
from pathlib import Path

import pytest
from libs.retrieval.trace import Candidate, RetrievalTrace, StageResult, load_trace, save_trace
from libs.storage.sqlite_cache import SqliteCache


@pytest.fixture
def cache(tmp_path: Path) -> SqliteCache:
    c = SqliteCache(tmp_path / "cache.db")
    c.migrate()
    return c


def test_save_and_load_trace(cache: SqliteCache) -> None:
    trace = RetrievalTrace(
        trace_id="t1",
        project="demo",
        query="login endpoint",
        mode="navigate",
        timestamp=time.time(),
        stages=[
            StageResult(name="symbol_match", candidate_count=5, elapsed_ms=2.5),
            StageResult(name="fts", candidate_count=8, elapsed_ms=1.2),
        ],
        initial_candidates=[Candidate(path="app/handlers/auth.py", score=10.0, source="symbol")],
        expanded_via_graph=[
            Candidate(path="tests/test_auth.py", score=5.0, source="graph_forward")
        ],
        dropped_by_score_decay=[],
        final_ranking=[
            Candidate(path="app/handlers/auth.py", score=10.0, source="symbol"),
            Candidate(path="tests/test_auth.py", score=5.0, source="graph_forward"),
        ],
        coverage="high",
    )
    save_trace(cache, trace)

    loaded = load_trace(cache, "t1")
    assert loaded is not None
    assert loaded.trace_id == "t1"
    assert loaded.coverage == "high"
    assert loaded.query == "login endpoint"
    assert len(loaded.stages) == 2
    assert loaded.final_ranking[0].path == "app/handlers/auth.py"


def test_load_missing_trace_returns_none(cache: SqliteCache) -> None:
    assert load_trace(cache, "nonexistent") is None
