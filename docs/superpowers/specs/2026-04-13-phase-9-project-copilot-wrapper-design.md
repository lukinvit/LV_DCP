# Phase 9 — Project Copilot Wrapper

**Status:** Draft 2026-04-13
**Owner:** Vladimir Lukin
**Follows:** Phase 8
**Version target:** 0.7.x+

## 1. Goal

Add a higher-level project copilot layer that acts as a convenient wrapper over
the existing MCP and CLI primitives, so users ask project questions and trigger
repair flows without remembering low-level LV_DCP commands.

**Litmus test:** a user can ask one project-facing command such as:

```bash
ctx project ask /path/to/project "how does voting work?"
```

and the wrapper will decide whether it needs to:

- check project status
- refresh the index
- inspect wiki freshness
- rebuild wiki if needed
- call `lvdcp_pack`
- explain degraded retrieval if results are ambiguous

## 2. Problem

LV_DCP already has the right primitives:

- `lvdcp_scan`
- `lvdcp_pack`
- `lvdcp_status`
- `lvdcp_explain`
- `ctx wiki update`

But these remain low-level building blocks. The product still assumes that the
user knows when to call which primitive and in what order.

That is powerful for maintainers but weak as a user-facing interface. The next
layer should behave like a project-aware copilot that orchestrates the existing
MCP tools instead of exposing the orchestration burden to the user.

## 3. Scope

### In scope

- a new project-facing wrapper command group
- question answering over the indexed project
- refresh/check flows for project scan and wiki freshness
- clear explanations when the wrapper degrades to base mode

### Out of scope

- replacing the low-level MCP tools
- general-purpose autonomous coding agent behavior
- multi-step code editing workflows in the first slice

## 4. Design

### 4.1 Wrapper responsibilities

The copilot wrapper should orchestrate:

- status inspection
- scan freshness checks
- wiki freshness checks
- pack retrieval
- explain/debug path when retrieval quality is ambiguous

### 4.2 Proposed command surface

Possible first-slice command surface:

```bash
ctx project check /path
ctx project refresh /path
ctx project wiki /path --refresh
ctx project ask /path "question"
```

This surface is intentionally user-oriented and does not expose internal LV_DCP
concepts like trace IDs or pack modes unless needed.

### 4.3 Capability-aware behavior

The wrapper must know the difference between:

- project not scanned
- wiki not generated
- full retrieval not available because Qdrant/embeddings are missing
- ambiguous retrieval that needs explain/debug fallback

It should surface those as actionable messages, not raw stack traces.

## 5. Acceptance Criteria

1. A user can ask a project question through one wrapper command.
2. The wrapper automatically refreshes or suggests refresh when the index is stale.
3. The wrapper can detect missing wiki/full-mode prerequisites and explain them.
4. The wrapper remains a thin orchestration layer over existing MCP/CLI
   primitives, not a separate retrieval system.
