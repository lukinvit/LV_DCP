"""Pure read-side for ~/.lvdcp/config.yaml — project registry.

Lives in libs/core so libs/status and other libs can import it without
violating the apps/ -> libs/ layering rule.
"""

from __future__ import annotations

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
    provider: str = "openai"  # "openai" | "ollama" | "bge_m3" | "fake"
    model: str = "text-embedding-3-small"
    # Must match the model. OpenAI text-embedding-3-small=1536,
    # Ollama nomic-embed-text=768, mxbai-embed-large=1024, all-minilm=384,
    # bge-m3=1024. Changing dimension after scans requires dropping Qdrant
    # collections.
    dimension: int = 1536
    api_key_env_var: str = "OPENAI_API_KEY"
    # Override for OpenAI-compatible endpoints (Ollama, LocalAI, vLLM, etc.).
    # When provider="ollama" and base_url is empty, defaults to
    # http://localhost:11434/v1.
    base_url: str = ""

    # bge-m3 unified embedder (spec #1). Ignored when provider != "bge_m3".
    # Device auto-detect: MPS -> CUDA -> CPU.
    bge_m3_device: str = "auto"  # "auto" | "mps" | "cuda" | "cpu"
    bge_m3_use_sparse: bool = True
    bge_m3_use_colbert: bool = True
    # RRF fusion weights for hybrid search across the three vector kinds.
    fusion_weights: dict[str, float] = Field(
        default_factory=lambda: {"dense": 1.0, "sparse": 1.0, "colbert": 0.7}
    )
    # Gradual rollout gate — off by default; flipping to True without
    # explicit migration is rejected by the embed service.
    enable_bge_m3: bool = False

    @field_validator("api_key_env_var")
    @classmethod
    def _check_not_secret(cls, v: str) -> str:
        return _validate_env_var_name(v)

    @field_validator("bge_m3_device")
    @classmethod
    def _check_device(cls, v: str) -> str:
        allowed = {"auto", "mps", "cuda", "cpu"}
        if v not in allowed:
            msg = f"bge_m3_device must be one of {sorted(allowed)}, got {v!r}"
            raise ValueError(msg)
        return v

    @field_validator("fusion_weights")
    @classmethod
    def _check_fusion_weights(cls, v: dict[str, float]) -> dict[str, float]:
        required = {"dense", "sparse", "colbert"}
        missing = required - v.keys()
        if missing:
            msg = f"fusion_weights missing keys: {sorted(missing)}"
            raise ValueError(msg)
        for key, weight in v.items():
            if weight < 0:
                msg = f"fusion_weights[{key!r}] must be >= 0, got {weight}"
                raise ValueError(msg)
        return v


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


class DaemonConfig(BaseModel):
    version: int = Field(default=1)
    projects: list[ProjectEntry] = Field(default_factory=list)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    obsidian: ObsidianConfig = Field(default_factory=ObsidianConfig)
    wiki: WikiConfig = Field(default_factory=WikiConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)


def load_config(path: Path) -> DaemonConfig:
    if not path.exists():
        return DaemonConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return DaemonConfig.model_validate(data)


def list_projects(config_path: Path) -> list[ProjectEntry]:
    return load_config(config_path).projects
