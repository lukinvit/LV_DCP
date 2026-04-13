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
        if not candidates:
            return []

        # Build prompt: ask LLM to score each candidate 0.0-1.0
        candidate_lines = "\n".join(
            f"{i+1}. [{c.id}] {c.summary[:200]}" for i, c in enumerate(candidates)
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a code retrieval reranker. Given a query and a list of "
                    "file candidates with summaries, score each file 0.0 to 1.0 on "
                    "relevance to the query. Respond ONLY with JSON: "
                    '[{"id": "file_path", "score": 0.85}, ...] '
                    "Order by score descending. No explanation."
                ),
            },
            {
                "role": "user",
                "content": f"Query: {query}\n\nCandidates:\n{candidate_lines}",
            },
        ]

        try:
            response = await _complete_with_retries(
                self._client, model=model, messages=messages,
            )
            import json  # noqa: PLC0415

            text = response.choices[0].message.content.strip()
            # Strip markdown code block if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
            parsed = json.loads(text)
            return [
                RerankResult(id=item["id"], relevance_score=float(item.get("score", 0.0)))
                for item in parsed
                if "id" in item
            ]
        except (json.JSONDecodeError, KeyError, TypeError):
            # LLM returned unparseable output — return original order with flat scores
            return [
                RerankResult(id=c.id, relevance_score=1.0 - i * 0.01)
                for i, c in enumerate(candidates)
            ]

    async def test_connection(self) -> bool:
        try:
            await self._client.models.list()
            return True
        except AuthenticationError as exc:
            raise LLMProviderError(f"openai auth failed: {exc}") from exc
        except OpenAIError as exc:
            raise LLMProviderError(f"openai connection failed: {exc}") from exc
