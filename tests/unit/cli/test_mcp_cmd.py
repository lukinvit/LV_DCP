"""Tests for `ctx mcp install` CLI subgroup (v0.8.64 ``ctx mcp install
--json`` opens the MCP-binding scriptability surface — symmetric to how
v0.8.62 ``ctx watch install-service --json`` opened the watch
daemon-service surface).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from apps.cli.main import app
from libs.mcp_ops.claude_cli import ClaudeCliError
from libs.mcp_ops.install import InstallResult
from typer.testing import CliRunner

# v0.8.64 schema lock for `mcp install --json`: eight top-level keys
# describing the just-installed MCP-binding state (Claude Code
# registration + on-disk CLAUDE.md managed section + lvdcp config bootstrap
# + hook scripts). Locked here so any evolution of the descriptor
# (e.g. a future `claude_cli_version` field, a `hook_settings_path`
# field) becomes a reviewed schema change rather than a silent payload
# drift. Same frozenset discipline as v0.8.44/v0.8.49/v0.8.54/
# v0.8.56-v0.8.63.
_MCP_INSTALL_JSON_KEYS = frozenset(
    {
        "scope",
        "entry_command",
        "entry_args",
        "claudemd_path",
        "config_path",
        "config_created",
        "version",
        "hooks_installed",
    }
)

# v0.8.64 dry-run snippet shape — `--json --dry-run` emits this exact
# Claude Desktop config snippet shape (same as `build_dry_run_snippet`
# but without the `# Copy the following ...` comment header so `jq`
# parses it as-is).
_MCP_DRY_RUN_TOP_KEYS = frozenset({"mcpServers"})


@pytest.fixture
def _isolated_mcp_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path]:
    """Redirect every on-disk side effect of `ctx mcp install` to tmp_path.

    Three things must be isolated:
    1. ``DEFAULT_CONFIG_PATH`` (the lvdcp config) — so we never rewrite
       the real `~/.lvdcp/config.yaml` from a unit test.
    2. ``_resolve_claudemd_path`` — so the managed section never lands
       in the developer's real `~/.claude/CLAUDE.md`.
    3. ``_HOOKS_DST`` — so `_install_hooks` writes hook scripts to a
       throwaway directory and never pollutes `~/.claude/hooks`.

    Returns ``(claudemd_path, config_path, hooks_dst)`` so tests can
    assert against the same paths the CLI writes to.
    """
    claudemd_path = tmp_path / "CLAUDE.md"
    config_path = tmp_path / "config.yaml"
    hooks_dst = tmp_path / "hooks"

    monkeypatch.setattr("apps.cli.commands.mcp_cmd.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        "apps.cli.commands.mcp_cmd._resolve_claudemd_path",
        lambda scope: claudemd_path,
    )
    monkeypatch.setattr("apps.cli.commands.mcp_cmd._HOOKS_DST", hooks_dst)

    # Also redirect the settings.json path used by _install_hooks so the
    # test never touches the real ~/.claude/settings.json.
    settings_path = tmp_path / "settings.json"

    def _fake_install_hooks() -> list[str]:
        # Minimal stand-in: write a single stub hook file and update the
        # tmp settings.json. The real _install_hooks() reads from a hook
        # source directory shipped in the repo; we don't need that here
        # — what the test cares about is the JSON descriptor's
        # `hooks_installed` array, not the hook script contents.
        hooks_dst.mkdir(parents=True, exist_ok=True)
        stub = hooks_dst / "lvdcp-precheck.sh"
        stub.write_text("#!/bin/bash\necho stub\n", encoding="utf-8")
        stub.chmod(0o755)
        settings_path.write_text(
            json.dumps({"hooks": {}}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return [str(stub)]

    monkeypatch.setattr("apps.cli.commands.mcp_cmd._install_hooks", _fake_install_hooks)

    return claudemd_path, config_path, hooks_dst


@pytest.fixture
def _stub_install_lvdcp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ``install_lvdcp`` with a stub that returns a deterministic
    ``InstallResult`` without touching the real `claude` CLI or writing
    to the developer's `~/.claude/CLAUDE.md`. The real `claude mcp add`
    is **never** invoked from tests.
    """

    def _fake_install_lvdcp(
        *,
        claudemd_path: Path,
        config_path: Path,
        entry_command: str,
        entry_args: list[str],
        scope: str,
        version: str,
    ) -> InstallResult:
        # Bootstrap the config file so `config_created=True` matches a
        # fresh-install state. Tests that want `config_created=False`
        # should pre-create the file before calling the CLI.
        config_created = not config_path.exists()
        if config_created:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("version: 1\nprojects: []\n", encoding="utf-8")
        return InstallResult(
            entry_command=entry_command,
            entry_args=list(entry_args),
            scope=scope,
            claudemd_path=claudemd_path,
            config_path=config_path,
            config_created=config_created,
            version=version,
        )

    monkeypatch.setattr("apps.cli.commands.mcp_cmd.install_lvdcp", _fake_install_lvdcp)


def test_mcp_install_text_output_unchanged_full_install(
    _isolated_mcp_paths: tuple[Path, Path, Path],
    _stub_install_lvdcp: None,
) -> None:
    """Text-mode output must stay byte-identical to the legacy chrome
    (`lvdcp MCP server registered ... / CLAUDE.md managed section: ... /
    config bootstrapped: ... / entry point: ... / hook installed: ... /
    hooks: PreToolUse ... / note: entry point contains ...`). Adding
    ``--json`` must not regress the default render — pre-existing
    automation grepping these lines must see no diff.
    """
    claudemd_path, config_path, _hooks_dst = _isolated_mcp_paths

    result = CliRunner().invoke(app, ["mcp", "install"])
    assert result.exit_code == 0, result.stdout

    # Legacy chrome lines preserved bytewise.
    assert "lvdcp MCP server registered (scope=user)" in result.stdout
    assert f"CLAUDE.md managed section: {claudemd_path}" in result.stdout
    assert f"config bootstrapped:       {config_path}" in result.stdout
    assert "entry point:" in result.stdout
    assert "hook installed:" in result.stdout
    assert "hooks: PreToolUse" in result.stdout
    assert "note: entry point contains" in result.stdout

    # Sanity: text mode must not leak JSON syntax (`{` only appears in
    # the legacy chrome inside parentheses, never as a top-level
    # JSON object).
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)


def test_mcp_install_json_emits_schema_locked_descriptor_full_install(
    _isolated_mcp_paths: tuple[Path, Path, Path],
    _stub_install_lvdcp: None,
) -> None:
    """JSON-mode output must be a single object with the eight
    schema-locked keys, field-by-field round-trip values, and **no**
    text chrome on stdout. Locks the v0.8.64 contract against silent
    payload drift — any future field addition becomes a reviewed
    schema change via the frozenset.
    """
    claudemd_path, config_path, _hooks_dst = _isolated_mcp_paths

    result = CliRunner().invoke(app, ["mcp", "install", "--json"])
    assert result.exit_code == 0, result.stdout

    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    assert frozenset(payload.keys()) == _MCP_INSTALL_JSON_KEYS

    # Field-by-field round-trip.
    assert payload["scope"] == "user"
    assert payload["entry_command"]  # sys.executable, non-empty
    assert payload["entry_args"] == ["-m", "apps.mcp.server"]
    assert payload["claudemd_path"] == str(claudemd_path)
    assert payload["config_path"] == str(config_path)
    assert payload["config_created"] is True
    assert payload["version"]  # LVDCP_VERSION, non-empty
    assert isinstance(payload["hooks_installed"], list)
    assert len(payload["hooks_installed"]) == 1
    assert payload["hooks_installed"][0].endswith("lvdcp-precheck.sh")

    # Chrome NOT on stdout — the legacy text lines must not leak when
    # --json is set.
    assert "lvdcp MCP server registered" not in result.stdout
    assert "CLAUDE.md managed section" not in result.stdout
    assert "hook installed:" not in result.stdout
    assert "note: entry point contains" not in result.stdout


def test_mcp_install_json_config_already_exists_is_false(
    _isolated_mcp_paths: tuple[Path, Path, Path],
    _stub_install_lvdcp: None,
) -> None:
    """`config_created=False` is the explicit signal that distinguishes
    a re-install over an existing config from a fresh install. Lets a
    script tell `jq -e '.config_created == false'` for the "we already
    had a config, just refreshed the registration" branch.
    """
    claudemd_path, config_path, _hooks_dst = _isolated_mcp_paths

    # Pre-create the config so the stub install sees it as existing.
    config_path.write_text("version: 1\nprojects: []\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["mcp", "install", "--json"])
    assert result.exit_code == 0, result.stdout

    payload = json.loads(result.stdout)
    assert payload["config_created"] is False
    # The other fields still round-trip identically — only
    # `config_created` flips.
    assert frozenset(payload.keys()) == _MCP_INSTALL_JSON_KEYS
    assert payload["claudemd_path"] == str(claudemd_path)


def test_mcp_install_json_dry_run_emits_snippet_alone_no_comment_header(
    _isolated_mcp_paths: tuple[Path, Path, Path],
) -> None:
    """`--json --dry-run` must emit the planned-config snippet alone (no
    `# Copy the following ...` comment header) so the output parses
    with `jq` as-is. Also verifies the dry-run path never invokes the
    stubbed `install_lvdcp` — config file must not be created.
    """
    _claudemd_path, config_path, _hooks_dst = _isolated_mcp_paths

    result = CliRunner().invoke(app, ["mcp", "install", "--json", "--dry-run"])
    assert result.exit_code == 0, result.stdout

    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    assert frozenset(payload.keys()) == _MCP_DRY_RUN_TOP_KEYS
    assert "lvdcp" in payload["mcpServers"]
    server = payload["mcpServers"]["lvdcp"]
    assert server["args"] == ["-m", "apps.mcp.server"]
    assert server["command"]  # sys.executable, non-empty

    # The comment header must NOT appear — it would break `jq` parsing.
    assert "# Copy the following" not in result.stdout

    # Dry-run must not touch disk — config file should not be created
    # (the stub `_install_lvdcp` was never invoked because dry_run
    # short-circuits before it).
    assert not config_path.exists()


def test_mcp_install_json_claude_cli_error_exits_1_with_no_stdout_payload(
    _isolated_mcp_paths: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ClaudeCliError` from a missing `claude` CLI must exit 1 with the
    error on stderr and **no** success-shape JSON payload on stdout.
    Locks the v0.8.42-v0.8.63 error-vs-success boundary so a refactor
    that swallows the launchctl-style error into a `{"error": "..."}`
    stdout payload breaks this test.
    """

    def _raise_claude_cli_error(**_: object) -> InstallResult:
        raise ClaudeCliError("claude CLI not found on PATH")

    monkeypatch.setattr("apps.cli.commands.mcp_cmd.install_lvdcp", _raise_claude_cli_error)

    result = CliRunner().invoke(app, ["mcp", "install", "--json"])
    assert result.exit_code == 1

    # No success-shape JSON on stdout — error must not look like success.
    # (Same `pytest.raises(json.JSONDecodeError)` pattern as v0.8.62
    # `test_install_service_json_launchctl_error_exits_3_no_payload`.)
    if result.stdout.strip():
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.stdout)

    # Error chrome lands on stderr per v0.8.42 structlog discipline; on
    # CliRunner without `mix_stderr=False`, stderr lands on `output`.
    combined = (result.stdout or "") + (result.output or "")
    assert "claude CLI not found" in combined or "error:" in combined
