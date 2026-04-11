from __future__ import annotations

import pytest
from libs.summaries.prompts import (
    FILE_SUMMARY_PROMPT_V1,
    FILE_SUMMARY_PROMPT_V2,
    PROMPTS,
    get_prompt,
)


def test_v1_and_v2_both_registered() -> None:
    assert "v1" in PROMPTS
    assert "v2" in PROMPTS
    assert PROMPTS["v1"] is FILE_SUMMARY_PROMPT_V1
    assert PROMPTS["v2"] is FILE_SUMMARY_PROMPT_V2


def test_v2_contains_mcp_glossary() -> None:
    system = FILE_SUMMARY_PROMPT_V2["system"]
    assert "Model Context Protocol" in system
    assert "MCP" in system
    # Negative: the wrong expansion should not be suggested
    assert "Managed Code Platform" not in system or "NOT" in system


def test_v2_contains_lvdcp_glossary() -> None:
    system = FILE_SUMMARY_PROMPT_V2["system"]
    assert "LV_DCP" in system


def test_get_prompt_returns_correct_version() -> None:
    assert get_prompt("v1") is FILE_SUMMARY_PROMPT_V1
    assert get_prompt("v2") is FILE_SUMMARY_PROMPT_V2


def test_get_prompt_unknown_raises() -> None:
    with pytest.raises(KeyError, match="unknown prompt_version"):
        get_prompt("v999")


def test_v1_and_v2_share_user_template_structure() -> None:
    # Both should accept the same {file_path} and {content} placeholders
    for p in (FILE_SUMMARY_PROMPT_V1, FILE_SUMMARY_PROMPT_V2):
        formatted = p["user_template"].format(file_path="a.py", content="x = 1")
        assert "a.py" in formatted
        assert "x = 1" in formatted
