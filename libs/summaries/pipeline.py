"""Orchestrator: iterate project files, generate summaries, persist to store."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from libs.core.entities import File
from libs.core.hashing import content_hash as compute_content_hash
from libs.llm.base import LLMClient
from libs.llm.errors import LLMProviderError
from libs.project_index.index import ProjectIndex
from libs.summaries.generator import generate_file_summary
from libs.summaries.store import SummaryRow, SummaryStore


@dataclass(frozen=True)
class SummarizeResult:
    project_root: Path
    files_total: int
    files_summarized: int
    files_cached: int
    total_cost_usd: float
    total_tokens_in: int
    total_tokens_out: int
    elapsed_seconds: float
    errors: list[str] = field(default_factory=list)


async def summarize_project(  # noqa: PLR0913
    root: Path,
    *,
    client: LLMClient,
    model: str,
    prompt_version: str,
    store: SummaryStore,
    concurrency: int = 10,
    progress_callback: Callable[[int, int], None] | None = None,
    allowed_roles: list[str] | None = None,
) -> SummarizeResult:
    """Summarize every file in a scanned project.

    Uses ProjectIndex to enumerate files, hashes each file on disk, consults
    the summary store, calls the LLM only on cache misses, persists results.

    Per-file errors are logged in `errors` but do not halt the pipeline.
    """
    root = root.resolve()  # noqa: ASYNC240 — resolve() is pure path manipulation, no I/O
    start = time.perf_counter()

    with ProjectIndex.open(root) as idx:
        files = list(idx.iter_files())

    if allowed_roles is not None:
        files = [f for f in files if f.role in allowed_roles]

    total = len(files)
    semaphore = asyncio.Semaphore(concurrency)

    # Use mutable state captured by closure — pipeline is fire-and-forget per file.
    state = {
        "files_summarized": 0,
        "files_cached": 0,
        "total_cost": 0.0,
        "total_in": 0,
        "total_out": 0,
        "processed": 0,
    }
    errors: list[str] = []

    async def _process_one(file_entity: File) -> None:
        rel_path = file_entity.path
        abs_path = root / rel_path
        async with semaphore:
            try:
                try:
                    data = await asyncio.to_thread(abs_path.read_bytes)
                except OSError as exc:
                    errors.append(f"{rel_path}: {exc}")
                    return

                file_hash = compute_content_hash(data)

                cached = store.lookup(
                    content_hash=file_hash,
                    prompt_version=prompt_version,
                    model_name=model,
                )
                if cached is not None:
                    state["files_cached"] += 1
                    return

                try:
                    text_content = data.decode("utf-8", errors="replace")
                except (UnicodeDecodeError, AttributeError) as exc:
                    errors.append(f"{rel_path}: decode: {exc}")
                    return

                try:
                    result = await generate_file_summary(
                        file_path=rel_path,
                        content=text_content,
                        client=client,
                        model=model,
                        prompt_version=prompt_version,
                    )
                except LLMProviderError as exc:
                    errors.append(f"{rel_path}: {exc}")
                    return

                row = SummaryRow(
                    content_hash=file_hash,
                    prompt_version=prompt_version,
                    model_name=model,
                    project_root=str(root),
                    file_path=rel_path,
                    summary_text=result.text,
                    cost_usd=result.usage.cost_usd,
                    tokens_in=result.usage.input_tokens,
                    tokens_out=result.usage.output_tokens,
                    tokens_cached=result.usage.cached_input_tokens,
                    created_at=result.usage.timestamp,
                )
                store.persist(row)

                state["files_summarized"] += 1
                state["total_cost"] += result.usage.cost_usd
                state["total_in"] += result.usage.input_tokens
                state["total_out"] += result.usage.output_tokens
            finally:
                state["processed"] += 1
                if progress_callback is not None:
                    progress_callback(int(state["processed"]), total)

    await asyncio.gather(*[_process_one(f) for f in files])

    return SummarizeResult(
        project_root=root,
        files_total=total,
        files_summarized=int(state["files_summarized"]),
        files_cached=int(state["files_cached"]),
        total_cost_usd=round(float(state["total_cost"]), 8),
        total_tokens_in=int(state["total_in"]),
        total_tokens_out=int(state["total_out"]),
        elapsed_seconds=time.perf_counter() - start,
        errors=errors,
    )
