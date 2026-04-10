"""Parser protocol and result dataclass."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from libs.core.entities import Immutable, Relation, Symbol


class ParseResult(Immutable):
    file_path: str
    language: str
    role: str
    symbols: tuple[Symbol, ...] = ()
    relations: tuple[Relation, ...] = ()
    errors: tuple[str, ...] = ()


@runtime_checkable
class FileParser(Protocol):
    """A parser takes raw bytes and a (POSIX) file path, returns ParseResult."""

    language: str

    def parse(self, *, file_path: str, data: bytes) -> ParseResult: ...
