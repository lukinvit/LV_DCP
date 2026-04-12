"""Regression test: code files must not be dominated by docs in top-5.

Reproduces the r04/r05 failure pattern from Phase 3c.2 failure analysis:
a project with docs files containing concentrated keywords pushes code
files out of top-5.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from libs.project_index.index import ProjectIndex
from libs.scanning.scanner import scan_project


@pytest.fixture()
def docs_heavy_repo(tmp_path: Path) -> Path:
    """Build a tiny repo with 1 code file + 3 docs files, all mentioning 'widget'."""
    code = tmp_path / "libs" / "widget.py"
    code.parent.mkdir(parents=True)
    code.write_text(textwrap.dedent("""\
        class Widget:
            def render(self) -> str:
                return "<widget/>"
    """))

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    for i in range(3):
        doc = docs_dir / f"spec-{i}.md"
        doc.write_text(
            f"# Widget Spec {i}\n\n"
            "The widget system handles widget rendering. "
            "Widget components are built by the widget factory. "
            "See widget docs for widget configuration.\n"
        )

    (tmp_path / ".context").mkdir(exist_ok=True)

    return tmp_path


def test_code_file_in_top3_despite_docs_keyword_density(docs_heavy_repo: Path) -> None:
    scan_project(docs_heavy_repo, mode="full")
    idx = ProjectIndex.open(docs_heavy_repo)
    try:
        result = idx.retrieve("widget rendering", mode="navigate", limit=5)
        top3 = result.files[:3]
        assert "libs/widget.py" in top3, (
            f"Code file should be in top-3 but got: {top3}. "
            f"Full top-5: {result.files}"
        )
    finally:
        idx.close()


def test_edit_mode_also_prefers_code(docs_heavy_repo: Path) -> None:
    scan_project(docs_heavy_repo, mode="full")
    idx = ProjectIndex.open(docs_heavy_repo)
    try:
        result = idx.retrieve("fix widget rendering bug", mode="edit", limit=5)
        top3 = result.files[:3]
        assert "libs/widget.py" in top3, (
            f"Code file should be in top-3 for edit but got: {top3}. "
            f"Full top-5: {result.files}"
        )
    finally:
        idx.close()
