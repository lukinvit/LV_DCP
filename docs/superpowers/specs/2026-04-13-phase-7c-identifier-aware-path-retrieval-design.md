# Phase 7C — Identifier-Aware Path Retrieval

**Status:** Implemented 2026-04-13
**Owner:** Vladimir Lukin
**Follows:** Phase 7A / Phase 7B
**Version target:** 0.6.x

## 1. Goal

Improve large-project and multi-project retrieval on queries that depend on
identifier-style and path-style terms without changing the mandatory synthetic
eval contract or introducing a heavyweight reranker.

**Litmus test:** queries such as `keyword research service`,
`rate_limiter TelegramClientPool`, and `LoginForm` match file paths more
reliably even when the file body itself is sparse.

## 2. Problem

The large-project advisory queries rely heavily on tokens that look like:

- `snake_case`
- `CamelCase`
- path/basename fragments

The current symbol index already tokenizes identifiers fairly well, but the FTS
layer and path scoring are weaker:

- path text is indexed mostly as raw path strings
- query sanitization does not explicitly expand identifier forms
- candidate ranking does not reward basename/path overlap in a bounded way

This creates a blind spot in large codebases where many files share generic
natural-language terms but only a few match the query's identifier/path shape.

## 3. Scope

### In scope

- shared identifier tokenization helper for retrieval components
- FTS path aliasing so `keyword_research_service.py` becomes searchable via
  `keyword research service`
- FTS query expansion for identifier-style terms like `LoginForm`
- bounded path-token boost for already-scored candidates
- targeted unit tests for FTS and pipeline heuristics

### Out of scope

- new eval thresholds
- LLM reranking
- large retrieval architecture changes
- promoting advisory multi-project eval to CI

## 4. Design

### 4.1 Shared identifier tokenizer

Introduce a small helper that splits text into lowercase identifier tokens
using:

- alphanumeric extraction
- `snake_case` splitting
- `CamelCase` splitting

This helper becomes the shared primitive for symbol lookup, FTS path aliasing,
and bounded path-token overlap.

### 4.2 FTS path aliasing

When indexing a file, add a normalized alias line derived from the file path,
for example:

```text
src/services/keyword_research_service.py
src services keyword research service py
```

This lets FTS retrieve files by natural-language references to path fragments.

### 4.3 Query expansion

FTS query building should consider both:

- raw cleaned query tokens
- identifier-expanded query tokens

Example:

- `LoginForm` → `loginform`, `login`, `form`
- `rate_limiter` → `rate_limiter`, `rate`, `limiter`

### 4.4 Bounded path-token boost

After symbol and FTS stages have produced a candidate pool, apply a small boost
based on overlap between query identifier tokens and the candidate's basename
(stronger) plus immediate parent directory (weaker).

This boost must never inject new files; it only reorders already-scored
candidates.

## 5. Acceptance Criteria

1. FTS can find `keyword_research_service.py` from `keyword research service`.
2. FTS can find `LoginForm.tsx` from `LoginForm`.
3. Retrieval ranking can favor a basename-matching file over a generic sibling
   when both are already candidates.
4. `ruff`, `mypy`, and the existing eval suite remain green.
