"""audit.hash_email 단위테스트 (Task009 §5.3·§8.1).

PIPA: query_log/acl_audit 에 email 원문 저장 금지 → sha256 해시만. 정규화(공백/대소문자)로
동일 사용자가 동일 해시를 받아 분석 가능해야 한다.
"""

from __future__ import annotations

import hashlib

from app.mcp.audit import hash_email


def test_returns_sha256_hexdigest():
    out = hash_email("a@cudo.co.kr")
    assert out == hashlib.sha256(b"a@cudo.co.kr").hexdigest()
    assert len(out) == 64


def test_does_not_contain_plaintext():
    out = hash_email("hong@cudo.co.kr")
    assert "hong" not in out
    assert "@" not in out


def test_normalizes_case_and_whitespace():
    assert hash_email("  Hong@Cudo.co.kr ") == hash_email("hong@cudo.co.kr")


def test_none_or_empty_returns_none():
    assert hash_email(None) is None
    assert hash_email("") is None
    assert hash_email("   ") is None


def test_distinct_emails_distinct_hash():
    assert hash_email("a@x.com") != hash_email("b@x.com")
