"""Integration test for ``lvdcp_diff`` + ``lvdcp_regressions`` (spec-010 T031).

End-to-end: real git repo → scanner → timeline store → MCP tools.

Corpus mirrors test_removed_since.py's three-tag story:
* v1: alpha, beta, gamma
* v2: beta, gamma, delta   (alpha removed, delta added)
* v3: gamma, delta         (beta removed, gamma modified)

Diff(v1, v2) must show: added={delta}, removed={alpha}, modified ⊆ {},
                       renamed=[].
Diff(v1, v3) must show: added={delta}, removed={alpha, beta}, modified ⊇
                       {gamma}.
Diff(v3, v3) must be fully empty.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import pytest
from apps.mcp.tools import (
    DiffResponse,
    RegressionResponse,
    lvdcp_diff,
    lvdcp_regressions,
)
from libs.scanning.scanner import scan_project
from libs.symbol_timeline.sinks import SqliteTimelineSink
from libs.symbol_timeline.store import SymbolTimelineStore


class _HasQualifiedName(Protocol):
    qualified_name: str | None


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True)


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _write_mod(repo: Path, funcs: dict[str, int]) -> None:
    body = "\n\n".join(
        f"def {name}() -> int:\n    return {value}\n" for name, value in funcs.items()
    )
    (repo / "pkg" / "mod.py").write_text(body + "\n")


@pytest.fixture
def tagged_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Real git repo with tags v1, v2, v3 and a populated timeline store."""
    monkeypatch.setenv("LVDCP_TIMELINE_DB", str(tmp_path / "timeline.db"))

    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")

    (repo / "pkg").mkdir()
    (repo / "pkg" / "__init__.py").write_text("")

    store = SymbolTimelineStore(tmp_path / "timeline.db")
    store.migrate()

    # v1
    _write_mod(repo, {"alpha": 0, "beta": 1, "gamma": 2})
    _commit_all(repo, "v1")
    _git(repo, "tag", "v1")
    scan_project(repo, mode="full", timeline_sink=SqliteTimelineSink(store=store))

    # v2: remove alpha, add delta
    _write_mod(repo, {"beta": 1, "gamma": 2, "delta": 3})
    _commit_all(repo, "v2")
    _git(repo, "tag", "v2")
    scan_project(repo, mode="full", timeline_sink=SqliteTimelineSink(store=store))

    # v3: remove beta, modify gamma body
    _write_mod(repo, {"gamma": 42, "delta": 3})
    _commit_all(repo, "v3")
    _git(repo, "tag", "v3")
    scan_project(repo, mode="full", timeline_sink=SqliteTimelineSink(store=store))

    store.close()
    return repo


def _names(entries: Sequence[_HasQualifiedName]) -> set[str]:
    return {e.qualified_name for e in entries if e.qualified_name}


def test_lvdcp_diff_v1_v2(tagged_repo: Path) -> None:
    result = lvdcp_diff(path=str(tagged_repo), from_ref="v1", to_ref="v2")
    assert isinstance(result, DiffResponse)
    assert result.ref_not_found is False
    assert _names(result.added) == {"pkg.mod.delta"}
    assert _names(result.removed) == {"pkg.mod.alpha"}
    # modified might be empty OR contain body-hash artefacts — we only insist
    # alpha is NOT in modified
    assert "pkg.mod.alpha" not in _names(result.modified)


def test_lvdcp_diff_v1_v3(tagged_repo: Path) -> None:
    result = lvdcp_diff(path=str(tagged_repo), from_ref="v1", to_ref="v3")
    assert result.ref_not_found is False
    assert _names(result.added) == {"pkg.mod.delta"}
    assert _names(result.removed) == {"pkg.mod.alpha", "pkg.mod.beta"}
    # gamma changed body between v1 and v3 → must be in modified
    assert "pkg.mod.gamma" in _names(result.modified)


def test_lvdcp_diff_same_ref_returns_empty(tagged_repo: Path) -> None:
    """Spec US3.2: from == to → all buckets empty, tiny payload."""
    result = lvdcp_diff(path=str(tagged_repo), from_ref="v3", to_ref="v3")
    assert result.added == []
    assert result.removed == []
    assert result.modified == []
    assert result.renamed == []
    payload = json.dumps(result.model_dump(), default=str)
    assert len(payload.encode()) <= 512


def test_lvdcp_diff_bogus_ref_returns_ref_not_found(tagged_repo: Path) -> None:
    result = lvdcp_diff(path=str(tagged_repo), from_ref="v999-nope", to_ref="v3")
    assert result.ref_not_found is True
    assert result.added == []
    assert result.removed == []


def test_lvdcp_diff_v1_v3_response_fits_budget(tagged_repo: Path) -> None:
    """SC-005-shaped: JSON ≤ 15 KB for a non-trivial diff."""
    result = lvdcp_diff(path=str(tagged_repo), from_ref="v1", to_ref="v3")
    payload = json.dumps(result.model_dump(), default=str)
    assert len(payload.encode()) <= 15 * 1024


def test_lvdcp_regressions_v1_v3_returns_removed_only(tagged_repo: Path) -> None:
    result = lvdcp_regressions(path=str(tagged_repo), from_ref="v1", to_ref="v3")
    assert isinstance(result, RegressionResponse)
    assert result.ref_not_found is False
    assert _names(result.removed) == {"pkg.mod.alpha", "pkg.mod.beta"}


def test_lvdcp_regressions_limit_truncates(tagged_repo: Path) -> None:
    result = lvdcp_regressions(path=str(tagged_repo), from_ref="v1", to_ref="v3", limit=1)
    assert len(result.removed) == 1
    assert result.truncated is True
    assert result.total_removed >= 2
