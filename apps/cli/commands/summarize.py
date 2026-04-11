"""`ctx summarize <path>` — generate LLM summaries for a scanned project."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from libs.core.projects_config import load_config
from libs.llm.errors import LLMConfigError
from libs.llm.registry import create_client
from libs.status.aggregator import resolve_config_path
from libs.summaries.pipeline import summarize_project
from libs.summaries.store import SummaryStore, resolve_default_store_path
from rich.progress import Progress, SpinnerColumn, TextColumn


def summarize(
    path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Project root to summarize",
    ),
    model: str | None = typer.Option(None, "--model", help="Override summary_model from config"),
    concurrency: int = typer.Option(10, "--concurrency", help="Parallel LLM calls"),
) -> None:
    """Generate LLM summaries for every file in a scanned project.

    Results are cached in ~/.lvdcp/summaries.db keyed on
    (content_hash, prompt_version, model_name). Running twice on unchanged
    files yields 100% cache hits and zero cost.
    """
    config = load_config(resolve_config_path())
    if not config.llm.enabled:
        typer.echo(
            "error: LLM is disabled. Enable via `ctx ui` settings page or edit "
            "~/.lvdcp/config.yaml to set llm.enabled: true",
            err=True,
        )
        raise typer.Exit(code=1)

    effective_model = model or config.llm.summary_model
    try:
        client = create_client(config.llm)
    except LLMConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    with SummaryStore(resolve_default_store_path()) as store:
        store.migrate()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TextColumn("{task.completed}/{task.total}"),
        ) as progress:
            task = progress.add_task(f"Summarizing {path.name}", total=None)

            def _callback(current: int, total: int) -> None:
                progress.update(task, total=total, completed=current)

            result = asyncio.run(
                summarize_project(
                    path.resolve(),
                    client=client,
                    model=effective_model,
                    prompt_version=config.llm.prompt_version,
                    store=store,
                    concurrency=concurrency,
                    progress_callback=_callback,
                )
            )

    typer.echo(
        f"summarized {result.files_summarized} new files "
        f"({result.files_cached} cached), "
        f"cost ${result.total_cost_usd:.4f}, "
        f"{result.total_tokens_in}→{result.total_tokens_out} tokens, "
        f"in {result.elapsed_seconds:.2f}s"
    )
    if result.errors:
        typer.echo(f"warnings: {len(result.errors)} files failed:", err=True)
        for err in result.errors[:5]:
            typer.echo(f"  {err}", err=True)
