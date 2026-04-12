"""Tests for hotspot scoring."""

from __future__ import annotations

from libs.impact.hotspots import compute_hotspots


def test_high_fan_in_high_churn_scores_highest() -> None:
    entries = compute_hotspots(
        file_degrees={"a.py": (10, 2), "b.py": (1, 1)},
        git_churn={"a.py": 5, "b.py": 0},
        test_coverage={"a.py": False, "b.py": True},
    )
    assert entries[0].file_path == "a.py"
    assert entries[0].hotspot_score > entries[1].hotspot_score


def test_no_tests_doubles_score() -> None:
    entries = compute_hotspots(
        file_degrees={"a.py": (5, 2), "b.py": (5, 2)},
        git_churn={"a.py": 3, "b.py": 3},
        test_coverage={"a.py": False, "b.py": True},
    )
    a = next(e for e in entries if e.file_path == "a.py")
    b = next(e for e in entries if e.file_path == "b.py")
    assert a.hotspot_score == b.hotspot_score * 2


def test_limit_parameter() -> None:
    entries = compute_hotspots(
        file_degrees={f"f{i}.py": (i, 1) for i in range(20)},
        git_churn={f"f{i}.py": 1 for i in range(20)},
        test_coverage={f"f{i}.py": True for i in range(20)},
        limit=5,
    )
    assert len(entries) == 5
