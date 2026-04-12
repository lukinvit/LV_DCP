"""Tests for Russian morphological stemmer."""

from __future__ import annotations

from libs.retrieval.stemmer import normalize_query, normalize_text, normalize_token


class TestNormalizeToken:
    def test_russian_noun_accusative(self) -> None:
        assert normalize_token("подключениями") == "подключение"

    def test_russian_verb_conjugated(self) -> None:
        assert normalize_token("проверяются") == "проверяться"

    def test_russian_adjective(self) -> None:
        result = normalize_token("телеграмных")
        assert result != "телеграмных"  # should normalize

    def test_english_word_unchanged(self) -> None:
        assert normalize_token("Connection") == "connection"

    def test_mixed_token_with_cyrillic(self) -> None:
        assert normalize_token("vpn") == "vpn"

    def test_empty_string(self) -> None:
        assert normalize_token("") == ""

    def test_numbers_pass_through(self) -> None:
        assert normalize_token("12345") == "12345"


class TestNormalizeQuery:
    def test_russian_query_normalized(self) -> None:
        result = normalize_query("сбор данных из телеграм каналов")
        assert "канал" in result  # каналов → канал

    def test_english_query_lowercased(self) -> None:
        assert normalize_query("Telegram Client") == "telegram client"

    def test_mixed_query(self) -> None:
        result = normalize_query("telegram подключениями api")
        assert "telegram" in result
        assert "подключение" in result
        assert "api" in result


class TestNormalizeText:
    def test_normalizes_russian_in_text(self) -> None:
        text = "обрабатывает команды администратора"
        result = normalize_text(text)
        assert "команда" in result
        assert "администратор" in result

    def test_preserves_english_in_text(self) -> None:
        text = "class Widget:\n    def render(self)"
        result = normalize_text(text)
        assert "class" in result
        assert "widget" in result
        assert "render" in result

    def test_preserves_code_structure(self) -> None:
        text = "def process_data(self, items):\n    return items"
        result = normalize_text(text)
        assert "process_data" in result or "process" in result
        assert "items" in result
