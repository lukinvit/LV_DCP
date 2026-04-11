from pathlib import Path

from apps.agent.handler import DebounceBuffer


def test_debounce_buffer_groups_events_by_project() -> None:
    buf = DebounceBuffer(debounce_seconds=0.05)
    buf.add(Path("/proj-a"), "a.py", "modified")
    buf.add(Path("/proj-a"), "b.py", "created")
    buf.add(Path("/proj-b"), "c.py", "deleted")

    flushed = buf.flush_all()
    assert set(flushed.keys()) == {Path("/proj-a"), Path("/proj-b")}
    # proj-a: a.py and b.py in modified, nothing deleted
    modified_a, deleted_a = flushed[Path("/proj-a")]
    assert modified_a == {"a.py", "b.py"}
    assert deleted_a == set()
    # proj-b: c.py in deleted, nothing modified
    modified_b, deleted_b = flushed[Path("/proj-b")]
    assert modified_b == set()
    assert deleted_b == {"c.py"}


def test_debounce_buffer_dedupes_same_path() -> None:
    buf = DebounceBuffer(debounce_seconds=0.05)
    buf.add(Path("/proj"), "a.py", "modified")
    buf.add(Path("/proj"), "a.py", "modified")
    buf.add(Path("/proj"), "a.py", "modified")

    flushed = buf.flush_all()
    modified, deleted = flushed[Path("/proj")]
    assert modified == {"a.py"}
    assert deleted == set()


def test_debounce_buffer_flush_clears() -> None:
    buf = DebounceBuffer(debounce_seconds=0.05)
    buf.add(Path("/proj"), "a.py", "modified")
    first = buf.flush_all()
    second = buf.flush_all()
    modified, deleted = first[Path("/proj")]
    assert modified == {"a.py"}
    assert deleted == set()
    assert second == {}


def test_debounce_buffer_tracks_deletions_separately() -> None:
    buf = DebounceBuffer(debounce_seconds=0.05)
    buf.add(Path("/proj"), "a.py", "modified")
    buf.add(Path("/proj"), "b.py", "deleted")

    flushed = buf.flush_all()
    modified, deleted = flushed[Path("/proj")]
    assert "a.py" in modified
    assert "a.py" not in deleted
    assert "b.py" in deleted
    assert "b.py" not in modified


def test_debounce_buffer_delete_then_modify_wins_modify() -> None:
    buf = DebounceBuffer(debounce_seconds=0.05)
    buf.add(Path("/proj"), "a.py", "deleted")
    buf.add(Path("/proj"), "a.py", "created")  # re-created wins

    flushed = buf.flush_all()
    modified, deleted = flushed[Path("/proj")]
    assert "a.py" in modified
    assert "a.py" not in deleted
