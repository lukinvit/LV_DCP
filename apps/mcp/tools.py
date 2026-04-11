"""MCP tool implementations. Separated from FastMCP registration for unit testability.

Each function takes primitive types and returns a pydantic model. The
FastMCP wrapper in `apps/mcp/server.py` decorates these with `@mcp.tool()`.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from pathlib import Path
from typing import Literal

from libs.context_pack.builder import build_edit_pack, build_navigate_pack
from libs.project_index.index import ProjectIndex, ProjectNotIndexedError
from libs.scanning.scanner import scan_project
from libs.status.aggregator import build_project_status, build_workspace_status
from libs.status.models import ProjectStatus, WorkspaceStatus
from pydantic import BaseModel, Field


class ScanResultResponse(BaseModel):
    files: int = Field(description="Number of files scanned")
    reparsed: int = Field(description="Files reparsed (others skipped via hash)")
    stale_removed: int = Field(description="Files removed from index (deleted from disk)")
    symbols: int = Field(description="Symbols extracted this scan")
    relations_reparsed: int = Field(description="Relations extracted from reparsed files this scan")
    relations_cached: int = Field(description="Total relations in the cache DB after scan")
    timing_seconds: float = Field(description="Wall-clock elapsed seconds")


class PackResult(BaseModel):
    markdown: str = Field(description="The assembled context pack (2-20 KB)")
    trace_id: str = Field(description="Retrieval trace ID for lvdcp_explain lookup")
    coverage: Literal["high", "medium", "ambiguous"] = Field(
        description="Confidence in the retrieval result",
    )
    retrieved_files: list[str] = Field(description="Ranked file paths")
    retrieved_symbols: list[str] = Field(description="Ranked symbol fq_names")


class InspectResult(BaseModel):
    project_name: str
    files: int
    symbols: int
    relations: int
    languages: dict[str, int]


class ExplainResult(BaseModel):
    trace_id: str
    query: str
    mode: str
    coverage: str
    stages: list[dict[str, object]]
    initial_candidate_count: int
    expanded_via_graph_count: int
    dropped_by_score_decay_count: int
    final_ranking: list[dict[str, object]]


def lvdcp_scan(path: str, full: bool = False) -> ScanResultResponse:
    """Scan a Python project and refresh its index.

    CALL THIS:
    - On demand when the index is suspected stale and the daemon is off
    - Rarely — usually the daemon handles this automatically

    DO NOT CALL FOR:
    - Every question (very slow compared to lvdcp_pack)

    Returns file/symbol/relation counts and elapsed time.
    """
    root = Path(path).resolve()
    result = scan_project(root, mode="full" if full else "incremental")
    return ScanResultResponse(
        files=result.files_scanned,
        reparsed=result.files_reparsed,
        stale_removed=result.stale_files_removed,
        symbols=result.symbols_extracted,
        relations_reparsed=result.relations_reparsed,
        relations_cached=result.relations_cached,
        timing_seconds=result.elapsed_seconds,
    )


def lvdcp_pack(
    path: str,
    query: str,
    mode: Literal["navigate", "edit"] = "navigate",
    limit: int = 10,
) -> PackResult:
    """Retrieve a compact markdown context pack for a question about a Python project.

    CALL THIS BEFORE:
    - Reading multiple files to understand "how does X work" in a project
    - Starting any edit task ("change X", "add Y to Z", "fix bug in W")
    - Answering architectural questions ("which module handles A")

    DO NOT CALL FOR:
    - Simple syntax questions unrelated to the current project
    - Questions the user already provided full context for

    Returns 2-20 KB of ranked files and symbols pulled from an index built
    by `ctx scan`. For edit tasks, use mode="edit" to get files grouped by
    role (target/tests/configs) with impacted files surfaced via graph
    expansion. Much cheaper than grep-walking the repo.

    If the returned coverage is "ambiguous", either expand `limit`, re-query
    with more specific keywords, or ask the user to clarify — do not proceed
    with a low-confidence pack on an edit task.
    """
    root = Path(path).resolve()
    try:
        idx = ProjectIndex.open(root)
    except ProjectNotIndexedError as exc:
        raise ValueError(f"not_indexed: {exc}. Call lvdcp_scan(path={path!r}) first.") from exc

    with idx:
        result = idx.retrieve(query, mode=mode, limit=limit)
        builder = build_edit_pack if mode == "edit" else build_navigate_pack
        pack = builder(
            project_slug=root.name,
            query=query,
            result=result,
        )
        # Persist the trace so lvdcp_explain can look it up.
        # Use dataclasses.replace to set project field (trace.project is "" by default).
        trace_with_project = dataclasses.replace(result.trace, project=root.name)
        idx.save_trace(trace_with_project)

    return PackResult(
        markdown=pack.assembled_markdown,
        trace_id=result.trace.trace_id,
        coverage=result.coverage,
        retrieved_files=result.files,
        retrieved_symbols=result.symbols,
    )


def lvdcp_inspect(path: str) -> InspectResult:
    """Print statistics about a project's current index — file count, symbol count, languages.

    CALL THIS FOR:
    - Quick sanity check that a project is indexed and fresh
    - Getting a high-level sense of project size and composition
    """
    root = Path(path).resolve()
    try:
        idx = ProjectIndex.open(root)
    except ProjectNotIndexedError as exc:
        raise ValueError(f"not_indexed: {exc}. Call lvdcp_scan(path={path!r}) first.") from exc

    with idx:
        files = list(idx.iter_files())
        symbols = list(idx.iter_symbols())
        relations = list(idx.iter_relations())
        lang_counts = Counter(f.language for f in files)
        return InspectResult(
            project_name=root.name,
            files=len(files),
            symbols=len(symbols),
            relations=len(relations),
            languages=dict(lang_counts),
        )


class StatusResponse(BaseModel):
    workspace: WorkspaceStatus | None = None
    project: ProjectStatus | None = None


def lvdcp_status(path: str | None = None) -> StatusResponse:
    """Return a snapshot of workspace health or a single project's detailed status.

    CALL THIS TO:
    - Quickly check which projects are indexed and fresh (`lvdcp_status()`)
    - Get detailed per-project data including dependency graph
      (`lvdcp_status(path="/abs/project")`)
    - See Claude Code token usage rolling totals per project or workspace-wide

    DO NOT CALL FOR:
    - Replacing `lvdcp_pack` (use pack for code context, status for meta-level state)
    """
    if path is None:
        return StatusResponse(workspace=build_workspace_status())
    return StatusResponse(project=build_project_status(Path(path).resolve()))


def lvdcp_explain(path: str, trace_id: str) -> ExplainResult:
    """Retrieve the full trace of a past lvdcp_pack call for debugging.

    CALL THIS WHEN:
    - A previous lvdcp_pack result looked wrong or incomplete
    - You want to see which candidates were dropped and why

    Pass the trace_id returned by lvdcp_pack.
    """
    root = Path(path).resolve()
    try:
        idx = ProjectIndex.open(root)
    except ProjectNotIndexedError as exc:
        raise ValueError(f"not_indexed: {exc}. Call lvdcp_scan(path={path!r}) first.") from exc

    with idx:
        trace = idx.load_trace(trace_id)
        if trace is None:
            raise ValueError(f"no trace with id {trace_id!r} in project {path!r}")
        return ExplainResult(
            trace_id=trace.trace_id,
            query=trace.query,
            mode=trace.mode,
            coverage=trace.coverage,
            stages=[
                {"name": s.name, "candidate_count": s.candidate_count, "elapsed_ms": s.elapsed_ms}
                for s in trace.stages
            ],
            initial_candidate_count=len(trace.initial_candidates),
            expanded_via_graph_count=len(trace.expanded_via_graph),
            dropped_by_score_decay_count=len(trace.dropped_by_score_decay),
            final_ranking=[
                {"path": c.path, "score": c.score, "source": c.source} for c in trace.final_ranking
            ],
        )
