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
    assert any(s.fq_name == "app.models.user.User" for s in results)


def test_tokens_match_name_case_insensitive() -> None:
    idx = SymbolIndex()
    idx.add(_sym("refresh_access_token", "app.services.auth.refresh_access_token"))
    results = idx.lookup("refresh token", limit=5)
    assert any(s.name == "refresh_access_token" for s in results)


def test_empty_query_returns_empty() -> None:
    idx = SymbolIndex()
    idx.add(_sym("x", "x"))
    assert idx.lookup("", limit=5) == []
