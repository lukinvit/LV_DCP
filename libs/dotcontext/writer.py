"""Write .context/project.md and .context/symbol_index.md."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from libs.core.entities import File, Symbol

DOT_CONTEXT_DIR = ".context"


def _dot_context(root: Path) -> Path:
    d = root / DOT_CONTEXT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_project_md(
    *,
    project_root: Path,
    project_name: str,
    files: Sequence[File],
    total_symbols: int,
    total_relations: int,
) -> Path:
    lang_counts = Counter(f.language for f in files)
    role_counts = Counter(f.role for f in files)
    total_bytes = sum(f.size_bytes for f in files)

    lines: list[str] = []
    lines.append(f"# {project_name} - LV_DCP project overview")
    lines.append("")
    lines.append(f"Generated: `{datetime.now(UTC).isoformat()}`")
    lines.append("")
    lines.append("## Stats")
    lines.append("")
    lines.append(f"- **Files:** {len(files)}")
    lines.append(f"- **Total size:** {total_bytes} bytes")
    lines.append(f"- **Symbols:** {total_symbols}")
    lines.append(f"- **Relations:** {total_relations}")
    lines.append("")
    lines.append("## Languages")
    lines.append("")
    for lang, count in lang_counts.most_common():
        lines.append(f"- {lang}: {count}")
    lines.append("")
    lines.append("## Roles")
    lines.append("")
    for role, count in role_counts.most_common():
        lines.append(f"- {role}: {count}")
    lines.append("")
    lines.append("## Pipeline")
    lines.append("")
    lines.append("- Phase: 1 (deterministic)")
    lines.append("- Generator: `libs/dotcontext/writer.py`")

    path = _dot_context(project_root) / "project.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_symbol_index_md(
    *,
    project_root: Path,
    symbols: Sequence[Symbol],
) -> Path:
    by_file: dict[str, list[Symbol]] = {}
    for s in symbols:
        by_file.setdefault(s.file_path, []).append(s)

    lines: list[str] = []
    lines.append("# Symbol index")
    lines.append("")
    lines.append(f"Generated: `{datetime.now(UTC).isoformat()}`")
    lines.append(f"Total symbols: **{len(symbols)}**")
    lines.append("")

    for file_path in sorted(by_file.keys()):
        lines.append(f"## {file_path}")
        lines.append("")
        for s in sorted(by_file[file_path], key=lambda x: x.start_line):
            lines.append(f"- `{s.fq_name}` - {s.symbol_type.value} (L{s.start_line}-L{s.end_line})")
        lines.append("")

    path = _dot_context(project_root) / "symbol_index.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
