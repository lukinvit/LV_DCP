"""`ctx watch add/remove/list/start` subcommands."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import typer
from libs.mcp_ops.launchd import (
    LAUNCH_AGENT_LABEL,
    LaunchctlError,
    bootout_agent,
    bootstrap_agent,
    write_plist,
)

from apps.agent.config import add_project, list_projects, remove_project
from apps.agent.daemon import DEFAULT_CONFIG_PATH, run_daemon

LAUNCH_AGENT_DIR = Path.home() / "Library" / "LaunchAgents"
AGENT_LOG_DIR = Path.home() / "Library" / "Logs" / "lvdcp-agent"

app = typer.Typer(name="watch", help="Auto-indexing daemon management")


@app.command("add")
def add(
    path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "Emit the registered ProjectEntry as a single JSON object "
            "(same schema as `watch list --json` rows: root, "
            "registered_at_iso, last_scan_at_iso, last_scan_status). "
            "Pure data on stdout — suppresses the human 'added X' line. "
            "Idempotent: re-adding an existing path emits the **already-"
            "registered** entry (the consumer can compare "
            "`registered_at_iso` against wall-clock to detect "
            "duplicate-add)."
        ),
    ),
) -> None:
    """Register a project to be watched by the daemon.

    ``ctx watch add`` is an explicit user intent, so we pass
    ``allow_transient=True`` — the user may legitimately want the daemon to
    follow a ship-ceremony worktree or the ``sample_repo`` fixture. Only
    implicit auto-registration (``ctx scan`` on an unregistered path) filters
    transient roots; explicit invocation wins.
    """
    add_project(DEFAULT_CONFIG_PATH, path, allow_transient=True)
    if as_json:
        # Read back the registered entry — same v0.8.49 schema. Two cases land
        # here: (1) fresh registration → returns the just-written row, (2)
        # idempotent re-add → returns the existing row. Both shapes are
        # identical; consumers diff `registered_at_iso` vs. wall-clock to
        # tell them apart. If the lookup misses (impossible in normal flow
        # — `add_project` either appends or no-ops on a duplicate; the only
        # way to miss is a concurrent `remove_project` between write and
        # read, vanishingly rare and benign), exit 1 with a stderr message
        # so the JSON contract never emits a malformed payload.
        resolved = path.resolve()
        registered = next(
            (p for p in list_projects(DEFAULT_CONFIG_PATH) if p.root == resolved), None
        )
        if registered is None:
            typer.echo(
                f"error: registered {resolved} but cannot read it back from {DEFAULT_CONFIG_PATH}",
                err=True,
            )
            raise typer.Exit(code=1)
        typer.echo(json.dumps(_project_to_json(registered), indent=2))
        return
    typer.echo(f"added {path}")


@app.command("remove")
def remove(
    path: Path = typer.Argument(  # noqa: B008
        ...,
        resolve_path=True,
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "Emit the removed ProjectEntry as a single JSON object "
            "wrapped in `{removed: <entry|null>}` instead of the human "
            "'removed X' line. Pure data on stdout. The wrapper enables "
            "`jq -e '.removed != null'` as the natural 'did this remove "
            "do work' guard — `null` means the path was not registered "
            "(no-op success, same v0.8.45/v0.8.49/v0.8.55 'no work done "
            "is still a successful run' discipline). Inner entry mirrors "
            "the v0.8.49 `watch list --json` row schema 1:1 (root, "
            "registered_at_iso, last_scan_at_iso, last_scan_status)."
        ),
    ),
) -> None:
    """Unregister a project.

    With ``--json``, the entry is captured **before** removal so the consumer
    sees what was just deleted (a script's "what did I just lose" log line).
    Capture-then-mutate ordering matters: ``remove_project`` rewrites the
    config file, after which the entry is gone — read-after-write would
    always emit ``null`` and lose the audit signal.
    """
    if as_json:
        resolved = path.resolve()
        existing = next((p for p in list_projects(DEFAULT_CONFIG_PATH) if p.root == resolved), None)
        remove_project(DEFAULT_CONFIG_PATH, path)
        payload: dict[str, object] = {
            "removed": _project_to_json(existing) if existing is not None else None,
        }
        typer.echo(json.dumps(payload, indent=2))
        return
    remove_project(DEFAULT_CONFIG_PATH, path)
    typer.echo(f"removed {path}")


def _project_to_json(project: Any) -> dict[str, object]:
    """Mirror ``ProjectEntry`` 1:1 as a JSON-serializable dict.

    Schema is intentionally locked to the dataclass shape so consumers can
    bind to it without a separate IDL. ``root`` is stringified because
    ``Path`` is not JSON-native; ISO timestamps stay as strings.
    """
    return {
        "root": str(project.root),
        "registered_at_iso": project.registered_at_iso,
        "last_scan_at_iso": project.last_scan_at_iso,
        "last_scan_status": project.last_scan_status,
    }


@app.command("list")
def list_cmd(
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit registered projects as a JSON array instead of a text list.",
    ),
) -> None:
    """List registered projects.

    With ``--json``, emits a bare array of per-project objects mirroring
    ``ProjectEntry`` (one row per registration). Empty registries return
    ``[]`` so consumers can rely on the shape unconditionally — there is no
    sentinel "no projects registered" string in JSON mode.
    """
    projects = list_projects(DEFAULT_CONFIG_PATH)
    if as_json:
        typer.echo(json.dumps([_project_to_json(p) for p in projects], indent=2))
        return
    if not projects:
        typer.echo("no projects registered")
        return
    for p in projects:
        typer.echo(f"  {p.root}")


@app.command("start")
def start() -> None:
    """Start the daemon main loop in the foreground (Ctrl+C to stop).

    For a permanent background service, use `ctx watch install-service`
    to register with launchd.
    """
    typer.echo("starting lvdcp-agent daemon (Ctrl+C to stop)")
    run_daemon()


@app.command("install-service")
def install_service(
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "Emit the installed launchd service descriptor as a single JSON "
            "object: `{label, plist_path, uid, program_arguments, log_dir, "
            "bootstrapped}`. Pure data on stdout — suppresses the human "
            "`plist written: ... / launchctl bootstrap ... succeeded` lines. "
            "`bootstrapped: true` is the explicit success signal "
            "(`jq -e '.bootstrapped'` is the natural 'did launchctl really "
            "happen' gate). On `LaunchctlError` exit 3 to stderr is "
            "preserved with **no** payload on stdout — same v0.8.42-v0.8.61 "
            "error-vs-success boundary."
        ),
    ),
) -> None:
    """Install LV_DCP agent as a launchd LaunchAgent (persistent background service).

    With ``--json`` the success-side payload includes `program_arguments`
    so an ops script can verify that launchd received the expected Python
    interpreter (catches the ``uv sync``-after-Python-upgrade footgun where
    the recorded interpreter no longer exists). The plist path round-trips
    so a follow-up ``ctx watch uninstall-service`` can be scripted from the
    same payload without re-deriving the path.
    """
    plist_path = LAUNCH_AGENT_DIR / f"{LAUNCH_AGENT_LABEL}.plist"
    program_arguments = [sys.executable, "-m", "apps.agent.daemon"]
    uid = os.getuid()
    write_plist(
        target_path=plist_path,
        program_arguments=program_arguments,
        log_dir=AGENT_LOG_DIR,
    )
    try:
        bootstrap_agent(plist_path=plist_path, uid=uid)
    except LaunchctlError as exc:
        typer.echo(f"error: {exc}", err=True)
        typer.echo(
            "note: launchctl bootstrap requires an active GUI session — "
            "run from Terminal.app on the desktop, not from SSH.",
            err=True,
        )
        raise typer.Exit(code=3) from exc
    if as_json:
        payload: dict[str, object] = {
            "label": LAUNCH_AGENT_LABEL,
            "plist_path": str(plist_path),
            "uid": uid,
            "program_arguments": list(program_arguments),
            "log_dir": str(AGENT_LOG_DIR),
            "bootstrapped": True,
        }
        typer.echo(json.dumps(payload, indent=2))
        return
    typer.echo(f"plist written: {plist_path}")
    typer.echo(f"launchctl bootstrap gui/{uid} succeeded")


@app.command("uninstall-service")
def uninstall_service(
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "Emit the uninstalled launchd service descriptor as a single "
            "JSON object: `{label, plist_path, uid, plist_existed, "
            "plist_removed, booted_out, bootout_error}`. Pure data on "
            "stdout — suppresses the human `note: ... / removed plist: "
            "... / no plist at ...` lines. The two-axis success signal "
            "(`booted_out` AND `plist_removed`) lets a script distinguish "
            "the four real states: full uninstall (true/true), bootout "
            "failed but plist removed (false/true — daemon may still be "
            "running until next reboot), no-op on absent plist "
            "(false/false — nothing was installed), or daemon-only "
            "removal where we never touched the disk (true/false — "
            "shouldn't happen but the schema covers it). `bootout_error` "
            "is `null` on success and populated with the launchctl "
            "stderr on failure (`jq -r '.bootout_error // empty'` "
            "without a defined-key guard, same v0.8.61 results-array "
            "discipline). Exit semantics unchanged: bootout failure is "
            "non-fatal in both modes (preserves the v0.8.42-v0.8.62 "
            "render-switch-not-behavior-change discipline)."
        ),
    ),
) -> None:
    """Remove LV_DCP agent launchd LaunchAgent.

    With ``--json`` the payload captures both the launchd-side cleanup
    (``booted_out``, ``bootout_error``) and the on-disk side
    (``plist_existed``, ``plist_removed``) as independent two-axis
    signals. This is the symmetric mirror of v0.8.62's
    ``install-service --json`` and closes the watch daemon-service
    surface end-to-end (alongside the pre-existing ``add`` v0.8.54,
    ``remove`` v0.8.56, ``list`` v0.8.49 registry triplet).
    """
    plist_path = LAUNCH_AGENT_DIR / f"{LAUNCH_AGENT_LABEL}.plist"
    uid = os.getuid()
    bootout_error: str | None = None
    booted_out = True
    try:
        bootout_agent(uid=uid)
    except LaunchctlError as exc:
        booted_out = False
        bootout_error = str(exc)
        if not as_json:
            typer.echo(f"note: {exc}", err=True)
    plist_existed = plist_path.exists()
    plist_removed = False
    if plist_existed:
        plist_path.unlink()
        plist_removed = True
        if not as_json:
            typer.echo(f"removed plist: {plist_path}")
    elif not as_json:
        typer.echo(f"no plist at {plist_path}")
    if as_json:
        payload: dict[str, object] = {
            "label": LAUNCH_AGENT_LABEL,
            "plist_path": str(plist_path),
            "uid": uid,
            "plist_existed": plist_existed,
            "plist_removed": plist_removed,
            "booted_out": booted_out,
            "bootout_error": bootout_error,
        }
        typer.echo(json.dumps(payload, indent=2))
