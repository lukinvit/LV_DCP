from pathlib import Path

from libs.core.entities import File, Symbol, SymbolType
from libs.dotcontext.writer import write_project_md, write_symbol_index_md


def test_write_project_md_creates_file(tmp_path: Path) -> None:
    files = [
        File(
            path="app/main.py",
            content_hash="h1",
            size_bytes=100,
            language="python",
            role="source",
        ),
        File(
            path="tests/test_a.py",
            content_hash="h2",
            size_bytes=50,
            language="python",
            role="test",
        ),
        File(
            path="docs/a.md",
            content_hash="h3",
            size_bytes=20,
            language="markdown",
            role="docs",
        ),
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
