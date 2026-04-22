"""Smoke test for the Claude Code + git hook scripts (spec-010 T037).

Verifies that each shipped `.claude/hooks/*.sh` is syntactically valid,
executable, and exits 0 when the `ctx` CLI is missing from PATH — this
is the "safe-degrade" path users hit right after cloning before they've
installed the tools.

We don't assert any timeline mutation here (that's
``test_reconcile.py`` / ``test_hooks.py``). The job of this file is
purely "the hooks won't break a developer's commit".
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "hooks"
HOOK_NAMES = ["post-commit.sh", "post-merge.sh", "post-checkout.sh", "post-rewrite.sh"]


@pytest.mark.parametrize("hook_name", HOOK_NAMES)
def test_hook_file_exists_and_is_executable(hook_name: str) -> None:
    path = HOOKS_DIR / hook_name
    assert path.is_file(), f"{path} missing"
    assert os.access(path, os.X_OK), f"{path} is not executable (chmod +x)"


@pytest.mark.parametrize("hook_name", HOOK_NAMES)
def test_hook_bash_syntax_is_valid(hook_name: str) -> None:
    path = HOOKS_DIR / hook_name
    # `bash -n` exits 0 if syntax is valid, non-zero with an error otherwise.
    res = subprocess.run(
        ["bash", "-n", str(path)], capture_output=True, text=True, check=False
    )
    assert res.returncode == 0, f"syntax error in {hook_name}: {res.stderr}"


@pytest.mark.parametrize("hook_name", HOOK_NAMES)
def test_hook_exits_zero_without_ctx_on_path(
    hook_name: str, tmp_path: Path
) -> None:
    """Hook must not break a commit when `ctx` is missing from PATH."""
    path = HOOKS_DIR / hook_name
    # Fake repo so `git rev-parse --show-toplevel` works.
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    env = {
        "PATH": "/usr/bin:/bin",  # no ctx here
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    # Some hooks take args (e.g. post-checkout gets prev/new/is_branch).
    # Pass three dummy args; the scripts tolerate extras.
    res = subprocess.run(
        [str(path), "0" * 40, "1" * 40, "1"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert res.returncode == 0, (
        f"{hook_name} exited {res.returncode} when ctx was missing; "
        f"stderr: {res.stderr}"
    )


def test_claude_hooks_setup_doc_exists() -> None:
    """The operator-facing setup guide is checked in."""
    doc = Path(__file__).resolve().parents[2] / "docs" / "claude-hooks-setup.md"
    assert doc.is_file()
    content = doc.read_text()
    for hook_name in HOOK_NAMES:
        assert hook_name in content, f"{hook_name} not documented"
