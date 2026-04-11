from __future__ import annotations

import time
from pathlib import Path

import pytest
from libs.core.projects_config import LLMConfig
from libs.status.budget import compute_budget_status
from libs.status.models import BudgetInfo
from libs.summaries.store import SummaryRow, SummaryStore


def _row(cost: float, ts: float) -> SummaryRow:
    return SummaryRow(
        content_hash=f"h{cost}-{ts}",
        prompt_version="v1",
        model_name="gpt-4o-mini",
        project_root="/abs/p",
        file_path="x.py",
        summary_text="t",
        cost_usd=cost,
        tokens_in=100, tokens_out=50, tokens_cached=0,
        created_at=ts,
    )


def test_compute_budget_status_disabled_returns_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LVDCP_SUMMARIES_DB", str(tmp_path / "summaries.db"))
    cfg = LLMConfig(enabled=False, monthly_budget_usd=25.0)
    status = compute_budget_status(cfg)
    assert isinstance(status, BudgetInfo)
    assert status.status == "disabled"
    assert status.spent_7d == 0.0


def test_compute_budget_status_within_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "summaries.db"
    monkeypatch.setenv("LVDCP_SUMMARIES_DB", str(db))

    store = SummaryStore(db)
    store.migrate()
    now = time.time()
    store.persist(_row(cost=5.0, ts=now - 86400))
    store.close()

    cfg = LLMConfig(enabled=True, monthly_budget_usd=25.0)
    status = compute_budget_status(cfg)
    assert status.status == "ok"
    assert status.spent_30d == pytest.approx(5.0, rel=1e-6)
    assert status.monthly_limit == 25.0


def test_compute_budget_status_warning_at_80_percent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "summaries.db"
    monkeypatch.setenv("LVDCP_SUMMARIES_DB", str(db))

    store = SummaryStore(db)
    store.migrate()
    now = time.time()
    store.persist(_row(cost=21.0, ts=now - 86400))  # 84% of 25
    store.close()

    cfg = LLMConfig(enabled=True, monthly_budget_usd=25.0)
    status = compute_budget_status(cfg)
    assert status.status == "warning"


def test_compute_budget_status_exceeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "summaries.db"
    monkeypatch.setenv("LVDCP_SUMMARIES_DB", str(db))

    store = SummaryStore(db)
    store.migrate()
    now = time.time()
    store.persist(_row(cost=30.0, ts=now - 86400))  # over 25
    store.close()

    cfg = LLMConfig(enabled=True, monthly_budget_usd=25.0)
    status = compute_budget_status(cfg)
    assert status.status == "exceeded"
