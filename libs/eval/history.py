"""Eval run history: atomic save/load + cross-run diff (see specs/006, T016).

The on-disk format is JSON because eval runs cross language boundaries —
promptfoo (JS) reads the same artifacts. Atomic save uses tmp + rename so
crashed writes never leave a partial file on disk.

``compare`` returns a :class:`DiffReport` with aggregate deltas plus a list
of per-metric comparisons; the CLI (T018) pretty-prints it. Missing or
newly-added ragas sections are handled gracefully — a run that predates
US1 compares cleanly against a post-US1 run.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from libs.eval.ragas_adapter import RagasMetrics, RagasPerQuery
from libs.eval.runner import EvalReport, QueryResult

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MetricDelta:
    """One metric's before/after/delta triple.

    ``before`` and ``after`` are optional because RAGAS metrics may be
    absent in one report but present in the other.
    """

    name: str
    before: float | None
    after: float | None

    @property
    def delta(self) -> float | None:
        if self.before is None or self.after is None:
            return None
        return self.after - self.before


@dataclass(frozen=True)
class DiffReport:
    """Pair of reports plus per-metric diffs.

    Per-query diffs are intentionally out of scope here — the per-query
    table is already in the Markdown report; ``DiffReport`` focuses on
    the aggregates that drive go/no-go decisions.
    """

    deltas: list[MetricDelta]
    a_label: str = "before"
    b_label: str = "after"


def save_run(report: EvalReport, out_dir: Path, *, filename: str | None = None) -> Path:
    """Serialize *report* to ``out_dir`` atomically.

    If *filename* is omitted, one is derived from the current UTC timestamp.
    Returns the final path. The write is atomic via tmp + ``os.replace``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    name = filename or datetime.now(tz=UTC).strftime("%Y-%m-%dT%H-%M-%SZ") + ".json"
    target = out_dir / name

    payload = _report_to_dict(report)
    data = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)

    fd, tmp_path = tempfile.mkstemp(
        prefix=".tmp-eval-", suffix=".json", dir=str(out_dir)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        Path(tmp_path).replace(target)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise
    return target


def load_run(path: Path) -> EvalReport:
    """Load a previously saved EvalReport."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _report_from_dict(payload)


def latest_runs(out_dir: Path, *, limit: int = 10) -> list[Path]:
    """Return the most recent ``*.json`` runs in *out_dir*, newest first.

    Sorted by mtime; ``.tmp-*`` files (in-flight writes) are skipped.
    Missing directory returns an empty list.
    """
    if not out_dir.is_dir():
        return []
    runs = [
        p
        for p in out_dir.glob("*.json")
        if p.is_file() and not p.name.startswith(".tmp-")
    ]
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return runs[:limit]


def compare(a: EvalReport, b: EvalReport, *, a_label: str = "before", b_label: str = "after") -> DiffReport:
    """Per-metric diff between two reports.

    IR metrics are always present; RAGAS fields may be None in either report,
    which :class:`MetricDelta` handles via an optional ``delta`` property.
    """
    pairs: list[tuple[str, float | None, float | None]] = [
        ("recall_at_5_files", a.recall_at_5_files, b.recall_at_5_files),
        ("precision_at_3_files", a.precision_at_3_files, b.precision_at_3_files),
        ("recall_at_5_symbols", a.recall_at_5_symbols, b.recall_at_5_symbols),
        ("mrr_files", a.mrr_files, b.mrr_files),
        ("impact_recall_at_5", a.impact_recall_at_5, b.impact_recall_at_5),
    ]
    if a.ragas is not None or b.ragas is not None:
        a_r = a.ragas
        b_r = b.ragas
        pairs.extend(
            [
                (
                    "ragas.context_precision",
                    a_r.context_precision if a_r else None,
                    b_r.context_precision if b_r else None,
                ),
                (
                    "ragas.context_recall",
                    a_r.context_recall if a_r else None,
                    b_r.context_recall if b_r else None,
                ),
                (
                    "ragas.faithfulness",
                    a_r.faithfulness if a_r else None,
                    b_r.faithfulness if b_r else None,
                ),
            ]
        )

    deltas = [MetricDelta(name=name, before=before, after=after) for name, before, after in pairs]
    return DiffReport(deltas=deltas, a_label=a_label, b_label=b_label)


def _report_to_dict(report: EvalReport) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "recall_at_5_files": report.recall_at_5_files,
        "precision_at_3_files": report.precision_at_3_files,
        "recall_at_5_symbols": report.recall_at_5_symbols,
        "mrr_files": report.mrr_files,
        "impact_recall_at_5": report.impact_recall_at_5,
        "query_results": [asdict(qr) for qr in report.query_results],
        "ragas": asdict(report.ragas) if report.ragas is not None else None,
    }


def _report_from_dict(data: dict[str, Any]) -> EvalReport:
    version = data.get("schema_version")
    if version not in (None, SCHEMA_VERSION):
        raise ValueError(f"unsupported eval snapshot schema_version={version!r}")

    query_results = [QueryResult(**qr) for qr in data.get("query_results", [])]
    ragas_payload = data.get("ragas")
    ragas: RagasMetrics | None = None
    if ragas_payload is not None:
        ragas = RagasMetrics(
            context_precision=ragas_payload.get("context_precision"),
            context_recall=ragas_payload.get("context_recall"),
            faithfulness=ragas_payload.get("faithfulness"),
            per_query=[
                RagasPerQuery(**pq) for pq in ragas_payload.get("per_query", [])
            ],
            cache_hits=int(ragas_payload.get("cache_hits", 0)),
            cache_misses=int(ragas_payload.get("cache_misses", 0)),
        )

    return EvalReport(
        query_results=query_results,
        recall_at_5_files=float(data["recall_at_5_files"]),
        precision_at_3_files=float(data["precision_at_3_files"]),
        recall_at_5_symbols=float(data["recall_at_5_symbols"]),
        mrr_files=float(data["mrr_files"]),
        impact_recall_at_5=float(data["impact_recall_at_5"]),
        ragas=ragas,
    )
