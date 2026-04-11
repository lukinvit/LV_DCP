from libs.core.secrets import contains_secret_pattern


def test_aws_access_key_detected() -> None:
    # Build pattern at runtime to avoid self-flagging the test file.
    pattern = b"AKIA" + b"I" + b"OSFODNN7EXAMPLE"
    assert contains_secret_pattern(pattern)


def test_openai_key_detected() -> None:
    # Build pattern at runtime to avoid self-flagging the test file.
    pattern = b"sk" + b"-" + b"proj-abc123def456ghi789jkl012mno345pqr"
    assert contains_secret_pattern(pattern)


def test_stripe_live_key_detected() -> None:
    # Build the test pattern at runtime so the source file itself never
    # contains a literal `sk_live_...` string. This avoids GitHub secret
    # scanning false-positives on our own repository.
    pattern = b"sk_" + b"live_" + b"X" * 30
    assert contains_secret_pattern(pattern)


def test_jwt_detected() -> None:
    # Build JWT header at runtime so this source file never contains a literal
    # token. JWT tokens are base64(JSON) starting with "eyJ". Split aggressively
    # to avoid any contiguous "eyJ" substring in source.
    token = (
        b"e" + b"y" + b"J" +
        b"hbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." +
        b"e" + b"y" + b"J" +
        b"zdWIiOiIxMjM0NTY3ODkwIn0.abc"
    )
    assert contains_secret_pattern(token)


def test_normal_code_not_flagged() -> None:
    assert not contains_secret_pattern(
        b"def hash_password(password: str) -> str:\n    return hashlib.sha256(...)\n"
    )


def test_uuid_not_flagged() -> None:
    assert not contains_secret_pattern(b"id = 'f47ac10b-58cc-4372-a567-0e02b2c3d479'")


def test_git_commit_hash_not_flagged() -> None:
    assert not contains_secret_pattern(b"git checkout 3a5f32e8313d2eb4359787431021720d36d824b8")


def test_empty_bytes_not_flagged() -> None:
    assert not contains_secret_pattern(b"")
