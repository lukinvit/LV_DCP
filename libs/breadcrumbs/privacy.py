"""Pattern-based secret redactor for breadcrumb query/turn_summary fields."""

from __future__ import annotations

import re

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("anthropic", re.compile(r"sk-ant-[A-Za-z0-9_-]{40,}")),
    ("openai",    re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("stripe",    re.compile(r"sk_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("github",    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("slack",     re.compile(r"xox[abprs]-[A-Za-z0-9-]{20,}")),
    ("aws",       re.compile(r"AKIA[0-9A-Za-z]{15,}")),
    ("jwt",       re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("hex64",     re.compile(r"\b[0-9a-fA-F]{64}\b")),
    ("conn_string", re.compile(r"(?:postgres|postgresql|mysql|mongodb|redis|rediss|amqp)://[^@\s]*:[^@\s]+@")),
    ("kv_secret", re.compile(
        r"(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?token|auth)\s*[=:]\s*[\"']?([^\s\"'&]+)",
        re.IGNORECASE,
    )),
]


def redact(text: str | None) -> str | None:
    """Redact secrets from text using pattern matching.

    Args:
        text: Text to redact, or None

    Returns:
        Redacted text with secrets replaced by [REDACTED:kind], or None if input is None
    """
    if text is None:
        return None
    for kind, pat in SECRET_PATTERNS:
        text = pat.sub(f"[REDACTED:{kind}]", text)
    return text
