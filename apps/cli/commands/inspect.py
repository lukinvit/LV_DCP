"""`ctx inspect <path>` — print index stats for a scanned project."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import TypedDict

import typer
from libs.project_index.index import ProjectIndex, ProjectNotIndexedError


class InspectPayload(TypedDict):
    """Schema-locked output of `ctx inspect` (text and `--json` paths).

    Keeping the keys typed (vs. `dict[str, object]`) lets mypy strict catch
    field-name typos in the renderer and gives JSON consumers a stable
    documented contract. Adding a field here is the single point that surfaces
    it in both text and JSON outputs — by design.
    """

    path: str
    files: int
    language_counts: dict[str, int]
    symbols: int
    symbol_type_counts: dict[str, int]
    relations: int
    relation_type_counts: dict[str, int]


def _collect_inspect_payload(idx: ProjectIndex, *, path: Path) -> InspectPayload:
    """Build the schema-locked payload for both text and JSON output paths.

    `*_counts` dicts are insertion-ordered by descending count
    (mirrors `Counter.most_common`) so JSON consumers get the same ordering
    semantics as the human-readable view — `jq '.language_counts | to_entries[0].key'`
    yields the most-frequent language without an explicit sort.

    `path` is stringified for JSON-serializability; counters become plain
    `dict[str, int]` for the same reason.
    """
    files = list(idx.iter_files())
    symbols = list(idx.iter_symbols())
    relations = list(idx.iter_relations())

    lang_counts = Counter(f.language for f in files)
    sym_type_counts = Counter(s.symbol_type.value for s in symbols)
    rel_type_counts = Counter(r.relation_type.value for r in relations)

    return InspectPayload(
        path=str(path),
        files=len(files),
        language_counts=dict(lang_counts.most_common()),
        symbols=len(symbols),
        symbol_type_counts=dict(sym_type_counts.most_common()),
        relations=len(relations),
        relation_type_counts=dict(rel_type_counts.most_common()),
    )


def _render_text(payload: InspectPayload, *, name: str) -> str:
    """Render the same payload `_collect_inspect_payload` builds as text.

    Single source of truth for the row order and labels — keeps text and
    JSON paths in lockstep so a future schema field automatically surfaces
    in both views.
    """
    lines: list[str] = [
        f"project: {name}",
        f"files: {payload['files']}",
    ]
    for lang, count in payload["language_counts"].items():
        lines.append(f"  {lang}: {count}")
    lines.append(f"symbols: {payload['symbols']}")
    for sym_t, sym_c in payload["symbol_type_counts"].items():
        lines.append(f"  {sym_t}: {sym_c}")
    lines.append(f"relations: {payload['relations']}")
    for rel_t, rel_c in payload["relation_type_counts"].items():
        lines.append(f"  {rel_t}: {rel_c}")
    return "\n".join(lines)


def inspect(
    path: Path,
    *,
    as_json: bool = False,
) -> None:
    """Print index stats for a scanned project.

    Note: this function is invoked directly from `apps/cli/main.py::inspect`
    (the Typer-decorated CLI wrapper) — not by Typer itself. Defaults are
    plain values so direct callers (and tests) can omit kwargs without
    tripping `typer.OptionInfo` truthiness ambiguity. Same pattern the scan
    command adopted in v0.8.42.
    """
    resolved = path.resolve()
    try:
        idx = ProjectIndex.open(resolved)
    except ProjectNotIndexedError as exc:
        # Error stays on stderr in BOTH text and --json modes — JSON
        # consumers gate on exit code, not on parsing the error string.
        # Emitting `{"error": "..."}` on stdout would split the contract
        # (stdout is sometimes JSON, sometimes prose) and force every
        # consumer to parse-then-check-keys instead of just relying on
        # `set -e` semantics.
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    with idx:
        payload = _collect_inspect_payload(idx, path=resolved)

    if as_json:
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(_render_text(payload, name=resolved.name))
