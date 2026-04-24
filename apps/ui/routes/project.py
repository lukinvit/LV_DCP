"""GET /project/<slug> — single project detail view + Obsidian sync."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from libs.core.projects_config import load_config
from libs.obsidian.models import ObsidianFileInfo, ObsidianModuleData, ObsidianSymbolInfo
from libs.status.aggregator import (
    build_project_status,
    build_wiki_refresh,
    build_workspace_status,
    resolve_config_path,
)
from libs.status.budget import compute_budget_status
from libs.status.models import WikiBackgroundRefresh, WorkspaceStatus
from libs.summaries.store import SummaryStore, resolve_default_store_path
from starlette.templating import _TemplateResponse

log = logging.getLogger(__name__)

router = APIRouter()

#: Crash-toast freshness window. The fragment endpoint emits the OOB
#: flash banner only when ``last_completed_at`` is within this many
#: seconds of ``time.time()``. Long enough to absorb a polling tick plus
#: a bit of clock drift (polling runs at 2 s), short enough that a user
#: re-opening devtools 30 s after an old crash doesn't trigger a toast.
_CRASH_TOAST_FRESH_SECONDS = 15.0

#: Exit codes that represent "graceful" terminations and therefore must
#: NOT surface the crash toast. ``0`` = clean completion; ``143`` =
#: SIGTERM / ``ctx project cancel-refresh``. Any other non-zero exit is
#: an unexpected crash and does trigger the toast.
_NON_CRASH_EXIT_CODES: frozenset[int] = frozenset({0, 143})


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


def _should_flash_crash_toast(wr: WikiBackgroundRefresh | None, request: Request) -> bool:
    """Decide whether the fragment response carries a one-shot crash toast.

    Four conditions must hold simultaneously:

    1. ``HX-Request`` header is present — rules out full page loads and
       manual ``curl`` hits, so a user navigating to ``/project/<slug>``
       ten minutes after a crash never sees the flash.
    2. A refresh has finished and was NOT live (``in_progress=False``
       with a concrete ``last_exit_code``). During an active refresh
       each poll would otherwise re-evaluate stale crash state.
    3. ``last_exit_code`` is a true crash — non-zero and not
       ``143``/SIGTERM. Cancellations are user-initiated and don't merit
       a red flash banner.
    4. ``last_completed_at`` is within :data:`_CRASH_TOAST_FRESH_SECONDS`
       of now. Guarantees the toast fires only on the *first* post-crash
       poll; any later fragment re-fetch sees a stale timestamp and
       stays silent.

    All four together make the toast fire exactly once per crash event
    — right on the polling tick that swaps the panel to FAILED and
    strips ``hx-get`` from the outer wrapper, killing polling.
    """
    if request.headers.get("HX-Request", "").lower() != "true":
        return False
    if wr is None or wr.in_progress:
        return False
    if wr.last_exit_code is None or wr.last_exit_code in _NON_CRASH_EXIT_CODES:
        return False
    if wr.last_completed_at is None:
        return False
    return (time.time() - wr.last_completed_at) <= _CRASH_TOAST_FRESH_SECONDS


@router.get("/api/project/{slug}/wiki-refresh", response_class=HTMLResponse)
def wiki_refresh_fragment(slug: str, request: Request) -> _TemplateResponse:
    """HTMX polling endpoint: render just the wiki_refresh partial.

    Called every ~2 s by the partial's outer wrapper while a refresh is
    in progress (``hx-get`` on ``#wiki-refresh-panel``). Builds only the
    ``WikiBackgroundRefresh`` snapshot — not the full ``ProjectStatus``
    — so polling stays cheap even during a live refresh. When the
    refresh transitions to idle, the response has no ``hx-get`` on the
    outer wrapper and HTMX stops the timer.

    On the exact polling tick that flips ``in_progress: True → False``
    with a crashing ``last_exit_code``, the response additionally
    carries an ``hx-swap-oob`` flash banner so HTMX moves it into the
    ``#toast-region`` drop zone from ``base.html.j2``. See
    :func:`_should_flash_crash_toast` for the freshness guard that
    keeps the toast from re-firing on subsequent fetches.

    **Error-backoff contract (v0.8.10+):** if anything in the
    status-assembly path raises (config read failure, transient file
    I/O, ``build_workspace_status`` hiccup, etc.), the endpoint returns
    a 200 response carrying the partial in **degraded mode** — a
    yellow "refresh status unavailable" card and a slowed ``hx-trigger
    ="every 30s"`` polling attribute. This avoids two bad outcomes
    that predated the contract: (a) a 500 during polling caused HTMX
    to hammer the endpoint at the original 2 s cadence, and (b) a
    ``build_wiki_refresh`` returning ``None`` silently stripped
    ``hx-get`` from the wrapper, stopping polling forever for a
    transient failure. Explicit 404 for unknown slug is preserved so
    genuine client-side bugs still surface.
    """
    templates = request.app.state.templates
    try:
        ws = build_workspace_status()
        root = _find_project_root_by_slug(ws, slug)
        if root is None:
            raise HTTPException(status_code=404, detail=f"project not found: {slug}")
        wr = build_wiki_refresh(Path(root))
    except HTTPException:
        # 404 is an intentional client signal — don't swallow it into the
        # degraded shell, or the dashboard would keep polling a slug that
        # will never resolve.
        raise
    except Exception:  # any backend hiccup must degrade gracefully
        log.warning(
            "wiki_refresh_fragment failed for slug=%s; serving degraded shell",
            slug,
            exc_info=True,
        )
        return templates.TemplateResponse(  # type: ignore[no-any-return]
            request=request,
            name="partials/wiki_refresh.html.j2",
            context={
                "wr": None,
                "slug": slug,
                "show_crash_toast": False,
                "degraded": True,
            },
        )
    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request=request,
        name="partials/wiki_refresh.html.j2",
        context={
            "wr": wr,
            "slug": slug,
            "show_crash_toast": _should_flash_crash_toast(wr, request),
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
        files: list[ObsidianFileInfo] = [
            {"path": f.path, "language": f.language} for f in cache.iter_files()
        ]
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
