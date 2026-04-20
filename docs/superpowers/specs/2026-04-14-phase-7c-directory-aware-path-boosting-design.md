# Phase 7C — Directory-Aware Path Boosting

**Status:** Implemented 2026-04-14
**Owner:** Vladimir Lukin
**Follows:** Phase 7C identifier-aware path retrieval
**Version target:** 0.6.x

## 1. Goal

Improve ranking for large-project and multi-project queries that name a file's
module area or deeper directory path in addition to, or instead of, its exact
basename.

**Litmus test:** queries like `temporal workflow schedule pipeline maintenance`
and `telegram client connection` should rank files under
`src/temporal/workflows/*` and `src/telegram/*` more reliably when those files
are already in the candidate pool.

## 2. Problem

Phase 7C already added:

- identifier-aware FTS path aliases
- query token expansion for `snake_case` and `CamelCase`
- bounded basename + immediate-parent path boosts

That still leaves a gap for deeper directory structure. In larger repositories,
the most distinguishing signal often lives one or two path segments above the
file:

- `src/temporal/workflows/pipeline.py`
- `src/telegram/client_pool.py`
- `src/services/keyword_research_service.py`

The current bounded boost only considers:

- file basename
- immediate parent directory

As a result, candidates that already matched FTS/symbol stages may remain
under-ranked when the query references deeper module context like `temporal`,
`telegram`, or `services`.

## 3. Scope

### In scope

- bounded overlap scoring for non-parent ancestor directories
- a lower-weight ancestor boost than basename/parent boosts
- targeted unit tests for deeper path overlap and boundedness

### Out of scope

- new eval thresholds
- reranking
- candidate injection from path-only signals
- broad retrieval architecture changes

## 4. Design

### 4.1 Ancestor token extraction

For each already-scored file candidate, derive tokens from all ancestor
directories except:

- the immediate parent directory, which already has its own boost
- empty / root-like segments

Example:

`src/temporal/workflows/pipeline.py`

- basename tokens: `pipeline`
- parent tokens: `workflows`
- ancestor tokens: `src`, `temporal`

### 4.2 Bounded ancestor boost

Add a small additive boost based on overlap between query tokens and ancestor
directory tokens.

Constraints:

- only applies to files already present in `file_scores`
- lower per-token weight than immediate parent
- capped to avoid precision regression on generic directory names

### 4.3 Ranking intent

The boost should help distinguish:

- a file in the right subsystem but with a generic basename
- from a generic sibling that matched fewer directory/module tokens

without overpowering stronger basename, symbol, or FTS signals.

## 5. Acceptance Criteria

1. A file under `src/temporal/workflows/` gets an additional bounded boost from
   the `temporal` token, not just `workflows`.
2. A file under `src/telegram/` benefits from `telegram` overlap even when the
   basename is generic.
3. The boost stays bounded and does not inject new files into the ranking.
4. `ruff`, `mypy`, non-eval tests, and the existing eval suite remain green.
