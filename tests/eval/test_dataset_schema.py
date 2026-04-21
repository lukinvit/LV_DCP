"""Unit tests for libs/eval/dataset_schema (see specs/006-ragas-promptfoo-eval)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from libs.eval.dataset_schema import (
    GoldQuery,
    load_all_gold_datasets,
    load_gold_dataset,
)


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_gold_query_minimal_fields() -> None:
    q = GoldQuery.model_validate(
        {
            "id": "q01",
            "text": "session factory",
            "mode": "navigate",
            "expected": {"files": ["libs/auth/session.py"], "symbols": []},
        }
    )
    assert q.id == "q01"
    assert q.mode == "navigate"
    assert q.tags == []
    assert q.notes is None
    assert q.expected.answer_text is None


def test_gold_query_full_fields() -> None:
    q = GoldQuery.model_validate(
        {
            "id": "q02",
            "text": "rare UUID",
            "mode": "edit",
            "expected": {
                "files": ["a.py"],
                "symbols": ["a.b"],
                "answer_text": "the thing is here",
            },
            "notes": "tricky",
            "tags": ["rare", "uuid"],
        }
    )
    assert q.notes == "tricky"
    assert q.tags == ["rare", "uuid"]
    assert q.expected.answer_text == "the thing is here"


def test_gold_query_rejects_unknown_mode() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GoldQuery.model_validate(
            {
                "id": "q03",
                "text": "t",
                "mode": "navigateX",
                "expected": {"files": [], "symbols": []},
            }
        )


def test_load_gold_dataset_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "ds.yaml"
    _write_yaml(
        path,
        {
            "queries": [
                {
                    "id": "q01",
                    "text": "session factory",
                    "mode": "navigate",
                    "expected": {"files": ["a.py"], "symbols": []},
                }
            ]
        },
    )
    queries = load_gold_dataset(path)
    assert len(queries) == 1
    assert queries[0].id == "q01"


def test_load_gold_dataset_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_gold_dataset(tmp_path / "nope.yaml")


def test_load_gold_dataset_malformed(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    _write_yaml(
        path,
        {"queries": [{"id": "q01", "text": "t", "mode": "navigate"}]},  # missing expected
    )
    with pytest.raises(ValueError, match="invalid gold dataset"):
        load_gold_dataset(path)


def test_load_all_gold_datasets(tmp_path: Path) -> None:
    p1 = tmp_path / "a.yaml"
    p2 = tmp_path / "b.yaml"
    _write_yaml(
        p1,
        {
            "queries": [
                {
                    "id": "a1",
                    "text": "t",
                    "mode": "navigate",
                    "expected": {"files": [], "symbols": []},
                }
            ]
        },
    )
    _write_yaml(
        p2,
        {
            "queries": [
                {
                    "id": "b1",
                    "text": "t",
                    "mode": "edit",
                    "expected": {"files": [], "symbols": []},
                }
            ]
        },
    )
    queries = load_all_gold_datasets([p1, p2])
    assert [q.id for q in queries] == ["a1", "b1"]
