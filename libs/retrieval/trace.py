"""Retrieval trace — explainability record for a pipeline run.

Persisted to SQLite so `lvdcp_explain` can look up any trace by ID,
even after the MCP tool call that produced it has returned.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Literal

from libs.storage.sqlite_cache import SqliteCache

Coverage = Literal["high", "medium", "ambiguous"]


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
    # Purge policy — keep last 100 per project
    conn.execute(
        """
        DELETE FROM retrieval_traces
        WHERE project = ?
        AND trace_id NOT IN (
            SELECT trace_id FROM retrieval_traces
            WHERE project = ?
            ORDER BY timestamp DESC
            LIMIT 100
        )
        """,
        (trace.project, trace.project),
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
