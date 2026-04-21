# ADR 007 — At-rest encryption for the project cache

**Status:** Accepted (scaffolded); implementation deferred to Phase 8.
**Date:** 2026-04-21.

## Context

The LV_DCP cache (`<project>/.context/cache.db`) contains the full
symbol table, relation graph, and file content hashes of every indexed
project. On a solo developer machine this is fine — the cache is
unreadable by anyone without local access. But two Q2 2026 signals push
encryption on-roadmap:

1. **Team-share (sprint item S7)** wants to pack the cache into a CI
   artifact or git-tracked bundle. Plaintext is unacceptable there.
2. **Cursor 3 "Glass"** (April 2026) ships encrypted local indexes as
   a differentiator. Users expect parity on privacy-visible axes.

## Decision

Treat encryption as **opt-in, optional-dep, zero-disruption**:

- A new config key `storage.encryption_key_env: str | None` names the
  environment variable holding the passphrase. The key itself is
  never stored in config — only the env-var name. Default is `None`
  (no encryption).
- When set, `SqliteCache` opens the DB via **SQLCipher** (`sqlcipher3`
  Python binding). When unset, uses stdlib `sqlite3` as today.
- `sqlcipher3` is an **optional dependency** (`lv-dcp[storage-encrypted]`).
  Users who never turn on encryption never install it.
- Enabling encryption requires a **one-way migration** (`ctx storage
  migrate --encrypt`). The reverse (`--decrypt`) is also offered for
  recovery.

## Why not

- **Mandatory encryption by default**: breaks every existing user's
  cache on upgrade; no compelling reason for solo workflows.
- **OS-level FDE (FileVault)** is an alternative, but it does not
  protect the cache once it leaves the local disk (team share, CI
  artifact). Encryption at DB level is the only choice that survives
  export.
- **Custom AES over stdlib sqlite**: reinventing what SQLCipher
  already does well (page-level encryption, auth tag, KDF). Rejected.
- **Row-level encryption**: too narrow. The graph table alone reveals
  internal APIs.

## Consequences

- Positive: team-share becomes possible; privacy-visible parity with
  Cursor 3; `.context/` safe to commit to a private repo.
- Negative: encrypted DB is ~15% slower on write and ~5% on read
  (SQLCipher benchmarks). Marginal — watch on real scans.
- Negative: binary dependency (`sqlcipher3` wheels exist for macOS /
  Linux / Windows, but source install requires `libsqlcipher-dev`).
  Mitigated by making the dep optional.
- Negative: `libs/patterns/aggregator.py` reads peer projects with the
  stdlib `sqlite3` in `mode=ro`. That driver cannot open encrypted DBs.
  If cross-project patterns run against encrypted caches, the
  aggregator must load the key for each project — design TBD.

## Migration plan (deferred)

1. User sets `LVDCP_STORAGE_KEY` env var with a passphrase.
2. User sets `storage.encryption_key_env: LVDCP_STORAGE_KEY` in
   `~/.lvdcp/config.yaml`.
3. User runs `ctx storage migrate --encrypt` for each project.
4. Migration command: reads plaintext DB, writes encrypted copy to
   `cache.db.new`, swaps atomically.
5. Old plaintext DB is kept as `cache.db.plaintext.bak` for 7 days
   then auto-deleted (unless `--keep-plaintext-backup` passed).

## Scaffolding landed with this ADR

- `storage.encryption_key_env` field in `libs/core/projects_config.py`
  (pydantic `StorageConfig`) — accepts str or None, defaults None.
- `libs/storage/encryption.py` — stateless helpers:
  - `resolve_key(env_name)` — reads env var, validates length, raises
    structured error when absent.
  - `encryption_enabled(config)` — returns bool.
- Unit tests covering config load, env-var resolution, and the
  "encryption requested but env missing" error path.
- `sqlite_cache.py` and the scanner flow are **unchanged** in this
  commit — connecting via sqlcipher3 is the Phase-8 delivery.

Future-me: remove the "scaffolded" status line above when Phase 8 wires
this into the actual connection path and ships the migration command.
