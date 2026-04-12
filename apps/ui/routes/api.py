"""JSON endpoints for D3 rendering."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from libs.graph.builder import Graph
from libs.impact.analyzer import analyze_impact
from libs.project_index.index import ProjectIndex
from libs.status.aggregator import build_project_status, build_workspace_status

router = APIRouter()


def _find_project_root_by_slug(slug: str) -> Path | None:
    ws = build_workspace_status()
    for card in ws.projects:
        if card.slug == slug:
            return Path(card.root)
    return None


@router.get("/api/project/{slug}/graph.json")
def graph_json(slug: str) -> JSONResponse:
    root = _find_project_root_by_slug(slug)
    if root is None:
        raise HTTPException(status_code=404, detail=f"project not found: {slug}")
    status = build_project_status(root)
    if status.graph is None:
        return JSONResponse({"nodes": [], "edges": []})
    return JSONResponse(status.graph.model_dump())


@router.get("/api/project/{slug}/sparklines.json")
def sparklines_json(slug: str) -> JSONResponse:
    root = _find_project_root_by_slug(slug)
    if root is None:
        raise HTTPException(status_code=404, detail=f"project not found: {slug}")
    status = build_project_status(root)
    return JSONResponse([s.model_dump() for s in status.sparklines])


@router.get("/api/project/{slug}/impact")
def impact_json(slug: str, file: str = "") -> JSONResponse:
    """Return dependency impact analysis for a single file."""
    if not file:
        return JSONResponse({"error": "file parameter required"}, status_code=400)
    root = _find_project_root_by_slug(slug)
    if root is None:
        raise HTTPException(status_code=404, detail=f"project not found: {slug}")

    try:
        with ProjectIndex.open(root) as idx:
            relations = list(idx.iter_relations())
            file_roles = {f.path: f.role for f in idx.iter_files()}
            git_stats = {s.file_path: s for s in idx._cache.iter_git_stats()}
    except Exception:
        return JSONResponse({"error": "project not indexed"}, status_code=400)

    graph = Graph()
    graph.add_relations(relations)

    churn = git_stats[file].churn_30d if file in git_stats else 0
    report = analyze_impact(
        file,
        graph,
        relations=relations,
        file_roles=file_roles,
        git_churn=churn,
    )

    return JSONResponse(
        {
            "target": report.target,
            "direct_dependents": report.direct_dependents,
            "transitive_dependents": report.transitive_dependents,
            "affected_tests": report.affected_tests,
            "risk_score": report.risk_score,
        }
    )
