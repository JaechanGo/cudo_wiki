"""redact 단위테스트 — PII 마스킹 + 원본 부분문자열 부재 불변식 (plan §5.3)."""

from __future__ import annotations

from app.search.redaction import redact


def test_email_masked():
    assert redact("문의는 hong@cudo.co.kr 로") == "문의는 [이메일] 로"


def test_resident_number_masked():
    out = redact("주민번호 900101-1234567 입니다")
    assert "[주민번호]" in out
    assert "900101-1234567" not in out


def test_phone_masked():
    out = redact("연락처 010-1234-5678")
    assert "[전화]" in out
    assert "010-1234-5678" not in out


def test_card_masked():
    out = redact("카드 1234-5678-9012-3456 결제")
    assert "[카드]" in out
    assert "1234-5678-9012-3456" not in out


def test_no_pii_unchanged():
    text = "연차휴가는 연 15일 부여된다"
    assert redact(text) == text


def test_invariant_no_original_pii_substring():
    """레닥션 후 원본 PII 부분문자열이 결과에 남지 않음(불변식)."""
    pii = ["hong@cudo.co.kr", "900101-1234567", "010-9876-5432", "1111-2222-3333-4444"]
    text = "정보: " + ", ".join(pii)
    out = redact(text)
    for token in pii:
        assert token not in out
