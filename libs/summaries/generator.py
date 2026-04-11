"""Single-file summary generator — thin wrapper around LLMClient.summarize.

Exists so the pipeline has a stable call site (one function, not a method
dispatch), and so future prompt selection logic can live here without
bloating pipeline.py.
"""

from __future__ import annotations

from libs.llm.base import LLMClient, SummaryResult


async def generate_file_summary(
    *,
    file_path: str,
    content: str,
    client: LLMClient,
    model: str,
    prompt_version: str,
) -> SummaryResult:
    """Produce a summary for a single file via the given client."""
    return await client.summarize(
        content=content,
        model=model,
        prompt_version=prompt_version,
        file_path=file_path,
    )
