"""Project add/remove API for dashboard."""

from __future__ import annotations

import contextlib
from pathlib import Path

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from libs.scanning.scanner import scan_project
from libs.status.aggregator import build_workspace_status, resolve_config_path

from apps.agent.config import add_project, remove_project

router = APIRouter()


@router.post("/api/projects/add")
def add_project_endpoint(
    path: str = Form(...),
) -> HTMLResponse | RedirectResponse:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        return HTMLResponse(
            f'<p style="color:red;">Path does not exist: {resolved}</p>',
            status_code=400,
        )
    config_path = resolve_config_path()
    add_project(config_path, resolved)
    with contextlib.suppress(Exception):
        scan_project(resolved, mode="full")
    return RedirectResponse(url="/", status_code=303)


@router.post("/api/projects/{slug}/remove")
def remove_project_endpoint(slug: str) -> RedirectResponse:
    config_path = resolve_config_path()
    ws = build_workspace_status()
    for card in ws.projects:
        if card.slug == slug:
            remove_project(config_path, Path(card.root))
            break
    return RedirectResponse(url="/", status_code=303)
