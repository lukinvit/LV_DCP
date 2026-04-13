"""Pure read-side for ~/.lvdcp/config.yaml — project registry.

Lives in libs/core so libs/status and other libs can import it without
violating the apps/ -> libs/ layering rule.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ProjectEntry(BaseModel):
    root: Path
    registered_at_iso: str
    last_scan_at_iso: str | None = None
    last_scan_status: str = "pending"


class LLMConfig(BaseModel):
    provider: str = "openai"
    summary_model: str = "gpt-4o-mini"
    rerank_model: str = "gpt-4o-mini"
    api_key_env_var: str = "OPENAI_API_KEY"
    monthly_budget_usd: float = 25.0
    prompt_version: str = "v2"
    enabled: bool = False
    summarize_roles: list[str] = Field(default_factory=lambda: ["source", "test"])


class QdrantConfig(BaseModel):
    enabled: bool = False
    url: str = "http://127.0.0.1:6333"
    api_key_env_var: str = ""  # env var name, not the key itself
    collection_prefix: str = "devctx"


class EmbeddingConfig(BaseModel):
    provider: str = "openai"  # "openai" | "local" | "fake"
    model: str = "text-embedding-3-small"
    dimension: int = 1536
    api_key_env_var: str = "OPENAI_API_KEY"
    base_url: str = ""  # override for local/compatible endpoints


class DaemonConfig(BaseModel):
    version: int = Field(default=1)
    projects: list[ProjectEntry] = Field(default_factory=list)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)


def load_config(path: Path) -> DaemonConfig:
    if not path.exists():
        return DaemonConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return DaemonConfig.model_validate(data)


def list_projects(config_path: Path) -> list[ProjectEntry]:
    return load_config(config_path).projects
