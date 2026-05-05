from pathlib import Path

from libs.mcp_ops.launchd import write_breadcrumb_prune_plist


def test_plist_contains_required_keys(tmp_path: Path) -> None:
    out = write_breadcrumb_prune_plist(
        plist_path=tmp_path / "prune.plist", ctx_path=Path("/usr/local/bin/ctx")
    )
    text = out.read_text()
    assert "com.lukinvit.lvdcp.breadcrumb-prune" in text
    assert "/usr/local/bin/ctx" in text
    assert "breadcrumb" in text and "prune" in text
    assert "<key>StartCalendarInterval</key>" in text
    assert "<integer>4</integer>" in text  # hour 04:00
