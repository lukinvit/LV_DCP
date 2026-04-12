"""Tests for docs -> code specifies relation extraction."""

from __future__ import annotations

from libs.core.entities import RelationType
from libs.parsers.docs_linker import extract_specifies_relations


def test_finds_file_path_references() -> None:
    docs = [("docs/design.md", "The main pipeline is at `libs/retrieval/pipeline.py`")]
    rels = extract_specifies_relations(docs, {"libs/retrieval/pipeline.py", "docs/design.md"})
    assert len(rels) == 1
    assert rels[0].dst_ref == "libs/retrieval/pipeline.py"
    assert rels[0].relation_type == RelationType.SPECIFIES


def test_finds_module_references() -> None:
    docs = [("docs/arch.md", "The module libs.retrieval.pipeline handles ranking")]
    rels = extract_specifies_relations(docs, {"libs/retrieval/pipeline.py", "docs/arch.md"})
    assert len(rels) == 1
    assert rels[0].dst_ref == "libs/retrieval/pipeline.py"


def test_ignores_nonexistent_paths() -> None:
    docs = [("docs/old.md", "See libs/deleted/module.py for details")]
    rels = extract_specifies_relations(docs, {"docs/old.md"})
    assert len(rels) == 0


def test_no_self_reference() -> None:
    docs = [("docs/design.md", "This file is docs/design.md")]
    rels = extract_specifies_relations(docs, {"docs/design.md"})
    assert len(rels) == 0


def test_deduplicates() -> None:
    docs = [("docs/x.md", "libs/foo.py and also libs/foo.py again")]
    rels = extract_specifies_relations(docs, {"libs/foo.py", "docs/x.md"})
    assert len(rels) == 1


def test_multiple_docs_files() -> None:
    docs = [
        ("docs/a.md", "See libs/foo.py"),
        ("docs/b.md", "See libs/foo.py and libs/bar.py"),
    ]
    all_paths = {"docs/a.md", "docs/b.md", "libs/foo.py", "libs/bar.py"}
    rels = extract_specifies_relations(docs, all_paths)
    assert len(rels) == 3  # a->foo, b->foo, b->bar


def test_mixed_file_and_module_refs() -> None:
    docs = [("specs/spec.md", "Uses libs/core/entities.py and also apps.cli.main")]
    all_paths = {"specs/spec.md", "libs/core/entities.py", "apps/cli/main.py"}
    rels = extract_specifies_relations(docs, all_paths)
    assert len(rels) == 2
    dst_refs = {r.dst_ref for r in rels}
    assert dst_refs == {"libs/core/entities.py", "apps/cli/main.py"}


def test_provenance_is_docs_linker() -> None:
    docs = [("docs/x.md", "libs/foo.py")]
    rels = extract_specifies_relations(docs, {"libs/foo.py", "docs/x.md"})
    assert len(rels) == 1
    assert rels[0].provenance == "docs_linker"
