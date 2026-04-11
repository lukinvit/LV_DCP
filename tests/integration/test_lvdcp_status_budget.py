from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from apps.agent.config import add_project
from apps.mcp.tools import lvdcp_status
from libs.scanning.scanner import scan_project


def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "config.yaml"
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("LVDCP_CLAUDE_PROJECTS_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("LVDCP_USAGE_CACHE_DB", str(tmp_path / "usage.db"))
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))
    monkeypatch.setenv("LVDCP_SUMMARIES_DB", str(tmp_path / "summaries.db"))
    return cfg


def test_lvdcp_status_budget_disabled_when_llm_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path = _isolated(tmp_path, monkeypatch)
    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("x = 1\n")
    scan_project(project, mode="full")
    add_project(cfg_path, project)

    result = lvdcp_status()
    assert result.budget is not None
    assert result.budget.status == "disabled"


def test_lvdcp_status_budget_populated_when_llm_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path = _isolated(tmp_path, monkeypatch)
    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("x = 1\n")
    scan_project(project, mode="full")
    add_project(cfg_path, project)

    # Enable LLM in config
    cfg_data = yaml.safe_load(cfg_path.read_text())
    cfg_data["llm"] = {"provider": "openai", "enabled": True, "monthly_budget_usd": 25.0}
    cfg_path.write_text(yaml.safe_dump(cfg_data))

    result = lvdcp_status()
    assert result.budget is not None
    assert result.budget.status == "ok"  # empty store = 0 spent
    assert result.budget.spent_7d == 0.0
    assert result.budget.monthly_limit == 25.0


def test_lvdcp_status_with_path_also_includes_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path = _isolated(tmp_path, monkeypatch)
    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("def f() -> None: return None\n")
    scan_project(project, mode="full")
    add_project(cfg_path, project)

    result = lvdcp_status(path=str(project))
    assert result.project is not None
    assert result.budget is not None
