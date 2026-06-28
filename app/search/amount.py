"""금액 파싱 — "300만원"/"3,000,000원"/"1억5천" → int (plan §9.3④, 순수 파이썬).

★ LLM 산술 절대 금지. 금액 범위 판정은 SQL(amount_band @>), 여기서는 질의 토큰만 결정론 파싱.
단위/원 표기가 없는 순수 숫자는 보수적으로 None(금액 오인 방지).
"""

from __future__ import annotations

import re

from app.search.normalize import normalize

# 소단위(만 미만)와 대단위.
_SMALL_UNITS = {"십": 10, "백": 100, "천": 1000}
_MAN = 10_000
_EOK = 100_000_000

# 금액 표현: 숫자그룹 또는 단위로 시작, 숫자/단위가 (공백 허용) 이어지고 선택적 '원'.
_MONEY_RE = re.compile(
    r"(?:[0-9][0-9,]*|[억만천백십])"
    r"(?:\s*(?:[0-9][0-9,]*|[억만천백십]))*"
    r"\s*원?"
)
_HAS_UNIT_RE = re.compile(r"[억만천백십]")
_TOKEN_RE = re.compile(r"\d+|[억만천백십]")


def _parse_korean_amount(expr: str) -> int | None:
    """정제된 금액식(쉼표/공백/원 제거 전 원문)을 int 로 환산. 실패 시 None."""
    cleaned = expr.replace(",", "").replace(" ", "").rstrip("원")
    tokens = _TOKEN_RE.findall(cleaned)
    if not tokens:
        return None

    total = 0
    man_section = 0   # 만 단위로 묶일 누적값
    num = 0           # 직전 숫자(소단위/만/억의 계수)
    saw_eok = False

    for tok in tokens:
        if tok.isdigit():
            num = int(tok)
        elif tok in _SMALL_UNITS:
            man_section += (num or 1) * _SMALL_UNITS[tok]
            num = 0
        elif tok == "만":
            man_section += num
            total += man_section * _MAN
            man_section = 0
            num = 0
        elif tok == "억":
            man_section += num
            total += man_section * _EOK
            man_section = 0
            num = 0
            saw_eok = True

    leftover = man_section + num
    if leftover:
        # "1억5천"처럼 억 뒤 소단위 꼬리에서 만이 생략된 구어체 → 만 보정.
        if saw_eok and man_section > 0 and num == 0:
            leftover *= _MAN
        total += leftover

    return total or None


def parse_amount(query: str) -> int | None:
    """질의에서 첫 금액 표현을 추출해 int 로 반환(단위/원 단서 없으면 None)."""
    norm = normalize(query)
    for m in _MONEY_RE.finditer(norm):
        expr = m.group().strip()
        if not expr:
            continue
        has_cue = bool(_HAS_UNIT_RE.search(expr)) or expr.endswith("원")
        if not has_cue:
            continue
        value = _parse_korean_amount(expr)
        if value is not None:
            return value
    return None
