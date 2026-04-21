"""YAML query-file loader for the eval harness.

A queries file is a YAML document with this shape::

    queries:
      - id: q01
        text: "session factory"
        mode: navigate
        expected:
          files: ["libs/auth/session.py"]
          symbols: ["libs.auth.session.make_session"]

``impact`` queries share the same shape and live in a separate file so
graph-expansion metrics can be computed over a distinct subset.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_queries_file(path: Path) -> list[dict[str, Any]]:
    """Return the ``queries:`` list from a YAML file, or [] if absent.

    Raises :class:`FileNotFoundError` if *path* does not exist — unlike
    the impact queries variant, a queries file is always required.
    """
    if not path.exists():
        raise FileNotFoundError(f"queries file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    queries = data.get("queries", [])
    if not isinstance(queries, list):
        raise ValueError(f"queries in {path} must be a list")
    return queries


def load_optional_queries_file(path: Path) -> list[dict[str, Any]]:
    """Return the ``queries:`` list, or [] when the file is missing.

    Used for optional supplementary query sets (e.g. impact queries).
    """
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    queries = data.get("queries", [])
    if not isinstance(queries, list):
        raise ValueError(f"queries in {path} must be a list")
    return queries
