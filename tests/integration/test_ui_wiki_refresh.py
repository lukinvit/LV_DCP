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


# -------- v0.8.12: recovery toast auto-dismiss ---------------------


@pytest.mark.asyncio
async def test_recovery_toast_carries_auto_dismiss_animation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recovery toast inline style includes the fadeout animation so it auto-dismisses.

    Transient good news shouldn't require a manual click to clear. The
    inline ``animation: lvdcp-toast-fadeout 8s forwards`` holds full
    opacity for 6 s then fades over 2 s, and ``forwards`` pins the end
    state (opacity 0 + pointer-events: none) so nothing blocks clicks
    after it disappears. The @keyframes definition is inlined
    alongside the toast so it's only in the DOM when the toast renders.
    """
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
    # The toast itself must reference the animation.
    assert "animation:lvdcp-toast-fadeout 8s forwards" in response.text
    # The keyframes definition must be present so the animation resolves.
    assert "@keyframes lvdcp-toast-fadeout" in response.text
    # The fadeout must terminate at pointer-events: none so the invisible
    # end-state doesn't intercept clicks on whatever is underneath.
    assert "pointer-events: none" in response.text


@pytest.mark.asyncio
async def test_crash_toast_does_not_carry_auto_dismiss_animation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crash toast stays sticky — bad news the user must acknowledge.

    Auto-dismissing a 'wiki refresh failed' banner would be a UX bug: a
    user scrolled away could miss the only signal that anything broke.
    The recovery toast auto-dismisses, the crash toast does not; this
    test locks in that asymmetry.
    """
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=2, modules_updated=1, elapsed_seconds=0.5)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/project/{_slug(project)}/wiki-refresh",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    # Sanity: the crash toast is actually present.
    assert "Wiki refresh failed" in response.text
    assert f'id="crash-toast-{_slug(project)}' in response.text
    # Asymmetry: the fadeout animation must NOT be attached to the crash toast.
    assert "lvdcp-toast-fadeout" not in response.text


@pytest.mark.asyncio
async def test_no_fadeout_keyframes_when_no_recovery_toast_rendered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Normal idle poll without a recovery toast ships zero unused fadeout CSS.

    The keyframes block is scoped to the ``{% if show_recovery_toast %}``
    guard so a clean idle body has no ``@keyframes lvdcp-toast-fadeout``
    definition floating around. Keeps the fragment small and avoids
    HTMX swapping in duplicate style nodes on every poll.
    """
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=0, modules_updated=2, elapsed_seconds=1.0)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Steady-state normal polling — no recovery, no crash.
        response = await client.get(
            f"/api/project/{_slug(project)}/wiki-refresh",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    assert "Last refresh: clean" in response.text
    # No fadeout CSS because no toast is present.
    assert "lvdcp-toast-fadeout" not in response.text


# -------- v0.8.13: accessibility + hover polish on the fadeout -------


@pytest.mark.asyncio
async def test_recovery_toast_respects_prefers_reduced_motion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recovery toast carries a ``prefers-reduced-motion`` media query.

    Users who've opted out of OS-level motion (screen reader, vestibular
    sensitivity, etc.) should not see the fade — the toast stays sticky
    like the crash toast instead. The rule is ``animation: none``,
    ``opacity: 1``, ``pointer-events: auto`` (all ``!important`` to
    override the inline ``animation`` shorthand). The ``.lvdcp-recovery-
    toast`` class must be attached to the toast div so the rule has a
    target to hit.
    """
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
    # The class hook must be present on the toast div.
    assert 'class="lvdcp-recovery-toast"' in response.text
    # The reduced-motion media query must be present.
    assert "@media (prefers-reduced-motion: reduce)" in response.text
    # Inside it, the animation must be cancelled and full opacity pinned.
    assert "animation: none !important" in response.text
    assert "opacity: 1 !important" in response.text
    # And the toast must remain interactive (dismiss button stays clickable).
    assert "pointer-events: auto !important" in response.text


@pytest.mark.asyncio
async def test_recovery_toast_pauses_on_hover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recovery toast CSS pauses the fade animation while the cursor is over it.

    If a user is mid-glance when the fade starts, moving the cursor onto
    the toast freezes it at the current opacity. Moving off resumes.
    Implemented as ``.lvdcp-recovery-toast:hover { animation-play-state:
    paused !important; }`` — ``!important`` is needed to override the
    inline ``animation`` shorthand which resets play-state to ``running``.
    """
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
    # Class selector for hover is present.
    assert ".lvdcp-recovery-toast:hover" in response.text
    # Paused state is applied with !important to beat the inline shorthand.
    assert "animation-play-state: paused !important" in response.text


@pytest.mark.asyncio
async def test_no_a11y_css_when_no_recovery_toast_rendered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Normal idle poll without a recovery toast ships zero a11y CSS.

    Parallel to ``test_no_fadeout_keyframes_when_no_recovery_toast_
    rendered``: the hover rule and the ``prefers-reduced-motion`` media
    query live inside the same ``{% if show_recovery_toast %}`` guard as
    the keyframes, so a clean idle response must not carry them either.
    Prevents accidentally leaving a11y rules in a non-toast response.
    """
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
    # Neither the media query nor the hover selector nor the class hook
    # should be present when no toast renders.
    assert "prefers-reduced-motion" not in response.text
    assert ".lvdcp-recovery-toast:hover" not in response.text
    assert "lvdcp-recovery-toast" not in response.text


# -------- v0.8.14: "Retry now" button on the degraded card -----------


@pytest.mark.asyncio
async def test_degraded_card_carries_retry_now_button(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Degraded response renders a button that hits the same endpoint on click.

    The 30s polling is a fallback, not the only escape hatch. A user who
    knows infra just came back should be able to force a retry. The
    button uses HTMX (``hx-get`` + ``hx-target`` + ``hx-swap`` pointing
    at the outer wrapper), identical to what the polling tick does on
    itself — so on success the wiki_refresh panel is replaced with the
    real card, on continued failure the degraded card is re-rendered
    in place.
    """
    project = _seed_project(tmp_path, monkeypatch)

    import apps.ui.routes.project as project_route

    def _boom(_root: Path) -> object:
        raise RuntimeError("transient hiccup")

    monkeypatch.setattr(project_route, "build_wiki_refresh", _boom)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/project/{_slug(project)}/wiki-refresh",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    # Sanity: we're in the degraded branch.
    assert "Refresh status unavailable" in response.text
    # Button text, id, and all the HTMX attrs must be there.
    assert (
        ">Retry now</button>" in response.text.replace("\n", "").replace("        ", "")
        or "Retry now" in response.text
    )
    assert f'id="wiki-refresh-retry-{_slug(project)}"' in response.text
    assert f'hx-get="/api/project/{_slug(project)}/wiki-refresh"' in response.text
    # Target the outer wrapper so the swap replaces the whole panel.
    assert 'hx-target="#wiki-refresh-panel"' in response.text
    assert 'hx-swap="outerHTML"' in response.text
    # ``hx-disabled-elt`` prevents a double-click from firing two parallel reqs.
    assert 'hx-disabled-elt="this"' in response.text


@pytest.mark.asyncio
async def test_retry_now_button_absent_on_happy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-degraded responses do not render the Retry button.

    The button lives inside the ``{% if degraded %}`` branch, so a clean
    last-run render — or a running refresh render — must never carry it.
    Locks in the scope invariant: Retry now is a degraded-mode-only
    affordance, not a general "force poll" button.
    """
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=0, modules_updated=5, elapsed_seconds=2.0)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/project/{_slug(project)}/wiki-refresh",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    assert "Last refresh: clean" in response.text
    assert "Retry now" not in response.text
    assert f'id="wiki-refresh-retry-{_slug(project)}"' not in response.text


@pytest.mark.asyncio
async def test_retry_now_button_carries_was_degraded_marker_for_recovery_toast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retry button echoes the same recovery marker the polling wrapper does.

    The wrapper element in degraded mode carries
    ``hx-headers='{"X-LV-DCP-Was-Degraded": "true"}'`` so the next
    successful poll gets the recovery toast. The Retry-now button must
    carry the exact same marker — otherwise clicking Retry at the
    moment infra recovers would silently return a normal card without
    the "recovered" confirmation, and the user would wonder whether
    the click did anything. Marker parity means manual retry and auto
    retry have identical success UX.
    """
    project = _seed_project(tmp_path, monkeypatch)

    import apps.ui.routes.project as project_route

    def _boom(_root: Path) -> object:
        raise RuntimeError("transient hiccup")

    monkeypatch.setattr(project_route, "build_wiki_refresh", _boom)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/project/{_slug(project)}/wiki-refresh",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    # Both the wrapper (for polling) AND the button (for manual click)
    # must carry the marker. Parity = identical recovery-toast UX from
    # either trigger source. Count the JSON key/value substring rather
    # than the full ``hx-headers`` attribute — v0.8.15 added a second
    # key (``X-LV-DCP-Retry-Source``) to the button's header JSON, so
    # the exact wrapper string and the exact button string differ, but
    # the marker pair itself still appears in both.
    assert response.text.count('"X-LV-DCP-Was-Degraded": "true"') >= 2, (
        "Expected the X-LV-DCP-Was-Degraded marker on BOTH the polling "
        "wrapper and the Retry button."
    )


# -------- v0.8.15: toast-render telemetry (structured logs) ----------


@pytest.mark.asyncio
async def test_crash_toast_render_emits_telemetry_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Rendering a crash toast emits a structured log event with slug + kind.

    The route logs ``ui.wiki_refresh.toast.rendered`` via stdlib
    ``logging`` with ``extra={"event": ..., "slug": ..., "kind": "crash"}``
    when the fragment response carries a one-shot crash toast. Lets
    observers answer "which projects flap their refresh binary and how
    often" without having to parse the HTML response.
    """
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=1, modules_updated=3, elapsed_seconds=2.1)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    with caplog.at_level("INFO", logger="apps.ui.routes.project"):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                f"/api/project/{_slug(project)}/wiki-refresh",
                headers={"HX-Request": "true"},
            )

    assert response.status_code == 200
    # Sanity: the red crash toast must actually be in the response, so
    # the telemetry is about the same render path a user would see.
    assert "Wiki refresh failed" in response.text

    rendered = [r for r in caplog.records if r.getMessage() == "ui.wiki_refresh.toast.rendered"]
    assert len(rendered) == 1, f"Expected exactly one toast.rendered event; got {len(rendered)}"
    record = rendered[0]
    assert record.levelname == "INFO"
    assert getattr(record, "event", None) == "ui.wiki_refresh.toast.rendered"
    assert getattr(record, "slug", None) == _slug(project)
    assert getattr(record, "kind", None) == "crash"
    # Crash path never carries a "trigger" field — only recovery does.
    # ``getattr`` instead of attr access: ``LogRecord`` has no declared
    # ``trigger`` attribute, so a direct ``record.trigger`` would fail
    # mypy even guarded by ``hasattr``.
    assert not hasattr(record, "trigger") or getattr(record, "trigger", None) is None


@pytest.mark.asyncio
async def test_recovery_toast_via_poll_emits_trigger_poll(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Auto-poll recovery (no Retry-Source header) classifies trigger=poll.

    The 30 s polling wrapper carries only ``X-LV-DCP-Was-Degraded:
    true``. When that poll lands on a now-healthy backend the route
    flips the recovery toast and must log ``trigger=poll`` so observers
    can separate "auto-recovery" from "user-initiated retry" dominance.
    """
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=0, modules_updated=2, elapsed_seconds=1.0)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    with caplog.at_level("INFO", logger="apps.ui.routes.project"):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                f"/api/project/{_slug(project)}/wiki-refresh",
                headers={
                    "HX-Request": "true",
                    "X-LV-DCP-Was-Degraded": "true",
                },
            )

    assert response.status_code == 200
    # Sanity: the green recovery toast is actually in the response.
    assert "Wiki refresh status recovered" in response.text

    rendered = [r for r in caplog.records if r.getMessage() == "ui.wiki_refresh.toast.rendered"]
    assert len(rendered) == 1
    record = rendered[0]
    assert getattr(record, "kind", None) == "recovery"
    assert getattr(record, "slug", None) == _slug(project)
    assert getattr(record, "trigger", None) == "poll"


@pytest.mark.asyncio
async def test_recovery_toast_via_manual_retry_emits_trigger_manual(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Retry-button recovery (X-LV-DCP-Retry-Source: manual) → trigger=manual.

    The v0.8.14 Retry button carries both headers — the degraded marker
    AND ``X-LV-DCP-Retry-Source: manual``. The route classifies this
    as ``trigger=manual`` so a "0% of recoveries are manual" signal
    would flag the button as invisible to users; a "90% manual" signal
    would flag the 30 s poll cadence as too slow.
    """
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=0, modules_updated=2, elapsed_seconds=1.0)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    with caplog.at_level("INFO", logger="apps.ui.routes.project"):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                f"/api/project/{_slug(project)}/wiki-refresh",
                headers={
                    "HX-Request": "true",
                    "X-LV-DCP-Was-Degraded": "true",
                    "X-LV-DCP-Retry-Source": "manual",
                },
            )

    assert response.status_code == 200
    assert "Wiki refresh status recovered" in response.text

    rendered = [r for r in caplog.records if r.getMessage() == "ui.wiki_refresh.toast.rendered"]
    assert len(rendered) == 1
    record = rendered[0]
    assert getattr(record, "kind", None) == "recovery"
    assert getattr(record, "trigger", None) == "manual"


@pytest.mark.asyncio
async def test_no_telemetry_emitted_on_idle_poll(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Clean poll with no toast path emits zero toast.rendered events.

    An ordinary 2 s polling tick on a healthy running/idle panel must
    NOT pollute logs with ``toast.rendered`` — the event name implies
    a toast actually appeared in the user's DOM. Firing the event on
    every clean poll would drown real signal in noise.
    """
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=0, modules_updated=2, elapsed_seconds=1.0)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    with caplog.at_level("INFO", logger="apps.ui.routes.project"):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                f"/api/project/{_slug(project)}/wiki-refresh",
                headers={"HX-Request": "true"},
            )

    assert response.status_code == 200
    assert "Last refresh: clean" in response.text

    rendered = [r for r in caplog.records if r.getMessage() == "ui.wiki_refresh.toast.rendered"]
    assert len(rendered) == 0


@pytest.mark.asyncio
async def test_retry_button_carries_retry_source_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The v0.8.14 Retry button declares ``X-LV-DCP-Retry-Source: manual``.

    Locks in the template contract that enables trigger classification
    on the server side. Without this header the route would classify
    any recovery as ``trigger=poll`` regardless of source, because the
    polling wrapper never sets the header. The button's hx-headers JSON
    must include both keys; the wrapper's must include only the degraded
    marker.
    """
    project = _seed_project(tmp_path, monkeypatch)

    import apps.ui.routes.project as project_route

    def _boom(_root: Path) -> object:
        raise RuntimeError("transient hiccup")

    monkeypatch.setattr(project_route, "build_wiki_refresh", _boom)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/project/{_slug(project)}/wiki-refresh",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    # The Retry button's header JSON carries both markers.
    assert '"X-LV-DCP-Retry-Source": "manual"' in response.text
    # Only the button should have the retry-source marker; the polling
    # wrapper must not (its absence is the "trigger=poll" signal).
    assert response.text.count('"X-LV-DCP-Retry-Source": "manual"') == 1


# -------- v0.8.16: forced-colors adaptation on both toasts -----------


@pytest.mark.asyncio
async def test_crash_toast_carries_forced_colors_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crash toast ships a ``@media (forced-colors: active)`` override.

    Windows high-contrast mode and similar accessibility palettes drop
    ``box-shadow`` and remap solid colors to system ``Canvas`` /
    ``CanvasText``, so a banner with only a colored background blends
    into the page. The v0.8.16 override adds a ``border: 1px solid
    CanvasText`` (visible frame) and pins ``box-shadow: none`` so the
    banner stays visually distinct regardless of UA shadow-drop policy.
    The ``<code>`` slug chip gets the same border treatment; the
    dismiss button's opacity is pinned to 1 so it doesn't look disabled
    in high-contrast.
    """
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=1, modules_updated=2, elapsed_seconds=1.5)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/project/{_slug(project)}/wiki-refresh",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    # Sanity: crash toast must actually render so the rule is attached
    # to a visible element.
    assert "Wiki refresh failed" in response.text
    # Class hook for the rule selector.
    assert 'class="lvdcp-crash-toast"' in response.text
    # The media query must be present.
    assert "@media (forced-colors: active)" in response.text
    # Border + shadow rule on the banner itself.
    assert ".lvdcp-crash-toast { border: 1px solid CanvasText !important;" in response.text
    assert "box-shadow: none !important" in response.text
    # Code chip + button overrides.
    assert ".lvdcp-crash-toast code { border: 1px solid CanvasText !important; }" in response.text
    assert ".lvdcp-crash-toast button { opacity: 1 !important; }" in response.text


@pytest.mark.asyncio
async def test_recovery_toast_carries_forced_colors_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recovery toast ships the same forced-colors override + cancels fade.

    Parallel to the crash-toast treatment, plus an extra guarantee: the
    v0.8.12 fadeout animation is cancelled in forced-colors mode. A user
    with OS-level high-contrast turned on is almost certainly an
    accessibility user; banners that vanish on a timer are hostile to
    screen-reader and low-vision workflows. Same reasoning as
    ``prefers-reduced-motion`` (v0.8.13): when in doubt, stay sticky.
    """
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=0, modules_updated=2, elapsed_seconds=1.0)

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
    assert "Wiki refresh status recovered" in response.text
    assert 'class="lvdcp-recovery-toast"' in response.text
    # The media query must be present (alongside the existing
    # prefers-reduced-motion block).
    assert "@media (forced-colors: active)" in response.text
    # Border + shadow + animation-cancel rule on the banner itself.
    assert "border: 1px solid CanvasText !important" in response.text
    assert "box-shadow: none !important" in response.text
    # Same fadeout-kill semantics as prefers-reduced-motion: stay
    # sticky with full opacity.
    assert (
        ".lvdcp-recovery-toast { animation: none !important; opacity: 1 !important;"
        in response.text
    )
    # Code chip + button overrides scoped to the class.
    assert (
        ".lvdcp-recovery-toast code { border: 1px solid CanvasText !important; }" in response.text
    )
    assert ".lvdcp-recovery-toast button { opacity: 1 !important; }" in response.text


@pytest.mark.asyncio
async def test_no_forced_colors_rule_when_no_toast_rendered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clean idle poll ships zero forced-colors CSS.

    Parallel to ``test_no_a11y_css_when_no_recovery_toast_rendered``:
    the forced-colors rules live inside the ``{% if show_crash_toast %}``
    and ``{% if show_recovery_toast %}`` guards respectively, so a
    healthy idle response must not carry either. Prevents accidentally
    leaving the media query in a non-toast response.
    """
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
    assert "forced-colors" not in response.text
    assert "CanvasText" not in response.text
    assert "lvdcp-crash-toast" not in response.text
    assert "lvdcp-recovery-toast" not in response.text


@pytest.mark.asyncio
async def test_forced_colors_rule_scoped_to_each_toast_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crash rule doesn't bleed into recovery render and vice versa.

    The two style blocks live inside their own ``{% if %}`` guards, so
    a crash-only render must NOT carry ``.lvdcp-recovery-toast`` rules,
    and a recovery-only render must NOT carry ``.lvdcp-crash-toast``
    rules. Prevents a future refactor from accidentally promoting
    either rule to a shared global scope — they'd then render on idle
    polls.
    """
    project = _seed_project(tmp_path, monkeypatch)

    # Crash-only render.
    write_last_refresh(project, exit_code=1, modules_updated=1, elapsed_seconds=1.5)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        crash_response = await client.get(
            f"/api/project/{_slug(project)}/wiki-refresh",
            headers={"HX-Request": "true"},
        )

    assert crash_response.status_code == 200
    assert "Wiki refresh failed" in crash_response.text
    assert "lvdcp-crash-toast" in crash_response.text
    # Recovery rule must not appear on a crash-only render.
    assert "lvdcp-recovery-toast" not in crash_response.text

    # Recovery-only render (reseed with a clean run).
    write_last_refresh(project, exit_code=0, modules_updated=2, elapsed_seconds=1.0)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        recovery_response = await client.get(
            f"/api/project/{_slug(project)}/wiki-refresh",
            headers={
                "HX-Request": "true",
                "X-LV-DCP-Was-Degraded": "true",
            },
        )

    assert recovery_response.status_code == 200
    assert "Wiki refresh status recovered" in recovery_response.text
    assert "lvdcp-recovery-toast" in recovery_response.text
    # Crash rule must not appear on a recovery-only render.
    assert "lvdcp-crash-toast" not in recovery_response.text


# -------- v0.8.17: a11y parity on the lvdcp-pulse running indicator ----


@pytest.mark.asyncio
async def test_running_dot_carries_pulse_class_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The blue "Running" status dot carries ``lvdcp-pulse-dot`` class.

    Without the class hook the inline ``style="animation:lvdcp-pulse..."``
    on the span has no way to accept scoped a11y overrides. Locks in the
    template contract so a future refactor can't strip the class.
    """
    project = _seed_project(tmp_path, monkeypatch)
    _seed_running_lock(project)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    # Sanity: the Running card is actually rendered.
    assert "Running" in response.text
    assert "phase: generating" in response.text
    # The class hook must be on the pulsing dot span.
    assert 'class="lvdcp-pulse-dot"' in response.text


@pytest.mark.asyncio
async def test_running_dot_respects_prefers_reduced_motion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running dot ships a ``@media (prefers-reduced-motion: reduce)`` override.

    Users who've opted out of OS-level motion must not be subjected to
    an infinite pulsing animation on a status indicator. The override
    cancels ``animation`` and pins opacity to 1 so the dot becomes a
    static visible indicator — the adjacent "Running" text still
    conveys the state signal. Mirrors the v0.8.13 treatment on the
    recovery toast fade.
    """
    project = _seed_project(tmp_path, monkeypatch)
    _seed_running_lock(project)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    assert "@media (prefers-reduced-motion: reduce)" in response.text
    # Rule must scope to the dot class.
    assert (
        ".lvdcp-pulse-dot { animation: none !important; opacity: 1 !important; }" in response.text
    )


@pytest.mark.asyncio
async def test_running_dot_respects_forced_colors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running dot ships a ``@media (forced-colors: active)`` override.

    In Windows high-contrast mode the dot's inline ``background:#1976d2``
    gets remapped to ``Canvas``, which matches the page background → dot
    is invisible. The fix uses ``background: CanvasText !important``
    (system-color tokens are preserved in forced-colors mode), so the
    dot becomes a solid visible shape in the user's contrast palette.
    Also cancels the animation — same reasoning as v0.8.13 / v0.8.16:
    a11y-mode users shouldn't pay a motion tax for a decorative effect.
    """
    project = _seed_project(tmp_path, monkeypatch)
    _seed_running_lock(project)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    assert "@media (forced-colors: active)" in response.text
    # Rule must cancel animation, pin opacity, AND set a visible background.
    assert (
        ".lvdcp-pulse-dot { animation: none !important; opacity: 1 !important; "
        "background: CanvasText !important; }"
    ) in response.text


@pytest.mark.asyncio
async def test_no_pulse_a11y_css_when_not_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Idle / clean / crashed responses ship zero pulse-dot a11y CSS.

    The dot only renders inside ``{% if wr.in_progress %}`` and its
    ``<style>`` block is scoped to the same branch. A clean last-run
    card, a crash card, or a no-data response must not carry the
    ``lvdcp-pulse-dot`` class, the media queries, or the keyframes.
    Prevents a future refactor from leaking the animation CSS onto
    non-running responses.
    """
    project = _seed_project(tmp_path, monkeypatch)
    # Clean last run — not running, no lock.
    write_last_refresh(project, exit_code=0, modules_updated=2, elapsed_seconds=1.0)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    assert "Last refresh: clean" in response.text
    assert "lvdcp-pulse-dot" not in response.text
    assert "lvdcp-pulse" not in response.text
    # Neither media query should be present — they live in the same
    # ``<style>`` block as the pulse keyframes, guarded by the same
    # ``{% if wr.in_progress %}`` branch.
    # Note: the page may carry forced-colors CSS from OTHER elements
    # (toasts, etc.) — but the pulse-specific class must be absent.


@pytest.mark.asyncio
async def test_pulse_keyframes_still_present_for_running_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: the animation itself is NOT removed, only adapted.

    Users without a11y preferences still see the pulsing dot — the
    v0.8.17 change adds media queries, it doesn't delete the default
    behaviour. Locks in that the ``@keyframes lvdcp-pulse`` block and
    the inline ``animation:lvdcp-pulse ...`` attribute stay present.
    """
    project = _seed_project(tmp_path, monkeypatch)
    _seed_running_lock(project)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    # Keyframes block still shipped.
    assert "@keyframes lvdcp-pulse" in response.text
    # Inline animation still declared on the dot.
    assert "animation:lvdcp-pulse 1.5s infinite ease-in-out" in response.text


# -------- v0.8.18: a11y parity on the wiki_refresh progress bar ----


@pytest.mark.asyncio
async def test_progress_bar_carries_track_class_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The progress bar track ships with ``class="lvdcp-progress-track"``.

    Without the class hook the inline ``background:#bbdefb`` on the outer
    track div has no way to accept scoped forced-colors overrides. Locks
    in the template contract so a refactor can't silently strip it.
    """
    project = _seed_project(tmp_path, monkeypatch)
    _seed_running_lock(project)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    # Sanity: Running card + progress bar actually rendered.
    assert "Running" in response.text
    assert "2 / 5 modules" in response.text
    assert 'class="lvdcp-progress-track"' in response.text


@pytest.mark.asyncio
async def test_progress_bar_carries_fill_class_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The progress bar fill ships with ``class="lvdcp-progress-fill"``.

    Parallel to the track hook: the inline ``background:#1976d2`` on the
    inner fill div needs a class hook for the forced-colors override and
    the ``transition:width 0.3s`` needs one for prefers-reduced-motion.
    """
    project = _seed_project(tmp_path, monkeypatch)
    _seed_running_lock(project)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    assert 'class="lvdcp-progress-fill"' in response.text


@pytest.mark.asyncio
async def test_progress_bar_respects_forced_colors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Progress bar ships scoped ``forced-colors: active`` rules.

    In Windows high-contrast mode (and similar accessibility palettes)
    the UA remaps both ``#bbdefb`` (track) and ``#1976d2`` (fill) to
    system ``Canvas`` — which equals the page background, so the 6 px
    bar becomes an invisible sliver and the module-progress signal is
    gone. Track gets a 1 px ``CanvasText`` border (preserved under
    forced-colors), fill is painted with ``background: CanvasText``
    so it's a solid dense shape against the remapped track. Also
    cancels the fill's ``transition: width 0.3s`` — consistency with
    the v0.8.17 dot rule (when in doubt, stay static in a11y mode).
    """
    project = _seed_project(tmp_path, monkeypatch)
    _seed_running_lock(project)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    assert "@media (forced-colors: active)" in response.text
    assert (".lvdcp-progress-track { border: 1px solid CanvasText !important; }") in response.text
    assert (
        ".lvdcp-progress-fill { background: CanvasText !important; transition: none !important; }"
    ) in response.text


@pytest.mark.asyncio
async def test_progress_bar_respects_prefers_reduced_motion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Progress bar cancels ``transition: width 0.3s`` under reduced-motion.

    The fill's width is re-rendered on every HTMX poll tick (every 2 s)
    as ``modules_done`` advances, and the inline ``transition:width 0.3s``
    animates each jump. That's a repeating motion effect users with
    ``prefers-reduced-motion: reduce`` have opted out of — the bar
    should snap to its new width without the slide. Track + fill
    remain visually identical otherwise; only the transition is killed.
    """
    project = _seed_project(tmp_path, monkeypatch)
    _seed_running_lock(project)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    assert "@media (prefers-reduced-motion: reduce)" in response.text
    assert ".lvdcp-progress-fill { transition: none !important; }" in response.text


@pytest.mark.asyncio
async def test_no_progress_bar_dom_when_no_modules_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If ``modules_total`` is absent, the progress bar DOM isn't rendered.

    The ``{% if wr.modules_total %}`` guard omits both the track and
    fill divs entirely when the module count isn't known yet (early
    "starting" phase). The ``class="..."`` attributes must not appear
    in the DOM even though the Running card itself renders. Locks in
    the nested-guard contract so a refactor can't leak the bar onto
    pre-total responses (which would divide-by-zero on the Jinja
    ``modules_done / modules_total`` expression).

    Note: the a11y ``<style>`` block on the Running card still ships
    (the selectors are inert without the matching elements) — this
    test asserts the DOM contract, not the CSS payload.
    """
    project = _seed_project(tmp_path, monkeypatch)
    # Running lock, but NO modules_total — the progress bar branch is skipped.
    lock_dir = project / ".context" / "wiki"
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / ".refresh.lock").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "started_at": time.time(),
                "phase": "starting",
            }
        )
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    assert "Running" in response.text
    # Neither class-hook element renders in the DOM.
    assert 'class="lvdcp-progress-track"' not in response.text
    assert 'class="lvdcp-progress-fill"' not in response.text


@pytest.mark.asyncio
async def test_no_progress_a11y_css_when_not_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clean / crashed / idle responses don't ship the progress-bar classes.

    The progress bar only lives inside ``{% if wr.in_progress %}`` (and
    the nested ``{% if wr.modules_total %}``). A clean last-run response
    has no Running card at all — so both the DOM class hooks AND the
    progress-specific media-query rules must be absent (the whole
    ``<style>`` block they live in is scoped to the Running branch).
    Same discipline as the v0.8.17 pulse-dot absence test.
    """
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=0, modules_updated=2, elapsed_seconds=1.0)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    assert "Last refresh: clean" in response.text
    assert "lvdcp-progress-track" not in response.text
    assert "lvdcp-progress-fill" not in response.text


@pytest.mark.asyncio
async def test_progress_bar_transition_still_present_for_running_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: default ``transition:width 0.3s`` still ships.

    v0.8.18 adapts the transition under prefers-reduced-motion; it does
    NOT remove it for users without a11y preferences. Locks in that the
    inline ``transition:width 0.3s`` stays on the fill element so the
    smooth progress-fill slide isn't silently dropped by a future edit.
    """
    project = _seed_project(tmp_path, monkeypatch)
    _seed_running_lock(project)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    assert "transition:width 0.3s" in response.text


# -------- v0.8.19: outage-duration signal on recovery toast ---------


@pytest.mark.asyncio
async def test_degraded_wrapper_stamps_degraded_since_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First degraded render stamps an integer Unix timestamp for X-LV-DCP-Degraded-Since.

    The v0.8.19 hx-headers JSON on the degraded wrapper must include
    ``X-LV-DCP-Degraded-Since`` alongside the v0.8.11 was-degraded
    marker. Value is ``int(time.time())`` at render time and is echoed
    back on every subsequent poll via HTMX so the recovery tick can
    compute ``now - since``.
    """
    _seed_project(tmp_path, monkeypatch)

    import apps.ui.routes.project as project_route

    def _boom() -> object:
        raise RuntimeError("transient hiccup")

    monkeypatch.setattr(project_route, "build_workspace_status", _boom)

    before = int(time.time())
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/project/anything/wiki-refresh",
            headers={"HX-Request": "true"},
        )
    after = int(time.time())

    assert response.status_code == 200
    # Key appears in hx-headers JSON on the wrapper.
    assert "X-LV-DCP-Degraded-Since" in response.text
    # Extract the value the template rendered and sanity-check it is
    # a plausible timestamp (within the ±1 s test-execution window).
    # Match the wrapper's hx-headers value, not the retry button's.
    panel_slice = response.text.split('id="wiki-refresh-panel"', 1)[1].split(">", 1)[0]
    assert "X-LV-DCP-Degraded-Since" in panel_slice
    # Extract the int following the header key in the panel's hx-headers.
    marker = '"X-LV-DCP-Degraded-Since": "'
    idx = panel_slice.index(marker) + len(marker)
    end = panel_slice.index('"', idx)
    ts = int(panel_slice[idx:end])
    assert before <= ts <= after


@pytest.mark.asyncio
async def test_degraded_wrapper_preserves_incoming_degraded_since(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Subsequent degraded polls echo the SAME timestamp, not a fresh one.

    This is the core round-trip invariant: a long multi-tick outage
    must report its original start time so the recovery toast says
    "reachable again after 2m 17s", not "after 30s" (which would just
    be the gap between the last degraded tick and the recovery tick).
    """
    _seed_project(tmp_path, monkeypatch)

    import apps.ui.routes.project as project_route

    def _boom() -> object:
        raise RuntimeError("still broken")

    monkeypatch.setattr(project_route, "build_workspace_status", _boom)

    # Pretend the outage started 137 seconds ago.
    original = int(time.time()) - 137

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/project/anything/wiki-refresh",
            headers={
                "HX-Request": "true",
                "X-LV-DCP-Was-Degraded": "true",
                "X-LV-DCP-Degraded-Since": str(original),
            },
        )

    assert response.status_code == 200
    # The panel wrapper must echo the incoming timestamp verbatim.
    panel_slice = response.text.split('id="wiki-refresh-panel"', 1)[1].split(">", 1)[0]
    assert f'"X-LV-DCP-Degraded-Since": "{original}"' in panel_slice


@pytest.mark.asyncio
async def test_degraded_wrapper_stamps_fresh_since_when_incoming_is_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed / non-positive / future incoming timestamp → stamp a fresh one.

    The parser rejects: empty, non-int ("abc"), non-positive (``0`` /
    negative), and future values. In every case the route falls back
    to ``int(time.time())`` so the recovery toast still has a usable
    (if short) duration to display rather than silently dropping the
    label because of a single bad upstream tick.
    """
    _seed_project(tmp_path, monkeypatch)

    import apps.ui.routes.project as project_route

    def _boom() -> object:
        raise RuntimeError("still broken")

    monkeypatch.setattr(project_route, "build_workspace_status", _boom)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    # Cover the three representative failure modes in one sweep.
    for bad_value in ("not-a-number", "0", str(int(time.time()) + 3600)):
        before = int(time.time())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/project/anything/wiki-refresh",
                headers={
                    "HX-Request": "true",
                    "X-LV-DCP-Was-Degraded": "true",
                    "X-LV-DCP-Degraded-Since": bad_value,
                },
            )
        after = int(time.time())

        assert response.status_code == 200
        panel_slice = response.text.split('id="wiki-refresh-panel"', 1)[1].split(">", 1)[0]
        marker = '"X-LV-DCP-Degraded-Since": "'
        idx = panel_slice.index(marker) + len(marker)
        end = panel_slice.index('"', idx)
        ts = int(panel_slice[idx:end])
        # The stamped timestamp must be fresh (within the request
        # window), NOT the bad incoming value.
        assert before <= ts <= after, (
            f"bad incoming value {bad_value!r} should have been replaced "
            f"with a fresh int(time.time()); got {ts}"
        )


@pytest.mark.asyncio
async def test_retry_button_also_carries_degraded_since(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Retry button's hx-headers JSON includes X-LV-DCP-Degraded-Since.

    Without this the manual-retry recovery path would flash a generic
    "recovered" banner while the poll-initiated recovery path would
    flash "recovered after Xm Ys" — same event, inconsistent UX. The
    button must round-trip the timestamp identically to the polling
    wrapper so both paths converge on the duration-aware copy.
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
    # Both the wrapper and the button declare the header, so the count
    # of occurrences in the rendered output is at least 2.
    assert response.text.count("X-LV-DCP-Degraded-Since") >= 2, (
        "Expected the X-LV-DCP-Degraded-Since header on BOTH the polling "
        "wrapper and the Retry button — one of them is missing."
    )
    # The button line itself must include the key; isolate by id.
    button_marker = 'id="wiki-refresh-retry-'
    assert button_marker in response.text
    btn_slice = response.text.split(button_marker, 1)[1].split("</button>", 1)[0]
    assert "X-LV-DCP-Degraded-Since" in btn_slice
    # Button also keeps the retry-source marker from v0.8.15.
    assert '"X-LV-DCP-Retry-Source": "manual"' in btn_slice


@pytest.mark.asyncio
async def test_recovery_toast_surfaces_outage_duration_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recovery tick with a valid Degraded-Since header → "reachable again after <duration>".

    Simulates a 2m 17s outage by sending ``X-LV-DCP-Degraded-Since``
    set to ``int(time.time()) - 137``. The route formats the diff as
    ``"2m 17s"`` and the template splices it into the toast copy.
    """
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=0, modules_updated=3, elapsed_seconds=1.5)

    since = int(time.time()) - 137

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/project/{_slug(project)}/wiki-refresh",
            headers={
                "HX-Request": "true",
                "X-LV-DCP-Was-Degraded": "true",
                "X-LV-DCP-Degraded-Since": str(since),
            },
        )

    assert response.status_code == 200
    # Recovery toast present.
    assert "Wiki refresh status recovered" in response.text
    # Duration-aware copy. The first second can drift ±1 depending on
    # test-execution timing, so accept 2m 16s, 2m 17s, or 2m 18s.
    assert (
        "reachable again after 2m 16s" in response.text
        or "reachable again after 2m 17s" in response.text
        or "reachable again after 2m 18s" in response.text
    ), "Expected 2m 16s/17s/18s duration label in recovery toast"
    # Pre-v0.8.19 fallback copy must NOT also appear.
    assert "is reachable again. Resuming normal polling." not in response.text


@pytest.mark.asyncio
async def test_recovery_toast_falls_back_to_plain_copy_without_since_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing Degraded-Since header → pre-v0.8.19 copy (backwards compatible).

    A browser tab that opened on a pre-v0.8.19 build and finally polls
    through a recovery has no Degraded-Since to echo. The toast must
    still fire with the original copy so rolling upgrades don't lose
    the recovery signal mid-flight.
    """
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
    assert "Wiki refresh status recovered" in response.text
    # Pre-v0.8.19 copy present.
    assert "is reachable again. Resuming normal polling." in response.text
    # No "after <duration>" copy (the label branch didn't fire).
    assert "reachable again after" not in response.text


@pytest.mark.asyncio
async def test_recovery_toast_falls_back_when_since_header_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed / zero / future Degraded-Since → recovery toast uses fallback copy.

    The parser collapses every failure mode to ``None`` so the toast
    branch cannot explode on garbage input. Locks that graceful
    degradation in.
    """
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=0, modules_updated=3, elapsed_seconds=1.5)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    for bad_value in ("garbled", "0", "-42", str(int(time.time()) + 3600)):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                f"/api/project/{_slug(project)}/wiki-refresh",
                headers={
                    "HX-Request": "true",
                    "X-LV-DCP-Was-Degraded": "true",
                    "X-LV-DCP-Degraded-Since": bad_value,
                },
            )

        assert response.status_code == 200, (
            f"route should stay 200 on bad Degraded-Since={bad_value!r}"
        )
        assert "Wiki refresh status recovered" in response.text
        # Fallback copy — no "after <duration>" should render.
        assert "is reachable again. Resuming normal polling." in response.text, (
            f"expected fallback copy for bad value {bad_value!r}"
        )
        assert "reachable again after" not in response.text, (
            f"bad value {bad_value!r} leaked a duration label"
        )


@pytest.mark.asyncio
async def test_recovery_log_event_includes_outage_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``ui.wiki_refresh.toast.rendered`` carries outage_seconds on recovery.

    Extends the v0.8.15 trigger telemetry with a numeric outage length
    so dashboards can plot mean/p95 outage duration without having to
    re-derive it from tick counts. Missing Degraded-Since → field is
    present as ``None`` (so field shape stays stable for consumers).
    """
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=0, modules_updated=2, elapsed_seconds=1.0)

    since = int(time.time()) - 42

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    with caplog.at_level("INFO", logger="apps.ui.routes.project"):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                f"/api/project/{_slug(project)}/wiki-refresh",
                headers={
                    "HX-Request": "true",
                    "X-LV-DCP-Was-Degraded": "true",
                    "X-LV-DCP-Degraded-Since": str(since),
                },
            )

    assert response.status_code == 200
    assert "Wiki refresh status recovered" in response.text

    rendered = [r for r in caplog.records if r.getMessage() == "ui.wiki_refresh.toast.rendered"]
    assert len(rendered) == 1
    record = rendered[0]
    assert getattr(record, "kind", None) == "recovery"
    # Value within the ±1 s test-execution window of the planned 42s gap.
    outage = getattr(record, "outage_seconds", None)
    assert outage is not None, (
        "outage_seconds must be set on a recovery with a valid Degraded-Since"
    )
    assert 41 <= outage <= 43, f"expected outage_seconds ≈ 42, got {outage}"


@pytest.mark.asyncio
async def test_recovery_log_event_outage_seconds_is_none_when_header_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Recovery without a Degraded-Since header still logs with outage_seconds=None.

    Field stability matters for downstream log consumers — a missing
    key vs a None value parse differently in structured-log sinks.
    Locks in that the route always emits the key, even when it has
    no duration hint to report.
    """
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=0, modules_updated=2, elapsed_seconds=1.0)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    with caplog.at_level("INFO", logger="apps.ui.routes.project"):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                f"/api/project/{_slug(project)}/wiki-refresh",
                headers={
                    "HX-Request": "true",
                    "X-LV-DCP-Was-Degraded": "true",
                },
            )

    assert response.status_code == 200
    rendered = [r for r in caplog.records if r.getMessage() == "ui.wiki_refresh.toast.rendered"]
    assert len(rendered) == 1
    record = rendered[0]
    assert getattr(record, "kind", None) == "recovery"
    # Attribute exists (so the extras dict included the key) and is None.
    assert hasattr(record, "outage_seconds")
    assert getattr(record, "outage_seconds", "MISSING") is None


# -------- v0.8.19: _format_outage_duration unit tests ---------------


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "<1s"),
        (1, "1s"),
        (42, "42s"),
        (59, "59s"),
        (60, "1m"),
        (61, "1m 1s"),
        (137, "2m 17s"),
        (180, "3m"),
        (3599, "59m 59s"),
        (3600, "1h"),
        (3660, "1h 1m"),
        (5025, "1h 23m"),
        (86399, "23h 59m"),
        (86400, "24h"),
    ],
)
def test_format_outage_duration_covers_range(seconds: int, expected: str) -> None:
    """``_format_outage_duration`` matches the v0.8.19 copy spec.

    Boundary values (1/59/60/3599/3600/86400) and representative
    midrange values lock in the format's range semantics so a future
    edit can't silently regress the "reachable again after ..." copy.
    """
    from apps.ui.routes.project import _format_outage_duration

    assert _format_outage_duration(seconds) == expected
