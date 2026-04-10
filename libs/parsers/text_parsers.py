"""Deterministic parsers for markdown and config files.

None of these need tree-sitter or LLM. They use stdlib or tiny deps.
"""

from __future__ import annotations

import json
import re
import tomllib

import yaml

from libs.core.entities import Symbol, SymbolType
from libs.parsers.base import ParseResult


class MarkdownParser:
    language = "markdown"

    _heading_re = re.compile(rb"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)

    def parse(self, *, file_path: str, data: bytes) -> ParseResult:
        symbols: list[Symbol] = []
        for match in self._heading_re.finditer(data):
            level = len(match.group(1))
            title = match.group(2).decode("utf-8", errors="replace").strip()
            line = data.count(b"\n", 0, match.start()) + 1
            symbols.append(
                Symbol(
                    name=title,
                    fq_name=f"{file_path}#h{level}-{title}",
                    symbol_type=SymbolType.MODULE if level == 1 else SymbolType.CLASS,
                    file_path=file_path,
                    start_line=line,
                    end_line=line,
                )
            )
        return ParseResult(
            file_path=file_path,
            language=self.language,
            role="docs",
            symbols=tuple(symbols),
        )


class YamlParser:
    language = "yaml"

    def parse(self, *, file_path: str, data: bytes) -> ParseResult:
        errors: tuple[str, ...] = ()
        try:
            yaml.safe_load(data)
        except yaml.YAMLError as exc:
            errors = (f"yaml parse error: {exc}",)
        return ParseResult(
            file_path=file_path,
            language=self.language,
            role="config",
            errors=errors,
        )


class JsonParser:
    language = "json"

    def parse(self, *, file_path: str, data: bytes) -> ParseResult:
        errors: tuple[str, ...] = ()
        try:
            json.loads(data)
        except json.JSONDecodeError as exc:
            errors = (f"json parse error: {exc}",)
        return ParseResult(
            file_path=file_path,
            language=self.language,
            role="config",
            errors=errors,
        )


class TomlParser:
    language = "toml"

    def parse(self, *, file_path: str, data: bytes) -> ParseResult:
        errors: tuple[str, ...] = ()
        try:
            tomllib.loads(data.decode("utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            errors = (f"toml parse error: {exc}",)
        return ParseResult(
            file_path=file_path,
            language=self.language,
            role="config",
            errors=errors,
        )
