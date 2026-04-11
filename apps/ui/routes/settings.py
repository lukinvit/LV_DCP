"""GET /settings — settings page + POST /settings — save + test-connection."""

from __future__ import annotations

import os

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from libs.core.projects_config import LLMConfig, load_config
from libs.llm.errors import LLMConfigError, LLMProviderError
from libs.llm.registry import create_client
from libs.status.aggregator import resolve_config_path
from libs.status.budget import compute_budget_status
from starlette.templating import _TemplateResponse

from apps.agent.config import save_config

router = APIRouter()

AVAILABLE_PROVIDERS = ["openai", "anthropic", "ollama"]
DEFAULT_MODELS_BY_PROVIDER = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5",
    "ollama": "qwen2.5-coder:7b",
}


def _api_key_status(llm: LLMConfig) -> str:
    if llm.provider == "ollama":
        return "n/a"
    return "set" if os.environ.get(llm.api_key_env_var) else "unset"


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> _TemplateResponse:
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
            "api_key_status": _api_key_status(config.llm),
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
    config = load_config(resolve_config_path())
    config.llm = LLMConfig(
        provider=provider,
        summary_model=summary_model,
        rerank_model=rerank_model,
        api_key_env_var=api_key_env_var,
        monthly_budget_usd=monthly_budget_usd,
        enabled=enabled == "on",
        prompt_version=config.llm.prompt_version,
    )
    save_config(resolve_config_path(), config)
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/api/settings/test-connection")
async def test_connection() -> JSONResponse:
    config = load_config(resolve_config_path())
    try:
        client = create_client(config.llm)
        await client.test_connection()
        return JSONResponse(
            {
                "status": "ok",
                "detail": f"Connected to {config.llm.provider}/{config.llm.summary_model}",
            }
        )
    except (LLMConfigError, LLMProviderError) as exc:
        return JSONResponse({"status": "error", "detail": str(exc)[:200]})
