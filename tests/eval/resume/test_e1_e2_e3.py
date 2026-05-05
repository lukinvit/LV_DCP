"""E1 mid-plan, E2 mid-debug, E3 cross-project switch."""

from __future__ import annotations

import getpass
import time
from pathlib import Path

import pytest
from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.views import build_cross_project_resume_pack, build_project_resume_pack

from tests.eval.resume.conftest import seed_hook_event, seed_pack_events

pytestmark = pytest.mark.eval


def test_e1_mid_plan_surfaces_active_plan(fake_repo: Path, store: BreadcrumbStore) -> None:
    plans = fake_repo / "docs" / "superpowers" / "plans"
    plans.mkdir(parents=True)
    (plans / "2026-05-04-foo.md").write_text(
        "# Foo\n## Step 1\n## Step 2\n## Step 3\n## Step 4\n## Step 5\n## Step 6\n## Step 7\n"
    )
    seed_pack_events(
        store,
        project_root=str(fake_repo),
        queries=["impl step 3 part a", "impl step 3 part b", "impl step 3 done"],
        paths=[["src/a.py"], ["src/a.py"], ["src/a.py"]],
    )
    pack = build_project_resume_pack(
        store=store,
        project_root=fake_repo,
        os_user=getpass.getuser(),
        cc_account_email=None,
        since_ts=0.0,
        limit=100,
    )
    assert pack.snapshot.active_plan is not None
    assert pack.snapshot.active_plan.total_steps == 7
    assert pack.inferred_focus.last_query == "impl step 3 done"


def test_e2_mid_debug_surfaces_failing_test(fake_repo: Path, store: BreadcrumbStore) -> None:
    seed_pack_events(
        store,
        project_root=str(fake_repo),
        queries=["why does test_foo fail", "what's wrong with foo"],
        paths=[["src/foo.py", "tests/test_foo.py"], ["src/foo.py"]],
    )
    seed_hook_event(
        store,
        project_root=str(fake_repo),
        summary="pytest tests/test_foo.py::test_specific_behavior — failing on assertion",
    )
    pack = build_project_resume_pack(
        store=store,
        project_root=fake_repo,
        os_user=getpass.getuser(),
        cc_account_email=None,
        since_ts=0.0,
        limit=100,
    )
    hot = [str(p) for p in pack.inferred_focus.hot_files]
    assert "src/foo.py" in hot
    assert any("fail" in q.lower() for q in pack.open_questions)


def test_e3_cross_project_orders_b_before_a(store: BreadcrumbStore) -> None:
    seed_pack_events(store, project_root="/proj_a", queries=["q1"], paths=[[]])
    time.sleep(0.05)
    seed_pack_events(store, project_root="/proj_b", queries=["q2"], paths=[[]])
    pack = build_cross_project_resume_pack(
        store=store,
        os_user=getpass.getuser(),
        since_ts=0.0,
        limit=10,
    )
    assert pack.digest is not None
    assert [d.project_root for d in pack.digest][:2] == ["/proj_b", "/proj_a"]
