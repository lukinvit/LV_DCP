"""Unit tests for libs/eval/history (see specs/006, T017)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from libs.eval.history import (
    SCHEMA_VERSION,
    DiffReport,
    MetricDelta,
    compare,
    latest_runs,
    load_run,
    save_run,
)
from libs.eval.ragas_adapter import RagasMetrics, RagasPerQuery
from libs.eval.runner import EvalReport, QueryResult


def _make_report(
    *, ragas: RagasMetrics | None = None, recall: float = 0.75
) -> EvalReport:
    return EvalReport(
        query_results=[
            QueryResult(
                query_id="q01",
                mode="navigate",
                retrieved_files=["app/models/user.py"],
                retrieved_symbols=["app.models.user.User"],
                expected_files=["app/models/user.py"],
                expected_symbols=["app.models.user.User"],
            ),
        ],
        recall_at_5_files=recall,
        precision_at_3_files=0.5,
        recall_at_5_symbols=1.0,
        mrr_files=0.8,
        impact_recall_at_5=0.0,
        ragas=ragas,
    )


def _make_ragas(cp: float = 0.8, cr: float = 0.7, f: float = 0.9) -> RagasMetrics:
    return RagasMetrics(
        context_precision=cp,
        context_recall=cr,
        faithfulness=f,
        per_query=[
            RagasPerQuery(
                query_id="q01",
                context_precision=cp,
                context_recall=cr,
                faithfulness=f,
            )
        ],
        cache_hits=0,
        cache_misses=3,
    )


def test_save_run_creates_directory(tmp_path: Path) -> None:
    out = tmp_path / "runs"
    path = save_run(_make_report(), out)
    assert path.exists()
    assert path.parent == out
    assert path.suffix == ".json"


def test_save_run_uses_atomic_write(tmp_path: Path) -> None:
    path = save_run(_make_report(), tmp_path, filename="r.json")
    # No stray tmp files should remain in the directory.
    tmp_leftover = list(tmp_path.glob(".tmp-*"))
    assert tmp_leftover == []
    # The real file is present and valid JSON.
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == SCHEMA_VERSION


def test_save_load_roundtrip_without_ragas(tmp_path: Path) -> None:
    original = _make_report()
    path = save_run(original, tmp_path, filename="r.json")
    loaded = load_run(path)
    assert loaded.recall_at_5_files == original.recall_at_5_files
    assert loaded.mrr_files == original.mrr_files
    assert loaded.ragas is None
    assert loaded.query_results[0].query_id == "q01"


def test_save_load_roundtrip_with_ragas(tmp_path: Path) -> None:
    original = _make_report(ragas=_make_ragas())
    path = save_run(original, tmp_path, filename="r.json")
    loaded = load_run(path)
    assert loaded.ragas is not None
    assert loaded.ragas.context_precision == 0.8
    assert loaded.ragas.per_query[0].query_id == "q01"
    assert loaded.ragas.cache_misses == 3


def test_load_run_rejects_unknown_schema_version(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "schema_version": 999,
                "recall_at_5_files": 0.0,
                "precision_at_3_files": 0.0,
                "recall_at_5_symbols": 0.0,
                "mrr_files": 0.0,
                "impact_recall_at_5": 0.0,
                "query_results": [],
                "ragas": None,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="schema_version"):
        load_run(bad)


def test_latest_runs_sorted_newest_first(tmp_path: Path) -> None:
    first = save_run(_make_report(), tmp_path, filename="a.json")
    time.sleep(0.01)  # Ensure mtime differs on fast filesystems.
    second = save_run(_make_report(), tmp_path, filename="b.json")

    latest = latest_runs(tmp_path, limit=10)
    assert latest == [second, first]


def test_latest_runs_respects_limit(tmp_path: Path) -> None:
    for i in range(5):
        save_run(_make_report(), tmp_path, filename=f"r{i}.json")
        time.sleep(0.005)
    assert len(latest_runs(tmp_path, limit=3)) == 3


def test_latest_runs_empty_dir(tmp_path: Path) -> None:
    assert latest_runs(tmp_path / "missing") == []
    assert latest_runs(tmp_path) == []


def test_latest_runs_skips_tmp_files(tmp_path: Path) -> None:
    (tmp_path / ".tmp-inflight.json").write_text("{}", encoding="utf-8")
    saved = save_run(_make_report(), tmp_path, filename="real.json")
    assert latest_runs(tmp_path) == [saved]


def test_compare_ir_only_produces_deltas() -> None:
    a = _make_report(recall=0.70)
    b = _make_report(recall=0.75)
    diff = compare(a, b)
    by_name = {d.name: d for d in diff.deltas}
    assert by_name["recall_at_5_files"].before == pytest.approx(0.70)
    assert by_name["recall_at_5_files"].after == pytest.approx(0.75)
    assert by_name["recall_at_5_files"].delta == pytest.approx(0.05)


def test_compare_adds_ragas_deltas_when_either_side_has_ragas() -> None:
    a = _make_report()
    b = _make_report(ragas=_make_ragas())
    diff = compare(a, b)
    names = {d.name for d in diff.deltas}
    assert "ragas.context_precision" in names
    cp = next(d for d in diff.deltas if d.name == "ragas.context_precision")
    assert cp.before is None
    assert cp.after == pytest.approx(0.8)
    assert cp.delta is None  # None before → delta undefined.


def test_compare_keeps_labels() -> None:
    a = _make_report()
    b = _make_report()
    diff = compare(a, b, a_label="main", b_label="feature")
    assert isinstance(diff, DiffReport)
    assert diff.a_label == "main"
    assert diff.b_label == "feature"


def test_metric_delta_handles_nones() -> None:
    d_both_none = MetricDelta(name="x", before=None, after=None)
    assert d_both_none.delta is None
    d_ok = MetricDelta(name="x", before=0.5, after=0.6)
    assert d_ok.delta == pytest.approx(0.1)
