"""Tests for A1Snapshot enrichment (plan, scan, eval)."""

from pathlib import Path

from libs.breadcrumbs.snapshot import (
    A1Snapshot,
    _clear_caches,
    build_a1_snapshot,
    collect_active_plan,
)


def test_collect_active_plan_picks_newest(tmp_path: Path) -> None:
    plans = tmp_path / "docs" / "superpowers" / "plans"
    plans.mkdir(parents=True)
    p1 = plans / "2026-01-01-foo.md"
    p1.write_text("# Foo\n## Step 1\n## Step 2\n")
    p2 = plans / "2026-02-01-bar.md"
    p2.write_text("# Bar\n## Step 1\n## Step 2\n## Step 3\n")
    plan = collect_active_plan(project_root=tmp_path)
    assert plan is not None
    assert plan.path == p2
    assert plan.total_steps == 3


def test_collect_active_plan_none_when_missing(tmp_path: Path) -> None:
    assert collect_active_plan(project_root=tmp_path) is None


def test_build_a1_snapshot_assembles_all_fields(tmp_path: Path) -> None:
    _clear_caches()
    snap = build_a1_snapshot(project_root=tmp_path)
    assert isinstance(snap, A1Snapshot)
    assert snap.git.branch == ""  # not a git repo
    assert snap.active_plan is None
    assert snap.last_scan is None
