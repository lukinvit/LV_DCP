"""Compute LLM budget status from summaries store."""

from __future__ import annotations

import time

from libs.core.projects_config import LLMConfig
from libs.status.models import BudgetInfo
from libs.summaries.store import SummaryStore, resolve_default_store_path

WARNING_THRESHOLD = 0.80


def compute_budget_status(config: LLMConfig) -> BudgetInfo:
    """Assemble a BudgetInfo snapshot based on config and summaries store."""
    if not config.enabled:
        return BudgetInfo(
            spent_7d=0.0,
            spent_30d=0.0,
            monthly_limit=config.monthly_budget_usd,
            status="disabled",
        )

    now = time.time()
    with SummaryStore(resolve_default_store_path()) as store:
        store.migrate()
        spent_7d = store.total_cost_since(since_ts=now - 7 * 86400)
        spent_30d = store.total_cost_since(since_ts=now - 30 * 86400)

    limit = config.monthly_budget_usd
    if limit <= 0:
        status = "disabled"
    elif spent_30d >= limit:
        status = "exceeded"
    elif spent_30d >= WARNING_THRESHOLD * limit:
        status = "warning"
    else:
        status = "ok"

    return BudgetInfo(
        spent_7d=round(spent_7d, 4),
        spent_30d=round(spent_30d, 4),
        monthly_limit=limit,
        status=status,
    )
