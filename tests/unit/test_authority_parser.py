"""authority_parser 단위테스트 (DB 불필요 — plan §3·§7·§10, 결정론).

금액표현(이하/초과보정/이상/미만/구간) → amount_min/amount_max, action_type enum,
consulter_roles 배열, 경계 케이스(한쪽 NULL·단일값·min>max 역전 방지).
amount_band 는 DB 생성열이므로 파서는 amount_min/max 만 생성.
"""

from __future__ import annotations

import pytest

from app.ingest.authority_parser import parse_amount_expr, parse_authority_matrix

# ── parse_amount_expr ───────────────────────────────────────────────────────


def test_amount_ihha() -> None:
    """'1천만원 이하' → (None, 10_000_000) — 상한 inclusive, 하한 무한."""
    assert parse_amount_expr("1천만원 이하") == (None, 10_000_000)


def test_amount_chogwa_boundary_plus_one() -> None:
    """'초과'(exclusive) → amount_min = 경계+1 보정('[]' 범위 정합)."""
    assert parse_amount_expr("1천만원 초과") == (10_000_001, None)


def test_amount_isang() -> None:
    """'이상'(inclusive) → amount_min = 경계."""
    assert parse_amount_expr("1천만원 이상") == (10_000_000, None)


def test_amount_miman_boundary_minus_one() -> None:
    """'미만'(exclusive) → amount_max = 경계-1 보정."""
    assert parse_amount_expr("1천만원 미만") == (None, 9_999_999)


def test_amount_range_chogwa_ihha() -> None:
    """구간 '초과~이하' → (경계+1, 상한)."""
    assert parse_amount_expr("1천만원 초과 5천만원 이하") == (10_000_001, 50_000_000)


def test_amount_range_isang_miman() -> None:
    """구간 '이상~미만' → (하한, 상한-1)."""
    assert parse_amount_expr("1천만원 이상 5천만원 미만") == (10_000_000, 49_999_999)


def test_amount_range_tilde() -> None:
    """물결 구간 'A ~ B' → 양끝 inclusive (A, B)."""
    assert parse_amount_expr("1천만원 ~ 5천만원") == (10_000_000, 50_000_000)


def test_amount_single_value() -> None:
    """단일값(수식어 없음) → min==max (단일정수 '[]' 매칭)."""
    assert parse_amount_expr("1천만원") == (10_000_000, 10_000_000)


def test_amount_one_side_null_valid() -> None:
    """한쪽 NULL 은 무한경계로 유효(이하=하한 None, 이상=상한 None)."""
    assert parse_amount_expr("3억원 이하") == (None, 300_000_000)
    assert parse_amount_expr("3억원 이상") == (300_000_000, None)


def test_amount_korean_units() -> None:
    """한국어 금액 단위 파싱(억/천만/백만/만 혼합)."""
    assert parse_amount_expr("1억5천만원 이하") == (None, 150_000_000)
    assert parse_amount_expr("5백만원 이하") == (None, 5_000_000)
    assert parse_amount_expr("1000만원 이하") == (None, 10_000_000)


def test_amount_empty() -> None:
    """빈 표현 → (None, None) (금액 무관 셀)."""
    assert parse_amount_expr("") == (None, None)
    assert parse_amount_expr(None) == (None, None)


def test_amount_reversed_raises() -> None:
    """min>max 역전은 파서가 차단(런타임 int8range INSERT 실패 전)."""
    with pytest.raises(ValueError):
        parse_amount_expr("5천만원 초과 1천만원 이하")


def test_amount_chogwa_not_overlap_single_boundary() -> None:
    """'초과' 보정(min=경계+1)이 인접 단일값 경계와 겹치지 않음(§10 ④)."""
    single_min, single_max = parse_amount_expr("1천만원")
    chogwa_min, _ = parse_amount_expr("1천만원 초과")
    assert single_max == 10_000_000
    assert chogwa_min == 10_000_001
    assert chogwa_min > single_max  # 겹침 없음


# ── parse_authority_matrix ──────────────────────────────────────────────────


def _cell(**kw):
    base = {"business_item": "지출 결의", "action_type": "전결"}
    base.update(kw)
    return base


def test_matrix_action_type_valid() -> None:
    """유효 action_type enum 매핑(전결/합의/보고/협조)."""
    cells = [
        _cell(action_type="전결"),
        _cell(action_type="합의"),
        _cell(action_type="보고"),
        _cell(action_type="협조"),
    ]
    out = parse_authority_matrix(cells, regulation_id=1)
    assert [a.action_type for a in out] == ["전결", "합의", "보고", "협조"]


def test_matrix_action_type_invalid_raises() -> None:
    """enum 밖 action_type 은 차단(CHECK 위반 전 파서 가드)."""
    with pytest.raises(ValueError):
        parse_authority_matrix([_cell(action_type="결재")], regulation_id=1)


def test_matrix_consulter_roles_array() -> None:
    """consulter_roles 는 배열(tuple) 보존 → text[] 적재."""
    cells = [_cell(consulter_roles=["재무팀장", "법무팀장"])]
    out = parse_authority_matrix(cells, regulation_id=1)
    assert out[0].consulter_roles == ("재무팀장", "법무팀장")


def test_matrix_amount_expr_and_canonical() -> None:
    """셀 amount_expr 파싱 + canonical_authority_id·order_seq 생성."""
    cells = [
        _cell(business_item="A", amount_expr="1천만원 이하", order_seq=0),
        _cell(business_item="B", amount_expr="1천만원 초과 5천만원 이하", order_seq=1),
    ]
    out = parse_authority_matrix(cells, regulation_id=7)
    assert out[0].amount_min is None and out[0].amount_max == 10_000_000
    assert out[1].amount_min == 10_000_001 and out[1].amount_max == 50_000_000
    assert out[0].canonical_authority_id == "R7#auth0"
    assert out[1].canonical_authority_id == "R7#auth1"
    # canonical 유일성(partial-unique 멱등 전제).
    assert len({a.canonical_authority_id for a in out}) == 2


def test_matrix_explicit_amounts_reversed_raises() -> None:
    """셀이 직접 준 amount_min/max 역전도 차단."""
    with pytest.raises(ValueError):
        parse_authority_matrix(
            [_cell(amount_min=50_000_000, amount_max=10_000_000)], regulation_id=1
        )


def test_matrix_amount_band_left_to_db() -> None:
    """파서는 amount_min/max 만 — amount_band 속성은 만들지 않음(DB 생성열)."""
    out = parse_authority_matrix([_cell(amount_expr="1천만원 이하")], regulation_id=1)
    assert not hasattr(out[0], "amount_band")
