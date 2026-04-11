"""File summary prompt templates, versioned."""

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
