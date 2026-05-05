"""Breadcrumb writers — exception-swallowing fire-and-forget primitives."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from libs.breadcrumbs.models import BreadcrumbSource
from libs.breadcrumbs.privacy import redact
from libs.breadcrumbs.store import BreadcrumbStore

log = logging.getLogger(__name__)

_TOP_K_PATHS = 5


def _insert(  # noqa: PLR0913
    store: BreadcrumbStore,
    *,
    source: str,
    project_root: str,
    os_user: str,
    timestamp: float,
    cc_session_id: str | None,
    cc_account_email: str | None,
    query: str | None,
    mode: str | None,
    paths_touched: list[str],
    todo_snapshot: list[dict[str, Any]] | None,
    turn_summary: str | None,
    privacy_mode: str = "local_only",
) -> None:
    conn = store.connect()
    conn.execute(
        "INSERT INTO breadcrumbs ("
        " project_root, timestamp, source, cc_session_id, os_user,"
        " cc_account_email, query, mode, paths_touched, todo_snapshot,"
        " turn_summary, privacy_mode"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            project_root,
            timestamp,
            source,
            cc_session_id,
            os_user,
            cc_account_email,
            redact(query),
            mode,
            json.dumps(paths_touched[:_TOP_K_PATHS]) if paths_touched else None,
            json.dumps(todo_snapshot) if todo_snapshot is not None else None,
            redact(turn_summary),
            privacy_mode,
        ),
    )
    conn.commit()


def write_pack_event(  # noqa: PLR0913
    *,
    store: BreadcrumbStore,
    project_root: str,
    os_user: str,
    query: str | None,
    mode: str | None,
    paths_touched: list[str],
    cc_session_id: str | None = None,
    cc_account_email: str | None = None,
) -> None:
    try:
        _insert(
            store,
            source=BreadcrumbSource.PACK.value,
            project_root=project_root,
            os_user=os_user,
            timestamp=time.time(),
            cc_session_id=cc_session_id,
            cc_account_email=cc_account_email,
            query=query,
            mode=mode,
            paths_touched=paths_touched,
            todo_snapshot=None,
            turn_summary=None,
        )
    except Exception:
        log.exception("breadcrumbs.write_pack_event failed (swallowed)")


def write_status_event(
    *,
    store: BreadcrumbStore,
    project_root: str,
    os_user: str,
    cc_session_id: str | None = None,
    cc_account_email: str | None = None,
) -> None:
    try:
        _insert(
            store,
            source=BreadcrumbSource.STATUS.value,
            project_root=project_root,
            os_user=os_user,
            timestamp=time.time(),
            cc_session_id=cc_session_id,
            cc_account_email=cc_account_email,
            query=None,
            mode=None,
            paths_touched=[],
            todo_snapshot=None,
            turn_summary=None,
        )
    except Exception:
        log.exception("breadcrumbs.write_status_event failed (swallowed)")


def write_hook_event(  # noqa: PLR0913
    *,
    store: BreadcrumbStore,
    source: BreadcrumbSource,
    project_root: str,
    os_user: str,
    cc_session_id: str | None = None,
    cc_account_email: str | None = None,
    todo_snapshot: list[dict[str, Any]] | None = None,
    turn_summary: str | None = None,
) -> None:
    if source not in {
        BreadcrumbSource.HOOK_STOP,
        BreadcrumbSource.HOOK_PRE_COMPACT,
        BreadcrumbSource.HOOK_SUBAGENT_STOP,
        BreadcrumbSource.MANUAL,
    }:
        raise ValueError(f"write_hook_event called with non-hook source {source!r}")
    try:
        _insert(
            store,
            source=source.value,
            project_root=project_root,
            os_user=os_user,
            timestamp=time.time(),
            cc_session_id=cc_session_id,
            cc_account_email=cc_account_email,
            query=None,
            mode=None,
            paths_touched=[],
            todo_snapshot=todo_snapshot,
            turn_summary=turn_summary,
        )
    except Exception:
        log.exception("breadcrumbs.write_hook_event failed (swallowed)")
