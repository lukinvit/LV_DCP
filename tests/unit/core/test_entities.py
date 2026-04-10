from __future__ import annotations

import pytest
from libs.core.entities import (
    ContextPack,
    File,
    PackMode,
    Project,
    RelationType,
    Summary,
    Symbol,
    SymbolType,
)
from pydantic import ValidationError


def test_file_is_immutable() -> None:
    f = File(
        path="app/main.py",
        content_hash="a" * 64,
        size_bytes=123,
        language="python",
        role="source",
    )
    with pytest.raises(ValidationError):
        f.path = "other.py"


def test_symbol_fq_name_uses_file_and_name() -> None:
    s = Symbol(
        name="User",
        fq_name="app.models.user.User",
        symbol_type=SymbolType.CLASS,
        file_path="app/models/user.py",
        start_line=10,
        end_line=42,
    )
    assert s.fq_name.endswith("User")


def test_project_requires_local_path() -> None:
    p = Project(name="lv-dcp", slug="lv-dcp", local_path="/abs/path")
    assert p.slug == "lv-dcp"


def test_context_pack_size_constraint() -> None:
    pack = ContextPack(
        project_slug="lv-dcp",
        query="where is User",
        mode=PackMode.NAVIGATE,
        assembled_markdown="# small\n",
        size_bytes=8,
    )
    assert pack.size_bytes == 8


def test_relation_type_enum_covers_phase_1() -> None:
    assert RelationType.IMPORTS.value == "imports"
    assert RelationType.DEFINES.value == "defines"
    assert RelationType.SAME_FILE_CALLS.value == "same_file_calls"


def test_summary_has_confidence() -> None:
    s = Summary(
        entity_type="file",
        entity_ref="app/main.py",
        summary_type="file_summary",
        text="entry point",
        text_hash="a" * 64,
        model_name="deterministic",
        model_version="v0",
        confidence=1.0,
    )
    assert 0.0 <= s.confidence <= 1.0
