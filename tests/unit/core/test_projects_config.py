from __future__ import annotations

from pathlib import Path

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
