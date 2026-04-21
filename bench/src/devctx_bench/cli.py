"""Standalone CLI: ``devctx-bench run <project> --queries <file> [--retriever-module MOD]``.

Without ``--retriever-module`` the CLI runs against a stub retriever
(useful to validate the eval harness itself is installed correctly).

With ``--retriever-module my_pkg.my_module:my_retriever`` the CLI imports
the target module and calls it as the ``RetrievalFn``. This is the
primary path — users bring their own retrieval system.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import typer

from devctx_bench.loader import load_optional_queries_file, load_queries_file
from devctx_bench.report import generate_per_query_report
from devctx_bench.runner import RetrievalFn, run_eval, stub_retrieve

app = typer.Typer(
    help="devctx-bench — retrieval-only benchmark harness for code-context tools.",
    no_args_is_help=True,
)


def _import_retriever(spec: str) -> RetrievalFn:
    """Load a RetrievalFn from ``module.path:attribute``.

    ``spec`` examples:
        ``my_pkg.retriever:retrieve``  → ``my_pkg.retriever.retrieve``
        ``retriever:my_fn``            → ``retriever.my_fn``
    """
    if ":" not in spec:
        raise typer.BadParameter(
            f"retriever spec must be 'module:attr', got {spec!r}",
        )
    module_name, attr = spec.split(":", 1)
    module = importlib.import_module(module_name)
    try:
        fn = getattr(module, attr)
    except AttributeError as exc:
        raise typer.BadParameter(
            f"attribute {attr!r} not found in module {module_name!r}",
        ) from exc
    return fn  # type: ignore[no-any-return]


@app.command()
def run(
    project: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Project root the retriever will receive as repo_path.",
    ),
    queries: Path = typer.Option(  # noqa: B008
        ...,
        "--queries",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        help="Path to a navigate queries YAML file.",
    ),
    impact_queries: Path | None = typer.Option(  # noqa: B008
        None,
        "--impact-queries",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        help="Optional path to an impact queries YAML file.",
    ),
    retriever_module: str | None = typer.Option(
        None,
        "--retriever-module",
        "-r",
        help=(
            "Python spec of the retriever function, format 'module:attr'. "
            "If omitted, a stub retriever is used (metrics will all be 0)."
        ),
    ),
    output: Path | None = typer.Option(  # noqa: B008
        None,
        "--output",
        "-o",
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        help="Write markdown report to this file instead of stdout.",
    ),
) -> None:
    """Run the eval harness against a user-supplied retriever."""
    retriever = _import_retriever(retriever_module) if retriever_module else stub_retrieve

    navigate = load_queries_file(queries)
    impact = load_optional_queries_file(impact_queries) if impact_queries else []

    report = run_eval(
        retriever,
        repo_path=project,
        navigate_queries=navigate,
        impact_queries=impact,
    )

    rendered = generate_per_query_report(
        report,
        tag=f"devctx-bench @ {project.name}",
    )
    if output is not None:
        output.write_text(rendered, encoding="utf-8")
        typer.echo(f"wrote: {output}")
    else:
        typer.echo(rendered)


@app.command()
def version() -> None:
    """Print the installed devctx-bench version."""
    from devctx_bench import __version__  # noqa: PLC0415

    typer.echo(__version__)
