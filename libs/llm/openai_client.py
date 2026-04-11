"""OpenAI Chat Completions adapter."""

from __future__ import annotations

import time

from openai import AsyncOpenAI, AuthenticationError, OpenAIError

from libs.llm.base import RerankCandidate, RerankResult, SummaryResult
from libs.llm.cost import calculate_cost
from libs.llm.errors import LLMProviderError
from libs.llm.models import UsageRecord
from libs.summaries.prompts import FILE_SUMMARY_PROMPT_V1


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
        if prompt_version != "v1":
            raise LLMProviderError(f"unsupported prompt_version: {prompt_version}")
        prompt = FILE_SUMMARY_PROMPT_V1
        user_msg = prompt["user_template"].format(
            file_path=file_path, content=content
        )
        try:
            resp = await self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": prompt["system"]},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.0,
            )
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
