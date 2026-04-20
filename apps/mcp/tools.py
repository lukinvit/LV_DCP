"""MCP tool implementations. Separated from FastMCP registration for unit testability.

Each function takes primitive types and returns a pydantic model. The
FastMCP wrapper in `apps/mcp/server.py` decorates these with `@mcp.tool()`.
"""

from __future__ import annotations

import dataclasses
import logging
from collections import Counter
from pathlib import Path
from typing import Literal

from libs.context_pack.builder import build_edit_pack, build_navigate_pack
from libs.core.projects_config import load_config
from libs.project_index.index import ProjectIndex, ProjectNotIndexedError
from libs.scanning.scanner import scan_project
from libs.status.aggregator import build_project_status, build_workspace_status, resolve_config_path
from libs.status.budget import compute_budget_status
from libs.status.models import BudgetInfo, ProjectStatus, WorkspaceStatus
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


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


class NeighborsResult(BaseModel):
    node: str = Field(description="The node that was queried")
    resolved_kind: Literal["file", "symbol", "unknown"] = Field(
        description=(
            "Whether the node exists in the graph and, if so, whether it was "
            "recognized as a file path, a symbol fq_name, or neither."
        )
    )
    outgoing: list[str] = Field(
        description="Nodes this one references (imports, calls, inherits, tests_for, defines)"
    )
    incoming: list[str] = Field(description="Nodes that reference this one — the impact radius")
    centrality: float | None = Field(
        default=None,
        description="PageRank score in [0, 1] if the graph is non-empty",
    )
    truncated: bool = Field(description="True if neighbor lists were cut to the requested limit")


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
        # Vector search (best-effort, adds scores if Qdrant enabled)
        v_scores: dict[str, float] | None = None
        try:
            import asyncio  # noqa: PLC0415

            from libs.core.projects_config import load_config  # noqa: PLC0415
            from libs.embeddings.service import vector_search  # noqa: PLC0415

            cfg = load_config(Path.home() / ".lvdcp" / "config.yaml")
            if cfg.qdrant.enabled:
                v_scores = (
                    asyncio.run(
                        vector_search(
                            config=cfg, query=query, project_id=root.name, limit=limit * 2
                        )
                    )
                    or None
                )
        except Exception:
            log.warning(
                "vector search unavailable during pack build for %s",
                root.name,
                exc_info=True,
            )

        result = idx.retrieve(query, mode=mode, limit=limit, vector_scores=v_scores)

        # LLM rerank (best-effort, rescores top candidates if llm.enabled)
        try:
            from libs.core.projects_config import load_config as _lc  # noqa: PLC0415
            from libs.retrieval.reranker import rerank_candidates  # noqa: PLC0415

            _cfg = _lc(Path.home() / ".lvdcp" / "config.yaml")
            if _cfg.llm.enabled and result.scores:
                reranked = rerank_candidates(
                    query=query,
                    file_scores=result.scores,
                    file_summaries={f: f for f in result.files},
                    llm_config=_cfg.llm,
                    top_n=20,
                )
                # Re-sort files by reranked scores
                result.files.sort(key=lambda f: -reranked.get(f, 0.0))
                result.scores.update(reranked)
        except Exception:
            log.warning(
                "llm rerank unavailable during pack build for %s",
                root.name,
                exc_info=True,
            )

        if mode == "edit":
            pack = build_edit_pack(
                project_slug=root.name,
                query=query,
                result=result,
                project_root=root,
            )
        else:
            pack = build_navigate_pack(
                project_slug=root.name,
                query=query,
                result=result,
            )
        # Persist the trace so lvdcp_explain can look it up.
        # Use dataclasses.replace to set project field (trace.project is "" by default).
        trace_with_project = dataclasses.replace(result.trace, project=root.name)
        idx.save_trace(trace_with_project)

    # Wiki enrichment (best-effort, prepends relevant wiki articles)
    final_markdown = pack.assembled_markdown
    try:
        from libs.wiki.pack_enrichment import (  # noqa: PLC0415
            enrich_pack_markdown,
            find_relevant_articles,
        )

        wiki_dir = root / ".context" / "wiki"
        if wiki_dir.exists():
            articles = find_relevant_articles(wiki_dir, query, limit=3)
            if articles:
                final_markdown = enrich_pack_markdown(final_markdown, articles)
    except Exception:
        log.warning(
            "wiki enrichment unavailable during pack build for %s",
            root.name,
            exc_info=True,
        )

    return PackResult(
        markdown=final_markdown,
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
    budget: BudgetInfo | None = None


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
    config = load_config(resolve_config_path())
    budget = compute_budget_status(config.llm)
    if path is None:
        return StatusResponse(workspace=build_workspace_status(), budget=budget)
    return StatusResponse(
        project=build_project_status(Path(path).resolve()),
        budget=budget,
    )


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


def lvdcp_neighbors(path: str, node: str, limit: int = 20) -> NeighborsResult:
    """Return incoming + outgoing graph neighbors for a file path or symbol fq_name.

    CALL THIS WHEN:
    - You need "who calls foo" / "what does bar depend on" / "impact radius of X"
    - You want a targeted follow-up after lvdcp_pack named an interesting symbol
    - You want the PageRank centrality of a specific node

    Unlike lvdcp_pack, this does no FTS/vector retrieval — it walks the already-
    built relation graph. Fast (O(degree)) and deterministic. Incoming neighbors
    are especially useful as the "impact radius" before editing a function.

    - *node* can be a relative file path (e.g. "libs/foo.py") or a symbol fq_name
      (e.g. "libs.foo.Bar.method"). The result's `resolved_kind` reports which.
    - *limit* caps each of outgoing/incoming at N entries.
    """
    root = Path(path).resolve()
    try:
        idx = ProjectIndex.open(root)
    except ProjectNotIndexedError as exc:
        raise ValueError(f"not_indexed: {exc}. Call lvdcp_scan(path={path!r}) first.") from exc

    with idx:
        present = idx.graph_has_node(node)
        out, inc = idx.graph_neighbors(node)
        centrality = idx.graph_centrality(node) if present else None

        resolved: Literal["file", "symbol", "unknown"]
        if not present:
            resolved = "unknown"
        elif "/" in node or node.endswith((".py", ".ts", ".tsx", ".js", ".go", ".rs")):
            resolved = "file"
        else:
            resolved = "symbol"

        truncated = len(out) > limit or len(inc) > limit
        return NeighborsResult(
            node=node,
            resolved_kind=resolved,
            outgoing=out[:limit],
            incoming=inc[:limit],
            centrality=centrality,
            truncated=truncated,
        )
