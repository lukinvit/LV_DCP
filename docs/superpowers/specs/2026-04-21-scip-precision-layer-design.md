# SCIP precision layer — design spike

**Status:** Design only. No code shipped in this spike. The spike's job is to
say *whether and how* to add compiler-precise references on top of LV_DCP's
tree-sitter graph.

## Why

LV_DCP's relation graph is built by tree-sitter extractors. They are fast and
multi-language but **heuristic**: `SAME_FILE_CALLS`, `IMPORTS`, and
`INHERITS` are inferred from AST patterns, not from a compiler's type
resolution. For large refactors a user will ask "who calls `foo.Bar.baz`"
and the current `lvdcp_neighbors` will return the syntactic matches — good
for 90% of cases, wrong for:

- **Method overriding**: `Child.foo` overriding `Parent.foo`. Tree-sitter
  sees two methods named `foo`; the call site `obj.foo()` is linked to
  neither precisely.
- **Dynamic dispatch**: `getattr(obj, name)()`, decorators, protocols.
- **Cross-module re-exports**: `from .a import b` inside `__init__.py`.
- **Generics / TypeVars**: `list[Foo].append(...)` — tree-sitter loses the
  type of the element.

Cody gets this right because it uses **SCIP** (Sourcegraph Code Intelligence
Protocol) indexers that run the actual compiler (scip-python = pyright,
scip-typescript = TS compiler, scip-go = type-check, scip-java = jar
scanning, etc.). SCIP writes a protobuf file listing every symbol, every
occurrence, and every reference with a compiler-resolved canonical symbol
ID.

## Scope of a future precision layer

**In scope:**
- Consume pre-built `.scip` index files if present alongside a project.
- Use SCIP occurrences to enrich the LV_DCP graph with PRECISE reference
  edges (relation type: `REFERENCES`, already reserved in
  `RelationType` enum but not yet emitted by any parser).
- Expose a new MCP tool `lvdcp_precise_refs(symbol)` that prefers SCIP
  edges over tree-sitter heuristics when SCIP data exists.

**Out of scope (for this feature):**
- Running `scip-python` / `scip-typescript` ourselves. Users generate the
  index with their existing tooling (make target, CI step).
- Mandatory precision: SCIP is opt-in. Tree-sitter remains the default
  because it is dep-free and covers all five shipped languages.

## Option comparison

| Option | Pros | Cons |
|---|---|---|
| **A. Consume SCIP protobuf** | Compiler-precise, matches Cody ecosystem, one format for all langs | Needs `scip-python` binary (Go-based) external; proto parsing; users must build the index |
| **B. Jedi (Python only)** | Pure Python, trivial install, no external binary | Python-only; weaker on type inference than pyright |
| **C. LSP per language** | Live, up-to-date, matches Serena's approach | Heavy startup, per-language server processes, stateful |

**Recommendation:** Start with **A** (SCIP) because (i) it matches the
multi-language story LV_DCP already has, (ii) it's static (no long-running
LSP processes), and (iii) the SCIP protobuf format is stable and public.
Keep **B/C** on the backlog as future precision boosts for specific
workflows.

## Shape of the implementation (Option A)

New module `libs/scip/`:

- `reader.py` — parses `.scip` protobuf via `scip-python-bindings` (Python
  package, ~10 KB wheel) or a hand-rolled minimal proto reader.
- `enricher.py` — converts SCIP `Occurrence` records into LV_DCP
  `Relation(relation_type=REFERENCES, provenance="scip")` values and
  merges them into the graph after the tree-sitter pass.
- `config.py` — looks up the index path in the project config
  (`scip.index_path: Optional[Path]`); absent = layer disabled.

New MCP tool `lvdcp_precise_refs(path, symbol)`:

- Requires SCIP data for the project.
- Returns a list of file:line occurrences for *symbol*, ordered by
  file + line.
- Falls back to `lvdcp_neighbors` with a clear `"precise_refs_unavailable"`
  diagnostic when no SCIP index exists.

Scanner integration:

- After the existing scanner pass, if `<root>/.context/index.scip` is
  present and newer than the last SCIP ingestion, re-ingest into a
  separate relations source (tagged with `provenance="scip"` so it can be
  distinguished from tree-sitter data).
- Never block scanning on SCIP: if parsing fails, log and continue.

## Eval impact hypothesis

SCIP should primarily lift two metrics:

1. **impact_recall@5** — precise reverse references improve the edit-mode
   impact radius. Current: 0.931 on synthetic fixture. Expected after
   SCIP: 0.95+ on real projects where heuristic refs miss overrides.
2. **"who calls X" latency** — the upcoming `lvdcp_precise_refs` tool
   answers this in O(1) lookup instead of walking the tree-sitter graph.

Precision and recall@5 should not change much — those are dominated by
FTS + role weights, not reference precision.

## Risk and rollout

- **Binary dependency risk**: `scip-python` is ~15 MB Go binary. We do NOT
  ship it with LV_DCP; users install it themselves (brew / asdf / go
  install). The LV_DCP side only needs the protobuf reader, which is
  ~50 KB of Python.
- **Schema stability**: SCIP protobuf has had breaking changes in the past.
  Pin a specific version of scip-python-bindings and document the tested
  version.
- **Rollout**: Start read-only and opt-in. Feature flag
  `scip.enabled: false` by default. Ship with a test fixture that has a
  pre-generated `.scip` file and a CI gate that verifies the reader
  parses it without error.

## Prior art

- Aider does **not** use SCIP — it accepts tree-sitter heuristics as good
  enough.
- Continue.dev does **not** use SCIP for its `@codebase` context.
- Cody is the only mainstream tool that relies on SCIP; the project owns
  the spec at <https://github.com/sourcegraph/scip>.

## Decision

**Ship as a Phase 8 add-on** if at least one of these signals lands:

1. A user asks for precise refs on a large monorepo and the heuristic
   answer is demonstrably wrong (e.g. missing 2+ real callers).
2. `lvdcp_neighbors` gets enough traffic that the precision quality
   becomes visible.

Until then, this spec stays in the backlog and the tree-sitter graph plus
the centrality boost shipped in G1 remain the answer.
