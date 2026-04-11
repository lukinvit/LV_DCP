# Phase 3c.1 — LLM Infrastructure + Summaries

**Status:** Approved 2026-04-11
**Owner:** Vladimir Lukin
**Follows:** Phase 3b complete (`phase-3b-complete` tag, version 0.3.1)
**Precedes:** Phase 3c.2 (vector search + rerank + retrieval quality gates)
**Decomposition:** Variant B from brainstorm — 3c.1 ≤ 2 weeks, then ≤1 week gap, then 3c.2 ~2.5 weeks

## 1. Цель

Заложить **работающий LLM слой** в LV_DCP: pluggable providers (OpenAI default, Anthropic + Ollama alternatives), persistent summary cache с content hashing, cost tracking с monthly budget enforcement, UI settings page. Retrieval pipeline **не меняется**. Summaries становятся видимым артефактом в dashboard и доступными через MCP, но существующие eval метрики остаются identical.

Это **не** "подготовка к 3c.2". Это standalone подфаза с independently useful deliverable: пользователь смотрит на проект в dashboard и видит AI-generated summaries файлов, знает сколько LLM API ему стоил этот месяц, и может переключить provider через UI без редактирования конфигов.

## 2. Context — закрытые design points

Brainstorm 2026-04-11 зафиксировал все критичные решения:

- **Variant A scope**: full LLM infrastructure, не measurement-first (eval targets 0.92/0.85 будут достигаться в 3c.2 с rerank'ом)
- **Provider D (pluggable)** с **дефолтом OpenAI** (`gpt-4o-mini` для summaries). Anthropic и Ollama — alternatives через тот же interface.
- **Granularity hybrid C**: file-level summaries в 3c.1, symbol-level signatures для embeddings — в 3c.2. Module-level — никогда (не стоит complexity).
- **Summary strategy**: OpenAI GPT-4o-mini даёт cold scan LV_DCP ~$0.055, 500-файловый canary ~$0.155 — укладывается в ≤$0.50 ADR-001 budget с запасом ×3. ADR обновлять **не** нужно.
- **Cache key composition**: `(content_hash, prompt_version, model_name)` — bumping prompt version инвалидирует cache. Per-model column позволяет сравнивать providers на одинаковых файлах.
- **API keys security**: ТОЛЬКО env vars (OPENAI_API_KEY и т.п.). НИКОГДА в config.yaml.
- **Rerank в 3c.1 НЕ делается**: метод `rerank()` объявлен в protocol но raise'ает NotImplementedError — реализация целиком в 3c.2.
- **UI settings configurable**: пользователь может переключить provider / model / budget через `/settings` page в dashboard.
- **Versioning**: `pyproject.toml` 0.3.1 → 0.3.2 (phase-based scheme).

## 3. Scope — 5 deliverables

### D1 — `libs/llm/` pluggable provider abstraction

Новый пакет с provider-agnostic interface. Три реализации.

**`libs/llm/base.py`** — `LLMClient` Protocol:
- `async summarize(content: str, *, model: str, prompt_version: str) -> SummaryResult` — обязательный метод
- `async rerank(query: str, candidates: list[RerankCandidate], *, model: str) -> list[RerankResult]` — объявлен в interface, но `raise NotImplementedError("rerank is Phase 3c.2")` in all 3c.1 implementations
- `async test_connection() -> bool` — ping API with trivial request (example: "list models" for OpenAI, `HEAD /api/tags` for Ollama), returns True on success, raises `LLMProviderError` on auth/connection failure

**`libs/llm/openai_client.py`** — OpenAI адаптер через `openai>=1.50` async SDK:
- Uses `AsyncOpenAI(api_key=os.environ[env_var])` at construction
- `summarize()` calls `chat.completions.create(model=..., messages=[...])` with `temperature=0.0` for determinism
- Extracts `usage.prompt_tokens` / `usage.completion_tokens` / `usage.prompt_tokens_details.cached_tokens` from response
- Computes `cost_usd` via `libs.llm.cost.calculate_cost(usage, model)`
- Prompt caching via OpenAI's automatic `cached_tokens` accounting — no explicit header needed

**`libs/llm/anthropic_client.py`** — Anthropic API через `anthropic>=0.40` async SDK:
- `AsyncAnthropic(api_key=os.environ[env_var])`
- `summarize()` uses `messages.create(model=..., system=..., messages=[{"role": "user", "content": ...}])`
- Extracts `usage.input_tokens` / `usage.output_tokens` / `usage.cache_creation_input_tokens` / `usage.cache_read_input_tokens`
- Explicit `anthropic-beta: prompt-caching-2024-07-31` header via client construction
- System prompt cached via `cache_control: {type: "ephemeral"}` on system message

**`libs/llm/ollama_client.py`** — локальный Ollama через HTTP:
- Base URL `http://localhost:11434` (configurable via `OLLAMA_HOST` env var)
- `summarize()` calls `POST /api/generate` with `{"model": ..., "prompt": ..., "system": ..., "stream": false}`
- No native token counts — compute approximately via `tiktoken` encoding (`cl100k_base`) for input length + response length / 4
- Cost always **$0** (always local compute)
- `test_connection()` → `GET /api/tags`, verify model listed in response

**`libs/llm/models.py`** — pydantic DTOs (not dataclasses — consistent with libs/status convention):
```python
class ModelSpec(BaseModel):
    name: str
    provider: str  # "openai" | "anthropic" | "ollama"
    context_window: int
    pricing_input_per_mtok: float  # USD per million input tokens
    pricing_output_per_mtok: float
    pricing_cache_read_per_mtok: float = 0.0  # reduced rate for cache hits

class UsageRecord(BaseModel):
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    cost_usd: float
    model: str
    provider: str
    timestamp: float

class SummaryResult(BaseModel):
    text: str
    usage: UsageRecord

# NOTE: provider configuration lives in libs/core/projects_config.LLMConfig
# (part of config.yaml schema, shared with apps/agent/config.py).
# libs/llm/registry.create_client takes that LLMConfig directly — no separate
# ProviderConfig duplicate. See D4 below for the schema.

class RerankCandidate(BaseModel):
    id: str
    summary: str  # or file head if no summary available

class RerankResult(BaseModel):
    id: str
    relevance_score: float
```

**`libs/llm/cost.py`** — static pricing tables + compute helpers:
```python
MODELS: dict[str, ModelSpec] = {
    "gpt-4o-mini":       ModelSpec(name="gpt-4o-mini", provider="openai",
                                    context_window=128_000,
                                    pricing_input_per_mtok=0.15,
                                    pricing_output_per_mtok=0.60,
                                    pricing_cache_read_per_mtok=0.075),
    "gpt-5-mini":        ModelSpec(name="gpt-5-mini", provider="openai",
                                    context_window=400_000,
                                    pricing_input_per_mtok=0.25,
                                    pricing_output_per_mtok=2.00,
                                    pricing_cache_read_per_mtok=0.025),
    "gpt-5":             ModelSpec(name="gpt-5", provider="openai",
                                    context_window=400_000,
                                    pricing_input_per_mtok=1.25,
                                    pricing_output_per_mtok=10.00,
                                    pricing_cache_read_per_mtok=0.125),
    "claude-haiku-4-5":  ModelSpec(name="claude-haiku-4-5", provider="anthropic",
                                    context_window=200_000,
                                    pricing_input_per_mtok=0.80,
                                    pricing_output_per_mtok=4.00,
                                    pricing_cache_read_per_mtok=0.08),
    "claude-sonnet-4-6": ModelSpec(name="claude-sonnet-4-6", provider="anthropic",
                                    context_window=1_000_000,
                                    pricing_input_per_mtok=3.00,
                                    pricing_output_per_mtok=15.00,
                                    pricing_cache_read_per_mtok=0.30),
    # Ollama models all free
    "qwen2.5-coder:32b": ModelSpec(name="qwen2.5-coder:32b", provider="ollama",
                                    context_window=32_768, pricing_input_per_mtok=0,
                                    pricing_output_per_mtok=0),
    "qwen2.5-coder:7b":  ModelSpec(name="qwen2.5-coder:7b", provider="ollama",
                                    context_window=32_768, pricing_input_per_mtok=0,
                                    pricing_output_per_mtok=0),
    "llama3.3:70b":      ModelSpec(name="llama3.3:70b", provider="ollama",
                                    context_window=128_000, pricing_input_per_mtok=0,
                                    pricing_output_per_mtok=0),
}

def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> float:
    spec = MODELS[model]
    regular_input = input_tokens - cached_input_tokens
    cost = (
        regular_input * spec.pricing_input_per_mtok / 1_000_000
        + cached_input_tokens * spec.pricing_cache_read_per_mtok / 1_000_000
        + output_tokens * spec.pricing_output_per_mtok / 1_000_000
    )
    return round(cost, 8)
```

**`libs/llm/registry.py`** — factory (takes `LLMConfig` from `libs/core/projects_config`):
```python
from libs.core.projects_config import LLMConfig

def create_client(config: LLMConfig) -> LLMClient:
    """Create an LLMClient for the configured provider. Raises LLMConfigError
    if api_key env var is missing (for non-ollama providers)."""
    if config.provider == "openai":
        api_key = os.environ.get(config.api_key_env_var)
        if not api_key:
            raise LLMConfigError(
                f"{config.api_key_env_var} env var not set. "
                f"Run: export {config.api_key_env_var}=sk-..."
            )
        return OpenAIClient(api_key=api_key)
    if config.provider == "anthropic":
        api_key = os.environ.get(config.api_key_env_var)
        if not api_key:
            raise LLMConfigError(
                f"{config.api_key_env_var} env var not set. "
                f"Run: export {config.api_key_env_var}=sk-ant-..."
            )
        return AnthropicClient(api_key=api_key)
    if config.provider == "ollama":
        return OllamaClient()  # no key needed
    raise LLMConfigError(f"unknown provider: {config.provider}")
```

**`libs/llm/errors.py`** — exception hierarchy:
- `LLMConfigError` — configuration invalid (missing env var, unknown provider)
- `LLMProviderError` — provider API failure (network, rate limit, auth)
- `BudgetExceededError` — attempted operation would exceed monthly budget (raised by pipeline, not client)

### D2 — `libs/summaries/` summary generation pipeline

**`libs/summaries/store.py`** — sqlite-backed cache at `~/.lvdcp/summaries.db`:

```sql
CREATE TABLE summaries (
    content_hash    TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    model_name      TEXT NOT NULL,
    project_root    TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    summary_text    TEXT NOT NULL,
    created_at      REAL NOT NULL,
    cost_usd        REAL NOT NULL,
    tokens_in       INTEGER NOT NULL,
    tokens_out      INTEGER NOT NULL,
    tokens_cached   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (content_hash, prompt_version, model_name)
);

CREATE INDEX idx_summaries_project_file
    ON summaries (project_root, file_path);

CREATE INDEX idx_summaries_created_at
    ON summaries (created_at);
```

Functions:
- `SummaryStore(db_path)` context manager
- `lookup(content_hash, prompt_version, model_name) -> SummaryRow | None`
- `persist(SummaryRow)` — INSERT OR REPLACE
- `list_for_project(project_root) -> list[SummaryRow]`
- `total_cost_since(since_ts) -> float`

Default path: `resolve_default_store_path()` reads env var `LVDCP_SUMMARIES_DB`, falls back to `~/.lvdcp/summaries.db`. Same pattern as Phase 3b `scan_history.store`.

**`libs/summaries/prompts.py`** — prompt templates with version ID:

```python
FILE_SUMMARY_PROMPT_V1 = {
    "version": "v1",
    "system": (
        "You are a Python code summarizer. Given a file, produce exactly 2-3 "
        "sentences describing: (1) what this file does as its main responsibility, "
        "(2) its key exported symbols or entry points, (3) its role in a larger "
        "system if inferable. Use technical tone, no preamble, no boilerplate like "
        "'This file contains...'. Output plain text only, no markdown."
    ),
    "user_template": (
        "File path: {file_path}\n"
        "```python\n{content}\n```\n\n"
        "Summary:"
    ),
}
```

Format for non-python files: reuse same template but drop `python` code fence label. Parser language is already detected in `.context/cache.db`, pass through to template.

**`libs/summaries/generator.py`**:
```python
async def generate_file_summary(
    file_path: str,
    content: str,
    client: LLMClient,
    *,
    model: str,
    prompt_version: str = "v1",
) -> SummaryResult:
    """Generate a single file summary. Low-level — caller handles caching."""
    # Compose prompt from template and call client.summarize
```

**`libs/summaries/pipeline.py`** — orchestrator:

```python
@dataclass(frozen=True)
class SummarizeResult:
    project_root: Path
    files_total: int
    files_summarized: int  # cache misses — actually called LLM
    files_cached: int      # cache hits — skipped LLM call
    total_cost_usd: float
    total_tokens_in: int
    total_tokens_out: int
    elapsed_seconds: float
    errors: list[str]      # file paths that failed; pipeline continues


async def summarize_project(
    root: Path,
    *,
    client: LLMClient,
    model: str,
    prompt_version: str,
    store: SummaryStore,
    concurrency: int = 10,
    progress_callback: Callable[[int, int], None] | None = None,
) -> SummarizeResult:
    """Iterate files in the project index, summarize each one (with cache lookup),
    persist results.

    - Opens ProjectIndex.open(root) to enumerate files from .context/cache.db
    - For each file: compute content_hash from file on disk
    - Lookup (content_hash, prompt_version, model) in store
      - hit: increment files_cached, skip LLM call
      - miss: read file bytes, call generate_file_summary, persist result
    - Uses asyncio.gather with Semaphore(concurrency) for parallel LLM calls
    - progress_callback(current_index, total) called after each file (for rich UI)
    - Errors on individual files logged but do not halt the pipeline
    """
```

### D3 — UI `/settings` page + cost tracking widget

**New route module `apps/ui/routes/settings.py`**:

```python
@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    """Render settings form with current provider + budget config."""
    config = _load_llm_config()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request, name="settings.html.j2",
        context={
            "llm_config": config,
            "available_providers": ["openai", "anthropic", "ollama"],
            "default_models_by_provider": {
                "openai": "gpt-4o-mini",
                "anthropic": "claude-haiku-4-5",
                "ollama": "qwen2.5-coder:7b",
            },
            "budget_status": _compute_budget_status(config),
            "api_key_status": _check_api_key_env_var(config),
        },
    )

@router.post("/settings")
def save_settings(...): ...

@router.post("/api/settings/test-connection", response_class=JSONResponse)
async def test_connection() -> JSONResponse:
    """Invoke client.test_connection() for current provider, return JSON."""
    config = _load_llm_config()
    try:
        client = create_client(config)
        await client.test_connection()
        return JSONResponse({"status": "ok", "detail": f"Connected to {config.provider}"})
    except (LLMConfigError, LLMProviderError) as exc:
        return JSONResponse({"status": "error", "detail": str(exc)})
```

**New template `apps/ui/templates/settings.html.j2`**:

Standard form with HTMX `hx-post="/api/settings/test-connection"` on Test button that swaps a status div. Submit button POST /settings writes config.yaml. Displayed fields:

1. Provider dropdown (3 choices)
2. Summary model text input
3. Rerank model text input (labeled "for Phase 3c.2")
4. API key env var name (text)
5. API key status (readonly, auto-updated via HTMX on change: shows "set/unset")
6. Monthly budget USD (numeric, default 25)
7. Enabled checkbox (killswitch)
8. Budget status display (Xd spent / YY / color-coded bar)
9. Save button
10. Test connection button (HTMX)

**Budget widget `apps/ui/templates/partials/budget_widget.html.j2`** — included in topbar via `base.html.j2`:

```html
<div class="budget-widget {{ budget_color_class }}">
    <a href="/settings">
        <span class="budget-label">LLM budget</span>
        <span class="budget-value">
            ${{ '%.2f'|format(budget.spent_30d) }} / ${{ '%.0f'|format(budget.monthly_limit) }}
        </span>
    </a>
</div>
```

Color class computed by route: `green` if spent_30d < 0.8 × limit, `yellow` if 0.8-1.0, `red` if >1.0.

### D4 — Config schema extension

`~/.lvdcp/config.yaml` gets `llm:` section:

```yaml
version: 1
projects: [...]
llm:
  provider: openai
  summary_model: gpt-4o-mini
  rerank_model: gpt-4o-mini
  api_key_env_var: OPENAI_API_KEY
  monthly_budget_usd: 25.0
  prompt_version: v1
  enabled: false
```

Code changes in `libs/core/projects_config.py`:

```python
class LLMConfig(BaseModel):
    provider: str = "openai"
    summary_model: str = "gpt-4o-mini"
    rerank_model: str = "gpt-4o-mini"
    api_key_env_var: str = "OPENAI_API_KEY"
    monthly_budget_usd: float = 25.0
    prompt_version: str = "v1"
    enabled: bool = False


class DaemonConfig(BaseModel):
    version: int = Field(default=1)
    projects: list[ProjectEntry] = Field(default_factory=list)
    llm: LLMConfig = Field(default_factory=LLMConfig)  # NEW
```

**Backwards compatibility**: existing `config.yaml` без `llm:` section parses успешно благодаря `default_factory=LLMConfig`. Phase 3a/3b users не замечают изменений, пока не включат `enabled: true`.

`save_config` в `apps/agent/config.py` продолжает работать — pydantic сериализует `llm:` секцию автоматически.

### D5 — `ctx mcp doctor` extension + `ctx summarize` CLI

**Doctor check 8 — LLM provider configured**:

```python
def check_llm_provider(config: DaemonConfig) -> CheckResult:
    llm = config.llm
    if not llm.enabled:
        return CheckResult(
            name="LLM provider",
            status=CheckStatus.PASS,
            detail="disabled (llm.enabled: false)",
        )
    if not os.environ.get(llm.api_key_env_var) and llm.provider != "ollama":
        return CheckResult(
            name="LLM provider",
            status=CheckStatus.WARN,
            detail=f"{llm.api_key_env_var} env var not set",
            hint=f"export {llm.api_key_env_var}=...",
        )
    # Try test_connection
    try:
        client = create_client(llm)
        # sync wrapper — doctor runs sync context
        asyncio.run(asyncio.wait_for(client.test_connection(), timeout=5.0))
        return CheckResult(
            name="LLM provider",
            status=CheckStatus.PASS,
            detail=f"{llm.provider}/{llm.summary_model}",
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="LLM provider",
            status=CheckStatus.WARN,
            detail=str(exc),
            hint="check API key and network",
        )
```

**Doctor check 9 — LLM budget status**:

```python
def check_llm_budget(config: DaemonConfig) -> CheckResult:
    if not config.llm.enabled:
        return CheckResult(name="LLM budget", status=CheckStatus.PASS, detail="N/A (disabled)")
    with SummaryStore() as store:
        now = time.time()
        spent_30d = store.total_cost_since(since_ts=now - 30 * 86400)
    limit = config.llm.monthly_budget_usd
    pct = spent_30d / limit * 100 if limit > 0 else 0
    if pct >= 100:
        return CheckResult(
            name="LLM budget",
            status=CheckStatus.FAIL,
            detail=f"${spent_30d:.2f} / ${limit:.0f} ({pct:.0f}%)",
            hint="raise monthly_budget_usd in settings or disable LLM",
        )
    if pct >= 80:
        return CheckResult(
            name="LLM budget",
            status=CheckStatus.WARN,
            detail=f"${spent_30d:.2f} / ${limit:.0f} ({pct:.0f}%)",
            hint="approaching monthly limit",
        )
    return CheckResult(
        name="LLM budget",
        status=CheckStatus.PASS,
        detail=f"${spent_30d:.2f} / ${limit:.0f} ({pct:.0f}%)",
    )
```

Total doctor checks: **9** (was 7).

**New CLI command `ctx summarize <path>`** in `apps/cli/commands/summarize.py`:

```python
def summarize(
    path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Project root to summarize",
    ),
    model: str | None = typer.Option(None, "--model", help="Override summary_model"),
    concurrency: int = typer.Option(10, "--concurrency"),
) -> None:
    """Generate LLM summaries for every file in a scanned project.

    Results are persisted in ~/.lvdcp/summaries.db keyed by content_hash +
    prompt_version + model_name. Running twice = ~100% cache hits on
    unchanged files = zero cost.
    """
    config = load_config(resolve_config_path())
    if not config.llm.enabled:
        typer.echo("error: LLM is disabled. Enable via `ctx ui` settings or edit ~/.lvdcp/config.yaml", err=True)
        raise typer.Exit(code=1)

    effective_model = model or config.llm.summary_model
    try:
        client = create_client(config.llm)
    except LLMConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    with SummaryStore() as store:
        with Progress(...) as progress:  # rich progress bar
            task = progress.add_task(f"Summarizing {path.name}", total=None)
            def callback(current: int, total: int) -> None:
                progress.update(task, total=total, completed=current)
            result = asyncio.run(summarize_project(
                path.resolve(),
                client=client,
                model=effective_model,
                prompt_version=config.llm.prompt_version,
                store=store,
                concurrency=concurrency,
                progress_callback=callback,
            ))

    typer.echo(
        f"summarized {result.files_summarized} new files "
        f"({result.files_cached} cached), "
        f"cost ${result.total_cost_usd:.4f}, "
        f"{result.total_tokens_in}→{result.total_tokens_out} tokens, "
        f"in {result.elapsed_seconds:.2f}s"
    )
```

**Also** add `--with-summaries` flag to `ctx scan` в `apps/cli/commands/scan.py`, which invokes `summarize` inline after scan when set. Default OFF.

**Also** extend `lvdcp_status` MCP resource in `apps/mcp/tools.py` to include a `budget` field in the response:

```python
class BudgetInfo(BaseModel):
    spent_7d: float
    spent_30d: float
    monthly_limit: float
    status: str  # "ok" | "warning" | "exceeded" | "disabled"

class StatusResponse(BaseModel):
    workspace: WorkspaceStatus | None = None
    project: ProjectStatus | None = None
    budget: BudgetInfo | None = None  # NEW
```

Budget info always included (regardless of path argument) when LLM is enabled. Computed by `libs/status/budget.py::compute_budget_status(config)` that reads `summaries.db` and `config.llm.monthly_budget_usd`.

## 4. Архитектура и data flow

```
User                         ctx summarize <path>
 │                                    │
 │                                    ▼
 │                          libs/summaries/pipeline.py
 │                                    │
 │                          ┌─────────┼─────────┐
 │                          │         │         │
 │                          ▼         ▼         ▼
 │              ~/.lvdcp/   ProjectIndex   libs/llm/registry
 │              summaries   (iter files)         │
 │              .db                               ▼
 │              (cache)                     LLMClient
 │                          │                     │
 │                          │              ┌──────┼──────┐
 │                          │              ▼      ▼      ▼
 │                          │            OpenAI  Anthropic  Ollama
 │                          │              │      │      │
 │                          │              └──────┼──────┘
 │                          │                     │
 │                          │◀────────────────────┘
 │                          │  SummaryResult (text, UsageRecord with cost)
 │                          │
 │                          ▼ INSERT OR REPLACE
 │                     summaries.db
 │                          │
 │                          ▼
 │                    SummarizeResult stats
 │◀─────────────────────────┘
 │
 │   ctx ui                  ┌──────────────────────────────┐
 │                           │ Dashboard                    │
 ├─────────────────────────▶ │ topbar: $X.XX / $25 budget   │
 │                           │                              │
 │                           │ /settings: provider form     │
 │                           │  + test connection (HTMX)    │
 │                           │                              │
 │                           │ /project/<slug>: summaries   │
 │                           │  listed under file names     │
 │                           └──────────────────────────────┘
 │                                       │
 │                                       ▼
 │                             libs/status/aggregator.py
 │                             + libs/status/budget.py (new)
 │                             Reads from summaries.db
 │
 │   Claude MCP              ┌──────────────────────────────┐
 │                           │ lvdcp_status(path=None)      │
 ├─────────────────────────▶ │   → workspace + budget       │
 │                           │                              │
 │                           │ lvdcp_status(path=<P>)       │
 │                           │   → project + budget         │
 │                           └──────────────────────────────┘
```

## 5. New files / modules

```
libs/
  llm/
    __init__.py
    base.py                 # LLMClient Protocol + RerankCandidate/RerankResult
    models.py               # ModelSpec, UsageRecord, SummaryResult, ProviderConfig
    registry.py              # create_client factory
    openai_client.py
    anthropic_client.py
    ollama_client.py
    cost.py                 # MODELS table + calculate_cost
    errors.py               # LLMConfigError, LLMProviderError, BudgetExceededError
  summaries/
    __init__.py
    store.py                # SummaryStore + SummaryRow
    generator.py            # generate_file_summary
    prompts.py              # FILE_SUMMARY_PROMPT_V1
    pipeline.py             # summarize_project orchestrator + SummarizeResult
  status/
    budget.py               # BudgetStatus + compute_budget_status (new)
apps/
  cli/commands/
    summarize.py            # ctx summarize command
  ui/
    routes/
      settings.py           # /settings, POST /settings, /api/settings/test-connection
    templates/
      settings.html.j2      # settings form
      partials/
        budget_widget.html.j2
docs/adr/
  006-llm-provider-abstraction.md
scripts/
  phase-3c1-dogfood.sh
docs/dogfood/
  phase-3c1.md
tests/unit/llm/
  __init__.py
  test_cost.py
  test_registry.py
  test_openai_client.py
  test_anthropic_client.py
  test_ollama_client.py
tests/unit/summaries/
  __init__.py
  test_store.py
  test_generator.py
  test_pipeline.py
tests/unit/status/
  test_budget.py
tests/integration/
  test_ctx_summarize.py
  test_ui_settings.py
  test_lvdcp_status_budget.py
```

## 6. Modified files

- `libs/core/projects_config.py` — add `LLMConfig` model, `DaemonConfig.llm` field
- `libs/status/models.py` — add `BudgetInfo`, extend `StatusResponse` with optional `budget` field
- `libs/status/aggregator.py` — add budget field to `build_workspace_status()` / `build_project_status()` returns
- `libs/mcp_ops/doctor.py` — add `check_llm_provider` + `check_llm_budget`, total 9 checks
- `apps/mcp/tools.py` — `StatusResponse` gains optional `budget` field
- `apps/mcp/server.py` — no changes (tool signature compatible)
- `apps/cli/main.py` — wire `ctx summarize` command
- `apps/cli/commands/scan.py` — add `--with-summaries` flag
- `apps/ui/main.py` — register settings router
- `apps/ui/routes/index.py` — inject budget data into template context
- `apps/ui/routes/project.py` — same
- `apps/ui/templates/base.html.j2` — include budget_widget in topbar
- `apps/ui/static/css/base.css` — add `.budget-widget`, `.green/.yellow/.red` modifiers, `.settings-form`, HTMX status classes
- `pyproject.toml` — add `openai>=1.50`, `anthropic>=0.40`, `tiktoken>=0.7`; bump version `0.3.1` → `0.3.2`
- `README.md` — document `ctx summarize` + `/settings` page

## 7. Files NOT touched (safety zone)

- `libs/retrieval/*` — retrieval pipeline untouched, **eval MUST remain identical**
- `libs/graph/*`, `libs/parsers/*` — data layer untouched
- `apps/agent/daemon.py` — daemon remains summaries-unaware (no auto-summarize)
- `apps/agent/handler.py` — debounce logic untouched
- `libs/scanning/scanner.py` — scanner остаётся pure function (summaries orchestration — отдельный path)
- `libs/trace_store` / `libs/scan_history` — Phase 3b data stores untouched
- `libs/claude_usage/*` — Claude Code usage tracking untouched, независимо от LLM API cost tracking

## 8. Testing strategy

- **Unit**: все `libs/llm/*` с mocked HTTP:
  - `openai_client` → mock `AsyncOpenAI` via `unittest.mock.patch`, provide fake response with usage fields
  - `anthropic_client` → same pattern via `anthropic.AsyncAnthropic`
  - `ollama_client` → mock `httpx.AsyncClient.post` with deterministic JSON
  - `cost.py` → table-driven tests for each model × input/output combinations
  - `registry.py` → monkeypatch env vars, verify correct client type created, verify missing key raises `LLMConfigError`
- **`libs/summaries/store.py`** — tmp_path sqlite, roundtrip, cache key uniqueness (different model_name = different row), `total_cost_since` aggregation
- **`libs/summaries/pipeline.py`** — fake `LLMClient` that returns canned responses, mock ProjectIndex with 3 files, verify first run calls LLM 3 times, second run calls 0 times, errors on one file don't block others
- **`libs/status/budget.py`** — mock summaries.db, assert 7d/30d sums, color logic
- **Integration `test_ctx_summarize.py`** — monkeypatch env var pointing at local test server (tiny FastAPI returning deterministic JSON matching OpenAI format), subprocess `ctx summarize <tmp>`, verify exit 0, stdout contains expected stats, summaries.db populated
- **Integration `test_ui_settings.py`** — httpx ASGI client, GET /settings renders form, POST /settings writes config, /api/settings/test-connection with mocked client returns status
- **Integration `test_lvdcp_status_budget.py`** — extend existing handshake test to verify `budget` field in StatusResponse when llm.enabled
- **Marker `requires_real_llm_api`** — new optional integration test that hits real OpenAI API (skipped by default, gated behind env `LVDCP_RUN_LLM_API_TESTS=1`). Used manually before tagging.

## 9. Exit criteria

Phase 3c.1 закрывается при ВСЕХ выполненных:

1. `libs/llm/` supports 3 providers, each passing unit tests with mocks
2. `libs/summaries/` generates summaries with persistent cache; повторный `ctx summarize` = 100% cache hits, zero cost
3. `~/.lvdcp/config.yaml` gains `llm:` section with default `enabled: false` (backwards compat)
4. `ctx summarize <path>` работает on LV_DCP with OpenAI default: generates ≥215 summaries, total cost ≤$0.10, reports stats
5. `ctx mcp doctor` shows 9 checks including LLM provider + budget
6. Dashboard `/settings` renders, POST saves config, test-connection works via HTMX
7. Dashboard topbar shows budget widget with color-coded status
8. `lvdcp_status` MCP resource returns `budget` field when `llm.enabled`
9. `make lint typecheck test` clean; new test count target ≥310 (was 278 at Phase 3b close, adding ~32 new)
10. **Eval harness: identical to Phase 3b close** (0.891 / 0.620 / 0.833 / 0.819) — retrieval untouched, zero regression
11. Dogfood: run `ctx summarize` on LV_DCP + TG_Proxy_enaibler_bot + TG_RUSCOFFEE_ADMIN_BOT, capture cost + latency + 5 sample summaries in `docs/dogfood/phase-3c1.md`
12. `pyproject.toml` version bumped `0.3.1` → `0.3.2`
13. README.md updated with `ctx summarize` + `/settings` usage
14. Upgrade smoke test from `phase-3b-complete`: `git pull && uv sync --all-extras && ctx mcp doctor` → WARN on version mismatch → `ctx mcp install` → clean → `ctx ui` → settings page accessible
15. Git tag `phase-3c1-complete`

## 10. Non-goals (3c.1 explicitly does NOT do)

- Embeddings / vector search — Phase 3c.2
- Rerank stage implementation — Phase 3c.2 (only interface stub in 3c.1)
- New retrieval quality metrics (recall@5 ≥ 0.92, impact_recall@5 ≥ 0.85) — Phase 3c.2
- Per-query cost tracking in `traces.db` — Phase 3c.2
- Symbol-level summaries — Phase 3c.2 (only file-level in 3c.1)
- Module-level summaries — never, not worth complexity
- Summary retention / purging — never, cache key invalidates automatically
- Auto-summarize on scan (daemon-driven) — never, explicit opt-in only
- Real-time cost alerts / push notifications — Phase 5+
- Hard-stop budget enforcement (kill API calls) — soft warning only in 3c.1; hard stop maybe Phase 5+
- Multi-project parallel summarization — one project at a time, default concurrency 10 within a project
- Custom prompt editing via UI — only prompt_version selector; prompts live in code (`libs/summaries/prompts.py`)

## 11. Risks

- **R1 — Prompt engineering quality.** Bad summaries = useless feature. Mitigation: start with v1 prompt (2-3 sentences, terse), manually review output on 20 LV_DCP files before committing v1, iterate if needed. Prompt version is bumpable (v1 → v2) invalidating cache per model.
- **R2 — OpenAI API key setup friction.** New user must create account, generate key, set env var. Mitigation: `ctx mcp doctor` detects missing key and prints exact `export` command. `/settings` UI shows clear "unset" status. Ollama remains as zero-setup alternative.
- **R3 — Cost runaway in dogfood.** Cache logic bug → every scan misses cache → monthly bill jumps unexpectedly. Mitigation: hard killswitch `llm.enabled: false` default. `ctx mcp doctor` check fails at 100% budget. Manual dogfood starts with small project (10 files) before LV_DCP.
- **R4 — Latency.** 215 files × ~400ms OpenAI latency = ~85s cold scan if sequential. User perceives hung process. Mitigation: `rich` progress bar, `asyncio.gather` with `Semaphore(10)` concurrency, target cold scan ≤20 seconds for LV_DCP.
- **R5 — API rate limiting.** OpenAI tier-1 has RPM limits. 215 files / 60 RPM = 3.5 min sequential. Mitigation: exponential backoff retry, configurable concurrency, document tier-1 expectation в README.
- **R6 — Ollama integration edge cases.** Tests mock Ollama but real integration may fail (wrong model name, response format differences across Ollama versions). Mitigation: `requires_real_llm_api` integration test hits real local Ollama before tagging.
- **R7 — pydantic v2 migration edge cases.** New DTOs use pydantic v2 patterns (model_dump, model_validate). Existing Phase 3a/3b DTOs already on pydantic v2. No migration needed.
- **R8 — Config.yaml schema backwards compat.** Existing users' `config.yaml` без `llm:` section must load без errors. Mitigation: `LLMConfig` has all-defaults constructor + `Field(default_factory=LLMConfig)`. Unit test: load Phase 3b-era config.yaml (no llm section), verify it parses and defaults apply.

## 12. Agents (Phase 3c.1 execution)

- **fastapi-architect** — `/settings` route + HTMX test-connection endpoint + template
- **db-expert** — `summaries.db` schema + cache lookup performance + SummaryStore
- **system-analyst** — impact analysis перед `LLMConfig` schema extension (affects all 3a/3b consumers of config.yaml)
- **code-reviewer** — gate between `libs/llm` infrastructure landing и `libs/summaries` pipeline
- **test-runner** — new llm + summaries + status unit tests + integration tests + `requires_real_llm_api` manual gate

## 13. Dependencies on Phase 3c.2

Phase 3c.2 will:
- Add `rerank()` implementation to all 3 LLMClients (protocol already defines the method in 3c.1)
- Embed cached summaries from `summaries.db` into sqlite-vec vector store
- Add vector stage to `libs/retrieval/pipeline.py`
- Extend `/settings` page with vector model + rerank model (fields already present in 3c.1, just become functional)
- Extend cost tracking: per-query cost in `traces.db` (new columns)
- Extend eval harness: enforce `recall@5 files ≥ 0.92`, `impact_recall@5 ≥ 0.85`
- Add dashboard sparkline for LLM cost/day

Phase 3c.2 **will NOT** modify 3c.1 artifacts beyond additive changes — all `libs/llm/*`, `libs/summaries/*`, `libs/status/budget.py` stay stable.

## 14. Budget reality check

Actual OpenAI pricing via GPT-4o-mini (2026-04):

- Per-file summary: ~1250 tokens input (file content + prompt), ~200 tokens output
- Per-file cost: `1250 × $0.15/M + 200 × $0.60/M = $0.000188 + $0.000120 = $0.000308`
- LV_DCP (215 files) cold scan: `215 × $0.000308 = $0.066`
- 500-файловый canary: `500 × $0.000308 = $0.154`
- Monthly dogfood (~1 full re-summarize per month + incremental ~20 file changes/day × 30 = 600 new): `$0.066 + 600 × $0.000308 = $0.25`
- **Monthly total well under $25 budget.** Real pressure will come from Phase 3c.2 rerank (~$1.40/month for 60 q/day).

ADR-001 ≤$0.50 canary is achievable with ×3 safety margin. No ADR update needed.

## 15. Versioning scheme

- `pyproject.toml` bump `0.3.1` → **`0.3.2`**
- Phase 3c.1 corresponds to 0.3.2
- Phase 3c.2 will be 0.3.3

## 16. Approval log

- 2026-04-11 — brainstorm session with Vladimir Lukin. Design points closed:
  - Scope variant A (full 3c targets, not measurement-first): approved
  - Provider D pluggable with OpenAI default: approved
  - Granularity hybrid C (file summaries + symbol signatures split across 3c.1/3c.2): approved
  - Rerank listwise + conditional + summary fallback (for 3c.2): approved
  - Decomposition B (3c.1 infrastructure first, 3c.2 retrieval improvements): approved
  - Full Phase 3c.1 design preview (this spec): approved
