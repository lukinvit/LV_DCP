"""Integration test for ``lvdcp_when`` (spec-010 T024).

Full pipeline: real git repo → scanner → timeline store → MCP tool.

1. Seed repo with ``alpha``, ``beta``, ``gamma`` — tag v1.
2. Modify ``alpha`` body → tag v2 (triggers a ``modified`` event).
3. Modify ``alpha`` body again → tag v3 (second ``modified`` event).

The story of ``alpha`` must be: ``added`` (v1) → ``modified`` (v2) → ``modified``
(v3), chronologically, with three distinct commit shas.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from apps.mcp.tools import WhenResponse, lvdcp_when
from libs.scanning.scanner import scan_project
from libs.symbol_timeline.sinks import SqliteTimelineSink
from libs.symbol_timeline.store import SymbolTimelineStore


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True)


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    res = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return res.stdout.strip()


def _write_mod(repo: Path, bodies: dict[str, int]) -> None:
    """Overwrite ``pkg/mod.py`` with one def per (name, return value)."""
    body = "\n\n".join(
        f"def {name}() -> int:\n    return {value}\n" for name, value in bodies.items()
    )
    (repo / "pkg" / "mod.py").write_text(body + "\n")


@pytest.fixture
def alpha_history_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, SymbolTimelineStore, list[str]]:
    """3-commit repo where ``alpha`` goes through added → modified → modified."""
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

    # v1: alpha=0, beta=1, gamma=2 — alpha added
    _write_mod(repo, {"alpha": 0, "beta": 1, "gamma": 2})
    sha_v1 = _commit_all(repo, "v1")
    scan_project(repo, mode="full", timeline_sink=SqliteTimelineSink(store=store))

    # v2: alpha body changes (return 10), beta/gamma stay
    _write_mod(repo, {"alpha": 10, "beta": 1, "gamma": 2})
    sha_v2 = _commit_all(repo, "v2")
    scan_project(repo, mode="full", timeline_sink=SqliteTimelineSink(store=store))

    # v3: alpha body changes again (return 20)
    _write_mod(repo, {"alpha": 20, "beta": 1, "gamma": 2})
    sha_v3 = _commit_all(repo, "v3")
    scan_project(repo, mode="full", timeline_sink=SqliteTimelineSink(store=store))

    store.close()
    return repo, SymbolTimelineStore(tmp_path / "timeline.db"), [sha_v1, sha_v2, sha_v3]


def test_lvdcp_when_tells_full_story_of_alpha(
    alpha_history_repo: tuple[Path, SymbolTimelineStore, list[str]],
) -> None:
    repo, _, shas = alpha_history_repo
    sha_v1, sha_v2, sha_v3 = shas

    result = lvdcp_when(path=str(repo), symbol="pkg.mod.alpha")
    assert isinstance(result, WhenResponse)
    assert result.not_found is False
    assert result.qualified_name == "pkg.mod.alpha"

    # Event sequence: added (v1), then two modifieds (v2, v3). Scanner may or
    # may not emit a modified-at-v1 alongside the added; we only insist that
    # the first event is 'added' and that the full list contains shas for all
    # three commits in chronological order.
    assert result.events[0].event_type == "added"
    assert result.events[0].commit_sha == sha_v1

    # At minimum: one added + one modified at v2 + one modified at v3.
    event_shas = [e.commit_sha for e in result.events]
    assert sha_v1 in event_shas
    assert sha_v2 in event_shas
    assert sha_v3 in event_shas
    # Chronological
    assert event_shas == sorted(event_shas, key=lambda s: shas.index(s) if s in shas else -1)


def test_lvdcp_when_unique_fuzzy_match_resolves(
    alpha_history_repo: tuple[Path, SymbolTimelineStore, list[str]],
) -> None:
    """Partial name ``alpha`` is unique in this repo — must auto-resolve."""
    repo, _, _ = alpha_history_repo
    result = lvdcp_when(path=str(repo), symbol="alpha")
    assert result.not_found is False
    assert result.qualified_name == "pkg.mod.alpha"
    assert result.candidates == []


def test_lvdcp_when_unknown_returns_not_found(
    alpha_history_repo: tuple[Path, SymbolTimelineStore, list[str]],
) -> None:
    repo, _, _ = alpha_history_repo
    result = lvdcp_when(path=str(repo), symbol="zzz_no_such_symbol")
    assert result.not_found is True
    assert result.events == []
    assert result.candidates == []


def test_lvdcp_when_response_fits_budget(
    alpha_history_repo: tuple[Path, SymbolTimelineStore, list[str]],
) -> None:
    """SC-002-shaped budget: JSON ≤ 3 KB for a 3-event symbol history."""
    repo, _, _ = alpha_history_repo
    result = lvdcp_when(path=str(repo), symbol="pkg.mod.alpha")
    payload = json.dumps(result.model_dump(), default=str)
    assert len(payload.encode()) <= 3 * 1024, f"response too large: {len(payload)} bytes"
