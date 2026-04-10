import pytest
from libs.parsers.base import ParseResult
from pydantic import ValidationError


def test_parse_result_is_immutable() -> None:
    r = ParseResult(
        file_path="a.py",
        symbols=(),
        relations=(),
        language="python",
        role="source",
    )
    with pytest.raises(ValidationError):
        r.language = "rust"


def test_parse_result_defaults() -> None:
    r = ParseResult(file_path="a.py", language="python", role="source")
    assert r.symbols == ()
    assert r.relations == ()
    assert r.errors == ()
