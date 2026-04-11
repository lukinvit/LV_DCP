"""FastAPI app factory for ctx ui dashboard."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from apps.ui.routes.api import router as api_router
from apps.ui.routes.index import router as index_router
from apps.ui.routes.project import router as project_router

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATE_DIR = Path(__file__).parent / "templates"


def create_app() -> FastAPI:
    app = FastAPI(title="LV_DCP Dashboard", docs_url=None, redoc_url=None)

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
    templates = Jinja2Templates(directory=_TEMPLATE_DIR)
    app.state.templates = templates

    app.include_router(index_router)
    app.include_router(project_router)
    app.include_router(api_router)

    return app
