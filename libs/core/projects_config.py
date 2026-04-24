"""Pure read-side for ~/.lvdcp/config.yaml — project registry.

Lives in libs/core so libs/status and other libs can import it without
violating the apps/ -> libs/ layering rule.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class ProjectEntry(BaseModel):
    root: Path
    registered_at_iso: str
    last_scan_at_iso: str | None = None
    last_scan_status: str = "pending"


def _validate_env_var_name(v: str) -> str:
    """Ensure the field contains an env var NAME, not an actual secret."""
    if v.startswith(("sk-", "key-", "token-", "ghp_", "ghs_", "AKIA")):
        msg = (
            f"api_key_env_var must be an environment variable NAME "
            f"(e.g. 'OPENAI_API_KEY'), not the key itself. "
            f"Got value starting with '{v[:6]}...'. "
            f"Set the actual key via: export OPENAI_API_KEY='your-key'"
        )
        raise ValueError(msg)
    return v


class LLMConfig(BaseModel):
    provider: str = "openai"
    summary_model: str = "gpt-4o-mini"
    rerank_model: str = "gpt-4o-mini"
    api_key_env_var: str = "OPENAI_API_KEY"
    monthly_budget_usd: float = 25.0
    prompt_version: str = "v2"
    enabled: bool = False
    summarize_roles: list[str] = Field(default_factory=lambda: ["source", "test"])

    @field_validator("api_key_env_var")
    @classmethod
    def _check_not_secret(cls, v: str) -> str:
        return _validate_env_var_name(v)


class QdrantConfig(BaseModel):
    enabled: bool = False
    url: str = "http://127.0.0.1:6333"
    api_key_env_var: str = ""  # env var name, not the key itself
    collection_prefix: str = "devctx"


class EmbeddingConfig(BaseModel):
    provider: str = "openai"  # "openai" | "ollama" | "fake"
    model: str = "text-embedding-3-small"
    # Must match the model. OpenAI text-embedding-3-small=1536,
    # Ollama nomic-embed-text=768, mxbai-embed-large=1024, all-minilm=384.
    # Changing dimension after scans requires dropping Qdrant collections.
    dimension: int = 1536
    api_key_env_var: str = "OPENAI_API_KEY"
    # Override for OpenAI-compatible endpoints (Ollama, LocalAI, vLLM, etc.).
    # When provider="ollama" and base_url is empty, defaults to
    # http://localhost:11434/v1.
    base_url: str = ""

    @field_validator("api_key_env_var")
    @classmethod
    def _check_not_secret(cls, v: str) -> str:
        return _validate_env_var_name(v)


class ObsidianConfig(BaseModel):
    enabled: bool = False
    vault_path: str = ""
    sync_mode: str = "manual"
    auto_sync_after_scan: bool = False
    debounce_seconds: int = Field(default=3600, gt=0)  # min interval between auto-syncs


class WikiConfig(BaseModel):
    enabled: bool = False
    auto_update_after_scan: bool = False
    max_modules_per_run: int = 10
    article_max_tokens: int = 2000
    dirty_threshold: int = Field(default=3, gt=0)  # min dirty modules to trigger background update
    max_workers: int = Field(default=1, gt=0)  # max concurrent wiki update tasks


class StorageConfig(BaseModel):
    """At-rest encryption scaffold (see ADR-007).

    ``encryption_key_env`` names the environment variable holding the
    SQLCipher passphrase. The key itself is never stored in config.
    ``None`` means plaintext SQLite (current default).

    Phase 8 will wire this field into ``SqliteCache``; for now it is
    scaffolding so the config format is forward-compatible.
    """

    encryption_key_env: str | None = None


class TimelineConfig(BaseModel):
    """Symbol timeline index (spec-010).

    Append-only event store answering "when was X implemented?" and
    "what disappeared after release Y?" with indexed lookups instead
    of git-log walks. ``enabled=False`` is a zero-overhead opt-out:
    scanner skips sink registration entirely.
    """

    enabled: bool = True
    # Relative name under ~/.lvdcp/ when no absolute override is supplied.
    store_filename: str = "symbol_timeline.db"
    # None = keep everything; integer N = prune events older than N days
    # on every append (matches ``scan_history`` behaviour).
    retention_days: int | None = None
    privacy_mode: str = Field(default="balanced")  # strict | balanced | off
    rename_similarity_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    enable_timeline_enrichment: bool = True
    pack_enrichment_markers: list[str] = Field(
        default_factory=lambda: [
            "когда",
            "when was",
            "since v",
            "removed",
            "между v",
            "между релизами",
        ],
    )
    tag_watcher_poll_seconds: int = Field(default=60, gt=0)
    # ``pkg.module:ClassName`` import paths for additional sinks (Obsidian, etc.).
    sink_plugins: list[str] = Field(default_factory=list)

    @field_validator("privacy_mode")
    @classmethod
    def _check_privacy_mode(cls, v: str) -> str:
        allowed = {"strict", "balanced", "off"}
        if v not in allowed:
            msg = f"privacy_mode must be one of {allowed}, got {v!r}"
            raise ValueError(msg)
        return v


class DaemonConfig(BaseModel):
    version: int = Field(default=1)
    projects: list[ProjectEntry] = Field(default_factory=list)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    obsidian: ObsidianConfig = Field(default_factory=ObsidianConfig)
    wiki: WikiConfig = Field(default_factory=WikiConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    timeline: TimelineConfig = Field(default_factory=TimelineConfig)


def load_config(path: Path) -> DaemonConfig:
    if not path.exists():
        return DaemonConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return DaemonConfig.model_validate(data)


def list_projects(config_path: Path) -> list[ProjectEntry]:
    return load_config(config_path).projects


def save_config(path: Path, config: DaemonConfig) -> None:
    """Atomically persist ``config`` to ``path``.

    Writes to a sibling ``*.tmp`` file, fsyncs, then ``rename()`` onto the
    target. On any failure the original file remains intact — the temp file
    is never partially visible at the final path.

    Used by destructive operations like ``ctx registry prune --yes``. Any
    caller that needs an undo handle should take a ``*.bak`` copy before
    invoking — this function focuses on write atomicity, not history.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = yaml.safe_dump(
        config.model_dump(mode="json", exclude_defaults=False),
        sort_keys=False,
        allow_unicode=True,
    )
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(path)
    except Exception:
        # Best-effort cleanup of the half-written temp; re-raise the original.
        if tmp.exists():
            with contextlib.suppress(OSError):
                tmp.unlink()
        raise
