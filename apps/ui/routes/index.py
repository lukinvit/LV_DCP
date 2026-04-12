"""GET / — multi-project index view."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from libs.core.projects_config import load_config
from libs.status.aggregator import build_workspace_status, resolve_config_path
from libs.status.budget import compute_budget_status
from libs.status.value_metrics import collect_value_metrics
from starlette.templating import _TemplateResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> _TemplateResponse:
    workspace = build_workspace_status()
    config_path = resolve_config_path()
    config = load_config(config_path)
    budget = compute_budget_status(config.llm)
    metrics = collect_value_metrics(config_path)
    templates = request.app.state.templates
    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request=request,
        name="index.html.j2",
        context={
            "workspace": workspace,
            "ws_usage_7d": workspace.claude_usage_7d,
            "budget": budget,
            "metrics": metrics,
        },
    )
