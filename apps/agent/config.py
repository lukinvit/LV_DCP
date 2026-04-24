"""Daemon-side registry mutation helpers.

Read side and the atomic ``save_config`` primitive both live in
``libs.core.projects_config`` so every writer (daemon, UI, CLI, prune)
shares one crash-safe code path. This module adds the domain helpers
that mutate specific fields — ``add_project``, ``remove_project``,
``update_last_scan`` — then defer to the shared writer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from libs.core.projects_config import (
    DaemonConfig,
    ProjectEntry,
    is_transient,
    list_projects,
    load_config,
    save_config,
)

__all__ = [
    "DaemonConfig",
    "ProjectEntry",
    "add_project",
    "is_transient",
    "list_projects",
    "load_config",
    "remove_project",
    "save_config",
    "update_last_scan",
]


def add_project(
    config_path: Path,
    root: Path,
    *,
    allow_transient: bool = False,
) -> None:
    """Register ``root`` in ``~/.lvdcp/config.yaml``.

    Transient paths (ship-ceremony worktrees under ``.claude/worktrees/`` and
    the ``sample_repo`` test fixture) are skipped silently by default — they
    only pile up audit noise that ``ctx registry prune`` would later have to
    clean. Pass ``allow_transient=True`` for explicit user intent (e.g.
    ``ctx watch add <path>`` deliberately targeting a worktree).
    """
    cfg = load_config(config_path)
    root_resolved = root.resolve()
    if not allow_transient and is_transient(root_resolved):
        return
    if any(p.root == root_resolved for p in cfg.projects):
        return
    cfg.projects.append(
        ProjectEntry(
            root=root_resolved,
            registered_at_iso=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )
    )
    save_config(config_path, cfg)


def remove_project(config_path: Path, root: Path) -> None:
    cfg = load_config(config_path)
    root_resolved = root.resolve()
    cfg.projects = [p for p in cfg.projects if p.root != root_resolved]
    save_config(config_path, cfg)


def update_last_scan(
    config_path: Path,
    root: Path,
    *,
    status: str,
    ts_iso: str,
) -> None:
    """Update last_scan_at_iso and last_scan_status for a registered project.

    No-op if the project is not registered (graceful for races where the user
    unregistered between scan-start and scan-complete).
    """
    cfg = load_config(config_path)
    root_resolved = root.resolve()
    updated = False
    for entry in cfg.projects:
        if entry.root == root_resolved:
            entry.last_scan_at_iso = ts_iso
            entry.last_scan_status = status
            updated = True
            break
    if updated:
        save_config(config_path, cfg)
