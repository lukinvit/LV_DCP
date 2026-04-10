"""Deterministic content hashes for cache keys and change detection."""

from __future__ import annotations

import hashlib


def content_hash(data: bytes) -> str:
    """Return a hex SHA-256 of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def prompt_hash(*, content: str, prompt_version: str) -> str:
    """Hash used as cache key for LLM-generated artifacts (Phase 2+).

    Combining content with a prompt version ensures cache invalidation
    when the prompt template itself changes, even if the input text does not.
    """
    payload = f"{prompt_version}\0{content}".encode()
    return hashlib.sha256(payload).hexdigest()
