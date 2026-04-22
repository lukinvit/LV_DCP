"""Unit tests for libs/gitintel/tag_watcher.py (spec-010 T027)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from libs.gitintel.tag_watcher import TagEvent, list_git_tags, poll_tags


def _fake_runner(output: str):  # type: ignore[no-untyped-def]
    def run(_args: list[str]) -> str:
        return output
    return run


def _raising_runner(exc: Exception):  # type: ignore[no-untyped-def]
    def run(_args: list[str]) -> str:
        raise exc
    return run


def test_list_tags_parses_annotated_and_lightweight() -> None:
    """Annotated tags use `*objectname` (peeled); lightweight use `objectname`."""
    # Columns: refname\tobjectname\t*objectname
    output = (
        "v1.0\tabcd1234\tcommit-sha-lightweight-v1\n"  # lightweight: no peel -> use col 2
        "v2.0\ttag-object-sha\tcommit-sha-v2-peeled\n"  # annotated: col 3 is the peel
        "v3.0\tcommit-v3\t\n"  # lightweight, empty peel column
    )
    tags = list_git_tags(Path("/tmp"), git_runner=_fake_runner(output))
    # For v1.0 a peel is present (fake lightweight with peel); use the peel.
    assert tags == {
        "v1.0": "commit-sha-lightweight-v1",
        "v2.0": "commit-sha-v2-peeled",
        "v3.0": "commit-v3",
    }


def test_list_tags_returns_empty_on_git_failure() -> None:
    tags = list_git_tags(
        Path("/tmp"),
        git_runner=_raising_runner(
            subprocess.CalledProcessError(1, ["git", "for-each-ref"])
        ),
    )
    assert tags == {}


def test_list_tags_returns_empty_when_git_missing() -> None:
    tags = list_git_tags(
        Path("/tmp"),
        git_runner=_raising_runner(FileNotFoundError("git not installed")),
    )
    assert tags == {}


def test_poll_tags_emits_created_for_new_tag() -> None:
    output = "v1\tsha1\t\n"
    current, events = poll_tags(
        Path("/tmp"), known={}, git_runner=_fake_runner(output)
    )
    assert current == {"v1": "sha1"}
    assert events == [TagEvent(tag="v1", head_sha="sha1", kind="created")]


def test_poll_tags_emits_moved_when_tag_changes_sha() -> None:
    output = "v1\tnewsha\t\n"
    known = {"v1": "oldsha"}
    current, events = poll_tags(
        Path("/tmp"), known=known, git_runner=_fake_runner(output)
    )
    assert current == {"v1": "newsha"}
    assert events == [
        TagEvent(tag="v1", head_sha="newsha", kind="moved", previous_sha="oldsha")
    ]


def test_poll_tags_silent_on_unchanged_tags() -> None:
    output = "v1\tsha1\t\nv2\tsha2\t\n"
    known = {"v1": "sha1", "v2": "sha2"}
    _, events = poll_tags(
        Path("/tmp"), known=known, git_runner=_fake_runner(output)
    )
    assert events == []


def test_poll_tags_does_not_emit_for_deletions() -> None:
    """Tag that vanished from git is NOT reported — reconcile handles that."""
    output = "v2\tsha2\t\n"  # v1 gone
    known = {"v1": "sha1", "v2": "sha2"}
    current, events = poll_tags(
        Path("/tmp"), known=known, git_runner=_fake_runner(output)
    )
    assert "v1" not in current
    assert events == []


def test_poll_tags_mixed_new_and_moved() -> None:
    output = "v1\tnewsha\t\nv2\tsha2\t\nv3\tsha3\t\n"
    known = {"v1": "oldsha", "v2": "sha2"}
    _, events = poll_tags(
        Path("/tmp"), known=known, git_runner=_fake_runner(output)
    )
    event_map = {(e.tag, e.kind) for e in events}
    assert event_map == {("v1", "moved"), ("v3", "created")}


def test_real_git_repo_end_to_end(tmp_path: Path) -> None:
    """Sanity check with real ``git`` on a tmp repo."""
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "t@t"], check=True
    )
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "a.txt").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "a.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "c1"], check=True
    )
    subprocess.run(["git", "-C", str(repo), "tag", "v1"], check=True)

    tags = list_git_tags(repo)
    assert "v1" in tags
    assert len(tags["v1"]) == 40  # 40-hex commit sha
