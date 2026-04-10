"""In-memory symbol index with token-based scoring.

Deterministic. Replaceable later by a proper inverted index or vector store.
"""

from __future__ import annotations

import re

from libs.core.entities import Symbol

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


def _tokenize(text: str) -> list[str]:
    parts = _TOKEN_RE.findall(text)
    out: list[str] = []
    for p in parts:
        for s in p.split("_"):
            if not s:
                continue
            chunks = re.split(r"(?<=[a-z])(?=[A-Z])", s)
            out.extend(c.lower() for c in chunks if c)
    return out


class SymbolIndex:
    def __init__(self) -> None:
        self._symbols: list[Symbol] = []

    def add(self, symbol: Symbol) -> None:
        self._symbols.append(symbol)

    def extend(self, symbols: list[Symbol]) -> None:
        self._symbols.extend(symbols)

    def clear(self) -> None:
        self._symbols.clear()

    def lookup(self, query: str, *, limit: int = 10) -> list[Symbol]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[float, Symbol]] = []
        for sym in self._symbols:
            score = self._score(sym, query_tokens, raw_query=query.lower())
            if score > 0:
                scored.append((score, sym))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _score, s in scored[:limit]]

    @staticmethod
    def _score(sym: Symbol, query_tokens: list[str], *, raw_query: str) -> float:
        name_tokens = _tokenize(sym.name)
        fq_tokens = _tokenize(sym.fq_name)

        score = 0.0
        if sym.name.lower() == raw_query.strip():
            score += 10.0
        if raw_query.strip() in sym.fq_name.lower():
            score += 3.0
        name_set = set(name_tokens)
        fq_set = set(fq_tokens)
        for t in query_tokens:
            if t in name_set:
                score += 2.0
            elif t in fq_set:
                score += 1.0
        return score
