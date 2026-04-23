"""Spec-010 T042 — scan-overhead perf check (SC-003).

Guardrail that the timeline sink doesn't add more than 10% wall-clock
overhead to a cold scan. We run each configuration ``REPEATS`` times
against a deterministically-generated project and compare the *min*
wall-clock — mins are more stable than means on CI runners because
they filter out scheduler noise.

Marked ``@pytest.mark.slow`` so it is excluded from the default unit
suite. Run with ``uv run pytest -m slow tests/perf``.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
from libs.scanning import scanner as scanner_mod
from libs.scanning.scanner import scan_project
from libs.symbol_timeline.sinks import MemoryTimelineSink

# Matched to the "small project" SC target in plan.md: a few dozen modules
# with real imports and real docstrings so the parser does actual work.
_FILE_COUNT = 40
_REPEATS = 3
_OVERHEAD_BUDGET = 0.10  # 10% — spec SC-003


def _seed_project(root: Path) -> None:
    """Generate ``_FILE_COUNT`` Python files with cross-module imports.

    Each file exports a small function and imports the two following
    modules so the symbol graph has real edges.
    """
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    for i in range(_FILE_COUNT):
        next1 = (i + 1) % _FILE_COUNT
        next2 = (i + 2) % _FILE_COUNT
        body = (
            f'"""Module {i} — synthetic perf fixture."""\n'
            "from __future__ import annotations\n\n"
            f"from pkg.mod_{next1:03d} import fn_{next1:03d}  # noqa: F401\n"
            f"from pkg.mod_{next2:03d} import fn_{next2:03d}  # noqa: F401\n\n\n"
            f"def fn_{i:03d}(value: int) -> int:\n"
            f'    """Doubler #{i} used only to give the parser something to chew."""\n'
            f"    return value * 2\n\n\n"
            f"class Shape{i:03d}:\n"
            f'    """Shape #{i}."""\n'
            f"    x: int = {i}\n"
            f"    y: int = {i * 2}\n"
        )
        (pkg / f"mod_{i:03d}.py").write_text(body)


def _time_scan_min(
    project_root: Path,
    *,
    sink: object | None,
    repeats: int,
) -> float:
    """Scan ``repeats`` times and return the minimum wall-clock seconds."""
    best = float("inf")
    for _ in range(repeats):
        # Reset .context/ between runs so every scan is cold.
        ctx = project_root / ".context"
        if ctx.exists():
            shutil.rmtree(ctx)
        start = time.perf_counter()
        scan_project(project_root, mode="full", timeline_sink=sink)
        best = min(best, time.perf_counter() - start)
    return best


@pytest.mark.slow
def test_timeline_overhead_under_ten_percent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Timeline-emitting scan must be ≤ 110% of no-timeline baseline.

    We override ``_maybe_build_default_timeline_sink`` so the baseline
    truly has no sink — otherwise the scanner picks up the user's
    ``~/.lvdcp/config.yaml`` and adds a sink unasked.
    """
    project = tmp_path / "project"
    project.mkdir()
    _seed_project(project)

    # Baseline: timeline fully disabled.
    monkeypatch.setattr(scanner_mod, "_maybe_build_default_timeline_sink", lambda: None)
    baseline = _time_scan_min(project, sink=None, repeats=_REPEATS)

    # Instrumented: MemoryTimelineSink captures every event but writes no
    # disk — isolates the orchestration cost from SQLite fsync variance.
    sink = MemoryTimelineSink()
    with_timeline = _time_scan_min(project, sink=sink, repeats=_REPEATS)

    # Sanity: sink received at least one `on_scan_begin` call.
    assert sink.begins, "MemoryTimelineSink saw no scan — test setup broken"

    overhead = (with_timeline - baseline) / baseline
    # Leave a tiny floor so CI jitter on a 20 ms run doesn't flake the gate.
    # 10 ms + 10% is the actual budget.
    allowed = _OVERHEAD_BUDGET + (0.010 / baseline if baseline > 0 else 0.0)
    assert overhead <= allowed, (
        f"timeline overhead {overhead * 100:.1f}% exceeds "
        f"{allowed * 100:.1f}% budget "
        f"(baseline={baseline * 1000:.1f} ms, with_timeline={with_timeline * 1000:.1f} ms)"
    )
