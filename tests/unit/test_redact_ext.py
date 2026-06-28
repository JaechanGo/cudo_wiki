"""redact_ext.redact_pii 단위테스트 (Task009 §5.1·§8.1).

C 전용 PIPA 확장 = B.redact(4패턴) 합성 + 계좌번호. ★ 핵심 위험 = 계좌 오탐:
날짜(2024-01-01)·금액(5,000,000원)·조번호(제15조)를 마스킹하면 안 된다(음성 회귀).
"""

from __future__ import annotations

from app.mcp.redact_ext import redact_pii

# ── 계좌번호 양성(마스킹돼야 함) ──────────────────────────────────────────


def test_masks_account_three_groups():
    out = redact_pii("입금계좌 110-123-456789 로 송금")
    assert "110-123-456789" not in out
    assert "[계좌번호]" in out


def test_masks_account_kookmin_6_2_6():
    out = redact_pii("국민 123456-78-901234")
    assert "123456-78-901234" not in out
    assert "[계좌번호]" in out


def test_masks_account_four_groups():
    out = redact_pii("농협 301-1234-5678-91 입니다")
    assert "301-1234-5678-91" not in out
    assert "[계좌번호]" in out


# ── 오탐 음성(마스킹되면 안 됨) — 날짜/금액/조번호 ───────────────────────


def test_does_not_mask_iso_date():
    out = redact_pii("시행일 2024-01-01 부터 적용")
    assert "2024-01-01" in out
    assert "[계좌번호]" not in out


def test_does_not_mask_datetime():
    out = redact_pii("등록 2024-01-01 10:00 기준")
    assert "2024-01-01" in out


def test_does_not_mask_amount_with_commas():
    out = redact_pii("한도 5,000,000원 이내 전결")
    assert "5,000,000" in out
    assert "[계좌번호]" not in out


def test_does_not_mask_clause_label():
    out = redact_pii("인사규정 제15조 제2항에 따른다")
    assert "제15조" in out
    assert "제2항" in out
    assert "[계좌번호]" not in out


def test_does_not_mask_clause_range_with_hyphen():
    out = redact_pii("제15조-제20조 참조")
    assert "제15조-제20조" in out


def test_does_not_mask_short_two_group_number():
    """2그룹·짧은 숫자(코드 등)는 계좌로 보지 않음(보수적)."""
    out = redact_pii("코드 12-34 항목")
    assert "12-34" in out


# ── B 4패턴 회귀(여전히 마스킹) ──────────────────────────────────────────


def test_b_email_still_masked():
    out = redact_pii("문의: hong@cudo.co.kr")
    assert "hong@cudo.co.kr" not in out
    assert "[이메일]" in out


def test_b_rrn_still_masked():
    out = redact_pii("주민 901201-1234567 확인")
    assert "901201-1234567" not in out
    assert "[주민번호]" in out


def test_b_card_masked_not_as_account():
    """16자리 카드는 B 가 먼저 [카드]로 — 계좌 패턴이 가로채면 안 됨."""
    out = redact_pii("카드 1234-5678-9012-3456 결제")
    assert "1234-5678-9012-3456" not in out
    assert "[카드]" in out
    assert "[계좌번호]" not in out


def test_b_phone_masked_not_as_account():
    out = redact_pii("대표전화 02-1234-5678")
    assert "02-1234-5678" not in out
    assert "[전화]" in out
    assert "[계좌번호]" not in out


# ── 합성/안전 ────────────────────────────────────────────────────────────


def test_empty_and_plain_text_unchanged():
    assert redact_pii("") == ""
    assert redact_pii("일반 규정 본문입니다") == "일반 규정 본문입니다"


def test_account_and_email_both_masked():
    out = redact_pii("계좌 110-123-456789, 메일 a@b.com")
    assert "[계좌번호]" in out
    assert "[이메일]" in out
