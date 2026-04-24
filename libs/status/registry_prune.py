"""Destructive operations for `~/.lvdcp/config.yaml` registry.

Separated from `registry_audit.py` by design: audit is purely read-side,
prune mutates the config. Mixing the two in one module would muddle the
"audit never mutates" invariant that the audit docstring promises.

Prune is gated twice:

1. The CLI surface (`ctx registry prune`) defaults to a dry-run. The
   user must pass `--yes` explicitly to mutate.
2. `prune_stale(..., apply=False)` is the default call signature in the
   library too — callers who forget the flag get a preview, never a
   deletion.

A sibling `*.bak` copy of the original config is always written right
before the mutation so the user has a trivial undo handle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from libs.core.projects_config import ProjectEntry, load_config, save_config
from libs.status.registry_audit import ProjectAudit, audit_registry, is_stale


@dataclass
class PruneResult:
    """Outcome of a prune invocation (dry-run or applied)."""

    kept: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    applied: bool = False
    backup_path: Path | None = None
    config_path: Path | None = None


def _filter_candidates(
    rows: list[ProjectAudit],
    *,
    older_than_days: int,
    kind: str,
) -> list[ProjectAudit]:
    out: list[ProjectAudit] = []
    for row in rows:
        if not is_stale(row, older_than_days=older_than_days):
            continue
        if kind not in {"all", row.kind}:
            continue
        out.append(row)
    return out


def plan_prune(
    config_path: Path,
    *,
    older_than_days: int = 30,
    kind: str = "transient",
) -> list[ProjectAudit]:
    """Return registry rows that WOULD be removed under the given policy.

    Does not mutate anything. Useful for rendering a dry-run preview.
    """
    return _filter_candidates(
        audit_registry(config_path),
        older_than_days=older_than_days,
        kind=kind,
    )


def prune_stale(
    config_path: Path,
    *,
    older_than_days: int = 30,
    kind: str = "transient",
    apply: bool = False,
    backup_suffix: str = ".bak",
) -> PruneResult:
    """Remove stale registry entries matching the policy.

    Args:
      config_path: path to `~/.lvdcp/config.yaml` (or equivalent).
      older_than_days: staleness cutoff (default 30 — matches `is_stale`).
      kind: "transient" | "real" | "all". Default "transient" — that's the
        safe bucket (worktree artifacts, test fixtures). Passing "real"
        can remove user projects that haven't been used in a month, so
        callers who want that must explicitly opt in.
      apply: ``False`` returns a preview, ``True`` mutates the file.
        CLI defaults to False; only `--yes` sets True.
      backup_suffix: appended to `config_path.name` for the backup copy
        (default `.bak`). Written atomically right before mutation.

    Returns:
      A `PruneResult` with the lists of kept/removed roots, plus the
      backup path on apply. On `apply=False` the backup path is None.
    """
    if kind not in {"transient", "real", "all"}:
        msg = f"kind must be 'transient', 'real', or 'all'; got {kind!r}"
        raise ValueError(msg)

    candidates = plan_prune(config_path, older_than_days=older_than_days, kind=kind)
    to_remove = {c.root for c in candidates}

    config = load_config(config_path)
    kept_entries: list[ProjectEntry] = [e for e in config.projects if str(e.root) not in to_remove]
    removed_entries: list[ProjectEntry] = [e for e in config.projects if str(e.root) in to_remove]

    result = PruneResult(
        kept=[str(e.root) for e in kept_entries],
        removed=[str(e.root) for e in removed_entries],
        applied=False,
        backup_path=None,
        config_path=config_path,
    )

    if not apply or not removed_entries:
        return result

    # Write the backup first — if save_config raises mid-way, the user
    # still has an authoritative copy of the original registry.
    backup_path = config_path.with_name(config_path.name + backup_suffix)
    backup_path.write_bytes(config_path.read_bytes())

    config.projects = kept_entries
    save_config(config_path, config)

    result.applied = True
    result.backup_path = backup_path
    return result
