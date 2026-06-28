"""classify_intent 단위테스트 — 규칙기반 키워드 분류 (DB 불필요)."""

from __future__ import annotations

import pytest

from app.search.intent import classify_intent
from app.search.types import QueryIntent


@pytest.mark.parametrize(
    "query",
    ["구매 전결권자 누구야", "3백만원 결재라인", "이 건의 전결권은", "합의 부서 알려줘"],
)
def test_authority_lookup(query):
    assert classify_intent(query) == QueryIntent.AUTHORITY_LOOKUP


@pytest.mark.parametrize(
    "query",
    ["규정이 몇 개야", "전체 규정 개수", "보드별 규정 카운트", "규정 목록 비교"],
)
def test_aggregate(query):
    assert classify_intent(query) == QueryIntent.AGGREGATE


@pytest.mark.parametrize(
    "query",
    ["연차 휴가 며칠", "출장비 규정", "제15조 내용"],
)
def test_search_default(query):
    assert classify_intent(query) == QueryIntent.SEARCH


def test_authority_outranks_aggregate():
    # 전결 키워드가 집계 키워드보다 우세(AUTHORITY > AGGREGATE).
    assert classify_intent("전결권자 몇 명") == QueryIntent.AUTHORITY_LOOKUP
