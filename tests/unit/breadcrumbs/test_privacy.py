import pytest
from libs.breadcrumbs.privacy import redact


@pytest.mark.parametrize(
    "text, kind",
    [
        ("error with sk-1234567890ABCDEFGHIJ token", "openai"),
        ("stripe sk_live_abcdef1234567890ABCD failed", "stripe"),
        ("anthropic sk-ant-abcdef1234567890ABCDEF1234567890ABCDEF1234 fail", "anthropic"),
        ("github ghp_abcdefghijklmnopqrstuvwxyz0123456789 fail", "github"),
        ("slack xoxb-1234567890-abcdef-ghijklmnop fail", "slack"),
        ("aws creds AKIAIOSFODNN7EXAMPLE leak", "aws"),
        ("token eyJabcdefghij.eyJabcdefghij.abcdefghij here", "jwt"),
        ("cert -----BEGIN RSA PRIVATE KEY----- here", "private_key"),
        ("hash 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef seen", "hex64"),
        ("conn postgresql://user:pass@db:5432/mydb here", "conn_string"),
        ("CLI api_key=sk_test_1234 here", "kv_secret"),
    ],
)
def test_redacts_secret(text: str, kind: str) -> None:
    redacted = redact(text)
    assert redacted is not None
    assert f"[REDACTED:{kind}]" in redacted


def test_does_not_redact_plain_code() -> None:
    code = "def calculate_total(items): return sum(i.price for i in items)"
    assert redact(code) == code


def test_redacts_multiple_secrets_in_one_string() -> None:
    text = "AKIAIOSFODNN7EXAMPLE and ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    redacted = redact(text)
    assert redacted is not None
    assert "[REDACTED:aws]" in redacted
    assert "[REDACTED:github]" in redacted
