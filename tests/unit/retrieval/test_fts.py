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


def test_search_matches_snake_case_path_via_natural_language(fts: FtsIndex) -> None:
    fts.index_file("src/services/keyword_research_service.py", "body without useful terms")
    results = fts.search("keyword research service", limit=5)
    assert any(path == "src/services/keyword_research_service.py" for path, _score in results)


def test_search_splits_camel_case_query_for_path_match(fts: FtsIndex) -> None:
    fts.index_file("frontend/src/features/auth/ui/LoginForm.tsx", "body without useful terms")
    results = fts.search("LoginForm", limit=5)
    assert any(path == "frontend/src/features/auth/ui/LoginForm.tsx" for path, _score in results)
