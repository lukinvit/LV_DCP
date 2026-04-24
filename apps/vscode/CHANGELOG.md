# Changelog

All notable changes to the LV_DCP VS Code extension.

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
