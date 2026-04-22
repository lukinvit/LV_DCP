"""Integration test for ``lvdcp_removed_since`` (spec-010 T019).

Exercises the full pipeline end-to-end:

1. Seed a git repo with 3 top-level functions, tag ``v1``.
2. Remove one function, add a new one, tag ``v2``.
3. Remove another function, tag ``v3``.

Each tag is backed by a real ``git commit`` so the scanner records the
correct ``commit_sha`` in the timeline. Then we call the MCP tool directly
and assert that the removed set matches what we deleted.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from apps.mcp.tools import RemovedSinceResponse, lvdcp_removed_since
from libs.scanning.scanner import scan_project
from libs.symbol_timeline.sinks import SqliteTimelineSink
from libs.symbol_timeline.store import SymbolTimelineStore


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True)


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _write_mod(repo: Path, funcs: list[str]) -> None:
    """Overwrite ``pkg/mod.py`` with one def per func name."""
    body = "\n\n".join(
        f"def {name}() -> int:\n    return {i}\n" for i, name in enumerate(funcs)
    )
    (repo / "pkg" / "mod.py").write_text(body + "\n")


@pytest.fixture
def three_tag_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, SymbolTimelineStore]:
    """Build a repo with three tagged states and a populated timeline store."""
    monkeypatch.setenv("LVDCP_TIMELINE_DB", str(tmp_path / "timeline.db"))

    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")

    (repo / "pkg").mkdir()
    (repo / "pkg" / "__init__.py").write_text("")

    # v1: alpha + beta + gamma
    _write_mod(repo, ["alpha", "beta", "gamma"])
    _commit_all(repo, "v1")
    _git(repo, "tag", "v1")
    store = SymbolTimelineStore(tmp_path / "timeline.db")
    store.migrate()
    scan_project(repo, mode="full", timeline_sink=SqliteTimelineSink(store=store))

    # v2: remove alpha, add delta (beta + gamma stay)
    _write_mod(repo, ["beta", "gamma", "delta"])
    _commit_all(repo, "v2")
    _git(repo, "tag", "v2")
    scan_project(repo, mode="full", timeline_sink=SqliteTimelineSink(store=store))

    # v3: remove beta (gamma + delta stay)
    _write_mod(repo, ["gamma", "delta"])
    _commit_all(repo, "v3")
    _git(repo, "tag", "v3")
    scan_project(repo, mode="full", timeline_sink=SqliteTimelineSink(store=store))

    store.close()
    return repo, SymbolTimelineStore(tmp_path / "timeline.db")


def test_removed_since_v1_returns_alpha_and_beta(
    three_tag_repo: tuple[Path, SymbolTimelineStore],
) -> None:
    repo, _ = three_tag_repo
    result = lvdcp_removed_since(path=str(repo), ref="v1")
    assert isinstance(result, RemovedSinceResponse)
    assert result.ref_not_found is False
    assert result.ref_resolved_sha is not None
    names = {r.qualified_name for r in result.removed}
    assert "pkg.mod.alpha" in names
    assert "pkg.mod.beta" in names
    # gamma + delta are still present in v3 → must NOT appear as removed
    assert "pkg.mod.gamma" not in names
    assert "pkg.mod.delta" not in names


def test_removed_since_v2_returns_beta_only(
    three_tag_repo: tuple[Path, SymbolTimelineStore],
) -> None:
    repo, _ = three_tag_repo
    result = lvdcp_removed_since(path=str(repo), ref="v2")
    names = {r.qualified_name for r in result.removed}
    assert names == {"pkg.mod.beta"}


def test_removed_since_v3_returns_nothing(
    three_tag_repo: tuple[Path, SymbolTimelineStore],
) -> None:
    repo, _ = three_tag_repo
    result = lvdcp_removed_since(path=str(repo), ref="v3")
    assert result.removed == []
    # ref resolves successfully — we just have no removals after v3
    assert result.ref_not_found is False


def test_removed_since_bogus_ref_returns_ref_not_found(
    three_tag_repo: tuple[Path, SymbolTimelineStore],
) -> None:
    repo, _ = three_tag_repo
    result = lvdcp_removed_since(path=str(repo), ref="v999-nope")
    assert result.ref_not_found is True
    assert result.removed == []


def test_removed_since_response_fits_budget(
    three_tag_repo: tuple[Path, SymbolTimelineStore],
) -> None:
    """SC-001 budget shape: JSON response ≤ 2 KB for the typical query."""
    repo, _ = three_tag_repo
    result = lvdcp_removed_since(path=str(repo), ref="v1")
    payload = json.dumps(result.model_dump(), default=str)
    assert len(payload.encode()) <= 2048, f"response too large: {len(payload)} bytes"


def test_removed_since_limit_truncates(
    three_tag_repo: tuple[Path, SymbolTimelineStore],
) -> None:
    repo, _ = three_tag_repo
    result = lvdcp_removed_since(path=str(repo), ref="v1", limit=1)
    assert len(result.removed) == 1
    assert result.truncated is True
    assert result.total_before_limit >= 2
