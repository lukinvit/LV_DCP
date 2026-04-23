# Tasks — spec-011 Project Copilot Wrapper

## Phase A — library (`libs/copilot/`)

- [x] T001 — Create `libs/copilot/models.py` with `DegradedMode`, `CopilotCheckReport`, `CopilotRefreshReport`, `CopilotAskReport`.
- [x] T002 — Create `libs/copilot/orchestrator.py::check_project`.
- [x] T003 — Create `libs/copilot/orchestrator.py::refresh_project` (scan + optional wiki update).
- [x] T004 — Create `libs/copilot/orchestrator.py::refresh_wiki` (wiki-only, thin wrapper).
- [x] T005 — Create `libs/copilot/orchestrator.py::ask_project` (delegates to `lvdcp_pack`, decorates with degraded modes).
- [x] T006 — `libs/copilot/__init__.py` re-exports.

## Phase B — CLI (`apps/cli/commands/`)

- [x] T007 — Create `apps/cli/commands/project_cmd.py` with four subcommands.
- [x] T008 — Wire `project_cmd.app` into `apps/cli/main.py` as `project`.
- [x] T009 — Shared text/JSON renderers for each `CopilotReport`.

## Phase C — tests

- [x] T010 — `tests/unit/copilot/__init__.py` + `test_check_project.py`.
- [x] T011 — `tests/unit/copilot/test_refresh_project.py`.
- [x] T012 — `tests/unit/copilot/test_ask_project.py`.
- [x] T013 — `tests/unit/cli/test_project_cmd.py` covering all four subcommands.

## Phase D — quality

- [x] T014 — `uv run ruff check . && uv run ruff format --check .`
- [x] T015 — `uv run mypy .`
- [x] T016 — `uv run pytest -q -m "not eval and not llm"`

## Phase E — release

- [x] T017 — Changelog entry + README line about `ctx project` surface.
- [x] T018 — Commit + push branch + PR.
- [x] T019 — Merge when CI green; tag `phase-9-complete`.
