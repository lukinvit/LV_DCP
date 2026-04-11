"""Anthropic Messages API adapter."""

from __future__ import annotations

import time

from anthropic import AnthropicError, AsyncAnthropic, AuthenticationError

from libs.llm.base import RerankCandidate, RerankResult, SummaryResult
from libs.llm.cost import calculate_cost
from libs.llm.errors import LLMProviderError
from libs.llm.models import UsageRecord
from libs.summaries.prompts import FILE_SUMMARY_PROMPT_V1


class AnthropicClient:
    def __init__(self, *, api_key: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)

    async def summarize(
        self,
        content: str,
        *,
        model: str,
        prompt_version: str,
        file_path: str,
    ) -> SummaryResult:
        if prompt_version != "v1":
            raise LLMProviderError(f"unsupported prompt_version: {prompt_version}")
        prompt = FILE_SUMMARY_PROMPT_V1
        user_msg = prompt["user_template"].format(
            file_path=file_path, content=content
        )
        try:
            resp = await self._client.messages.create(
                model=model,
                max_tokens=1024,
                system=prompt["system"],
                messages=[{"role": "user", "content": user_msg}],
                temperature=0.0,
            )
        except AnthropicError as exc:
            raise LLMProviderError(f"anthropic summarize failed: {exc}") from exc

        text_parts = [block.text for block in resp.content if hasattr(block, "text")]
        text = "".join(text_parts).strip()
        cache_read = getattr(resp.usage, "cache_read_input_tokens", 0) or 0
        cost = calculate_cost(
            model=model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            cached_input_tokens=cache_read,
        )
        return SummaryResult(
            text=text,
            usage=UsageRecord(
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
                cached_input_tokens=cache_read,
                cost_usd=cost,
                model=model,
                provider="anthropic",
                timestamp=time.time(),
            ),
        )

    async def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        model: str,
    ) -> list[RerankResult]:
        del query, candidates, model  # intentionally unused in 3c.1
        raise NotImplementedError("rerank is Phase 3c.2")

    async def test_connection(self) -> bool:
        try:
            await self._client.messages.count_tokens(
                model="claude-haiku-4-5",
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except AuthenticationError as exc:
            raise LLMProviderError(f"anthropic auth failed: {exc}") from exc
        except AnthropicError as exc:
            raise LLMProviderError(f"anthropic connection failed: {exc}") from exc
