import json
from pathlib import Path

import pytest
from apps.cli.main import app
from typer.testing import CliRunner

runner = CliRunner()

# Schema lock for the JSON shape — mirrors the MCP `PackResult` contract.
# Any divergence here forces an explicit, reviewed update to both the
# helper, the MCP shape (`apps.mcp.tools.PackResult`), and this frozenset.
_PACK_JSON_KEYS = frozenset(
    {"markdown", "trace_id", "coverage", "retrieved_files", "retrieved_symbols"}
)
_VALID_COVERAGE_VALUES = frozenset({"high", "medium", "ambiguous"})


def test_pack_after_scan(sample_repo_path: Path) -> None:
    scan_result = runner.invoke(app, ["scan", str(sample_repo_path)])
    assert scan_result.exit_code == 0

    pack_result = runner.invoke(
        app,
        ["pack", str(sample_repo_path), "login endpoint", "--mode", "navigate"],
    )
    assert pack_result.exit_code == 0, pack_result.output
    assert "app/handlers/auth.py" in pack_result.output


def test_pack_edit_mode(sample_repo_path: Path) -> None:
    runner.invoke(app, ["scan", str(sample_repo_path)])
    result = runner.invoke(
        app,
        ["pack", str(sample_repo_path), "change login validation", "--mode", "edit"],
    )
    assert result.exit_code == 0
    assert "Target files" in result.output or "target" in result.output.lower()


def test_pack_exits_with_error_when_cache_missing(tmp_path: Path) -> None:
    """ctx pack on a never-scanned directory must fail cleanly."""
    (tmp_path / "hello.py").write_text("def hi():\n    pass\n")
    result = runner.invoke(app, ["pack", str(tmp_path), "hello"])
    assert result.exit_code != 0
    # Error message should tell the user to run scan first
    combined = result.output + (result.stderr or "")
    assert "scan" in combined.lower()


def test_pack_text_output_is_markdown_unchanged(sample_repo_path: Path) -> None:
    """Default (no ``--json``) text mode must remain pure markdown — the
    same string the MCP ``lvdcp_pack`` returns in its ``markdown`` field.
    A future regression that promotes JSON to the default render would
    break this test instead of silently breaking shell consumers."""
    runner.invoke(app, ["scan", str(sample_repo_path)])
    result = runner.invoke(
        app, ["pack", str(sample_repo_path), "login endpoint", "--mode", "navigate"]
    )
    assert result.exit_code == 0, result.output
    # Markdown header from the navigate-pack template is the canonical
    # text-mode signature.
    assert "Context pack" in result.output
    # Sanity: text mode must not leak JSON syntax.
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.output)


def test_pack_json_emits_well_formed_payload(sample_repo_path: Path) -> None:
    """``ctx pack ... --json`` emits a single object mirroring the MCP
    ``PackResult`` schema 1:1: ``markdown`` carries the same body the
    text view prints, ``trace_id`` is the retrieval trace ID,
    ``coverage`` is one of the three documented enum values, and the
    ranked file/symbol lists are arrays of strings."""
    runner.invoke(app, ["scan", str(sample_repo_path)])
    result = runner.invoke(
        app,
        [
            "pack",
            str(sample_repo_path),
            "login endpoint",
            "--mode",
            "navigate",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert isinstance(payload, dict)
    assert set(payload.keys()) == _PACK_JSON_KEYS
    assert isinstance(payload["markdown"], str)
    # Markdown body must carry the same template signature as the text
    # view — the JSON wrapper carries the body, it does not replace it.
    assert "Context pack" in payload["markdown"]
    assert isinstance(payload["trace_id"], str)
    # trace_id must be non-empty and look like a UUID/ULID-ish token.
    assert payload["trace_id"]
    assert payload["coverage"] in _VALID_COVERAGE_VALUES
    assert isinstance(payload["retrieved_files"], list)
    assert isinstance(payload["retrieved_symbols"], list)
    # The login endpoint query is expected to surface app/handlers/auth.py
    # via the existing fixture data — same expectation as the text-mode
    # smoke test above.
    assert any("auth" in f for f in payload["retrieved_files"])


def test_pack_json_edit_mode_emits_same_schema(sample_repo_path: Path) -> None:
    """Edit mode must emit the same JSON contract as navigate mode — the
    schema is render-mode-invariant, only the markdown body shape
    differs (target/tests/configs grouping vs. navigate ranking)."""
    runner.invoke(app, ["scan", str(sample_repo_path)])
    result = runner.invoke(
        app,
        [
            "pack",
            str(sample_repo_path),
            "change login validation",
            "--mode",
            "edit",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert isinstance(payload, dict)
    assert set(payload.keys()) == _PACK_JSON_KEYS
    # Edit-mode markdown surfaces the "Target files" header from the
    # edit-pack template — locks the body content against accidentally
    # routing edit mode through the navigate template.
    assert "Target files" in payload["markdown"] or "target" in payload["markdown"].lower()
    assert payload["coverage"] in _VALID_COVERAGE_VALUES


def test_pack_json_error_path_does_not_emit_stdout_payload(tmp_path: Path) -> None:
    """When the project is not indexed, ``--json`` mode does **not** swallow
    the error into a `{"error": "..."}` stdout payload. Same discipline as
    v0.8.42-v0.8.50: exit code is the script gate, stderr carries the
    human message, stdout is exclusively the success payload."""
    (tmp_path / "hello.py").write_text("def hi():\n    pass\n")
    result = runner.invoke(app, ["pack", str(tmp_path), "hello", "--json"])
    assert result.exit_code != 0
    # Stdout (or merged output via mix_stderr) must not parse as a JSON
    # success payload — the error path is identical in both modes.
    if result.output.strip():
        try:
            parsed = json.loads(result.output)
            # If something parses, it must NOT be the success-shape dict.
            assert not (isinstance(parsed, dict) and "markdown" in parsed)
        except json.JSONDecodeError:
            pass  # Expected — error went to stderr, stdout is empty/non-JSON.
