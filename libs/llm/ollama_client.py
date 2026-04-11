"""Ollama HTTP adapter — local LLM, $0 cost."""

from __future__ import annotations

import os
import time

import httpx

from libs.llm.base import RerankCandidate, RerankResult, SummaryResult
from libs.llm.errors import LLMProviderError
from libs.llm.models import UsageRecord
from libs.summaries.prompts import get_prompt

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
REQUEST_TIMEOUT_SECONDS = 300.0  # local inference can be slow


class OllamaClient:
    def __init__(self, *, host: str | None = None) -> None:
        self._host = host or os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_HOST)

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
            async with httpx.AsyncClient(
                base_url=self._host, timeout=REQUEST_TIMEOUT_SECONDS
            ) as http:
                resp = await http.post(
                    "/api/generate",
                    json={
                        "model": model,
                        "prompt": user_msg,
                        "system": prompt["system"],
                        "stream": False,
                        "options": {"temperature": 0.0},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, httpx.ConnectError) as exc:
            raise LLMProviderError(f"ollama request failed: {exc}") from exc

        text = data.get("response", "").strip()
        input_tokens = int(data.get("prompt_eval_count", 0) or 0)
        output_tokens = int(data.get("eval_count", 0) or 0)

        return SummaryResult(
            text=text,
            usage=UsageRecord(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=0,
                cost_usd=0.0,
                model=model,
                provider="ollama",
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
        del query, candidates, model
        raise NotImplementedError("rerank is Phase 3c.2")

    async def test_connection(self) -> bool:
        try:
            async with httpx.AsyncClient(base_url=self._host, timeout=5.0) as http:
                resp = await http.get("/api/tags")
                resp.raise_for_status()
                return True
        except httpx.ConnectError as exc:
            raise LLMProviderError(f"ollama unreachable: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"ollama unreachable: {exc}") from exc
