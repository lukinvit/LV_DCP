from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from libs.core.projects_config import DaemonConfig, LLMConfig
from libs.mcp_ops.doctor import (
    CheckStatus,
    DoctorReport,
    check_claude_cli_present,
    check_claudemd_managed_section,
    check_config_yaml_valid,
    check_legacy_pollution,
    check_llm_budget,
    check_llm_provider,
    check_mcp_list_contains_lvdcp,
    check_project_caches,
    render_json,
    render_table,
    run_doctor,
)

# ---------- Individual check tests ----------


def test_check_claude_cli_pass() -> None:
    with patch("libs.mcp_ops.doctor.has_claude_cli", return_value=True):
        check = check_claude_cli_present()
    assert check.status == CheckStatus.PASS


def test_check_claude_cli_warn() -> None:
    with patch("libs.mcp_ops.doctor.has_claude_cli", return_value=False):
        check = check_claude_cli_present()
    assert check.status == CheckStatus.WARN
    assert "install" in check.hint.lower()


def test_check_mcp_list_contains_lvdcp_pass() -> None:
    with patch(
        "libs.mcp_ops.doctor.claude_mcp_list",
        return_value="lvdcp: Connected\nother: Disconnected\n",
    ):
        check = check_mcp_list_contains_lvdcp()
    assert check.status == CheckStatus.PASS


def test_check_mcp_list_fail_when_missing() -> None:
    with patch("libs.mcp_ops.doctor.claude_mcp_list", return_value="other: Connected\n"):
        check = check_mcp_list_contains_lvdcp()
    assert check.status == CheckStatus.FAIL
    assert "ctx mcp install" in check.hint


def test_check_config_yaml_pass(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("version: 1\nprojects: []\n")
    check = check_config_yaml_valid(config)
    assert check.status == CheckStatus.PASS


def test_check_config_yaml_fail_on_missing(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    check = check_config_yaml_valid(config)
    assert check.status == CheckStatus.FAIL
    assert "ctx mcp install" in check.hint


def test_check_config_yaml_fail_on_malformed(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("version: not-an-int\nprojects: 42\n")
    check = check_config_yaml_valid(config)
    assert check.status == CheckStatus.FAIL


def test_check_project_caches_pass_empty(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("version: 1\nprojects: []\n")
    check = check_project_caches(config)
    assert check.status == CheckStatus.PASS


def test_check_project_caches_warn_missing(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config.write_text(
        f"version: 1\nprojects:\n  - root: {project_root}\n    registered_at_iso: 2026-01-01T00:00:00Z\n    last_scan_at_iso: null\n    last_scan_status: pending\n"
    )
    check = check_project_caches(config)
    assert check.status == CheckStatus.WARN


def test_check_claudemd_managed_missing_file(tmp_path: Path) -> None:
    claudemd = tmp_path / "CLAUDE.md"
    check = check_claudemd_managed_section(claudemd, expected_version="0.0.0")
    assert check.status == CheckStatus.WARN


def test_check_claudemd_managed_version_match(tmp_path: Path) -> None:
    claudemd = tmp_path / "CLAUDE.md"
    claudemd.write_text(
        "<!-- LV_DCP-managed-section:start:v1 -->\n"
        "<!-- lvdcp-managed-version: 0.0.0 -->\n"
        "content\n"
        "<!-- LV_DCP-managed-section:end:v1 -->\n"
    )
    check = check_claudemd_managed_section(claudemd, expected_version="0.0.0")
    assert check.status == CheckStatus.PASS


def test_check_claudemd_managed_version_mismatch(tmp_path: Path) -> None:
    claudemd = tmp_path / "CLAUDE.md"
    claudemd.write_text(
        "<!-- LV_DCP-managed-section:start:v1 -->\n"
        "<!-- lvdcp-managed-version: 0.0.1 -->\n"
        "content\n"
        "<!-- LV_DCP-managed-section:end:v1 -->\n"
    )
    check = check_claudemd_managed_section(claudemd, expected_version="0.0.2")
    assert check.status == CheckStatus.WARN


def test_check_legacy_pollution_warn(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"mcpServers": {"lvdcp": {"command": "x"}}}))
    check = check_legacy_pollution(settings)
    assert check.status == CheckStatus.WARN
    assert "legacy-clean" in check.hint


def test_check_legacy_pollution_pass_when_clean(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"permissions": {}}))
    check = check_legacy_pollution(settings)
    assert check.status == CheckStatus.PASS


# ---------- Report / rendering tests ----------


def _fresh_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    (tmp_path / "config.yaml").write_text("version: 1\nprojects: []\n")
    (tmp_path / "CLAUDE.md").write_text(
        "<!-- LV_DCP-managed-section:start:v1 -->\n"
        "<!-- lvdcp-managed-version: 0.0.0 -->\n"
        "content\n"
        "<!-- LV_DCP-managed-section:end:v1 -->\n"
    )
    (tmp_path / "settings.json").write_text("{}")
    return tmp_path / "config.yaml", tmp_path / "CLAUDE.md", tmp_path / "settings.json"


def test_run_doctor_returns_report_with_9_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LVDCP_SUMMARIES_DB", str(tmp_path / "summaries.db"))
    config, claudemd, settings = _fresh_paths(tmp_path)
    with (
        patch("libs.mcp_ops.doctor.has_claude_cli", return_value=True),
        patch("libs.mcp_ops.doctor.claude_mcp_list", return_value="lvdcp: Connected\n"),
        patch("libs.mcp_ops.doctor._run_handshake", return_value=True),
    ):
        report = run_doctor(
            config_path=config,
            claudemd_path=claudemd,
            settings_legacy_path=settings,
            expected_version="0.0.0",
        )
    assert isinstance(report, DoctorReport)
    assert len(report.checks) == 9


def test_report_exit_code_zero_when_all_pass(tmp_path: Path) -> None:
    config, claudemd, settings = _fresh_paths(tmp_path)
    with (
        patch("libs.mcp_ops.doctor.has_claude_cli", return_value=True),
        patch("libs.mcp_ops.doctor.claude_mcp_list", return_value="lvdcp: Connected\n"),
        patch("libs.mcp_ops.doctor._run_handshake", return_value=True),
    ):
        report = run_doctor(
            config_path=config,
            claudemd_path=claudemd,
            settings_legacy_path=settings,
            expected_version="0.0.0",
        )
    assert report.exit_code == 0


def test_report_exit_code_one_when_any_warn(tmp_path: Path) -> None:
    config, claudemd, settings = _fresh_paths(tmp_path)
    with (
        patch("libs.mcp_ops.doctor.has_claude_cli", return_value=False),  # WARN
        patch("libs.mcp_ops.doctor.claude_mcp_list", return_value="lvdcp: Connected\n"),
        patch("libs.mcp_ops.doctor._run_handshake", return_value=True),
    ):
        report = run_doctor(
            config_path=config,
            claudemd_path=claudemd,
            settings_legacy_path=settings,
            expected_version="0.0.0",
        )
    assert report.exit_code == 1


def test_report_exit_code_two_when_any_fail(tmp_path: Path) -> None:
    with (
        patch("libs.mcp_ops.doctor.has_claude_cli", return_value=True),
        patch("libs.mcp_ops.doctor.claude_mcp_list", return_value="other: Connected\n"),  # FAIL
        patch("libs.mcp_ops.doctor._run_handshake", return_value=False),
    ):
        report = run_doctor(
            config_path=tmp_path / "nothing.yaml",
            claudemd_path=tmp_path / "CLAUDE.md",
            settings_legacy_path=tmp_path / "settings.json",
            expected_version="0.0.0",
        )
    assert report.exit_code == 2


def test_render_table_contains_status(tmp_path: Path) -> None:
    config, claudemd, settings = _fresh_paths(tmp_path)
    with (
        patch("libs.mcp_ops.doctor.has_claude_cli", return_value=True),
        patch("libs.mcp_ops.doctor.claude_mcp_list", return_value="lvdcp: Connected\n"),
        patch("libs.mcp_ops.doctor._run_handshake", return_value=True),
    ):
        report = run_doctor(
            config_path=config,
            claudemd_path=claudemd,
            settings_legacy_path=settings,
            expected_version="0.0.0",
        )
    text = render_table(report)
    assert "PASS" in text
    assert "Result:" in text


def test_render_json_parses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LVDCP_SUMMARIES_DB", str(tmp_path / "summaries.db"))
    config, claudemd, settings = _fresh_paths(tmp_path)
    with (
        patch("libs.mcp_ops.doctor.has_claude_cli", return_value=True),
        patch("libs.mcp_ops.doctor.claude_mcp_list", return_value="lvdcp: Connected\n"),
        patch("libs.mcp_ops.doctor._run_handshake", return_value=True),
    ):
        report = run_doctor(
            config_path=config,
            claudemd_path=claudemd,
            settings_legacy_path=settings,
            expected_version="0.0.0",
        )
    rendered = render_json(report)
    parsed = json.loads(rendered)
    assert parsed["exit_code"] == report.exit_code
    assert len(parsed["checks"]) == 9


# ---------- LLM provider check tests ----------


def test_check_llm_provider_disabled_passes() -> None:
    config = DaemonConfig(llm=LLMConfig(enabled=False))
    check = check_llm_provider(config)
    assert check.status == CheckStatus.PASS
    assert "disabled" in check.detail


def test_check_llm_provider_warns_if_env_var_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = DaemonConfig(llm=LLMConfig(enabled=True, api_key_env_var="OPENAI_API_KEY"))
    check = check_llm_provider(config)
    assert check.status == CheckStatus.WARN
    assert "OPENAI_API_KEY" in check.detail


# ---------- LLM budget check tests ----------


def test_check_llm_budget_disabled_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LVDCP_SUMMARIES_DB", str(tmp_path / "summaries.db"))
    config = DaemonConfig(llm=LLMConfig(enabled=False))
    check = check_llm_budget(config)
    assert check.status == CheckStatus.PASS


def test_check_llm_budget_fails_at_100_percent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from libs.summaries.store import SummaryRow, SummaryStore

    monkeypatch.setenv("LVDCP_SUMMARIES_DB", str(tmp_path / "summaries.db"))
    store = SummaryStore(tmp_path / "summaries.db")
    store.migrate()
    store.persist(
        SummaryRow(
            content_hash="h",
            prompt_version="v1",
            model_name="gpt-4o-mini",
            project_root="/p",
            file_path="f.py",
            summary_text="t",
            cost_usd=30.0,
            tokens_in=1,
            tokens_out=1,
            tokens_cached=0,
            created_at=time.time() - 86400,
        )
    )
    store.close()

    config = DaemonConfig(llm=LLMConfig(enabled=True, monthly_budget_usd=25.0))
    check = check_llm_budget(config)
    assert check.status == CheckStatus.FAIL
