import json
from pathlib import Path

from libs.breadcrumbs.cc_identity import resolve_cc_account_email


def test_returns_none_when_root_missing(tmp_path: Path) -> None:
    assert resolve_cc_account_email(root=tmp_path / "missing") is None


def test_extracts_email_from_newest_local_json(tmp_path: Path) -> None:
    base = tmp_path / "local-agent-mode-sessions" / "acct1" / "org1"
    base.mkdir(parents=True)
    older = base / "local_old.json"
    older.write_text(
        json.dumps({"accountName": "old@example.com", "emailAddress": "old@example.com"})
    )
    older_mtime = older.stat().st_mtime
    newer = base / "local_new.json"
    newer.write_text(json.dumps({"accountName": "Alice", "emailAddress": "alice@example.com"}))
    import os

    os.utime(newer, (older_mtime + 100, older_mtime + 100))
    assert resolve_cc_account_email(root=tmp_path) == "alice@example.com"


def test_returns_none_on_corrupt_json(tmp_path: Path) -> None:
    base = tmp_path / "local-agent-mode-sessions" / "acct1" / "org1"
    base.mkdir(parents=True)
    (base / "local_x.json").write_text("not json {{{")
    assert resolve_cc_account_email(root=tmp_path) is None
