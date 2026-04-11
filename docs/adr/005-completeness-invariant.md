# ADR-005: Retrieval completeness is a first-class invariant for edit tasks

**Status:** Accepted
**Date:** 2026-04-11
**Supersedes:** —

## Context

Phase 1 retrieval uses keyword-based matching (SymbolIndex + FTS5) to rank files relevant to a query. This works well when the user's question contains the same vocabulary as the code, and the retrieval evaluation harness (ADR-002) measures this via `recall@5 files` and `precision@3 files`.

However, during the final review of Phase 1, a gap emerged: for edit-mode queries, the pipeline can return files matching the query text while silently missing files that are **structurally impacted** but do not contain the query keywords. Example: the query "change how session tokens are stored" matches `app/models/session.py` and `app/services/auth.py` (both contain "session" or "token" keywords), but misses `app/workers/cleanup.py` — a background job that does `DELETE FROM sessions WHERE expires_at < now()` and is directly impacted by any schema or storage change. The word "token" does not appear in `cleanup.py`; the word "session" may or may not, depending on variable naming.

If Claude acts on the incomplete pack, it will edit the handler and the service, run the tests that touch those two files, and commit — without ever looking at the cleanup worker. The bug surfaces weeks later.

The user's stated requirement is: *"ничего из контекста не должно утекать"* — nothing from the context should slip through unnoticed. Interpreted as an engineering constraint, this means: **for edit-mode queries, the pack must include files that are reachable from the matched files through static relations, not only files that match by keyword.**

This is a retrieval completeness invariant, and it is non-negotiable for edit tasks because the consequences of missing an impacted file are higher than the cost of including an irrelevant one.

## Decision

1. **Graph expansion is mandatory in edit mode.** `RetrievalPipeline.retrieve(mode="edit", ...)` always runs graph expansion on the initial candidate set. Forward walk (what this file uses), reverse walk (who uses this file), through `imports`, `defines`, and `same_file_calls` edges, at `depth=2` with `decay=0.5`.

2. **Navigate mode may use graph expansion as a boost, but is not required to.** For pure navigation queries ("where is X"), keyword match is usually sufficient. Expansion is enabled but its output is weighted lower (`SYMBOL_WEIGHT * 0.5` vs. `SYMBOL_WEIGHT * 1.0`).

3. **A new metric `impact_recall_at_k` measures this invariant.** It operates on a dedicated class of "impact queries" in `tests/eval/queries.yaml` whose `expected` list includes at least one file reachable only via graph walk (not keyword match). Phase 2 threshold: `impact_recall@5 ≥ 0.75`. This threshold is a permanent floor — Phase 3+ must not regress below it.

4. **The retrieval trace records what was expanded, why, and what was dropped.** Each `RetrievalPipeline.retrieve()` call produces a `RetrievalTrace` with:
   - `initial_candidates` (from keyword match + FTS)
   - `expanded_via_graph` (added by graph walk)
   - `dropped_by_score_decay` (candidates below the cutoff)
   - `final_ranking`
   - `coverage: "high" | "medium" | "ambiguous"`

   The `coverage` field is a heuristic over the score distribution. It is exposed to Claude via the MCP `lvdcp_pack` tool's return value, so the LLM can act accordingly (retry with expanded limit, ask user for clarification, or proceed confidently).

5. **Ambiguous-coverage edit packs must trigger a behavioral check.** The auto-injected CLAUDE.md rule (from ADR-004) explicitly instructs Claude to either expand the query, increase the `limit`, or ask the user rather than proceeding with a low-confidence pack on an edit task. This closes the loop between retrieval metadata and LLM behavior.

## Consequences

### Positive

- Edit tasks become safer: the pack surfaces files that keyword matching alone would miss.
- The completeness invariant is measurable and enforced in CI through `impact_recall@5`.
- Debugging retrieval gaps has a first-class tool: `lvdcp_explain(trace_id)` shows exactly which candidates were considered, which were dropped, and why.
- The `coverage` heuristic gives the LLM actionable metadata instead of a flat list.

### Negative

- `precision@3_files` will drop slightly due to graph expansion adding more candidates, some of which are irrelevant. Phase 2 thresholds accept this (`precision@3_files ≥ 0.60` vs. Phase 1's `0.55`).
- Graph expansion depends on the quality of the relations extracted by parsers. Python's `same_file_calls` has `confidence=0.8` because it captures only in-file calls and cannot resolve cross-file dispatch statically. Users should understand that expansion is best-effort, not provably complete.
- `RetrievalTrace` adds storage overhead: ~2-5 KB of JSON per retrieval call. Purged to last 100 per project, this caps disk usage at ~500 KB per project for traces.
- The "12 impact queries" eval set is hand-authored by one person. It risks reflecting that author's biases about what "impacted" means. Mitigation: the query set is reviewable in `tests/eval/queries.yaml`, and any disagreement during code review can propose additions or replacements through the normal PR flow.

### Operational

- Graph expansion is now load-bearing for Phase 2 acceptance. If the graph data is wrong (e.g., a parser bug emits false edges), `impact_recall@5` will either be inflated (false edges provide spurious paths) or deflated (missing edges hide real paths). The eval harness serves as the canary.
- Phase 2 retrieval tests gain a new subdirectory `tests/unit/retrieval/test_graph_expansion.py` for fine-grained graph-walk unit tests. These are the first tests in the project that exercise the `libs/graph/` module in an integrated way (Phase 1 had it unit-tested but disconnected).
- The `coverage` heuristic is tuned on the Phase 2 fixture repo. It may need recalibration when the eval query set grows in Phase 3+.

## Alternatives considered

1. **Keyword-only retrieval with higher `recall@5` targets.** Rejected: even `recall@5 = 1.0` cannot find files that do not contain the query keywords. The metric does not capture the problem the invariant is designed to solve.
2. **Static analysis via Pyright or Jedi for cross-file references.** Rejected for Phase 2 as scope bloat. Kept in mind for Phase 4 when proper call graphs become the priority.
3. **LLM-based query expansion ("rewrite the query with synonyms via Claude").** Rejected: depends on Phase 3 infrastructure and adds non-determinism. The graph walk is fully deterministic and free.
4. **Soft completeness (warn but do not enforce via eval).** Rejected: without a CI-enforced threshold, the invariant becomes advisory and will drift silently through future changes. The `impact_recall@5 ≥ 0.75` gate is what makes this invariant durable.
5. **Higher depth (3 or 4) with lower decay.** Rejected: eval experiments on the fixture repo showed that depth 3 adds mostly unrelated stdlib imports without improving recall, while materially degrading precision. Depth 2 is the sweet spot for Phase 1/2 code size.
