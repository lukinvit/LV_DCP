# Changelog

All notable changes to the LV_DCP VS Code extension.

## 0.8.30 — 2026-04-24

**Activation-event narrowing.** The extension no longer activates on every VS Code startup — it activates only when the workspace actually contains an LV_DCP index. Visible side effect: the "LV_DCP" status bar item stops appearing in unrelated projects.

- Replaced `"activationEvents": ["onStartupFinished"]` with `"activationEvents": ["workspaceContains:**/.context/cache.db"]`. Users opening a non-indexed project see no LV_DCP UI; users opening an indexed project get the status bar item, tree view, and commands as before.
- Commands `lvdcp.getPack` and `lvdcp.showImpact` remain invokable from the Command Palette anywhere thanks to implicit command activation (VS Code ≥1.74; engine requirement stays at ^1.85.0). Invoking a command in a non-indexed workspace still works — it just activates on demand rather than pre-emptively.
- No changes to `src/*.ts` — pure manifest change. `out/` rebuild not required for this release; the compiled code path is identical.

**Known behaviour change:** if you relied on the status bar item as a permanent "LV_DCP is installed" reminder in projects you never scan, that reminder is gone. Run `ctx scan` once in the project to re-enable the sidebar affordances.

## 0.8.28–0.8.29 — 2026-04-24 (unreleased to marketplace)

- No extension-side changes. v0.8.28 shipped `ctx obsidian sync-all` (CLI), v0.8.29 added Obsidian sync observability to the dashboard project card. Both are backend-only; the extension version stayed at 0.8.27 through those releases and jumps to 0.8.30 here.

## 0.8.27 — 2026-04-24

**Extension settings.** First user-configurable behaviour in the extension. No breaking change — all settings have defaults that preserve the 0.8.26 behaviour.

- Added `lvdcp.cliPath` (default `"ctx"`) — path to the `ctx` executable. Unblocks users whose `ctx` is not on `PATH` (e.g. running the CLI via `uv run python -m apps.cli`).
- Added `lvdcp.defaultMode` (default `"navigate"`, enum `"navigate" | "edit"`) — default retrieval mode for `LV_DCP: Get Context Pack`. `LV_DCP: Show Impact` continues to force `"edit"`.
- Added `lvdcp.cliTimeoutMs` (default `30000`, range `1000–300000`) — timeout for `ctx` subprocess calls, previously hardcoded.
- `ctxClient.ts` refactored to take an explicit `CtxConfig` parameter instead of relying on implicit `ctx` PATH lookup and hardcoded 30s timeout.
- README: new "Settings" section with table + `uv run` wrapper example.

## 0.8.26 — 2026-04-24

**Marketplace-readiness prep.** No behaviour change; metadata and packaging only.

- Added `repository`, `bugs`, `homepage`, `license` fields to `package.json`
- Added `keywords` for marketplace discoverability: `context`, `retrieval`, `rag`, `claude`, `cursor`, `codebase`, `impact-analysis`, `local-first`, `ai`, `graph`
- Expanded `categories` from `Other` only to `Programming Languages`, `Machine Learning`, `Other`
- Added `galleryBanner` (dark theme)
- Added `qna` link to GitHub Discussions
- Added `vscode:prepublish` and `publish` scripts; `vscode:prepublish` runs `tsc` before packaging
- Added `apps/vscode/README.md` — marketplace listing content (what, requirements, commands, limitations, links)
- Added `apps/vscode/CHANGELOG.md` — this file
- Added `apps/vscode/LICENSE` — Apache 2.0, matching repo root
- Expanded `apps/vscode/.vscodeignore` to exclude `package-lock.json`, `.claude/`, `.github/`, `*.log`, map files, etc., so the published `.vsix` stays lean

## 0.8.25 — 2026-04-24 (unreleased to marketplace)

- Bumped to match repo release cadence (Swift `INHERITS` edges, `libs/parsers/swift.py`). No extension-side changes.

## 0.8.24 — 2026-04-24 (unreleased to marketplace)

- Bumped to match repo release cadence (Kotlin `INHERITS` edges). No extension-side changes.

## 0.8.23 — 2026-04-24 (unreleased to marketplace)

- Bumped to match repo release cadence (Java `INHERITS` edges). No extension-side changes.

## 0.8.22 and earlier

Version tracked in the main repo changelog until this extension is first published to the Marketplace. See [repo release notes](https://github.com/lukinvit/LV_DCP/tree/main/docs/release) for feature history.
