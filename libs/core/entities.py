"""Domain entities for LV_DCP.

All models are frozen (immutable) — parse/retrieve results are values, not state.
Mutation lives exclusively in libs/storage.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SymbolType(StrEnum):
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    VARIABLE = "variable"
    CONSTANT = "constant"
    IMPORT = "import"
    MODULE = "module"


class RelationType(StrEnum):
    # Phase 1 — deterministic only
    IMPORTS = "imports"
    DEFINES = "defines"
    SAME_FILE_CALLS = "same_file_calls"
    # Phase 2+ — reserved for later
    REFERENCES = "references"
    USES_ENV = "uses_env"


class PackMode(StrEnum):
    NAVIGATE = "navigate"
    EDIT = "edit"


class Immutable(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class File(Immutable):
    path: str  # POSIX relative to project root
    content_hash: str  # hex sha256
    size_bytes: int
    language: str  # "python" | "markdown" | "yaml" | "json" | "toml" | "text"
    role: str  # "source" | "test" | "docs" | "config" | "generated" | "unknown"
    is_generated: bool = False
    is_binary: bool = False


class Symbol(Immutable):
    name: str
    fq_name: str  # dotted fully qualified name
    symbol_type: SymbolType
    file_path: str
    start_line: int
    end_line: int
    parent_fq_name: str | None = None
    signature: str | None = None
    docstring: str | None = None


class Relation(Immutable):
    src_type: str  # "file" | "symbol"
    src_ref: str  # path or fq_name
    dst_type: str
    dst_ref: str
    relation_type: RelationType
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    provenance: str = "deterministic"


class Summary(Immutable):
    entity_type: str  # "file" | "symbol" | "module" | "project"
    entity_ref: str
    summary_type: str  # "file_summary" | "symbol_summary" | ...
    text: str
    text_hash: str
    model_name: str  # "deterministic" in Phase 1; LLM model in Phase 2
    model_version: str
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


class Project(Immutable):
    name: str
    slug: str
    local_path: str
    default_branch: str = "main"
    languages: tuple[str, ...] = ()


class ContextPack(Immutable):
    project_slug: str
    query: str
    mode: PackMode
    assembled_markdown: str
    size_bytes: int
    retrieved_files: tuple[str, ...] = ()
    retrieved_symbols: tuple[str, ...] = ()
    pipeline_version: str = "phase-1-v0"
