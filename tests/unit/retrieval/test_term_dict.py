"""Tests for dual-language term dictionary."""
from __future__ import annotations

from libs.retrieval.term_dict import expand_query


def test_russian_to_english_expansion() -> None:
    result = expand_query("подключение к серверу")
    assert "connection" in result
    assert "server" in result


def test_english_to_russian_expansion() -> None:
    result = expand_query("telegram client connection")
    assert "подключение" in result or "клиент" in result


def test_no_expansion_when_no_matches() -> None:
    result = expand_query("hello world")
    assert result == "hello world"


def test_mixed_query_expands_both() -> None:
    result = expand_query("сбор данных telegram channel")
    assert "collection" in result
    assert "data" in result
    assert "канал" in result


def test_does_not_duplicate() -> None:
    result = expand_query("connection подключение")
    # Already has both, shouldn't add duplicates
    assert result.count("connection") == 1


def test_telegram_scraping_query() -> None:
    result = expand_query("сбор данных из телеграм каналов")
    assert "collection" in result
    assert "data" in result
    assert "telegram" in result
    assert "channel" in result
