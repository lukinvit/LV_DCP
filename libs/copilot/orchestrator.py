"""Orchestration functions for the Project Copilot Wrapper (spec-011).

Each public function is a thin composition over existing LV_DCP primitives
(:mod:`libs.scanning`, :mod:`libs.context_pack`, :mod:`libs.project_index`,
:mod:`libs.wiki`, :mod:`libs.status`). No new side-effecting store is
introduced — the copilot is strictly a composition layer.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import TYPE_CHECKING

from libs.context_pack.builder import build_edit_pack, build_navigate_pack
from libs.copilot.models import (
    CopilotAskReport,
    CopilotCheckReport,
    CopilotRefreshReport,
    DegradedMode,
)
from libs.copilot.wiki_background import (
    read_status,
    start_background_refresh,
)
from libs.core.projects_config import load_config
from libs.project_index.index import ProjectIndex, ProjectNotIndexedError
from libs.scanning.scanner import scan_project
from libs.status.aggregator import resolve_config_path
from libs.status.health import build_health_card
from libs.storage.sqlite_cache import SqliteCache
from libs.wiki.state import ensure_wiki_table, get_all_modules, get_dirty_modules

if TYPE_CHECKING:
    from libs.core.projects_config import DaemonConfig

log = logging.getLogger(__name__)


# ---- helpers ---------------------------------------------------------------


DEGRADED_MODE_HINTS: dict[DegradedMode, str] = {
    DegradedMode.NOT_SCANNED: "Project is not scanned. Run `ctx project refresh <path>`.",
    DegradedMode.STALE_SCAN: "Index is > 24 h old. Consider `ctx project refresh <path>`.",
    DegradedMode.WIKI_MISSING: (
        "No wiki generated yet. Run `ctx project wiki <path> --refresh` for richer pack enrichment."
    ),
    DegradedMode.WIKI_STALE: ("Wiki has dirty modules. Run `ctx project wiki <path> --refresh`."),
    DegradedMode.QDRANT_OFF: (
        "Vector retrieval off (Qdrant disabled). Results use keyword + graph fallback."
    ),
    DegradedMode.AMBIGUOUS: (
        "Retrieval coverage is ambiguous — rephrase with more specific terms, "
        "expand `--limit`, or use `ctx explain <trace_id>` to debug."
    ),
}


def _wiki_is_present(root: Path) -> bool:
    return (root / ".context" / "wiki" / "INDEX.md").exists()


def _count_dirty_wiki_modules(root: Path) -> int:
    """Return count of ``status='dirty'`` wiki_state rows; 0 if table missing.

    Best-effort: any sqlite error is swallowed and returned as 0 so the
    copilot never fails a ``check`` because the wiki table wasn't created
    yet.
    """
    db_path = root / ".context" / "cache.db"
    if not db_path.exists():
        return 0
    try:
        with SqliteCache(db_path) as cache:
            cache.migrate()
            conn = cache._connect()
            ensure_wiki_table(conn)
            conn.commit()
            return len(get_dirty_modules(conn))
    except Exception:
        log.warning("wiki state read failed for %s", root, exc_info=True)
        return 0


def _load_config_safe(config_path: Path | None) -> DaemonConfig | None:
    """Load ``~/.lvdcp/config.yaml`` without raising on missing files."""
    path = config_path if config_path is not None else resolve_config_path()
    try:
        return load_config(path)
    except Exception:
        log.warning("config load failed at %s", path, exc_info=True)
        return None


def _project_name(root: Path) -> str:
    return root.name


# ---- check -----------------------------------------------------------------


def check_project(
    root: Path,
    *,
    config_path: Path | None = None,
) -> CopilotCheckReport:
    """Return a ``CopilotCheckReport`` for ``root`` without mutating state.

    Composes ``HealthCard`` + wiki state + Qdrant config into a single
    snapshot. Safe to call on an un-scanned project: all downstream
    primitives are wrapped in try/except and degrade to "not scanned".
    """
    root = root.resolve()
    cfg_path = config_path if config_path is not None else resolve_config_path()
    card = build_health_card(root, config_path=cfg_path)
    scanned = card.last_scan_status != "unregistered" and card.files > 0
    # HealthCard doesn't directly track "scanned" (cache.db exists);
    # re-check so an un-registered but scanned dir still reports True.
    if not scanned:
        scanned = (root / ".context" / "cache.db").exists()

    wiki_present = _wiki_is_present(root)
    wiki_dirty = _count_dirty_wiki_modules(root)
    bg_status = read_status(root)
    cfg = _load_config_safe(config_path)
    qdrant_enabled = bool(cfg and cfg.qdrant.enabled)

    degraded: list[DegradedMode] = []
    if not scanned:
        degraded.append(DegradedMode.NOT_SCANNED)
    elif card.stale:
        degraded.append(DegradedMode.STALE_SCAN)
    if not wiki_present:
        degraded.append(DegradedMode.WIKI_MISSING)
    elif wiki_dirty > 0:
        degraded.append(DegradedMode.WIKI_STALE)
    if not qdrant_enabled:
        degraded.append(DegradedMode.QDRANT_OFF)

    last_run = bg_status.last_run
    return CopilotCheckReport(
        project_root=str(root),
        project_name=_project_name(root),
        scanned=scanned,
        stale=card.stale,
        last_scan_at_iso=card.last_scan_at_iso,
        files=card.files,
        symbols=card.symbols,
        relations=card.relations,
        wiki_present=wiki_present,
        wiki_dirty_modules=wiki_dirty,
        wiki_refresh_in_progress=bg_status.in_progress,
        wiki_refresh_phase=bg_status.phase if bg_status.in_progress else None,
        wiki_refresh_modules_total=(bg_status.modules_total if bg_status.in_progress else None),
        wiki_refresh_modules_done=(bg_status.modules_done if bg_status.in_progress else 0),
        wiki_refresh_current_module=(bg_status.current_module if bg_status.in_progress else None),
        wiki_refresh_pid=bg_status.pid if bg_status.in_progress else None,
        wiki_last_refresh_completed_at=(last_run.completed_at if last_run is not None else None),
        wiki_last_refresh_exit_code=(last_run.exit_code if last_run is not None else None),
        wiki_last_refresh_modules_updated=(
            last_run.modules_updated if last_run is not None else None
        ),
        wiki_last_refresh_elapsed_seconds=(
            last_run.elapsed_seconds if last_run is not None else None
        ),
        wiki_last_refresh_log_tail=(
            list(last_run.log_tail)
            if (last_run is not None and last_run.log_tail is not None)
            else None
        ),
        qdrant_enabled=qdrant_enabled,
        degraded_modes=degraded,
    )


# ---- watch -----------------------------------------------------------------


#: Minimum allowed poll interval, seconds. Anything lower and we risk
#: hammering the filesystem for negligible UX gain.
_WATCH_MIN_INTERVAL_S = 0.2

#: Default maximum watch duration, seconds (15 min). A wall-clock safety
#: net so a wedged runner can't keep a `check --watch` process alive forever.
_WATCH_DEFAULT_MAX_DURATION_S = 15 * 60


def watch_check_project(  # noqa: PLR0913 — each kw-only knob is a distinct tuning dial or test seam
    root: Path,
    *,
    interval_seconds: float = 2.0,
    max_duration_seconds: float = _WATCH_DEFAULT_MAX_DURATION_S,
    config_path: Path | None = None,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
) -> Iterator[CopilotCheckReport]:
    """Yield :class:`CopilotCheckReport` snapshots until the refresh settles.

    Semantics:

    - Emit one snapshot immediately.
    - If ``wiki_refresh_in_progress`` is already ``False`` on the first
      snapshot, stop — there is nothing to watch.
    - Otherwise sleep ``interval_seconds`` and emit another snapshot;
      repeat until either the refresh transitions to
      ``in_progress=False`` (final snapshot is yielded too) or the
      wall-clock budget ``max_duration_seconds`` is exhausted.

    ``sleep`` and ``clock`` default to :func:`time.sleep` and
    :func:`time.monotonic` — resolved *at call time* so tests can
    monkeypatch :mod:`time` at the orchestrator module level.
    """
    if interval_seconds < _WATCH_MIN_INTERVAL_S:
        raise ValueError(
            f"interval_seconds must be ≥ {_WATCH_MIN_INTERVAL_S} (got {interval_seconds})"
        )
    sleep_fn = sleep if sleep is not None else time.sleep
    clock_fn = clock if clock is not None else time.monotonic

    started = clock_fn()
    deadline = started + max_duration_seconds

    report = check_project(root, config_path=config_path)
    yield report
    if not report.wiki_refresh_in_progress:
        return

    while clock_fn() < deadline:
        sleep_fn(interval_seconds)
        report = check_project(root, config_path=config_path)
        yield report
        if not report.wiki_refresh_in_progress:
            return


# ---- refresh ---------------------------------------------------------------


def refresh_project(
    root: Path,
    *,
    full: bool = False,
    refresh_wiki_after: bool = True,
    wiki_background: bool = False,
) -> CopilotRefreshReport:
    """Run a scan and, by default, a wiki update. One call, one report.

    - ``full=True`` forces a mode-``full`` scan; default is incremental.
    - ``refresh_wiki_after=False`` skips the wiki update (scan-only).
    - ``wiki_background=True`` spawns the wiki refresh as a detached
      subprocess and returns immediately. Ignored when
      ``refresh_wiki_after=False``.
    """
    root = root.resolve()
    scan_res = scan_project(root, mode="full" if full else "incremental")
    messages: list[str] = [
        f"scan: {scan_res.files_scanned} file(s), "
        f"{scan_res.files_reparsed} reparsed, "
        f"{scan_res.symbols_extracted} symbol(s), "
        f"{scan_res.elapsed_seconds:.2f} s"
    ]

    wiki_updated = 0
    wiki_refreshed = False
    wiki_bg_started = False
    if refresh_wiki_after:
        if wiki_background:
            status = start_background_refresh(root, all_modules=False)
            wiki_bg_started = status.in_progress
            messages.append(
                "wiki: background refresh started "
                f"(pid={status.pid}, log=.context/wiki/.refresh.log)"
                if wiki_bg_started
                else "wiki: background refresh skipped — a refresh is already running"
            )
        else:
            wiki_report = refresh_wiki(root, all_modules=False)
            wiki_updated = wiki_report.wiki_modules_updated
            wiki_refreshed = wiki_report.wiki_refreshed
            messages.extend(wiki_report.messages)

    return CopilotRefreshReport(
        project_root=str(root),
        project_name=_project_name(root),
        scanned=True,
        scan_files=scan_res.files_scanned,
        scan_reparsed=scan_res.files_reparsed,
        scan_elapsed_seconds=scan_res.elapsed_seconds,
        wiki_refreshed=wiki_refreshed,
        wiki_refresh_background_started=wiki_bg_started,
        wiki_modules_updated=wiki_updated,
        messages=messages,
    )


def refresh_wiki(
    root: Path,
    *,
    all_modules: bool = False,
    background: bool = False,
) -> CopilotRefreshReport:
    """Wiki-only refresh. Skips gracefully when the project is not scanned.

    - ``background=False`` (default): run synchronously in-process.
    - ``background=True``: spawn a detached subprocess via
      :func:`libs.copilot.wiki_background.start_background_refresh` and
      return immediately with ``wiki_refresh_background_started=True``.

    This function intentionally does *not* re-implement
    ``ctx wiki update`` — it shells out through
    :func:`_run_wiki_update_in_process` which reuses the same helpers the
    CLI command uses. The only divergence is that failures become
    ``messages`` entries instead of stderr prints, so the copilot can
    batch-report.
    """
    root = root.resolve()
    db_path = root / ".context" / "cache.db"
    if not db_path.exists():
        return CopilotRefreshReport(
            project_root=str(root),
            project_name=_project_name(root),
            scanned=False,
            wiki_refreshed=False,
            wiki_modules_updated=0,
            messages=["wiki: skipped — project is not scanned"],
        )

    if background:
        status = start_background_refresh(root, all_modules=all_modules)
        started = status.in_progress
        msg = (
            f"wiki: background refresh started (pid={status.pid}, log=.context/wiki/.refresh.log)"
            if started
            else "wiki: background refresh skipped — a refresh is already running"
        )
        return CopilotRefreshReport(
            project_root=str(root),
            project_name=_project_name(root),
            scanned=True,
            wiki_refreshed=False,
            wiki_refresh_background_started=started,
            wiki_modules_updated=0,
            messages=[msg],
        )

    updated, messages = _run_wiki_update_in_process(root, all_modules=all_modules)
    return CopilotRefreshReport(
        project_root=str(root),
        project_name=_project_name(root),
        scanned=True,
        wiki_refreshed=True,
        wiki_modules_updated=updated,
        messages=messages,
    )


_WikiProgressCallback = Callable[..., None]


def _run_wiki_update_in_process(  # noqa: PLR0915 — progress emission + per-module loop is one cohesive unit
    root: Path,
    *,
    all_modules: bool,
    on_progress: _WikiProgressCallback | None = None,
) -> tuple[int, list[str]]:
    """Reduced port of ``ctx wiki update`` that returns a count + log lines.

    The real CLI command does LLM generation per module; we reuse the
    same generator helpers but swallow exceptions per-module so a single
    failure does not abort the batch. The return tuple is
    ``(modules_updated, messages)``.

    ``on_progress`` is an optional keyword-only callback invoked at each
    module boundary with ``done=<int>, total=<int>, current=<str|None>``.
    The background runner uses it to stream lock-file progress events;
    the sync path leaves it ``None``.
    """
    from libs.wiki.generator import generate_wiki_article  # noqa: PLC0415
    from libs.wiki.index_builder import write_index  # noqa: PLC0415
    from libs.wiki.state import mark_current  # noqa: PLC0415

    wiki_dir = root / ".context" / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "modules").mkdir(parents=True, exist_ok=True)

    messages: list[str] = []
    updated = 0

    db_path = root / ".context" / "cache.db"
    with SqliteCache(db_path) as cache:
        cache.migrate()
        conn = cache._connect()
        ensure_wiki_table(conn)
        conn.commit()

        modules = get_all_modules(conn) if all_modules else get_dirty_modules(conn)
        if not modules:
            messages.append("wiki: no modules to update")
            if on_progress is not None:
                on_progress(done=0, total=0, current=None)
            return 0, messages

        files = {f.path: f for f in cache.iter_files()}
        symbols = list(cache.iter_symbols())
        relations = list(cache.iter_relations())

        total = len(modules)
        for idx, mod in enumerate(modules):
            module_path = mod["module_path"]
            if on_progress is not None:
                on_progress(done=idx, total=total, current=module_path)
            mod_files = [
                fp for fp in files if fp.startswith(module_path + "/") or fp == module_path
            ]
            mod_symbols = [s.fq_name for s in symbols if s.file_path in mod_files]

            mod_file_set = set(mod_files)
            deps: set[str] = set()
            dependents: set[str] = set()
            for r in relations:
                if r.src_ref in mod_file_set and r.dst_ref not in mod_file_set:
                    parts = r.dst_ref.split("/")
                    deps.add("/".join(parts[:2]) if len(parts) >= 2 else parts[0])
                elif r.dst_ref in mod_file_set and r.src_ref not in mod_file_set:
                    parts = r.src_ref.split("/")
                    dependents.add("/".join(parts[:2]) if len(parts) >= 2 else parts[0])

            safe_name = module_path.replace("/", "-").replace("\\", "-")
            article_file = wiki_dir / "modules" / f"{safe_name}.md"
            existing = article_file.read_text(encoding="utf-8") if article_file.exists() else ""

            try:
                article = generate_wiki_article(
                    project_root=root,
                    project_name=root.name,
                    module_path=module_path,
                    file_list=mod_files,
                    symbols=mod_symbols[:20],
                    deps=sorted(deps),
                    dependents=sorted(dependents),
                    existing_article=existing,
                )
                article_file.write_text(article, encoding="utf-8")
                mark_current(conn, module_path, f"modules/{safe_name}.md", mod["source_hash"])
                conn.commit()
                updated += 1
            except Exception as exc:
                messages.append(f"wiki: {module_path} skipped — {exc}")

        write_index(wiki_dir, root.name)

    if on_progress is not None:
        on_progress(done=len(modules), total=len(modules), current=None)
    messages.append(f"wiki: {updated} module(s) updated")
    return updated, messages


# ---- ask -------------------------------------------------------------------


PackInvoker = Callable[[Path, str, str, int], "_PackOutcome"]


class _PackOutcome:
    """Lightweight struct holding the pack result + coverage + trace id.

    Defined locally so ``ask_project`` doesn't leak a ``PackResult``
    import onto callers; the CLI layer re-wraps into the pydantic DTO.
    """

    __slots__ = ("coverage", "markdown", "retrieved_files", "trace_id")

    def __init__(
        self,
        *,
        markdown: str,
        trace_id: str,
        coverage: str,
        retrieved_files: list[str],
    ) -> None:
        self.markdown = markdown
        self.trace_id = trace_id
        self.coverage = coverage
        self.retrieved_files = retrieved_files


def _default_pack_invoker(root: Path, query: str, mode: str, limit: int) -> _PackOutcome:
    """Default pack path: uses :mod:`libs.project_index` + context-pack builders.

    Stays inside ``libs/`` — no import of ``apps.mcp.tools`` — so the
    ``apps/ ↛ libs/`` direction rule holds. Vector search and rerank are
    deliberately *not* wired here; the copilot leaves those to callers
    who explicitly want the full MCP stack.
    """
    try:
        idx = ProjectIndex.open(root)
    except ProjectNotIndexedError as exc:
        raise ValueError(f"not_indexed: {exc}") from exc

    with idx:
        result = idx.retrieve(query, mode=mode, limit=limit)
        trace_with_project = dataclass_replace(result.trace, project=root.name)
        idx.save_trace(trace_with_project)
        if mode == "edit":
            pack = build_edit_pack(
                project_slug=root.name,
                query=query,
                result=result,
                project_root=root,
            )
        else:
            pack = build_navigate_pack(
                project_slug=root.name,
                query=query,
                result=result,
                project_root=root,
            )
        return _PackOutcome(
            markdown=pack.assembled_markdown,
            trace_id=result.trace.trace_id,
            coverage=result.coverage,
            retrieved_files=list(result.files),
        )


def ask_project(  # noqa: PLR0913 — thin orchestrator, each kwarg is a legit tuning knob
    root: Path,
    query: str,
    *,
    mode: str = "navigate",
    limit: int = 10,
    auto_refresh: bool = False,
    config_path: Path | None = None,
    _pack_invoker: PackInvoker | None = None,
) -> CopilotAskReport:
    """Answer a project-scoped question.

    The flow:

    1. Run ``check_project`` to discover degraded modes.
    2. If the project is not scanned and ``auto_refresh=True``, run a
       scan first.
    3. Delegate to ``_pack_invoker`` (default: the in-process
       ``libs.context_pack`` pipeline, same primitives as ``ctx pack``).
    4. Decorate the result with ``suggestions`` derived from the
       degraded modes observed.
    """
    root = root.resolve()
    invoker = _pack_invoker if _pack_invoker is not None else _default_pack_invoker

    check = check_project(root, config_path=config_path)

    suggestions: list[str] = []
    modes_accumulated: list[DegradedMode] = list(check.degraded_modes)

    # Auto-refresh opt-in: scan now so the pack call has something to bite on.
    if DegradedMode.NOT_SCANNED in modes_accumulated and auto_refresh:
        refresh_project(root, full=False, refresh_wiki_after=False)
        # Re-run check to refresh the state snapshot.
        check = check_project(root, config_path=config_path)
        modes_accumulated = list(check.degraded_modes)

    if DegradedMode.NOT_SCANNED in modes_accumulated:
        # Hard degrade — we cannot answer without a cache.db.
        return CopilotAskReport(
            project_root=str(root),
            project_name=_project_name(root),
            query=query,
            mode=mode,
            markdown="",
            trace_id=None,
            coverage="unavailable",
            retrieved_files=[],
            degraded_modes=modes_accumulated,
            suggestions=[DEGRADED_MODE_HINTS[m] for m in modes_accumulated],
        )

    try:
        outcome = invoker(root, query, mode, limit)
    except ValueError as exc:
        # e.g. ``not_indexed`` bubbling up from a race condition.
        log.warning("pack invoker failed for %s: %s", root, exc)
        return CopilotAskReport(
            project_root=str(root),
            project_name=_project_name(root),
            query=query,
            mode=mode,
            markdown="",
            trace_id=None,
            coverage="unavailable",
            retrieved_files=[],
            degraded_modes=[*modes_accumulated, DegradedMode.NOT_SCANNED],
            suggestions=[DEGRADED_MODE_HINTS[DegradedMode.NOT_SCANNED]],
        )

    if outcome.coverage == "ambiguous" and DegradedMode.AMBIGUOUS not in modes_accumulated:
        modes_accumulated.append(DegradedMode.AMBIGUOUS)

    for mode_ in modes_accumulated:
        hint = DEGRADED_MODE_HINTS.get(mode_)
        if hint and hint not in suggestions:
            suggestions.append(hint)

    return CopilotAskReport(
        project_root=str(root),
        project_name=_project_name(root),
        query=query,
        mode=mode,
        markdown=outcome.markdown,
        trace_id=outcome.trace_id,
        coverage=outcome.coverage,
        retrieved_files=outcome.retrieved_files,
        degraded_modes=modes_accumulated,
        suggestions=suggestions,
    )
