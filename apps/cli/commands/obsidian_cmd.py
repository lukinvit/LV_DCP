"""`ctx obsidian sync` and `ctx obsidian status` subcommands."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import typer
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

    typer.echo(f"Synced {project_name} to {vault}")
    typer.echo(f"  Pages written: {report.pages_written}")
    typer.echo(f"  Duration: {report.duration_seconds:.2f}s")
    if report.errors:
        typer.echo(f"  Errors ({len(report.errors)}):")
        for err in report.errors:
            typer.echo(f"    - {err}")


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
) -> None:
    """List project directories in the Obsidian vault."""
    projects_dir = vault / "Projects"
    if not projects_dir.exists():
        typer.echo("No Projects/ directory found in vault.")
        raise typer.Exit(code=0)

    dirs = sorted(p.name for p in projects_dir.iterdir() if p.is_dir())
    if not dirs:
        typer.echo("No project directories found.")
    else:
        typer.echo(f"Projects in vault ({len(dirs)}):")
        for d in dirs:
            typer.echo(f"  - {d}")
