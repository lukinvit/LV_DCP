"""RAGAS LLM-judge adapter (see specs/006-ragas-promptfoo-eval, research.md).

Wraps 3 RAGAS metrics (context_precision, context_recall, faithfulness)
behind a small, testable surface:

- LLM via ``ragas.llms.llm_factory(provider='anthropic', ...)`` — native,
  no LangChain wrapper (validated in Phase 0).
- Per-(query, context, metric) LRU cache for determinism / cost savings.
- Metrics that need unavailable inputs (``reference`` / ``response``) are
  skipped per sample rather than failing — allows progressive enrichment
  of gold datasets.
- Spend is tracked via :class:`CostGuard`; exceeds → aborts the run.

Design note: this module does **not** read files. Callers pass
``retrieved_contexts`` (already-materialized text blobs) in
:class:`RagasQuerySample`. The runner (``libs/eval/runner.py``) is
responsible for reading file contents when ``llm_judge=True``.

``answer_relevancy`` is deliberately omitted: the RAGAS class requires
a ``BaseRagasEmbedding`` provider, which is extra wiring we do not need
for the MVP. Can be added in a follow-up once an embedding adapter is
agreed on.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from libs.eval.cost_guard import CostGuard, CostGuardExceeded


@dataclass(frozen=True)
class RagasQuerySample:
    """One eval sample, pre-assembled for the LLM judge."""

    query_id: str
    user_input: str
    retrieved_contexts: list[str]
    response: str | None = None
    reference: str | None = None


@dataclass(frozen=True)
class RagasPerQuery:
    query_id: str
    context_precision: float | None = None
    context_recall: float | None = None
    faithfulness: float | None = None


@dataclass(frozen=True)
class RagasMetrics:
    """Aggregated + per-query RAGAS scores."""

    context_precision: float | None
    context_recall: float | None
    faithfulness: float | None
    per_query: list[RagasPerQuery] = field(default_factory=list)
    cache_hits: int = 0
    cache_misses: int = 0


def _hash_key(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


class RagasAdapter:
    """Evaluate :class:`RagasQuerySample` list against 4 RAGAS metrics.

    Parameters
    ----------
    judge_model:
        Anthropic model name (e.g. ``"claude-haiku-4-5"``).
    cost_guard:
        Aborts the run when cumulative spend exceeds its budget.
    api_key:
        Anthropic API key. Explicit so tests can pass dummy values.
    llm_override:
        Inject a pre-built RAGAS LLM (used in tests to avoid the
        ``anthropic`` import path and real HTTP).
    cache_enabled:
        When ``True`` (default), repeated ``(query, context_hash, metric)``
        triples return the cached score without calling the LLM.
    """

    def __init__(
        self,
        *,
        judge_model: str,
        cost_guard: CostGuard,
        api_key: str,
        llm_override: Any | None = None,
        cache_enabled: bool = True,
    ) -> None:
        self._model = judge_model
        self._cost_guard = cost_guard
        self._cache_enabled = cache_enabled
        self._cache: dict[str, float] = {}

        if llm_override is not None:
            self._llm = llm_override
        else:
            self._llm = _build_anthropic_llm(judge_model, api_key)

        # Lazy import: ragas is an optional extra; hoisting to module scope
        # would break ``ctx`` for users who did not ``uv sync --extra eval``.
        from ragas.metrics.collections import (  # noqa: PLC0415
            ContextPrecision,
            ContextRecall,
            Faithfulness,
        )

        self._cp = ContextPrecision(llm=self._llm)
        self._cr = ContextRecall(llm=self._llm)
        self._f = Faithfulness(llm=self._llm)

    async def run(self, samples: list[RagasQuerySample]) -> RagasMetrics:
        """Score all samples and return aggregated metrics.

        Raises :class:`CostGuardExceeded` propagated from the guard.
        """
        per_query: list[RagasPerQuery] = []
        agg_cp: list[float] = []
        agg_cr: list[float] = []
        agg_f: list[float] = []
        hits = 0
        misses = 0

        for s in samples:
            cp_val: float | None = None
            cr_val: float | None = None
            f_val: float | None = None

            ctx_blob = "|".join(s.retrieved_contexts)

            # context_precision needs: user_input, reference, retrieved_contexts
            if s.user_input and s.reference and s.retrieved_contexts:
                cp_val, dh, dm = await self._score(
                    "context_precision",
                    ctx_blob,
                    s,
                    lambda s=s: self._cp.ascore(
                        user_input=s.user_input,
                        reference=s.reference or "",
                        retrieved_contexts=list(s.retrieved_contexts),
                    ),
                )
                hits += dh
                misses += dm
                agg_cp.append(cp_val)

            # context_recall needs: user_input, retrieved_contexts, reference
            if s.user_input and s.retrieved_contexts and s.reference:
                cr_val, dh, dm = await self._score(
                    "context_recall",
                    ctx_blob,
                    s,
                    lambda s=s: self._cr.ascore(
                        user_input=s.user_input,
                        retrieved_contexts=list(s.retrieved_contexts),
                        reference=s.reference or "",
                    ),
                )
                hits += dh
                misses += dm
                agg_cr.append(cr_val)

            # faithfulness needs: user_input, response, retrieved_contexts
            if s.user_input and s.response and s.retrieved_contexts:
                f_val, dh, dm = await self._score(
                    "faithfulness",
                    ctx_blob,
                    s,
                    lambda s=s: self._f.ascore(
                        user_input=s.user_input,
                        response=s.response or "",
                        retrieved_contexts=list(s.retrieved_contexts),
                    ),
                )
                hits += dh
                misses += dm
                agg_f.append(f_val)

            per_query.append(
                RagasPerQuery(
                    query_id=s.query_id,
                    context_precision=cp_val,
                    context_recall=cr_val,
                    faithfulness=f_val,
                )
            )

        def _mean(vs: list[float]) -> float | None:
            return float(sum(vs) / len(vs)) if vs else None

        return RagasMetrics(
            context_precision=_mean(agg_cp),
            context_recall=_mean(agg_cr),
            faithfulness=_mean(agg_f),
            per_query=per_query,
            cache_hits=hits,
            cache_misses=misses,
        )

    async def _score(
        self,
        metric_name: str,
        ctx_blob: str,
        sample: RagasQuerySample,
        call: Any,
    ) -> tuple[float, int, int]:
        """Run a single metric call with cache + cost_guard.

        Returns ``(score, cache_hit_delta, cache_miss_delta)``.
        """
        cache_key = _hash_key(
            metric_name,
            sample.user_input,
            ctx_blob,
            sample.response or "",
            sample.reference or "",
        )
        if self._cache_enabled and cache_key in self._cache:
            return self._cache[cache_key], 1, 0

        # Each LLM call is charged up-front; budget exhaustion aborts cleanly.
        try:
            self._cost_guard.incur(
                tokens_in=1500, tokens_out=200, model=self._model
            )
        except CostGuardExceeded:
            raise

        result = await call()
        val = float(result.value)
        if self._cache_enabled:
            self._cache[cache_key] = val
        return val, 0, 1


def _build_anthropic_llm(model: str, api_key: str) -> Any:
    """Construct a RAGAS-compatible LLM via the native anthropic path."""
    from anthropic import Anthropic  # noqa: PLC0415
    from ragas.llms import llm_factory  # noqa: PLC0415

    client = Anthropic(api_key=api_key)
    return llm_factory(model, provider="anthropic", client=client)
