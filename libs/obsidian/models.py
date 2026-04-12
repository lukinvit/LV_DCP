"""Data models for Obsidian vault sync."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class VaultConfig:
    """Configuration for Obsidian vault sync."""

    vault_path: Path
    sync_mode: str = "manual"
    include_symbols: bool = True
    max_symbol_pages: int = 50


@dataclass
class SyncReport:
    """Result of a vault sync operation."""

    project_name: str
    pages_written: int = 0
    pages_deleted: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)
