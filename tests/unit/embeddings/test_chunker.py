"""Tests for the code-aware file chunker."""

from __future__ import annotations

from libs.embeddings.chunker import Chunk, chunk_file


def test_chunk_returns_chunks() -> None:
    content = "line1\nline2\nline3\n"
    chunks = chunk_file("test.py", content)
    assert len(chunks) >= 1
    assert all(isinstance(c, Chunk) for c in chunks)


def test_chunk_metadata_correct() -> None:
    content = "a\nb\nc\n"
    chunks = chunk_file("foo.py", content)
    assert chunks[0].file_path == "foo.py"
    assert chunks[0].start_line == 1
    # All content fits in one chunk.
    assert chunks[0].end_line == 3


def test_chunk_respects_max_tokens() -> None:
    # Build content large enough to require multiple chunks.
    # Each line is ~5 tokens ("word word word word\n").
    lines = ["word word word word\n"] * 200
    content = "".join(lines)
    chunks = chunk_file("big.py", content, max_tokens=50)
    assert len(chunks) > 1
    # Verify no gaps in line coverage.
    for i in range(len(chunks) - 1):
        assert chunks[i + 1].start_line == chunks[i].end_line + 1


def test_chunk_empty_file() -> None:
    assert chunk_file("empty.py", "") == []
    assert chunk_file("blank.py", "   \n  \n") == []


def test_chunk_small_file() -> None:
    content = "x = 1\n"
    chunks = chunk_file("small.py", content)
    assert len(chunks) == 1
    assert chunks[0].text == "x = 1\n"
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 1


def test_chunk_prefers_blank_line_boundary() -> None:
    # Two logical blocks separated by blank line.
    block_a = "def foo():\n    return 1\n"
    block_b = "def bar():\n    return 2\n"
    content = block_a + "\n" + block_b
    # Use a very small max_tokens to force a split.
    chunks = chunk_file("split.py", content, max_tokens=8)
    # Should split at or near the blank line.
    assert len(chunks) >= 2


def test_chunk_frozen() -> None:
    chunks = chunk_file("f.py", "x = 1\n")
    import pytest

    with pytest.raises(AttributeError):
        chunks[0].text = "changed"  # type: ignore[misc]
