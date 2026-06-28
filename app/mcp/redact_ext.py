"""PIPA 확장 레닥션 — B.redact(4패턴) 합성 + 계좌번호 (Task009 plan §5.1).

★ B 수정 금지 → C 가 합성한다: B.redact(이메일/주민/카드/전화) 먼저 통과시킨 뒤 계좌번호를 추가
마스킹. 사용자에게 나가는 모든 본문 텍스트(스니펫·조항·추출텍스트·OCR·condition_note)는 이
``redact_pii`` 를 통과한다(§3 공통).

★ 계좌 오탐 위험(§5.1): 한국 계좌는 은행별 가변(``\\d{2,6}-\\d{2,6}-\\d{2,6}`` 류). 단순 패턴은
ISO 날짜(2024-01-01)·금액·조번호를 오마스킹할 수 있어 **보수적 규칙**:
  (a) 하이픈으로 구분된 **3그룹 이상**, 각 그룹 2~6자리 숫자,
  (b) **총 숫자 ≥ 9자리** (날짜 8자리 yyyy-mm-dd 를 자연 배제),
  (c) 카드/주민/전화는 B 가 먼저 치환하므로 계좌 패턴이 가로채지 않음(순서 의존).
조번호("제15조")·금액("5,000,000원")은 하이픈 3그룹 형태가 아니라 구조적으로 매칭 불가.
실첨부 텍스트 확보 후 추가 튜닝 + 오탐 회귀 테스트로 수렴(§9-5).
"""

from __future__ import annotations

import re

from app.search import redaction

# 하이픈 3그룹+ 숫자열(각 그룹 2~6자리). 마스킹 여부는 _mask_account 가 총자릿수로 최종 판정.
_ACCOUNT_CANDIDATE = re.compile(r"(?<![\d-])\d{2,6}(?:-\d{2,6}){2,}(?![\d-])")

# 계좌로 인정하는 최소 총 숫자 자릿수(날짜 yyyymmdd=8 을 배제하기 위해 9).
_ACCOUNT_MIN_DIGITS = 9

_ACCOUNT_TOKEN = "[계좌번호]"


def _mask_account(match: re.Match[str]) -> str:
    """후보 문자열이 충분한 자릿수(≥9)면 계좌로 마스킹, 아니면(날짜 등) 원문 보존."""
    raw = match.group()
    digit_count = sum(c.isdigit() for c in raw)
    if digit_count < _ACCOUNT_MIN_DIGITS:
        return raw
    return _ACCOUNT_TOKEN


def redact_pii(text: str) -> str:
    """B 4패턴(이메일/주민/카드/전화) 후 계좌번호를 추가 마스킹한다(PIPA 확장, 순수 함수)."""
    masked = redaction.redact(text)
    return _ACCOUNT_CANDIDATE.sub(_mask_account, masked)
