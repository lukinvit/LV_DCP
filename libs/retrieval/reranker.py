"""LLM-based reranker for retrieval pipeline.

Takes top-N candidates from FTS+graph+vector pipeline and rescores them
using an LLM. Improves precision on large projects where keyword matching
is ambiguous.

Called from lvdcp_pack when llm.enabled=true and rerank_model is configured.
Graceful degradation: if LLM fails, returns original scores.
"""
from __future__ import annotations

import asyncio
import logging

from libs.core.projects_config import LLMConfig
from libs.llm.base import RerankCandidate, RerankResult
from libs.llm.errors import LLMConfigError, LLMProviderError
from libs.llm.registry import create_client

log = logging.getLogger(__name__)


def rerank_candidates(
    *,
    query: str,
    file_scores: dict[str, float],
    file_summaries: dict[str, str],
    llm_config: LLMConfig,
    top_n: int = 20,
) -> dict[str, float]:
    """Rerank top-N files using LLM. Returns updated file_scores.

    Falls back to original scores on any error.
    """
    if not llm_config.enabled:
        return file_scores

    # Take top-N candidates
    sorted_files = sorted(file_scores.items(), key=lambda x: -x[1])[:top_n]
    if not sorted_files:
        return file_scores

    candidates = [
        RerankCandidate(
            id=path,
            summary=file_summaries.get(path, path),
        )
        for path, _ in sorted_files
    ]

    try:
        client = create_client(llm_config)
        results: list[RerankResult] = asyncio.run(
            client.rerank(
                query,
                candidates,
                model=llm_config.rerank_model,
            )
        )

        if not results:
            return file_scores

        # Merge rerank scores: scale to match original score range
        max_original = sorted_files[0][1] if sorted_files else 1.0
        reranked = {r.id: r.relevance_score * max_original for r in results}

        # Update file_scores: reranked files get new scores, rest keep original
        updated = dict(file_scores)
        for path, score in reranked.items():
            if path in updated:
                updated[path] = score
        return updated

    except (LLMConfigError, LLMProviderError, NotImplementedError):
        log.debug("rerank unavailable, using original scores", exc_info=True)
        return file_scores
    except Exception:
        log.warning("rerank failed, using original scores", exc_info=True)
        return file_scores
