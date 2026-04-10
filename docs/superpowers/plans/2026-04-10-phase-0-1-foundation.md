# Phase 0 + Phase 1: Foundation & Deterministic Local Slice — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Доставить (a) работающий retrieval evaluation harness и (b) полностью локальный CLI `ctx`, который сканирует Python-проекты без LLM, строит `.context/*.md` артефакты и проходит пороги eval harness — с LV_DCP-самим-собой в качестве канареечного репо.

**Architecture:** Modular monolith. Единственное app в этих фазах — `apps/cli` (Typer). Вся логика в `libs/*` (core / parsers / retrieval / graph / context_pack / storage). Никакого backend, никакого Postgres, никакого Qdrant, никакого LLM. Детерминированный retrieval через symbol exact match + SQLite FTS5. Граф-v0 только для imports / defines / same_file_calls. Edit pack и cross-file call graph — Phase 4+.

**Tech stack:** Python 3.12 strict, uv, ruff, mypy strict, pytest + pytest-asyncio, pydantic v2, Typer, structlog, tree-sitter + tree-sitter-python, стандартный Python AST (cross-validation), stdlib sqlite3 с FTS5, PyYAML, tomllib (stdlib), markdown-it-py.

**Exit criteria (Phase 0):**
- [ ] `make lint typecheck test eval` зелёный
- [ ] Eval harness scaffold существует, thresholds.yaml активная фаза = 0, все метрики = 0.0, harness **проходит**
- [ ] `libs/core` доменные типы с полным type coverage
- [ ] Первый commit после Phase 0

**Exit criteria (Phase 1):**
- [ ] `ctx scan <path>` работает на fixture repo и на самом LV_DCP
- [ ] `ctx pack <path> "<query>"` возвращает осмысленный markdown context pack
- [ ] `ctx inspect <path>` показывает stats (files, symbols, relations)
- [ ] Eval harness при phase=1: recall@5 ≥ 0.70 (files), precision@3 ≥ 0.55, recall@5 ≥ 0.60 (symbols)
- [ ] `ctx scan` LV_DCP ≤ 20s (будет ≈300–500 файлов к концу Phase 1)
- [ ] `.context/project.md` и `.context/symbol_index.md` созданы в LV_DCP самого себя — содержание осмысленно
- [ ] Dogfood report (краткий markdown) зафиксирован в `docs/dogfood/phase-1.md`

**Phase 0 и Phase 1 — это два review checkpoint'а.** После Phase 0 мы **останавливаемся**, прогоняем `make lint typecheck test eval`, и только потом приступаем к Phase 1.

---

## File Structure

Будут созданы (по ходу plan'а):

```
libs/
  core/
    __init__.py
    entities.py           # Project, File, Symbol, Relation, Summary, ContextPack (pydantic)
    hashing.py            # content_hash, prompt_hash
    paths.py              # normalize_path, is_ignored
  parsers/
    __init__.py
    base.py               # FileParser Protocol, ParseResult dataclass
    registry.py           # language detection + parser selection
    text_parsers.py       # markdown, yaml, json, toml (stdlib-heavy)
    python.py             # tree-sitter + AST cross-validation
  graph/
    __init__.py
    edges.py              # Edge types, RelationType enum
    builder.py            # build_graph(parse_results) → Graph
    traversal.py          # neighbors(), expand(seed, depth)
  retrieval/
    __init__.py
    index.py              # SymbolIndex, FileIndex
    fts.py                # SQLite FTS5 wrapper
    ranking.py            # combine(scores) → ordered list
    pipeline.py           # retrieve(query, scope) → RetrievalResult
  context_pack/
    __init__.py
    builder.py            # assemble_pack(results, mode) → ContextPack
    navigate_mode.py
    edit_mode.py
    rendering.py          # ContextPack → markdown
  storage/
    __init__.py
    sqlite_cache.py       # schema, migrate, put/get FileState rows
  dotcontext/
    __init__.py
    writer.py             # write_project_md, write_symbol_index_md

apps/
  cli/
    __init__.py
    __main__.py           # python -m apps.cli entry
    main.py               # Typer app assembly
    commands/
      __init__.py
      scan.py
      pack.py
      inspect.py

tests/
  eval/
    __init__.py
    fixtures/
      sample_repo/         # ~30 файлов, будет создан целиком в Phase 0
    queries.yaml
    thresholds.yaml
    metrics.py             # recall_at_k, precision_at_k, mrr
    run_eval.py
    test_eval_harness.py   # применяет пороги
  unit/
    core/
      test_hashing.py
      test_entities.py
      test_paths.py
    parsers/
      test_text_parsers.py
      test_python_parser.py
    graph/
      test_builder.py
      test_traversal.py
    retrieval/
      test_fts.py
      test_index.py
      test_pipeline.py
    context_pack/
      test_builder.py
      test_rendering.py
    storage/
      test_sqlite_cache.py
    dotcontext/
      test_writer.py
  integration/
    test_cli_scan.py
    test_cli_pack.py
    test_dogfood.py        # запускает ctx scan на самом LV_DCP

docs/
  dogfood/
    phase-1.md             # пишется в последней задаче Phase 1
```

Границы ответственности:
- `libs/core` — доменные типы и примитивы, никаких зависимостей кроме stdlib + pydantic
- `libs/parsers` — только парсинг, возвращают иммутабельные `ParseResult`, не знают ничего про storage/graph/retrieval
- `libs/graph` — чисто in-memory; SQLite-персистентность живёт в `libs/storage`
- `libs/retrieval` — читает из `libs/storage` и `libs/graph`, не знает про CLI
- `libs/context_pack` — получает `RetrievalResult`, отдаёт отрендеренный markdown
- `libs/storage` — SQLite cache, единственный writer — в пределах этой фазы CLI
- `apps/cli` — тонкий Typer layer, вся логика в libs

---

# Phase 0 — Foundation & Measurement

## Task 0.1: Bootstrap Python project with uv, ruff, mypy, pytest

**Files:**
- Create: `libs/__init__.py` (empty namespace marker)
- Create: `apps/__init__.py` (empty namespace marker)
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Modify: `pyproject.toml` (already scaffolded — add runtime + dev deps)

- [ ] **Step 1: Add runtime + dev dependencies to pyproject.toml**

Modify `pyproject.toml`, replace `dependencies = []` and `[project.optional-dependencies]` sections with:

```toml
dependencies = [
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "typer>=0.12",
    "structlog>=24.1",
    "rich>=13.7",
    "pyyaml>=6.0",
    "markdown-it-py>=3.0",
    "tree-sitter>=0.23",
    "tree-sitter-python>=0.23",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "ruff>=0.6",
    "mypy>=1.11",
    "types-PyYAML>=6.0",
    "pre-commit>=3.7",
]

[project.scripts]
ctx = "apps.cli.main:app"
```

- [ ] **Step 2: Create empty namespace markers**

```bash
mkdir -p libs apps tests
touch libs/__init__.py apps/__init__.py tests/__init__.py
```

- [ ] **Step 3: Create tests/conftest.py with base fixtures**

```python
# tests/conftest.py
"""Shared pytest fixtures for LV_DCP unit and integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def project_root() -> Path:
    """Absolute path to the LV_DCP repo root."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def sample_repo_path(project_root: Path) -> Path:
    """Absolute path to tests/eval/fixtures/sample_repo."""
    return project_root / "tests" / "eval" / "fixtures" / "sample_repo"
```

- [ ] **Step 4: Run `uv sync` to install everything**

Run: `uv sync --all-extras`
Expected: creates `.venv/`, installs all deps, writes `uv.lock`.

- [ ] **Step 5: Verify tooling works on empty project**

Run:
```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy libs apps tests
uv run pytest
```
Expected: all four exit with code 0. `pytest` reports "no tests ran".

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock libs/__init__.py apps/__init__.py tests/__init__.py tests/conftest.py
git commit -m "chore(phase-0): bootstrap python project with uv/ruff/mypy/pytest"
```

---

## Task 0.2: libs/core/paths.py — path normalization and ignore rules

**Files:**
- Create: `libs/core/__init__.py`
- Create: `libs/core/paths.py`
- Create: `tests/unit/core/__init__.py`
- Create: `tests/unit/core/test_paths.py`

- [ ] **Step 1: Write failing test for normalize_path**

Create `tests/unit/core/test_paths.py`:

```python
from pathlib import Path

from libs.core.paths import is_ignored, normalize_path


def test_normalize_path_resolves_relative_to_root(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "c.py").touch()
    result = normalize_path(tmp_path / "a" / "b" / "c.py", root=tmp_path)
    assert result == "a/b/c.py"


def test_normalize_path_rejects_path_outside_root(tmp_path: Path) -> None:
    import pytest
    with pytest.raises(ValueError, match="outside root"):
        normalize_path(Path("/tmp/elsewhere.py"), root=tmp_path)


def test_is_ignored_matches_default_patterns() -> None:
    assert is_ignored("node_modules/foo.js")
    assert is_ignored(".venv/lib/python.py")
    assert is_ignored("__pycache__/x.pyc")
    assert is_ignored(".git/HEAD")


def test_is_ignored_allows_source_files() -> None:
    assert not is_ignored("libs/core/paths.py")
    assert not is_ignored("docs/constitution.md")
    assert not is_ignored("apps/cli/main.py")
```

- [ ] **Step 2: Run test — expect ImportError**

Run: `uv run pytest tests/unit/core/test_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'libs.core'`.

- [ ] **Step 3: Implement libs/core/paths.py**

Create `libs/core/__init__.py`:
```python
"""Core domain primitives for LV_DCP. No deps beyond stdlib + pydantic."""
```

Create `libs/core/paths.py`:
```python
"""Path normalization and ignore rules.

Pure, deterministic, no I/O beyond Path resolution.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_IGNORE_PREFIXES: tuple[str, ...] = (
    ".git/",
    ".venv/",
    "venv/",
    "node_modules/",
    "__pycache__/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".pytest_cache/",
    "dist/",
    "build/",
    ".next/",
    ".cache/",
    "coverage/",
)

DEFAULT_IGNORE_SUFFIXES: tuple[str, ...] = (
    ".pyc",
    ".pyo",
    ".so",
    ".dylib",
    ".dll",
    ".log",
    ".DS_Store",
)


def normalize_path(absolute: Path, *, root: Path) -> str:
    """Return a POSIX relative path from ``root`` to ``absolute``.

    Raises ``ValueError`` if ``absolute`` is not inside ``root``.
    """
    absolute = absolute.resolve()
    root = root.resolve()
    try:
        rel = absolute.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path {absolute} is outside root {root}") from exc
    return rel.as_posix()


def is_ignored(relative_posix: str) -> bool:
    """Return True if a path should be excluded from scanning."""
    for prefix in DEFAULT_IGNORE_PREFIXES:
        if relative_posix.startswith(prefix):
            return True
        if f"/{prefix}" in relative_posix:
            return True
    for suffix in DEFAULT_IGNORE_SUFFIXES:
        if relative_posix.endswith(suffix):
            return True
    return False
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/unit/core/test_paths.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run mypy strict**

Run: `uv run mypy libs apps tests`
Expected: 0 errors.

- [ ] **Step 6: Commit**

```bash
git add libs/core/__init__.py libs/core/paths.py tests/unit/core/__init__.py tests/unit/core/test_paths.py
git commit -m "feat(core): path normalization and default ignore rules"
```

---

## Task 0.3: libs/core/hashing.py — deterministic content hashing

**Files:**
- Create: `libs/core/hashing.py`
- Create: `tests/unit/core/test_hashing.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/core/test_hashing.py`:

```python
from libs.core.hashing import content_hash, prompt_hash


def test_content_hash_is_deterministic() -> None:
    data = b"hello world"
    assert content_hash(data) == content_hash(data)


def test_content_hash_changes_with_content() -> None:
    assert content_hash(b"abc") != content_hash(b"abd")


def test_content_hash_is_hex_sha256() -> None:
    h = content_hash(b"abc")
    assert len(h) == 64
    int(h, 16)  # validates hex


def test_content_hash_handles_empty() -> None:
    h = content_hash(b"")
    assert h == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_prompt_hash_combines_content_and_prompt_version() -> None:
    a = prompt_hash(content="hello", prompt_version="v1")
    b = prompt_hash(content="hello", prompt_version="v2")
    c = prompt_hash(content="hello", prompt_version="v1")
    assert a != b
    assert a == c
```

- [ ] **Step 2: Run test — expect fail**

Run: `uv run pytest tests/unit/core/test_hashing.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement hashing**

Create `libs/core/hashing.py`:
```python
"""Deterministic content hashes for cache keys and change detection."""

from __future__ import annotations

import hashlib


def content_hash(data: bytes) -> str:
    """Return a hex SHA-256 of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def prompt_hash(*, content: str, prompt_version: str) -> str:
    """Hash used as cache key for LLM-generated artifacts (Phase 2+).

    Combining content with a prompt version ensures cache invalidation
    when the prompt template itself changes, even if the input text does not.
    """
    payload = f"{prompt_version}\0{content}".encode()
    return hashlib.sha256(payload).hexdigest()
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/core/test_hashing.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add libs/core/hashing.py tests/unit/core/test_hashing.py
git commit -m "feat(core): deterministic content and prompt hashes"
```

---

## Task 0.4: libs/core/entities.py — domain types as Pydantic models

**Files:**
- Create: `libs/core/entities.py`
- Create: `tests/unit/core/test_entities.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/core/test_entities.py`:

```python
from libs.core.entities import (
    ContextPack,
    File,
    PackMode,
    Project,
    RelationType,
    Summary,
    Symbol,
    SymbolType,
)


def test_file_is_immutable() -> None:
    f = File(
        path="app/main.py",
        content_hash="a" * 64,
        size_bytes=123,
        language="python",
        role="source",
    )
    import pytest
    with pytest.raises(Exception):
        f.path = "other.py"  # type: ignore[misc]


def test_symbol_fq_name_uses_file_and_name() -> None:
    s = Symbol(
        name="User",
        fq_name="app.models.user.User",
        symbol_type=SymbolType.CLASS,
        file_path="app/models/user.py",
        start_line=10,
        end_line=42,
    )
    assert s.fq_name.endswith("User")


def test_project_requires_local_path() -> None:
    p = Project(name="lv-dcp", slug="lv-dcp", local_path="/abs/path")
    assert p.slug == "lv-dcp"


def test_context_pack_size_constraint() -> None:
    pack = ContextPack(
        project_slug="lv-dcp",
        query="where is User",
        mode=PackMode.NAVIGATE,
        assembled_markdown="# small\n",
        size_bytes=8,
    )
    assert pack.size_bytes == 8


def test_relation_type_enum_covers_phase_1() -> None:
    assert RelationType.IMPORTS
    assert RelationType.DEFINES
    assert RelationType.SAME_FILE_CALLS


def test_summary_has_confidence() -> None:
    s = Summary(
        entity_type="file",
        entity_ref="app/main.py",
        summary_type="file_summary",
        text="entry point",
        text_hash="a" * 64,
        model_name="deterministic",
        model_version="v0",
        confidence=1.0,
    )
    assert 0.0 <= s.confidence <= 1.0
```

- [ ] **Step 2: Run — expect fail**

Run: `uv run pytest tests/unit/core/test_entities.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement entities**

Create `libs/core/entities.py`:
```python
"""Domain entities for LV_DCP.

All models are frozen (immutable) — parse/retrieve results are values, not state.
Mutation lives exclusively in libs/storage.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class SymbolType(str, Enum):
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    VARIABLE = "variable"
    CONSTANT = "constant"
    IMPORT = "import"
    MODULE = "module"


class RelationType(str, Enum):
    # Phase 1 — deterministic only
    IMPORTS = "imports"
    DEFINES = "defines"
    SAME_FILE_CALLS = "same_file_calls"
    # Phase 2+ — reserved for later
    REFERENCES = "references"
    USES_ENV = "uses_env"


class PackMode(str, Enum):
    NAVIGATE = "navigate"
    EDIT = "edit"


class Immutable(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class File(Immutable):
    path: str                    # POSIX relative to project root
    content_hash: str            # hex sha256
    size_bytes: int
    language: str                # "python" | "markdown" | "yaml" | "json" | "toml" | "text"
    role: str                    # "source" | "test" | "docs" | "config" | "generated" | "unknown"
    is_generated: bool = False
    is_binary: bool = False


class Symbol(Immutable):
    name: str
    fq_name: str                 # dotted fully qualified name
    symbol_type: SymbolType
    file_path: str
    start_line: int
    end_line: int
    parent_fq_name: str | None = None
    signature: str | None = None
    docstring: str | None = None


class Relation(Immutable):
    src_type: str                # "file" | "symbol"
    src_ref: str                 # path or fq_name
    dst_type: str
    dst_ref: str
    relation_type: RelationType
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    provenance: str = "deterministic"


class Summary(Immutable):
    entity_type: str             # "file" | "symbol" | "module" | "project"
    entity_ref: str
    summary_type: str            # "file_summary" | "symbol_summary" | ...
    text: str
    text_hash: str
    model_name: str              # "deterministic" in Phase 1; LLM model in Phase 2
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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/core -v`
Expected: all 10 passed (4 paths + 5 hashing + 6 entities).

- [ ] **Step 5: mypy clean**

Run: `uv run mypy libs tests`
Expected: 0 errors.

- [ ] **Step 6: Commit**

```bash
git add libs/core/entities.py tests/unit/core/test_entities.py
git commit -m "feat(core): immutable domain entities (File, Symbol, Relation, Summary, Project, ContextPack)"
```

---

## Task 0.5: tests/eval/ scaffold — fixtures/sample_repo

**Files:**
- Create: `tests/eval/__init__.py`
- Create: `tests/eval/fixtures/sample_repo/` (≈30 files total, listed below)

This task creates the **fixture repo** — a hand-crafted mini project we use as the ground truth for retrieval. Quality of the fixture determines quality of the eval harness forever. Spend time here.

The fixture represents a small Python API service: one FastAPI-like app with auth, user model, and a worker. Contents are intentionally **verbose enough to have structure** and **small enough to re-read**.

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p tests/eval/fixtures/sample_repo/{app/{models,handlers,services,workers},tests,docs,config}
touch tests/eval/__init__.py
```

- [ ] **Step 2: Create sample_repo/README.md**

Create `tests/eval/fixtures/sample_repo/README.md`:
```markdown
# sample_repo — LV_DCP retrieval eval fixture

Small FastAPI-like project used as ground truth for the LV_DCP retrieval
evaluation harness. Do NOT modify this repo in the same PR that changes
retrieval code — see ADR-002.

Stack (simulated): Python 3.12, FastAPI, SQLAlchemy async, Redis.
```

- [ ] **Step 3: Create pyproject.toml for sample_repo**

Create `tests/eval/fixtures/sample_repo/pyproject.toml`:
```toml
[project]
name = "sample-api"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["fastapi", "sqlalchemy", "redis"]
```

- [ ] **Step 4: Create app/__init__.py and app/main.py**

Create `tests/eval/fixtures/sample_repo/app/__init__.py`:
```python
"""Sample API package."""
```

Create `tests/eval/fixtures/sample_repo/app/main.py`:
```python
"""Entrypoint — wires FastAPI app, routers, and lifespan."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.handlers import auth, profile
from app.services.db import close_db, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(lifespan=lifespan)
app.include_router(auth.router)
app.include_router(profile.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 5: Create app/models/user.py**

Create `tests/eval/fixtures/sample_repo/app/models/__init__.py`:
```python
"""ORM models."""
```

Create `tests/eval/fixtures/sample_repo/app/models/user.py`:
```python
"""User ORM model."""

from datetime import datetime

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    """Represents an authenticated human user."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    hashed_password: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    def is_locked(self) -> bool:
        return not self.is_active
```

- [ ] **Step 6: Create app/models/session.py**

Create `tests/eval/fixtures/sample_repo/app/models/session.py`:
```python
"""Session token model."""

from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey

from app.models.user import Base


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    access_token: Mapped[str] = mapped_column(unique=True)
    refresh_token: Mapped[str] = mapped_column(unique=True)
    expires_at: Mapped[datetime]
```

- [ ] **Step 7: Create app/handlers/__init__.py and auth.py**

Create `tests/eval/fixtures/sample_repo/app/handlers/__init__.py`:
```python
"""HTTP handlers."""
```

Create `tests/eval/fixtures/sample_repo/app/handlers/auth.py`:
```python
"""Authentication routes — login, logout, refresh token."""

from fastapi import APIRouter, Depends, HTTPException

from app.models.user import User
from app.services.auth import authenticate, issue_tokens, refresh_access_token
from app.services.db import get_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(email: str, password: str, db=Depends(get_session)) -> dict[str, str]:
    user = await authenticate(db, email, password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid credentials")
    access, refresh = await issue_tokens(db, user)
    return {"access_token": access, "refresh_token": refresh}


@router.post("/refresh")
async def refresh(refresh_token: str, db=Depends(get_session)) -> dict[str, str]:
    access = await refresh_access_token(db, refresh_token)
    return {"access_token": access}
```

- [ ] **Step 8: Create app/handlers/profile.py**

Create `tests/eval/fixtures/sample_repo/app/handlers/profile.py`:
```python
"""User profile routes."""

from fastapi import APIRouter, Depends

from app.models.user import User
from app.services.auth import current_user

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("")
async def me(user: User = Depends(current_user)) -> dict[str, str | bool]:
    return {"email": user.email, "is_active": user.is_active}
```

- [ ] **Step 9: Create app/services/__init__.py, auth.py, db.py**

Create `tests/eval/fixtures/sample_repo/app/services/__init__.py`:
```python
"""Business logic services."""
```

Create `tests/eval/fixtures/sample_repo/app/services/auth.py`:
```python
"""Authentication service — password check, token issuance, refresh flow."""

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.models.user import User

ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=30)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
    from sqlalchemy import select
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None or user.hashed_password != hash_password(password):
        return None
    return user


async def issue_tokens(db: AsyncSession, user: User) -> tuple[str, str]:
    access = secrets.token_urlsafe(32)
    refresh = secrets.token_urlsafe(48)
    session = Session(
        user_id=user.id,
        access_token=access,
        refresh_token=refresh,
        expires_at=datetime.utcnow() + ACCESS_TTL,
    )
    db.add(session)
    await db.commit()
    return access, refresh


async def refresh_access_token(db: AsyncSession, refresh_token: str) -> str:
    from sqlalchemy import select
    stmt = select(Session).where(Session.refresh_token == refresh_token)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session is None:
        raise ValueError("invalid refresh token")
    new_access = secrets.token_urlsafe(32)
    session.access_token = new_access
    session.expires_at = datetime.utcnow() + ACCESS_TTL
    await db.commit()
    return new_access


async def current_user(db: AsyncSession, access_token: str) -> User:
    from sqlalchemy import select
    stmt = select(Session).where(Session.access_token == access_token)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session is None or session.expires_at < datetime.utcnow():
        raise ValueError("expired or unknown token")
    user_stmt = select(User).where(User.id == session.user_id)
    return (await db.execute(user_stmt)).scalar_one()
```

Create `tests/eval/fixtures/sample_repo/app/services/db.py`:
```python
"""Database engine and session lifecycle."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_engine = None
_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db() -> None:
    global _engine, _factory
    _engine = create_async_engine("postgresql+asyncpg://localhost/sample")
    _factory = async_sessionmaker(_engine, expire_on_commit=False)


async def close_db() -> None:
    if _engine is not None:
        await _engine.dispose()


async def get_session() -> AsyncSession:
    assert _factory is not None, "init_db not called"
    async with _factory() as session:
        yield session
```

- [ ] **Step 10: Create app/workers/ — background job**

Create `tests/eval/fixtures/sample_repo/app/workers/__init__.py`:
```python
"""Background workers."""
```

Create `tests/eval/fixtures/sample_repo/app/workers/cleanup.py`:
```python
"""Scheduled cleanup of expired sessions."""

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session


async def cleanup_expired_sessions(db: AsyncSession) -> int:
    stmt = delete(Session).where(Session.expires_at < datetime.utcnow())
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount or 0
```

- [ ] **Step 11: Create tests/ in sample_repo**

Create `tests/eval/fixtures/sample_repo/tests/__init__.py`:
```python
```

Create `tests/eval/fixtures/sample_repo/tests/test_auth.py`:
```python
"""Tests for the authentication service."""

import pytest

from app.services.auth import hash_password


def test_hash_password_is_deterministic() -> None:
    assert hash_password("hunter2") == hash_password("hunter2")


def test_hash_password_changes_with_input() -> None:
    assert hash_password("a") != hash_password("b")
```

Create `tests/eval/fixtures/sample_repo/tests/test_cleanup.py`:
```python
"""Tests for the cleanup worker."""

from datetime import datetime, timedelta

# Placeholder — real integration test would use a DB fixture.
def test_cleanup_marker() -> None:
    assert datetime.utcnow() - timedelta(days=1) < datetime.utcnow()
```

- [ ] **Step 12: Create docs/ in sample_repo**

Create `tests/eval/fixtures/sample_repo/docs/architecture.md`:
```markdown
# Sample API architecture

- `app/handlers/` — FastAPI routers, thin glue
- `app/services/` — business logic (auth, db)
- `app/models/` — SQLAlchemy models
- `app/workers/` — background jobs (cleanup of expired sessions)

## Auth flow

1. `POST /auth/login` → `authenticate` → `issue_tokens` → returns access+refresh
2. `POST /auth/refresh` → `refresh_access_token` → returns new access
3. `current_user` resolves access tokens via the `sessions` table

The cleanup worker periodically deletes expired Session rows.
```

Create `tests/eval/fixtures/sample_repo/docs/deployment.md`:
```markdown
# Deployment notes

Docker compose brings up Postgres, Redis, and the API. The API container
is built from `pyproject.toml` and runs `uvicorn app.main:app`.
```

- [ ] **Step 13: Create config/ in sample_repo**

Create `tests/eval/fixtures/sample_repo/config/settings.yaml`:
```yaml
database:
  url: postgresql+asyncpg://localhost/sample
  pool_size: 10

auth:
  access_ttl_minutes: 15
  refresh_ttl_days: 30

worker:
  cleanup_interval_seconds: 3600
```

Create `tests/eval/fixtures/sample_repo/config/logging.json`:
```json
{
  "version": 1,
  "disable_existing_loggers": false,
  "handlers": {
    "console": {"class": "logging.StreamHandler"}
  },
  "root": {"level": "INFO", "handlers": ["console"]}
}
```

- [ ] **Step 14: Commit the fixture repo**

```bash
git add tests/eval/__init__.py tests/eval/fixtures/
git commit -m "test(eval): fixture sample_repo for retrieval evaluation harness"
```

---

## Task 0.6: tests/eval/queries.yaml — initial 20 retrieval queries

**Files:**
- Create: `tests/eval/queries.yaml`
- Create: `tests/eval/thresholds.yaml`

- [ ] **Step 1: Create queries.yaml**

Create `tests/eval/queries.yaml`:
```yaml
version: 1
queries:
  - id: q01-user-model
    text: "where is the User model defined"
    mode: navigate
    expected:
      files: [app/models/user.py]
      symbols: [app.models.user.User]

  - id: q02-session-model
    text: "where is session token stored"
    mode: navigate
    expected:
      files: [app/models/session.py]
      symbols: [app.models.session.Session]

  - id: q03-login-route
    text: "login endpoint"
    mode: navigate
    expected:
      files: [app/handlers/auth.py]
      symbols: [app.handlers.auth.login]

  - id: q04-refresh-flow
    text: "refresh token flow"
    mode: navigate
    expected:
      files:
        - app/handlers/auth.py
        - app/services/auth.py
      symbols:
        - app.services.auth.refresh_access_token
        - app.handlers.auth.refresh

  - id: q05-authenticate
    text: "how are passwords verified"
    mode: navigate
    expected:
      files: [app/services/auth.py]
      symbols:
        - app.services.auth.authenticate
        - app.services.auth.hash_password

  - id: q06-current-user
    text: "which function resolves the access token to a user"
    mode: navigate
    expected:
      files: [app/services/auth.py]
      symbols: [app.services.auth.current_user]

  - id: q07-profile-route
    text: "profile endpoint"
    mode: navigate
    expected:
      files: [app/handlers/profile.py]
      symbols: [app.handlers.profile.me]

  - id: q08-db-lifecycle
    text: "database engine setup and shutdown"
    mode: navigate
    expected:
      files: [app/services/db.py]
      symbols:
        - app.services.db.init_db
        - app.services.db.close_db

  - id: q09-session-factory
    text: "session factory"
    mode: navigate
    expected:
      files: [app/services/db.py]
      symbols: [app.services.db.get_session]

  - id: q10-cleanup-worker
    text: "background job that deletes expired sessions"
    mode: navigate
    expected:
      files: [app/workers/cleanup.py]
      symbols: [app.workers.cleanup.cleanup_expired_sessions]

  - id: q11-app-entrypoint
    text: "FastAPI app entrypoint"
    mode: navigate
    expected:
      files: [app/main.py]
      symbols: [app.main.app, app.main.lifespan]

  - id: q12-health-route
    text: "health check route"
    mode: navigate
    expected:
      files: [app/main.py]
      symbols: [app.main.health]

  - id: q13-auth-tests
    text: "tests for authentication"
    mode: navigate
    expected:
      files: [tests/test_auth.py]

  - id: q14-architecture-doc
    text: "where is the architecture described"
    mode: navigate
    expected:
      files: [docs/architecture.md]

  - id: q15-db-config
    text: "database connection string configuration"
    mode: navigate
    expected:
      files: [config/settings.yaml]

  - id: q16-access-ttl
    text: "access token lifetime"
    mode: navigate
    expected:
      files:
        - app/services/auth.py
        - config/settings.yaml
      symbols: [app.services.auth.ACCESS_TTL]

  - id: q17-user-is-locked
    text: "how to check if a user account is locked"
    mode: navigate
    expected:
      files: [app/models/user.py]
      symbols: [app.models.user.User.is_locked]

  - id: q18-password-hashing
    text: "password hashing implementation"
    mode: navigate
    expected:
      files: [app/services/auth.py]
      symbols: [app.services.auth.hash_password]

  - id: q19-edit-login
    text: "I want to change how login validates credentials"
    mode: edit
    expected:
      files:
        - app/handlers/auth.py
        - app/services/auth.py
        - tests/test_auth.py
      symbols:
        - app.handlers.auth.login
        - app.services.auth.authenticate

  - id: q20-edit-cleanup-schedule
    text: "change the cleanup worker interval"
    mode: edit
    expected:
      files:
        - app/workers/cleanup.py
        - config/settings.yaml
      symbols: [app.workers.cleanup.cleanup_expired_sessions]
```

- [ ] **Step 2: Create thresholds.yaml**

Create `tests/eval/thresholds.yaml`:
```yaml
# Active retrieval quality thresholds. Changed only by explicit PR, never bundled
# with retrieval pipeline changes (see ADR-002).
active_phase: 0

phases:
  "0":
    description: "Foundation — stub retrieval, metrics = 0 expected"
    recall_at_5_files: 0.0
    precision_at_3_files: 0.0
    recall_at_5_symbols: 0.0

  "1":
    description: "Deterministic local slice"
    recall_at_5_files: 0.70
    precision_at_3_files: 0.55
    recall_at_5_symbols: 0.60

  "2":
    description: "LLM enrichment + semantic retrieval"
    recall_at_5_files: 0.85
    precision_at_3_files: 0.70
    recall_at_5_symbols: 0.75
```

- [ ] **Step 3: Commit**

```bash
git add tests/eval/queries.yaml tests/eval/thresholds.yaml
git commit -m "test(eval): 20 ground-truth queries and phase thresholds"
```

---

## Task 0.7: tests/eval/metrics.py — recall@k, precision@k, MRR

**Files:**
- Create: `tests/eval/metrics.py`
- Create: `tests/unit/eval/__init__.py`
- Create: `tests/unit/eval/test_metrics.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/eval/__init__.py`:
```python
```

Create `tests/unit/eval/test_metrics.py`:
```python
from tests.eval.metrics import mean_reciprocal_rank, precision_at_k, recall_at_k


def test_recall_at_k_all_hit() -> None:
    retrieved = ["a.py", "b.py", "c.py"]
    expected = ["a.py", "b.py"]
    assert recall_at_k(retrieved, expected, k=3) == 1.0


def test_recall_at_k_partial() -> None:
    retrieved = ["a.py", "x.py", "y.py"]
    expected = ["a.py", "b.py"]
    assert recall_at_k(retrieved, expected, k=3) == 0.5


def test_recall_at_k_none() -> None:
    assert recall_at_k(["x.py"], ["a.py"], k=5) == 0.0


def test_recall_at_k_empty_expected_is_one() -> None:
    # Empty expected set means no ground truth to miss
    assert recall_at_k(["a.py"], [], k=3) == 1.0


def test_precision_at_k_half() -> None:
    retrieved = ["a.py", "x.py", "b.py", "y.py"]
    expected = ["a.py", "b.py"]
    assert precision_at_k(retrieved, expected, k=4) == 0.5


def test_precision_at_k_respects_k() -> None:
    retrieved = ["a.py", "b.py", "c.py"]
    expected = ["a.py", "b.py"]
    # only top-2
    assert precision_at_k(retrieved, expected, k=2) == 1.0


def test_mrr_first_rank() -> None:
    assert mean_reciprocal_rank([["a", "b", "c"]], [["a"]]) == 1.0


def test_mrr_second_rank() -> None:
    assert mean_reciprocal_rank([["x", "a", "b"]], [["a"]]) == 0.5


def test_mrr_no_hit() -> None:
    assert mean_reciprocal_rank([["x", "y"]], [["a"]]) == 0.0


def test_mrr_averages_over_queries() -> None:
    # query 1: hit at rank 1 → 1.0
    # query 2: hit at rank 2 → 0.5
    # avg = 0.75
    result = mean_reciprocal_rank(
        retrieved_lists=[["a"], ["x", "b"]],
        expected_lists=[["a"], ["b"]],
    )
    assert result == 0.75
```

- [ ] **Step 2: Run — expect fail**

Run: `uv run pytest tests/unit/eval/test_metrics.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement metrics.py**

Create `tests/eval/metrics.py`:
```python
"""Retrieval evaluation metrics. Pure functions, no I/O.

Contract:
- A "retrieved" list is ordered by retrieval rank, most relevant first.
- An "expected" list is unordered ground truth.
- Both contain opaque string keys (file paths or fq_names) — the caller
  decides what domain they represent.
"""

from __future__ import annotations

from collections.abc import Sequence


def recall_at_k(retrieved: Sequence[str], expected: Sequence[str], *, k: int) -> float:
    """Fraction of expected items that appear in the top-k of retrieved.

    If expected is empty, returns 1.0 (no ground truth can be missed).
    """
    if not expected:
        return 1.0
    top = set(retrieved[:k])
    hits = sum(1 for e in expected if e in top)
    return hits / len(expected)


def precision_at_k(retrieved: Sequence[str], expected: Sequence[str], *, k: int) -> float:
    """Fraction of the top-k retrieved items that are in the expected set.

    If k is 0 or retrieved is empty, returns 0.0.
    """
    if k <= 0:
        return 0.0
    top = list(retrieved[:k])
    if not top:
        return 0.0
    expected_set = set(expected)
    hits = sum(1 for r in top if r in expected_set)
    return hits / len(top)


def mean_reciprocal_rank(
    retrieved_lists: Sequence[Sequence[str]],
    expected_lists: Sequence[Sequence[str]],
) -> float:
    """Mean reciprocal rank of the first expected hit across queries.

    A query contributes 1/rank (1-indexed) for the first expected item found,
    or 0 if none found. The final MRR is the mean over all queries.
    """
    if len(retrieved_lists) != len(expected_lists):
        raise ValueError("retrieved and expected lists differ in length")
    if not retrieved_lists:
        return 0.0
    total = 0.0
    for retrieved, expected in zip(retrieved_lists, expected_lists, strict=True):
        expected_set = set(expected)
        reciprocal = 0.0
        for idx, item in enumerate(retrieved, start=1):
            if item in expected_set:
                reciprocal = 1.0 / idx
                break
        total += reciprocal
    return total / len(retrieved_lists)
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/unit/eval/test_metrics.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/eval/metrics.py tests/unit/eval/__init__.py tests/unit/eval/test_metrics.py
git commit -m "test(eval): recall/precision/MRR metrics with unit tests"
```

---

## Task 0.8: tests/eval/run_eval.py — runner that plugs into a retrieval function

**Files:**
- Create: `tests/eval/run_eval.py`

- [ ] **Step 1: Create run_eval.py**

Create `tests/eval/run_eval.py`:
```python
"""Eval harness runner.

Loads queries.yaml, invokes a retrieval callable against the fixture repo,
and returns aggregated metrics. No pytest dependency here — this is importable
from scripts and from the pytest wrapper in test_eval_harness.py.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tests.eval.metrics import mean_reciprocal_rank, precision_at_k, recall_at_k

EVAL_DIR = Path(__file__).resolve().parent
FIXTURE_REPO = EVAL_DIR / "fixtures" / "sample_repo"
QUERIES_YAML = EVAL_DIR / "queries.yaml"
THRESHOLDS_YAML = EVAL_DIR / "thresholds.yaml"


@dataclass(frozen=True)
class QueryResult:
    query_id: str
    mode: str
    retrieved_files: list[str]
    retrieved_symbols: list[str]
    expected_files: list[str]
    expected_symbols: list[str]


@dataclass(frozen=True)
class EvalReport:
    query_results: list[QueryResult]
    recall_at_5_files: float
    precision_at_3_files: float
    recall_at_5_symbols: float
    mrr_files: float


RetrievalFn = Callable[[str, str, Path], tuple[list[str], list[str]]]
# (query_text, mode, repo_path) -> (retrieved_files_ordered, retrieved_symbols_ordered)


def load_queries() -> list[dict[str, Any]]:
    data = yaml.safe_load(QUERIES_YAML.read_text(encoding="utf-8"))
    queries = data["queries"]
    assert isinstance(queries, list)
    return queries


def load_thresholds() -> dict[str, Any]:
    data = yaml.safe_load(THRESHOLDS_YAML.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def run_eval(retrieve: RetrievalFn, *, repo_path: Path = FIXTURE_REPO) -> EvalReport:
    queries = load_queries()
    results: list[QueryResult] = []
    for q in queries:
        retrieved_files, retrieved_symbols = retrieve(q["text"], q["mode"], repo_path)
        expected = q.get("expected", {}) or {}
        results.append(
            QueryResult(
                query_id=q["id"],
                mode=q["mode"],
                retrieved_files=list(retrieved_files),
                retrieved_symbols=list(retrieved_symbols),
                expected_files=list(expected.get("files", []) or []),
                expected_symbols=list(expected.get("symbols", []) or []),
            )
        )

    recall_5_files = _avg(
        recall_at_k(r.retrieved_files, r.expected_files, k=5) for r in results
    )
    precision_3_files = _avg(
        precision_at_k(r.retrieved_files, r.expected_files, k=3) for r in results
    )
    recall_5_symbols = _avg(
        recall_at_k(r.retrieved_symbols, r.expected_symbols, k=5) for r in results
    )
    mrr_f = mean_reciprocal_rank(
        [r.retrieved_files for r in results],
        [r.expected_files for r in results],
    )

    return EvalReport(
        query_results=results,
        recall_at_5_files=recall_5_files,
        precision_at_3_files=precision_3_files,
        recall_at_5_symbols=recall_5_symbols,
        mrr_files=mrr_f,
    )


def _avg(values: "Any") -> float:
    lst = list(values)
    if not lst:
        return 0.0
    return sum(lst) / len(lst)


def stub_retrieve(query: str, mode: str, repo_path: Path) -> tuple[list[str], list[str]]:
    """Phase 0 placeholder — returns nothing. Exists so the harness is runnable."""
    return [], []


if __name__ == "__main__":
    report = run_eval(stub_retrieve)
    print(f"recall@5 files   : {report.recall_at_5_files:.3f}")
    print(f"precision@3 files: {report.precision_at_3_files:.3f}")
    print(f"recall@5 symbols : {report.recall_at_5_symbols:.3f}")
    print(f"MRR (files)      : {report.mrr_files:.3f}")
```

- [ ] **Step 2: Run the module directly to smoke test**

Run: `uv run python -m tests.eval.run_eval`
Expected output: all four metrics = 0.000 (stub retrieval returns empty).

- [ ] **Step 3: Commit**

```bash
git add tests/eval/run_eval.py
git commit -m "test(eval): runner and stub retrieval"
```

---

## Task 0.9: tests/eval/test_eval_harness.py — pytest wrapper with threshold gating

**Files:**
- Create: `tests/eval/test_eval_harness.py`

- [ ] **Step 1: Create the threshold gating test**

Create `tests/eval/test_eval_harness.py`:
```python
"""Pytest wrapper around the eval harness.

Applies the active-phase thresholds from thresholds.yaml and fails if any
metric falls below its threshold. See ADR-002.
"""

from __future__ import annotations

import pytest

from tests.eval.run_eval import EvalReport, load_thresholds, run_eval, stub_retrieve

pytestmark = pytest.mark.eval


def _active_thresholds() -> dict[str, float]:
    data = load_thresholds()
    phase = str(data["active_phase"])
    thresholds = data["phases"][phase]
    return {
        "recall_at_5_files": float(thresholds["recall_at_5_files"]),
        "precision_at_3_files": float(thresholds["precision_at_3_files"]),
        "recall_at_5_symbols": float(thresholds["recall_at_5_symbols"]),
    }


def _current_retrieve():
    """Wire the retrieval function used by the eval harness.

    Phase 0 uses stub_retrieve. Phase 1+ will import the real pipeline.
    """
    return stub_retrieve


def test_eval_harness_meets_thresholds() -> None:
    thresholds = _active_thresholds()
    report: EvalReport = run_eval(_current_retrieve())

    failures: list[str] = []
    if report.recall_at_5_files < thresholds["recall_at_5_files"]:
        failures.append(
            f"recall@5 files = {report.recall_at_5_files:.3f} "
            f"< threshold {thresholds['recall_at_5_files']:.3f}"
        )
    if report.precision_at_3_files < thresholds["precision_at_3_files"]:
        failures.append(
            f"precision@3 files = {report.precision_at_3_files:.3f} "
            f"< threshold {thresholds['precision_at_3_files']:.3f}"
        )
    if report.recall_at_5_symbols < thresholds["recall_at_5_symbols"]:
        failures.append(
            f"recall@5 symbols = {report.recall_at_5_symbols:.3f} "
            f"< threshold {thresholds['recall_at_5_symbols']:.3f}"
        )

    if failures:
        msg = "Eval harness below thresholds:\n  - " + "\n  - ".join(failures)
        pytest.fail(msg)
```

- [ ] **Step 2: Run eval harness**

Run: `uv run pytest tests/eval/test_eval_harness.py -v -m eval`
Expected: PASS. Thresholds for phase 0 are all 0.0, stub returns 0.0, equal ≥ equal → passes.

- [ ] **Step 3: Run full test suite including eval**

Run: `make eval && make test`
Expected: both green.

- [ ] **Step 4: Commit**

```bash
git add tests/eval/test_eval_harness.py
git commit -m "test(eval): pytest wrapper enforcing active-phase thresholds"
```

---

## Phase 0 checkpoint

- [ ] **Verify Phase 0 exit criteria**

Run:
```bash
make lint
make typecheck
make test
make eval
```

All four must be green. Then STOP. Review the tree, review the ADRs, review the plan for Phase 1 against what actually shipped. Only after explicit human go/no-go continue to Phase 1.

- [ ] **Phase 0 milestone commit**

```bash
git tag phase-0-complete
git commit --allow-empty -m "chore(phase-0): foundation and eval harness complete"
```

---

# Phase 1 — Deterministic Local Slice

> **Begin only after Phase 0 checkpoint passed.**

## Task 1.1: libs/parsers/base.py — FileParser protocol and ParseResult

**Files:**
- Create: `libs/parsers/__init__.py`
- Create: `libs/parsers/base.py`
- Create: `tests/unit/parsers/__init__.py`
- Create: `tests/unit/parsers/test_base.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/parsers/__init__.py`:
```python
```

Create `tests/unit/parsers/test_base.py`:
```python
from libs.parsers.base import ParseResult


def test_parse_result_is_immutable() -> None:
    r = ParseResult(
        file_path="a.py",
        symbols=(),
        relations=(),
        language="python",
        role="source",
    )
    import pytest
    with pytest.raises(Exception):
        r.language = "rust"  # type: ignore[misc]


def test_parse_result_defaults() -> None:
    r = ParseResult(file_path="a.py", language="python", role="source")
    assert r.symbols == ()
    assert r.relations == ()
    assert r.errors == ()
```

- [ ] **Step 2: Run — expect fail**

Run: `uv run pytest tests/unit/parsers/test_base.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement base**

Create `libs/parsers/__init__.py`:
```python
"""Parsers convert raw file bytes into ParseResult (symbols + relations)."""
```

Create `libs/parsers/base.py`:
```python
"""Parser protocol and result dataclass."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import ConfigDict

from libs.core.entities import Immutable, Relation, Symbol


class ParseResult(Immutable):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    file_path: str
    language: str
    role: str
    symbols: tuple[Symbol, ...] = ()
    relations: tuple[Relation, ...] = ()
    errors: tuple[str, ...] = ()


@runtime_checkable
class FileParser(Protocol):
    """A parser takes raw bytes and a (POSIX) file path, returns ParseResult."""

    language: str

    def parse(self, *, file_path: str, data: bytes) -> ParseResult:
        ...
```

Also need to re-export `Immutable` from `libs/core/entities.py` — add to its `__all__` or just import directly. The code above imports it directly, which works.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/parsers/test_base.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add libs/parsers/__init__.py libs/parsers/base.py tests/unit/parsers/__init__.py tests/unit/parsers/test_base.py
git commit -m "feat(parsers): FileParser protocol and ParseResult dataclass"
```

---

## Task 1.2: libs/parsers/text_parsers.py — markdown/yaml/json/toml

**Files:**
- Create: `libs/parsers/text_parsers.py`
- Create: `tests/unit/parsers/test_text_parsers.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/parsers/test_text_parsers.py`:
```python
from libs.parsers.text_parsers import (
    JsonParser,
    MarkdownParser,
    TomlParser,
    YamlParser,
)


def test_markdown_extracts_headings_as_symbols() -> None:
    parser = MarkdownParser()
    data = b"# Title\n\n## Section A\n\ntext\n\n## Section B\n"
    result = parser.parse(file_path="docs/a.md", data=data)
    names = [s.name for s in result.symbols]
    assert "Title" in names
    assert "Section A" in names
    assert "Section B" in names


def test_yaml_parses_valid_doc_without_symbols() -> None:
    parser = YamlParser()
    data = b"key: value\nlist:\n  - 1\n  - 2\n"
    result = parser.parse(file_path="config.yaml", data=data)
    assert result.language == "yaml"
    assert result.errors == ()


def test_yaml_records_error_on_invalid() -> None:
    parser = YamlParser()
    result = parser.parse(file_path="bad.yaml", data=b": : : bad")
    assert result.errors != ()


def test_json_parses_valid() -> None:
    parser = JsonParser()
    result = parser.parse(file_path="a.json", data=b'{"a":1}')
    assert result.errors == ()


def test_toml_parses_valid() -> None:
    parser = TomlParser()
    result = parser.parse(file_path="a.toml", data=b'key = "value"\n')
    assert result.errors == ()
```

- [ ] **Step 2: Run — expect fail**

Run: `uv run pytest tests/unit/parsers/test_text_parsers.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement parsers**

Create `libs/parsers/text_parsers.py`:
```python
"""Deterministic parsers for markdown and config files.

None of these need tree-sitter or LLM. They use stdlib or tiny deps.
"""

from __future__ import annotations

import json
import re
import tomllib

import yaml

from libs.core.entities import Symbol, SymbolType
from libs.parsers.base import ParseResult


class MarkdownParser:
    language = "markdown"

    _heading_re = re.compile(rb"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)

    def parse(self, *, file_path: str, data: bytes) -> ParseResult:
        symbols: list[Symbol] = []
        for match in self._heading_re.finditer(data):
            level = len(match.group(1))
            title = match.group(2).decode("utf-8", errors="replace").strip()
            # Line number: count newlines before match.start
            line = data.count(b"\n", 0, match.start()) + 1
            symbols.append(
                Symbol(
                    name=title,
                    fq_name=f"{file_path}#h{level}-{title}",
                    symbol_type=SymbolType.MODULE if level == 1 else SymbolType.CLASS,
                    file_path=file_path,
                    start_line=line,
                    end_line=line,
                )
            )
        return ParseResult(
            file_path=file_path,
            language=self.language,
            role="docs",
            symbols=tuple(symbols),
        )


class YamlParser:
    language = "yaml"

    def parse(self, *, file_path: str, data: bytes) -> ParseResult:
        errors: tuple[str, ...] = ()
        try:
            yaml.safe_load(data)
        except yaml.YAMLError as exc:
            errors = (f"yaml parse error: {exc}",)
        return ParseResult(
            file_path=file_path,
            language=self.language,
            role="config",
            errors=errors,
        )


class JsonParser:
    language = "json"

    def parse(self, *, file_path: str, data: bytes) -> ParseResult:
        errors: tuple[str, ...] = ()
        try:
            json.loads(data)
        except json.JSONDecodeError as exc:
            errors = (f"json parse error: {exc}",)
        return ParseResult(
            file_path=file_path,
            language=self.language,
            role="config",
            errors=errors,
        )


class TomlParser:
    language = "toml"

    def parse(self, *, file_path: str, data: bytes) -> ParseResult:
        errors: tuple[str, ...] = ()
        try:
            tomllib.loads(data.decode("utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            errors = (f"toml parse error: {exc}",)
        return ParseResult(
            file_path=file_path,
            language=self.language,
            role="config",
            errors=errors,
        )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/parsers/test_text_parsers.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add libs/parsers/text_parsers.py tests/unit/parsers/test_text_parsers.py
git commit -m "feat(parsers): markdown/yaml/json/toml deterministic parsers"
```

---

## Task 1.3: libs/parsers/python.py — tree-sitter + AST Python parser

**Files:**
- Create: `libs/parsers/python.py`
- Create: `tests/unit/parsers/test_python_parser.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/parsers/test_python_parser.py`:
```python
from libs.core.entities import RelationType, SymbolType
from libs.parsers.python import PythonParser


SOURCE = b'''
"""module docstring"""

from datetime import datetime
from app.models.user import User

CONSTANT = 42


class Service:
    """A service."""

    def run(self) -> None:
        helper()
        self.process()

    def process(self) -> None:
        pass


def helper() -> int:
    return 1
'''


def test_python_extracts_functions_and_classes() -> None:
    result = PythonParser().parse(file_path="app/svc.py", data=SOURCE)
    names = {s.name for s in result.symbols}
    assert "Service" in names
    assert "helper" in names
    assert "run" in names
    assert "process" in names
    assert "CONSTANT" in names


def test_python_records_imports_as_relations() -> None:
    result = PythonParser().parse(file_path="app/svc.py", data=SOURCE)
    imports = [
        r for r in result.relations if r.relation_type == RelationType.IMPORTS
    ]
    targets = {r.dst_ref for r in imports}
    assert "datetime" in targets
    assert "app.models.user.User" in targets


def test_python_records_defines_relations() -> None:
    result = PythonParser().parse(file_path="app/svc.py", data=SOURCE)
    defines = [
        r for r in result.relations if r.relation_type == RelationType.DEFINES
    ]
    # file defines at least Service, helper, CONSTANT
    dst_refs = {r.dst_ref for r in defines}
    assert any("Service" in x for x in dst_refs)
    assert any("helper" in x for x in dst_refs)


def test_python_records_same_file_calls() -> None:
    result = PythonParser().parse(file_path="app/svc.py", data=SOURCE)
    calls = [
        r for r in result.relations if r.relation_type == RelationType.SAME_FILE_CALLS
    ]
    # Service.run calls helper and self.process
    targets = {r.dst_ref for r in calls}
    assert any("helper" in t for t in targets)


def test_python_handles_syntax_error_gracefully() -> None:
    result = PythonParser().parse(file_path="bad.py", data=b"def (((")
    assert result.errors != ()


def test_python_symbol_types() -> None:
    result = PythonParser().parse(file_path="app/svc.py", data=SOURCE)
    by_name = {s.name: s for s in result.symbols}
    assert by_name["Service"].symbol_type == SymbolType.CLASS
    assert by_name["helper"].symbol_type == SymbolType.FUNCTION
    assert by_name["run"].symbol_type == SymbolType.METHOD
    assert by_name["CONSTANT"].symbol_type == SymbolType.CONSTANT
```

- [ ] **Step 2: Run — expect fail**

Run: `uv run pytest tests/unit/parsers/test_python_parser.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement Python parser using stdlib ast (primary)**

We'll use Python stdlib `ast` as the **primary** parser for Python because name binding and scope resolution are actually tractable with stdlib. Tree-sitter is reserved for non-Python languages in later phases. This keeps Phase 1 simpler and more accurate.

Create `libs/parsers/python.py`:
```python
"""Python parser using stdlib ast.

Primary parser for Python — stdlib is more accurate for Python name resolution
than tree-sitter, which shines for multi-language heuristics. We can add
tree-sitter cross-validation later if precision drops.
"""

from __future__ import annotations

import ast

from libs.core.entities import Relation, RelationType, Symbol, SymbolType
from libs.parsers.base import ParseResult


class PythonParser:
    language = "python"

    def parse(self, *, file_path: str, data: bytes) -> ParseResult:
        try:
            tree = ast.parse(data, filename=file_path, type_comments=False)
        except SyntaxError as exc:
            return ParseResult(
                file_path=file_path,
                language=self.language,
                role=self._role(file_path),
                errors=(f"python parse error: {exc}",),
            )

        module_fq = self._module_fq(file_path)
        collector = _SymbolCollector(file_path=file_path, module_fq=module_fq)
        collector.visit(tree)

        return ParseResult(
            file_path=file_path,
            language=self.language,
            role=self._role(file_path),
            symbols=tuple(collector.symbols),
            relations=tuple(collector.relations),
        )

    @staticmethod
    def _module_fq(file_path: str) -> str:
        posix = file_path.replace("\\", "/")
        if posix.endswith(".py"):
            posix = posix[:-3]
        if posix.endswith("/__init__"):
            posix = posix[: -len("/__init__")]
        return posix.replace("/", ".")

    @staticmethod
    def _role(file_path: str) -> str:
        p = file_path.replace("\\", "/")
        if "/tests/" in p or p.startswith("tests/") or p.endswith("_test.py") or p.startswith("test_"):
            return "test"
        return "source"


class _SymbolCollector(ast.NodeVisitor):
    def __init__(self, *, file_path: str, module_fq: str) -> None:
        self.file_path = file_path
        self.module_fq = module_fq
        self.symbols: list[Symbol] = []
        self.relations: list[Relation] = []
        self._scope_stack: list[str] = [module_fq]
        self._current_function_fq: str | None = None

    # --- imports ------------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.relations.append(
                Relation(
                    src_type="file",
                    src_ref=self.file_path,
                    dst_type="module",
                    dst_ref=alias.name,
                    relation_type=RelationType.IMPORTS,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            dst = f"{module}.{alias.name}" if module else alias.name
            self.relations.append(
                Relation(
                    src_type="file",
                    src_ref=self.file_path,
                    dst_type="symbol",
                    dst_ref=dst,
                    relation_type=RelationType.IMPORTS,
                )
            )

    # --- definitions --------------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        fq = self._join_scope(node.name)
        self.symbols.append(
            Symbol(
                name=node.name,
                fq_name=fq,
                symbol_type=SymbolType.CLASS,
                file_path=self.file_path,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                parent_fq_name=self._scope_stack[-1],
                docstring=ast.get_docstring(node),
            )
        )
        self._add_defines(fq)
        self._scope_stack.append(fq)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_func(node, is_async=True)

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef, *, is_async: bool) -> None:
        fq = self._join_scope(node.name)
        parent = self._scope_stack[-1]
        sym_type = (
            SymbolType.METHOD
            if len(self._scope_stack) > 1 and self._is_class_scope(parent)
            else SymbolType.FUNCTION
        )
        signature = self._render_signature(node)
        self.symbols.append(
            Symbol(
                name=node.name,
                fq_name=fq,
                symbol_type=sym_type,
                file_path=self.file_path,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                parent_fq_name=parent,
                signature=signature,
                docstring=ast.get_docstring(node),
            )
        )
        self._add_defines(fq)

        prev = self._current_function_fq
        self._current_function_fq = fq
        self._scope_stack.append(fq)
        self.generic_visit(node)
        self._scope_stack.pop()
        self._current_function_fq = prev

    def visit_Assign(self, node: ast.Assign) -> None:
        # Module-level uppercase assignments → CONSTANT
        if len(self._scope_stack) == 1:
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    fq = self._join_scope(target.id)
                    self.symbols.append(
                        Symbol(
                            name=target.id,
                            fq_name=fq,
                            symbol_type=SymbolType.CONSTANT,
                            file_path=self.file_path,
                            start_line=node.lineno,
                            end_line=node.end_lineno or node.lineno,
                            parent_fq_name=self._scope_stack[-1],
                        )
                    )
                    self._add_defines(fq)
        self.generic_visit(node)

    # --- calls --------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        if self._current_function_fq is not None:
            target = self._call_target(node.func)
            if target is not None:
                self.relations.append(
                    Relation(
                        src_type="symbol",
                        src_ref=self._current_function_fq,
                        dst_type="symbol",
                        dst_ref=target,
                        relation_type=RelationType.SAME_FILE_CALLS,
                        confidence=0.8,  # same-file, but no type inference
                    )
                )
        self.generic_visit(node)

    # --- helpers ------------------------------------------------------------

    def _join_scope(self, name: str) -> str:
        return f"{self._scope_stack[-1]}.{name}"

    def _is_class_scope(self, fq: str) -> bool:
        for s in self.symbols:
            if s.fq_name == fq and s.symbol_type == SymbolType.CLASS:
                return True
        return False

    def _add_defines(self, fq: str) -> None:
        self.relations.append(
            Relation(
                src_type="file",
                src_ref=self.file_path,
                dst_type="symbol",
                dst_ref=fq,
                relation_type=RelationType.DEFINES,
            )
        )

    @staticmethod
    def _render_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        try:
            return f"{node.name}({ast.unparse(node.args)})"
        except Exception:
            return node.name

    @staticmethod
    def _call_target(func: ast.AST) -> str | None:
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            parts: list[str] = [func.attr]
            cur: ast.AST = func.value
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
            return ".".join(reversed(parts))
        return None
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/parsers/test_python_parser.py -v`
Expected: 6 passed.

- [ ] **Step 5: mypy strict check**

Run: `uv run mypy libs tests`
Expected: 0 errors.

- [ ] **Step 6: Commit**

```bash
git add libs/parsers/python.py tests/unit/parsers/test_python_parser.py
git commit -m "feat(parsers): python parser (stdlib ast) with symbols, imports, defines, same-file calls"
```

---

## Task 1.4: libs/parsers/registry.py — language detection and parser selection

**Files:**
- Create: `libs/parsers/registry.py`
- Create: `tests/unit/parsers/test_registry.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/parsers/test_registry.py`:
```python
from libs.parsers.registry import detect_language, get_parser


def test_detect_language_by_extension() -> None:
    assert detect_language("a.py") == "python"
    assert detect_language("a.md") == "markdown"
    assert detect_language("a.yaml") == "yaml"
    assert detect_language("a.yml") == "yaml"
    assert detect_language("a.json") == "json"
    assert detect_language("a.toml") == "toml"
    assert detect_language("unknown.xyz") == "unknown"


def test_get_parser_returns_matching_instance() -> None:
    p = get_parser("python")
    assert p is not None
    assert p.language == "python"


def test_get_parser_returns_none_for_unknown() -> None:
    assert get_parser("cobol") is None
```

- [ ] **Step 2: Run — expect fail**

Run: `uv run pytest tests/unit/parsers/test_registry.py -v`

- [ ] **Step 3: Implement registry**

Create `libs/parsers/registry.py`:
```python
"""Language detection and parser lookup."""

from __future__ import annotations

from libs.parsers.base import FileParser
from libs.parsers.python import PythonParser
from libs.parsers.text_parsers import JsonParser, MarkdownParser, TomlParser, YamlParser

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".md": "markdown",
    ".markdown": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
}


def detect_language(path: str) -> str:
    for ext, lang in EXTENSION_TO_LANGUAGE.items():
        if path.endswith(ext):
            return lang
    return "unknown"


_PARSERS: dict[str, FileParser] = {
    "python": PythonParser(),
    "markdown": MarkdownParser(),
    "yaml": YamlParser(),
    "json": JsonParser(),
    "toml": TomlParser(),
}


def get_parser(language: str) -> FileParser | None:
    return _PARSERS.get(language)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/parsers -v`
Expected: all parser tests pass.

- [ ] **Step 5: Commit**

```bash
git add libs/parsers/registry.py tests/unit/parsers/test_registry.py
git commit -m "feat(parsers): language detection and parser registry"
```

---

## Task 1.5: libs/storage/sqlite_cache.py — local SQLite cache

**Files:**
- Create: `libs/storage/__init__.py`
- Create: `libs/storage/sqlite_cache.py`
- Create: `tests/unit/storage/__init__.py`
- Create: `tests/unit/storage/test_sqlite_cache.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/storage/__init__.py`:
```python
```

Create `tests/unit/storage/test_sqlite_cache.py`:
```python
from pathlib import Path

import pytest

from libs.core.entities import File, RelationType, Symbol, SymbolType, Relation
from libs.storage.sqlite_cache import SqliteCache


@pytest.fixture
def cache(tmp_path: Path) -> SqliteCache:
    c = SqliteCache(tmp_path / "cache.db")
    c.migrate()
    return c


def test_put_and_get_file(cache: SqliteCache) -> None:
    f = File(
        path="app/main.py",
        content_hash="a" * 64,
        size_bytes=100,
        language="python",
        role="source",
    )
    cache.put_file(f)
    got = cache.get_file("app/main.py")
    assert got == f


def test_put_file_is_idempotent(cache: SqliteCache) -> None:
    f = File(path="a.py", content_hash="h1", size_bytes=1, language="python", role="source")
    cache.put_file(f)
    cache.put_file(f)
    assert cache.file_count() == 1


def test_update_file_replaces_row(cache: SqliteCache) -> None:
    f1 = File(path="a.py", content_hash="h1", size_bytes=1, language="python", role="source")
    f2 = File(path="a.py", content_hash="h2", size_bytes=2, language="python", role="source")
    cache.put_file(f1)
    cache.put_file(f2)
    assert cache.get_file("a.py") == f2
    assert cache.file_count() == 1


def test_delete_file(cache: SqliteCache) -> None:
    f = File(path="a.py", content_hash="h", size_bytes=1, language="python", role="source")
    cache.put_file(f)
    cache.delete_file("a.py")
    assert cache.get_file("a.py") is None


def test_put_and_list_symbols(cache: SqliteCache) -> None:
    s = Symbol(
        name="User",
        fq_name="app.models.user.User",
        symbol_type=SymbolType.CLASS,
        file_path="app/models/user.py",
        start_line=1,
        end_line=20,
    )
    cache.replace_symbols(file_path="app/models/user.py", symbols=(s,))
    got = list(cache.iter_symbols())
    assert got == [s]


def test_replace_symbols_removes_old(cache: SqliteCache) -> None:
    s1 = Symbol(
        name="Old", fq_name="x.Old", symbol_type=SymbolType.CLASS,
        file_path="x.py", start_line=1, end_line=2,
    )
    s2 = Symbol(
        name="New", fq_name="x.New", symbol_type=SymbolType.CLASS,
        file_path="x.py", start_line=1, end_line=2,
    )
    cache.replace_symbols(file_path="x.py", symbols=(s1,))
    cache.replace_symbols(file_path="x.py", symbols=(s2,))
    names = {s.name for s in cache.iter_symbols()}
    assert names == {"New"}


def test_replace_relations(cache: SqliteCache) -> None:
    r = Relation(
        src_type="file", src_ref="a.py",
        dst_type="module", dst_ref="datetime",
        relation_type=RelationType.IMPORTS,
    )
    cache.replace_relations(file_path="a.py", relations=(r,))
    got = list(cache.iter_relations())
    assert len(got) == 1
    assert got[0].dst_ref == "datetime"
```

- [ ] **Step 2: Run — expect fail**

Run: `uv run pytest tests/unit/storage/test_sqlite_cache.py -v`

- [ ] **Step 3: Implement SqliteCache**

Create `libs/storage/__init__.py`:
```python
"""Persistent state for LV_DCP CLI. Phase 1 uses SQLite only."""
```

Create `libs/storage/sqlite_cache.py`:
```python
"""SQLite local cache for file state, symbols, and relations.

Single-writer (the CLI process). Schema is versioned via PRAGMA user_version.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path

from libs.core.entities import File, Relation, RelationType, Symbol, SymbolType

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path          TEXT PRIMARY KEY,
    content_hash  TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    language      TEXT NOT NULL,
    role          TEXT NOT NULL,
    is_generated  INTEGER NOT NULL DEFAULT 0,
    is_binary     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS symbols (
    fq_name         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    symbol_type     TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    start_line      INTEGER NOT NULL,
    end_line        INTEGER NOT NULL,
    parent_fq_name  TEXT,
    signature       TEXT,
    docstring       TEXT,
    FOREIGN KEY (file_path) REFERENCES files(path) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_path);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);

CREATE TABLE IF NOT EXISTS relations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    src_type       TEXT NOT NULL,
    src_ref        TEXT NOT NULL,
    dst_type       TEXT NOT NULL,
    dst_ref        TEXT NOT NULL,
    relation_type  TEXT NOT NULL,
    confidence     REAL NOT NULL DEFAULT 1.0,
    provenance     TEXT NOT NULL DEFAULT 'deterministic',
    origin_file    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rel_origin ON relations(origin_file);
CREATE INDEX IF NOT EXISTS idx_rel_src ON relations(src_ref);
CREATE INDEX IF NOT EXISTS idx_rel_dst ON relations(dst_ref);
CREATE INDEX IF NOT EXISTS idx_rel_type ON relations(relation_type);
"""


class SqliteCache:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def migrate(self) -> None:
        conn = self._connect()
        conn.executescript(_SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()

    # --- files --------------------------------------------------------------

    def put_file(self, file: File) -> None:
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO files (path, content_hash, size_bytes, language, role, is_generated, is_binary)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                content_hash = excluded.content_hash,
                size_bytes = excluded.size_bytes,
                language = excluded.language,
                role = excluded.role,
                is_generated = excluded.is_generated,
                is_binary = excluded.is_binary
            """,
            (
                file.path,
                file.content_hash,
                file.size_bytes,
                file.language,
                file.role,
                int(file.is_generated),
                int(file.is_binary),
            ),
        )
        conn.commit()

    def get_file(self, path: str) -> File | None:
        conn = self._connect()
        row = conn.execute(
            "SELECT path, content_hash, size_bytes, language, role, is_generated, is_binary "
            "FROM files WHERE path = ?",
            (path,),
        ).fetchone()
        if row is None:
            return None
        return File(
            path=row[0],
            content_hash=row[1],
            size_bytes=row[2],
            language=row[3],
            role=row[4],
            is_generated=bool(row[5]),
            is_binary=bool(row[6]),
        )

    def delete_file(self, path: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM files WHERE path = ?", (path,))
        conn.commit()

    def file_count(self) -> int:
        conn = self._connect()
        return int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])

    def iter_files(self) -> Iterator[File]:
        conn = self._connect()
        for row in conn.execute(
            "SELECT path, content_hash, size_bytes, language, role, is_generated, is_binary FROM files"
        ):
            yield File(
                path=row[0],
                content_hash=row[1],
                size_bytes=row[2],
                language=row[3],
                role=row[4],
                is_generated=bool(row[5]),
                is_binary=bool(row[6]),
            )

    # --- symbols ------------------------------------------------------------

    def replace_symbols(self, *, file_path: str, symbols: Iterable[Symbol]) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM symbols WHERE file_path = ?", (file_path,))
        conn.executemany(
            """
            INSERT OR REPLACE INTO symbols
                (fq_name, name, symbol_type, file_path, start_line, end_line,
                 parent_fq_name, signature, docstring)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    s.fq_name,
                    s.name,
                    s.symbol_type.value,
                    s.file_path,
                    s.start_line,
                    s.end_line,
                    s.parent_fq_name,
                    s.signature,
                    s.docstring,
                )
                for s in symbols
            ],
        )
        conn.commit()

    def iter_symbols(self) -> Iterator[Symbol]:
        conn = self._connect()
        for row in conn.execute(
            "SELECT name, fq_name, symbol_type, file_path, start_line, end_line, "
            "parent_fq_name, signature, docstring FROM symbols"
        ):
            yield Symbol(
                name=row[0],
                fq_name=row[1],
                symbol_type=SymbolType(row[2]),
                file_path=row[3],
                start_line=row[4],
                end_line=row[5],
                parent_fq_name=row[6],
                signature=row[7],
                docstring=row[8],
            )

    # --- relations ----------------------------------------------------------

    def replace_relations(self, *, file_path: str, relations: Iterable[Relation]) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM relations WHERE origin_file = ?", (file_path,))
        conn.executemany(
            """
            INSERT INTO relations
                (src_type, src_ref, dst_type, dst_ref, relation_type, confidence, provenance, origin_file)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r.src_type,
                    r.src_ref,
                    r.dst_type,
                    r.dst_ref,
                    r.relation_type.value,
                    r.confidence,
                    r.provenance,
                    file_path,
                )
                for r in relations
            ],
        )
        conn.commit()

    def iter_relations(self) -> Iterator[Relation]:
        conn = self._connect()
        for row in conn.execute(
            "SELECT src_type, src_ref, dst_type, dst_ref, relation_type, confidence, provenance FROM relations"
        ):
            yield Relation(
                src_type=row[0],
                src_ref=row[1],
                dst_type=row[2],
                dst_ref=row[3],
                relation_type=RelationType(row[4]),
                confidence=row[5],
                provenance=row[6],
            )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/storage -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add libs/storage/__init__.py libs/storage/sqlite_cache.py tests/unit/storage/__init__.py tests/unit/storage/test_sqlite_cache.py
git commit -m "feat(storage): SQLite local cache for files/symbols/relations"
```

---

## Task 1.6: libs/retrieval/fts.py — SQLite FTS5 wrapper

**Files:**
- Create: `libs/retrieval/__init__.py`
- Create: `libs/retrieval/fts.py`
- Create: `tests/unit/retrieval/__init__.py`
- Create: `tests/unit/retrieval/test_fts.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/retrieval/__init__.py`:
```python
```

Create `tests/unit/retrieval/test_fts.py`:
```python
from pathlib import Path

import pytest

from libs.retrieval.fts import FtsIndex


@pytest.fixture
def fts(tmp_path: Path) -> FtsIndex:
    idx = FtsIndex(tmp_path / "fts.db")
    idx.create()
    return idx


def test_index_and_search_file(fts: FtsIndex) -> None:
    fts.index_file("app/models/user.py", "User model with email and password hash")
    results = fts.search("User model", limit=5)
    assert any(path == "app/models/user.py" for path, _score in results)


def test_search_ranks_more_specific_higher(fts: FtsIndex) -> None:
    fts.index_file("a.py", "unrelated content about foo bar baz")
    fts.index_file("b.py", "authentication authentication authentication")
    results = fts.search("authentication", limit=5)
    assert results[0][0] == "b.py"


def test_replace_file_removes_old_content(fts: FtsIndex) -> None:
    fts.index_file("a.py", "old content about cats")
    fts.index_file("a.py", "new content about dogs")
    cats = fts.search("cats", limit=5)
    dogs = fts.search("dogs", limit=5)
    assert not cats
    assert dogs


def test_delete_file_removes_from_index(fts: FtsIndex) -> None:
    fts.index_file("a.py", "content here")
    fts.delete_file("a.py")
    assert not fts.search("content", limit=5)
```

- [ ] **Step 2: Run — expect fail**

Run: `uv run pytest tests/unit/retrieval/test_fts.py -v`

- [ ] **Step 3: Implement FtsIndex**

Create `libs/retrieval/__init__.py`:
```python
"""Retrieval pipeline (deterministic in Phase 1, + semantic in Phase 2)."""
```

Create `libs/retrieval/fts.py`:
```python
"""SQLite FTS5 wrapper for full-text search over file contents and symbol text.

Two-layer schema:
- fts_files(path, content) — one row per file
- external delete/replace handled via explicit DELETE + INSERT
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


class FtsIndex:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA journal_mode = WAL")
        return self._conn

    def create(self) -> None:
        conn = self._connect()
        conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_files USING fts5(
                path UNINDEXED,
                content,
                tokenize = 'porter unicode61'
            );
            """
        )
        conn.commit()

    def index_file(self, path: str, content: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM fts_files WHERE path = ?", (path,))
        conn.execute(
            "INSERT INTO fts_files (path, content) VALUES (?, ?)",
            (path, content),
        )
        conn.commit()

    def delete_file(self, path: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM fts_files WHERE path = ?", (path,))
        conn.commit()

    def search(self, query: str, *, limit: int = 20) -> list[tuple[str, float]]:
        conn = self._connect()
        # bm25() gives lower = better; negate so higher = better
        safe_query = self._sanitize(query)
        if not safe_query:
            return []
        rows = conn.execute(
            """
            SELECT path, -bm25(fts_files) AS score
            FROM fts_files
            WHERE fts_files MATCH ?
            ORDER BY score DESC
            LIMIT ?
            """,
            (safe_query, limit),
        ).fetchall()
        return [(path, float(score)) for path, score in rows]

    @staticmethod
    def _sanitize(query: str) -> str:
        # Strip FTS5 special characters except alphanumerics, underscores, dots, spaces
        allowed = []
        for ch in query:
            if ch.isalnum() or ch in " _.":
                allowed.append(ch)
            else:
                allowed.append(" ")
        cleaned = " ".join("".join(allowed).split())
        if not cleaned:
            return ""
        # Wrap each token as prefix search for lenient matching
        tokens = [f'"{t}"*' for t in cleaned.split() if len(t) >= 2]
        return " OR ".join(tokens)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/retrieval/test_fts.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add libs/retrieval/__init__.py libs/retrieval/fts.py tests/unit/retrieval/__init__.py tests/unit/retrieval/test_fts.py
git commit -m "feat(retrieval): SQLite FTS5 wrapper for file-level full-text search"
```

---

## Task 1.7: libs/retrieval/index.py — symbol index with exact and fuzzy lookup

**Files:**
- Create: `libs/retrieval/index.py`
- Create: `tests/unit/retrieval/test_index.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/retrieval/test_index.py`:
```python
from libs.core.entities import Symbol, SymbolType
from libs.retrieval.index import SymbolIndex


def _sym(name: str, fq: str) -> Symbol:
    return Symbol(
        name=name,
        fq_name=fq,
        symbol_type=SymbolType.FUNCTION,
        file_path=fq.rsplit(".", 1)[0].replace(".", "/") + ".py",
        start_line=1,
        end_line=2,
    )


def test_exact_name_match_ranks_first() -> None:
    idx = SymbolIndex()
    idx.add(_sym("login", "app.handlers.auth.login"))
    idx.add(_sym("logout", "app.handlers.auth.logout"))
    results = idx.lookup("login", limit=5)
    assert results[0].name == "login"


def test_fq_substring_match() -> None:
    idx = SymbolIndex()
    idx.add(_sym("User", "app.models.user.User"))
    idx.add(_sym("UserService", "app.services.user.UserService"))
    results = idx.lookup("models.user", limit=5)
    assert any("app.models.user.User" == s.fq_name for s in results)


def test_tokens_match_name_case_insensitive() -> None:
    idx = SymbolIndex()
    idx.add(_sym("refresh_access_token", "app.services.auth.refresh_access_token"))
    results = idx.lookup("refresh token", limit=5)
    assert any("refresh_access_token" == s.name for s in results)


def test_empty_query_returns_empty() -> None:
    idx = SymbolIndex()
    idx.add(_sym("x", "x"))
    assert idx.lookup("", limit=5) == []
```

- [ ] **Step 2: Run — expect fail**

Run: `uv run pytest tests/unit/retrieval/test_index.py -v`

- [ ] **Step 3: Implement SymbolIndex**

Create `libs/retrieval/index.py`:
```python
"""In-memory symbol index with token-based scoring.

Deterministic. Replaceable later by a proper inverted index or vector store.
"""

from __future__ import annotations

import re

from libs.core.entities import Symbol

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


def _tokenize(text: str) -> list[str]:
    # Split on non-alphanumeric, then further split camelCase and snake_case
    parts = _TOKEN_RE.findall(text)
    out: list[str] = []
    for p in parts:
        # snake_case
        for s in p.split("_"):
            if not s:
                continue
            # camelCase: insert break before uppercase preceded by lowercase
            chunks = re.split(r"(?<=[a-z])(?=[A-Z])", s)
            out.extend(c.lower() for c in chunks if c)
    return out


class SymbolIndex:
    def __init__(self) -> None:
        self._symbols: list[Symbol] = []

    def add(self, symbol: Symbol) -> None:
        self._symbols.append(symbol)

    def extend(self, symbols: list[Symbol]) -> None:
        self._symbols.extend(symbols)

    def clear(self) -> None:
        self._symbols.clear()

    def lookup(self, query: str, *, limit: int = 10) -> list[Symbol]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[float, Symbol]] = []
        for sym in self._symbols:
            score = self._score(sym, query_tokens, raw_query=query.lower())
            if score > 0:
                scored.append((score, sym))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _score, s in scored[:limit]]

    @staticmethod
    def _score(sym: Symbol, query_tokens: list[str], *, raw_query: str) -> float:
        name_tokens = _tokenize(sym.name)
        fq_tokens = _tokenize(sym.fq_name)

        score = 0.0
        # Exact name match (case-insensitive) is strongest
        if sym.name.lower() == raw_query.strip():
            score += 10.0
        # Substring of fq_name
        if raw_query.strip() in sym.fq_name.lower():
            score += 3.0
        # Token overlap
        name_set = set(name_tokens)
        fq_set = set(fq_tokens)
        for t in query_tokens:
            if t in name_set:
                score += 2.0
            elif t in fq_set:
                score += 1.0
        return score
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/retrieval/test_index.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add libs/retrieval/index.py tests/unit/retrieval/test_index.py
git commit -m "feat(retrieval): in-memory symbol index with token scoring"
```

---

## Task 1.8: libs/retrieval/pipeline.py — multi-stage deterministic retrieval

**Files:**
- Create: `libs/retrieval/pipeline.py`
- Create: `tests/unit/retrieval/test_pipeline.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/retrieval/test_pipeline.py`:
```python
from pathlib import Path

import pytest

from libs.core.entities import File, RelationType, Symbol, SymbolType, Relation
from libs.retrieval.fts import FtsIndex
from libs.retrieval.index import SymbolIndex
from libs.retrieval.pipeline import RetrievalPipeline, RetrievalResult
from libs.storage.sqlite_cache import SqliteCache


@pytest.fixture
def pipeline(tmp_path: Path) -> RetrievalPipeline:
    cache = SqliteCache(tmp_path / "cache.db")
    cache.migrate()
    fts = FtsIndex(tmp_path / "fts.db")
    fts.create()
    sym_idx = SymbolIndex()

    # Seed
    cache.put_file(File(
        path="app/models/user.py",
        content_hash="h1", size_bytes=100,
        language="python", role="source",
    ))
    cache.put_file(File(
        path="app/handlers/auth.py",
        content_hash="h2", size_bytes=200,
        language="python", role="source",
    ))
    fts.index_file("app/models/user.py", "class User email password")
    fts.index_file("app/handlers/auth.py", "login logout refresh authentication")

    sym_idx.add(Symbol(
        name="User",
        fq_name="app.models.user.User",
        symbol_type=SymbolType.CLASS,
        file_path="app/models/user.py",
        start_line=1, end_line=10,
    ))
    sym_idx.add(Symbol(
        name="login",
        fq_name="app.handlers.auth.login",
        symbol_type=SymbolType.FUNCTION,
        file_path="app/handlers/auth.py",
        start_line=5, end_line=15,
    ))

    return RetrievalPipeline(cache=cache, fts=fts, symbols=sym_idx)


def test_pipeline_finds_file_by_symbol_query(pipeline: RetrievalPipeline) -> None:
    result: RetrievalResult = pipeline.retrieve("User", mode="navigate", limit=5)
    assert "app/models/user.py" in result.files
    assert "app.models.user.User" in result.symbols


def test_pipeline_finds_file_by_fts(pipeline: RetrievalPipeline) -> None:
    result = pipeline.retrieve("authentication", mode="navigate", limit=5)
    assert "app/handlers/auth.py" in result.files


def test_pipeline_combines_symbol_and_fts(pipeline: RetrievalPipeline) -> None:
    result = pipeline.retrieve("login", mode="navigate", limit=5)
    assert result.files[0] == "app/handlers/auth.py"
```

- [ ] **Step 2: Run — expect fail**

Run: `uv run pytest tests/unit/retrieval/test_pipeline.py -v`

- [ ] **Step 3: Implement pipeline**

Create `libs/retrieval/pipeline.py`:
```python
"""Multi-stage deterministic retrieval.

Phase 1 stages:
1. Symbol exact / substring match → candidate symbols, their files
2. FTS5 full-text search → candidate files by content
3. Merge with weighted scoring, stable tie-breaking
4. Return files and symbols ordered by combined score

Phase 2 adds: vector stage, rerank. Wire points preserved in TODO comments.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from libs.core.entities import Symbol
from libs.retrieval.fts import FtsIndex
from libs.retrieval.index import SymbolIndex
from libs.storage.sqlite_cache import SqliteCache

SYMBOL_WEIGHT = 3.0
FTS_WEIGHT = 1.0


@dataclass(frozen=True)
class RetrievalResult:
    files: list[str]
    symbols: list[str]
    scores: dict[str, float]


class RetrievalPipeline:
    def __init__(
        self,
        *,
        cache: SqliteCache,
        fts: FtsIndex,
        symbols: SymbolIndex,
    ) -> None:
        self._cache = cache
        self._fts = fts
        self._symbols = symbols

    def retrieve(
        self,
        query: str,
        *,
        mode: str = "navigate",
        limit: int = 10,
    ) -> RetrievalResult:
        file_scores: dict[str, float] = defaultdict(float)
        symbol_hits: list[Symbol] = []

        # Stage 1: symbol match
        for sym in self._symbols.lookup(query, limit=limit * 2):
            symbol_hits.append(sym)
            file_scores[sym.file_path] += SYMBOL_WEIGHT

        # Stage 2: FTS
        for path, score in self._fts.search(query, limit=limit * 2):
            file_scores[path] += FTS_WEIGHT * score

        # Rank files
        ordered_files = sorted(
            file_scores.items(), key=lambda kv: (-kv[1], kv[0])
        )
        files = [p for p, _ in ordered_files[:limit]]

        # Deduplicate symbols by fq_name, keep insertion order
        seen: set[str] = set()
        symbol_fqs: list[str] = []
        for sym in symbol_hits:
            if sym.fq_name not in seen:
                seen.add(sym.fq_name)
                symbol_fqs.append(sym.fq_name)
        symbol_fqs = symbol_fqs[:limit]

        return RetrievalResult(
            files=files,
            symbols=symbol_fqs,
            scores=dict(file_scores),
        )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/retrieval -v`
Expected: all retrieval tests pass.

- [ ] **Step 5: Commit**

```bash
git add libs/retrieval/pipeline.py tests/unit/retrieval/test_pipeline.py
git commit -m "feat(retrieval): multi-stage deterministic pipeline (symbol + FTS merge)"
```

---

## Task 1.9: libs/graph — in-memory graph builder and traversal

**Files:**
- Create: `libs/graph/__init__.py`
- Create: `libs/graph/builder.py`
- Create: `tests/unit/graph/__init__.py`
- Create: `tests/unit/graph/test_builder.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/graph/__init__.py`:
```python
```

Create `tests/unit/graph/test_builder.py`:
```python
from libs.core.entities import Relation, RelationType
from libs.graph.builder import Graph


def _rel(src: str, dst: str, rt: RelationType = RelationType.IMPORTS) -> Relation:
    return Relation(
        src_type="file", src_ref=src,
        dst_type="file", dst_ref=dst,
        relation_type=rt,
    )


def test_graph_neighbors() -> None:
    g = Graph()
    g.add_relation(_rel("a.py", "b.py"))
    g.add_relation(_rel("a.py", "c.py"))
    assert set(g.neighbors("a.py")) == {"b.py", "c.py"}


def test_graph_reverse_neighbors() -> None:
    g = Graph()
    g.add_relation(_rel("a.py", "b.py"))
    g.add_relation(_rel("c.py", "b.py"))
    assert set(g.reverse_neighbors("b.py")) == {"a.py", "c.py"}


def test_graph_expand_bfs() -> None:
    g = Graph()
    g.add_relation(_rel("a.py", "b.py"))
    g.add_relation(_rel("b.py", "c.py"))
    g.add_relation(_rel("c.py", "d.py"))
    # depth 2 from a → a, b, c
    assert g.expand("a.py", depth=2) == {"a.py", "b.py", "c.py"}


def test_graph_expand_respects_direction() -> None:
    g = Graph()
    g.add_relation(_rel("a.py", "b.py"))
    g.add_relation(_rel("b.py", "c.py"))
    # reverse expansion from c depth 2 → c, b, a
    assert g.expand("c.py", depth=2, reverse=True) == {"c.py", "b.py", "a.py"}
```

- [ ] **Step 2: Run — expect fail**

Run: `uv run pytest tests/unit/graph/test_builder.py -v`

- [ ] **Step 3: Implement graph**

Create `libs/graph/__init__.py`:
```python
"""In-memory graph built from deterministic relations."""
```

Create `libs/graph/builder.py`:
```python
"""Simple directed graph with BFS expansion."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable

from libs.core.entities import Relation


class Graph:
    def __init__(self) -> None:
        self._fwd: dict[str, set[str]] = defaultdict(set)
        self._rev: dict[str, set[str]] = defaultdict(set)
        self._relation_count = 0

    def add_relation(self, rel: Relation) -> None:
        self._fwd[rel.src_ref].add(rel.dst_ref)
        self._rev[rel.dst_ref].add(rel.src_ref)
        self._relation_count += 1

    def add_relations(self, rels: Iterable[Relation]) -> None:
        for r in rels:
            self.add_relation(r)

    def neighbors(self, node: str) -> set[str]:
        return set(self._fwd.get(node, set()))

    def reverse_neighbors(self, node: str) -> set[str]:
        return set(self._rev.get(node, set()))

    def expand(self, seed: str, *, depth: int, reverse: bool = False) -> set[str]:
        adj = self._rev if reverse else self._fwd
        visited: set[str] = {seed}
        frontier: deque[tuple[str, int]] = deque([(seed, 0)])
        while frontier:
            node, d = frontier.popleft()
            if d >= depth:
                continue
            for nxt in adj.get(node, set()):
                if nxt not in visited:
                    visited.add(nxt)
                    frontier.append((nxt, d + 1))
        return visited

    def relation_count(self) -> int:
        return self._relation_count
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/graph -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add libs/graph/__init__.py libs/graph/builder.py tests/unit/graph/__init__.py tests/unit/graph/test_builder.py
git commit -m "feat(graph): directed graph with BFS expansion for deterministic relations"
```

---

## Task 1.10: libs/context_pack — navigate and edit pack assembly

**Files:**
- Create: `libs/context_pack/__init__.py`
- Create: `libs/context_pack/builder.py`
- Create: `tests/unit/context_pack/__init__.py`
- Create: `tests/unit/context_pack/test_builder.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/context_pack/__init__.py`:
```python
```

Create `tests/unit/context_pack/test_builder.py`:
```python
from libs.context_pack.builder import build_navigate_pack, build_edit_pack
from libs.core.entities import PackMode
from libs.retrieval.pipeline import RetrievalResult


def test_navigate_pack_contains_query_and_files() -> None:
    result = RetrievalResult(
        files=["app/main.py", "app/handlers/auth.py"],
        symbols=["app.main.app", "app.handlers.auth.login"],
        scores={"app/main.py": 5.0, "app/handlers/auth.py": 3.0},
    )
    pack = build_navigate_pack(
        project_slug="sample",
        query="login endpoint",
        result=result,
    )
    assert pack.mode == PackMode.NAVIGATE
    assert "login endpoint" in pack.assembled_markdown
    assert "app/main.py" in pack.assembled_markdown
    assert "app/handlers/auth.py" in pack.assembled_markdown
    assert pack.size_bytes > 0


def test_edit_pack_flags_impacted_sections() -> None:
    result = RetrievalResult(
        files=["app/handlers/auth.py", "app/services/auth.py", "tests/test_auth.py"],
        symbols=["app.handlers.auth.login"],
        scores={"app/handlers/auth.py": 8.0, "app/services/auth.py": 5.0, "tests/test_auth.py": 3.0},
    )
    pack = build_edit_pack(
        project_slug="sample",
        query="change login validation",
        result=result,
    )
    assert pack.mode == PackMode.EDIT
    md = pack.assembled_markdown
    assert "Target files" in md or "target" in md.lower()
    assert "Impacted tests" in md or "tests/test_auth.py" in md
```

- [ ] **Step 2: Run — expect fail**

Run: `uv run pytest tests/unit/context_pack -v`

- [ ] **Step 3: Implement context pack builder**

Create `libs/context_pack/__init__.py`:
```python
"""Context pack assembly — takes retrieval results, renders markdown."""
```

Create `libs/context_pack/builder.py`:
```python
"""Build NAVIGATE and EDIT context packs from retrieval results.

These are deterministic in Phase 1 — no LLM summarization. Just structured
markdown with the top files, symbols, and for EDIT mode a tests/configs split.
"""

from __future__ import annotations

from libs.core.entities import ContextPack, PackMode
from libs.retrieval.pipeline import RetrievalResult

PIPELINE_VERSION = "phase-1-v0"


def build_navigate_pack(
    *,
    project_slug: str,
    query: str,
    result: RetrievalResult,
) -> ContextPack:
    lines: list[str] = []
    lines.append(f"# Context pack — navigate")
    lines.append("")
    lines.append(f"**Project:** `{project_slug}`")
    lines.append(f"**Query:** {query}")
    lines.append(f"**Pipeline:** `{PIPELINE_VERSION}`")
    lines.append("")

    lines.append("## Top files")
    lines.append("")
    if not result.files:
        lines.append("_no files retrieved_")
    else:
        for i, path in enumerate(result.files, start=1):
            score = result.scores.get(path, 0.0)
            lines.append(f"{i}. `{path}` (score {score:.2f})")
    lines.append("")

    lines.append("## Top symbols")
    lines.append("")
    if not result.symbols:
        lines.append("_no symbols retrieved_")
    else:
        for i, fq in enumerate(result.symbols, start=1):
            lines.append(f"{i}. `{fq}`")
    lines.append("")

    md = "\n".join(lines)
    return ContextPack(
        project_slug=project_slug,
        query=query,
        mode=PackMode.NAVIGATE,
        assembled_markdown=md,
        size_bytes=len(md.encode("utf-8")),
        retrieved_files=tuple(result.files),
        retrieved_symbols=tuple(result.symbols),
        pipeline_version=PIPELINE_VERSION,
    )


def build_edit_pack(
    *,
    project_slug: str,
    query: str,
    result: RetrievalResult,
) -> ContextPack:
    # Split retrieved files into categories by path heuristics
    target_files: list[str] = []
    impacted_tests: list[str] = []
    impacted_configs: list[str] = []
    for p in result.files:
        if "/tests/" in p or p.startswith("tests/") or p.endswith("_test.py") or p.startswith("test_"):
            impacted_tests.append(p)
        elif p.endswith((".yaml", ".yml", ".json", ".toml")) or "/config/" in p:
            impacted_configs.append(p)
        else:
            target_files.append(p)

    lines: list[str] = []
    lines.append("# Context pack — edit")
    lines.append("")
    lines.append(f"**Project:** `{project_slug}`")
    lines.append(f"**Intent:** {query}")
    lines.append(f"**Pipeline:** `{PIPELINE_VERSION}`")
    lines.append("")
    lines.append(
        "> This is an **edit pack**: files grouped by role so the executor can "
        "plan a minimal, reversible patch. Run validation after every change."
    )
    lines.append("")

    lines.append("## Target files")
    lines.append("")
    if not target_files:
        lines.append("_no target files identified — re-query with more specific intent_")
    for p in target_files:
        score = result.scores.get(p, 0.0)
        lines.append(f"- `{p}` (score {score:.2f})")
    lines.append("")

    lines.append("## Impacted tests")
    lines.append("")
    if not impacted_tests:
        lines.append("_no tests directly matched — verify that target files are test-covered_")
    for p in impacted_tests:
        lines.append(f"- `{p}`")
    lines.append("")

    lines.append("## Impacted configs")
    lines.append("")
    if not impacted_configs:
        lines.append("_no config files matched_")
    for p in impacted_configs:
        lines.append(f"- `{p}`")
    lines.append("")

    lines.append("## Candidate symbols")
    lines.append("")
    if not result.symbols:
        lines.append("_no symbol candidates_")
    for fq in result.symbols:
        lines.append(f"- `{fq}`")
    lines.append("")

    lines.append("## Reminder: edit discipline (constitution §II.10)")
    lines.append("")
    lines.append("1. Build minimal plan before patching multiple files")
    lines.append("2. Never touch write_protected_paths (generated, vendor, dist, applied migrations)")
    lines.append("3. Run lint + typecheck + tests after every change")
    lines.append("4. Summarize the diff when done")

    md = "\n".join(lines)
    return ContextPack(
        project_slug=project_slug,
        query=query,
        mode=PackMode.EDIT,
        assembled_markdown=md,
        size_bytes=len(md.encode("utf-8")),
        retrieved_files=tuple(result.files),
        retrieved_symbols=tuple(result.symbols),
        pipeline_version=PIPELINE_VERSION,
    )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/context_pack -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add libs/context_pack/__init__.py libs/context_pack/builder.py tests/unit/context_pack/__init__.py tests/unit/context_pack/test_builder.py
git commit -m "feat(context-pack): navigate and edit pack assembly with role-based file split"
```

---

## Task 1.11: libs/dotcontext/writer.py — write .context/*.md artifacts

**Files:**
- Create: `libs/dotcontext/__init__.py`
- Create: `libs/dotcontext/writer.py`
- Create: `tests/unit/dotcontext/__init__.py`
- Create: `tests/unit/dotcontext/test_writer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/dotcontext/__init__.py`:
```python
```

Create `tests/unit/dotcontext/test_writer.py`:
```python
from pathlib import Path

from libs.core.entities import File, Symbol, SymbolType
from libs.dotcontext.writer import write_project_md, write_symbol_index_md


def test_write_project_md_creates_file(tmp_path: Path) -> None:
    files = [
        File(path="app/main.py", content_hash="h1", size_bytes=100, language="python", role="source"),
        File(path="tests/test_a.py", content_hash="h2", size_bytes=50, language="python", role="test"),
        File(path="docs/a.md", content_hash="h3", size_bytes=20, language="markdown", role="docs"),
    ]
    path = write_project_md(
        project_root=tmp_path,
        project_name="demo",
        files=files,
        total_symbols=12,
        total_relations=20,
    )
    assert path.exists()
    content = path.read_text()
    assert "demo" in content
    assert "python" in content
    assert "3 files" in content or "3" in content


def test_write_symbol_index_md(tmp_path: Path) -> None:
    symbols = [
        Symbol(
            name="User",
            fq_name="app.models.user.User",
            symbol_type=SymbolType.CLASS,
            file_path="app/models/user.py",
            start_line=10,
            end_line=20,
        ),
        Symbol(
            name="login",
            fq_name="app.handlers.auth.login",
            symbol_type=SymbolType.FUNCTION,
            file_path="app/handlers/auth.py",
            start_line=5,
            end_line=15,
        ),
    ]
    path = write_symbol_index_md(project_root=tmp_path, symbols=symbols)
    content = path.read_text()
    assert "User" in content
    assert "login" in content
    assert "app/models/user.py" in content
```

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Implement writer**

Create `libs/dotcontext/__init__.py`:
```python
"""Generators for .context/*.md artifacts committed with the project."""
```

Create `libs/dotcontext/writer.py`:
```python
"""Write .context/project.md and .context/symbol_index.md."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone
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
    lines.append(f"# {project_name} — LV_DCP project overview")
    lines.append("")
    lines.append(f"Generated: `{datetime.now(timezone.utc).isoformat()}`")
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
    lines.append(f"Generated: `{datetime.now(timezone.utc).isoformat()}`")
    lines.append(f"Total symbols: **{len(symbols)}**")
    lines.append("")

    for file_path in sorted(by_file.keys()):
        lines.append(f"## {file_path}")
        lines.append("")
        for s in sorted(by_file[file_path], key=lambda x: x.start_line):
            lines.append(
                f"- `{s.fq_name}` — {s.symbol_type.value} (L{s.start_line}–L{s.end_line})"
            )
        lines.append("")

    path = _dot_context(project_root) / "symbol_index.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/dotcontext -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add libs/dotcontext/__init__.py libs/dotcontext/writer.py tests/unit/dotcontext/__init__.py tests/unit/dotcontext/test_writer.py
git commit -m "feat(dotcontext): .context/project.md and .context/symbol_index.md writers"
```

---

## Task 1.12: apps/cli/main.py + commands/scan.py — `ctx scan`

**Files:**
- Create: `apps/cli/__init__.py`
- Create: `apps/cli/__main__.py`
- Create: `apps/cli/main.py`
- Create: `apps/cli/commands/__init__.py`
- Create: `apps/cli/commands/scan.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_cli_scan.py`

- [ ] **Step 1: Write failing integration test**

Create `tests/integration/__init__.py`:
```python
```

Create `tests/integration/test_cli_scan.py`:
```python
from pathlib import Path

from typer.testing import CliRunner

from apps.cli.main import app

runner = CliRunner()


def test_scan_fixture_repo(sample_repo_path: Path, tmp_path: Path) -> None:
    # Copy-free: scan in-place, write artifacts to .context/ under sample_repo
    result = runner.invoke(app, ["scan", str(sample_repo_path)])
    assert result.exit_code == 0, result.output
    assert (sample_repo_path / ".context" / "project.md").exists()
    assert (sample_repo_path / ".context" / "symbol_index.md").exists()

    index_content = (sample_repo_path / ".context" / "symbol_index.md").read_text()
    assert "User" in index_content
    assert "login" in index_content


def test_scan_reports_counts(sample_repo_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(sample_repo_path)])
    assert result.exit_code == 0
    assert "files" in result.output.lower()
    assert "symbols" in result.output.lower()
```

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Implement CLI skeleton**

Create `apps/cli/__init__.py`:
```python
"""LV_DCP command-line interface."""
```

Create `apps/cli/__main__.py`:
```python
from apps.cli.main import app

if __name__ == "__main__":
    app()
```

Create `apps/cli/main.py`:
```python
"""Typer app — wires subcommands."""

from __future__ import annotations

import typer

from apps.cli.commands import scan as scan_cmd

app = typer.Typer(
    name="ctx",
    help="LV_DCP — Developer Context Platform CLI",
    no_args_is_help=True,
)
app.command(name="scan", help="Scan a project and regenerate .context/")(scan_cmd.scan)
```

Create `apps/cli/commands/__init__.py`:
```python
```

Create `apps/cli/commands/scan.py`:
```python
"""`ctx scan <path>` — walk the project, parse, write .context/ artifacts."""

from __future__ import annotations

from pathlib import Path

import typer

from libs.core.entities import File
from libs.core.hashing import content_hash
from libs.core.paths import is_ignored, normalize_path
from libs.dotcontext.writer import write_project_md, write_symbol_index_md
from libs.parsers.registry import detect_language, get_parser
from libs.storage.sqlite_cache import SqliteCache

CACHE_REL = Path(".context") / "cache.db"


def scan(
    path: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True, resolve_path=True),
) -> None:
    """Scan a project and regenerate .context/*.md artifacts."""
    root = path
    cache = SqliteCache(root / CACHE_REL)
    cache.migrate()

    files_processed: list[File] = []
    total_symbols = 0
    total_relations = 0
    all_symbols = []

    for abs_path in _walk(root):
        try:
            rel = normalize_path(abs_path, root=root)
        except ValueError:
            continue
        if is_ignored(rel):
            continue

        try:
            data = abs_path.read_bytes()
        except OSError as exc:
            typer.echo(f"skip {rel}: {exc}", err=True)
            continue

        language = detect_language(rel)
        if language == "unknown":
            continue

        parser = get_parser(language)
        if parser is None:
            continue

        parse_result = parser.parse(file_path=rel, data=data)
        if parse_result.errors:
            for err in parse_result.errors:
                typer.echo(f"warn {rel}: {err}", err=True)

        file_entity = File(
            path=rel,
            content_hash=content_hash(data),
            size_bytes=len(data),
            language=language,
            role=parse_result.role,
        )
        cache.put_file(file_entity)
        cache.replace_symbols(file_path=rel, symbols=parse_result.symbols)
        cache.replace_relations(file_path=rel, relations=parse_result.relations)

        files_processed.append(file_entity)
        all_symbols.extend(parse_result.symbols)
        total_symbols += len(parse_result.symbols)
        total_relations += len(parse_result.relations)

    write_project_md(
        project_root=root,
        project_name=root.name,
        files=files_processed,
        total_symbols=total_symbols,
        total_relations=total_relations,
    )
    write_symbol_index_md(project_root=root, symbols=all_symbols)

    typer.echo(
        f"scanned {len(files_processed)} files, "
        f"{total_symbols} symbols, {total_relations} relations"
    )
    cache.close()


def _walk(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file():
            out.append(p)
    return out
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/integration/test_cli_scan.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run `ctx scan` on the fixture repo manually**

Run: `uv run ctx scan tests/eval/fixtures/sample_repo`
Expected: success output, `tests/eval/fixtures/sample_repo/.context/` created with `project.md`, `symbol_index.md`, `cache.db`.

Then **clean up** — these shouldn't be committed under fixture (it would pollute the eval harness):

Run:
```bash
rm -rf tests/eval/fixtures/sample_repo/.context
```

Add to `.gitignore`:
```
tests/eval/fixtures/sample_repo/.context/
```

- [ ] **Step 6: Commit**

```bash
git add apps/cli .gitignore tests/integration/__init__.py tests/integration/test_cli_scan.py
git commit -m "feat(cli): ctx scan — walk, parse, persist, write .context/"
```

---

## Task 1.13: `ctx pack` command — query → context pack markdown

**Files:**
- Create: `apps/cli/commands/pack.py`
- Create: `tests/integration/test_cli_pack.py`
- Modify: `apps/cli/main.py` (wire command)

- [ ] **Step 1: Write failing test**

Create `tests/integration/test_cli_pack.py`:
```python
from pathlib import Path

from typer.testing import CliRunner

from apps.cli.main import app

runner = CliRunner()


def test_pack_after_scan(sample_repo_path: Path) -> None:
    scan_result = runner.invoke(app, ["scan", str(sample_repo_path)])
    assert scan_result.exit_code == 0

    pack_result = runner.invoke(
        app,
        ["pack", str(sample_repo_path), "login endpoint", "--mode", "navigate"],
    )
    assert pack_result.exit_code == 0, pack_result.output
    assert "app/handlers/auth.py" in pack_result.output


def test_pack_edit_mode(sample_repo_path: Path) -> None:
    runner.invoke(app, ["scan", str(sample_repo_path)])
    result = runner.invoke(
        app,
        ["pack", str(sample_repo_path), "change login validation", "--mode", "edit"],
    )
    assert result.exit_code == 0
    assert "Target files" in result.output or "target" in result.output.lower()
```

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Implement pack command**

Create `apps/cli/commands/pack.py`:
```python
"""`ctx pack <path> <query> --mode navigate|edit` — build and print a context pack."""

from __future__ import annotations

from pathlib import Path

import typer

from libs.context_pack.builder import build_edit_pack, build_navigate_pack
from libs.core.entities import PackMode
from libs.retrieval.fts import FtsIndex
from libs.retrieval.index import SymbolIndex
from libs.retrieval.pipeline import RetrievalPipeline
from libs.storage.sqlite_cache import SqliteCache

from apps.cli.commands.scan import CACHE_REL


def pack(
    path: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True, resolve_path=True),
    query: str = typer.Argument(...),
    mode: PackMode = typer.Option(PackMode.NAVIGATE, "--mode", case_sensitive=False),
    limit: int = typer.Option(10, "--limit"),
) -> None:
    cache = SqliteCache(path / CACHE_REL)
    cache.migrate()

    fts = FtsIndex(path / ".context" / "fts.db")
    fts.create()

    # Rebuild indexes from cache (Phase 1 — no persistent FTS between runs)
    for f in cache.iter_files():
        try:
            content = (path / f.path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
        fts.index_file(f.path, f"{f.path}\n{content}")

    sym_idx = SymbolIndex()
    sym_idx.extend(list(cache.iter_symbols()))

    pipeline = RetrievalPipeline(cache=cache, fts=fts, symbols=sym_idx)
    result = pipeline.retrieve(query, mode=mode.value, limit=limit)

    if mode == PackMode.EDIT:
        pack_obj = build_edit_pack(
            project_slug=path.name, query=query, result=result,
        )
    else:
        pack_obj = build_navigate_pack(
            project_slug=path.name, query=query, result=result,
        )

    typer.echo(pack_obj.assembled_markdown)
    cache.close()
```

Modify `apps/cli/main.py` — add pack wiring. Replace the file content with:

```python
"""Typer app — wires subcommands."""

from __future__ import annotations

import typer

from apps.cli.commands import pack as pack_cmd
from apps.cli.commands import scan as scan_cmd

app = typer.Typer(
    name="ctx",
    help="LV_DCP — Developer Context Platform CLI",
    no_args_is_help=True,
)
app.command(name="scan", help="Scan a project and regenerate .context/")(scan_cmd.scan)
app.command(name="pack", help="Build a context pack from a query")(pack_cmd.pack)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/integration/test_cli_pack.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/cli/commands/pack.py apps/cli/main.py tests/integration/test_cli_pack.py
git commit -m "feat(cli): ctx pack — query to navigate/edit context pack"
```

---

## Task 1.14: `ctx inspect` command — stats about the current index

**Files:**
- Create: `apps/cli/commands/inspect.py`
- Modify: `apps/cli/main.py`
- Create: `tests/integration/test_cli_inspect.py`

- [ ] **Step 1: Write failing test**

Create `tests/integration/test_cli_inspect.py`:
```python
from pathlib import Path

from typer.testing import CliRunner

from apps.cli.main import app

runner = CliRunner()


def test_inspect_reports_stats(sample_repo_path: Path) -> None:
    runner.invoke(app, ["scan", str(sample_repo_path)])
    result = runner.invoke(app, ["inspect", str(sample_repo_path)])
    assert result.exit_code == 0
    assert "files" in result.output.lower()
    assert "symbols" in result.output.lower()
    assert "relations" in result.output.lower()
```

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Implement**

Create `apps/cli/commands/inspect.py`:
```python
"""`ctx inspect <path>` — print index stats for a scanned project."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import typer

from libs.storage.sqlite_cache import SqliteCache

from apps.cli.commands.scan import CACHE_REL


def inspect(
    path: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True, resolve_path=True),
) -> None:
    cache_path = path / CACHE_REL
    if not cache_path.exists():
        typer.echo(f"no cache at {cache_path}. Run `ctx scan {path}` first.", err=True)
        raise typer.Exit(code=1)

    cache = SqliteCache(cache_path)
    cache.migrate()

    files = list(cache.iter_files())
    symbols = list(cache.iter_symbols())
    relations = list(cache.iter_relations())

    lang_counts = Counter(f.language for f in files)
    sym_type_counts = Counter(s.symbol_type.value for s in symbols)
    rel_type_counts = Counter(r.relation_type.value for r in relations)

    typer.echo(f"project: {path.name}")
    typer.echo(f"files: {len(files)}")
    for lang, count in lang_counts.most_common():
        typer.echo(f"  {lang}: {count}")
    typer.echo(f"symbols: {len(symbols)}")
    for t, c in sym_type_counts.most_common():
        typer.echo(f"  {t}: {c}")
    typer.echo(f"relations: {len(relations)}")
    for t, c in rel_type_counts.most_common():
        typer.echo(f"  {t}: {c}")

    cache.close()
```

Modify `apps/cli/main.py` — add inspect wiring. Replace the imports and wiring with:

```python
from apps.cli.commands import inspect as inspect_cmd
from apps.cli.commands import pack as pack_cmd
from apps.cli.commands import scan as scan_cmd
```

And add:
```python
app.command(name="inspect", help="Print index stats")(inspect_cmd.inspect)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/integration/test_cli_inspect.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/cli/commands/inspect.py apps/cli/main.py tests/integration/test_cli_inspect.py
git commit -m "feat(cli): ctx inspect — print index stats from SQLite cache"
```

---

## Task 1.15: Wire the real retrieval into the eval harness

**Files:**
- Modify: `tests/eval/test_eval_harness.py`
- Create: `tests/eval/retrieval_adapter.py`
- Modify: `tests/eval/thresholds.yaml` (bump active_phase to 1)

This is the **moment of truth** — we replace `stub_retrieve` with a real pipeline and check if it clears Phase 1 thresholds.

- [ ] **Step 1: Create retrieval adapter for eval harness**

Create `tests/eval/retrieval_adapter.py`:
```python
"""Adapter: glues the eval harness to the real retrieval pipeline.

For each eval call, performs a transient scan against a temporary cache
(we don't pollute fixtures/sample_repo/.context/). This is O(repo) per call
but the fixture is tiny, so it's acceptable for the harness.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from libs.context_pack.builder import build_edit_pack, build_navigate_pack
from libs.core.entities import PackMode
from libs.core.hashing import content_hash
from libs.core.paths import is_ignored, normalize_path
from libs.parsers.registry import detect_language, get_parser
from libs.retrieval.fts import FtsIndex
from libs.retrieval.index import SymbolIndex
from libs.retrieval.pipeline import RetrievalPipeline
from libs.storage.sqlite_cache import SqliteCache
from libs.core.entities import File as FileEntity


_cached_pipeline: tuple[Path, RetrievalPipeline, SqliteCache] | None = None


def _build_pipeline_for(repo: Path) -> tuple[RetrievalPipeline, SqliteCache]:
    global _cached_pipeline
    if _cached_pipeline is not None and _cached_pipeline[0] == repo:
        return _cached_pipeline[1], _cached_pipeline[2]

    tmp = Path(tempfile.mkdtemp(prefix="lv-dcp-eval-"))
    cache = SqliteCache(tmp / "cache.db")
    cache.migrate()
    fts = FtsIndex(tmp / "fts.db")
    fts.create()
    sym_idx = SymbolIndex()

    for abs_path in repo.rglob("*"):
        if not abs_path.is_file():
            continue
        try:
            rel = normalize_path(abs_path, root=repo)
        except ValueError:
            continue
        if is_ignored(rel):
            continue
        language = detect_language(rel)
        if language == "unknown":
            continue
        parser = get_parser(language)
        if parser is None:
            continue
        try:
            data = abs_path.read_bytes()
        except OSError:
            continue
        parse_result = parser.parse(file_path=rel, data=data)

        cache.put_file(FileEntity(
            path=rel,
            content_hash=content_hash(data),
            size_bytes=len(data),
            language=language,
            role=parse_result.role,
        ))
        cache.replace_symbols(file_path=rel, symbols=parse_result.symbols)
        cache.replace_relations(file_path=rel, relations=parse_result.relations)

        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            text = ""
        fts.index_file(rel, f"{rel}\n{text}")
        sym_idx.extend(list(parse_result.symbols))

    pipeline = RetrievalPipeline(cache=cache, fts=fts, symbols=sym_idx)
    _cached_pipeline = (repo, pipeline, cache)
    return pipeline, cache


def retrieve_for_eval(query: str, mode: str, repo: Path) -> tuple[list[str], list[str]]:
    pipeline, _ = _build_pipeline_for(repo)
    result = pipeline.retrieve(query, mode=mode, limit=10)
    return result.files, result.symbols
```

- [ ] **Step 2: Wire adapter into eval harness**

Modify `tests/eval/test_eval_harness.py` — replace the `_current_retrieve` function:

```python
def _current_retrieve():
    """Phase 1+: use the real retrieval pipeline via the adapter."""
    from tests.eval.retrieval_adapter import retrieve_for_eval
    return retrieve_for_eval
```

- [ ] **Step 3: Bump active_phase to 1**

Modify `tests/eval/thresholds.yaml`:
```yaml
active_phase: 1
```

- [ ] **Step 4: Run eval harness**

Run: `uv run pytest tests/eval/test_eval_harness.py -v -m eval -s`

If it fails with metrics below threshold: **do not immediately modify thresholds**. Read the failing queries, identify which ones the pipeline misses, and improve the pipeline (usually symbol scoring or FTS query expansion) until thresholds are met. Iterate in separate commits.

If metrics pass: celebrate, then commit.

- [ ] **Step 5: Commit**

```bash
git add tests/eval/retrieval_adapter.py tests/eval/test_eval_harness.py tests/eval/thresholds.yaml
git commit -m "test(eval): wire real pipeline into harness, activate phase 1 thresholds"
```

---

## Task 1.16: Dogfood — run `ctx scan` on LV_DCP itself

**Files:**
- Create: `docs/dogfood/phase-1.md`
- Create: `tests/integration/test_dogfood.py`

- [ ] **Step 1: Write dogfood integration test**

Create `tests/integration/test_dogfood.py`:
```python
"""Run ctx scan on LV_DCP itself as the single canary project."""

from pathlib import Path

from typer.testing import CliRunner

from apps.cli.main import app

runner = CliRunner()


def test_ctx_scan_on_lv_dcp(project_root: Path) -> None:
    # Sanity: this test lives inside LV_DCP, so project_root is the repo itself
    result = runner.invoke(app, ["scan", str(project_root)])
    assert result.exit_code == 0, result.output

    dot = project_root / ".context"
    assert (dot / "project.md").exists()
    assert (dot / "symbol_index.md").exists()

    # Must contain at least some of our own code
    idx = (dot / "symbol_index.md").read_text()
    assert "libs/core" in idx or "libs" in idx
```

- [ ] **Step 2: Add .context/ to .gitignore for LV_DCP itself**

Modify `.gitignore`:
```
# LV_DCP local scan artifacts
/.context/
```

- [ ] **Step 3: Run the dogfood test**

Run: `uv run pytest tests/integration/test_dogfood.py -v`
Expected: pass. `.context/` directory created at LV_DCP root.

- [ ] **Step 4: Hand-inspect the generated files**

```bash
cat .context/project.md
head -50 .context/symbol_index.md
ls -la .context/
```

Check:
- `project.md` shows correct language breakdown (python dominant, yaml/markdown/toml/json present)
- `symbol_index.md` has the real symbols we wrote (e.g. `SqliteCache`, `PythonParser`, `FtsIndex`, `RetrievalPipeline`, `build_navigate_pack`)
- No obvious noise or missing files

- [ ] **Step 5: Write the dogfood report**

Create `docs/dogfood/phase-1.md`:
```markdown
# Phase 1 Dogfood Report — 2026-04-XX

(Fill the XX with the day this task ran.)

## Command

```bash
uv run ctx scan .
```

## Output

(Paste the stdout from the ctx scan run here.)

## .context/project.md summary

(Paste the top of .context/project.md here — file count, languages, roles.)

## Qualitative assessment

- **What worked:** (e.g. top-level symbol index matches my mental model, language
  breakdown correct, no crash)
- **What surprised:** (e.g. X was classified as generated when it shouldn't,
  Y parser missed symbols Z)
- **What's missing:** (e.g. cross-file relation density too low, no way to
  query call graph)

## Eval harness snapshot

(Paste `make eval` output here.)

## Performance snapshot

(Approximate `time uv run ctx scan .` output.)

## Decisions triggered

- (What to fix in Phase 2? What deserves an ADR update?)
```

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_dogfood.py docs/dogfood/phase-1.md .gitignore
git commit -m "test(dogfood): run ctx scan on LV_DCP itself; phase 1 dogfood report scaffold"
```

---

## Task 1.17: Performance budget verification

**Files:**
- Create: `scripts/bench_scan.py`

- [ ] **Step 1: Create a simple bench script**

Create `scripts/bench_scan.py`:
```python
"""Measure cold-scan latency of a project and check against ADR-001."""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

from apps.cli.commands.scan import scan

BUDGETS_SECONDS = {
    "initial_scan_500_files_p95": 20.0,
}


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/bench_scan.py <path>")
        return 2
    target = Path(sys.argv[1]).resolve()

    # Clear prior cache to measure cold path
    dot = target / ".context"
    if dot.exists():
        shutil.rmtree(dot)

    start = time.perf_counter()
    scan(target)
    elapsed = time.perf_counter() - start

    # Count files (approximate — walk filesystem minus ignores)
    from libs.core.paths import is_ignored, normalize_path

    file_count = 0
    for p in target.rglob("*"):
        if not p.is_file():
            continue
        try:
            rel = normalize_path(p, root=target)
        except ValueError:
            continue
        if not is_ignored(rel):
            file_count += 1

    print(f"scanned {file_count} files in {elapsed:.2f}s")

    if file_count >= 400:
        budget = BUDGETS_SECONDS["initial_scan_500_files_p95"]
        if elapsed > budget:
            print(
                f"BUDGET VIOLATION: {elapsed:.2f}s > {budget:.2f}s for ~500 files"
            )
            return 1
        else:
            print(f"within budget ({budget}s for 500 files)")
    else:
        print(f"note: {file_count} files is below 500, budget not formally checked")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run against LV_DCP and sample_repo**

```bash
uv run python scripts/bench_scan.py .
uv run python scripts/bench_scan.py tests/eval/fixtures/sample_repo
```

Record the numbers in `docs/dogfood/phase-1.md` (Performance snapshot section).

- [ ] **Step 3: If LV_DCP is under 400 files, note it**

If the file count is below 400, ADR-001 budget for 500 files isn't formally exercised — that's expected in Phase 1 because LV_DCP is small. Note this in `phase-1.md` and move on. We'll re-bench at Phase 2 when LV_DCP grows.

- [ ] **Step 4: Commit**

```bash
git add scripts/bench_scan.py docs/dogfood/phase-1.md
git commit -m "perf(phase-1): bench_scan script and phase 1 perf snapshot"
```

---

## Phase 1 checkpoint

- [ ] **Verify Phase 1 exit criteria**

Run:
```bash
make lint
make typecheck
make test
make eval
```

All four must be green. Eval harness must be passing phase-1 thresholds (`active_phase: 1` in `thresholds.yaml`).

- [ ] **Manual verification**

```bash
uv run ctx scan .
uv run ctx inspect .
uv run ctx pack . "where is the retrieval pipeline"
uv run ctx pack . "change how ctx scan handles ignored paths" --mode edit
```

Each must return useful markdown. Sanity-check with a skeptical eye — are the top results actually the right files? If not, the pipeline needs work before declaring Phase 1 done.

- [ ] **Phase 1 milestone commit**

```bash
git tag phase-1-complete
git commit --allow-empty -m "chore(phase-1): deterministic local slice complete"
```

---

# Notes on what's deliberately out of this plan

- **No LLM calls.** Phase 2 introduces summaries. Until then every step is deterministic.
- **No backend, no daemon, no Postgres, no Qdrant.** Phase 3.
- **No cross-file call graph.** Python cross-file `calls` edges require semantic analysis; Phase 2 adds `references` from explicit `from X import Y` → we can mark calls to `Y` as likely cross-file. Phase 1 only has `same_file_calls`.
- **No edit pack impact analysis beyond heuristic file-role split.** Real edit pack (graph-aware, test mapping) is Phase 4.
- **No git intelligence.** Phase 4.
- **No Obsidian sync.** Phase 6+.
- **No multi-project.** One project at a time. Phase 3 adds registry.
- **No watcher.** `ctx scan` is manual. Phase 3 adds `apps/agent` with launchd.

Every item above has a designated phase. If any creeps into Phase 0 or Phase 1 during execution, stop and re-plan with an ADR.
