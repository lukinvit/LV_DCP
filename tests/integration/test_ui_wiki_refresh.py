"""Integration tests: /project/<slug> renders the wiki_refresh panel.

Covers the four shapes the partial must support:

1. no data at all          → panel not rendered
2. last refresh was clean  → green "Last refresh: clean" card
3. last refresh crashed    → red FAILED card with log-tail <details>
4. refresh in progress     → blue "Running" card with phase + progress
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
import pytest
import yaml
from apps.agent.config import add_project
from apps.ui.main import create_app
from libs.copilot.wiki_background import write_last_refresh
from libs.scanning.scanner import scan_project


def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"version": 1, "projects": []}))
    add_project(cfg, project)
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("LVDCP_CLAUDE_PROJECTS_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("LVDCP_USAGE_CACHE_DB", str(tmp_path / "usage.db"))
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))
    monkeypatch.setenv("LVDCP_SUMMARIES_DB", str(tmp_path / "summaries.db"))


def _seed_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "a.py").write_text("def a() -> None: return None\n")
    scan_project(project, mode="full")
    _env(tmp_path, monkeypatch, project)
    return project


def _slug(project: Path) -> str:
    return project.name.lower().replace("_", "-")


@pytest.mark.asyncio
async def test_project_detail_hides_panel_when_no_refresh_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fresh project with no lock and no .refresh.last → no panel at all."""
    project = _seed_project(tmp_path, monkeypatch)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    # Panel header must be absent — partial short-circuits on `wr is None`
    # or when both in_progress=False and last_exit_code is None.
    assert "Wiki background refresh" not in response.text


@pytest.mark.asyncio
async def test_project_detail_renders_clean_last_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """exit_code=0 last run → green 'Last refresh: clean' card, no log tail."""
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(
        project,
        exit_code=0,
        modules_updated=7,
        elapsed_seconds=4.2,
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    assert "Wiki background refresh" in response.text
    assert "Last refresh: clean" in response.text
    assert "7 modules updated" in response.text
    # Clean run must NOT surface a log tail control.
    assert "Log tail" not in response.text


@pytest.mark.asyncio
async def test_project_detail_renders_crash_with_log_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """exit_code=1 last run with log_tail → red FAILED card + <details> block."""
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(
        project,
        exit_code=1,
        modules_updated=3,
        elapsed_seconds=12.0,
        log_tail=[
            "ERROR: llm provider timed out",
            "Traceback (most recent call last):",
            "RuntimeError: upstream 504",
        ],
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    assert "Wiki background refresh" in response.text
    assert "FAILED (exit 1)" in response.text
    assert "3 modules updated before crash" in response.text
    # Log tail lines must be rendered inside the collapsible block.
    assert "Log tail" in response.text
    assert "llm provider timed out" in response.text
    assert "RuntimeError: upstream 504" in response.text


def _seed_running_lock(project: Path, *, phase: str = "generating") -> None:
    """Write a `.refresh.lock` pointing at the test process so _pid_alive=True."""
    lock_dir = project / ".context" / "wiki"
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / ".refresh.lock").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "started_at": time.time(),
                "phase": phase,
                "modules_total": 5,
                "modules_done": 2,
                "current_module": "libs/foo",
            }
        )
    )


@pytest.mark.asyncio
async def test_project_detail_renders_live_in_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live lock with our own PID → blue 'Running' card with phase and progress."""
    project = _seed_project(tmp_path, monkeypatch)
    _seed_running_lock(project)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    assert "Wiki background refresh" in response.text
    assert "Running" in response.text
    assert "phase: generating" in response.text
    assert "2 / 5 modules" in response.text
    assert "libs/foo" in response.text


# -------- v0.8.8: HTMX polling fragment -----------------------------


@pytest.mark.asyncio
async def test_project_detail_adds_htmx_polling_while_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full page render while running must emit hx-get + hx-trigger on the wrapper."""
    project = _seed_project(tmp_path, monkeypatch)
    _seed_running_lock(project)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    # The wrapper must carry the polling attributes so HTMX starts its
    # timer on page load — the whole point of v0.8.8.
    assert f'hx-get="/api/project/{_slug(project)}/wiki-refresh"' in response.text
    assert 'hx-trigger="every 2s"' in response.text
    assert 'hx-swap="outerHTML"' in response.text
    assert 'id="wiki-refresh-panel"' in response.text


@pytest.mark.asyncio
async def test_project_detail_omits_htmx_polling_when_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No running refresh → wrapper has NO hx-get, so HTMX stays silent."""
    project = _seed_project(tmp_path, monkeypatch)
    # Seed a clean last-run record so the section renders — we want to
    # verify the wrapper is present but without polling attributes.
    write_last_refresh(project, exit_code=0, modules_updated=3, elapsed_seconds=2.5)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    assert 'id="wiki-refresh-panel"' in response.text
    # Slice to just the wrapper's opening tag to be sure no hx-get on it.
    panel_slice = response.text.split('id="wiki-refresh-panel"', 1)[1].split(">", 1)[0]
    assert "hx-get=" not in panel_slice
    assert "Last refresh: clean" in response.text


@pytest.mark.asyncio
async def test_wiki_refresh_fragment_endpoint_returns_running_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/project/<slug>/wiki-refresh during a refresh returns running HTML + polling."""
    project = _seed_project(tmp_path, monkeypatch)
    _seed_running_lock(project)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/project/{_slug(project)}/wiki-refresh")

    assert response.status_code == 200
    # Fragment must include the wrapper + hx-get so HTMX keeps polling.
    assert 'id="wiki-refresh-panel"' in response.text
    assert f'hx-get="/api/project/{_slug(project)}/wiki-refresh"' in response.text
    assert "Running" in response.text
    assert "phase: generating" in response.text
    # Fragment must NOT be a full HTML page — no <html>/<body>/<header>.
    assert "<html" not in response.text
    assert "<body" not in response.text


@pytest.mark.asyncio
async def test_wiki_refresh_fragment_endpoint_stops_polling_when_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the refresh completes, the fragment response has NO hx-get → polling halts."""
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=0, modules_updated=7, elapsed_seconds=4.2)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/project/{_slug(project)}/wiki-refresh")

    assert response.status_code == 200
    assert 'id="wiki-refresh-panel"' in response.text
    assert "hx-get=" not in response.text
    assert "Last refresh: clean" in response.text


@pytest.mark.asyncio
async def test_wiki_refresh_fragment_endpoint_returns_404_for_unknown_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown project → 404, same contract as /project/<slug>."""
    _seed_project(tmp_path, monkeypatch)
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/project/does-not-exist/wiki-refresh")
    assert response.status_code == 404


# -------- v0.8.9: crash-transition toast (hx-swap-oob) ---------------


@pytest.mark.asyncio
async def test_project_detail_has_toast_region_for_oob_swaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full page must carry the #toast-region drop zone so HTMX OOB swaps have a target."""
    project = _seed_project(tmp_path, monkeypatch)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    assert 'id="toast-region"' in response.text


@pytest.mark.asyncio
async def test_crash_toast_emitted_on_htmx_fragment_for_fresh_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HX-Request + just-crashed (< 15 s ago) → OOB toast in fragment."""
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(
        project,
        exit_code=2,
        modules_updated=3,
        elapsed_seconds=7.5,
        completed_at=time.time() - 1.0,  # fresh crash, 1 s ago
        log_tail=["ERROR: upstream failure", "RuntimeError: boom"],
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/project/{_slug(project)}/wiki-refresh",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    # OOB toast element must be present with hx-swap-oob targeting #toast-region.
    assert 'hx-swap-oob="beforeend:#toast-region"' in response.text
    assert 'id="crash-toast-' in response.text
    # Toast body carries the crash summary.
    assert "Wiki refresh failed" in response.text
    assert "exited 2" in response.text
    # The panel itself still renders (FAILED card with log tail).
    assert "FAILED (exit 2)" in response.text
    # Polling must be silent now (no hx-get on the wrapper).
    panel_slice = response.text.split('id="wiki-refresh-panel"', 1)[1].split(">", 1)[0]
    assert "hx-get=" not in panel_slice


@pytest.mark.asyncio
async def test_crash_toast_absent_on_non_htmx_full_page_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full page /project/<slug> after a crash must NOT re-flash the toast."""
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(
        project,
        exit_code=2,
        modules_updated=1,
        elapsed_seconds=3.0,
        completed_at=time.time() - 2.0,  # would be fresh if HX-Request were set
        log_tail=["ERROR: crashed"],
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    # FAILED card renders (normal full-page behaviour), but no OOB toast.
    assert "FAILED (exit 2)" in response.text
    assert "hx-swap-oob" not in response.text
    assert "Wiki refresh failed" not in response.text


@pytest.mark.asyncio
async def test_crash_toast_absent_on_stale_crash_outside_freshness_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HX-Request but crash > 15 s old → polling tick must stay silent."""
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(
        project,
        exit_code=2,
        modules_updated=1,
        elapsed_seconds=3.0,
        completed_at=time.time() - 60.0,  # 1 min old → stale
        log_tail=["ERROR: old crash"],
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/project/{_slug(project)}/wiki-refresh",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    assert "FAILED (exit 2)" in response.text
    assert "hx-swap-oob" not in response.text
    assert "Wiki refresh failed" not in response.text


@pytest.mark.asyncio
async def test_crash_toast_absent_on_clean_last_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HX-Request + exit_code=0 → no toast (clean completion)."""
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(
        project,
        exit_code=0,
        modules_updated=5,
        elapsed_seconds=2.1,
        completed_at=time.time() - 1.0,
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/project/{_slug(project)}/wiki-refresh",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    assert "Last refresh: clean" in response.text
    assert "hx-swap-oob" not in response.text


@pytest.mark.asyncio
async def test_crash_toast_absent_on_sigterm_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HX-Request + exit_code=143 (SIGTERM) → no toast; user-initiated cancels stay quiet."""
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(
        project,
        exit_code=143,
        modules_updated=2,
        elapsed_seconds=5.0,
        completed_at=time.time() - 1.0,
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/project/{_slug(project)}/wiki-refresh",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    assert "cancelled (SIGTERM)" in response.text
    assert "hx-swap-oob" not in response.text


@pytest.mark.asyncio
async def test_crash_toast_absent_while_refresh_still_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live refresh → no toast regardless of any past crash record."""
    project = _seed_project(tmp_path, monkeypatch)
    # Seed a fresh crash in the .last record AND a live lock on top —
    # the live lock wins, so no toast should fire until the running
    # refresh itself completes.
    write_last_refresh(
        project,
        exit_code=2,
        modules_updated=1,
        elapsed_seconds=2.0,
        completed_at=time.time() - 2.0,
        log_tail=["ERROR: previous run"],
    )
    _seed_running_lock(project)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/project/{_slug(project)}/wiki-refresh",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    assert "Running" in response.text
    assert "hx-swap-oob" not in response.text
    # Polling must still be active.
    assert 'hx-trigger="every 2s"' in response.text


@pytest.mark.asyncio
async def test_crash_toast_absent_on_manual_curl_without_htmx_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No HX-Request header → no toast even on a fresh crash. Manual curl stays quiet."""
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(
        project,
        exit_code=2,
        modules_updated=1,
        elapsed_seconds=2.0,
        completed_at=time.time() - 1.0,
        log_tail=["ERROR: crash"],
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/project/{_slug(project)}/wiki-refresh")

    assert response.status_code == 200
    assert "FAILED (exit 2)" in response.text
    assert "hx-swap-oob" not in response.text


# -------- v0.8.10: degraded shell on internal error (error backoff) --


@pytest.mark.asyncio
async def test_fragment_returns_degraded_shell_on_workspace_status_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """build_workspace_status raising → 200 with degraded yellow card + slow polling.

    Predates the contract: a 500 mid-poll had HTMX hammering the endpoint
    at 2 s forever. v0.8.10 catches any internal exception, logs it, and
    serves a ``degraded=True`` partial so polling self-heals at 30 s.
    """
    _seed_project(tmp_path, monkeypatch)

    # Patch the symbol at its imported location in the route module so the
    # route sees the failing impl, not the library original.
    import apps.ui.routes.project as project_route

    def _boom() -> object:
        raise RuntimeError("transient config-db hiccup")

    monkeypatch.setattr(project_route, "build_workspace_status", _boom)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Use any slug — the endpoint fails before slug resolution anyway.
        response = await client.get(
            "/api/project/anything/wiki-refresh",
            headers={"HX-Request": "true"},
        )

    # Must NOT 500 — that would keep HTMX hammering at 2 s.
    assert response.status_code == 200
    # Degraded yellow card is present.
    assert "Refresh status unavailable" in response.text
    assert "Retrying every 30s" in response.text
    # Wrapper must keep hx-get so the panel self-heals when infra recovers.
    assert 'hx-get="/api/project/anything/wiki-refresh"' in response.text
    # Critically: polling is THROTTLED to 30 s, not 2 s.
    assert 'hx-trigger="every 30s"' in response.text
    assert 'hx-trigger="every 2s"' not in response.text
    # No crash toast — an infra blip is not a wiki-refresh crash.
    assert "hx-swap-oob" not in response.text


@pytest.mark.asyncio
async def test_fragment_returns_degraded_shell_on_build_wiki_refresh_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """build_wiki_refresh raising (vs returning None) → degraded shell, 30s polling."""
    project = _seed_project(tmp_path, monkeypatch)

    import apps.ui.routes.project as project_route

    def _boom(_root: Path) -> object:
        raise OSError("disk went sideways")

    monkeypatch.setattr(project_route, "build_wiki_refresh", _boom)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/project/{_slug(project)}/wiki-refresh",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    assert "Refresh status unavailable" in response.text
    assert 'hx-trigger="every 30s"' in response.text


@pytest.mark.asyncio
async def test_fragment_404_for_unknown_slug_still_surfaces_on_degradable_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown slug must still return 404 — don't swallow it into the degraded shell.

    A genuine client-side bug (typo, stale bookmark) should surface as
    404 rather than being masked by endless 30 s polling of a slug that
    will never resolve.
    """
    _seed_project(tmp_path, monkeypatch)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/project/totally-made-up/wiki-refresh",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 404
    # Sanity: the degraded card must not appear in a 404 body.
    assert "Refresh status unavailable" not in response.text


@pytest.mark.asyncio
async def test_fragment_happy_path_untouched_by_degraded_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clean idle project renders the normal 'clean' card with NO degraded markers."""
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=0, modules_updated=2, elapsed_seconds=1.0)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/project/{_slug(project)}/wiki-refresh",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    assert "Last refresh: clean" in response.text
    # The degraded-only markers must not leak into the normal card.
    assert "Refresh status unavailable" not in response.text
    assert 'hx-trigger="every 30s"' not in response.text
    # Idle = polling stopped, so no hx-get either.
    panel_slice = response.text.split('id="wiki-refresh-panel"', 1)[1].split(">", 1)[0]
    assert "hx-get=" not in panel_slice


@pytest.mark.asyncio
async def test_project_detail_full_page_still_500s_on_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The degraded-shell contract is fragment-only; full /project/<slug> keeps normal error flow.

    Important to verify because the degraded branch lives in the partial,
    not the page. Serving a degraded panel inside a full page load would
    be user-visible noise on what's probably a hard-broken deploy.
    """
    _seed_project(tmp_path, monkeypatch)

    import apps.ui.routes.project as project_route

    def _boom() -> object:
        raise RuntimeError("status pipeline down")

    monkeypatch.setattr(project_route, "build_workspace_status", _boom)

    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/project/anything")

    # FastAPI surfaces unhandled exceptions as 500.
    assert response.status_code == 500
    # The degraded card must not leak into the error body.
    assert "Refresh status unavailable" not in response.text


# -------- v0.8.11: recovery toast on degraded → normal transition ----


@pytest.mark.asyncio
async def test_degraded_wrapper_carries_was_degraded_marker_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Degraded shell emits ``hx-headers`` so the next HTMX poll round-trips the marker.

    Without the marker the server would have no way to tell a
    degraded→normal transition from a plain steady-state normal poll,
    and the recovery toast could never fire.
    """
    _seed_project(tmp_path, monkeypatch)

    import apps.ui.routes.project as project_route

    def _boom() -> object:
        raise RuntimeError("transient hiccup")

    monkeypatch.setattr(project_route, "build_workspace_status", _boom)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/project/anything/wiki-refresh",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    # The hx-headers attribute carries the marker as JSON — HTMX echoes
    # each key in the JSON object as a request header on the next fetch.
    assert "hx-headers=" in response.text
    assert "X-LV-DCP-Was-Degraded" in response.text
    assert '"true"' in response.text


@pytest.mark.asyncio
async def test_recovery_toast_emitted_when_was_degraded_header_present_and_now_recovered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HX-Request + X-LV-DCP-Was-Degraded marker + successful assembly → green recovery toast."""
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=0, modules_updated=3, elapsed_seconds=1.5)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/project/{_slug(project)}/wiki-refresh",
            headers={
                "HX-Request": "true",
                "X-LV-DCP-Was-Degraded": "true",
            },
        )

    assert response.status_code == 200
    # Green recovery toast must be present with the OOB swap target.
    assert f'id="recovery-toast-{_slug(project)}"' in response.text
    assert 'hx-swap-oob="beforeend:#toast-region"' in response.text
    assert "Wiki refresh status recovered" in response.text
    # Normal clean card is still present — the panel swapped back to normal.
    assert "Last refresh: clean" in response.text
    # The new wrapper MUST NOT re-emit the marker, or the next poll would
    # replay the toast on every tick. Confirm by slicing just the wrapper.
    panel_slice = response.text.split('id="wiki-refresh-panel"', 1)[1].split(">", 1)[0]
    assert "hx-headers" not in panel_slice


@pytest.mark.asyncio
async def test_recovery_toast_absent_without_was_degraded_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Steady-state normal polling never emits a recovery toast."""
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=0, modules_updated=2, elapsed_seconds=1.0)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/project/{_slug(project)}/wiki-refresh",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    assert "Wiki refresh status recovered" not in response.text
    assert "recovery-toast-" not in response.text
    # Sanity: the normal clean card is still there.
    assert "Last refresh: clean" in response.text


@pytest.mark.asyncio
async def test_recovery_toast_absent_when_still_degraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Infra still broken → response stays degraded, no recovery toast even with the marker.

    A degraded-to-degraded transition is still "broken", not "recovered".
    The marker re-echoes on the next poll (still a degraded wrapper), so
    when the infra eventually comes back the toast fires then.
    """
    _seed_project(tmp_path, monkeypatch)

    import apps.ui.routes.project as project_route

    def _boom() -> object:
        raise RuntimeError("still broken")

    monkeypatch.setattr(project_route, "build_workspace_status", _boom)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/project/anything/wiki-refresh",
            headers={
                "HX-Request": "true",
                "X-LV-DCP-Was-Degraded": "true",
            },
        )

    assert response.status_code == 200
    # Still degraded.
    assert "Refresh status unavailable" in response.text
    # No recovery toast.
    assert "Wiki refresh status recovered" not in response.text
    assert "recovery-toast-" not in response.text
    # Marker STILL on the wrapper so the next poll can try again.
    assert "X-LV-DCP-Was-Degraded" in response.text


@pytest.mark.asyncio
async def test_recovery_toast_absent_on_non_htmx_full_page_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A user navigating to /project/<slug> after an old recovery never sees the toast.

    The full page path renders the partial with ``show_recovery_toast``
    absent from the template context entirely, so even if a user
    manually spoofed the marker header the page wouldn't flash.
    """
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=0, modules_updated=2, elapsed_seconds=1.0)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Full page load — note NO HX-Request header, despite the spoofed marker.
        response = await client.get(
            f"/project/{_slug(project)}",
            headers={"X-LV-DCP-Was-Degraded": "true"},
        )

    assert response.status_code == 200
    assert "Wiki refresh status recovered" not in response.text
    assert "recovery-toast-" not in response.text
