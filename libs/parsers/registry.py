"""Language detection and parser lookup."""

from __future__ import annotations

from libs.parsers.base import FileParser
from libs.parsers.golang import GoParser
from libs.parsers.java import JavaParser
from libs.parsers.kotlin import KotlinParser
from libs.parsers.python import PythonParser
from libs.parsers.rust import RustParser
from libs.parsers.swift import SwiftParser
from libs.parsers.text_parsers import JsonParser, MarkdownParser, TomlParser, YamlParser
from libs.parsers.typescript import TypeScriptParser

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".md": "markdown",
    ".markdown": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
}


def detect_language(path: str) -> str:
    for ext, lang in EXTENSION_TO_LANGUAGE.items():
        if path.endswith(ext):
            return lang
    return "unknown"


def _make_js_parser() -> TypeScriptParser:
    """Create a TypeScriptParser configured for JavaScript grammar."""
    p = TypeScriptParser()
    p.language = "javascript"
    return p


_PARSERS: dict[str, FileParser] = {
    "python": PythonParser(),
    "markdown": MarkdownParser(),
    "yaml": YamlParser(),
    "json": JsonParser(),
    "toml": TomlParser(),
    "typescript": TypeScriptParser(),
    "javascript": _make_js_parser(),
    "go": GoParser(),
    "rust": RustParser(),
    "java": JavaParser(),
    "kotlin": KotlinParser(),
    "swift": SwiftParser(),
}


def get_parser(language: str) -> FileParser | None:
    return _PARSERS.get(language)
