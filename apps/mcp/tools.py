"""MCP tool implementations. Separated from FastMCP registration for unit testability.

Each function takes primitive types and returns a pydantic model. The
FastMCP wrapper in `apps/mcp/server.py` decorates these with `@mcp.tool()`.
"""

from __future__ import annotations

import dataclasses
import getpass
import logging
import os
import time
from collections import Counter
from pathlib import Path
from typing import Literal

from libs.breadcrumbs.cc_identity import resolve_cc_account_email
from libs.breadcrumbs.renderer import render_cross_project, render_project_pack
from libs.breadcrumbs.store import DEFAULT_STORE_PATH, BreadcrumbStore
from libs.breadcrumbs.views import build_cross_project_resume_pack, build_project_resume_pack
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


class CrossProjectPattern(BaseModel):
    name: str = Field(description="Dependency name or directory leaf")
    pattern_type: Literal["dependency", "structural"]
    projects: list[str] = Field(description="Names of the projects sharing this pattern")
    confidence: float = Field(
        description="Share of inspected projects where the pattern appears (0 to 1)"
    )


class CrossProjectPatternsResult(BaseModel):
    total_projects: int = Field(description="Number of registered projects considered")
    inspected_projects: list[str] = Field(
        description="Projects whose .context/cache.db was successfully read"
    )
    skipped_projects: list[dict[str, str]] = Field(
        description="Projects that were skipped, with reason"
    )
    dependency_patterns: list[CrossProjectPattern]
    structural_patterns: list[CrossProjectPattern]


class MemoryEntry(BaseModel):
    id: str
    status: Literal["proposed", "accepted", "rejected"]
    topic: str
    tags: list[str]
    created_at_iso: str
    created_by: str
    body: str
    path: str


class MemoryProposeResult(BaseModel):
    memory: MemoryEntry
    review_hint: str = Field(
        description=(
            "Human-readable hint describing how to review the proposed entry — "
            "where it was written and what edit to make to accept/reject it."
        )
    )


class MemoryListResult(BaseModel):
    project: str
    status_filter: str | None
    memories: list[MemoryEntry]


class HistoryCommitModel(BaseModel):
    sha: str
    author: str
    date_iso: str
    subject: str
    files: list[str]


class HistoryResult(BaseModel):
    project: str
    since_days: int
    filter_path: str | None
    commits: list[HistoryCommitModel]
    truncated: bool = Field(description="True when *limit* was reached — there may be more commits")


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


class RemovedSymbolModel(BaseModel):
    """One symbol that disappeared after the queried ref (spec US1)."""

    symbol_id: str = Field(description="Stable 32-hex identifier from symbol_timeline")
    qualified_name: str | None = Field(
        default=None,
        description="Fully qualified dotted name when the parser recorded one",
    )
    file_path: str = Field(description="Repo-relative path the symbol used to live in")
    removed_at_iso: str = Field(
        description="UTC ISO-8601 timestamp of the 'removed' event (seconds precision)"
    )
    commit_sha: str | None = Field(
        default=None,
        description="Commit sha at which the removal was observed (None if no git context)",
    )
    author: str | None = Field(
        default=None,
        description="Commit author email if the scan attributed the removal",
    )
    importance: float | None = Field(
        default=None,
        description="PageRank centrality lookup result in [0, 1]; None if unavailable",
    )


class RenamePairModel(BaseModel):
    """One rename edge observed after the queried ref (spec US1 output)."""

    old_symbol_id: str
    new_symbol_id: str
    old_qualified_name: str | None
    new_qualified_name: str | None
    confidence: float = Field(description="Similarity score in [0, 1] driving the edge")
    is_candidate: bool = Field(
        description="True when confidence < threshold and a human should confirm"
    )
    renamed_at_iso: str = Field(description="UTC ISO-8601 timestamp of the rename event")
    commit_sha: str | None = None


class RemovedSinceResponse(BaseModel):
    """MCP response for ``lvdcp_removed_since``."""

    ref: str = Field(description="The ref the caller asked about, verbatim")
    ref_resolved_sha: str | None = Field(
        default=None,
        description="40-hex commit sha the ref resolved to (None if ref_not_found)",
    )
    ref_resolved_at_iso: str | None = Field(
        default=None,
        description="UTC ISO-8601 timestamp of the ref's commit (None if ref_not_found)",
    )
    ref_not_found: bool = Field(
        description=(
            "True when the ref could not be resolved (unknown tag / not a git repo). "
            "All other lists are empty in that case."
        )
    )
    removed: list[RemovedSymbolModel] = Field(description="Ranked list of removed symbols")
    renamed: list[RenamePairModel] = Field(
        description="Rename edges observed after the ref, always returned for context"
    )
    total_before_limit: int = Field(description="Full hit count before `limit` truncation")
    truncated: bool = Field(description="True when `removed` was capped by `limit`")


class DiffEntryModel(BaseModel):
    """One symbol changed between two refs (spec US3)."""

    symbol_id: str = Field(description="Stable 32-hex identifier from symbol_timeline")
    qualified_name: str | None = Field(
        default=None,
        description="Fully qualified dotted name when the parser recorded one",
    )
    file_path: str = Field(description="Repo-relative path recorded with the event")
    event_type: str = Field(description="Net effect: added | removed | modified")
    at_iso: str = Field(
        description="UTC ISO-8601 timestamp of the latest event driving this net-effect"
    )
    commit_sha: str | None = Field(
        default=None,
        description="Commit sha that produced the event (None if no git context)",
    )
    author: str | None = Field(
        default=None,
        description="Commit author email if attribution is available",
    )
    importance: float | None = Field(
        default=None,
        description="PageRank centrality lookup result in [0, 1]; None if unavailable",
    )


class DiffResponse(BaseModel):
    """MCP response for ``lvdcp_diff`` — structural diff between two refs."""

    from_ref: str
    to_ref: str
    from_resolved_sha: str | None = None
    to_resolved_sha: str | None = None
    from_resolved_at_iso: str | None = None
    to_resolved_at_iso: str | None = None
    ref_not_found: bool = Field(
        description=(
            "True when either ref failed to resolve. In that case all lists "
            "are empty and the caller should surface the verbatim refs back "
            "to the user."
        )
    )
    added: list[DiffEntryModel] = Field(description="Symbols new to `to_ref`")
    removed: list[DiffEntryModel] = Field(
        description="Symbols that existed at `from_ref` and are gone by `to_ref`"
    )
    modified: list[DiffEntryModel] = Field(
        description="Symbols whose content_hash changed between the refs"
    )
    renamed: list[RenamePairModel] = Field(
        description="Rename edges observed in the window; always returned for context"
    )
    total_added: int = Field(description="Full added count before `limit_per_bucket`")
    total_removed: int = Field(description="Full removed count before `limit_per_bucket`")
    total_modified: int = Field(description="Full modified count before `limit_per_bucket`")
    truncated: bool = Field(description="True when any bucket was capped by `limit_per_bucket`")


class RegressionResponse(BaseModel):
    """MCP response for ``lvdcp_regressions`` — removed symbols between two refs."""

    from_ref: str
    to_ref: str
    from_resolved_sha: str | None = None
    to_resolved_sha: str | None = None
    ref_not_found: bool = Field(
        description="True when either ref failed to resolve; `removed` is empty"
    )
    removed: list[DiffEntryModel] = Field(
        description=(
            "Subset of the diff's `removed` bucket that likely caused regressions. "
            "Ranked by importance + recency, DESC."
        )
    )
    total_removed: int = Field(description="Full removed count before `limit` truncation")
    truncated: bool = Field(description="True when `removed` was capped by `limit`")


class TimelineEventModel(BaseModel):
    """One event in the life of a symbol (spec US2 output)."""

    symbol_id: str = Field(description="Stable 32-hex identifier from symbol_timeline")
    event_type: str = Field(
        description="One of: added, modified, removed, renamed, moved",
    )
    timestamp_iso: str = Field(
        description="UTC ISO-8601 timestamp of the event (seconds precision)"
    )
    commit_sha: str | None = Field(
        default=None,
        description="Commit sha at which the event was observed (None if no git context)",
    )
    author: str | None = Field(
        default=None, description="Commit author email if attribution is available"
    )
    file_path: str = Field(description="Repo-relative path recorded with the event")
    qualified_name: str | None = Field(
        default=None, description="Fully qualified dotted name when the parser recorded one"
    )


class SymbolCandidateModel(BaseModel):
    """One fuzzy-match candidate returned when the queried symbol is ambiguous."""

    symbol_id: str
    qualified_name: str | None
    file_path: str
    latest_event_type: str
    latest_event_iso: str


class WhenResponse(BaseModel):
    """MCP response for ``lvdcp_when`` — the full biography of one symbol."""

    symbol_id: str = Field(
        description=(
            "Resolved 32-hex identifier. Echoes the caller's input when it was "
            "already a hex id; otherwise the unique fuzzy match."
        )
    )
    qualified_name: str | None = Field(
        default=None,
        description="Most recent qualified_name observed for the symbol (None if not_found)",
    )
    file_path: str | None = Field(
        default=None,
        description="Most recent file path observed for the symbol (None if not_found)",
    )
    events: list[TimelineEventModel] = Field(
        description="All events for this symbol, oldest first",
    )
    rename_predecessors: list[RenamePairModel] = Field(
        description=(
            "Rename edges where THIS symbol is the new side — i.e. what it was called before"
        )
    )
    rename_successors: list[RenamePairModel] = Field(
        description=("Rename edges where THIS symbol is the old side — i.e. what it became")
    )
    not_found: bool = Field(
        description=(
            "True when the symbol could not be resolved (unknown id or ambiguous "
            "fuzzy match). In that case `events` is empty; `candidates` may be "
            "populated so the caller can disambiguate."
        )
    )
    candidates: list[SymbolCandidateModel] = Field(
        description=(
            "Top-N fuzzy matches offered when the query was ambiguous. Empty when "
            "`not_found=False`."
        )
    )


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
                project_root=root,
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

    _record_pack_breadcrumb(
        project_root=str(root),
        query=query,
        mode=mode,
        retrieved_files=list(result.files),
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
    - Inspect background wiki-refresh state before deciding whether to
      trigger a refresh — the per-project response exposes ``wiki_refresh``
      with live progress (``in_progress``, ``phase``, ``modules_done/total``)
      and the last run's outcome (``last_exit_code``, ``last_log_tail`` on
      crash). Mirrors what ``ctx project check`` prints on the CLI.

    DO NOT CALL FOR:
    - Replacing `lvdcp_pack` (use pack for code context, status for meta-level state)
    """
    config = load_config(resolve_config_path())
    budget = compute_budget_status(config.llm)
    if path is None:
        _record_status_breadcrumb(project_root="")
        return StatusResponse(workspace=build_workspace_status(), budget=budget)
    _record_status_breadcrumb(project_root=str(Path(path).resolve()))
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

        # Classify against the authoritative file list so symbol fq_names that
        # happen to contain "/" (e.g. a path-prefixed convention) aren't
        # mis-labeled as files. Falls back to an extension heuristic only when
        # the node is not an indexed file.
        resolved: Literal["file", "symbol", "unknown"]
        if not present:
            resolved = "unknown"
        else:
            known_files = {f.path for f in idx.iter_files()}
            if node in known_files or node.endswith((".py", ".ts", ".tsx", ".js", ".go", ".rs")):
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


def lvdcp_cross_project_patterns(min_projects: int = 2) -> CrossProjectPatternsResult:
    """Surface naming conventions and shared dependencies across indexed projects.

    CALL THIS WHEN:
    - You need to know "how does this user structure similar projects" before
      scaffolding or renaming
    - You want to see if a library is already used elsewhere in the workspace
    - You're writing architecture advice that should reference the user's
      existing conventions instead of generic defaults

    DO NOT CALL FOR:
    - Questions scoped to a single project (use lvdcp_pack instead)

    Reads every registered project's ``.context/cache.db`` in strict read-only
    mode — no scans are triggered, no caches are written. Projects without
    an indexed cache are reported in ``skipped_projects`` with a reason.

    *min_projects* controls the pattern threshold: a dependency or directory
    leaf must appear in at least this many projects to be returned (default 2).
    """
    from libs.core.projects_config import list_projects  # noqa: PLC0415
    from libs.patterns.aggregator import build_cross_project_patterns  # noqa: PLC0415
    from libs.status.aggregator import resolve_config_path  # noqa: PLC0415

    entries = list_projects(resolve_config_path())
    roots = [e.root for e in entries]
    result = build_cross_project_patterns(roots, min_projects=min_projects)

    return CrossProjectPatternsResult(
        total_projects=result.total_projects,
        inspected_projects=list(result.inspected_projects),
        skipped_projects=[
            {"project": name, "reason": reason} for name, reason in result.skipped_projects
        ],
        dependency_patterns=[
            CrossProjectPattern(
                name=p.name,
                pattern_type=p.pattern_type,
                projects=list(p.projects),
                confidence=p.confidence,
            )
            for p in result.dependency_patterns
        ],
        structural_patterns=[
            CrossProjectPattern(
                name=p.name,
                pattern_type=p.pattern_type,
                projects=list(p.projects),
                confidence=p.confidence,
            )
            for p in result.structural_patterns
        ],
    )


def lvdcp_history(
    path: str,
    since_days: int = 7,
    filter_path: str | None = None,
    limit: int = 20,
) -> HistoryResult:
    """Return recent git commits for a project, optionally filtered to a path.

    CALL THIS WHEN:
    - You want "what changed in this file / this module last week"
    - You need to ground an edit decision in recent history
      ("has this function been touched recently, by whom")
    - You want a dated trail of subject lines — cheap alternative to reading diffs

    DO NOT CALL FOR:
    - Full diff content (use `git show <sha>` outside LV_DCP)
    - Very old history (this is tuned for recent context, max 20 commits by
      default; pass *limit* if you need more, but prefer lvdcp_pack for
      historical architecture questions)

    Reads via a single `git log` subprocess — no write side-effects. Returns
    empty commit list and truncated=False for non-git directories so the
    caller can differentiate "no activity" from "not a repo".
    """
    from libs.gitintel.history import read_recent_history  # noqa: PLC0415

    root = Path(path).resolve()
    commits = read_recent_history(
        root,
        since_days=since_days,
        filter_path=filter_path,
        limit=limit,
    )

    return HistoryResult(
        project=root.name,
        since_days=since_days,
        filter_path=filter_path,
        commits=[
            HistoryCommitModel(
                sha=c.sha,
                author=c.author,
                date_iso=c.date_iso,
                subject=c.subject,
                files=list(c.files),
            )
            for c in commits
        ],
        truncated=len(commits) >= limit,
    )


def lvdcp_removed_since(
    path: str,
    ref: str,
    include_renamed: bool = False,
    limit: int = 50,
) -> RemovedSinceResponse:
    """List symbols that disappeared from the project after a given ref.

    CALL THIS WHEN:
    - You need "what did we delete since v0.5.0" before writing release notes
    - You're explaining a regression that looks like "API X is gone now"
    - You want to confirm a refactor actually removed the old entry points

    DO NOT CALL FOR:
    - File-level change history (use lvdcp_history instead)
    - The full biography of one symbol (use lvdcp_when once it ships)

    The ref is resolved via ``git rev-parse`` inside the project. Every
    ``removed`` event with ``timestamp > ref_commit_timestamp`` is returned,
    ranked by PageRank importance + recency (DESC). Symbols that the rename
    detector paired with a new name are hidden by default (``include_renamed
    =False``); the matched rename edges are always echoed in ``renamed`` so
    you can tell "renamed" from "deleted" at a glance.

    Returns ``ref_not_found=True`` (and empty lists) when the ref can't be
    resolved — e.g. the project isn't a git repo, or the tag was typo'd.
    """
    from datetime import UTC, datetime  # noqa: PLC0415

    from libs.project_index.index import ProjectIndex, ProjectNotIndexedError  # noqa: PLC0415
    from libs.symbol_timeline.query import find_removed_since  # noqa: PLC0415
    from libs.symbol_timeline.store import (  # noqa: PLC0415
        SymbolTimelineStore,
        resolve_default_store_path,
    )

    root = Path(path).resolve()

    def _iso(ts: float) -> str:
        return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Best-effort importance lookup: PageRank centrality for the still-indexed
    # side of the graph. Removed symbols mostly won't be present, so the
    # ranking degrades gracefully to pure recency — still deterministic.
    importance_lookup: object = None
    idx_ctx: ProjectIndex | None
    try:
        idx_ctx = ProjectIndex.open(root)
    except ProjectNotIndexedError:
        idx_ctx = None
    if idx_ctx is not None:
        _bound_idx = idx_ctx

        def _lookup(name: str) -> float | None:
            try:
                return _bound_idx.graph_centrality(name)
            except Exception:
                return None

        importance_lookup = _lookup

    store = SymbolTimelineStore(resolve_default_store_path())
    store.migrate()
    try:
        result = find_removed_since(
            store,
            project_root=str(root),
            ref=ref,
            include_renamed=include_renamed,
            limit=limit,
            git_root=root,
            importance_lookup=importance_lookup,  # type: ignore[arg-type]
        )
    finally:
        store.close()
        if idx_ctx is not None:
            idx_ctx.close()

    return RemovedSinceResponse(
        ref=result.ref,
        ref_resolved_sha=result.ref_resolved_sha,
        ref_resolved_at_iso=(
            _iso(result.ref_resolved_timestamp)
            if result.ref_resolved_timestamp is not None
            else None
        ),
        ref_not_found=result.ref_not_found,
        removed=[
            RemovedSymbolModel(
                symbol_id=r.symbol_id,
                qualified_name=r.qualified_name,
                file_path=r.file_path,
                removed_at_iso=_iso(r.removed_at),
                commit_sha=r.commit_sha,
                author=r.author,
                importance=r.importance,
            )
            for r in result.removed
        ],
        renamed=[
            RenamePairModel(
                old_symbol_id=p.old_symbol_id,
                new_symbol_id=p.new_symbol_id,
                old_qualified_name=p.old_qualified_name,
                new_qualified_name=p.new_qualified_name,
                confidence=p.confidence,
                is_candidate=p.is_candidate,
                renamed_at_iso=_iso(p.renamed_at),
                commit_sha=p.commit_sha,
            )
            for p in result.renamed
        ],
        total_before_limit=result.total_before_limit,
        truncated=result.truncated,
    )


def lvdcp_when(
    path: str,
    symbol: str,
    include_orphaned: bool = False,
    candidate_limit: int = 5,
) -> WhenResponse:
    """Return the full event history of one symbol — "when was X implemented?".

    CALL THIS WHEN:
    - A user asks "когда был добавлен/изменён/переименован X"
    - You need to show a symbol's full life: added → modified → renamed
    - You're citing the exact commit sha that introduced a function / class
    - You want to distinguish a *rename* from a *new implementation*

    DO NOT CALL FOR:
    - "What disappeared since v0.5.0" — use lvdcp_removed_since
    - File-level change history — use lvdcp_history
    - Bulk diffs between releases — use lvdcp_diff once it ships

    ``symbol`` accepts either a 32-hex ``symbol_id`` (exact lookup) or a
    qualified name / substring (e.g. ``pkg.auth.login`` or ``login``).
    Unique substring matches are auto-resolved; ambiguous matches return
    ``not_found=True`` plus a ``candidates`` list of the top-N hits so you
    can re-call with the disambiguated name.

    Events are returned chronologically (oldest first). Rename edges touching
    the symbol are split into ``rename_predecessors`` (what it *used to be*)
    and ``rename_successors`` (what it *became*) so the caller can stitch a
    multi-name story without duplicating events.
    """
    from datetime import UTC, datetime  # noqa: PLC0415

    from libs.symbol_timeline.query import symbol_timeline  # noqa: PLC0415
    from libs.symbol_timeline.store import (  # noqa: PLC0415
        SymbolTimelineStore,
        resolve_default_store_path,
    )

    root = Path(path).resolve()

    def _iso(ts: float) -> str:
        return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    store = SymbolTimelineStore(resolve_default_store_path())
    store.migrate()
    try:
        result = symbol_timeline(
            store,
            project_root=str(root),
            symbol=symbol,
            include_orphaned=include_orphaned,
            candidate_limit=candidate_limit,
        )
    finally:
        store.close()

    return WhenResponse(
        symbol_id=result.symbol_id,
        qualified_name=result.qualified_name,
        file_path=result.file_path,
        events=[
            TimelineEventModel(
                symbol_id=e.symbol_id,
                event_type=e.event_type,
                timestamp_iso=_iso(e.timestamp),
                commit_sha=e.commit_sha,
                author=e.author,
                file_path=e.file_path,
                qualified_name=e.qualified_name,
            )
            for e in result.events
        ],
        rename_predecessors=[
            RenamePairModel(
                old_symbol_id=p.old_symbol_id,
                new_symbol_id=p.new_symbol_id,
                old_qualified_name=p.old_qualified_name,
                new_qualified_name=p.new_qualified_name,
                confidence=p.confidence,
                is_candidate=p.is_candidate,
                renamed_at_iso=_iso(p.renamed_at),
                commit_sha=p.commit_sha,
            )
            for p in result.rename_predecessors
        ],
        rename_successors=[
            RenamePairModel(
                old_symbol_id=p.old_symbol_id,
                new_symbol_id=p.new_symbol_id,
                old_qualified_name=p.old_qualified_name,
                new_qualified_name=p.new_qualified_name,
                confidence=p.confidence,
                is_candidate=p.is_candidate,
                renamed_at_iso=_iso(p.renamed_at),
                commit_sha=p.commit_sha,
            )
            for p in result.rename_successors
        ],
        not_found=result.not_found,
        candidates=[
            SymbolCandidateModel(
                symbol_id=c.symbol_id,
                qualified_name=c.qualified_name,
                file_path=c.file_path,
                latest_event_type=c.latest_event_type,
                latest_event_iso=_iso(c.latest_event_ts),
            )
            for c in result.candidates
        ],
    )


def lvdcp_diff(
    path: str,
    from_ref: str,
    to_ref: str = "HEAD",
    limit_per_bucket: int = 20,
) -> DiffResponse:
    """Structural diff between two refs — "what changed between ``v0.5.0`` and ``v0.7.0``?".

    CALL THIS WHEN:
    - You're drafting release notes and need added / removed / modified / renamed
      at the symbol level
    - You want to audit a sprint's worth of structural change (``lvdcp_diff(sha_a, sha_b)``)
    - The user asks "что поменялось между" / "what's new in"

    DO NOT CALL FOR:
    - Single-symbol history — use lvdcp_when
    - Only removed symbols — use lvdcp_regressions (narrower contract, tighter budget)
    - File-level change history — use lvdcp_history

    Ranking is ``importance + recency`` DESC (same as lvdcp_removed_since).
    Rename edges are always returned in ``renamed``; the paired add/remove
    events are hidden from ``added``/``removed`` when the rename is
    *confirmed* (``is_candidate=False``) so the caller doesn't double-count
    a rename as one add + one remove.

    Returns ``ref_not_found=True`` (and empty lists) when either ref can't
    be resolved — e.g. the project isn't a git repo, or the tag was typo'd.
    """
    from datetime import UTC, datetime  # noqa: PLC0415

    from libs.project_index.index import ProjectIndex, ProjectNotIndexedError  # noqa: PLC0415
    from libs.symbol_timeline.query import diff as _diff  # noqa: PLC0415
    from libs.symbol_timeline.store import (  # noqa: PLC0415
        SymbolTimelineStore,
        resolve_default_store_path,
    )

    root = Path(path).resolve()

    def _iso(ts: float) -> str:
        return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    importance_lookup: object = None
    idx_ctx: ProjectIndex | None
    try:
        idx_ctx = ProjectIndex.open(root)
    except ProjectNotIndexedError:
        idx_ctx = None
    if idx_ctx is not None:
        _bound_idx = idx_ctx

        def _lookup(name: str) -> float | None:
            try:
                return _bound_idx.graph_centrality(name)
            except Exception:
                return None

        importance_lookup = _lookup

    store = SymbolTimelineStore(resolve_default_store_path())
    store.migrate()
    try:
        result = _diff(
            store,
            project_root=str(root),
            from_ref=from_ref,
            to_ref=to_ref,
            limit_per_bucket=limit_per_bucket,
            git_root=root,
            importance_lookup=importance_lookup,  # type: ignore[arg-type]
        )
    finally:
        store.close()
        if idx_ctx is not None:
            idx_ctx.close()

    def _to_entry_model(e: object) -> DiffEntryModel:
        # e is a DiffEntry dataclass
        return DiffEntryModel(
            symbol_id=e.symbol_id,  # type: ignore[attr-defined]
            qualified_name=e.qualified_name,  # type: ignore[attr-defined]
            file_path=e.file_path,  # type: ignore[attr-defined]
            event_type=e.event_type,  # type: ignore[attr-defined]
            at_iso=_iso(e.at_timestamp),  # type: ignore[attr-defined]
            commit_sha=e.commit_sha,  # type: ignore[attr-defined]
            author=e.author,  # type: ignore[attr-defined]
            importance=e.importance,  # type: ignore[attr-defined]
        )

    return DiffResponse(
        from_ref=result.from_ref,
        to_ref=result.to_ref,
        from_resolved_sha=result.from_resolved_sha,
        to_resolved_sha=result.to_resolved_sha,
        from_resolved_at_iso=(
            _iso(result.from_resolved_timestamp)
            if result.from_resolved_timestamp is not None
            else None
        ),
        to_resolved_at_iso=(
            _iso(result.to_resolved_timestamp) if result.to_resolved_timestamp is not None else None
        ),
        ref_not_found=result.ref_not_found,
        added=[_to_entry_model(e) for e in result.added],
        removed=[_to_entry_model(e) for e in result.removed],
        modified=[_to_entry_model(e) for e in result.modified],
        renamed=[
            RenamePairModel(
                old_symbol_id=p.old_symbol_id,
                new_symbol_id=p.new_symbol_id,
                old_qualified_name=p.old_qualified_name,
                new_qualified_name=p.new_qualified_name,
                confidence=p.confidence,
                is_candidate=p.is_candidate,
                renamed_at_iso=_iso(p.renamed_at),
                commit_sha=p.commit_sha,
            )
            for p in result.renamed
        ],
        total_added=result.total_added,
        total_removed=result.total_removed,
        total_modified=result.total_modified,
        truncated=result.truncated,
    )


def lvdcp_regressions(
    path: str,
    from_ref: str,
    to_ref: str = "HEAD",
    limit: int = 20,
) -> RegressionResponse:
    """Narrow version of ``lvdcp_diff`` returning only *removed* symbols between two refs.

    CALL THIS WHEN:
    - A regression landed between two releases and you want the removal shortlist
    - You need "what did we lose between v0.5.0 and v0.7.0" but don't care about adds
    - You're building a blame/ownership report after a failed release

    DO NOT CALL FOR:
    - Full structural diff — use lvdcp_diff
    - Single-symbol history — use lvdcp_when
    - Removals since a single ref (vs HEAD) — use lvdcp_removed_since

    Returns the same ``removed`` shape as ``lvdcp_diff``, ranked by
    importance + recency. Rename-paired removals are hidden (they're
    renames, not regressions).
    """
    full = lvdcp_diff(path=path, from_ref=from_ref, to_ref=to_ref, limit_per_bucket=limit)
    return RegressionResponse(
        from_ref=full.from_ref,
        to_ref=full.to_ref,
        from_resolved_sha=full.from_resolved_sha,
        to_resolved_sha=full.to_resolved_sha,
        ref_not_found=full.ref_not_found,
        removed=full.removed,
        total_removed=full.total_removed,
        truncated=full.total_removed > limit,
    )


def _memory_to_entry(m: object) -> MemoryEntry:
    # `m` is a libs.memory.models.Memory; wrap in the MCP DTO.
    from libs.memory.models import Memory  # noqa: PLC0415

    assert isinstance(m, Memory)
    return MemoryEntry(
        id=m.id,
        status=m.status.value,
        topic=m.topic,
        tags=list(m.tags),
        created_at_iso=m.created_at_iso,
        created_by=m.created_by,
        body=m.body,
        path=m.path,
    )


def lvdcp_memory_propose(
    path: str,
    topic: str,
    body: str,
    tags: list[str] | None = None,
) -> MemoryProposeResult:
    """Write a reviewable memory entry for a project as a ``proposed`` item.

    CALL THIS WHEN:
    - You want to persist a non-obvious insight the user will want next time
      ("this codebase names session-rotation handlers with the `rotate_*`
      prefix", "`.env.production.local` overrides `.env.production`")
    - The user asks you to "remember" something about the project

    DO NOT CALL FOR:
    - Facts that are already obvious from the code (a good `lvdcp_pack` call
      would surface them) — that clutters the review queue
    - Personal preferences about working style — those belong in the user's
      CLAUDE.md, not the project's memory store

    The memory is written as a markdown file under
    ``<project>/.context/memory/`` with YAML frontmatter. It starts in
    ``status: proposed`` — a human must flip it to ``accepted`` before it
    is surfaced by retrieval. Matches ByteRover's reviewable memory
    pattern but stays local-first (the file is just Markdown — any editor
    or Obsidian can be the review UI).
    """
    from libs.memory.store import MemoryError, propose_memory  # noqa: PLC0415

    root = Path(path).resolve()
    try:
        memory = propose_memory(
            root,
            topic=topic,
            body=body,
            tags=tags,
            created_by="agent",
        )
    except MemoryError as exc:
        raise ValueError(f"memory_rejected: {exc}") from exc

    return MemoryProposeResult(
        memory=_memory_to_entry(memory),
        review_hint=(
            f"Proposed memory written to {memory.path}. "
            f"Edit the frontmatter 'status' from 'proposed' to 'accepted' "
            f"(or 'rejected') to approve it. Or run: "
            f"ctx memory accept {memory.id} --project {root}"
        ),
    )


def lvdcp_memory_list(
    path: str,
    status: Literal["proposed", "accepted", "rejected"] | None = None,
) -> MemoryListResult:
    """List reviewable memory entries for a project, optionally filtered by status.

    CALL THIS WHEN:
    - You need to see what the user has accepted as project facts
      (before writing a new memory or when grounding an edit decision)
    - You want to check the review queue (``status='proposed'``) before
      asking the user about something the previous session flagged

    DO NOT CALL FOR:
    - Bulk reads (the full body of every memory is returned — cap your
      listing by passing ``status='accepted'`` to skip the review queue)
    """
    from libs.memory.models import MemoryStatus  # noqa: PLC0415
    from libs.memory.store import list_memories  # noqa: PLC0415

    root = Path(path).resolve()
    status_enum = MemoryStatus(status) if status is not None else None
    memories = list_memories(root, status=status_enum)
    return MemoryListResult(
        project=root.name,
        status_filter=status,
        memories=[_memory_to_entry(m) for m in memories],
    )


class ResumeResult(BaseModel):
    scope: Literal["project", "cross_project"]
    markdown: str = Field(description="Rendered resume pack")
    breadcrumbs_empty: bool = Field(description="True when no breadcrumbs in window")
    project_root: str | None = Field(default=None)


_RESUME_WINDOW_SECONDS = 12 * 3600


def lvdcp_resume(
    path: str | None = None,
    scope: Literal["auto", "project", "cross_project"] = "auto",
    limit: int = 10,
    format: Literal["markdown", "json"] = "markdown",
) -> ResumeResult:
    """Resume engineering context for a previously active session.

    CALL THIS WHEN:
    - Starting a new session and want to know where you left off
    - The user asks "what was I working on?" or "resume my context"
    - You need the last query, hot files, git state, and open questions

    DO NOT CALL FOR:
    - Full project code context — use lvdcp_pack instead
    - Querying which symbols changed — use lvdcp_removed_since or lvdcp_diff

    path=None auto-detects from cwd (or falls back to cross_project digest).
    Limit applies to breadcrumbs (project scope) or projects (cross_project).
    format="json" is reserved for future use — only "markdown" is wired today.
    """
    del format  # reserved for future JSON output

    os_user = getpass.getuser()
    cc_email = resolve_cc_account_email()
    since_ts = time.time() - _RESUME_WINDOW_SECONDS
    store = BreadcrumbStore(db_path=DEFAULT_STORE_PATH)
    store.migrate()
    try:
        if scope == "cross_project" or (scope == "auto" and not path):
            pack = build_cross_project_resume_pack(
                store=store,
                os_user=os_user,
                since_ts=since_ts,
                limit=limit,
            )
            md = render_cross_project(pack)
            return ResumeResult(
                scope="cross_project",
                markdown=md,
                breadcrumbs_empty=not pack.digest,
            )
        target = Path(path) if path else Path.cwd()
        ppack = build_project_resume_pack(
            store=store,
            project_root=target,
            os_user=os_user,
            cc_account_email=cc_email,
            since_ts=since_ts,
            limit=limit,
        )
        md = render_project_pack(ppack)
        return ResumeResult(
            scope="project",
            markdown=md,
            breadcrumbs_empty=ppack.breadcrumbs_empty,
            project_root=str(target),
        )
    finally:
        store.close()


def _record_status_breadcrumb(*, project_root: str) -> None:
    """Fire-and-forget status breadcrumb. Never raises."""
    if not project_root:
        return
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    try:
        from libs.breadcrumbs.store import BreadcrumbStore  # noqa: PLC0415
        from libs.breadcrumbs.writer import write_status_event  # noqa: PLC0415

        store = BreadcrumbStore(db_path=DEFAULT_STORE_PATH)
        store.migrate()
        try:
            write_status_event(
                store=store,
                project_root=project_root,
                os_user=getpass.getuser(),
                cc_account_email=resolve_cc_account_email(),
            )
        finally:
            store.close()
    except Exception:
        log.exception("breadcrumb side-effect (status) failed (suppressed)")


def _record_pack_breadcrumb(
    *,
    project_root: str,
    query: str | None,
    mode: str | None,
    retrieved_files: list[str],
) -> None:
    """Fire-and-forget breadcrumb write. Never raises."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    try:
        from libs.breadcrumbs.store import BreadcrumbStore  # noqa: PLC0415
        from libs.breadcrumbs.writer import write_pack_event  # noqa: PLC0415

        store = BreadcrumbStore(db_path=DEFAULT_STORE_PATH)
        store.migrate()
        try:
            write_pack_event(
                store=store,
                project_root=project_root,
                os_user=getpass.getuser(),
                query=query,
                mode=mode,
                paths_touched=retrieved_files,
                cc_account_email=resolve_cc_account_email(),
            )
        finally:
            store.close()
    except Exception:
        log.exception("breadcrumb side-effect (pack) failed (suppressed)")
