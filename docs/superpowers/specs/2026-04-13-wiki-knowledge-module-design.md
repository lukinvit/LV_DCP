# Wiki Knowledge Module — Phase 1

**Status:** Approved 2026-04-13
**Owner:** Vladimir Lukin
**Follows:** Phase 6 complete (v0.6.0)
**Pattern:** Karpathy's LLM Wiki adapted for code intelligence

## 1. Goal

Add a persistent LLM-synthesized knowledge layer to LV_DCP. During scan, modules with changed files are marked dirty. On `ctx wiki update`, a Claude Code subagent reads the code and writes/updates wiki articles per module. Context packs include relevant wiki articles before raw files — agents read understanding, not code.

**Litmus test:** After `ctx wiki update` on a Go microservices project, asking "how does the voting service work?" returns a wiki article with architecture, components, and patterns — no raw code reading needed.

## 2. Architecture

### Storage

```
.context/
├── cache.db          # existing (+ new table wiki_state)
├── wiki/
│   ├── INDEX.md      # one line per article, ~5KB for 100 articles
│   └── modules/
│       ├── auth-service.md
│       ├── voting-service.md
│       └── frontend-features.md
```

Wiki files are plain markdown, committed to `.context/wiki/` alongside existing `.context/*.md` artifacts. They are project-local (per-project). Global cross-project wiki is Phase 2.

### Dirty tracking

New table in `cache.db`:

```sql
CREATE TABLE IF NOT EXISTS wiki_state (
    module_path TEXT PRIMARY KEY,
    wiki_file TEXT NOT NULL,
    last_generated_ts REAL NOT NULL DEFAULT 0,
    source_hash TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'dirty'
);
```

- `module_path`: first 2 path segments (e.g. `services/auth-service`)
- `source_hash`: SHA256 of sorted concatenated content_hashes of all files in module
- `status`: `dirty` | `current` | `generating`

### Scan integration

After `_process_and_index_files` in `scan_project`, new step:

1. Group all files by module (first 2 path segments)
2. For each module: compute source_hash from file content_hashes
3. Compare with wiki_state table
4. If hash changed or no entry exists → set status='dirty'
5. If hash unchanged → leave as 'current'

This adds ~10ms to scan — no LLM calls, just hashing.

### Wiki generation (`ctx wiki update`)

For each dirty module:

1. Read module files, symbols, dependencies from cache.db
2. Read existing wiki article (if any) for incremental update
3. Launch Claude Code subagent via CLI:

```bash
claude -p --output-format text --max-turns 3 \
  "You are updating the wiki article for module '{module_name}' in project '{project_name}'.

Current article (empty if first generation):
{existing_article_or_empty}

Module files ({file_count} files):
{file_list_with_roles}

Key symbols:
{top_symbols}

Dependencies (imports from):
{dependency_modules}

Dependents (imported by):
{dependent_modules}

Write a concise wiki article (max 2000 tokens) in this format:

# {module_name}

## Purpose
One paragraph: what this module does and why it exists.

## Key Components
Bullet list of main files/classes/functions with one-line descriptions.

## Dependencies
What this module depends on and why.

## Patterns & Decisions
Notable architectural patterns, design decisions, or conventions used.

## Known Issues
Any obvious tech debt, missing tests, or potential problems.

Rules:
- Be specific, reference actual file names and function names
- Update existing content incrementally, don't rewrite from scratch
- If the module is trivial (< 3 files), write 3-5 sentences total
- No generic filler text"
```

4. Save output to `.context/wiki/modules/{safe_module_name}.md`
5. Update wiki_state: status='current', source_hash, last_generated_ts
6. Regenerate INDEX.md

### INDEX.md generation

After all dirty modules are processed, regenerate INDEX.md:

```markdown
# Wiki Index — {project_name}

Updated: {timestamp}
Modules: {count}

## Modules
- [auth-service](modules/auth-service.md) — {first_sentence_of_Purpose}
- [voting-service](modules/voting-service.md) — {first_sentence_of_Purpose}
```

The summary line is extracted from the first sentence of the Purpose section of each article.

### Context pack enrichment

In `lvdcp_pack` (apps/mcp/tools.py), after retrieval and before building the pack:

1. Check if `.context/wiki/INDEX.md` exists
2. Read INDEX.md (~5KB — fits in any context)
3. Match query keywords against INDEX entries
4. Read top 1-3 matching wiki articles
5. Prepend to pack markdown:

```markdown
## Project knowledge (wiki)

{wiki article content}

---

## Top files
{existing pack content}
```

Keyword matching: split query into words, match against INDEX summary lines. Score = count of matching words. Take top 3 articles with score > 0.

### CLI commands

```bash
ctx wiki update                # update dirty modules only
ctx wiki update --all          # regenerate all articles
ctx wiki status                # show dirty/current per module
```

### Configuration

New section in `~/.lvdcp/config.yaml`:

```yaml
wiki:
  enabled: true
  auto_update_after_scan: false
  max_modules_per_run: 10
  article_max_tokens: 2000
```

`auto_update_after_scan: true` enables the daemon-side post-scan wiki hook: after
an automatic daemon scan, dirty modules can be regenerated in the background.
Manual `ctx scan` remains scan-only. Default false to keep scan paths fast and
predictable.

## 3. Files

### New files

```
libs/wiki/__init__.py                    — package init
libs/wiki/state.py                       — wiki_state table CRUD + dirty tracking
libs/wiki/generator.py                   — Claude subagent launcher + article writer
libs/wiki/index_builder.py               — INDEX.md generation from articles
libs/wiki/pack_enrichment.py             — keyword match + wiki injection into packs
apps/cli/commands/wiki_cmd.py            — ctx wiki update/status CLI
tests/unit/wiki/__init__.py
tests/unit/wiki/test_state.py
tests/unit/wiki/test_index_builder.py
tests/unit/wiki/test_pack_enrichment.py
```

### Modified files

```
libs/scanning/scanner.py                 — add dirty tracking after file processing
libs/storage/sqlite_cache.py             — add wiki_state table to migrate()
apps/mcp/tools.py                        — add wiki enrichment to lvdcp_pack
apps/cli/main.py                         — add wiki subcommand
libs/core/projects_config.py             — add WikiConfig
```

## 4. Files NOT touched

- `libs/parsers/*` — parsing unchanged
- `libs/retrieval/pipeline.py` — retrieval unchanged, wiki is pre-retrieval enrichment
- `libs/embeddings/*` — vector store unchanged
- `libs/obsidian/*` — Obsidian sync unchanged (wiki → Obsidian sync is Phase 2)
- `libs/graph/*` — graph unchanged

## 5. Dependencies

No new Python dependencies. Claude CLI (`claude`) must be available on PATH for subagent execution. If not available, `ctx wiki update` prints error and exits.

## 6. Risks

**R1 — Claude CLI not installed or not authenticated.**
Mitigation: `ctx wiki update` checks `which claude` before starting. Clear error message with install instructions.

**R2 — Subagent cost per module.**
Each module = ~1 Opus/Sonnet call with tool use. For 15 modules = ~$0.15-0.50.
Mitigation: `max_modules_per_run` config, dirty tracking (only changed modules), `--all` flag for explicit full regen.

**R3 — Subagent produces inconsistent or low-quality articles.**
Mitigation: Structured prompt with explicit format. Incremental updates (existing article as context). Max 2000 token limit per article.

**R4 — scan becomes slower due to dirty tracking.**
Mitigation: Dirty tracking is hash comparison only (~10ms). Manual `ctx scan`
does not invoke LLM work. With `auto_update_after_scan: true`, the daemon may
queue background wiki generation after the scan completes.

**R5 — INDEX.md grows too large.**
At 100 modules × 100 chars per line = 10KB. Fits in any context window. Not a risk for personal-scale projects.

## 7. Non-goals (Phase 1)

- Global cross-project wiki (`~/.lvdcp/wiki/`)
- Architecture page auto-generation
- Decision extraction from git history
- Lint operation (consistency checking)
- Outputs layer (persistent query results)
- Obsidian sync of wiki articles
- Wiki articles for individual files (only module-level)

## 8. Success criteria

1. `ctx wiki update` generates wiki articles for dirty modules via Claude subagent
2. `ctx wiki status` shows dirty/current state per module
3. `lvdcp_pack` includes relevant wiki articles in context packs
4. Wiki articles persist across scans (incremental updates)
5. INDEX.md is compact and parseable
6. `make test` green (no regressions)
