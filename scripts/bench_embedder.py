"""Micro-benchmark for the bge-m3 embedding pipeline (spec-001 US3 — T021).

Generates a synthetic corpus, pushes it through the configured adapter in
batches, and reports p50/p95/p99 per-batch latency plus overall throughput
(chunks / second). Supports ``fake``, ``fake_bge_m3``, and the real
``bge_m3`` provider (the latter requires the optional ``[bge-m3]`` extras
and downloads ~2.3 GB of weights on first run).

Examples:

    uv run python scripts/bench_embedder.py \\
        --provider fake_bge_m3 --n-chunks 200 --batch-size 32 --output json

    uv run python scripts/bench_embedder.py \\
        --provider bge_m3 --n-chunks 500 --device auto --output json \\
        > bench-output.json

Exit status is always 0 unless the script crashes. Per spec §US3 / SC-002
the CPU-fallback path emits a ``WARN`` line on stderr when p95 exceeds
``BGE_M3_P95_BATCH_32_MS * CPU_MULTIPLIER``, but does not fail — CI
pipelines gate on the JSON artefact via a dedicated comparison step
(``T022 bench-embedder.yml``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from typing import Any

from libs.core.projects_config import EmbeddingConfig
from libs.embeddings.adapter import EmbeddingAdapter, MultiVectorEmbeddingAdapter
from libs.embeddings.service import _build_adapter, _is_multi_vector

# Latency SLO anchors for spec-001 SC-002. The absolute number here is
# a placeholder — tuned from the real-model first-run once the
# ``[bge-m3]`` extras are available in the CI image.
BGE_M3_P95_BATCH_32_MS = 400.0
CPU_MULTIPLIER = 3.0

_CORPUS_FRAGMENTS = (
    "Batch scheduler drains the pending queue every reconcile tick.",
    "Vector store upserts reuse the cached client session across projects.",
    "Fallback renderer paints a degraded layout when the theme pack fails.",
    "Observer hook records span attributes at the outbound boundary.",
    "Routing table rebuilds on a reload signal from the control plane.",
    "Snapshot uploader seals directories before handing off to storage.",
    "Pipeline warms secondary indexes after the primary write commits.",
    "Policy engine evaluates egress rules before a connection is dialled.",
    "Cache eviction drains least recently used keys when memory tightens.",
    "Health probe aggregates readiness across all managed processes.",
    "Scheduler reschedules the task after the back-pressure window lifts.",
    "Telemetry batcher flushes samples once the in-flight buffer fills.",
    "Audit log anchor pins every mutation to an append-only event stream.",
    "Tenant registry entry carries the billing profile and quota limits.",
    "Signing daemon verifies canary headers before the deletion lands.",
)


def _synthesize_corpus(n: int, *, seed: int = 42) -> list[str]:
    """Deterministic corpus of ``n`` short documents for stable benching."""
    rng = random.Random(seed)  # noqa: S311 — deterministic bench corpus, no crypto use
    out: list[str] = []
    for i in range(n):
        base = _CORPUS_FRAGMENTS[rng.randrange(len(_CORPUS_FRAGMENTS))]
        out.append(f"doc_{i:05d} {base}")
    return out


def _percentile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank percentile; ``q`` in [0, 1]."""
    if not sorted_values:
        return 0.0
    idx = max(0, min(len(sorted_values) - 1, int(q * len(sorted_values))))
    return sorted_values[idx]


async def _bench_adapter(
    adapter: EmbeddingAdapter,
    corpus: list[str],
    batch_size: int,
) -> dict[str, Any]:
    hybrid = _is_multi_vector(adapter)
    batch_latencies_ms: list[float] = []

    total_start = time.perf_counter()
    for i in range(0, len(corpus), batch_size):
        batch = corpus[i : i + batch_size]
        t0 = time.perf_counter()
        if hybrid:
            mv: MultiVectorEmbeddingAdapter = adapter  # type: ignore[assignment]
            await mv.embed_batch_multi(batch, dense=True, sparse=True, colbert=False)
        else:
            await adapter.embed_batch(batch)
        batch_latencies_ms.append((time.perf_counter() - t0) * 1000.0)
    total_elapsed_s = time.perf_counter() - total_start

    sorted_l = sorted(batch_latencies_ms)
    throughput = (
        round(len(corpus) / total_elapsed_s, 2) if total_elapsed_s > 0 else 0.0
    )
    return {
        "hybrid": hybrid,
        "n_chunks": len(corpus),
        "batch_size": batch_size,
        "n_batches": len(batch_latencies_ms),
        "total_seconds": round(total_elapsed_s, 4),
        "throughput_chunks_per_s": throughput,
        "latency_ms": {
            "p50": round(_percentile(sorted_l, 0.5), 3),
            "p95": round(_percentile(sorted_l, 0.95), 3),
            "p99": round(_percentile(sorted_l, 0.99), 3),
            "min": round(sorted_l[0], 3) if sorted_l else 0.0,
            "max": round(sorted_l[-1], 3) if sorted_l else 0.0,
            "mean": round(statistics.fmean(sorted_l), 3) if sorted_l else 0.0,
        },
    }


def _build_cfg(provider: str, dimension: int, device: str) -> EmbeddingConfig:
    if provider == "bge_m3":
        return EmbeddingConfig(provider="bge_m3", dimension=1024, bge_m3_device=device)
    if provider == "fake_bge_m3":
        return EmbeddingConfig(provider="fake_bge_m3", dimension=dimension)
    if provider == "fake":
        return EmbeddingConfig(provider="fake", dimension=dimension)
    msg = f"unsupported provider: {provider!r}"
    raise ValueError(msg)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "--provider",
        default="fake_bge_m3",
        choices=["fake", "fake_bge_m3", "bge_m3"],
        help="Adapter under test (default: fake_bge_m3 — hermetic, no weights download).",
    )
    parser.add_argument("--n-chunks", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument(
        "--dimension",
        type=int,
        default=128,
        help="Ignored for provider=bge_m3 (fixed at 1024).",
    )
    parser.add_argument("--device", default="auto", choices=["auto", "mps", "cuda", "cpu"])
    parser.add_argument("--output", default="text", choices=["text", "json"])
    return parser.parse_args(argv)


def _print_text(result: dict[str, Any]) -> None:
    print(f"provider   : {result['provider']}")
    print(f"model      : {result['model_name']}")
    print(f"hybrid     : {result['hybrid']}")
    print(f"n_chunks   : {result['n_chunks']}")
    print(f"batch_size : {result['batch_size']}")
    print(f"total      : {result['total_seconds']} s")
    print(f"throughput : {result['throughput_chunks_per_s']} chunks/s")
    lat = result["latency_ms"]
    print(
        f"latency ms : p50={lat['p50']} p95={lat['p95']} p99={lat['p99']} "
        f"min={lat['min']} max={lat['max']} mean={lat['mean']}"
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    cfg = _build_cfg(args.provider, args.dimension, args.device)
    adapter = _build_adapter(cfg)
    corpus = _synthesize_corpus(args.n_chunks)

    result = asyncio.run(_bench_adapter(adapter, corpus, args.batch_size))
    result["provider"] = args.provider
    result["model_name"] = getattr(adapter, "model_name", "unknown")
    result["device"] = args.device

    # Spec §US3 / SC-002: warn on CPU fallback, do NOT fail. CI diff-gates
    # the JSON artefact separately.
    p95 = result["latency_ms"]["p95"]
    if args.provider == "bge_m3" and p95 > BGE_M3_P95_BATCH_32_MS * CPU_MULTIPLIER:
        print(
            f"WARN: p95 {p95} ms > {BGE_M3_P95_BATCH_32_MS * CPU_MULTIPLIER} ms "
            "(CPU fallback? set device=mps/cuda if available)",
            file=sys.stderr,
        )

    if args.output == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_text(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
