"""질의 intent 분류 — 규칙기반 키워드/패턴, 순수 함수 (plan §7.1, D-07).

LLM 분류는 R0 미채택(결정론·무네트워크). 우선순위 AUTHORITY_LOOKUP > AGGREGATE > SEARCH.
모호하면 가장 안전한 SEARCH.
"""

from __future__ import annotations

from app.search.normalize import normalize
from app.search.types import QueryIntent

# 전결권/결재 관련 — AUTHORITY_LOOKUP.
_AUTHORITY_KEYWORDS = (
    "전결권자",
    "전결권",
    "전결",
    "결재라인",
    "결재권자",
    "승인권자",
    "합의",
)

# 카운트/비교/목록 — AGGREGATE.
_AGGREGATE_KEYWORDS = (
    "몇 개",
    "몇개",
    "개수",
    "카운트",
    "비교",
    "목록",
    "총",
    "전체",
)


def classify_intent(query: str) -> QueryIntent:
    """질의 의도를 규칙기반으로 분류한다(우선순위 AUTHORITY > AGGREGATE > SEARCH)."""
    norm = normalize(query)
    if any(kw in norm for kw in _AUTHORITY_KEYWORDS):
        return QueryIntent.AUTHORITY_LOOKUP
    if any(kw in norm for kw in _AGGREGATE_KEYWORDS):
        return QueryIntent.AGGREGATE
    return QueryIntent.SEARCH
