"""Test that daemon scan pass updates last_scan_at_iso in config.yaml."""

from __future__ import annotations

from pathlib import Path

from apps.agent.config import add_project, list_projects
from apps.agent.daemon import process_pending_events
from apps.agent.handler import DebounceBuffer


def test_process_pending_events_updates_last_scan(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()
    (project_root / "hello.py").write_text("def hi() -> None:\n    return None\n")

    config_path = tmp_path / "config.yaml"
    add_project(config_path, project_root)

    buffer = DebounceBuffer(debounce_seconds=0.0)
    buffer.add(project_root.resolve(), "hello.py", "modified")

    process_pending_events(buffer, config_path=config_path)

    entries = list_projects(config_path)
    assert len(entries) == 1
    assert entries[0].last_scan_at_iso is not None
    assert entries[0].last_scan_status == "ok"
