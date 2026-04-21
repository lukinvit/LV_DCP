"""Tests for the reviewable memory store."""

from __future__ import annotations

from pathlib import Path

import pytest
from libs.memory.models import MemoryStatus
from libs.memory.store import (
    MemoryError,
    MemoryNotFoundError,
    accept_memory,
    list_memories,
    propose_memory,
    reject_memory,
)


class TestProposeMemory:
    def test_writes_a_proposed_markdown_file(self, tmp_path: Path) -> None:
        m = propose_memory(tmp_path, topic="Auth flow", body="JWT rotation notes.")
        assert m.status is MemoryStatus.PROPOSED
        assert m.topic == "Auth flow"
        assert m.id.startswith("mem_")
        assert Path(m.path).exists()

    def test_file_contains_yaml_frontmatter(self, tmp_path: Path) -> None:
        m = propose_memory(tmp_path, topic="X", body="body")
        text = Path(m.path).read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert "status: proposed" in text
        assert "id: mem_" in text
        assert "body" in text

    def test_empty_topic_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(MemoryError):
            propose_memory(tmp_path, topic="  ", body="body")

    def test_empty_body_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(MemoryError):
            propose_memory(tmp_path, topic="X", body="")

    def test_tags_are_persisted(self, tmp_path: Path) -> None:
        propose_memory(
            tmp_path,
            topic="tagged",
            body="body",
            tags=["auth", "jwt"],
        )
        reloaded = list_memories(tmp_path)[0]
        assert reloaded.tags == ("auth", "jwt")


class TestListMemories:
    def test_returns_empty_when_no_memory_dir(self, tmp_path: Path) -> None:
        assert list_memories(tmp_path) == []

    def test_newest_first(self, tmp_path: Path) -> None:
        m1 = propose_memory(tmp_path, topic="first", body="one")
        m2 = propose_memory(tmp_path, topic="second", body="two")
        listed = list_memories(tmp_path)
        assert listed[0].id == m2.id
        assert listed[1].id == m1.id

    def test_status_filter(self, tmp_path: Path) -> None:
        m1 = propose_memory(tmp_path, topic="one", body="one")
        propose_memory(tmp_path, topic="two", body="two")
        accept_memory(tmp_path, m1.id)

        accepted = list_memories(tmp_path, status=MemoryStatus.ACCEPTED)
        proposed = list_memories(tmp_path, status=MemoryStatus.PROPOSED)
        assert [m.id for m in accepted] == [m1.id]
        assert len(proposed) == 1

    def test_skips_malformed_files(self, tmp_path: Path) -> None:
        mem_dir = tmp_path / ".context" / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "valid.md").write_text(
            "---\nid: mem_abc\nstatus: proposed\ntopic: t\ntags: []\ncreated_at: x\ncreated_by: y\n---\nbody",
            encoding="utf-8",
        )
        (mem_dir / "broken.md").write_text("no frontmatter", encoding="utf-8")

        listed = list_memories(tmp_path)
        assert len(listed) == 1
        assert listed[0].id == "mem_abc"


class TestAcceptReject:
    def test_accept_flips_status(self, tmp_path: Path) -> None:
        m = propose_memory(tmp_path, topic="t", body="b")
        updated = accept_memory(tmp_path, m.id)
        assert updated.is_accepted()
        # On disk.
        fresh = list_memories(tmp_path)[0]
        assert fresh.status is MemoryStatus.ACCEPTED

    def test_reject_flips_status(self, tmp_path: Path) -> None:
        m = propose_memory(tmp_path, topic="t", body="b")
        updated = reject_memory(tmp_path, m.id)
        assert updated.status is MemoryStatus.REJECTED

    def test_unknown_id_raises(self, tmp_path: Path) -> None:
        with pytest.raises(MemoryNotFoundError):
            accept_memory(tmp_path, "mem_does_not_exist")

    def test_accept_preserves_body_and_tags(self, tmp_path: Path) -> None:
        m = propose_memory(
            tmp_path,
            topic="auth",
            body="**Important** rotation rule",
            tags=["auth", "security"],
        )
        accept_memory(tmp_path, m.id)
        reloaded = list_memories(tmp_path)[0]
        assert reloaded.tags == ("auth", "security")
        assert "Important" in reloaded.body
