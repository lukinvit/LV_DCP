from __future__ import annotations

from libs.core.projects_config import WikiConfig


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
    from libs.core.projects_config import DaemonConfig

    cfg = DaemonConfig.model_validate({"wiki": {"dirty_threshold": 7, "max_workers": 2}})
    assert cfg.wiki.dirty_threshold == 7
    assert cfg.wiki.max_workers == 2
