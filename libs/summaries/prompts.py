"""File summary prompt templates, versioned.

Prompts are keyed on a version string (v1, v2, ...). Each version is immutable
once released so the summary cache (keyed on content_hash + prompt_version +
model_name) remains valid. Bumping to a new version means old cached summaries
stay accessible via lookup with the old version, new calls get the new template.
"""

from __future__ import annotations

FILE_SUMMARY_PROMPT_V1 = {
    "version": "v1",
    "system": (
        "You are a Python code summarizer. Given a file, produce exactly 2-3 "
        "sentences describing: (1) what this file does as its main responsibility, "
        "(2) its key exported symbols or entry points, (3) its role in a larger "
        "system if inferable. Use technical tone, no preamble, no boilerplate like "
        "'This file contains...'. Output plain text only, no markdown."
    ),
    "user_template": (
        "File path: {file_path}\n"
        "```\n{content}\n```\n\n"
        "Summary:"
    ),
}


FILE_SUMMARY_PROMPT_V2 = {
    "version": "v2",
    "system": (
        "You are a Python code summarizer for the LV_DCP project. Given a file, "
        "produce exactly 2-3 sentences describing: (1) what this file does as its "
        "main responsibility, (2) its key exported symbols or entry points, "
        "(3) its role in a larger system if inferable. Use technical tone, "
        "no preamble, no boilerplate like 'This file contains...'. Output plain "
        "text only, no markdown.\n"
        "\n"
        "Glossary of acronyms used in this codebase:\n"
        "- MCP = Model Context Protocol (the Anthropic Claude extension standard, "
        "NOT 'Managed Code Platform' or similar inventions)\n"
        "- LV_DCP = LV Developer Context Platform (the project itself)\n"
        "- FTS = Full-Text Search (SQLite FTS5)\n"
        "- AST = Abstract Syntax Tree\n"
        "- LLM = Large Language Model\n"
        "- DTO = Data Transfer Object\n"
    ),
    "user_template": (
        "File path: {file_path}\n"
        "```\n{content}\n```\n\n"
        "Summary:"
    ),
}


PROMPTS: dict[str, dict[str, str]] = {
    "v1": FILE_SUMMARY_PROMPT_V1,
    "v2": FILE_SUMMARY_PROMPT_V2,
}


def get_prompt(version: str) -> dict[str, str]:
    """Return the prompt template for *version*, or raise KeyError."""
    if version not in PROMPTS:
        raise KeyError(f"unknown prompt_version: {version!r}")
    return PROMPTS[version]
