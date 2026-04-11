# ADR-004: Phase 2 pivot — native integration and completeness before LLM enrichment

**Status:** Accepted
**Date:** 2026-04-11
**Supersedes:** implicit Phase 2 scope from `docs/superpowers/plans/2026-04-10-phase-0-1-foundation.md` (LLM summaries + vector search)

## Context

The original Phase 2 plan prioritized LLM summarization via the Claude API and vector search (sqlite-vss / pgvector) to improve retrieval recall and precision. After Phase 1 shipped with deterministic retrieval at `recall@5 files = 0.917` and `precision@3 files = 0.625`, the user identified a different pain point:

1. The tool is only useful if it is **actually used by the LLM** without manual intervention. Phase 1 requires the user to run `ctx scan` / `ctx pack` manually. This friction caps adoption at a tiny fraction of possible value.
2. Even with perfect keyword retrieval, the tool silently **loses context** for edit-mode tasks. A query like "change how session tokens are stored" returns files matching "session" and "token" but may miss the cleanup worker that deletes expired sessions — which is directly impacted but contains neither keyword.

The practical gap is not "understand abstract queries" (needs LLM/vector) but "know what else is impacted" (needs graph) and "be invoked automatically" (needs MCP).

## Decision

Phase 2 is repurposed. The new scope is:

1. **Native MCP integration.** Build an MCP server exposing `lvdcp_scan`, `lvdcp_pack`, `lvdcp_inspect`, and `lvdcp_explain` tools. Install via `ctx mcp-install` in one command, default `--scope user` (works in every project). Tool descriptions authored so Claude auto-calls without per-project reminders. Supported transport: stdio only.
2. **Auto-indexing daemon.** A `launchd`-managed background process watches registered projects via `watchdog` + `FSEventsObserver`, runs incremental scans on file changes within a 2s debounce window. Users register projects via `ctx watch add`. The daemon is a convenience layer; all commands work without it.
3. **Graph expansion in the retrieval pipeline.** After keyword match and FTS merge, expand the candidate set via `imports` / `defines` / `same_file_calls` edges with `depth=2, decay=0.5`. Expanded files carry `provenance="graph_expanded"` in the retrieval trace. Edit-mode packs explicitly surface impacted tests and configs found only via graph walk.
4. **Completeness metric as first-class eval gate.** Add 12 impact queries to `tests/eval/queries.yaml` whose `expected` list includes files only findable via graph relations. Add `impact_recall_at_k` metric to `tests/eval/metrics.py`. Phase 2 threshold: `impact_recall@5 ≥ 0.75`.
5. **Privacy hardening.** Secret pattern detection (`libs/core/secrets.py`) excludes file content from indexes when regex matches known credential formats. Metadata (path, size) still indexed; content is suppressed and annotated in packs. Default ignore list expanded to `.env`, `.env.*`, `secrets/`, `credentials.json`.

The LLM enrichment scope from the original Phase 2 — content-hashed Claude API summaries, embeddings, vector stage — is **deferred to Phase 3** without changes.

## Consequences

### Positive

- Users get a working, hands-off tool 3-4 weeks earlier than the LLM-first path.
- The token-saving proposition of LV_DCP is realized through usage, not configuration.
- The completeness metric creates an objective, graph-aware quality standard that survives through Phase 3+ refactorings.
- Privacy position is unambiguous: the entire Phase 2 system runs locally, with zero network egress for data.

### Negative

- Phase 2 does not improve retrieval on queries that lack matching keywords ("authentication flow" vs. "безопасность пользователя"). Users with non-English code comments or abstract questions will still see the Phase 1 ceiling.
- Graph expansion increases candidate set size by ~2-3x, which may reduce `precision@3_files` slightly. Phase 2 thresholds explicitly permit this: `precision@3_files ≥ 0.60` vs. Phase 1's `0.55` floor (still above).
- More moving parts (MCP server, daemon, plist, CLAUDE.md patching) increase debugging surface. Mitigated by foreground-first daemon development, comprehensive integration tests, and a rollback via `ctx mcp-uninstall` that cleanly removes every modification.
- Writing to `~/.claude/CLAUDE.md` is a form of global state pollution that requires user trust. Mitigated by the managed-section pattern with sentinels, backup-before-write, and idempotent reinstall.

### Operational

- Phase 3 can pick up the original LLM/vector scope with no architectural debt because `ProjectIndex` + `RetrievalPipeline` already accommodate new stages.
- Phase 2 eval thresholds become the permanent floor — Phase 3 must not regress `impact_recall@5` below 0.75.
- The daemon's registration file `~/.lvdcp/config.yaml` becomes the first cross-project state owned by LV_DCP. Subsequent phases will likely grow this file; versioning it from day one (`version: 1`) was a deliberate choice to make that growth safe.

## Alternatives considered

1. **Original Phase 2 (LLM + vector first).** Rejected: solves the wrong problem (semantic abstraction) while leaving the concrete problems (manual invocation, incomplete edit context) untouched. Would also burn the first real budget under ADR-001 before proving the manual version was actually used.
2. **Native integration only (no graph expansion).** Rejected: would make automatic invocation work but leave the "missed test file" problem unsolved. The user explicitly flagged this as the core concern. Half-solving it would erode trust in the tool's edit-mode output.
3. **Graph expansion only (no MCP or daemon).** Rejected: improves retrieval quality for manual users but doesn't address the adoption gap. The user explicitly stated the goal is automatic usage.
4. **LLM-summarized index built first, retrieval over summaries.** Rejected as premature. We have no evidence yet that summaries help more than raw symbol graphs for the dominant query class (edit tasks in known code). Build graph first, measure, then decide whether summaries are worth their cost.
5. **MCP server with tools proxying directly to Phase 1 CLI subprocess.** Rejected: extra process for every tool call, ~100ms overhead, no way to share a warm index across calls within a session. In-process via `ProjectIndex` is strictly better.
