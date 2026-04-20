"""Tests for inherits and tests_for relation types."""

from __future__ import annotations

from libs.core.entities import RelationType
from libs.parsers.python import PythonParser

parser = PythonParser()


# --- inherits ----------------------------------------------------------------


def test_inherits_single_base() -> None:
    code = b"class Foo(Bar):\n    pass\n"
    result = parser.parse(file_path="src/foo.py", data=code)
    inherits = [r for r in result.relations if r.relation_type == RelationType.INHERITS]
    assert len(inherits) == 1
    assert "Foo" in inherits[0].src_ref
    assert "Bar" in inherits[0].dst_ref


def test_inherits_multiple_bases() -> None:
    code = b"class Foo(Bar, Baz):\n    pass\n"
    result = parser.parse(file_path="src/foo.py", data=code)
    inherits = [r for r in result.relations if r.relation_type == RelationType.INHERITS]
    assert len(inherits) == 2
    dst_refs = {r.dst_ref for r in inherits}
    assert any("Bar" in r for r in dst_refs)
    assert any("Baz" in r for r in dst_refs)


def test_inherits_resolves_imported_base() -> None:
    code = b"from libs.base import Base\n\nclass Foo(Base):\n    pass\n"
    result = parser.parse(file_path="src/foo.py", data=code)
    inherits = [r for r in result.relations if r.relation_type == RelationType.INHERITS]
    assert len(inherits) == 1
    assert inherits[0].dst_ref == "libs.base.Base"


def test_inherits_resolves_same_file_base() -> None:
    code = b"class Base:\n    pass\n\nclass Child(Base):\n    pass\n"
    result = parser.parse(file_path="src/models.py", data=code)
    inherits = [r for r in result.relations if r.relation_type == RelationType.INHERITS]
    assert len(inherits) == 1
    assert inherits[0].dst_ref == "src.models.Base"


def test_inherits_dotted_base() -> None:
    code = b"import abc\n\nclass Foo(abc.ABC):\n    pass\n"
    result = parser.parse(file_path="src/foo.py", data=code)
    inherits = [r for r in result.relations if r.relation_type == RelationType.INHERITS]
    assert len(inherits) == 1
    assert "abc.ABC" in inherits[0].dst_ref


# --- tests_for ---------------------------------------------------------------


def test_tests_for_from_imports() -> None:
    code = (
        b"from libs.retrieval.pipeline import RetrievalPipeline\n\ndef test_pipeline():\n    pass\n"
    )
    result = parser.parse(file_path="tests/test_pipeline.py", data=code)
    tests_for = [r for r in result.relations if r.relation_type == RelationType.TESTS_FOR]
    assert len(tests_for) >= 1
    assert any("libs/retrieval/pipeline.py" in r.dst_ref for r in tests_for)


def test_tests_for_plain_import() -> None:
    code = b"import libs.core.entities\n\ndef test_entities():\n    pass\n"
    result = parser.parse(file_path="tests/test_entities.py", data=code)
    tests_for = [r for r in result.relations if r.relation_type == RelationType.TESTS_FOR]
    assert len(tests_for) >= 1
    assert any("libs/core/entities.py" in r.dst_ref for r in tests_for)


def test_no_tests_for_on_source_files() -> None:
    code = b"from libs.core.entities import File\n\ndef process():\n    pass\n"
    result = parser.parse(file_path="libs/scanner.py", data=code)
    tests_for = [r for r in result.relations if r.relation_type == RelationType.TESTS_FOR]
    assert len(tests_for) == 0


def test_tests_for_skips_stdlib() -> None:
    """Single-segment imports like 'os' or 'datetime' should not produce tests_for."""
    code = b"from datetime import datetime\nimport os\n\ndef test_x():\n    pass\n"
    result = parser.parse(file_path="tests/test_x.py", data=code)
    tests_for = [r for r in result.relations if r.relation_type == RelationType.TESTS_FOR]
    # datetime and os are stdlib — no tests_for expected
    assert len(tests_for) == 0


def test_tests_for_accepts_ddd_roots() -> None:
    """DDD-style roots like `domains/` and `services/` count as internal.

    LV_Presentation and similar DDD projects use `domains/identity/...`
    as the source layout; tests there must still produce tests_for.
    """
    code = (
        b"from domains.identity.mcp.server import create_identity_mcp_server\n\n"
        b"def test_server():\n    pass\n"
    )
    result = parser.parse(
        file_path="domains/identity/tests/unit/test_mcp_server.py",
        data=code,
    )
    tests_for = [r for r in result.relations if r.relation_type == RelationType.TESTS_FOR]
    assert any("domains/identity/mcp/server.py" in r.dst_ref for r in tests_for)
