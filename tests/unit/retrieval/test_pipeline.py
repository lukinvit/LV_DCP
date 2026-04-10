from pathlib import Path

import pytest
from libs.core.entities import File, Symbol, SymbolType
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

    cache.put_file(
        File(
            path="app/models/user.py",
            content_hash="h1",
            size_bytes=100,
            language="python",
            role="source",
        )
    )
    cache.put_file(
        File(
            path="app/handlers/auth.py",
            content_hash="h2",
            size_bytes=200,
            language="python",
            role="source",
        )
    )
    fts.index_file("app/models/user.py", "class User email password")
    fts.index_file("app/handlers/auth.py", "login logout refresh authentication")

    sym_idx.add(
        Symbol(
            name="User",
            fq_name="app.models.user.User",
            symbol_type=SymbolType.CLASS,
            file_path="app/models/user.py",
            start_line=1,
            end_line=10,
        )
    )
    sym_idx.add(
        Symbol(
            name="login",
            fq_name="app.handlers.auth.login",
            symbol_type=SymbolType.FUNCTION,
            file_path="app/handlers/auth.py",
            start_line=5,
            end_line=15,
        )
    )

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
