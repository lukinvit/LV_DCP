"""Integration test for the LLM-judge path end-to-end (see specs/006).

Uses the ``sample_repo`` fixture and a deterministic stub retriever. The
RAGAS adapter's metric ``ascore`` methods are patched so the test does
not depend on a network or an API key — but the full wiring
(run_eval → enrich_with_ragas → EvalReport.ragas) is exercised.

Determinism guarantee: running the pipeline twice with the same inputs
and ``cache_enabled=True`` must produce bit-identical metric values.

Markers: ``eval`` (harness) + ``llm`` (would call an LLM in the non-test
variant). The ``llm`` marker is skipped by default in pyproject.toml
configuration; this test opts back in explicitly.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from libs.eval.cost_guard import CostGuard
from libs.eval.ragas_adapter import RagasAdapter
from libs.eval.runner import enrich_with_ragas
from ragas.llms.base import InstructorBaseRagasLLM

from tests.eval.run_eval import FIXTURE_REPO, load_queries, run_eval

pytestmark = [pytest.mark.eval, pytest.mark.llm]


def _queries_with_judge_fields() -> list[dict[str, Any]]:
    """Fixture gold queries don't carry reference/response — inject dummies so
    all 3 RAGAS metrics fire end-to-end."""
    queries = [deepcopy(q) for q in load_queries()]
    for q in queries:
        expected = q.setdefault("expected", {})
        expected["answer_text"] = f"expected answer for {q['id']}"
        q["response"] = f"mock response for {q['id']}"
    return queries


def _stub_retrieve(query: str, mode: str, repo_path: Path) -> tuple[list[str], list[str]]:
    """Deterministic retriever: returns the first file from sample_repo for every query."""
    del query, mode
    # Return a file that actually exists in the fixture, so file_reader
    # materializes a non-empty context. Falls back to empty lists if the
    # fixture layout changes.
    sample = next(iter(repo_path.rglob("*.py")), None)
    if sample is None:
        return [], []
    rel = sample.relative_to(repo_path).as_posix()
    return [rel], []


def _metric_result(value: float) -> MagicMock:
    r = MagicMock()
    r.value = value
    return r


def _build_adapter() -> tuple[RagasAdapter, dict[str, AsyncMock]]:
    guard = CostGuard(max_usd=10.0)
    adapter = RagasAdapter(
        judge_model="claude-haiku-4-5",
        cost_guard=guard,
        api_key="dummy",
        llm_override=MagicMock(spec=InstructorBaseRagasLLM),
        cache_enabled=True,
    )
    cp = AsyncMock(return_value=_metric_result(0.82))
    cr = AsyncMock(return_value=_metric_result(0.71))
    f = AsyncMock(return_value=_metric_result(0.93))
    adapter._cp.ascore = cp  # type: ignore[method-assign]
    adapter._cr.ascore = cr  # type: ignore[method-assign]
    adapter._f.ascore = f  # type: ignore[method-assign]
    return adapter, {"cp": cp, "cr": cr, "f": f}


async def test_eval_full_pipeline_runs_end_to_end() -> None:
    queries = _queries_with_judge_fields()
    ir_report = run_eval(_stub_retrieve, repo_path=FIXTURE_REPO)
    assert ir_report.ragas is None  # IR-only stage has no judge yet.

    adapter, _ = _build_adapter()
    enriched = await enrich_with_ragas(
        ir_report,
        queries=queries,
        repo_path=FIXTURE_REPO,
        adapter=adapter,
    )

    assert enriched.ragas is not None
    # IR metrics copied through unchanged.
    assert enriched.recall_at_5_files == ir_report.recall_at_5_files
    assert enriched.mrr_files == ir_report.mrr_files
    # Per-query judge entries one per query_result.
    assert len(enriched.ragas.per_query) == len(ir_report.query_results)
    # All 3 judge metrics fired at least once.
    assert enriched.ragas.context_precision == pytest.approx(0.82)
    assert enriched.ragas.context_recall == pytest.approx(0.71)
    assert enriched.ragas.faithfulness == pytest.approx(0.93)


async def test_eval_full_pipeline_is_deterministic_with_cache() -> None:
    """Two runs with cache_enabled=True yield byte-identical metric values."""
    queries = _queries_with_judge_fields()
    ir_report = run_eval(_stub_retrieve, repo_path=FIXTURE_REPO)

    adapter, _ = _build_adapter()
    first = await enrich_with_ragas(
        ir_report,
        queries=queries,
        repo_path=FIXTURE_REPO,
        adapter=adapter,
    )
    second = await enrich_with_ragas(
        ir_report,
        queries=queries,
        repo_path=FIXTURE_REPO,
        adapter=adapter,
    )

    assert first.ragas is not None
    assert second.ragas is not None
    assert first.ragas.context_precision == second.ragas.context_precision
    assert first.ragas.context_recall == second.ragas.context_recall
    assert first.ragas.faithfulness == second.ragas.faithfulness
    # Second run should be all cache hits.
    assert second.ragas.cache_misses == 0
    assert second.ragas.cache_hits > 0


async def test_eval_full_pipeline_caches_identical_queries() -> None:
    """If two queries share user_input + contexts, metric LLM runs once."""
    queries = _queries_with_judge_fields()
    # Duplicate the first query under a new id; cache keys on query+contexts
    # (not id), so the duplicate must hit the cache.
    if not queries:
        pytest.skip("No fixture queries to duplicate.")
    dup = deepcopy(queries[0])
    dup["id"] = dup["id"] + "-dup"
    queries = [*queries, dup]

    ir_report = run_eval(_stub_retrieve, repo_path=FIXTURE_REPO)
    from libs.eval.runner import QueryResult

    dup_qr = QueryResult(
        query_id=dup["id"],
        mode=dup["mode"],
        retrieved_files=list(ir_report.query_results[0].retrieved_files),
        retrieved_symbols=list(ir_report.query_results[0].retrieved_symbols),
        expected_files=list(ir_report.query_results[0].expected_files),
        expected_symbols=list(ir_report.query_results[0].expected_symbols),
    )
    from dataclasses import replace

    ir_report = replace(
        ir_report, query_results=[*ir_report.query_results, dup_qr]
    )

    adapter, _ = _build_adapter()
    result = await enrich_with_ragas(
        ir_report,
        queries=queries,
        repo_path=FIXTURE_REPO,
        adapter=adapter,
    )

    # First query + duplicate share user_input + contexts → cache hits on dup.
    assert result.ragas is not None
    assert result.ragas.cache_hits >= 1
