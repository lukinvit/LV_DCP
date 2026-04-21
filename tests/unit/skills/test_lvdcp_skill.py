"""Sanity tests for the shipped Claude Code skill.

These are not end-to-end tests of Claude Code loading the skill — they
just verify the markdown shape so drift in the skill file surfaces in CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SKILL_PATH = Path(__file__).resolve().parents[3] / "skills" / "lvdcp" / "SKILL.md"


@pytest.mark.skipif(not SKILL_PATH.exists(), reason="skill file missing")
class TestSkillShape:
    def test_has_frontmatter(self) -> None:
        text = SKILL_PATH.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert "\n---\n" in text

    def test_frontmatter_declares_name_and_description(self) -> None:
        text = SKILL_PATH.read_text(encoding="utf-8")
        header, _, _ = text.partition("\n---\n")
        assert "name: lvdcp" in header
        assert "description:" in header

    def test_mentions_every_shipped_tool(self) -> None:
        text = SKILL_PATH.read_text(encoding="utf-8")
        expected_tools = [
            "lvdcp_pack",
            "lvdcp_inspect",
            "lvdcp_status",
            "lvdcp_scan",
            "lvdcp_explain",
            "lvdcp_neighbors",
            "lvdcp_history",
            "lvdcp_cross_project_patterns",
            "lvdcp_memory_propose",
            "lvdcp_memory_list",
        ]
        for tool in expected_tools:
            assert tool in text, f"{tool} missing from SKILL.md"

    def test_documents_ambiguous_coverage_rule(self) -> None:
        # The "do not proceed on ambiguous coverage" rule must stay in the
        # skill so the agent knows to stop and clarify.
        text = SKILL_PATH.read_text(encoding="utf-8").lower()
        assert "ambiguous" in text
