"""Phase 2 dogfood: ctx scan LV_DCP itself and verify artifacts include phase 2 modules."""

from pathlib import Path

from apps.cli.main import app
from typer.testing import CliRunner

from tests.eval.retrieval_adapter import retrieve_for_eval
from tests.eval.run_eval import FIXTURE_REPO, load_impact_queries

runner = CliRunner()


def test_lv_dcp_self_scan_contains_phase2_modules(project_root: Path) -> None:
    result = runner.invoke(app, ["scan", str(project_root)])
    assert result.exit_code == 0, result.output

    dot = project_root / ".context"
    assert (dot / "project.md").exists()
    assert (dot / "symbol_index.md").exists()

    idx = (dot / "symbol_index.md").read_text()
    # Phase 2 additions must be visible in the symbol index
    phase2_evidence = [
        "libs/retrieval/graph_expansion",
        "libs.retrieval.graph_expansion",
        "libs/project_index",
        "libs.project_index",
        "apps/mcp",
        "apps.mcp",
        "apps/agent",
        "apps.agent",
    ]
    assert any(p in idx for p in phase2_evidence), (
        "symbol index does not mention any Phase 2 module"
    )


def test_impact_queries_surface_graph_reachable_files() -> None:
    """On the fixture repo, impact queries must find files reachable via graph walk."""
    queries = load_impact_queries()
    hits = 0
    for q in queries:
        retrieved_files, _symbols = retrieve_for_eval(q["text"], q["mode"], FIXTURE_REPO)
        expected = q["expected"].get("files", [])
        if any(f in retrieved_files[:5] for f in expected):
            hits += 1
    recall = hits / len(queries) if queries else 0.0
    assert recall >= 0.75, f"impact recall {recall:.2%} below 0.75 threshold"
