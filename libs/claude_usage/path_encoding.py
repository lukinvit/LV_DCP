"""Encode / decode project paths to match ~/.claude/projects/ naming.

Observed encoding:
- Leading '/' → '-'
- Every '/' inside the path → '-'
- Every '.' inside any segment → '-'
- Every '_' inside any segment → '-'

Example:
    /Users/v.lukin/Nextcloud/lukinvit.tech/projects/LV_DCP
    → -Users-v-lukin-Nextcloud-lukinvit-tech-projects-LV-DCP

Decoding is lossy (a '-' could represent '/', '.' or '_' originally); the
decoder reconstructs path separators only and returns a best-effort Path
that is NOT guaranteed to exist on disk.
"""

from __future__ import annotations

from pathlib import Path


def encode_project_path(abs_path: Path) -> str:
    """Encode an absolute POSIX path to the Claude Code projects-dir format."""
    s = str(abs_path.resolve())
    return s.replace(".", "-").replace("_", "-").replace("/", "-")


def decode_project_path(encoded: str) -> Path | None:
    """Best-effort decode of an encoded name back to a Path.

    Returns None for empty input or input that does not start with '-'.
    """
    if not encoded or not encoded.startswith("-"):
        return None
    parts = encoded.split("-")[1:]
    return Path("/" + "/".join(parts))
