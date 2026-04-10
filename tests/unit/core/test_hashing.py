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
