import json
from itertools import pairwise
from pathlib import Path

from apps.cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


_INSPECT_JSON_KEYS = {
    "path",
    "files",
    "language_counts",
    "symbols",
    "symbol_type_counts",
    "relations",
    "relation_type_counts",
}


def test_inspect_reports_stats(sample_repo_path: Path) -> None:
    runner.invoke(app, ["scan", str(sample_repo_path)])
    result = runner.invoke(app, ["inspect", str(sample_repo_path)])
    assert result.exit_code == 0
    assert "files" in result.output.lower()
    assert "symbols" in result.output.lower()
    assert "relations" in result.output.lower()


# ---- v0.8.43: ctx inspect --json (scriptable index stats) ------------------


def test_inspect_json_emits_well_formed_object(sample_repo_path: Path) -> None:
    """`inspect --json` returns a parseable JSON object with the locked schema.

    Mirrors the v0.8.38 / v0.8.40 / v0.8.42 `--json` discipline: pure data,
    no human chrome, exact key set so scripts have a stable surface to bind
    against. Existing text output unaffected.
    """
    runner.invoke(app, ["scan", str(sample_repo_path)])
    result = runner.invoke(app, ["inspect", str(sample_repo_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == _INSPECT_JSON_KEYS
    assert payload["path"] == str(sample_repo_path.resolve())
    assert isinstance(payload["files"], int)
    assert payload["files"] >= 1  # sample repo has at least one file
    assert isinstance(payload["language_counts"], dict)
    assert isinstance(payload["symbols"], int)
    assert isinstance(payload["symbol_type_counts"], dict)
    assert isinstance(payload["relations"], int)
    assert isinstance(payload["relation_type_counts"], dict)


def test_inspect_json_suppresses_human_text_on_stdout(sample_repo_path: Path) -> None:
    """`--json` output is a pure JSON object — no `project: ...` line.

    Scripts that pipe `inspect --json | jq` fail confusingly if any non-JSON
    text leaks into stdout. The single JSON object must be the entire stdout
    content, even when structlog (or any other library logger) fires during
    the index open / iter — same guarantee v0.8.42 locked for `scan --json`.
    """
    runner.invoke(app, ["scan", str(sample_repo_path)])
    result = runner.invoke(app, ["inspect", str(sample_repo_path), "--json"])

    assert result.exit_code == 0, result.output
    # `json.loads` on the entire stdout must succeed → confirms no text leak.
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    # Spot-check the human prose markers don't appear.
    assert "project: " not in result.stdout
    # `files: N` text-mode prefix should not appear; the JSON key uses quoted form.
    assert '"files":' in result.stdout


def test_inspect_json_counts_are_descending_ordered_dicts(
    sample_repo_path: Path,
) -> None:
    """`*_counts` dicts preserve insertion order = descending by count.

    Scripts that want the most-frequent language / symbol type / relation type
    can do `jq '.language_counts | to_entries[0].key'` without an explicit
    sort — same ordering semantics as the human text view's `most_common()`.
    Locks the contract so a future refactor that drops the `most_common()` call
    breaks this test instead of silently reshuffling consumer dashboards.
    """
    runner.invoke(app, ["scan", str(sample_repo_path)])
    result = runner.invoke(app, ["inspect", str(sample_repo_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)

    for key in ("language_counts", "symbol_type_counts", "relation_type_counts"):
        counts = payload[key]
        if len(counts) <= 1:
            continue  # trivially ordered
        values = list(counts.values())
        # Each value must be ≥ the next — strictly non-increasing.
        for prev, nxt in pairwise(values):
            assert prev >= nxt, f"{key} not in descending order: {counts}; prev={prev} nxt={nxt}"


def test_inspect_not_indexed_error_goes_to_stderr_with_exit_1(tmp_path: Path) -> None:
    """An un-scanned project surfaces the error on stderr, exits 1, in BOTH modes.

    Discipline: `--json` does NOT swallow the error into stdout JSON
    (`{"error": "..."}`). Scripts gate on exit code (`set -e`) and read the
    error message from stderr. Splitting the contract — sometimes JSON,
    sometimes prose, both on stdout — would force every consumer to
    parse-then-check-keys and defeats the point of the JSON gate.
    """
    # Plain mode → stderr error, exit 1, empty stdout.
    result = runner.invoke(app, ["inspect", str(tmp_path)])
    assert result.exit_code == 1
    assert result.stdout == ""  # error is on stderr, nothing on stdout
    assert "not indexed" in result.stderr.lower() or len(result.stderr) > 0

    # JSON mode → identical contract: stderr error, exit 1, empty stdout.
    result_json = runner.invoke(app, ["inspect", str(tmp_path), "--json"])
    assert result_json.exit_code == 1
    assert result_json.stdout == ""  # no `{"error": ...}` leak into stdout
