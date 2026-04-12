from __future__ import annotations

from pathlib import Path

from libs.claude_usage.path_encoding import decode_project_path, encode_project_path


def test_encode_absolute_path() -> None:
    assert encode_project_path(Path("/home/user/proj/LV_DCP")) == "-home-user-proj-LV-DCP"


def test_encode_replaces_underscore_with_dash() -> None:
    assert encode_project_path(Path("/a_b/c_d")) == "-a-b-c-d"


def test_decode_returns_best_effort_path() -> None:
    # Lossy — '-' could have been '/', '.' or '_' in original.
    # decode reconstructs path separators only.
    decoded = decode_project_path("-home-user-proj-LV-DCP")
    assert decoded == Path("/home/user/proj/LV/DCP")


def test_decode_returns_none_for_non_encoded() -> None:
    assert decode_project_path("plain_string") is None
    assert decode_project_path("") is None


def test_encode_real_project_paths_match_observed() -> None:
    cases = [
        (
            "/home/user/projects/LV_DCP",
            "-home-user-projects-LV-DCP",
        ),
        (
            "/home/user/projects/project-bot",
            "-home-user-projects-project-bot",
        ),
    ]
    for abs_path, expected in cases:
        assert encode_project_path(Path(abs_path)) == expected, abs_path
