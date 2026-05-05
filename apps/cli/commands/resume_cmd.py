"""`ctx resume` — print/inject session context."""

from __future__ import annotations

import getpass
import sys
import time
from pathlib import Path
from typing import Annotated

import typer
from libs.breadcrumbs.cc_identity import resolve_cc_account_email
from libs.breadcrumbs.renderer import render_cross_project, render_inject, render_project_pack
from libs.breadcrumbs.store import DEFAULT_STORE_PATH, BreadcrumbStore
from libs.breadcrumbs.views import build_cross_project_resume_pack, build_project_resume_pack

app = typer.Typer(invoke_without_command=True, add_completion=False)

_RESUME_WINDOW_SECONDS = 12 * 3600


@app.callback()
def resume(
    path: Annotated[Path | None, typer.Option("--path")] = None,
    all_projects: Annotated[bool, typer.Option("--all", "-a")] = False,
    inject: Annotated[bool, typer.Option("--inject")] = False,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
    limit: Annotated[int, typer.Option("--limit")] = 10,
) -> None:
    """Print resume context (markdown). With --inject, output is capped to 2KB."""
    try:
        os_user = getpass.getuser()
        cc_email = resolve_cc_account_email()
        since_ts = time.time() - _RESUME_WINDOW_SECONDS
        store = BreadcrumbStore(db_path=DEFAULT_STORE_PATH)
        store.migrate()
        try:
            if all_projects:
                pack = build_cross_project_resume_pack(
                    store=store,
                    os_user=os_user,
                    since_ts=since_ts,
                    limit=limit,
                )
                md = render_cross_project(pack)
                if md.strip():
                    typer.echo(md, nl=False)
                return
            target = Path(path) if path else Path.cwd()
            ppack = build_project_resume_pack(
                store=store,
                project_root=target,
                os_user=os_user,
                cc_account_email=cc_email,
                since_ts=since_ts,
                limit=limit,
            )
            md = render_inject(ppack) if inject else render_project_pack(ppack)
            if md.strip():
                typer.echo(md, nl=False)
        finally:
            store.close()
    except Exception as exc:
        if not quiet:
            sys.stderr.write(f"resume failed (suppressed): {exc}\n")
