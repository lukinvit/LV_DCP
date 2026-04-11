"""LLMClient Protocol — the one interface every provider implements."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from libs.llm.models import UsageRecord


class SummaryResult(BaseModel):
    text: str
    usage: UsageRecord


class RerankCandidate(BaseModel):
    id: str
    summary: str


class RerankResult(BaseModel):
    id: str
    relevance_score: float


@runtime_checkable
class LLMClient(Protocol):
    """Provider-agnostic LLM client.

    `rerank` is declared here so Phase 3c.2 can add it additively; all 3c.1
    implementations raise NotImplementedError for it.
    """

    async def summarize(
        self,
        content: str,
        *,
        model: str,
        prompt_version: str,
        file_path: str,
    ) -> SummaryResult:
        ...

    async def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        model: str,
    ) -> list[RerankResult]:
        ...

    async def test_connection(self) -> bool:
        ...
