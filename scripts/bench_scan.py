"""Measure cold-scan latency of a project and check against ADR-001."""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

from apps.cli.commands.scan import scan
from libs.core.paths import is_ignored, normalize_path

BUDGETS_SECONDS: dict[str, float] = {
    "initial_scan_500_files_p95": 20.0,
}


def main() -> int:
    """Benchmark cold scan performance."""
    if len(sys.argv) < 2:
        print("usage: python scripts/bench_scan.py <path>")
        return 2
    target = Path(sys.argv[1]).resolve()

    # Clear prior cache to measure cold path
    dot = target / ".context"
    if dot.exists():
        shutil.rmtree(dot)

    start = time.perf_counter()
    scan(target)
    elapsed = time.perf_counter() - start

    # Count files the scanner would have visited (approximate)
    file_count = 0
    for p in target.rglob("*"):
        if not p.is_file():
            continue
        try:
            rel = normalize_path(p, root=target)
        except ValueError:
            continue
        if not is_ignored(rel):
            file_count += 1

    print(f"scanned {file_count} files in {elapsed:.2f}s")

    if file_count >= 400:
        budget = BUDGETS_SECONDS["initial_scan_500_files_p95"]
        if elapsed > budget:
            print(f"BUDGET VIOLATION: {elapsed:.2f}s > {budget:.2f}s for ~500 files")
            return 1
        print(f"within budget ({budget}s for 500 files)")
    else:
        print(f"note: {file_count} files is below 500, budget not formally checked")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
