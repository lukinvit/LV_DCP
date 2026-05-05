"""Synthetic breadcrumb fixtures + fake git repo helpers for resume eval."""

from __future__ import annotations

import getpass
import json
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from libs.breadcrumbs.models import BreadcrumbSource
from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.writer import write_hook_event


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "T")
    (r / "README.md").write_text("# Project\n")
    _git(r, "add", "README.md")
    _git(r, "commit", "-q", "-m", "initial")
    return r


@pytest.fixture
def store(tmp_path: Path) -> Iterator[BreadcrumbStore]:
    s = BreadcrumbStore(db_path=tmp_path / "bc.db")
    s.migrate()
    yield s
    s.close()


def seed_pack_events(
    store: BreadcrumbStore,
    *,
    project_root: str,
    queries: list[str],
    paths: list[list[str]],
    spacing_seconds: float = 1.0,
    os_user: str | None = None,
    cc_session_id: str | None = None,
) -> None:
    user = os_user or getpass.getuser()
    base_ts = time.time() - spacing_seconds * len(queries)
    for i, (q, ps) in enumerate(zip(queries, paths, strict=True)):
        store.connect().execute(
            "INSERT INTO breadcrumbs ("
            " project_root, timestamp, source, cc_session_id, os_user, query, mode,"
            " paths_touched, privacy_mode"
            ") VALUES (?, ?, 'pack', ?, ?, ?, 'navigate', ?, 'local_only')",
            (
                project_root,
                base_ts + i * spacing_seconds,
                cc_session_id,
                user,
                q,
                None if not ps else json.dumps(ps[:5]),
            ),
        )
    store.connect().commit()


def seed_hook_event(
    store: BreadcrumbStore,
    *,
    project_root: str,
    todo: list[dict[str, object]] | None = None,
    summary: str | None = None,
) -> None:
    write_hook_event(
        store=store,
        source=BreadcrumbSource.HOOK_STOP,
        project_root=project_root,
        os_user=getpass.getuser(),
        todo_snapshot=todo,
        turn_summary=summary,
    )
