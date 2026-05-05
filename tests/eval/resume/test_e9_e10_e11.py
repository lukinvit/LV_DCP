"""E9 inject latency, E10 cross-project digest order, E11 worktree resolution."""

from __future__ import annotations

import getpass
import subprocess
import time
from pathlib import Path

import pytest
from libs.breadcrumbs.renderer import render_inject
from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.views import build_cross_project_resume_pack, build_project_resume_pack

from tests.eval.resume.conftest import seed_pack_events

pytestmark = pytest.mark.eval


def test_e9_inject_under_500ms_p95(fake_repo: Path, store: BreadcrumbStore) -> None:
    """E9: render_inject() completes in <= 500ms at p95 across 20 samples."""
    seed_pack_events(
        store,
        project_root=str(fake_repo),
        queries=[f"query {i}" for i in range(40)],
        paths=[[f"src/f{i}.py"] for i in range(40)],
    )
    timings: list[float] = []
    for _ in range(20):
        start = time.perf_counter()
        pack = build_project_resume_pack(
            store=store,
            project_root=fake_repo,
            os_user=getpass.getuser(),
            cc_account_email=None,
            since_ts=0.0,
            limit=100,
        )
        render_inject(pack)
        timings.append((time.perf_counter() - start) * 1000)
    timings.sort()
    p95 = timings[int(len(timings) * 0.95)]
    assert p95 <= 500, f"p95 inject latency {p95:.1f}ms exceeds 500ms"


def test_e10_cross_project_digest_orders_correctly(store: BreadcrumbStore) -> None:
    """E10: cross-project digest orders projects by recency (most recent first)."""
    user = getpass.getuser()
    base = time.time() - 100
    for i in range(10):
        store.connect().execute(
            "INSERT INTO breadcrumbs ("
            " project_root, timestamp, source, os_user, query, mode, privacy_mode"
            ") VALUES (?, ?, 'pack', ?, ?, 'navigate', 'local_only')",
            (f"/proj_{i}", base + i, user, f"q{i}"),
        )
    store.connect().commit()
    pack = build_cross_project_resume_pack(store=store, os_user=user, since_ts=0.0, limit=5)
    expected = [f"/proj_{i}" for i in range(9, 4, -1)]
    assert pack.digest is not None
    assert [d.project_root for d in pack.digest] == expected


def test_e11_worktree_resolution(fake_repo: Path, store: BreadcrumbStore, tmp_path: Path) -> None:
    """E11: breadcrumbs seeded against parent path are visible when querying parent."""
    seed_pack_events(
        store,
        project_root=str(fake_repo),
        queries=["work in worktree"],
        paths=[["src/x.py"]],
    )
    wt_path = tmp_path / "worktree"
    subprocess.run(
        ["git", "worktree", "add", "-b", "feat-x", str(wt_path)],
        cwd=fake_repo,
        check=True,
        capture_output=True,
    )
    pack = build_project_resume_pack(
        store=store,
        project_root=fake_repo,
        os_user=getpass.getuser(),
        cc_account_email=None,
        since_ts=0.0,
        limit=100,
    )
    assert pack.inferred_focus.last_query == "work in worktree"
    out = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=wt_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == "feat-x"
