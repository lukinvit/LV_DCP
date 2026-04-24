"""`ctx registry ls` — audit registered projects.

Read-only view of `~/.lvdcp/config.yaml` enriched with per-entry activity
signals (scanned?, packs_7d, packs_total, last_scan age). Surfaces the
real-vs-transient split from v0.8.31 and flags stale candidates for
future pruning — but does NOT prune anything itself (destructive actions
need explicit user confirmation, not a CLI flag default).
"""

from __future__ import annotations

import json
from dataclasses import asdict

import typer
from libs.status.aggregator import resolve_config_path
from libs.status.registry_audit import ProjectAudit, audit_registry, is_stale

app = typer.Typer(help="Audit the LV_DCP project registry (~/.lvdcp/config.yaml).")


# ---- helpers ---------------------------------------------------------------


def _format_age(hours: float | None) -> str:
    if hours is None:
        return "(never)"
    if hours < 1:
        return "<1h"
    if hours < 48:
        return f"{hours:.0f}h"
    return f"{hours / 24:.0f}d"


def _render_text(rows: list[ProjectAudit]) -> str:
    if not rows:
        return "(registry empty)"
    # Two-column layout: left summary, right path. Widths chosen to fit 120 cols.
    name_w = min(max(len(r.name) for r in rows), 32)
    header = (
        f"{'NAME':<{name_w}}  {'KIND':<9} {'SCAN':<5} {'7D':>4} {'TOTAL':>6} {'LASTSCAN':>9}  PATH"
    )
    lines = [header, "-" * len(header)]
    for r in rows:
        name = (r.name[: name_w - 1] + "…") if len(r.name) > name_w else r.name
        lines.append(
            f"{name:<{name_w}}  {r.kind:<9} "
            f"{'yes' if r.scanned else 'no':<5} "
            f"{r.packs_7d:>4} {r.packs_total:>6} "
            f"{_format_age(r.last_scan_age_hours):>9}  {r.root}"
        )
    return "\n".join(lines)


def _apply_filters(rows: list[ProjectAudit], *, kind: str, stale: bool) -> list[ProjectAudit]:
    out = rows
    if kind != "all":
        out = [r for r in out if r.kind == kind]
    if stale:
        out = [r for r in out if is_stale(r)]
    return out


# ---- commands --------------------------------------------------------------


@app.command("ls")
def ls_cmd(
    kind: str = typer.Option(
        "all",
        "--kind",
        help="Filter by classification: real | transient | all (default).",
    ),
    stale: bool = typer.Option(
        False,
        "--stale",
        help=(
            "Show only stale entries — packs_total=0 and last scan >30d ago "
            "(or never scanned). Candidates for future pruning; this flag "
            "does NOT prune anything."
        ),
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Emit the audit as a JSON array instead of a table."
    ),
) -> None:
    """List registered projects with classification and activity signals."""
    if kind not in {"real", "transient", "all"}:
        typer.echo(
            f"error: --kind must be 'real', 'transient', or 'all', got {kind!r}",
            err=True,
        )
        raise typer.Exit(code=2)

    rows = audit_registry(resolve_config_path())
    rows = _apply_filters(rows, kind=kind, stale=stale)

    if as_json:
        typer.echo(json.dumps([asdict(r) for r in rows], indent=2))
        return
    typer.echo(_render_text(rows))
