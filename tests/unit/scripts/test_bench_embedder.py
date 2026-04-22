"""Smoke test for scripts/bench_embedder.py (spec-001 US3 — T021)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "bench_embedder.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )


class TestBenchEmbedderSmoke:
    def test_script_file_exists(self) -> None:
        assert SCRIPT.exists(), "scripts/bench_embedder.py is missing"

    def test_json_output_schema_matches_contract(self) -> None:
        """CI workflows (T022) diff these keys — treat them as a contract."""
        result = _run(
            "--provider",
            "fake_bge_m3",
            "--n-chunks",
            "16",
            "--batch-size",
            "4",
            "--dimension",
            "32",
            "--output",
            "json",
        )
        assert result.returncode == 0, (
            f"bench exited non-zero: {result.returncode}\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        payload = json.loads(result.stdout)
        # Top-level keys the CI comparison relies on.
        for key in (
            "provider",
            "model_name",
            "device",
            "hybrid",
            "n_chunks",
            "batch_size",
            "n_batches",
            "total_seconds",
            "throughput_chunks_per_s",
            "latency_ms",
        ):
            assert key in payload, f"missing top-level key: {key}"
        # Percentile keys — p50/p95/p99 are the ADR-001 budget anchors.
        for lat_key in ("p50", "p95", "p99", "min", "max", "mean"):
            assert lat_key in payload["latency_ms"], (
                f"missing latency_ms.{lat_key}"
            )
        # Sanity: fake_bge_m3 is hybrid by construction.
        assert payload["hybrid"] is True
        assert payload["provider"] == "fake_bge_m3"
        assert payload["n_chunks"] == 16
        assert payload["batch_size"] == 4

    def test_text_output_mentions_latency_percentiles(self) -> None:
        result = _run(
            "--provider",
            "fake",
            "--n-chunks",
            "8",
            "--batch-size",
            "4",
            "--dimension",
            "32",
        )
        assert result.returncode == 0, result.stderr
        assert "p50=" in result.stdout
        assert "p95=" in result.stdout
        assert "p99=" in result.stdout
        assert "throughput :" in result.stdout
