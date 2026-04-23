"""Build :class:`AstSnapshot` objects from an in-repo SqliteCache.

Two collaborators in the scanner (T013):
* previous snapshot - loaded from ``.context/timeline_prev.json``
  (written by the prior scan). First scan: file absent → empty snapshot.
* current snapshot - built from ``cache.iter_symbols()`` AFTER the scan,
  hashing real source-line bytes for each symbol body.

The pair is then fed into :func:`libs.symbol_timeline.differ.diff_ast_snapshots`,
and the scanner writes the current snapshot to ``.context/timeline_prev.json``
on the way out so the next scan has a baseline.

Symbol identity (FR-003) is derived deterministically from
``sha256(project_root | file_path | fq_name | symbol_type)[:32]`` so the
same symbol in two different projects never collides, yet survives content
edits that keep ``fq_name`` stable.

The per-symbol ``content_hash`` prefers the *actual source slice*: when a
``body_reader`` is supplied we hash ``bytes_of_lines(start_line..end_line)``.
When no reader is available, we fall back to a signature-aware proxy that
blends ``fq_name``, ``signature``, ``docstring`` and line range. The
signature-only fallback intentionally under-reports body edits — callers
who care about those edits MUST pass a reader.

Spec: specs/010-feature-timeline-index/data-model.md §1 + §Key Entities.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from libs.symbol_timeline.differ import AstSnapshot, SymbolSnapshot

if TYPE_CHECKING:
    from libs.core.entities import Symbol

PREV_SNAPSHOT_RELPATH = Path(".context") / "timeline_prev.json"
_SNAPSHOT_SCHEMA_VERSION = 1


def compute_symbol_id(*, project_root: str, file_path: str, fq_name: str, symbol_type: str) -> str:
    """Return the stable 32-hex symbol_id (spec FR-003)."""
    payload = f"{project_root}\0{file_path}\0{fq_name}\0{symbol_type}".encode()
    return hashlib.sha256(payload).hexdigest()[:32]


def compute_symbol_content_hash(symbol: Symbol, *, body_bytes: bytes | None = None) -> str:
    """Return the per-symbol content_hash used for modified/moved detection.

    When ``body_bytes`` is provided, it is hashed alongside ``fq_name`` so
    body edits that don't touch the signature still produce distinct hashes.
    When omitted, falls back to the signature/line-range proxy.
    """
    if body_bytes is not None:
        digest = hashlib.sha256()
        digest.update(symbol.fq_name.encode())
        digest.update(b"\0")
        digest.update(body_bytes)
        return digest.hexdigest()[:16]
    payload = "\0".join(
        [
            symbol.fq_name,
            symbol.signature or "",
            symbol.docstring or "",
            str(symbol.start_line),
            str(symbol.end_line),
        ]
    ).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def _default_body_reader(root: Path) -> Callable[[Symbol], bytes | None]:
    """Return a reader that slices ``root/symbol.file_path`` by line range.

    Caches per-file bytes to keep the cost at one read per file per scan.
    Returns ``None`` for any file that can't be read (e.g., removed between
    pre- and post-snapshot).
    """
    cache: dict[str, list[bytes] | None] = {}

    def read(symbol: Symbol) -> bytes | None:
        lines = cache.get(symbol.file_path)
        if lines is None and symbol.file_path not in cache:
            try:
                raw = (root / symbol.file_path).read_bytes()
            except OSError:
                cache[symbol.file_path] = None
                return None
            lines = raw.splitlines(keepends=True)
            cache[symbol.file_path] = lines
        if lines is None:
            return None
        # start_line / end_line are 1-based per parser contract.
        start = max(1, symbol.start_line) - 1
        end = max(symbol.end_line, symbol.start_line)
        slice_ = lines[start:end]
        return b"".join(slice_) if slice_ else b""

    return read


def build_snapshot_from_symbols(
    symbols: Iterable[Symbol],
    *,
    project_root: str,
    commit_sha: str | None,
    body_reader: Callable[[Symbol], bytes | None] | None = None,
) -> AstSnapshot:
    """Map ``Symbol`` rows from SqliteCache into an :class:`AstSnapshot`.

    Pass ``body_reader`` (e.g., :func:`_default_body_reader`) to get
    body-accurate content hashes; omit it for cheap signature-only hashes.
    """
    snap: dict[str, SymbolSnapshot] = {}
    for s in symbols:
        if not s.fq_name:
            continue
        sid = compute_symbol_id(
            project_root=project_root,
            file_path=s.file_path,
            fq_name=s.fq_name,
            symbol_type=str(s.symbol_type),
        )
        body = body_reader(s) if body_reader is not None else None
        snap[sid] = SymbolSnapshot(
            symbol_id=sid,
            file_path=s.file_path,
            content_hash=compute_symbol_content_hash(s, body_bytes=body),
            qualified_name=s.fq_name,
        )
    return AstSnapshot(symbols=snap, commit_sha=commit_sha)


def build_snapshot_from_cache(
    symbols: Iterable[Symbol],
    *,
    project_root: str,
    root_path: Path,
    commit_sha: str | None,
) -> AstSnapshot:
    """Convenience: build a body-accurate snapshot from symbols + filesystem."""
    return build_snapshot_from_symbols(
        symbols,
        project_root=project_root,
        commit_sha=commit_sha,
        body_reader=_default_body_reader(root_path),
    )


def save_snapshot(snapshot: AstSnapshot, *, path: Path) -> None:
    """Serialize ``snapshot`` to ``path`` as JSON (schema-versioned)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _SNAPSHOT_SCHEMA_VERSION,
        "commit_sha": snapshot.commit_sha,
        "symbols": [
            {
                "symbol_id": s.symbol_id,
                "file_path": s.file_path,
                "content_hash": s.content_hash,
                "qualified_name": s.qualified_name,
            }
            for s in snapshot.symbols.values()
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")


def load_snapshot(path: Path) -> AstSnapshot | None:
    """Load a snapshot saved by :func:`save_snapshot`, or ``None`` if missing.

    Malformed or wrong-version files are treated as missing so a corrupted
    sidecar doesn't wedge the scan — the next scan overwrites it with a
    fresh snapshot anyway.
    """
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != _SNAPSHOT_SCHEMA_VERSION:
        return None
    raw_symbols = payload.get("symbols")
    if not isinstance(raw_symbols, list):
        return None
    out: dict[str, SymbolSnapshot] = {}
    for row in raw_symbols:
        if not isinstance(row, dict):
            continue
        try:
            snap = SymbolSnapshot(
                symbol_id=str(row["symbol_id"]),
                file_path=str(row["file_path"]),
                content_hash=str(row["content_hash"]),
                qualified_name=row.get("qualified_name"),
            )
        except KeyError:
            continue
        out[snap.symbol_id] = snap
    return AstSnapshot(symbols=out, commit_sha=payload.get("commit_sha"))
