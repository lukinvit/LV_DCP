from __future__ import annotations

from pathlib import Path

from libs.claude_usage.path_encoding import decode_project_path, encode_project_path


def test_encode_absolute_path() -> None:
    assert encode_project_path(Path("/Users/v.lukin/proj/LV_DCP")) == "-Users-v-lukin-proj-LV-DCP"


def test_encode_replaces_underscore_with_dash() -> None:
    assert encode_project_path(Path("/a_b/c_d")) == "-a-b-c-d"


def test_decode_returns_best_effort_path() -> None:
    # Lossy — '-' could have been '/', '.' or '_' in original.
    # decode reconstructs path separators only.
    decoded = decode_project_path("-Users-v-lukin-proj-LV-DCP")
    assert decoded == Path("/Users/v/lukin/proj/LV/DCP")


def test_decode_returns_none_for_non_encoded() -> None:
    assert decode_project_path("plain_string") is None
    assert decode_project_path("") is None


def test_encode_real_project_paths_match_observed() -> None:
    cases = [
        (
            "/Users/v.lukin/Nextcloud/lukinvit.tech/projects/LV_DCP",
            "-Users-v-lukin-Nextcloud-lukinvit-tech-projects-LV-DCP",
        ),
        (
            "/Users/v.lukin/Nextcloud/lukinvit.tech/projects/TG_Proxy_enaibler_bot",
            "-Users-v-lukin-Nextcloud-lukinvit-tech-projects-TG-Proxy-enaibler-bot",
        ),
    ]
    for abs_path, expected in cases:
        assert encode_project_path(Path(abs_path)) == expected, abs_path
