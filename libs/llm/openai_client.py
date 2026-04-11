"""OpenAI Chat Completions adapter."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from openai import AsyncOpenAI, AuthenticationError, OpenAIError, RateLimitError

from libs.llm.base import RerankCandidate, RerankResult, SummaryResult
from libs.llm.cost import calculate_cost
from libs.llm.errors import LLMProviderError
from libs.llm.models import UsageRecord
from libs.summaries.prompts import get_prompt

_MAX_RETRIES = 3
_DEFAULT_RETRY_AFTER_SECONDS = 5.0


async def _complete_with_retries(
    client: AsyncOpenAI,
    *,
    model: str,
    messages: list[Any],
) -> Any:
    """Call chat.completions.create with Retry-After-aware retry on 429."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.0,
            )
        except RateLimitError as exc:
            last_exc = exc
            if attempt >= _MAX_RETRIES:
                break
            retry_after = _DEFAULT_RETRY_AFTER_SECONDS
            try:
                header_value = exc.response.headers.get("retry-after")
                if header_value is not None:
                    retry_after = float(header_value)
            except (AttributeError, ValueError):
                pass
            await asyncio.sleep(min(retry_after, 60.0))
    assert last_exc is not None
    raise LLMProviderError(
        f"openai rate limit exceeded after {_MAX_RETRIES} retries: {last_exc}"
    ) from last_exc


class OpenAIClient:
    def __init__(self, *, api_key: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)

    async def summarize(
        self,
        content: str,
        *,
        model: str,
        prompt_version: str,
        file_path: str,
    ) -> SummaryResult:
        try:
            prompt = get_prompt(prompt_version)
        except KeyError as exc:
            raise LLMProviderError(f"unsupported prompt_version: {prompt_version}") from exc
        user_msg = prompt["user_template"].format(file_path=file_path, content=content)
        try:
            resp = await _complete_with_retries(
                self._client,
                model=model,
                messages=[
                    {"role": "system", "content": prompt["system"]},
                    {"role": "user", "content": user_msg},
                ],
            )
        except LLMProviderError:
            raise  # propagate our typed error
        except OpenAIError as exc:
            raise LLMProviderError(f"openai summarize failed: {exc}") from exc

        text = (resp.choices[0].message.content or "").strip()
        usage = resp.usage  # CompletionUsage | None per OpenAI stubs
        if usage is None:
            raise LLMProviderError("openai response missing usage field")
        cached = 0
        if usage.prompt_tokens_details is not None:
            cached = usage.prompt_tokens_details.cached_tokens or 0
        cost = calculate_cost(
            model=model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            cached_input_tokens=cached,
        )
        return SummaryResult(
            text=text,
            usage=UsageRecord(
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                cached_input_tokens=cached,
                cost_usd=cost,
                model=model,
                provider="openai",
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
        raise NotImplementedError("rerank is Phase 3c.2")

    async def test_connection(self) -> bool:
        try:
            await self._client.models.list()
            return True
        except AuthenticationError as exc:
            raise LLMProviderError(f"openai auth failed: {exc}") from exc
        except OpenAIError as exc:
            raise LLMProviderError(f"openai connection failed: {exc}") from exc
