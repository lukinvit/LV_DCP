"""`ctx registry {ls,prune}` — audit and clean the project registry.

- ``ls`` is read-only: enriches `~/.lvdcp/config.yaml` entries with
  activity signals (scanned?, packs_7d, packs_total, last_scan age) and
  the v0.8.31 real-vs-transient classification.
- ``prune`` is destructive but defaults to a dry-run. The user must pass
  ``--yes`` explicitly to mutate. A sibling ``*.bak`` copy of the
  original config is written right before any mutation.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import typer
from libs.status.aggregator import resolve_config_path
from libs.status.registry_audit import ProjectAudit, audit_registry, is_missing, is_stale
from libs.status.registry_prune import prune_stale

app = typer.Typer(help="Audit and clean the LV_DCP project registry (~/.lvdcp/config.yaml).")


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
        # Surface tombstones in the SCAN column: "MISS" reads at a glance as
        # "root gone from disk" without widening the table or adding a column.
        if r.missing:
            scan_cell = "MISS"
        elif r.scanned:
            scan_cell = "yes"
        else:
            scan_cell = "no"
        lines.append(
            f"{name:<{name_w}}  {r.kind:<9} "
            f"{scan_cell:<5} "
            f"{r.packs_7d:>4} {r.packs_total:>6} "
            f"{_format_age(r.last_scan_age_hours):>9}  {r.root}"
        )
    return "\n".join(lines)


def _apply_filters(
    rows: list[ProjectAudit],
    *,
    kind: str,
    stale: bool,
    missing: bool,
) -> list[ProjectAudit]:
    """Compose filters as AND. All independent — `ls --missing --kind transient`
    returns tombstoned worktrees; `ls --missing --stale` returns the intersection
    (which may be empty but is logically coherent)."""
    out = rows
    if kind != "all":
        out = [r for r in out if r.kind == kind]
    if stale:
        out = [r for r in out if is_stale(r)]
    if missing:
        out = [r for r in out if is_missing(r)]
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
    missing: bool = typer.Option(
        False,
        "--missing",
        help=(
            "Show only entries whose root directory no longer exists on disk — "
            "tombstones left by deleted worktrees or moved project folders. "
            "Composes with --kind and --stale (AND). Pure read — does NOT prune."
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
    rows = _apply_filters(rows, kind=kind, stale=stale, missing=missing)

    if as_json:
        typer.echo(json.dumps([asdict(r) for r in rows], indent=2))
        return
    typer.echo(_render_text(rows))


@app.command("prune")
def prune_cmd(
    older_than: int = typer.Option(
        30,
        "--older-than",
        help="Staleness cutoff in days (default 30). Entries with zero packs_total "
        "and a last scan older than this are eligible. Ignored when --missing is set.",
    ),
    kind: str = typer.Option(
        "transient",
        "--kind",
        help=(
            "Which classification to prune: transient | real | all. "
            "Default 'transient' — worktree artifacts and test fixtures. "
            "Use 'real' only when you know dormant user projects should go. "
            "Ignored when --missing is set."
        ),
    ),
    missing: bool = typer.Option(
        False,
        "--missing",
        help=(
            "Prune entries whose root directory no longer exists on disk — "
            "tombstones left by deleted worktrees or moved project folders. "
            "Ignores --older-than and --kind: a gone root is gone regardless "
            "of classification or scan age. Default off."
        ),
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help=(
            "Actually remove the entries. Without this flag, the command runs "
            "as a dry-run: prints what would be removed and exits without "
            "touching the config. A sibling *.bak copy of the original config "
            "is written right before mutation."
        ),
    ),
) -> None:
    """Remove stale registry entries. Defaults to dry-run — pass --yes to apply.

    Two independent eligibility modes:

    - Default (staleness + kind): entries with ``packs_total=0`` and last
      scan older than ``--older-than`` days, filtered by ``--kind``. The
      default kind is 'transient' (worktree clones, test fixtures) — the
      population where false-positive pruning has near-zero cost.
    - ``--missing``: entries whose root directory no longer exists on disk.
      Independent predicate — catches deleted worktrees and moved project
      folders immediately, without waiting for the staleness gate.

    Pass ``--kind real`` or ``--kind all`` to include real user projects.
    """
    if kind not in {"transient", "real", "all"}:
        typer.echo(
            f"error: --kind must be 'transient', 'real', or 'all', got {kind!r}",
            err=True,
        )
        raise typer.Exit(code=2)
    if older_than <= 0:
        typer.echo("error: --older-than must be positive", err=True)
        raise typer.Exit(code=2)

    config_path = resolve_config_path()
    result = prune_stale(
        config_path,
        older_than_days=older_than,
        kind=kind,
        missing_only=missing,
        apply=yes,
    )

    if not result.removed:
        if missing:
            typer.echo(
                f"prune: no entries with a missing root directory in {config_path} — nothing to do."
            )
        else:
            typer.echo(
                f"prune: no {kind} entries older than {older_than}d in {config_path} — nothing to do."
            )
        return

    mode = "REMOVED" if result.applied else "would remove (dry-run)"
    if missing:
        typer.echo(f"prune: {mode} {len(result.removed)} entries (missing root):")
    else:
        typer.echo(f"prune: {mode} {len(result.removed)} entries ({kind}, >{older_than}d):")
    for root in result.removed:
        typer.echo(f"  - {root}")
    if result.applied and result.backup_path is not None:
        typer.echo(f"prune: backup saved to {result.backup_path}")
    elif not result.applied:
        typer.echo("\nprune: dry-run — no changes written. Pass --yes to apply.")
