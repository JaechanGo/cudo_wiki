"""전결표 파서 — 금액구간·결재구분 결정론 (plan §3·§7). LLM 금지.

전결표 2D 셀 → authority_matrix 행(ParsedAuthority). 금액은 **파서가 생성**
(인용 결정론, NFR). amount_band 는 DB 생성열(``int8range(min,max,'[]')`` STORED)이므로
파서는 amount_min/amount_max 만 산출한다.

금액구간 보정(plan §3):
  이하  → (None, v)        상한 inclusive
  이상  → (v, None)        하한 inclusive
  초과  → (v+1, None)      exclusive → '[]' 정합 위해 +1
  미만  → (None, v-1)      exclusive → '[]' 정합 위해 -1
  A~B   → (A, B)           양끝 inclusive
  단일값 → (v, v)          min==max
min>max 역전은 ValueError 로 차단(런타임 int8range INSERT 실패 전).
"""

from __future__ import annotations

import re

from app.ingest.models import ParsedAuthority

_ACTION_TYPES = ("전결", "합의", "보고", "협조")  # authority_matrix.action_type CHECK

# 한국어 수사 단위.
_SMALL_UNITS = {"십": 10, "백": 100, "천": 1000}
_BIG_UNITS = {"만": 10_000, "억": 100_000_000}

# 금액 토큰(숫자+한국어 단위) + 선택적 '원' + 선택적 수식어.
_AMOUNT_RE = re.compile(
    r"([0-9,]*[0-9억만천백십][0-9억만천백십,]*)\s*원?\s*(이하|이상|초과|미만)?"
)


def _parse_korean_amount(token: str) -> int:
    """'1천만'/'1억5천만'/'1000만'/'500000' → 정수(원). 콤마 무시."""
    total = 0
    section = 0  # 현재 억/만 그룹 누적
    current = 0  # 연속 숫자 런
    for ch in token:
        if ch.isdigit():
            current = current * 10 + int(ch)
        elif ch in _SMALL_UNITS:
            section += (current or 1) * _SMALL_UNITS[ch]
            current = 0
        elif ch in _BIG_UNITS:
            section += current
            total += (section or 1) * _BIG_UNITS[ch]
            section = 0
            current = 0
        # 그 외 문자(콤마 등) 무시.
    return total + section + current


def parse_amount_expr(expr: str | None) -> tuple[int | None, int | None]:
    """금액표현 → (amount_min, amount_max). 없으면 (None, None). 역전 시 ValueError."""
    if not expr or not expr.strip():
        return (None, None)

    pairs: list[tuple[int, str | None]] = []
    for m in _AMOUNT_RE.finditer(expr):
        raw = m.group(1)
        if not any(c.isdigit() for c in raw):
            continue
        pairs.append((_parse_korean_amount(raw), m.group(2)))

    if not pairs:
        return (None, None)

    amin: int | None = None
    amax: int | None = None
    if not any(qual for _, qual in pairs):
        # 수식어 없음: 단일값 → (v, v), 다중(물결 구간) → (첫, 끝).
        if len(pairs) == 1:
            amin = amax = pairs[0][0]
        else:
            amin, amax = pairs[0][0], pairs[-1][0]
    else:
        for value, qual in pairs:
            if qual == "이하":
                amax = value
            elif qual == "미만":
                amax = value - 1
            elif qual == "이상":
                amin = value
            elif qual == "초과":
                amin = value + 1

    if amin is not None and amax is not None and amin > amax:
        raise ValueError(f"amount_min({amin}) > amount_max({amax}) in {expr!r}")
    return (amin, amax)


def parse_authority_matrix(
    cells: list[dict], regulation_id: int
) -> list[ParsedAuthority]:
    """전결표 셀 목록 → ParsedAuthority 목록.

    각 셀(dict)이 받는 키:
      business_item(필수), action_type(필수, enum), business_category, approver_role,
      consulter_roles(list), amount_expr(파싱) 또는 amount_min/amount_max(직접),
      currency, condition_note, matrix_row_label, matrix_col_label, effective_date,
      order_seq(미지정 시 인덱스).

    canonical_authority_id = ``R{rid}#auth{order_seq}`` (1차 위치 기반, 멱등 안정).
    """
    key = f"R{regulation_id}"
    out: list[ParsedAuthority] = []
    for idx, cell in enumerate(cells):
        action_type = (cell.get("action_type") or "").strip()
        if action_type not in _ACTION_TYPES:
            raise ValueError(f"invalid action_type: {action_type!r}")

        if cell.get("amount_expr") is not None:
            amin, amax = parse_amount_expr(cell["amount_expr"])
        else:
            amin = cell.get("amount_min")
            amax = cell.get("amount_max")
            if amin is not None and amax is not None and amin > amax:
                raise ValueError(f"amount_min({amin}) > amount_max({amax})")

        order_seq = cell.get("order_seq", idx)
        out.append(
            ParsedAuthority(
                canonical_authority_id=f"{key}#auth{order_seq}",
                business_item=cell["business_item"],
                action_type=action_type,
                business_category=cell.get("business_category"),
                approver_role=cell.get("approver_role"),
                consulter_roles=tuple(cell.get("consulter_roles") or ()),
                amount_min=amin,
                amount_max=amax,
                currency=cell.get("currency", "KRW"),
                condition_note=cell.get("condition_note"),
                matrix_row_label=cell.get("matrix_row_label"),
                matrix_col_label=cell.get("matrix_col_label"),
                effective_date=cell.get("effective_date"),
                order_seq=order_seq,
            )
        )
    return out
