# LV_DCP — Developer Context Platform

Local-first **context packs** and **impact analysis** for your codebase, from inside VS Code.

Ask a question in plain language — *"where is refresh token logic?"* or *"what breaks if I change login validation?"* — and the extension returns a ranked set of 2–5 relevant files sourced from a local LV_DCP index. No network calls, no telemetry, no SaaS.

## What it does

- **Context Pack.** Type a query in the command palette; LV_DCP returns the most relevant files from the active workspace via a ranked retrieval pipeline (summary → symbol → graph → vector → rerank) and shows them in a tree view in the activity bar.
- **Impact Analysis.** For the current file, LV_DCP walks the relation graph and surfaces dependents — tests that import it, configs that reference it, and downstream callers — before you edit.
- **Status bar indicator.** Click the `LV_DCP` status bar item to trigger a context pack query against the active workspace.

The extension shells out to the `ctx` CLI (part of the LV_DCP backend). Indexes live in `.context/` next to each project.

## Requirements

1. **Python 3.12+** and `uv` installed.
2. The LV_DCP backend stack running locally (Postgres + Qdrant + Redis). See [LV_DCP setup](https://github.com/lukinvit/LV_DCP#install).
3. The `ctx` CLI on your `PATH` — `uv run python -m apps.cli` or install the `lv-dcp` package in editable mode.
4. Your project indexed at least once: `ctx scan <path>`.

## Commands

- **LV_DCP: Get Context Pack** (`lvdcp.getPack`) — prompts for a query, shows results in the activity-bar tree view.
- **LV_DCP: Show Impact** (`lvdcp.showImpact`) — runs impact analysis on the active file; results appear in the same tree view.

## Design philosophy

LV_DCP is **local-first** by design. The extension never uploads your source code anywhere. All retrieval happens against a local index on your machine; optionally, summarisation goes through Claude API (user-controlled). Secrets in source files are detected by regex and excluded from the index.

## Known limitations

- The extension expects the `ctx` CLI to be on `PATH`. If you installed the LV_DCP backend with `uv sync`, you may need to run the CLI via `uv run` — configure this via a shell wrapper for now. Path-configuration via extension settings is planned.
- A publisher account is required for the public marketplace install. Until first publish, you can install the `.vsix` locally via `code --install-extension lv-dcp-<version>.vsix`.
- The status bar currently shows a single indicator; per-query history and re-run from the tree view are planned.

## Links

- **Full docs:** [github.com/lukinvit/LV_DCP](https://github.com/lukinvit/LV_DCP)
- **Issues:** [github.com/lukinvit/LV_DCP/issues](https://github.com/lukinvit/LV_DCP/issues)
- **Discussions / Q&A:** [github.com/lukinvit/LV_DCP/discussions](https://github.com/lukinvit/LV_DCP/discussions)
- **License:** Apache 2.0 — see [LICENSE](https://github.com/lukinvit/LV_DCP/blob/main/LICENSE)
