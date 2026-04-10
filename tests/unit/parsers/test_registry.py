from libs.parsers.registry import detect_language, get_parser


def test_detect_language_by_extension() -> None:
    assert detect_language("a.py") == "python"
    assert detect_language("a.md") == "markdown"
    assert detect_language("a.yaml") == "yaml"
    assert detect_language("a.yml") == "yaml"
    assert detect_language("a.json") == "json"
    assert detect_language("a.toml") == "toml"
    assert detect_language("unknown.xyz") == "unknown"


def test_get_parser_returns_matching_instance() -> None:
    p = get_parser("python")
    assert p is not None
    assert p.language == "python"


def test_get_parser_returns_none_for_unknown() -> None:
    assert get_parser("cobol") is None
