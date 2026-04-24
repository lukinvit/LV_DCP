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

#: Request header the v0.8.10 degraded wrapper echoes on its next
#: HTMX poll. When a subsequent fetch reaches this route *without* an
#: internal exception, the presence of this header tells us we just
#: transitioned degraded → normal, so the response emits a green
#: recovery toast alongside the fresh panel. The degraded wrapper
#: sets it via ``hx-headers='{"X-LV-DCP-Was-Degraded": "true"}'`` —
#: pure HTMX, no cookies, no server-side session state.
_WAS_DEGRADED_HEADER = "X-LV-DCP-Was-Degraded"

#: Request header the v0.8.14 "Retry now" button adds to its fetch
#: (alongside :data:`_WAS_DEGRADED_HEADER`). Lets the route distinguish
#: recovery triggered by a 30 s polling tick (header absent → trigger
#: "poll") from recovery triggered by a user click (header == "manual"
#: → trigger "manual") when emitting telemetry. Auto-poll wrappers do
#: NOT send this header, so the absence alone classifies the trigger.
_RETRY_SOURCE_HEADER = "X-LV-DCP-Retry-Source"

#: Request header the v0.8.19 degraded wrapper stamps on its first
#: degraded render and echoes back on every subsequent degraded poll
#: via HTMX ``hx-headers``. Carries an integer Unix timestamp (seconds
#: since epoch) marking when the current outage started. On the
#: recovery tick (degraded → normal) the route reads it back and
#: surfaces the duration on the green recovery toast ("reachable again
#: after 2m 17s"). Pure-HTMX round-trip: no cookie, no session, no
#: server-side memory — identical discipline to the v0.8.11
#: ``X-LV-DCP-Was-Degraded`` marker. A malformed / missing / future
#: value is tolerated — it yields no label, the recovery toast just
#: falls back to the pre-v0.8.19 copy.
_DEGRADED_SINCE_HEADER = "X-LV-DCP-Degraded-Since"


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


def _should_flash_recovery_toast(request: Request) -> bool:
    """Decide whether the fragment response carries a one-shot recovery toast.

    Fires on the exact polling tick that flips ``degraded → normal`` —
    i.e. the first successful status assembly after one or more
    consecutive degraded responses. Two conditions must hold:

    1. ``HX-Request: true`` header is present — rules out full page
       loads and manual ``curl`` hits. A user navigating to
       ``/project/<slug>`` after a long-past recovery never sees the
       flash.
    2. The request carries the :data:`_WAS_DEGRADED_HEADER` marker —
       set by HTMX on polls fired from a degraded wrapper (via the
       ``hx-headers`` attribute added in the partial). Absent on any
       poll fired from a normal / running / idle wrapper, so the
       toast fires exactly once per recovery event.

    The marker is a pure-HTMX round trip: no cookie, no session, no
    memory. That makes worker restarts, multiple browser tabs, and
    curl-based testing trivially correct — each element tracks its
    own degraded/normal state via the HTML attribute HTMX rewrites on
    every swap.
    """
    if request.headers.get("HX-Request", "").lower() != "true":
        return False
    return request.headers.get(_WAS_DEGRADED_HEADER, "").lower() == "true"


def _parse_degraded_since(request: Request) -> int | None:
    """Parse :data:`_DEGRADED_SINCE_HEADER` into a Unix timestamp (int seconds).

    Returns ``None`` on any of:

    - Header absent or empty after strip.
    - Non-integer value (e.g. a float, a base-16 string, or garbled bytes).
    - Non-positive value (``0`` or negative → sentinel / garbage).
    - Future value beyond ``int(time.time())`` (clock skew between browser
      and server, or a malicious client trying to inflate outage labels).

    All failure modes collapse to ``None`` so the caller can safely
    branch on truthiness without worrying about exceptions. Defensive:
    the header is client-controlled via HTMX round-trip, so we never
    trust its contents structurally — only as an opaque integer hint
    that the caller can choose to use or ignore.
    """
    raw = request.headers.get(_DEGRADED_SINCE_HEADER, "").strip()
    if not raw:
        return None
    try:
        ts = int(raw)
    except ValueError:
        return None
    if ts <= 0:
        return None
    now = int(time.time())
    if ts > now:
        return None
    return ts


def _format_outage_duration(seconds: int) -> str:
    """Format an outage length in seconds as a short human label.

    Ranges:

    - ``< 1`` seconds → ``"<1s"`` (clock skew can produce this legitimately
      on a very fast recovery).
    - ``1-59`` → ``"Ns"`` (e.g. ``"47s"``).
    - ``60-3599`` → ``"Xm"`` or ``"Xm Ys"``; the ``"Ys"`` suffix is
      omitted when the remainder is 0 so ``180 → "3m"`` not ``"3m 0s"``.
    - ``>= 3600`` → ``"Xh"`` or ``"Xh Ym"``; same omission logic for
      zero-minute values.

    Deliberately simple / no locale handling — this label rides on a
    toast banner that already carries English copy ("reachable again
    after ..."), so we match the surrounding tone. Seconds precision on
    longer outages would just add noise ("1h 23m 47s" is harder to
    scan than "1h 23m") so only the two largest non-zero units are
    surfaced.
    """
    if seconds < 1:
        return "<1s"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        minutes, secs = divmod(seconds, 60)
        if secs == 0:
            return f"{minutes}m"
        return f"{minutes}m {secs}s"
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    if minutes == 0:
        return f"{hours}h"
    return f"{hours}h {minutes}m"


def _classify_recovery_trigger(request: Request) -> str:
    """Classify a recovery-toast fetch as ``"manual"`` or ``"poll"``.

    The v0.8.14 "Retry now" button carries
    ``hx-headers='{"X-LV-DCP-Retry-Source": "manual"}'`` on its request;
    the auto-poll wrapper carries no such header. So the presence of
    ``manual`` in :data:`_RETRY_SOURCE_HEADER` classifies the trigger as
    a user click; its absence (or any other value) defaults to ``poll``.

    Used for telemetry only — both paths render the identical green
    toast and take the identical code branch; we only want to distinguish
    them in logs to answer questions like "do users actually click
    Retry or does auto-poll dominate?". Defaulting to ``poll`` on
    unknown values is conservative: a garbled header shouldn't inflate
    the manual-click count.
    """
    value = request.headers.get(_RETRY_SOURCE_HEADER, "").lower()
    if value == "manual":
        return "manual"
    return "poll"


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

    **Recovery toast (v0.8.11+):** the degraded wrapper carries
    ``hx-headers='{"X-LV-DCP-Was-Degraded": "true"}'`` so its next
    HTMX poll echoes the marker back. When we see the marker on a
    now-successful assembly it means we just self-healed — the
    response adds a green OOB toast alongside the fresh panel so
    scrolled-away users notice the recovery. The new successful
    wrapper does NOT re-emit the marker, so subsequent polls don't
    replay the toast. See :func:`_should_flash_recovery_toast`.
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
        # v0.8.19+: stamp (or preserve) the outage-start timestamp on
        # the degraded response so the next recovery tick can surface
        # an outage duration. The degraded wrapper and the Retry button
        # both echo ``X-LV-DCP-Degraded-Since`` back via ``hx-headers``,
        # so a long multi-tick outage keeps the same start time across
        # every re-render. A first-time degradation has no incoming
        # header → stamp ``int(time.time())``. A corrupted / future
        # value is ignored (``_parse_degraded_since`` returns None) →
        # stamp fresh. Future-dated timestamps are rejected in the
        # parser, but a very-old real timestamp is technically accepted
        # — outage length is a telemetry hint, not a security boundary,
        # so a malicious client at worst inflates its own label.
        degraded_since = _parse_degraded_since(request) or int(time.time())
        return templates.TemplateResponse(  # type: ignore[no-any-return]
            request=request,
            name="partials/wiki_refresh.html.j2",
            context={
                "wr": None,
                "slug": slug,
                "show_crash_toast": False,
                "degraded": True,
                "degraded_since": degraded_since,
            },
        )
    show_crash_toast = _should_flash_crash_toast(wr, request)
    show_recovery_toast = _should_flash_recovery_toast(request)

    # v0.8.15+: structured-log telemetry for the one-shot toast render
    # paths. Answers two questions that have been invisible since the
    # toasts shipped: (1) how often does a given project actually
    # surface each kind of toast, and (2) for recovery toasts, are
    # users clicking the v0.8.14 "Retry now" button or is the 30 s
    # auto-poll dominating? Both questions matter for tuning — e.g. a
    # slug that flaps crash-toasts every few hours deserves a look at
    # the refresh binary, and a "manual" share near zero would mean
    # the Retry button is invisible to users.
    #
    # We emit stdlib ``log.info`` events with keyword fields via
    # ``extra=``; they ride through the same handler chain as every
    # other route log, so a future structlog / OTel adapter picks them
    # up without further plumbing. The event name is namespaced
    # (``ui.wiki_refresh.toast.rendered``) so log aggregators can
    # filter on it cheaply. Dismiss-side telemetry is deliberately
    # out of scope for this release — the Dismiss button is a pure
    # ``onclick="this.parentElement.remove()"`` DOM op and wiring up a
    # JS beacon for it would cost more than the signal is worth at
    # current scale.
    if show_crash_toast:
        log.info(
            "ui.wiki_refresh.toast.rendered",
            extra={
                "event": "ui.wiki_refresh.toast.rendered",
                "slug": slug,
                "kind": "crash",
            },
        )
    # v0.8.19+: on the recovery tick, translate the incoming
    # ``X-LV-DCP-Degraded-Since`` timestamp into a human-readable outage
    # duration ("reachable again after 2m 17s"). The header is a pure-
    # HTMX round-trip stamped on the degraded wrapper, so the moment
    # the user's browser echoes it back on the first successful poll
    # we can compute ``now - since`` without any server-side state.
    # A missing / malformed / future header → ``outage_seconds = None``,
    # and the toast falls back to the pre-v0.8.19 copy — backwards-
    # compatible with any browser tab that opened on a pre-v0.8.19
    # build and hasn't reloaded yet.
    outage_seconds: int | None = None
    outage_duration_label: str | None = None
    if show_recovery_toast:
        since = _parse_degraded_since(request)
        if since is not None:
            outage_seconds = max(0, int(time.time()) - since)
            outage_duration_label = _format_outage_duration(outage_seconds)
        log.info(
            "ui.wiki_refresh.toast.rendered",
            extra={
                "event": "ui.wiki_refresh.toast.rendered",
                "slug": slug,
                "kind": "recovery",
                "trigger": _classify_recovery_trigger(request),
                "outage_seconds": outage_seconds,
            },
        )

    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request=request,
        name="partials/wiki_refresh.html.j2",
        context={
            "wr": wr,
            "slug": slug,
            "show_crash_toast": show_crash_toast,
            "show_recovery_toast": show_recovery_toast,
            "outage_duration_label": outage_duration_label,
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
