"""Data models for Obsidian vault sync."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict


class ObsidianFileInfo(TypedDict):
    path: str
    language: str


class ObsidianSymbolInfo(TypedDict, total=False):
    name: str
    fq_name: str
    file_path: str
    symbol_type: str


class ObsidianRelationInfo(TypedDict):
    src_ref: str
    dst_ref: str
    relation_type: str


class ObsidianModuleData(TypedDict):
    file_count: int
    symbol_count: int
    top_symbols: list[str]
    dependencies: list[str]
    dependents: list[str]


class ObsidianGitInfo(TypedDict, total=False):
    file_path: str
    churn_30d: int
    commit_count: int
    last_author: str


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
