import json
from pathlib import Path

import pytest
from apps.cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


_SCAN_JSON_KEYS = {
    "path",
    "mode",
    "files_scanned",
    "files_reparsed",
    "stale_files_removed",
    "symbols_extracted",
    "relations_reparsed",
    "relations_cached",
    "elapsed_seconds",
    "wiki_dirty_count",
    "qdrant_warnings",
}


def test_scan_fixture_repo(sample_repo_path: Path, tmp_path: Path) -> None:
    # Copy-free: scan in-place, write artifacts to .context/ under sample_repo
    result = runner.invoke(app, ["scan", str(sample_repo_path)])
    assert result.exit_code == 0, result.output
    assert (sample_repo_path / ".context" / "project.md").exists()
    assert (sample_repo_path / ".context" / "symbol_index.md").exists()

    index_content = (sample_repo_path / ".context" / "symbol_index.md").read_text()
    assert "User" in index_content
    assert "login" in index_content


def test_scan_reports_counts(sample_repo_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(sample_repo_path)])
    assert result.exit_code == 0
    assert "files" in result.output.lower()
    assert "symbols" in result.output.lower()


def test_scan_populates_fts_index(sample_repo_path: Path) -> None:
    """After ctx scan, the FTS index at .context/fts.db must be populated."""
    result = runner.invoke(app, ["scan", str(sample_repo_path)])
    assert result.exit_code == 0
    fts_path = sample_repo_path / ".context" / "fts.db"
    assert fts_path.exists()

    from libs.retrieval.fts import FtsIndex

    fts = FtsIndex(fts_path)
    fts.create()
    # Must find content from our known fixture
    results = fts.search("refresh token", limit=5)
    assert any("auth" in path.lower() for path, _score in results)


def test_scan_output_contains_absolute_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "hello.py").write_text("def hi() -> None:\n    return None\n")
    from apps.cli.commands.scan import scan as scan_cmd

    scan_cmd(path=tmp_path, full=False)

    captured = capsys.readouterr()
    assert str(tmp_path.resolve()) in captured.out, captured.out


# ---- v0.8.42: ctx scan --json (scriptable scan results) -------------------


def test_scan_json_emits_well_formed_object(sample_repo_path: Path) -> None:
    """`scan --json` returns a parseable JSON object with the locked schema.

    Mirrors the v0.8.38 / v0.8.40 `--json` discipline: pure data, no human
    chrome, exact key set so scripts have a stable surface to bind against.
    """
    result = runner.invoke(app, ["scan", str(sample_repo_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == _SCAN_JSON_KEYS
    assert payload["path"] == str(sample_repo_path.resolve())
    assert payload["mode"] == "incremental"  # default; --full not passed
    assert payload["files_scanned"] >= 1  # sample repo has at least one file
    assert isinstance(payload["qdrant_warnings"], list)
    assert isinstance(payload["elapsed_seconds"], (int, float))
    assert payload["elapsed_seconds"] >= 0.0


def test_scan_json_suppresses_human_text_on_stdout(sample_repo_path: Path) -> None:
    """`--json` output is a pure JSON object — no `scanned N files` line.

    Discipline from v0.8.38 prune: scripts that pipe `scan --json | jq`
    fail confusingly if any non-JSON text leaks into stdout. The single
    JSON object must be the entire stdout content.
    """
    result = runner.invoke(app, ["scan", str(sample_repo_path), "--json"])

    assert result.exit_code == 0, result.output
    # `json.loads` on the entire stdout must succeed → confirms no text leak.
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    # Spot-check the human prose markers don't appear.
    assert "scanned " not in result.stdout
    assert "symbols" not in result.stdout.split('"symbols_extracted"')[0]


def test_scan_json_full_mode_echoes_full(sample_repo_path: Path) -> None:
    """`scan --full --json` reports `mode=full`, letting scripts assert intent.

    The `mode` field exists exactly so a script can defensively assert the
    run actually used the mode it asked for (e.g., a daily full-rescan
    that wraps `--full --json | jq -e '.mode == "full"'`).
    """
    result = runner.invoke(app, ["scan", str(sample_repo_path), "--full", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["mode"] == "full"


def test_scan_json_qdrant_warnings_is_empty_list_when_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Qdrant is disabled (default fixture), `qdrant_warnings` is `[]`, not `null`.

    Empty-list contract is the ergonomic choice for `jq` consumers —
    `payload.qdrant_warnings | length` works without a None-guard.
    """
    # Point DEFAULT_CONFIG_PATH at a non-existent file → load_config returns
    # defaults (qdrant.enabled=False) → no warnings collected.
    monkeypatch.setattr(
        "apps.cli.commands.scan.DEFAULT_CONFIG_PATH",
        tmp_path / "no_such_config.yaml",
    )
    (tmp_path / "hello.py").write_text("def hi() -> None:\n    return None\n")

    result = runner.invoke(app, ["scan", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["qdrant_warnings"] == []
    assert payload["qdrant_warnings"] is not None
