"""Generate a launchd plist XML string for the LV_DCP daemon."""

from __future__ import annotations

from pathlib import Path


def generate_plist(
    *,
    label: str,
    program_arguments: list[str],
    log_dir: Path,
) -> str:
    """Produce the plist XML. Does not write to disk — caller decides where."""
    args_xml = "\n".join(f"        <string>{a}</string>" for a in program_arguments)
    out_log = str(log_dir / "agent.out.log")
    err_log = str(log_dir / "agent.err.log")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{out_log}</string>
    <key>StandardErrorPath</key>
    <string>{err_log}</string>
</dict>
</plist>
"""
