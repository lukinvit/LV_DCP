"""Tests for the authentication service."""

import pytest

from app.services.auth import hash_password


def test_hash_password_is_deterministic() -> None:
    assert hash_password("hunter2") == hash_password("hunter2")


def test_hash_password_changes_with_input() -> None:
    assert hash_password("a") != hash_password("b")
