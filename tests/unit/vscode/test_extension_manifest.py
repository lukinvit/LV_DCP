"""Contract tests for ``apps/vscode/package.json``.

These assertions live in the Python CI rather than in a TypeScript test
because: (a) the Python test suite is what runs on every PR, and (b) the
manifest is the source of truth for VS Code Marketplace publication —
silently regressing ``activationEvents`` or ``version`` would ship broken
UX to real users. A JSON-parse smoke test is the cheapest way to lock the
contract without pulling in ``npm`` + ``@vscode/test-electron`` in CI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_MANIFEST_PATH = Path(__file__).resolve().parents[3] / "apps" / "vscode" / "package.json"


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    """Parse ``apps/vscode/package.json`` once per module.

    Return type is ``dict[str, Any]`` (not ``dict[str, object]``) because
    the manifest is a deeply nested heterogenous JSON blob; locking every
    value to ``object`` would force ``cast()`` calls in every assertion
    without buying any type safety for a fixture whose whole purpose is
    to be inspected ad-hoc by the tests.
    """
    with _MANIFEST_PATH.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data


def test_manifest_has_required_publication_fields(manifest: dict[str, Any]) -> None:
    """Marketplace-required fields from v0.8.26 must stay present."""
    for field in (
        "name",
        "displayName",
        "description",
        "version",
        "publisher",
        "license",
        "repository",
        "engines",
    ):
        assert field in manifest, f"missing required manifest field: {field}"


def test_activation_is_narrowed_to_workspace_contains_cache_db(
    manifest: dict[str, Any],
) -> None:
    """Activation must be gated on ``.context/cache.db`` presence (v0.8.30).

    Regressing to ``onStartupFinished`` would re-introduce the problem this
    release fixed: the extension activating — and the status bar item
    appearing — on every VS Code workspace, including unrelated projects.
    """
    events = manifest.get("activationEvents", [])
    assert events == ["workspaceContains:**/.context/cache.db"], (
        f"unexpected activationEvents: {events!r}. v0.8.30 narrowed these to "
        "only trigger on workspaces that actually contain a `.context/cache.db`."
    )


def test_activation_does_not_include_on_startup_finished(manifest: dict[str, Any]) -> None:
    """Explicit negative: ``onStartupFinished`` must not reappear."""
    events = manifest.get("activationEvents", [])
    assert "onStartupFinished" not in events, (
        "onStartupFinished forces activation on every VS Code startup; "
        "v0.8.30 removed it deliberately. If you need to re-add it, update "
        "`docs/release/2026-04-24-v0.8.30-vscode-activation.md` first."
    )


def test_contributed_commands_still_registered(manifest: dict[str, Any]) -> None:
    """Commands must keep appearing in the Command Palette even after narrowing.

    VS Code ≥1.74 auto-registers commands listed in ``contributes.commands``
    as implicit activation events, so dropping ``onStartupFinished`` does
    not require listing the commands explicitly in ``activationEvents``.
    But they must stay contributed, or the palette gate breaks.
    """
    commands = manifest.get("contributes", {}).get("commands", [])
    command_ids = {c["command"] for c in commands}
    assert "lvdcp.getPack" in command_ids
    assert "lvdcp.showImpact" in command_ids


def test_engine_requirement_supports_implicit_command_activation(
    manifest: dict[str, Any],
) -> None:
    """Engine requirement must be ≥1.74 so implicit command activation works."""
    engine = manifest.get("engines", {}).get("vscode", "")
    # Supported forms: "^1.85.0", "^1.74.0", ">=1.74.0", etc.
    # Strip the leading range specifier and parse the major.minor.
    stripped = engine.lstrip("^>=~ ")
    major_minor = stripped.split(".")[:2]
    assert len(major_minor) == 2, f"unexpected engine spec: {engine!r}"
    major, minor = int(major_minor[0]), int(major_minor[1])
    assert (major, minor) >= (1, 74), (
        f"engines.vscode={engine!r} is below 1.74 — implicit command "
        "activation is not guaranteed and dropping onStartupFinished would "
        "leave Command Palette entries broken."
    )


def test_version_not_regressed_below_0_8_30(manifest: dict[str, Any]) -> None:
    """Manifest version must track the v0.8.30 bump or later."""
    version = manifest.get("version", "")
    parts = version.split(".")
    assert len(parts) == 3, f"unexpected version: {version!r}"
    major, minor, patch = (int(p) for p in parts)
    assert (major, minor, patch) >= (0, 8, 30), (
        f"extension version {version!r} is below 0.8.30; v0.8.30 bumped it. "
        "If this is intentional (e.g. yanking a release), remove this assert."
    )
