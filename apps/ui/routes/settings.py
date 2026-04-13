"""GET /settings — settings page + POST /settings — save + test-connection."""

from __future__ import annotations

import os

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from libs.core.projects_config import load_config
from libs.llm.errors import LLMConfigError, LLMProviderError
from libs.llm.registry import create_client
from libs.status.aggregator import resolve_config_path
from libs.status.budget import compute_budget_status
from starlette.templating import _TemplateResponse

from apps.agent.config import save_config

router = APIRouter()

AVAILABLE_PROVIDERS = ["openai", "anthropic", "ollama"]
EMBEDDING_PROVIDERS = ["openai", "fake", "local"]
DEFAULT_MODELS_BY_PROVIDER = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5",
    "ollama": "qwen2.5-coder:7b",
}


def _api_key_status(env_var: str, provider: str = "") -> str:
    if provider == "ollama":
        return "n/a"
    if not env_var:
        return "n/a"
    return "set" if os.environ.get(env_var) else "unset"


def _qdrant_status(url: str, enabled: bool) -> str:
    if not enabled:
        return "disabled"
    try:
        import httpx  # noqa: PLC0415

        r = httpx.get(f"{url}/collections", timeout=2)
        return "ok" if r.status_code == 200 else "error"
    except Exception:
        return "unreachable"


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    saved: bool = Query(False),
    error: str = Query(""),
) -> _TemplateResponse:
    config = load_config(resolve_config_path())
    budget = compute_budget_status(config.llm)
    templates = request.app.state.templates
    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request=request,
        name="settings.html.j2",
        context={
            "llm_config": config.llm,
            "available_providers": AVAILABLE_PROVIDERS,
            "default_models_by_provider": DEFAULT_MODELS_BY_PROVIDER,
            "budget": budget,
            "ws_usage_7d": None,  # base template expects this
            "api_key_status": _api_key_status(config.llm.api_key_env_var, config.llm.provider),
            "qdrant_config": config.qdrant,
            "qdrant_status": _qdrant_status(config.qdrant.url, config.qdrant.enabled),
            "embedding_config": config.embedding,
            "embedding_providers": EMBEDDING_PROVIDERS,
            "embedding_key_status": _api_key_status(config.embedding.api_key_env_var, config.embedding.provider),
            "saved": saved,
            "error": error,
        },
    )


@router.post("/settings")
def save_settings(  # noqa: PLR0913
    provider: str = Form(...),
    summary_model: str = Form(...),
    rerank_model: str = Form(...),
    api_key_env_var: str = Form(...),
    monthly_budget_usd: float = Form(...),
    enabled: str | None = Form(None),
) -> RedirectResponse:
    # Protect against pasting the actual key instead of the env var name
    if api_key_env_var.startswith(("sk-", "key-", "token-", "ghp_", "ghs_", "AKIA")):
        # User pasted the secret — reject and redirect with error
        return RedirectResponse(
            url="/settings?error=api_key_env_var+must+be+an+environment+variable+NAME"
            "+like+OPENAI_API_KEY+not+the+key+itself.+Set+the+key+via+export+OPENAI_API_KEY",
            status_code=303,
        )

    config = load_config(resolve_config_path())
    # Only update LLM fields — preserve qdrant, embedding, and other sections
    config.llm.provider = provider
    config.llm.summary_model = summary_model
    config.llm.rerank_model = rerank_model
    config.llm.api_key_env_var = api_key_env_var
    config.llm.monthly_budget_usd = monthly_budget_usd
    config.llm.enabled = enabled == "on"
    save_config(resolve_config_path(), config)
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/settings/qdrant")
def save_qdrant_settings(
    qdrant_enabled: str | None = Form(None),
    qdrant_url: str = Form("http://127.0.0.1:6333"),
    collection_prefix: str = Form("devctx"),
) -> RedirectResponse:
    config = load_config(resolve_config_path())
    config.qdrant.enabled = qdrant_enabled == "on"
    config.qdrant.url = qdrant_url
    config.qdrant.collection_prefix = collection_prefix
    save_config(resolve_config_path(), config)
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/settings/embedding")
def save_embedding_settings(
    embedding_provider: str = Form("openai"),
    embedding_model: str = Form("text-embedding-3-small"),
    embedding_dimension: int = Form(1536),
    embedding_api_key_env_var: str = Form("OPENAI_API_KEY"),
    embedding_base_url: str = Form(""),
) -> RedirectResponse:
    if embedding_api_key_env_var.startswith(("sk-", "key-", "token-", "ghp_", "ghs_", "AKIA")):
        return RedirectResponse(
            url="/settings?error=embedding+api_key_env_var+must+be+a+variable+NAME+not+the+key",
            status_code=303,
        )
    config = load_config(resolve_config_path())
    config.embedding.provider = embedding_provider
    config.embedding.model = embedding_model
    config.embedding.dimension = embedding_dimension
    config.embedding.api_key_env_var = embedding_api_key_env_var
    config.embedding.base_url = embedding_base_url
    save_config(resolve_config_path(), config)
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/api/settings/test-qdrant", response_class=HTMLResponse)
def test_qdrant() -> HTMLResponse:
    config = load_config(resolve_config_path())
    if not config.qdrant.enabled:
        return HTMLResponse('<span class="test-result test-error">&#10007; Qdrant disabled</span>')
    try:
        import httpx  # noqa: PLC0415

        r = httpx.get(f"{config.qdrant.url}/collections", timeout=3)
        if r.status_code == 200:
            data = r.json()
            count = len(data.get("result", {}).get("collections", []))
            return HTMLResponse(
                f'<span class="test-result test-ok">&#10003; Connected — {count} collections</span>'
            )
        return HTMLResponse(
            f'<span class="test-result test-error">&#10007; HTTP {r.status_code}</span>'
        )
    except Exception as exc:
        return HTMLResponse(
            f'<span class="test-result test-error">&#10007; {str(exc)[:100]}</span>'
        )


@router.post("/api/settings/test-connection", response_class=HTMLResponse)
async def test_connection() -> HTMLResponse:
    config = load_config(resolve_config_path())
    try:
        client = create_client(config.llm)
        await client.test_connection()
        return HTMLResponse(
            f'<span class="test-result test-ok">&#10003; Connected to '
            f"{config.llm.provider}/{config.llm.summary_model}</span>"
        )
    except (LLMConfigError, LLMProviderError) as exc:
        return HTMLResponse(
            f'<span class="test-result test-error">&#10007; {str(exc)[:200]}</span>'
        )
