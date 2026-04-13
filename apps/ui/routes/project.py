"""GET /project/<slug> — single project detail view + Obsidian sync."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from libs.core.projects_config import load_config
from libs.obsidian.models import ObsidianFileInfo, ObsidianModuleData, ObsidianSymbolInfo
from libs.status.aggregator import build_project_status, build_workspace_status, resolve_config_path
from libs.status.budget import compute_budget_status
from libs.status.models import WorkspaceStatus
from libs.summaries.store import SummaryStore, resolve_default_store_path
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

    with SummaryStore(resolve_default_store_path()) as store:
        store.migrate()
        summaries = store.list_for_project(root)

    config = load_config(resolve_config_path())
    obsidian_config = config.obsidian

    templates = request.app.state.templates
    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request=request,
        name="project.html.j2",
        context={
            "status": status,
            "workspace": ws,
            "ws_usage_7d": ws.claude_usage_7d,
            "budget": budget,
            "summaries": summaries,
            "obsidian_config": obsidian_config,
        },
    )


@router.post("/api/project/{slug}/obsidian-sync", response_class=HTMLResponse)
def obsidian_sync(slug: str) -> HTMLResponse:
    """Sync a single project to the Obsidian vault."""
    config = load_config(resolve_config_path())
    if not config.obsidian.enabled or not config.obsidian.vault_path:
        return HTMLResponse(
            '<span class="test-result test-error">'
            "&#10007; Configure vault path in ~/.lvdcp/config.yaml first</span>"
        )

    ws = build_workspace_status()
    root_str = _find_project_root_by_slug(ws, slug)
    if root_str is None:
        return HTMLResponse(
            f'<span class="test-result test-error">&#10007; project not found: {slug}</span>'
        )

    root = Path(root_str)
    cache_path = root / ".context" / "cache.db"
    if not cache_path.exists():
        return HTMLResponse(
            '<span class="test-result test-error">&#10007; No cache.db — scan project first</span>'
        )

    from libs.obsidian.models import VaultConfig  # noqa: PLC0415
    from libs.obsidian.publisher import ObsidianPublisher  # noqa: PLC0415
    from libs.storage.sqlite_cache import SqliteCache  # noqa: PLC0415

    cache = SqliteCache(cache_path)
    try:
        cache.migrate()
        files: list[ObsidianFileInfo] = [{"path": f.path, "language": f.language} for f in cache.iter_files()]
        symbols: list[ObsidianSymbolInfo] = [
            {"name": s.name, "file_path": s.file_path, "symbol_type": s.symbol_type}
            for s in cache.iter_symbols()
        ]

        # Group files into modules (top-level directory or package)
        modules: dict[str, ObsidianModuleData] = defaultdict(
            lambda: {
                "file_count": 0,
                "symbol_count": 0,
                "top_symbols": [],
                "dependencies": [],
                "dependents": [],
            }
        )
        for f in files:
            parts = f["path"].split("/")
            mod_name = parts[0] if len(parts) > 1 else "(root)"
            modules[mod_name]["file_count"] += 1
        for s in symbols:
            parts = s["file_path"].split("/")
            mod_name = parts[0] if len(parts) > 1 else "(root)"
            modules[mod_name]["symbol_count"] += 1
            if len(modules[mod_name]["top_symbols"]) < 10:
                modules[mod_name]["top_symbols"].append(s["name"])

        vault_cfg = VaultConfig(vault_path=Path(config.obsidian.vault_path))
        publisher = ObsidianPublisher(vault_cfg)
        report = publisher.sync_project(
            project_name=root.name,
            files=files,
            symbols=symbols,
            modules=dict(modules),
            hotspots=[],
            recent_changes=[],
            languages=list({f["language"] for f in files}),
        )
    finally:
        cache.close()

    if report.errors:
        err_text = "; ".join(report.errors[:3])
        return HTMLResponse(
            f'<span class="test-result test-error">'
            f"&#10003; {report.pages_written} pages, errors: {err_text}</span>"
        )
    return HTMLResponse(
        f'<span class="test-result test-ok">'
        f"&#10003; {report.pages_written} pages synced to Obsidian</span>"
    )
