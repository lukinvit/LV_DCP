"""`ctx mcp doctor` checks.

Runs 9 independent checks:
1. claude CLI present                         (WARN if missing)
2. claude mcp list contains lvdcp              (FAIL if missing)
3. MCP stdio handshake responds in < 3s        (FAIL if no response)
4. ~/.lvdcp/config.yaml readable + valid       (FAIL if missing or malformed)
5. Registered projects have .context/cache.db  (WARN per missing)
6. CLAUDE.md managed section + version match   (WARN if missing or mismatch)
7. No legacy pollution in settings.json        (WARN if found)
8. LLM provider reachable + API key present    (WARN if unreachable)
9. LLM monthly budget not exceeded             (FAIL if exceeded, WARN if >=80%)

Exit codes: 0 = all PASS, 1 = any WARN, 2 = any FAIL.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import yaml

from libs.core.projects_config import DaemonConfig, load_config
from libs.llm.errors import LLMConfigError, LLMProviderError
from libs.llm.registry import create_client
from libs.mcp_ops.claude_cli import (
    ClaudeCliError,
    claude_mcp_list,
    has_claude_cli,
)
from libs.status.budget import compute_budget_status

HANDSHAKE_TIMEOUT_SECONDS = 3.0
# Spec-010 FR-008: a timeline store is considered "stale" when its
# most-recent scan is older than this window. Operator-facing signal —
# when we go stale, `ctx timeline reconcile` probably hasn't run recently.
TIMELINE_STALE_DAYS = 7


class CheckStatus(StrEnum):
    PASS = "PASS"  # noqa: S105
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    detail: str
    hint: str = ""


@dataclass(frozen=True)
class DoctorReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        if any(c.status == CheckStatus.FAIL for c in self.checks):
            return 2
        if any(c.status == CheckStatus.WARN for c in self.checks):
            return 1
        return 0

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.status == CheckStatus.PASS)

    @property
    def warn_count(self) -> int:
        return sum(1 for c in self.checks if c.status == CheckStatus.WARN)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if c.status == CheckStatus.FAIL)


def check_claude_cli_present() -> CheckResult:
    if has_claude_cli():
        return CheckResult(
            name="claude CLI",
            status=CheckStatus.PASS,
            detail="found on PATH",
        )
    return CheckResult(
        name="claude CLI",
        status=CheckStatus.WARN,
        detail="not found on PATH",
        hint="install Claude Code (https://docs.claude.com/claude-code)",
    )


def check_mcp_list_contains_lvdcp() -> CheckResult:
    try:
        output = claude_mcp_list()
    except ClaudeCliError as exc:
        return CheckResult(
            name="claude mcp list",
            status=CheckStatus.FAIL,
            detail=str(exc),
            hint="run `ctx mcp install`",
        )
    if "lvdcp" in output:
        return CheckResult(
            name="claude mcp list",
            status=CheckStatus.PASS,
            detail="lvdcp registered",
        )
    return CheckResult(
        name="claude mcp list",
        status=CheckStatus.FAIL,
        detail="lvdcp not in registered MCP servers",
        hint="run `ctx mcp install`",
    )


def _run_handshake() -> bool:
    """Spawn the MCP server and complete the initialize handshake within a short timeout."""
    from mcp.client.stdio import stdio_client  # noqa: PLC0415

    from mcp import ClientSession, StdioServerParameters  # noqa: PLC0415

    async def _run() -> bool:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "apps.mcp.server"],
            env={**os.environ},
        )
        try:
            async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=HANDSHAKE_TIMEOUT_SECONDS)
                return True
        except (TimeoutError, Exception):  # broad-catch: any subprocess failure → FAIL
            return False

    return asyncio.run(_run())


def check_mcp_handshake() -> CheckResult:
    ok = _run_handshake()
    if ok:
        return CheckResult(
            name="mcp handshake",
            status=CheckStatus.PASS,
            detail="initialize round-trip < 3s",
        )
    return CheckResult(
        name="mcp handshake",
        status=CheckStatus.FAIL,
        detail="subprocess did not respond within timeout",
        hint="check `uv run python -m apps.mcp.server` manually",
    )


def check_config_yaml_valid(config_path: Path) -> CheckResult:
    if not config_path.exists():
        return CheckResult(
            name="config.yaml",
            status=CheckStatus.FAIL,
            detail=f"missing: {config_path}",
            hint="run `ctx mcp install` to bootstrap",
        )
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return CheckResult(
            name="config.yaml",
            status=CheckStatus.FAIL,
            detail=f"malformed YAML: {exc}",
            hint="edit or delete + re-run `ctx mcp install`",
        )
    if not isinstance(data, dict) or not isinstance(data.get("projects", []), list):
        return CheckResult(
            name="config.yaml",
            status=CheckStatus.FAIL,
            detail="schema invalid (projects must be a list)",
            hint="delete + re-run `ctx mcp install`",
        )
    projects = data.get("projects", [])
    return CheckResult(
        name="config.yaml",
        status=CheckStatus.PASS,
        detail=f"{len(projects)} project(s) registered",
    )


def check_project_caches(config_path: Path) -> CheckResult:
    if not config_path.exists():
        return CheckResult(
            name="project caches",
            status=CheckStatus.WARN,
            detail="config.yaml missing; skipping",
        )
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return CheckResult(
            name="project caches",
            status=CheckStatus.WARN,
            detail="config.yaml unreadable; skipping",
        )
    projects = data.get("projects", [])
    if not projects:
        return CheckResult(
            name="project caches",
            status=CheckStatus.PASS,
            detail="0/0 (no registered projects)",
        )
    accessible = 0
    missing: list[str] = []
    for entry in projects:
        root = Path(entry["root"])
        cache = root / ".context" / "cache.db"
        if cache.exists():
            accessible += 1
        else:
            missing.append(str(root))
    if missing:
        return CheckResult(
            name="project caches",
            status=CheckStatus.WARN,
            detail=f"{accessible}/{len(projects)} accessible",
            hint=f"missing: {', '.join(missing)} — run `ctx scan <path>` or unregister",
        )
    return CheckResult(
        name="project caches",
        status=CheckStatus.PASS,
        detail=f"{accessible}/{len(projects)} accessible",
    )


def check_claudemd_managed_section(claudemd_path: Path, expected_version: str) -> CheckResult:
    if not claudemd_path.exists():
        return CheckResult(
            name="CLAUDE.md managed",
            status=CheckStatus.WARN,
            detail=f"missing: {claudemd_path}",
            hint="run `ctx mcp install`",
        )
    content = claudemd_path.read_text(encoding="utf-8")
    if "<!-- LV_DCP-managed-section:start" not in content:
        return CheckResult(
            name="CLAUDE.md managed",
            status=CheckStatus.WARN,
            detail="managed section missing",
            hint="run `ctx mcp install`",
        )
    match = re.search(r"lvdcp-managed-version:\s*([\w\.\-]+)", content)
    if match is None:
        return CheckResult(
            name="CLAUDE.md managed",
            status=CheckStatus.WARN,
            detail="managed section present but no version tag",
            hint="re-run `ctx mcp install` to refresh",
        )
    found_version = match.group(1)
    if found_version != expected_version:
        return CheckResult(
            name="CLAUDE.md managed",
            status=CheckStatus.WARN,
            detail=f"version mismatch: {found_version} → {expected_version}",
            hint="re-run `ctx mcp install` to refresh",
        )
    return CheckResult(
        name="CLAUDE.md managed",
        status=CheckStatus.PASS,
        detail=f"version {found_version}",
    )


def check_legacy_pollution(settings_path: Path) -> CheckResult:
    if not settings_path.exists():
        return CheckResult(
            name="legacy pollution",
            status=CheckStatus.PASS,
            detail="settings.json not present",
        )
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return CheckResult(
            name="legacy pollution",
            status=CheckStatus.PASS,
            detail="settings.json unreadable (no lvdcp pollution)",
        )
    servers = data.get("mcpServers", {})
    if isinstance(servers, dict) and "lvdcp" in servers:
        return CheckResult(
            name="legacy pollution",
            status=CheckStatus.WARN,
            detail=f"stray lvdcp entry in {settings_path}",
            hint="run `ctx mcp uninstall --legacy-clean`",
        )
    return CheckResult(
        name="legacy pollution",
        status=CheckStatus.PASS,
        detail="clean",
    )


def check_llm_provider(config: DaemonConfig) -> CheckResult:
    llm = config.llm
    if not llm.enabled:
        return CheckResult(
            name="LLM provider",
            status=CheckStatus.PASS,
            detail="disabled (llm.enabled: false)",
        )
    if llm.provider != "ollama":
        key = os.environ.get(llm.api_key_env_var)
        if not key:
            return CheckResult(
                name="LLM provider",
                status=CheckStatus.WARN,
                detail=f"{llm.api_key_env_var} env var not set",
                hint=f"export {llm.api_key_env_var}=...",
            )
    try:
        client = create_client(llm)
        asyncio.run(asyncio.wait_for(client.test_connection(), timeout=5.0))
        return CheckResult(
            name="LLM provider",
            status=CheckStatus.PASS,
            detail=f"{llm.provider}/{llm.summary_model}",
        )
    except (LLMConfigError, LLMProviderError, TimeoutError) as exc:
        return CheckResult(
            name="LLM provider",
            status=CheckStatus.WARN,
            detail=str(exc)[:100],
            hint="check API key and network",
        )


def check_timeline_store(config: DaemonConfig) -> CheckResult:  # noqa: PLR0911 - seven outcomes
    """Spec-010 T041: verify timeline store is reachable and fresh.

    Emits three outcomes:

    * PASS — store file exists, opens cleanly, and every registered
      project's ``last_scan_ts`` is within ``TIMELINE_STALE_DAYS``.
    * WARN — store exists but one or more projects are stale, OR the
      store is completely empty (fresh install — not a failure, but worth
      flagging so operators know they haven't scanned yet).
    * FAIL — file unreachable, file unreadable as SQLite, or the required
      table is missing. The timeline tools will not function.

    Honours ``timeline.enabled`` — returns PASS/skip when the feature is
    disabled so legacy installs pass doctor without touching the store.
    """
    import sqlite3  # noqa: PLC0415 — stdlib, lazy-load for test isolation
    import time as _time  # noqa: PLC0415

    from libs.symbol_timeline.store import resolve_default_store_path  # noqa: PLC0415

    if not config.timeline.enabled:
        return CheckResult(
            name="timeline store",
            status=CheckStatus.PASS,
            detail="disabled (timeline.enabled: false)",
        )

    store_path = resolve_default_store_path()
    if not store_path.exists():
        return CheckResult(
            name="timeline store",
            status=CheckStatus.WARN,
            detail=f"not created yet: {store_path}",
            hint="run `ctx scan <path>` to initialize",
        )

    try:
        conn = sqlite3.connect(str(store_path))
    except sqlite3.Error as exc:
        return CheckResult(
            name="timeline store",
            status=CheckStatus.FAIL,
            detail=f"cannot open: {exc}",
            hint="check file permissions or remove and re-scan",
        )
    try:
        rows = conn.execute(
            "SELECT project_root, last_scan_ts FROM symbol_timeline_scan_state"
        ).fetchall()
    except sqlite3.Error as exc:
        conn.close()
        return CheckResult(
            name="timeline store",
            status=CheckStatus.FAIL,
            detail=f"schema invalid: {exc}",
            hint="delete the store to let the scanner recreate it",
        )
    conn.close()

    if not rows:
        return CheckResult(
            name="timeline store",
            status=CheckStatus.WARN,
            detail="empty — no projects scanned yet",
            hint="run `ctx scan <path>` to populate",
        )

    now = _time.time()
    stale_window = TIMELINE_STALE_DAYS * 86_400
    stale: list[str] = []
    fresh_count = 0
    for project_root, last_scan_ts in rows:
        if last_scan_ts is None or (now - last_scan_ts) > stale_window:
            stale.append(str(project_root))
        else:
            fresh_count += 1

    if stale:
        return CheckResult(
            name="timeline store",
            status=CheckStatus.WARN,
            detail=f"{fresh_count}/{len(rows)} projects fresh (< {TIMELINE_STALE_DAYS}d)",
            hint=f"stale: {', '.join(stale[:3])}"
            + (f" + {len(stale) - 3} more" if len(stale) > 3 else "")
            + " — run `ctx scan` or `ctx timeline reconcile`",
        )
    return CheckResult(
        name="timeline store",
        status=CheckStatus.PASS,
        detail=f"{fresh_count} project(s) fresh (< {TIMELINE_STALE_DAYS}d)",
    )


def check_llm_budget(config: DaemonConfig) -> CheckResult:
    if not config.llm.enabled:
        return CheckResult(
            name="LLM budget",
            status=CheckStatus.PASS,
            detail="N/A (llm disabled)",
        )
    budget = compute_budget_status(config.llm)
    detail = f"${budget.spent_30d:.2f} / ${budget.monthly_limit:.0f}"
    if budget.status == "exceeded":
        return CheckResult(
            name="LLM budget",
            status=CheckStatus.FAIL,
            detail=detail + " (exceeded)",
            hint="raise monthly_budget_usd or disable LLM",
        )
    if budget.status == "warning":
        return CheckResult(
            name="LLM budget",
            status=CheckStatus.WARN,
            detail=detail + " (>=80%)",
            hint="approaching monthly limit",
        )
    return CheckResult(
        name="LLM budget",
        status=CheckStatus.PASS,
        detail=detail,
    )


def run_doctor(
    *,
    config_path: Path,
    claudemd_path: Path,
    settings_legacy_path: Path,
    expected_version: str,
) -> DoctorReport:
    try:
        daemon_cfg = load_config(config_path)
    except Exception:  # broad-catch: corrupt YAML, missing file, etc.
        daemon_cfg = DaemonConfig()
    checks: list[CheckResult] = [
        check_claude_cli_present(),
        check_mcp_list_contains_lvdcp(),
        check_mcp_handshake(),
        check_config_yaml_valid(config_path),
        check_project_caches(config_path),
        check_claudemd_managed_section(claudemd_path, expected_version),
        check_legacy_pollution(settings_legacy_path),
        check_llm_provider(daemon_cfg),
        check_llm_budget(daemon_cfg),
        check_timeline_store(daemon_cfg),
    ]
    return DoctorReport(checks=checks)


def render_table(report: DoctorReport) -> str:
    symbol = {
        CheckStatus.PASS: "✓",
        CheckStatus.WARN: "⚠",
        CheckStatus.FAIL: "✗",
    }
    lines: list[str] = []
    for c in report.checks:
        line = f"{symbol[c.status]} {c.name:<22} {c.status.value:<5} {c.detail}"
        lines.append(line)
        if c.hint:
            lines.append(f"    hint: {c.hint}")
    lines.append("")
    lines.append(
        f"Result: {report.pass_count} PASS, {report.warn_count} WARN, {report.fail_count} FAIL"
    )
    return "\n".join(lines)


def render_json(report: DoctorReport) -> str:
    payload = {
        "exit_code": report.exit_code,
        "summary": {
            "pass": report.pass_count,
            "warn": report.warn_count,
            "fail": report.fail_count,
        },
        "checks": [
            {
                "name": c.name,
                "status": c.status.value,
                "detail": c.detail,
                "hint": c.hint,
            }
            for c in report.checks
        ],
    }
    return json.dumps(payload, indent=2)
