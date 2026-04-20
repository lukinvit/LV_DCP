"""`ctx setup <path>` — one-command onboarding for a new project."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast
from urllib.error import URLError
from urllib.request import urlopen

import typer
from libs.core.projects_config import DaemonConfig, load_config

from apps.agent.config import save_config
from apps.cli.commands import mcp_cmd, watch_cmd, wiki_cmd
from apps.cli.commands import scan as scan_module
from apps.cli.commands import ui as ui_module

DEFAULT_CONFIG_PATH = Path.home() / ".lvdcp" / "config.yaml"

StatusKind = Literal["ready", "skipped", "degraded"]


@dataclass(frozen=True)
class SetupStatus:
    state: StatusKind
    detail: str


@dataclass(frozen=True)
class SetupSummary:
    base_mode: SetupStatus
    mcp: SetupStatus
    hooks: SetupStatus
    wiki: SetupStatus
    service: SetupStatus
    full_mode: SetupStatus


def _has_claude_cli() -> bool:
    return shutil.which("claude") is not None


def _enable_wiki_defaults(config_path: Path) -> None:
    cfg = load_config(config_path)
    cfg.wiki.enabled = True
    cfg.wiki.auto_update_after_scan = True
    save_config(config_path, cfg)


def _qdrant_reachable(url: str) -> bool:
    try:
        with urlopen(f"{url.rstrip('/')}/collections", timeout=2) as response:  # noqa: S310
            status = cast("int | None", response.getcode())
            return status == 200
    except (OSError, URLError, ValueError):
        return False


def _full_mode_status(config: DaemonConfig) -> SetupStatus:
    missing: list[str] = []
    if not config.qdrant.enabled:
        missing.append("Qdrant disabled")
    elif not _qdrant_reachable(config.qdrant.url):
        missing.append(f"Qdrant unreachable at {config.qdrant.url}")

    if config.embedding.provider == "fake":
        missing.append("embedding.provider=fake")
    elif config.embedding.provider == "local":
        if not config.embedding.base_url:
            missing.append("local embedding base_url unset")
    else:
        key_name = config.embedding.api_key_env_var
        if not os.environ.get(key_name):
            missing.append(f"{key_name} env var not set")

    if missing:
        return SetupStatus("degraded", f"missing: {', '.join(missing)}")
    return SetupStatus("ready", "Qdrant + embeddings ready")


def _print_summary(summary: SetupSummary) -> None:
    typer.echo("")
    typer.echo("Setup summary")
    typer.echo(f"- base mode: {summary.base_mode.state} — {summary.base_mode.detail}")
    typer.echo(f"- mcp: {summary.mcp.state} — {summary.mcp.detail}")
    typer.echo(f"- hooks: {summary.hooks.state} — {summary.hooks.detail}")
    typer.echo(f"- wiki: {summary.wiki.state} — {summary.wiki.detail}")
    typer.echo(f"- background service: {summary.service.state} — {summary.service.detail}")
    typer.echo(f"- full mode: {summary.full_mode.state} — {summary.full_mode.detail}")


def setup(  # noqa: PLR0912, PLR0913, PLR0915
    path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Path to project root directory",
    ),
    scope: str = typer.Option(
        "user",
        "--scope",
        help="MCP scope: user (global), project (./.mcp.json), or local (gitignored)",
    ),
    full_scan: bool = typer.Option(
        False,
        "--full-scan",
        help="Force a full re-parse of every file during initial scan.",
    ),
    wiki: bool = typer.Option(
        True,
        "--wiki/--no-wiki",
        help="Enable wiki defaults and attempt an initial wiki build.",
    ),
    install_service: bool = typer.Option(
        True,
        "--install-service/--no-install-service",
        help="Attempt to install the background watch service.",
    ),
    open_ui: bool = typer.Option(
        False,
        "--open-ui",
        help="Launch the local dashboard after setup completes.",
    ),
) -> None:
    """Set up a project for LV_DCP in one guided flow."""
    root = path.resolve()

    typer.echo(f"[1/5] scanning {root}")
    try:
        scan_module.scan(root, full=full_scan)
    except Exception as exc:
        typer.echo(f"error: initial scan failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    base_status = SetupStatus("ready", "project registered + scanned")

    mcp_status = SetupStatus("skipped", "Claude CLI missing — MCP install skipped")
    hooks_status = SetupStatus("skipped", "hook install skipped with MCP")
    if _has_claude_cli():
        typer.echo("[2/5] installing MCP + hooks")
        try:
            mcp_cmd.install(scope=scope, dry_run=False)
            mcp_status = SetupStatus("ready", f"registered (scope={scope})")
            hooks_status = SetupStatus("ready", "PreToolUse + PostToolUse installed")
        except typer.Exit as exc:
            mcp_status = SetupStatus("degraded", f"install failed (exit {exc.exit_code})")
            hooks_status = SetupStatus("degraded", "hook install not completed")
    else:
        typer.echo("[2/5] skipping MCP install — Claude CLI not found on PATH")

    wiki_status = SetupStatus("skipped", "disabled by flag")
    if wiki:
        if _has_claude_cli():
            typer.echo("[3/5] enabling wiki + generating initial articles")
            _enable_wiki_defaults(DEFAULT_CONFIG_PATH)
            try:
                wiki_cmd.update(root, all_modules=False)
                wiki_status = SetupStatus("ready", "enabled + initial wiki build attempted")
            except typer.Exit as exc:
                wiki_status = SetupStatus("degraded", f"wiki update failed (exit {exc.exit_code})")
        else:
            wiki_status = SetupStatus("degraded", "Claude CLI missing — wiki not enabled")
            typer.echo("[3/5] skipping wiki generation — Claude CLI not found on PATH")

    service_status = SetupStatus("skipped", "disabled by flag")
    if install_service:
        if sys.platform != "darwin":
            service_status = SetupStatus("skipped", "launchd flow is currently macOS-only")
            typer.echo("[4/5] skipping service install — launchd flow is macOS-only")
        else:
            typer.echo("[4/5] installing background watch service")
            try:
                watch_cmd.install_service()
                service_status = SetupStatus("ready", "launchd agent installed")
            except typer.Exit as exc:
                service_status = SetupStatus(
                    "degraded",
                    f"launchd install failed (exit {exc.exit_code})",
                )

    cfg = load_config(DEFAULT_CONFIG_PATH)
    summary = SetupSummary(
        base_mode=base_status,
        mcp=mcp_status,
        hooks=hooks_status,
        wiki=wiki_status,
        service=service_status,
        full_mode=_full_mode_status(cfg),
    )

    typer.echo("[5/5] evaluating readiness")
    _print_summary(summary)

    if open_ui:
        ui_module.ui(root)
