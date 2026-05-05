"""E7 multi-user isolation, E8 secret redaction."""

from __future__ import annotations

import pytest
from libs.breadcrumbs.reader import load_recent
from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.writer import write_pack_event

from tests.eval.resume.conftest import seed_pack_events

pytestmark = pytest.mark.eval


def test_e7_multi_user_isolation(store: BreadcrumbStore) -> None:
    """E7: Write 50 events for 'alice', read for 'bob' → exactly 0 rows (os_user filter)."""
    seed_pack_events(
        store,
        project_root="/x",
        queries=[f"q{i}" for i in range(50)],
        paths=[[]] * 50,
        os_user="alice",
    )
    rows_for_bob = load_recent(
        store=store,
        project_root="/x",
        os_user="bob",
        since_ts=0.0,
        limit=100,
    )
    assert rows_for_bob == []


def test_e8_secret_redaction_no_plaintext_in_db(store: BreadcrumbStore) -> None:
    """E8: Query bundles 3 secret patterns; verify NONE leak to DB and [REDACTED: marker present."""
    write_pack_event(
        store=store,
        project_root="/x",
        os_user="alice",
        query=(
            "why does sk-1234567890ABCDEFGHIJ token fail "
            "with conn postgresql://u:p@db/x and api_key=sk_test_abcdefghijklmnopqr"
        ),
        mode="navigate",
        paths_touched=[],
    )
    rows = list(store.connect().execute("SELECT query FROM breadcrumbs"))
    assert len(rows) == 1
    q = rows[0][0]
    # Verify none of the plaintext secrets are in the database
    assert "sk-1234567890ABCDEFGHIJ" not in q
    assert "postgresql://u:p@db/x" not in q
    assert "sk_test_abcdefghijklmnopqr" not in q
    # Verify redaction markers are present
    assert "[REDACTED:" in q
