from libs.context_pack.builder import build_edit_pack, build_navigate_pack
from libs.core.entities import PackMode
from libs.retrieval.pipeline import RetrievalResult
from libs.retrieval.trace import RetrievalTrace


def _make_trace(query: str = "q", mode: str = "navigate") -> RetrievalTrace:
    return RetrievalTrace(
        trace_id="test-trace",
        project="sample",
        query=query,
        mode=mode,
        timestamp=0.0,
    )


def test_navigate_pack_contains_query_and_files() -> None:
    result = RetrievalResult(
        files=["app/main.py", "app/handlers/auth.py"],
        symbols=["app.main.app", "app.handlers.auth.login"],
        scores={"app/main.py": 5.0, "app/handlers/auth.py": 3.0},
        trace=_make_trace("login endpoint"),
        coverage="medium",
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
        scores={
            "app/handlers/auth.py": 8.0,
            "app/services/auth.py": 5.0,
            "tests/test_auth.py": 3.0,
        },
        trace=_make_trace("change login validation", "edit"),
        coverage="high",
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


def test_navigate_pack_includes_coverage_and_trace_id() -> None:
    trace = RetrievalTrace(
        trace_id="abc-123",
        project="sample",
        query="login",
        mode="navigate",
        timestamp=0.0,
        coverage="medium",
    )
    result = RetrievalResult(
        files=["app/handlers/auth.py"],
        symbols=["app.handlers.auth.login"],
        scores={"app/handlers/auth.py": 10.0},
        trace=trace,
        coverage="medium",
    )
    pack = build_navigate_pack(
        project_slug="sample",
        query="login",
        result=result,
    )
    assert pack.trace_id == "abc-123"
    assert pack.coverage == "medium"
    assert (
        "medium" in pack.assembled_markdown.lower() or "coverage" in pack.assembled_markdown.lower()
    )


def test_edit_pack_warns_on_ambiguous_coverage() -> None:
    trace = RetrievalTrace(
        trace_id="abc",
        project="sample",
        query="refactor",
        mode="edit",
        timestamp=0.0,
        coverage="ambiguous",
    )
    result = RetrievalResult(
        files=["a.py", "b.py"],
        symbols=[],
        scores={"a.py": 5.0, "b.py": 4.5},
        trace=trace,
        coverage="ambiguous",
    )
    pack = build_edit_pack(project_slug="sample", query="refactor", result=result)
    assert pack.coverage == "ambiguous"
    # Must include a warning pointing at re-query / expand limit
    md_lower = pack.assembled_markdown.lower()
    assert "ambiguous" in md_lower or "re-query" in md_lower or "expand" in md_lower
