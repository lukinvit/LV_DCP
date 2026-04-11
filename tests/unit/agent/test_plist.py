from pathlib import Path

from apps.agent.plist import generate_plist


def test_generate_plist_contains_expected_keys(tmp_path: Path) -> None:
    wrapper_path = tmp_path / "lvdcp-agent"
    log_dir = tmp_path / "logs"

    plist = generate_plist(
        label="tech.lvdcp.agent",
        program_arguments=[str(wrapper_path)],
        log_dir=log_dir,
    )

    assert "<key>Label</key>" in plist
    assert "tech.lvdcp.agent" in plist
    assert "<key>ProgramArguments</key>" in plist
    assert str(wrapper_path) in plist
    assert "<key>RunAtLoad</key>" in plist
    assert "<true/>" in plist
    assert "<key>KeepAlive</key>" in plist
    assert str(log_dir / "agent.out.log") in plist
    assert str(log_dir / "agent.err.log") in plist
