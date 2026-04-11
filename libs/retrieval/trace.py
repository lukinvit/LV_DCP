"""Retrieval trace — explainability record for a pipeline run.

Persisted to SQLite so `lvdcp_explain` can look up any trace by ID,
even after the MCP tool call that produced it has returned.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Literal

from libs.storage.sqlite_cache import SqliteCache

Coverage = Literal["high", "medium", "ambiguous"]

RETENTION_SECONDS = 30 * 24 * 3600  # 30 days
RETENTION_ROW_CAP = 2000


@dataclass(frozen=True)
class Candidate:
    path: str
    score: float
    source: str  # "symbol" | "fts" | "graph_forward" | "graph_reverse"


@dataclass(frozen=True)
class StageResult:
    name: str
    candidate_count: int
    elapsed_ms: float


@dataclass(frozen=True)
class RetrievalTrace:
    trace_id: str
    project: str
    query: str
    mode: str
    timestamp: float
    stages: list[StageResult] = field(default_factory=list)
    initial_candidates: list[Candidate] = field(default_factory=list)
    expanded_via_graph: list[Candidate] = field(default_factory=list)
    dropped_by_score_decay: list[Candidate] = field(default_factory=list)
    final_ranking: list[Candidate] = field(default_factory=list)
    coverage: Coverage = "ambiguous"


def save_trace(cache: SqliteCache, trace: RetrievalTrace) -> None:
    conn = cache._connect()
    payload = json.dumps(asdict(trace))
    conn.execute(
        "INSERT OR REPLACE INTO retrieval_traces "
        "(trace_id, project, query, mode, timestamp, coverage, trace_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            trace.trace_id,
            trace.project,
            trace.query,
            trace.mode,
            trace.timestamp,
            trace.coverage,
            payload,
        ),
    )
    # Retention: rolling 30 days AND cap 2000 rows per project.
    cutoff = time.time() - RETENTION_SECONDS
    conn.execute(
        "DELETE FROM retrieval_traces WHERE project = ? AND timestamp < ?",
        (trace.project, cutoff),
    )
    conn.execute(
        """
        DELETE FROM retrieval_traces
        WHERE project = ?
          AND trace_id NOT IN (
            SELECT trace_id FROM retrieval_traces
            WHERE project = ?
            ORDER BY timestamp DESC
            LIMIT ?
          )
        """,
        (trace.project, trace.project, RETENTION_ROW_CAP),
    )
    conn.commit()


def load_trace(cache: SqliteCache, trace_id: str) -> RetrievalTrace | None:
    conn = cache._connect()
    row = conn.execute(
        "SELECT trace_json FROM retrieval_traces WHERE trace_id = ?",
        (trace_id,),
    ).fetchone()
    if row is None:
        return None
    data = json.loads(row[0])
    return RetrievalTrace(
        trace_id=data["trace_id"],
        project=data["project"],
        query=data["query"],
        mode=data["mode"],
        timestamp=data["timestamp"],
        stages=[StageResult(**s) for s in data["stages"]],
        initial_candidates=[Candidate(**c) for c in data["initial_candidates"]],
        expanded_via_graph=[Candidate(**c) for c in data["expanded_via_graph"]],
        dropped_by_score_decay=[Candidate(**c) for c in data["dropped_by_score_decay"]],
        final_ranking=[Candidate(**c) for c in data["final_ranking"]],
        coverage=data["coverage"],
    )


def query_traces_since(
    cache: SqliteCache,
    *,
    project: str,
    since_ts: float,
) -> list[RetrievalTrace]:
    """Return all persisted traces for *project* whose timestamp >= since_ts.

    Ordered by timestamp ascending so callers can build time series directly.
    """
    conn = cache._connect()
    rows = conn.execute(
        "SELECT trace_json FROM retrieval_traces "
        "WHERE project = ? AND timestamp >= ? "
        "ORDER BY timestamp ASC",
        (project, since_ts),
    ).fetchall()
    traces: list[RetrievalTrace] = []
    for (trace_json,) in rows:
        data = json.loads(trace_json)
        traces.append(
            RetrievalTrace(
                trace_id=data["trace_id"],
                project=data["project"],
                query=data["query"],
                mode=data["mode"],
                timestamp=data["timestamp"],
                stages=[StageResult(**s) for s in data["stages"]],
                initial_candidates=[Candidate(**c) for c in data["initial_candidates"]],
                expanded_via_graph=[Candidate(**c) for c in data["expanded_via_graph"]],
                dropped_by_score_decay=[Candidate(**c) for c in data["dropped_by_score_decay"]],
                final_ranking=[Candidate(**c) for c in data["final_ranking"]],
                coverage=data["coverage"],
            )
        )
    return traces
