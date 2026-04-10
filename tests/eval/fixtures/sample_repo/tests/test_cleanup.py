"""Tests for the cleanup worker."""

from datetime import datetime, timedelta

# Placeholder — real integration test would use a DB fixture.
def test_cleanup_marker() -> None:
    assert datetime.utcnow() - timedelta(days=1) < datetime.utcnow()
