# Claude Code + git hook setup for the Symbol Timeline Index

Spec reference: [`specs/010-feature-timeline-index/tasks.md`](../specs/010-feature-timeline-index/tasks.md) §T035.

## What these hooks do

The Symbol Timeline Index captures every `added` / `modified` / `removed`
symbol on each scan. To keep the index in sync with the repo without
running `ctx scan` manually, we ship four git hooks in `.claude/hooks/`
that run automatically on the local machine:

| Hook              | Fires on                     | Action                                 |
|-------------------|------------------------------|----------------------------------------|
| `post-commit.sh`  | `git commit`                 | `ctx scan <repo>` (detached)           |
| `post-merge.sh`   | `git merge`, `git pull`      | `ctx scan` + `reconcile` on squash     |
| `post-checkout.sh`| `git checkout`, `git switch` | No-op breadcrumb (branch switch only)  |
| `post-rewrite.sh` | `git commit --amend`, rebase | `ctx timeline reconcile` + `ctx scan`  |

Each hook:

- Is idempotent — safe to run multiple times.
- Runs detached (`&`, `disown`) so the user's git command never blocks.
- Skips silently when `ctx` is not on `$PATH`.
- Logs to `.context/logs/timeline-hook.log`.

## Activating the hooks

Git looks for hooks in `.git/hooks/` by default. We ship them in
`.claude/hooks/` so they're checked into the repo; link them into place
per clone:

```bash
# From the repo root
for hook in post-commit post-merge post-checkout post-rewrite; do
    ln -sf "../../.claude/hooks/${hook}.sh" ".git/hooks/${hook}"
done
```

Verify:

```bash
ls -l .git/hooks/ | grep -E "post-(commit|merge|checkout|rewrite)"
```

You should see symlinks pointing into `.claude/hooks/`.

## Disabling the timeline without removing the hooks

The hooks call `ctx scan` and `ctx timeline reconcile`. If you want to
pause timeline capture temporarily without touching the symlinks:

```bash
ctx timeline disable --project "$(pwd)"
```

This writes `.context/timeline.enabled=off` and the sink registration in
the agent / scanner checks that flag before wiring itself in. Re-enable
with `ctx timeline enable`.

## Claude Code `settings.json`

If you're running Claude Code in this repo and want it to run the same
scan automatically after it finishes an edit, add this entry to
`.claude/settings.json`:

```json
{
    "hooks": {
        "PostToolUse": [
            {
                "matcher": "Edit|Write|MultiEdit",
                "hooks": [
                    {
                        "type": "command",
                        "command": "sh .claude/hooks/post-commit.sh"
                    }
                ]
            }
        ]
    }
}
```

This reuses `post-commit.sh` after every tool-use — the hook is
idempotent and runs in the background, so it's safe to trigger frequently.

## What's *not* automated here

- **Pre-push scans** — by design a `git push` doesn't rewrite history,
  so we leave the timeline alone. If you want a pre-push guard that
  blocks pushes until the timeline is fresh, add a `pre-push` hook
  separately.
- **Remote-triggered reconcile** — if a colleague force-pushed to a
  shared branch and you `git pull --rebase`, `post-rewrite.sh` fires
  locally and handles it. No server-side reconcile is needed.
- **Backfilling history** — `ctx timeline backfill` is a placeholder in
  Phase 7. The authoritative way to seed the timeline is a one-time
  `ctx scan <repo>` on the current HEAD.

## Troubleshooting

- **Hooks don't fire** — check that `.git/hooks/post-commit` is executable
  (`chmod +x`) and resolves to a file. Symlinks on macOS stay intact after
  `git clone`, but some CI setups strip them.
- **`ctx` not on PATH** — the hooks fall back silently and log a note to
  `.context/logs/timeline-hook.log`. Install `ctx` (`uv pip install -e .`
  inside LV_DCP) and the hooks will start working without further
  action.
- **Ballooning log file** — rotate `.context/logs/timeline-hook.log`
  with `logrotate` or a periodic `truncate --size=0`; the hooks append
  only and don't self-manage size.
