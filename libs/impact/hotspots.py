"""Hotspot scoring — ranks files by maintenance risk."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HotspotEntry:
    """A single file's hotspot metrics and composite score."""

    file_path: str
    fan_in: int
    fan_out: int
    churn_30d: int
    has_tests: bool
    hotspot_score: float


def compute_hotspots(
    *,
    file_degrees: dict[str, tuple[int, int]],  # {path: (fan_in, fan_out)}
    git_churn: dict[str, int],
    test_coverage: dict[str, bool],
    limit: int = 10,
) -> list[HotspotEntry]:
    """Rank files by risk: high fan_in, frequent changes, no tests = highest score."""
    entries: list[HotspotEntry] = []
    for fp, (fan_in, fan_out) in file_degrees.items():
        churn = git_churn.get(fp, 0)
        has_tests = test_coverage.get(fp, False)
        score = fan_in * (1 + churn) * (2.0 if not has_tests else 1.0)
        entries.append(
            HotspotEntry(
                file_path=fp,
                fan_in=fan_in,
                fan_out=fan_out,
                churn_30d=churn,
                has_tests=has_tests,
                hotspot_score=score,
            )
        )
    entries.sort(key=lambda e: -e.hotspot_score)
    return entries[:limit]
