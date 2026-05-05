"""E4 multi-day gap, E5 cold start, E6 hook missed (pack-only)."""

from __future__ import annotations

import getpass
import time
from pathlib import Path

import pytest
from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.views import build_project_resume_pack

from tests.eval.resume.conftest import seed_pack_events

pytestmark = pytest.mark.eval


def test_e4_multi_day_gap_returns_empty_window(fake_repo: Path, store: BreadcrumbStore) -> None:
    """E4: Insert breadcrumb 3 days ago, query with 12h window → breadcrumbs_empty."""
    # Insert breadcrumb 3 days ago directly (bypassing seed helper to control ts)
    long_ago = time.time() - 3 * 86400
    store.connect().execute(
        "INSERT INTO breadcrumbs ("
        " project_root, timestamp, source, os_user, query, mode, privacy_mode"
        ") VALUES (?, ?, 'pack', ?, ?, 'navigate', 'local_only')",
        (str(fake_repo), long_ago, getpass.getuser(), "old"),
    )
    store.connect().commit()
    pack = build_project_resume_pack(
        store=store,
        project_root=fake_repo,
        os_user=getpass.getuser(),
        cc_account_email=None,
        since_ts=time.time() - 12 * 3600,
        limit=100,
    )
    assert pack.breadcrumbs_empty is True
    assert pack.snapshot.git.branch == "main"  # A1 still complete


def test_e5_cold_start(fake_repo: Path, store: BreadcrumbStore) -> None:
    """E5: Empty store, cold start → A1 snapshot is still available."""
    pack = build_project_resume_pack(
        store=store,
        project_root=fake_repo,
        os_user=getpass.getuser(),
        cc_account_email=None,
        since_ts=0.0,
        limit=100,
    )
    assert pack.breadcrumbs_empty is True
    assert pack.inferred_focus.last_query is None
    assert pack.snapshot.git.branch == "main"


def test_e6_hook_missed_pack_only_focus(fake_repo: Path, store: BreadcrumbStore) -> None:
    """E6: No hook events, only pack events → FocusGuess from pack data only."""
    # No hook events, only pack events
    seed_pack_events(
        store,
        project_root=str(fake_repo),
        queries=["q1", "q2", "q3"],
        paths=[["src/x.py"], ["src/x.py", "src/y.py"], ["src/x.py"]],
    )
    pack = build_project_resume_pack(
        store=store,
        project_root=fake_repo,
        os_user=getpass.getuser(),
        cc_account_email=None,
        since_ts=0.0,
        limit=100,
    )
    assert pack.breadcrumbs_empty is False
    assert "src/x.py" in [str(p) for p in pack.inferred_focus.hot_files]
    assert pack.inferred_focus.last_query == "q3"
