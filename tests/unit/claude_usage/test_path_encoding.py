from __future__ import annotations

from pathlib import Path

from libs.claude_usage.path_encoding import decode_project_path, encode_project_path


def test_encode_absolute_path(tmp_path: Path) -> None:
    # Use a real tmp dir to avoid macOS /home symlink resolution
    project = tmp_path / "proj" / "LV_DCP"
    project.mkdir(parents=True)
    encoded = encode_project_path(project)
    assert encoded.endswith("-proj-LV-DCP")
    assert encoded.startswith("-")


def test_encode_replaces_underscore_with_dash(tmp_path: Path) -> None:
    d = tmp_path / "a_b" / "c_d"
    d.mkdir(parents=True)
    encoded = encode_project_path(d)
    assert encoded.endswith("-a-b-c-d")


def test_decode_returns_best_effort_path() -> None:
    # Lossy — '-' could have been '/', '.' or '_' in original.
    # decode reconstructs path separators only.
    decoded = decode_project_path("-tmp-proj-LV-DCP")
    assert decoded == Path("/tmp/proj/LV/DCP")


def test_decode_returns_none_for_non_encoded() -> None:
    assert decode_project_path("plain_string") is None
    assert decode_project_path("") is None


def test_encode_real_project_paths(tmp_path: Path) -> None:
    proj = tmp_path / "projects" / "LV_DCP"
    proj.mkdir(parents=True)
    encoded = encode_project_path(proj)
    assert encoded.endswith("-projects-LV-DCP")

    bot = tmp_path / "projects" / "project-bot"
    bot.mkdir(parents=True)
    encoded2 = encode_project_path(bot)
    assert encoded2.endswith("-projects-project-bot")
