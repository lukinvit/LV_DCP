"""Tests for the at-rest encryption scaffolding helpers (ADR-007)."""

from __future__ import annotations

import pytest
from libs.core.projects_config import DaemonConfig, StorageConfig
from libs.storage.encryption import (
    MIN_KEY_LENGTH,
    EncryptionConfigError,
    encryption_enabled,
    resolve_key,
)


class TestEncryptionEnabled:
    def test_default_config_disables_encryption(self) -> None:
        assert encryption_enabled(DaemonConfig()) is False

    def test_setting_env_var_name_enables(self) -> None:
        cfg = DaemonConfig(storage=StorageConfig(encryption_key_env="LVDCP_KEY"))
        assert encryption_enabled(cfg) is True

    def test_explicit_none_disables(self) -> None:
        cfg = DaemonConfig(storage=StorageConfig(encryption_key_env=None))
        assert encryption_enabled(cfg) is False


class TestResolveKey:
    def test_empty_env_name_raises(self) -> None:
        with pytest.raises(EncryptionConfigError, match="empty"):
            resolve_key("")

    def test_unset_env_var_raises_with_var_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LVDCP_DOES_NOT_EXIST", raising=False)
        with pytest.raises(EncryptionConfigError, match="LVDCP_DOES_NOT_EXIST"):
            resolve_key("LVDCP_DOES_NOT_EXIST")

    def test_short_key_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LVDCP_SHORT_KEY", "abc")
        with pytest.raises(EncryptionConfigError, match="too short"):
            resolve_key("LVDCP_SHORT_KEY")

    def test_valid_key_returns_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        key = "x" * MIN_KEY_LENGTH
        monkeypatch.setenv("LVDCP_GOOD_KEY", key)
        assert resolve_key("LVDCP_GOOD_KEY") == key

    def test_minimum_length_is_boundary(self) -> None:
        # Sanity: the constant is at least sensible for a passphrase.
        assert MIN_KEY_LENGTH >= 8


class TestConfigIntegration:
    def test_storage_config_in_daemon_config(self) -> None:
        cfg = DaemonConfig()
        assert isinstance(cfg.storage, StorageConfig)
        assert cfg.storage.encryption_key_env is None

    def test_storage_config_round_trips_through_dict(self) -> None:
        cfg = DaemonConfig(storage=StorageConfig(encryption_key_env="MY_KEY"))
        data = cfg.model_dump()
        restored = DaemonConfig.model_validate(data)
        assert restored.storage.encryption_key_env == "MY_KEY"
