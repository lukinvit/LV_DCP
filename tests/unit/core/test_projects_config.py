from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from libs.core.projects_config import (
    DaemonConfig,
    ProjectEntry,
    WikiConfig,
    load_config,
    save_config,
)


def test_wiki_config_dirty_threshold_default() -> None:
    cfg = WikiConfig()
    assert cfg.dirty_threshold == 3


def test_wiki_config_max_workers_default() -> None:
    cfg = WikiConfig()
    assert cfg.max_workers == 1


def test_wiki_config_from_dict() -> None:
    cfg = WikiConfig.model_validate({"dirty_threshold": 5, "max_workers": 2})
    assert cfg.dirty_threshold == 5
    assert cfg.max_workers == 2


def test_daemon_config_wiki_dirty_threshold_propagates() -> None:
    cfg = DaemonConfig.model_validate({"wiki": {"dirty_threshold": 7, "max_workers": 2}})
    assert cfg.wiki.dirty_threshold == 7
    assert cfg.wiki.max_workers == 2


# ---- save_config atomic write (v0.8.33) -----------------------------------


def test_save_config_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    cfg = DaemonConfig(
        projects=[ProjectEntry(root=tmp_path / "proj", registered_at_iso="2026-04-24T00:00:00Z")]
    )
    save_config(path, cfg)
    assert path.exists()

    reloaded = load_config(path)
    assert len(reloaded.projects) == 1
    assert str(reloaded.projects[0].root) == str(tmp_path / "proj")


def test_save_config_leaves_no_tmp_file(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    save_config(path, DaemonConfig())
    assert not (tmp_path / "config.yaml.tmp").exists()


def test_save_config_overwrites_existing_atomically(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump({"projects": [{"root": "/old", "registered_at_iso": "2025-01-01"}]}),
        encoding="utf-8",
    )

    save_config(path, DaemonConfig())  # empty config should replace the stale payload
    reloaded = load_config(path)
    assert reloaded.projects == []


# ---- v0.8.34: chmod + crash-atomicity + allow_unicode --------------------


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX perms only")
def test_save_config_applies_owner_only_perms(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    save_config(path, DaemonConfig())
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600


def test_save_config_preserves_original_on_rename_failure(tmp_path: Path) -> None:
    """If `tmp.replace(path)` raises, the pre-existing config must survive."""
    path = tmp_path / "config.yaml"
    original_bytes = yaml.safe_dump(
        {"projects": [{"root": str(tmp_path / "kept"), "registered_at_iso": "2026-01-01"}]}
    ).encode("utf-8")
    path.write_bytes(original_bytes)

    def _boom(_self: Path, _dst: Path) -> None:
        raise OSError("disk full")

    with (
        patch("pathlib.Path.replace", _boom),
        pytest.raises(OSError, match="disk full"),
    ):
        save_config(path, DaemonConfig())

    # Original file unchanged, temp cleaned up.
    assert path.read_bytes() == original_bytes
    assert not (tmp_path / "config.yaml.tmp").exists()


def test_save_config_preserves_unicode_project_names(tmp_path: Path) -> None:
    """allow_unicode=True keeps Cyrillic / emoji project paths readable."""
    path = tmp_path / "config.yaml"
    cfg = DaemonConfig(
        projects=[
            ProjectEntry(
                root=tmp_path / "проект-рф",
                registered_at_iso="2026-04-24T00:00:00Z",
            )
        ]
    )
    save_config(path, cfg)
    text = path.read_text(encoding="utf-8")
    assert "проект-рф" in text  # not escaped to \u...

    reloaded = load_config(path)
    assert str(reloaded.projects[0].root).endswith("проект-рф")


def test_save_config_survives_chmod_failure(tmp_path: Path) -> None:
    """chmod is best-effort — a filesystem that rejects it must not crash save."""
    path = tmp_path / "config.yaml"

    real_chmod = os.chmod

    def _chmod_fails(target: object, mode: int) -> None:
        # Fail only on our config target; allow pytest's own chmod calls through.
        if str(target).endswith("config.yaml"):
            raise OSError("fs does not support chmod")
        real_chmod(target, mode)

    with patch("pathlib.Path.chmod", lambda self, mode: _chmod_fails(str(self), mode)):
        save_config(path, DaemonConfig())  # must not raise

    assert path.exists()
    reloaded = load_config(path)
    assert reloaded.projects == []
