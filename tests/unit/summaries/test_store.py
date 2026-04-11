from __future__ import annotations

import time
from pathlib import Path

import pytest
from libs.summaries.store import SummaryRow, SummaryStore


def _row(
    *,
    content_hash: str = "h1",
    prompt_version: str = "v1",
    model_name: str = "gpt-4o-mini",
    project_root: str = "/abs/proj",
    file_path: str = "x.py",
    summary_text: str = "Does a thing.",
    cost_usd: float = 0.001,
    tokens_in: int = 100,
    tokens_out: int = 50,
    tokens_cached: int = 0,
    created_at: float | None = None,
) -> SummaryRow:
    return SummaryRow(
        content_hash=content_hash,
        prompt_version=prompt_version,
        model_name=model_name,
        project_root=project_root,
        file_path=file_path,
        summary_text=summary_text,
        cost_usd=cost_usd,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        tokens_cached=tokens_cached,
        created_at=created_at if created_at is not None else time.time(),
    )


def test_persist_and_lookup_roundtrip(tmp_path: Path) -> None:
    store = SummaryStore(tmp_path / "summaries.db")
    store.migrate()

    row = _row()
    store.persist(row)

    got = store.lookup(content_hash="h1", prompt_version="v1", model_name="gpt-4o-mini")
    assert got is not None
    assert got.summary_text == "Does a thing."
    assert got.cost_usd == 0.001


def test_cache_key_differs_by_model(tmp_path: Path) -> None:
    """Different model names produce different rows for the same content."""
    store = SummaryStore(tmp_path / "summaries.db")
    store.migrate()

    store.persist(_row(model_name="gpt-4o-mini", summary_text="gpt version"))
    store.persist(_row(model_name="claude-haiku-4-5", summary_text="claude version"))

    got_gpt = store.lookup(content_hash="h1", prompt_version="v1", model_name="gpt-4o-mini")
    got_claude = store.lookup(content_hash="h1", prompt_version="v1", model_name="claude-haiku-4-5")
    assert got_gpt is not None and got_gpt.summary_text == "gpt version"
    assert got_claude is not None and got_claude.summary_text == "claude version"


def test_list_for_project(tmp_path: Path) -> None:
    store = SummaryStore(tmp_path / "summaries.db")
    store.migrate()

    store.persist(_row(file_path="a.py", project_root="/abs/proj"))
    store.persist(_row(content_hash="h2", file_path="b.py", project_root="/abs/proj"))
    store.persist(_row(content_hash="h3", file_path="c.py", project_root="/other"))

    rows = store.list_for_project("/abs/proj")
    paths = {r.file_path for r in rows}
    assert paths == {"a.py", "b.py"}


def test_total_cost_since(tmp_path: Path) -> None:
    store = SummaryStore(tmp_path / "summaries.db")
    store.migrate()

    now = time.time()
    store.persist(_row(content_hash="h1", cost_usd=0.01, created_at=now - 86400))
    store.persist(_row(content_hash="h2", cost_usd=0.02, created_at=now - 3 * 86400))
    store.persist(_row(content_hash="h3", cost_usd=0.03, created_at=now - 10 * 86400))

    total_7d = store.total_cost_since(since_ts=now - 7 * 86400)
    assert total_7d == pytest.approx(0.03, rel=1e-6)

    total_30d = store.total_cost_since(since_ts=now - 30 * 86400)
    assert total_30d == pytest.approx(0.06, rel=1e-6)


def test_resolve_default_store_path_uses_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from libs.summaries.store import resolve_default_store_path

    override = tmp_path / "custom.db"
    monkeypatch.setenv("LVDCP_SUMMARIES_DB", str(override))
    assert resolve_default_store_path() == override
