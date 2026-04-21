"""Typed schema for gold-standard eval datasets (see specs/006-ragas-promptfoo-eval).

New datasets (rare_symbols, close_siblings, graph_expansion, edit_tasks) are
validated against this schema so malformed YAML fails fast in CI.

Existing queries.yaml / impact_queries.yaml continue to flow through
``loader.load_queries_file`` (raw dict) — this schema is additive and
non-breaking.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

QueryMode = Literal["navigate", "edit", "graph"]


class Expected(BaseModel):
    files: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    answer_text: str | None = None


class GoldQuery(BaseModel):
    id: str
    text: str
    mode: QueryMode
    expected: Expected
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)


def load_gold_dataset(path: Path) -> list[GoldQuery]:
    """Load and validate a gold YAML file.

    Raises ``FileNotFoundError`` if *path* is missing and
    ``pydantic.ValidationError`` if any entry is malformed.
    """
    if not path.exists():
        raise FileNotFoundError(f"gold dataset not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    queries = data.get("queries", [])
    if not isinstance(queries, list):
        raise ValueError(f"queries in {path} must be a list")
    try:
        return [GoldQuery.model_validate(q) for q in queries]
    except ValidationError as e:
        raise ValueError(f"invalid gold dataset at {path}:\n{e}") from e


def load_all_gold_datasets(paths: list[Path]) -> list[GoldQuery]:
    """Concatenate multiple gold datasets; used by the eval runner."""
    out: list[GoldQuery] = []
    for p in paths:
        out.extend(load_gold_dataset(p))
    return out
