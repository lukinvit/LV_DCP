from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parents[3] / "apps" / "mcp" / "hooks"
EXPECTED = [
    "lvdcp-resume-stop.sh",
    "lvdcp-resume-precompact.sh",
    "lvdcp-resume-subagent-stop.sh",
    "lvdcp-resume-sessionstart.sh",
]


def test_resume_hooks_present_and_executable() -> None:
    for name in EXPECTED:
        p = HOOK_DIR / name
        assert p.exists(), f"missing {p}"
        assert p.stat().st_mode & 0o111, f"not executable: {p}"


def test_hooks_have_5s_timeout_marker() -> None:
    for name in EXPECTED:
        text = (HOOK_DIR / name).read_text()
        assert "timeout 5" in text, f"{name} missing timeout 5"
