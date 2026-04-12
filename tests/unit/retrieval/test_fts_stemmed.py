"""Tests for FTS5 with Russian stemming support."""

from __future__ import annotations

from pathlib import Path

import pytest

from libs.retrieval.fts import FtsIndex


@pytest.fixture()
def fts_db(tmp_path: Path) -> FtsIndex:
    fts = FtsIndex(tmp_path / "fts.db")
    fts.create()
    return fts


class TestStemmedFtsSearch:
    def test_russian_query_matches_russian_content(self, fts_db: FtsIndex) -> None:
        fts_db.index_file("bot/vpn.py", "class VpnPeer:\n    подключение к серверу")
        results = fts_db.search("подключениями к серверу")
        assert len(results) >= 1
        assert results[0][0] == "bot/vpn.py"

    def test_russian_verb_form_matches_infinitive(self, fts_db: FtsIndex) -> None:
        fts_db.index_file("lib/checker.py", "def validate():\n    проверять данные")
        results = fts_db.search("проверяются данные")
        assert len(results) >= 1

    def test_english_still_works(self, fts_db: FtsIndex) -> None:
        fts_db.index_file("app/main.py", "class Application:\n    def connect(self)")
        results = fts_db.search("connection")
        assert len(results) >= 1
        assert results[0][0] == "app/main.py"

    def test_mixed_russian_english_query(self, fts_db: FtsIndex) -> None:
        fts_db.index_file("bot/client.py", "telegram подключение client")
        results = fts_db.search("telegram подключениями")
        assert len(results) >= 1

    def test_original_content_still_searchable(self, fts_db: FtsIndex) -> None:
        fts_db.index_file("bot/vpn.py", "подключениями к серверу")
        results = fts_db.search("подключениями")
        assert len(results) >= 1

    def test_russian_single_word_morphology(self, fts_db: FtsIndex) -> None:
        """Single-word query: different morphological form must still match."""
        fts_db.index_file("a.py", "подключение к серверу")
        results = fts_db.search("подключениями")
        assert len(results) >= 1
        assert results[0][0] == "a.py"

    def test_russian_verb_single_word_morphology(self, fts_db: FtsIndex) -> None:
        """Verb conjugation must match infinitive via stemmer."""
        fts_db.index_file("b.py", "проверять данные")
        results = fts_db.search("проверяет")
        assert len(results) >= 1
