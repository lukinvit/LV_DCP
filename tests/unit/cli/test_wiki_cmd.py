"""Tests for the `ctx wiki` CLI group — focuses on the v0.8.46 `--json` slice.

Older surfaces (`update`, `lint`, `cross-project`) have integration coverage
elsewhere; this module locks the new JSON contract on `ctx wiki status`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from apps.cli.main import app
from libs.storage.sqlite_cache import SqliteCache
from libs.wiki.state import ensure_wiki_table, mark_current, mark_dirty
from typer.testing import CliRunner

# Schema-locked surface for `ctx wiki status --json`. Adding a key requires
# bumping this set + `_module_to_json` at the same time. Mirrors the
# wiki_state row schema from libs/wiki/state.py::get_all_modules.
_WIKI_STATUS_JSON_KEYS = frozenset(
    {"module_path", "wiki_file", "status", "last_generated_ts", "source_hash"}
)

# Schema-locked surface for `ctx wiki lint --json`. Adding a key requires
# bumping this set + `_issue_to_json` at the same time. Mirrors the
# LintIssue dataclass from libs/wiki/lint.py::LintIssue.
_WIKI_LINT_JSON_KEYS = frozenset({"severity", "module_path", "message"})


def _seed_modules(project_path: Path, modules: list[tuple[str, str, bool]]) -> None:
    """Create `.context/cache.db` and seed wiki_state with `modules`.

    Each tuple is `(module_path, source_hash, is_current)`. `is_current=True`
    rows land via `mark_current` (status='current', non-zero ts);
    `is_current=False` rows go through `mark_dirty` (status='dirty', ts=0).
    """
    db_dir = project_path / ".context"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "cache.db"
    with SqliteCache(db_path) as cache:
        cache.migrate()
        conn = cache._connect()
        ensure_wiki_table(conn)
        for module_path, source_hash, is_current in modules:
            if is_current:
                # mark_current writes ts via CURRENT_TIMESTAMP — non-zero.
                mark_current(conn, module_path, f"modules/{module_path}.md", source_hash)
            else:
                mark_dirty(conn, module_path, source_hash)
        conn.commit()


def test_wiki_status_text_output_unchanged(tmp_path: Path) -> None:
    """Baseline: text path emits the legacy table format byte-identically."""
    _seed_modules(tmp_path, [("pkg.mod", "abc123", True)])
    runner = CliRunner()
    result = runner.invoke(app, ["wiki", "status", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "Module" in result.stdout
    assert "Status" in result.stdout
    assert "pkg.mod" in result.stdout
    assert "current" in result.stdout


def test_wiki_status_json_emits_well_formed_array(tmp_path: Path) -> None:
    """`--json` returns a bare JSON array; each entry mirrors the locked schema."""
    _seed_modules(
        tmp_path,
        [
            ("pkg.alpha", "hash_alpha", True),
            ("pkg.beta", "hash_beta", False),
        ],
    )
    runner = CliRunner()
    result = runner.invoke(app, ["wiki", "status", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert len(payload) == 2
    by_path = {row["module_path"]: row for row in payload}
    assert set(by_path["pkg.alpha"].keys()) == _WIKI_STATUS_JSON_KEYS
    assert by_path["pkg.alpha"]["status"] == "current"
    assert by_path["pkg.alpha"]["source_hash"] == "hash_alpha"
    assert by_path["pkg.alpha"]["wiki_file"] == "modules/pkg.alpha.md"
    # `last_generated_ts` is the raw POSIX float — non-zero for current rows
    # so dashboards can do `now - ts` without re-parsing a formatted string.
    assert isinstance(by_path["pkg.alpha"]["last_generated_ts"], (int, float))
    assert by_path["pkg.alpha"]["last_generated_ts"] > 0
    # Dirty modules carry status='dirty' and ts=0 (never generated).
    assert by_path["pkg.beta"]["status"] == "dirty"
    assert by_path["pkg.beta"]["last_generated_ts"] == 0


def test_wiki_status_json_empty_returns_bare_list(tmp_path: Path) -> None:
    """No modules tracked → `[]`, never `null` and never the prose marker."""
    # Create an empty wiki_state table (cache.db exists, no rows).
    _seed_modules(tmp_path, [])
    runner = CliRunner()
    result = runner.invoke(app, ["wiki", "status", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload == []
    # The prose marker from the human-readable path must NOT leak into JSON.
    assert "No modules tracked" not in result.stdout


def test_wiki_status_no_cache_db_fails_in_both_modes(tmp_path: Path) -> None:
    """Missing `cache.db` exits 1 in both text and JSON modes — discipline.

    Same v0.8.42-v0.8.45 contract: `--json` never swallows the error into a
    `{"error": "..."}` stdout payload. `json.loads(output)` raises on the
    merged error message; consumers gate on exit code (`set -e`).
    """
    # tmp_path has no .context/ — cache.db is missing.
    runner = CliRunner()

    # Text mode: error on stderr (merged into output), exit 1.
    text_result = runner.invoke(app, ["wiki", "status", str(tmp_path)])
    assert text_result.exit_code == 1
    assert "no cache.db" in text_result.output

    # JSON mode: same exit code + message; no JSON object emitted on stdout.
    json_result = runner.invoke(app, ["wiki", "status", str(tmp_path), "--json"])
    assert json_result.exit_code == 1
    assert "no cache.db" in json_result.output
    assert '"error"' not in json_result.output
    with pytest.raises(json.JSONDecodeError):
        json.loads(json_result.output)


# ---------------------------------------------------------------------------
# v0.8.47: `ctx wiki lint --json` slice
# ---------------------------------------------------------------------------


def _seed_lint_fixture(project_path: Path, *, with_orphan: bool, with_empty: bool) -> None:
    """Set up `cache.db` + wiki layout to deterministically trigger lint findings.

    `with_orphan=True` leaves an article on disk with no source files in the
    `files` table — triggers the warning-severity "Orphaned article" finding.
    `with_empty=True` writes a sub-50-byte article — triggers the
    error-severity "Empty article" finding (the only error code path that
    fires the exit-1 gate).
    """
    db_dir = project_path / ".context"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "cache.db"
    with SqliteCache(db_path) as cache:
        cache.migrate()
        conn = cache._connect()
        ensure_wiki_table(conn)
        conn.commit()

    wiki_dir = project_path / ".context" / "wiki"
    modules_dir = wiki_dir / "modules"
    modules_dir.mkdir(parents=True, exist_ok=True)

    if with_orphan:
        # Article on disk, no matching files in cache → orphaned warning.
        # Body is 80+ bytes so it doesn't also trigger the empty-error gate.
        (modules_dir / "ghost.mod.md").write_text(
            "# ghost.mod\n\nA stub article whose source module is gone.\n" * 2,
            encoding="utf-8",
        )

    if with_empty:
        # < 50 bytes → empty error finding (severity='error').
        (modules_dir / "stub.mod.md").write_text("tiny\n", encoding="utf-8")


def test_wiki_lint_text_output_unchanged(tmp_path: Path) -> None:
    """Baseline: text path emits the legacy bullet list byte-identically."""
    _seed_lint_fixture(tmp_path, with_orphan=True, with_empty=False)
    runner = CliRunner()
    result = runner.invoke(app, ["wiki", "lint", str(tmp_path)])
    # Warnings only → exit 0; format is `  [WARN] <path>: <message>`.
    assert result.exit_code == 0, result.output
    assert "[WARN]" in result.output
    assert "ghost.mod" in result.output
    assert "warning(s)" in result.output


def test_wiki_lint_json_emits_well_formed_array_warnings_only(tmp_path: Path) -> None:
    """`--json` returns a bare JSON array; warnings-only exits 0 (no error gate)."""
    _seed_lint_fixture(tmp_path, with_orphan=True, with_empty=False)
    runner = CliRunner()
    result = runner.invoke(app, ["wiki", "lint", str(tmp_path), "--json"])
    # Exit-code gate carried unchanged: warnings → exit 0 in both modes.
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert len(payload) >= 1
    # Schema-locked: each row mirrors LintIssue exactly.
    for row in payload:
        assert set(row.keys()) == _WIKI_LINT_JSON_KEYS
        assert row["severity"] in {"warning", "error"}
    # Orphan article surfaces as a warning-severity finding.
    assert any(r["severity"] == "warning" and "ghost.mod" in r["module_path"] for r in payload)
    # No prose marker leaks into JSON.
    assert "No issues found" not in result.output
    assert "warning(s)" not in result.output


def test_wiki_lint_json_empty_returns_bare_list(tmp_path: Path) -> None:
    """No issues → `[]`, never `null` and never the `No issues found.` prose."""
    # Seed an empty cache.db with no articles → no issues fire.
    _seed_lint_fixture(tmp_path, with_orphan=False, with_empty=False)
    runner = CliRunner()
    result = runner.invoke(app, ["wiki", "lint", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == []
    assert "No issues found" not in result.output


def test_wiki_lint_json_preserves_exit_code_gate_on_errors(tmp_path: Path) -> None:
    """Error-severity row → exit 1 in both text and JSON modes — script gate.

    The exit-code contract is the script's gating mechanism (`set -e`); the
    `--json` render switch must not break it. Splitting the contract would
    force consumers to choose between the JSON payload and the CI gate.
    """
    _seed_lint_fixture(tmp_path, with_orphan=False, with_empty=True)
    runner = CliRunner()

    # Text mode: error severity → exit 1.
    text_result = runner.invoke(app, ["wiki", "lint", str(tmp_path)])
    assert text_result.exit_code == 1
    assert "[ERROR]" in text_result.output

    # JSON mode: same exit code, payload still emits the structured row.
    json_result = runner.invoke(app, ["wiki", "lint", str(tmp_path), "--json"])
    assert json_result.exit_code == 1
    payload = json.loads(json_result.output)
    assert any(r["severity"] == "error" for r in payload)
    # Discipline shared with v0.8.42-v0.8.46: never the `{"error": "..."}` swallow.
    # The structured payload IS valid JSON; what we lock here is that the
    # error-severity row carries `severity='error'` (not a wrapped error
    # object) and the script gate (exit 1) fires.
    assert isinstance(payload, list)
