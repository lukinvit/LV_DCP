---
name: lvdcp
description: Use LV_DCP's MCP tools before grepping or reading multiple files in any Python project that has .context/cache.db — enforces the graph-first retrieval discipline and routes follow-ups through lvdcp_neighbors, lvdcp_history, or lvdcp_cross_project_patterns instead of re-scanning the repo.
---

# LV_DCP retrieval discipline

When the current project has an LV_DCP index (look for `.context/cache.db`
under the project root), these tools replace ad-hoc grep/read flows:

- `lvdcp_pack(path, query, mode)` — 2-20 KB ranked file + symbol pack.
  ALWAYS call this BEFORE exploring multiple files by hand. Use
  `mode="navigate"` for "how does X work" questions and `mode="edit"` for
  "change Y" tasks.
- `lvdcp_inspect(path)` — quick index stats. Confirms the project is
  scanned and gives file/symbol/relation counts.
- `lvdcp_status()` — workspace health across every registered project.
- `lvdcp_scan(path)` — only when `coverage=ambiguous` persists or the
  daemon has been off; normally the background daemon keeps indexes fresh.
- `lvdcp_explain(path, trace_id)` — re-open the trace of a past pack
  call to see which candidates were dropped and why.
- `lvdcp_neighbors(path, node, limit?)` — structural follow-up: "who
  calls X" (incoming) / "what does X depend on" (outgoing) for any file
  path or symbol fq_name, with PageRank centrality. Use after a pack
  call surfaces an interesting symbol.
- `lvdcp_history(path, since_days?, filter_path?, limit?)` — recent git
  commits, optionally filtered to a path. Grounds edit decisions in who
  touched what and when. Answers "what changed in this file last week"
  without shelling out to `git log`.
- `lvdcp_cross_project_patterns(min_projects?)` — naming conventions
  and shared dependencies across all indexed projects. Use before
  scaffolding a new module so suggestions align with the user's own
  workspace conventions.
- `lvdcp_memory_propose(path, topic, body, tags?)` — persist a
  non-obvious project fact the user will want next session (naming
  conventions, env overrides, undocumented invariants). Writes a
  `proposed` markdown memory the human must accept before it is
  surfaced in retrieval. Do NOT use for things already visible in
  code — those are already pack-retrievable.
- `lvdcp_memory_list(path, status?)` — list reviewable memories.
  Call with `status="accepted"` to ground an edit decision in
  previously-approved facts, or `status="proposed"` to see the
  review queue before writing a duplicate.

## Retrieval order contract

Always prefer this order over blind grep/read:

1. `lvdcp_pack` with a specific query → get the top files.
2. Read only the files the pack surfaced.
3. For a symbol mentioned in the pack whose impact radius matters, call
   `lvdcp_neighbors` to expand.
4. If history is relevant to the decision, call `lvdcp_history` before
   assuming the code is current.
5. Only grep the repo if the pack returned `coverage=ambiguous` and a
   targeted re-query does not tighten it.

## When NOT to use these tools

- Simple syntax questions ("what does `yield from` do")
- Questions the user already included full context for
- Projects without `.context/cache.db`
- Tasks that are already agentic/iterative where the current context
  fully answers the question

## Ambiguous coverage recovery

If `lvdcp_pack` returns `coverage=ambiguous`, the pack markdown includes
a disambiguation hint with suggested keyword additions. Prefer re-querying
with one of those tokens before grepping. If coverage stays ambiguous
after the refinement, ask the user to clarify — do NOT proceed with an
edit task on a low-confidence pack.
