"""`ctx obsidian sync`, `status`, and `sync-all` subcommands."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import typer
from libs.core.projects_config import load_config
from libs.obsidian.models import (
    ObsidianFileInfo,
    ObsidianGitInfo,
    ObsidianModuleData,
    ObsidianRelationInfo,
    ObsidianSymbolInfo,
    VaultConfig,
)
from libs.obsidian.publisher import ObsidianPublisher
from libs.storage.sqlite_cache import SqliteCache

app = typer.Typer(name="obsidian", help="Obsidian vault sync commands")

DEFAULT_CONFIG_PATH = Path.home() / ".lvdcp" / "config.yaml"
_OBSIDIAN_MARKER = "obsidian_last_sync"
_SYNC_ALL_DEFAULT_TIMEOUT_SECONDS = 300


def _build_modules(
    files: list[ObsidianFileInfo],
    symbols: list[ObsidianSymbolInfo],
    relations: list[ObsidianRelationInfo],
) -> dict[str, ObsidianModuleData]:
    """Group files/symbols by top-level module directory."""
    modules: dict[str, ObsidianModuleData] = {}
    file_to_module: dict[str, str] = {}

    # Assign each file to a module (first path component, or "_root")
    for f in files:
        parts = Path(f["path"]).parts
        mod_name = parts[0] if len(parts) > 1 else "_root"
        file_to_module[f["path"]] = mod_name
        if mod_name not in modules:
            modules[mod_name] = {
                "file_count": 0,
                "symbol_count": 0,
                "top_symbols": [],
                "dependencies": [],
                "dependents": [],
            }
        modules[mod_name]["file_count"] += 1

    # Count symbols per module and collect top symbol names
    for s in symbols:
        mod_name = file_to_module.get(s["file_path"], "_root")
        if mod_name in modules:
            modules[mod_name]["symbol_count"] += 1
            if len(modules[mod_name]["top_symbols"]) < 10:
                modules[mod_name]["top_symbols"].append(s["name"])

    # Build dependency graph from relations (imports between modules)
    mod_deps: dict[str, set[str]] = defaultdict(set)
    mod_dependents: dict[str, set[str]] = defaultdict(set)
    for r in relations:
        src_mod = file_to_module.get(r.get("src_ref", ""), "")
        dst_mod = file_to_module.get(r.get("dst_ref", ""), "")
        if src_mod and dst_mod and src_mod != dst_mod:
            mod_deps[src_mod].add(dst_mod)
            mod_dependents[dst_mod].add(src_mod)

    for mod_name, mod_data in modules.items():
        mod_data["dependencies"] = sorted(mod_deps.get(mod_name, set()))
        mod_data["dependents"] = sorted(mod_dependents.get(mod_name, set()))

    return modules


def _sync_report_to_json(
    report: object,
    *,
    vault: Path,
    project: Path,
) -> dict[str, object]:
    """Mirror the ``SyncReport`` dataclass schema 1:1 plus the invocation
    parameters that round-trip what this run actually synced.

    Schema (matches ``libs.obsidian.models.SyncReport``):
      - ``vault``: absolute path of the Obsidian vault root that was
        targeted (round-tripped so a script can confirm the run actually
        targeted the vault it intended without reconstructing it from
        ``--vault``)
      - ``project``: absolute path of the project root that was synced
        (round-tripped for the same reason)
      - ``project_name``: the basename used as the vault subdirectory —
        same string that the text view echoes in "Synced X to Y"
      - ``pages_written``: count of vault pages newly written or
        rewritten (the canonical "did this sync actually do work"
        signal — `jq -e '.pages_written > 0'` is the natural CI guard)
      - ``pages_deleted``: count of vault pages removed because the
        source files no longer exist (separate from ``pages_written``
        so dashboards can split "drift cleanup" from "fresh write" load)
      - ``duration_seconds``: float seconds the publisher ran for —
        useful for the "did this sync slow down" hygiene track via
        ``jq '.duration_seconds'``
      - ``errors``: array of human-readable error messages collected
        during sync. Empty array (never ``null``) for a clean sync —
        ``jq -e '.errors == []'`` works as the CI gate without a
        None-guard. ``len(errors) > 0`` does **not** flip the exit
        code: the publisher swallows per-page errors into the report
        rather than crashing, and the JSON contract preserves that
        semantic so consumers see the partial-success case as
        ``exit 0`` + non-empty errors array (mirroring ``v0.8.50``
        ``obsidian status`` "missing Projects/ is exit 0 + structured
        signal" discipline).

    The ``SyncReport`` dataclass is consumed via ``getattr`` rather
    than imported so this helper survives a future ``SyncReport`` move
    or rename without import-graph churn — the helper's sole input
    contract is "object with the documented fields", same shape
    discipline as v0.8.45 ``ReconcileReport`` shaping.
    """
    return {
        "vault": str(vault),
        "project": str(project),
        "project_name": getattr(report, "project_name", ""),
        "pages_written": getattr(report, "pages_written", 0),
        "pages_deleted": getattr(report, "pages_deleted", 0),
        "duration_seconds": getattr(report, "duration_seconds", 0.0),
        "errors": list(getattr(report, "errors", []) or []),
    }


@app.command("sync")
def sync(
    vault: Path = typer.Option(  # noqa: B008
        ...,
        "--vault",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Path to Obsidian vault root.",
    ),
    project_path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Path to the scanned project.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "Emit a single JSON object mirroring the SyncReport dataclass: "
            "{vault, project, project_name, pages_written, pages_deleted, "
            "duration_seconds, errors} instead of the human-readable summary. "
            "Suppresses all hint text — pure data on stdout. Per-page errors "
            "still land in the `errors` array (exit 0 — partial success is "
            "the publisher's documented semantic); `cache.db` missing still "
            "exits 1 to stderr."
        ),
    ),
) -> None:
    """Sync a scanned project to an Obsidian vault."""
    db_path = project_path / ".context" / "cache.db"
    if not db_path.exists():
        typer.echo(f"error: no cache.db found at {db_path}. Run `ctx scan` first.", err=True)
        raise typer.Exit(code=1)

    project_name = project_path.name

    with SqliteCache(db_path) as cache:
        cache.migrate()

        # Read files
        files: list[ObsidianFileInfo] = [
            {"path": f.path, "language": f.language} for f in cache.iter_files()
        ]

        # Read symbols
        symbols: list[ObsidianSymbolInfo] = [
            {
                "name": s.name,
                "fq_name": s.fq_name,
                "file_path": s.file_path,
                "symbol_type": s.symbol_type.value,
            }
            for s in cache.iter_symbols()
        ]

        # Read relations
        relations: list[ObsidianRelationInfo] = [
            {"src_ref": r.src_ref, "dst_ref": r.dst_ref, "relation_type": r.relation_type.value}
            for r in cache.iter_relations()
        ]

        # Git stats for hotspots / recent changes
        hotspots: list[ObsidianGitInfo] = []
        recent_changes: list[ObsidianGitInfo] = []
        for gs in cache.iter_git_stats():
            entry: ObsidianGitInfo = {
                "file_path": gs.file_path,
                "churn_30d": gs.churn_30d,
                "commit_count": gs.commit_count,
                "last_author": gs.last_author,
            }
            if gs.churn_30d > 0:
                recent_changes.append(entry)
            if gs.churn_30d > 5 or gs.commit_count > 20:
                hotspots.append(entry)

    # Sort hotspots by churn desc
    hotspots.sort(key=lambda h: h.get("churn_30d", 0), reverse=True)
    recent_changes.sort(key=lambda c: c.get("churn_30d", 0), reverse=True)

    # Detect languages
    languages = sorted({f["language"] for f in files if f["language"] != "unknown"})

    # Build modules
    modules = _build_modules(files, symbols, relations)

    config = VaultConfig(vault_path=vault)
    publisher = ObsidianPublisher(config)
    report = publisher.sync_project(
        project_name=project_name,
        files=files,
        symbols=symbols,
        modules=modules,
        hotspots=hotspots,
        recent_changes=recent_changes,
        languages=languages,
    )

    if as_json:
        # JSON path: pure data on stdout, no hint text. Per-page errors land
        # in the `errors` array (exit 0 — partial success is the publisher's
        # documented semantic; see _sync_report_to_json docstring).
        typer.echo(
            json.dumps(
                _sync_report_to_json(report, vault=vault, project=project_path),
                indent=2,
            )
        )
        return

    typer.echo(f"Synced {project_name} to {vault}")
    typer.echo(f"  Pages written: {report.pages_written}")
    typer.echo(f"  Duration: {report.duration_seconds:.2f}s")
    if report.errors:
        typer.echo(f"  Errors ({len(report.errors)}):")
        for err in report.errors:
            typer.echo(f"    - {err}")


def _read_last_sync(project_root: Path) -> float | None:
    """Return the last-sync epoch from `.context/obsidian_last_sync`, or None.

    None means "never synced" or "marker corrupt" — both surface as stale.
    """
    marker = project_root / ".context" / _OBSIDIAN_MARKER
    if not marker.exists():
        return None
    try:
        return float(marker.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def _is_stale(project_root: Path, stale_seconds: float, now: float) -> bool:
    """True if this project should be synced now under the stale-hours gate.

    A missing or unreadable marker counts as stale — a project registered
    but never synced is the most common "please sync this" case.
    ``stale_seconds <= 0`` forces-stale regardless of marker age, so
    ``--stale-hours 0`` acts as a "sync everything" override without
    needing a separate flag.
    """
    if stale_seconds <= 0:
        return True
    last = _read_last_sync(project_root)
    if last is None:
        return True
    return (now - last) >= stale_seconds


def _plan_reason(root: Path, stale_seconds: float, now: float) -> str:
    """Classify one project into ``"sync"`` / ``"skip: ..."``.

    Extracted so ``sync_all`` stays under the ruff PLR0912/PLR0915 budgets.
    """
    if not root.exists() or not (root / ".context" / "cache.db").exists():
        return "skip: no cache.db"
    if _is_stale(root, stale_seconds, now):
        return "sync"
    last = _read_last_sync(root)
    age_hours = (now - last) / 3600.0 if last is not None else float("inf")
    return f"skip: fresh ({age_hours:.1f}h old)"


def _invoke_sync(root: Path, vault_path: str, timeout_seconds: int) -> str | None:
    """Shell to ``ctx obsidian sync`` for one project; return error detail or None."""
    try:
        subprocess.run(  # noqa: S603  # controlled invocation of our own CLI
            [
                sys.executable,
                "-m",
                "apps.cli.main",
                "obsidian",
                "sync",
                str(root),
                "--vault",
                vault_path,
            ],
            check=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        stderr = getattr(exc, "stderr", b"") or b""
        detail = stderr.decode("utf-8", errors="replace").strip().splitlines()[-1:] or ["?"]
        return detail[0]
    return None


def _run_plan(
    plan: list[tuple[Path, str]],
    vault_path: str,
    timeout_seconds: int,
    *,
    quiet: bool = False,
) -> tuple[int, int, list[Path], list[dict[str, object]]]:
    """Execute the plan; return ``(synced, skipped, failed, results)``.

    ``results`` is the per-project outcome list that backs the v0.8.61
    ``--json`` payload — one entry per planned project with the keys
    ``{project_root, outcome, reason, error}``. ``outcome`` is exactly
    one of ``"synced"`` / ``"skipped"`` / ``"failed"``; ``reason`` is
    populated only on the ``skipped`` outcome (mirroring the text view's
    ``[skip] <root>: <reason>`` line); ``error`` is populated only on
    the ``failed`` outcome (mirroring ``[fail] <root>: <err>``). Both
    are explicit ``None`` rather than missing keys so consumers can
    ``jq -r '.results[] | select(.outcome == "failed") | .error'``
    without a defined-key guard.

    ``quiet=True`` suppresses the ``[sync] / [skip] / [fail]`` prose so
    the JSON path keeps stdout pure data; the structured ``results``
    list carries the same information without the human chrome.
    """
    synced = 0
    skipped = 0
    failed: list[Path] = []
    results: list[dict[str, object]] = []
    for root, reason in plan:
        if reason != "sync":
            skip_reason = reason.removeprefix("skip: ")
            if not quiet:
                typer.echo(f"[skip] {root}: {skip_reason}")
            skipped += 1
            results.append(
                {
                    "project_root": str(root),
                    "outcome": "skipped",
                    "reason": skip_reason,
                    "error": None,
                }
            )
            continue
        if not quiet:
            typer.echo(f"[sync] {root} …")
        err = _invoke_sync(root, vault_path, timeout_seconds)
        if err is not None:
            if not quiet:
                typer.echo(f"[fail] {root}: {err}", err=True)
            failed.append(root)
            results.append(
                {
                    "project_root": str(root),
                    "outcome": "failed",
                    "reason": None,
                    "error": err,
                }
            )
            continue
        # Advance the shared debounce marker so the daemon's auto-sync
        # respects this successful nightly run and doesn't re-fire on the
        # next scan event within the debounce window.
        marker = root / ".context" / _OBSIDIAN_MARKER
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(time.time()), encoding="utf-8")
        synced += 1
        results.append(
            {
                "project_root": str(root),
                "outcome": "synced",
                "reason": None,
                "error": None,
            }
        )
    return synced, skipped, failed, results


@app.command("sync-all")
def sync_all(  # noqa: PLR0912
    stale_hours: float = typer.Option(
        24.0,
        "--stale-hours",
        help=(
            "Sync only projects whose last Obsidian sync is older than N hours "
            "(or never synced). Pass 0 to force-sync every registered project."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print the sync plan without invoking `ctx obsidian sync`.",
    ),
    config_path: Path = typer.Option(  # noqa: B008
        DEFAULT_CONFIG_PATH,
        "--config",
        help="Path to daemon config YAML (defaults to ~/.lvdcp/config.yaml).",
    ),
    timeout_seconds: int = typer.Option(
        _SYNC_ALL_DEFAULT_TIMEOUT_SECONDS,
        "--timeout",
        min=1,
        help="Per-project sync timeout in seconds.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "Emit a single JSON object summarising the run instead of the "
            "human-readable lines. Schema: `{vault, stale_hours, dry_run, "
            "synced, skipped, failed, results}` — counters round-trip the "
            "summary line and `results` is a per-project array with "
            "`{project_root, outcome, reason, error}` entries (`outcome` is "
            "exactly `synced` / `skipped` / `failed`; `reason` populated "
            "only on `skipped`; `error` populated only on `failed`; both "
            "explicit `null` elsewhere so `jq -r` filters need no defined-"
            "key guard). Suppresses the `[sync] / [skip] / [fail]` per-"
            "project prose so stdout stays pure data — `structlog` is "
            "already routed to `sys.stderr` since v0.8.42. Same exit "
            "discipline as the text path: `obsidian.enabled=false` exits "
            "0 with `{disabled: true, results: []}`-shape, missing config "
            "/ empty vault path exits 1 to stderr (no JSON success-shape "
            "payload — same v0.8.42-v0.8.60 error-vs-success boundary)."
        ),
    ),
) -> None:
    """Iterate all registered projects and sync stale ones to the Obsidian vault.

    Designed for nightly scheduling via user-level ``cron`` / ``launchd`` —
    LV_DCP does not install scheduler entries itself. Idempotent: safe to
    run every 5 minutes or every week; the ``--stale-hours`` gate plus the
    per-project ``obsidian_last_sync`` marker ensure each project only syncs
    once per window regardless of invocation frequency.

    Exits 0 when every candidate project synced cleanly (or was skipped as
    fresh). Exits 1 if any invoked sync failed — the rest still run, so a
    single flaky project doesn't block the others.
    """
    if not config_path.exists():
        typer.echo(f"error: config not found at {config_path}", err=True)
        raise typer.Exit(code=1)

    daemon_cfg = load_config(config_path)
    obsidian_cfg = daemon_cfg.obsidian

    if not obsidian_cfg.enabled:
        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "vault": "",
                        "stale_hours": stale_hours,
                        "dry_run": dry_run,
                        "synced": 0,
                        "skipped": 0,
                        "failed": 0,
                        "results": [],
                    },
                    indent=2,
                )
            )
            return
        typer.echo("Obsidian sync is disabled (obsidian.enabled=false). Nothing to do.")
        raise typer.Exit(code=0)
    if not obsidian_cfg.vault_path:
        typer.echo("error: obsidian.vault_path is empty in config.", err=True)
        raise typer.Exit(code=1)

    projects = daemon_cfg.projects
    if not projects:
        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "vault": obsidian_cfg.vault_path,
                        "stale_hours": stale_hours,
                        "dry_run": dry_run,
                        "synced": 0,
                        "skipped": 0,
                        "failed": 0,
                        "results": [],
                    },
                    indent=2,
                )
            )
            return
        typer.echo("No registered projects. Run `ctx scan <path>` first.")
        raise typer.Exit(code=0)

    stale_seconds = stale_hours * 3600.0
    now = time.time()
    plan: list[tuple[Path, str]] = [
        (entry.root, _plan_reason(entry.root, stale_seconds, now)) for entry in projects
    ]

    if dry_run:
        if as_json:
            # Render plan into the same `results` shape the run-mode would
            # produce — every entry's `outcome` mirrors the planned action
            # ("synced" → would-sync, "skipped" → would-skip-with-reason).
            # Counters reflect the *plan*, not actual side effects (none
            # happened — that's what dry_run means). Locked by the
            # dry-run JSON test.
            results: list[dict[str, object]] = []
            synced = 0
            skipped = 0
            for root, reason in plan:
                if reason == "sync":
                    synced += 1
                    results.append(
                        {
                            "project_root": str(root),
                            "outcome": "synced",
                            "reason": None,
                            "error": None,
                        }
                    )
                else:
                    skipped += 1
                    results.append(
                        {
                            "project_root": str(root),
                            "outcome": "skipped",
                            "reason": reason.removeprefix("skip: "),
                            "error": None,
                        }
                    )
            typer.echo(
                json.dumps(
                    {
                        "vault": obsidian_cfg.vault_path,
                        "stale_hours": stale_hours,
                        "dry_run": True,
                        "synced": synced,
                        "skipped": skipped,
                        "failed": 0,
                        "results": results,
                    },
                    indent=2,
                )
            )
            return
        typer.echo(f"Sync plan (dry-run, stale-hours={stale_hours}):")
        for root, reason in plan:
            typer.echo(f"  {reason:<30} {root}")
        raise typer.Exit(code=0)

    synced, skipped, failed, results = _run_plan(
        plan, obsidian_cfg.vault_path, timeout_seconds, quiet=as_json
    )

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "vault": obsidian_cfg.vault_path,
                    "stale_hours": stale_hours,
                    "dry_run": False,
                    "synced": synced,
                    "skipped": skipped,
                    "failed": len(failed),
                    "results": results,
                },
                indent=2,
            )
        )
        if failed:
            raise typer.Exit(code=1)
        return

    typer.echo("")
    typer.echo(f"Done. Synced: {synced}, skipped: {skipped}, failed: {len(failed)}")
    if failed:
        raise typer.Exit(code=1)


def _vault_status_to_json(
    *,
    vault: Path,
    projects_dir: Path,
    projects_dir_exists: bool,
    projects: list[str],
) -> dict[str, object]:
    """Single-object payload describing the vault's `Projects/` state.

    Why a single object (not a bare array of project names): the command has
    a tri-state contract — Projects/ missing vs. present-but-empty vs.
    populated — that a bare array cannot encode without a sentinel value.
    The object cleanly distinguishes them via ``projects_dir_exists``.
    """
    return {
        "vault": str(vault),
        "projects_dir": str(projects_dir),
        "projects_dir_exists": projects_dir_exists,
        "projects": projects,
    }


@app.command("status")
def status(
    vault: Path = typer.Option(  # noqa: B008
        ...,
        "--vault",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Path to Obsidian vault root.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "Emit a single JSON object describing the vault state instead "
            "of the human-readable listing. Tri-state contract: "
            "`projects_dir_exists` distinguishes missing vs. empty vs. "
            "populated; `projects` is always an array of sorted dir names."
        ),
    ),
) -> None:
    """List project directories in the Obsidian vault.

    With ``--json``, emits a single object with the tri-state vault-state
    contract intact. Empty / missing vault paths still exit 0 — a missing
    ``Projects/`` directory is a valid vault configuration (no projects
    have been synced yet), not an error.
    """
    projects_dir = vault / "Projects"
    projects_dir_exists = projects_dir.exists()
    dirs: list[str] = (
        sorted(p.name for p in projects_dir.iterdir() if p.is_dir()) if projects_dir_exists else []
    )

    if as_json:
        typer.echo(
            json.dumps(
                _vault_status_to_json(
                    vault=vault,
                    projects_dir=projects_dir,
                    projects_dir_exists=projects_dir_exists,
                    projects=dirs,
                ),
                indent=2,
            )
        )
        return

    if not projects_dir_exists:
        typer.echo("No Projects/ directory found in vault.")
        raise typer.Exit(code=0)

    if not dirs:
        typer.echo("No project directories found.")
    else:
        typer.echo(f"Projects in vault ({len(dirs)}):")
        for d in dirs:
            typer.echo(f"  - {d}")
