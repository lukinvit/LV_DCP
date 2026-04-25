"""Tests for the `ctx eval` CLI command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from apps.cli.main import app
from libs.scanning.scanner import scan_project
from typer.testing import CliRunner

# Schema lock for the JSON shape — mirrors the EvalReport dataclass plus
# the invocation-parameter round-trip fields. Any divergence forces an
# explicit, reviewed update to both the helper and this frozenset.
_EVAL_JSON_KEYS = frozenset(
    {"project", "queries_path", "impact_queries_path", "summary", "query_results"}
)
_EVAL_SUMMARY_KEYS = frozenset(
    {
        "recall_at_5_files",
        "precision_at_3_files",
        "recall_at_5_symbols",
        "mrr_files",
        "impact_recall_at_5",
    }
)
_EVAL_QUERY_RESULT_KEYS = frozenset(
    {
        "query_id",
        "mode",
        "retrieved_files",
        "retrieved_symbols",
        "expected_files",
        "expected_symbols",
    }
)


@pytest.fixture
def indexed_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "auth.py").write_text(
        "def login(email: str, password: str) -> None:\n    return None\n"
    )
    (tmp_path / "app" / "session.py").write_text("class Session: ...\n")
    scan_project(tmp_path, mode="full")
    return tmp_path


@pytest.fixture
def queries_file(tmp_path: Path) -> Path:
    path = tmp_path / "queries.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "queries": [
                    {
                        "id": "q01",
                        "text": "login endpoint",
                        "mode": "navigate",
                        "expected": {"files": ["app/auth.py"]},
                    },
                    {
                        "id": "q02",
                        "text": "session model",
                        "mode": "navigate",
                        "expected": {"files": ["app/session.py"]},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_eval_cmd_prints_markdown_report(indexed_project: Path, queries_file: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["eval", str(indexed_project), "--queries", str(queries_file)],
    )
    assert result.exit_code == 0, result.stdout
    assert "# Eval Report" in result.stdout
    assert "recall@5" in result.stdout
    assert "q01" in result.stdout


def test_eval_cmd_writes_output_file(
    indexed_project: Path, queries_file: Path, tmp_path: Path
) -> None:
    out = tmp_path / "report.md"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "eval",
            str(indexed_project),
            "--queries",
            str(queries_file),
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert out.exists()
    assert "# Eval Report" in out.read_text(encoding="utf-8")


def test_eval_cmd_rejects_unindexed_project(tmp_path: Path, queries_file: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["eval", str(plain), "--queries", str(queries_file)],
    )
    assert result.exit_code == 2
    # typer echoes err=True to stderr; accept either channel.
    stderr = result.stderr or ""
    assert "no cache" in stderr or "no cache" in result.stdout


def test_eval_cmd_rejects_unknown_baseline(indexed_project: Path, queries_file: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "eval",
            str(indexed_project),
            "--queries",
            str(queries_file),
            "--baseline",
            "cody",
        ],
    )
    assert result.exit_code == 2


def test_eval_cmd_aider_baseline_runs(indexed_project: Path, queries_file: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "eval",
            str(indexed_project),
            "--queries",
            str(queries_file),
            "--baseline",
            "aider",
        ],
    )
    # Even if the project is tiny, the comparison report should render.
    assert result.exit_code == 0, result.stdout
    assert "Eval Comparison" in result.stdout
    assert "Aider baseline" in result.stdout


def test_eval_cmd_text_output_unchanged(indexed_project: Path, queries_file: Path) -> None:
    """Default (no ``--json``) markdown mode must remain pure markdown — a
    future regression that promotes JSON to the default render would
    break this test instead of silently breaking shell consumers that
    pipe `ctx eval` to `pandoc` or another markdown processor."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["eval", str(indexed_project), "--queries", str(queries_file)],
    )
    assert result.exit_code == 0, result.stdout
    # Markdown header from the per-query report template is the canonical
    # text-mode signature.
    assert "# Eval Report" in result.stdout
    # Sanity: text mode must not leak JSON syntax.
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)


def test_eval_cmd_json_emits_well_formed_payload(indexed_project: Path, queries_file: Path) -> None:
    """``ctx eval ... --json`` emits a single object mirroring the
    EvalReport dataclass: top-level invocation parameters + summary
    (aggregate metrics) + query_results (per-query rows). All keys are
    schema-locked via the frozensets at module top."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["eval", str(indexed_project), "--queries", str(queries_file), "--json"],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)

    assert isinstance(payload, dict)
    assert set(payload.keys()) == _EVAL_JSON_KEYS

    # Round-tripped invocation parameters: project + queries_path are
    # absolute paths that confirm what this run actually evaluated;
    # impact_queries_path is null when --impact-queries was not passed.
    assert payload["project"] == str(indexed_project)
    assert payload["queries_path"] == str(queries_file)
    assert payload["impact_queries_path"] is None

    # Summary metrics: schema-locked exact key set; values are floats in
    # [0, 1] for all metrics (recall, precision, MRR are all bounded).
    summary = payload["summary"]
    assert isinstance(summary, dict)
    assert set(summary.keys()) == _EVAL_SUMMARY_KEYS
    for metric_name, value in summary.items():
        assert isinstance(value, float), f"{metric_name} must be float, got {type(value)}"
        assert 0.0 <= value <= 1.0, f"{metric_name}={value} out of [0, 1]"

    # Query results: one row per input query, schema-locked.
    query_results = payload["query_results"]
    assert isinstance(query_results, list)
    assert len(query_results) == 2  # q01 + q02 from the fixture
    for row in query_results:
        assert isinstance(row, dict)
        assert set(row.keys()) == _EVAL_QUERY_RESULT_KEYS
        assert isinstance(row["query_id"], str)
        assert row["mode"] in {"navigate", "edit"}  # impact mode allowed too
        assert isinstance(row["retrieved_files"], list)
        assert isinstance(row["retrieved_symbols"], list)
        assert isinstance(row["expected_files"], list)
        assert isinstance(row["expected_symbols"], list)

    # Order matches input file order (q01 before q02) — locks the
    # consumer-friendly invariant that per-query rows correlate across
    # runs by index without re-keying on query_id.
    assert query_results[0]["query_id"] == "q01"
    assert query_results[1]["query_id"] == "q02"


def test_eval_cmd_json_with_output_writes_json_to_file(
    indexed_project: Path, queries_file: Path, tmp_path: Path
) -> None:
    """With ``--json --output``, the file receives the JSON payload (not
    markdown) and stdout is empty (the 'wrote: ...' confirmation goes
    to stderr to keep stdout pure for redirect-then-read workflows)."""
    out = tmp_path / "report.json"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "eval",
            str(indexed_project),
            "--queries",
            str(queries_file),
            "--json",
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert set(payload.keys()) == _EVAL_JSON_KEYS
    assert payload["project"] == str(indexed_project)


def test_eval_cmd_json_with_baseline_rejects_combo(
    indexed_project: Path, queries_file: Path
) -> None:
    """``--json`` + ``--baseline`` is not yet supported (comparison-report
    JSON shape deserves its own ship). The combination must reject
    cleanly with exit 2 and a helpful error message — it must NOT emit
    a half-defined JSON payload that consumers might rely on before the
    comparison shape is finalized."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "eval",
            str(indexed_project),
            "--queries",
            str(queries_file),
            "--json",
            "--baseline",
            "aider",
        ],
    )
    assert result.exit_code == 2
    # typer echoes err=True to stderr; accept either channel for the
    # message but stdout must NOT contain a JSON payload.
    combined = result.output + (result.stderr or "")
    assert "--json" in combined
    assert "--baseline" in combined
    # Stdout (or merged via mix_stderr) must not parse as a success-shape
    # JSON object — the gate is exit code 2 + stderr message.
    if result.stdout.strip():
        try:
            parsed = json.loads(result.stdout)
            assert not (isinstance(parsed, dict) and "summary" in parsed)
        except json.JSONDecodeError:
            pass  # Expected — error path went to stderr, stdout is clean.
