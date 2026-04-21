"""Cost guard for LLM-judge eval (see specs/006-ragas-promptfoo-eval).

Wraps ``libs.llm.cost.calculate_cost`` and aborts the eval run when the
accumulated spend exceeds ``max_usd``. The guard is used by the RAGAS
adapter around each LLM call.
"""

from __future__ import annotations

from libs.llm.cost import calculate_cost


class CostGuardExceeded(RuntimeError):
    """Raised when the cost guard's budget is exhausted."""

    def __init__(self, spent_usd: float, max_usd: float) -> None:
        super().__init__(
            f"cost guard exceeded: spent ${spent_usd:.4f} > max ${max_usd:.4f}"
        )
        self.spent_usd = spent_usd
        self.max_usd = max_usd


class CostGuard:
    """Accumulates USD spend across LLM calls; raises when over budget.

    Usage::

        guard = CostGuard(max_usd=1.0)
        guard.incur(tokens_in=500, tokens_out=100, model="claude-haiku-4-5")
        # ... raises CostGuardExceeded if total > max_usd
    """

    def __init__(self, max_usd: float) -> None:
        if max_usd <= 0:
            raise ValueError(f"max_usd must be > 0, got {max_usd}")
        self._max_usd = max_usd
        self._spent_usd = 0.0

    @property
    def spent_usd(self) -> float:
        return self._spent_usd

    @property
    def max_usd(self) -> float:
        return self._max_usd

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self._max_usd - self._spent_usd)

    def incur(self, *, tokens_in: int, tokens_out: int, model: str) -> float:
        """Record LLM usage and return cost of this call.

        Raises :class:`CostGuardExceeded` when the *cumulative* spend after
        this call would exceed ``max_usd``. The call is not recorded in
        that case.
        """
        cost = calculate_cost(model, input_tokens=tokens_in, output_tokens=tokens_out)
        projected = self._spent_usd + cost
        if projected > self._max_usd:
            raise CostGuardExceeded(projected, self._max_usd)
        self._spent_usd = projected
        return cost
