from __future__ import annotations

from pathlib import Path

import yaml
from libs.core.projects_config import DaemonConfig, LLMConfig, load_config


def test_llm_config_defaults() -> None:
    cfg = LLMConfig()
    assert cfg.provider == "openai"
    assert cfg.summary_model == "gpt-4o-mini"
    assert cfg.rerank_model == "gpt-4o-mini"
    assert cfg.api_key_env_var == "OPENAI_API_KEY"
    assert cfg.monthly_budget_usd == 25.0
    assert cfg.prompt_version == "v1"
    assert cfg.enabled is False


def test_daemon_config_has_llm_field() -> None:
    cfg = DaemonConfig()
    assert isinstance(cfg.llm, LLMConfig)
    assert cfg.llm.enabled is False


def test_backwards_compat_load_config_without_llm_section(tmp_path: Path) -> None:
    """Phase 3a/3b config.yaml (no llm: section) must still parse."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"version": 1, "projects": []}, sort_keys=False))
    cfg = load_config(config_path)
    assert cfg.llm.enabled is False


def test_load_config_with_explicit_llm_section(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "projects": [],
                "llm": {
                    "provider": "anthropic",
                    "summary_model": "claude-haiku-4-5",
                    "enabled": True,
                    "monthly_budget_usd": 50.0,
                },
            },
            sort_keys=False,
        )
    )
    cfg = load_config(config_path)
    assert cfg.llm.provider == "anthropic"
    assert cfg.llm.summary_model == "claude-haiku-4-5"
    assert cfg.llm.enabled is True
    assert cfg.llm.monthly_budget_usd == 50.0
    assert cfg.llm.api_key_env_var == "OPENAI_API_KEY"  # default still applied
