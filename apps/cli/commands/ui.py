"""`ctx ui` command — launch the local dashboard server."""

from __future__ import annotations

import webbrowser
from pathlib import Path

import typer
import uvicorn


def ui(
    path: Path | None = typer.Argument(  # noqa: B008
        None,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Optional project path to open directly in detail view.",
    ),
    port: int = typer.Option(8787, "--port", help="Port to bind on 127.0.0.1"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not auto-open in browser"),
) -> None:
    """Launch the LV_DCP dashboard on localhost:<port>."""
    from apps.ui.main import create_app  # noqa: PLC0415

    app = create_app()
    open_path = "/"
    if path is not None:
        slug = path.name.lower().replace("_", "-")
        open_path = f"/project/{slug}"

    url = f"http://127.0.0.1:{port}{open_path}"
    typer.echo(f"LV_DCP dashboard starting on {url}")
    if not no_browser:
        webbrowser.open(url)

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
