"""Scaffolding helpers for at-rest cache encryption (see ADR-007).

This module exposes two stateless helpers used by the (future) encrypted
cache path and by the one-time migration command. It deliberately does
not import SQLCipher — the binary dependency is gated behind the
``lv-dcp[storage-encrypted]`` extra and loaded only when the connection
layer actually needs it.
"""

from __future__ import annotations

import os

from libs.core.projects_config import DaemonConfig

# Minimum acceptable passphrase length. SQLCipher itself accepts any
# non-empty key, but short keys defeat the purpose; enforce a floor so
# users don't set "1234" and feel protected.
MIN_KEY_LENGTH = 12


class EncryptionConfigError(ValueError):
    """Raised when encryption is requested but the environment is not set up."""


def encryption_enabled(config: DaemonConfig) -> bool:
    """Return True when the config requests an encrypted cache."""
    return config.storage.encryption_key_env is not None


def resolve_key(env_name: str) -> str:
    """Read the passphrase from the named environment variable.

    Raises :class:`EncryptionConfigError` when:
    - *env_name* is empty or None-like
    - the env var is unset
    - the value is shorter than :data:`MIN_KEY_LENGTH`

    The resolved key is returned as a string. Callers are responsible for
    passing it through ``PRAGMA key = ...`` or the SQLCipher API — this
    helper never touches the database.
    """
    if not env_name:
        raise EncryptionConfigError(
            "storage.encryption_key_env is empty — set the env-var name in "
            "~/.lvdcp/config.yaml (e.g. LVDCP_STORAGE_KEY)."
        )
    value = os.environ.get(env_name)
    if value is None:
        raise EncryptionConfigError(
            f"encryption enabled but ${env_name} is not set in the environment"
        )
    if len(value) < MIN_KEY_LENGTH:
        raise EncryptionConfigError(
            f"${env_name} is too short ({len(value)} chars) — minimum "
            f"{MIN_KEY_LENGTH}. Pick a longer passphrase."
        )
    return value
