"""GET /project/<slug> — single project detail view."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from libs.core.projects_config import load_config
from libs.status.aggregator import build_project_status, build_workspace_status, resolve_config_path
from libs.status.budget import compute_budget_status
from libs.status.models import WorkspaceStatus
from starlette.templating import _TemplateResponse

router = APIRouter()


def _find_project_root_by_slug(workspace: WorkspaceStatus, slug: str) -> str | None:
    for card in workspace.projects:
        if card.slug == slug:
            return card.root
    return None


@router.get("/project/{slug}", response_class=HTMLResponse)
def project_detail(slug: str, request: Request) -> _TemplateResponse:
    ws = build_workspace_status()
    root = _find_project_root_by_slug(ws, slug)
    if root is None:
        raise HTTPException(status_code=404, detail=f"project not found: {slug}")

    status = build_project_status(Path(root))
    config = load_config(resolve_config_path())
    budget = compute_budget_status(config.llm)
    templates = request.app.state.templates
    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request=request,
        name="project.html.j2",
        context={
            "status": status,
            "workspace": ws,
            "ws_usage_7d": ws.claude_usage_7d,
            "budget": budget,
        },
    )
