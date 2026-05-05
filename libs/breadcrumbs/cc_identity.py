"""Read-only resolver for current CC session's account email."""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_ROOT = Path.home() / "Library" / "Application Support" / "Claude"
_AGENT_DIR = "local-agent-mode-sessions"


def resolve_cc_account_email(*, root: Path | None = None) -> str | None:
    """Best-effort lookup of the most recent CC session's account email.

    Returns None on any failure (missing root, no sessions, broken JSON,
    permissions). Logs at most one warning per process via module logger.
    """
    base = (root or _DEFAULT_ROOT) / _AGENT_DIR
    if not base.exists():
        return None
    candidates: list[Path] = []
    for session_file in base.rglob("local_*.json"):
        if session_file.is_file():
            candidates.append(session_file)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.debug("cc_identity: failed to read %s: %s", path, exc)
            continue
        email = data.get("emailAddress") or data.get("accountName")
        if isinstance(email, str) and email:
            return email
    return None
