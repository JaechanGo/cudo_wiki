"""parse_amount 경계 단위테스트 (plan §9.3④ minor-6) — 산술은 순수 파이썬, LLM 금지."""

from __future__ import annotations

import pytest

from app.search.amount import parse_amount


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("300만원", 3_000_000),
        ("3,000,000원", 3_000_000),
        ("3백만", 3_000_000),
        ("1억", 100_000_000),
        ("1억5천", 150_000_000),
        ("1억5천만원", 150_000_000),
        ("500만원 결재라인 알려줘", 5_000_000),
        ("십만원", 100_000),
    ],
)
def test_parse_amount_boundaries(query, expected):
    assert parse_amount(query) == expected


# 마지막 "3000000": 단위/원 없는 순수숫자 → None(보수적, 금액 오인 방지).
@pytest.mark.parametrize("query", ["결재라인 알려줘", "전결권자 누구", "", "3000000"])
def test_parse_amount_none(query):
    assert parse_amount(query) is None
