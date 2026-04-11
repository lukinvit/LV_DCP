"""Secret pattern detection for Phase 2 privacy filter.

Detects known credential formats by regex prefix-anchoring. Errs on the
safe side — any flagged content is excluded from the FTS index and pack
output. False positives are tolerated (cost: one irrelevant file skipped),
false negatives are not tolerated (cost: credential leak).
"""

from __future__ import annotations

import re

# Each pattern is anchored to make false positives on random ASCII unlikely.
# Order by expected frequency / severity.
SECRET_PATTERNS: tuple[re.Pattern[bytes], ...] = (
    re.compile(rb"AKIA[0-9A-Z]{16}"),  # AWS access key
    re.compile(rb"sk-proj-[A-Za-z0-9_-]{20,}"),  # OpenAI project key
    re.compile(rb"sk-[A-Za-z0-9]{32,}"),  # OpenAI legacy key
    re.compile(rb"sk_live_[0-9a-zA-Z]{24,}"),  # Stripe live
    re.compile(rb"sk_test_[0-9a-zA-Z]{24,}"),  # Stripe test
    re.compile(rb"pk_live_[0-9a-zA-Z]{24,}"),  # Stripe publishable live
    re.compile(rb"ghp_[A-Za-z0-9]{36}"),  # GitHub personal token
    re.compile(rb"gho_[A-Za-z0-9]{36}"),  # GitHub OAuth token
    re.compile(rb"github_pat_[A-Za-z0-9_]{22,}"),  # GitHub fine-grained PAT
    re.compile(rb"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack tokens
    re.compile(rb"eyJ[A-Za-z0-9_-]{3,}\.eyJ[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]{3,}"),  # JWT
    re.compile(rb"-----BEGIN (RSA|DSA|EC|OPENSSH|PRIVATE) KEY-----"),  # Private key header
)


def contains_secret_pattern(data: bytes) -> bool:
    """Return True if any known secret pattern matches the byte content."""
    if not data:
        return False
    return any(pat.search(data) for pat in SECRET_PATTERNS)
