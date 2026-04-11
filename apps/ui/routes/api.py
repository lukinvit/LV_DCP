"""JSON endpoints for D3 rendering."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
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
