"""Generate markdown reports for advisory real-project eval suites."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import date
from pathlib import Path

from tests.eval.real_project_eval import (
    RealProjectEvalReport,
    generate_real_project_report,
    skip_summary,
)
from tests.eval.run_multiproject_eval import run_multiproject_eval
from tests.eval.run_polyglot_eval import run_polyglot_eval


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "suite",
        choices=["multiproject", "polyglot"],
        help="Advisory eval suite to run.",
    )
    parser.add_argument(
        "tag",
        nargs="?",
        default="manual",
        help="Suffix used in the output markdown filename.",
    )
    return parser.parse_args()


def _output_path(suite: str, tag: str) -> Path:
    return Path("docs/eval") / f"{date.today().isoformat()}-{suite}-{tag}.md"


def _title_for_suite(suite: str) -> str:
    if suite == "polyglot":
        return "Polyglot Eval"
    return "Multi-project Eval"


def _runner_for_suite(suite: str) -> Callable[[], RealProjectEvalReport]:
    if suite == "polyglot":
        return run_polyglot_eval
    return run_multiproject_eval


def main() -> int:
    args = _parse_args()
    report = _runner_for_suite(args.suite)()
    output_path = _output_path(args.suite, args.tag)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        generate_real_project_report(report, title=_title_for_suite(args.suite)),
        encoding="utf-8",
    )

    print(f"Wrote {output_path}")
    print(f"Overall recall@5: {report.overall_recall:.3f}")
    if report.skipped_projects:
        print(f"Skipped: {skip_summary(report)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
