"""Code-aware file chunker for embedding pipelines."""

from __future__ import annotations

from dataclasses import dataclass

import tiktoken


@dataclass(frozen=True)
class Chunk:
    """A contiguous slice of a source file."""

    file_path: str
    text: str
    start_line: int  # 1-based inclusive
    end_line: int  # 1-based inclusive


_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    global _encoder  # noqa: PLW0603
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def _token_count(text: str) -> int:
    return len(_get_encoder().encode(text))


def chunk_file(
    file_path: str,
    content: str,
    *,
    max_tokens: int = 512,
) -> list[Chunk]:
    """Split *content* into chunks respecting *max_tokens*.

    Strategy:
    - Split into lines.
    - Accumulate lines until the next line would exceed *max_tokens*.
    - Prefer to break at blank-line boundaries when possible.
    - Each chunk records its 1-based start/end line numbers.
    """
    if not content or not content.strip():
        return []

    lines = content.splitlines(keepends=True)
    chunks: list[Chunk] = []

    buf: list[str] = []
    buf_tokens = 0
    start_line = 1
    last_blank_idx: int | None = None  # index in buf of last blank line

    for i, line in enumerate(lines):
        line_tokens = _token_count(line)

        # If a single line exceeds max_tokens, flush buf then emit line solo.
        if line_tokens > max_tokens:
            if buf:
                chunks.append(_make_chunk(file_path, buf, start_line))
                buf = []
                buf_tokens = 0
                last_blank_idx = None
            chunks.append(
                Chunk(
                    file_path=file_path,
                    text=line,
                    start_line=i + 1,
                    end_line=i + 1,
                )
            )
            start_line = i + 2
            continue

        would_exceed = buf_tokens + line_tokens > max_tokens

        if would_exceed and buf:
            # Try to split at last blank line for cleaner boundaries.
            if last_blank_idx is not None and last_blank_idx > 0:
                split_at = last_blank_idx + 1  # include the blank line
                head = buf[:split_at]
                tail = buf[split_at:]
                chunks.append(_make_chunk(file_path, head, start_line))
                buf = tail
                buf_tokens = _token_count("".join(buf))
                start_line = start_line + split_at
                last_blank_idx = None
            else:
                chunks.append(_make_chunk(file_path, buf, start_line))
                buf = []
                buf_tokens = 0
                start_line = i + 1
                last_blank_idx = None

        buf.append(line)
        buf_tokens += line_tokens

        if line.strip() == "":
            last_blank_idx = len(buf) - 1

    if buf:
        chunks.append(_make_chunk(file_path, buf, start_line))

    return chunks


def _make_chunk(file_path: str, lines: list[str], start_line: int) -> Chunk:
    return Chunk(
        file_path=file_path,
        text="".join(lines),
        start_line=start_line,
        end_line=start_line + len(lines) - 1,
    )
