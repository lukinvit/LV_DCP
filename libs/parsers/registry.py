"""Language detection and parser lookup."""

from __future__ import annotations

from libs.parsers.base import FileParser
from libs.parsers.python import PythonParser
from libs.parsers.text_parsers import JsonParser, MarkdownParser, TomlParser, YamlParser

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".md": "markdown",
    ".markdown": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
}


def detect_language(path: str) -> str:
    for ext, lang in EXTENSION_TO_LANGUAGE.items():
        if path.endswith(ext):
            return lang
    return "unknown"


_PARSERS: dict[str, FileParser] = {
    "python": PythonParser(),
    "markdown": MarkdownParser(),
    "yaml": YamlParser(),
    "json": JsonParser(),
    "toml": TomlParser(),
}


def get_parser(language: str) -> FileParser | None:
    return _PARSERS.get(language)
