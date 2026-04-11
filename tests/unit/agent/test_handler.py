from pathlib import Path

from apps.agent.handler import DebounceBuffer


def test_debounce_buffer_groups_events_by_project() -> None:
    buf = DebounceBuffer(debounce_seconds=0.05)
    buf.add(Path("/proj-a"), "a.py", "modified")
    buf.add(Path("/proj-a"), "b.py", "created")
    buf.add(Path("/proj-b"), "c.py", "deleted")

    flushed = buf.flush_all()
    assert set(flushed.keys()) == {Path("/proj-a"), Path("/proj-b")}
    assert flushed[Path("/proj-a")] == {"a.py", "b.py"}
    assert flushed[Path("/proj-b")] == {"c.py"}


def test_debounce_buffer_dedupes_same_path() -> None:
    buf = DebounceBuffer(debounce_seconds=0.05)
    buf.add(Path("/proj"), "a.py", "modified")
    buf.add(Path("/proj"), "a.py", "modified")
    buf.add(Path("/proj"), "a.py", "modified")

    flushed = buf.flush_all()
    assert flushed[Path("/proj")] == {"a.py"}


def test_debounce_buffer_flush_clears() -> None:
    buf = DebounceBuffer(debounce_seconds=0.05)
    buf.add(Path("/proj"), "a.py", "modified")
    first = buf.flush_all()
    second = buf.flush_all()
    assert first == {Path("/proj"): {"a.py"}}
    assert second == {}
