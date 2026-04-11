"""GET / — multi-project index view."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from libs.status.aggregator import build_workspace_status
from starlette.templating import _TemplateResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> _TemplateResponse:
    workspace = build_workspace_status()
    templates = request.app.state.templates
    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request=request,
        name="index.html.j2",
        context={
            "workspace": workspace,
            "ws_usage_7d": workspace.claude_usage_7d,
        },
    )
