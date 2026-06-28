"""서브시스템 B — 검색 코어 (DOMAIN-002). 공개 심볼 re-export (plan §2.1, minor-8).

공개 5함수 + intent 라우터 + 반환형 dataclass/Enum. PGroonga 렉시컬 검색(N-gram + 동의어 확장 +
mecab 병렬 + 조항ID 정확매칭), GLM 리랭크(레닥션본 전송 + BM25 폴백), 인용 결정론 + 거절 게이트,
구조화 SQL 집계, intent 분류, 평가 하네스. chunk/clause/authority_matrix 등은 read-only.
관련 FEAT: 002·004·006·008·012·021·024·028·029 (LogiCraft).
"""

from __future__ import annotations

from app.search.abstain import ABS_THRESHOLD, ABSTAIN_MESSAGE_KO, decide_abstain
from app.search.aggregate import aggregate
from app.search.amount import parse_amount
from app.search.cite import cite, validate_citations
from app.search.glm_client import GLM_MODEL, GlmClient, RerankClient
from app.search.intent import classify_intent
from app.search.normalize import extract_clause_ref, normalize
from app.search.redaction import redact
from app.search.rerank import rerank
from app.search.router import route
from app.search.search import search
from app.search.types import (
    AbstainDecision,
    AggregateResult,
    AggregateRow,
    Citation,
    CitationKind,
    QueryIntent,
    RerankResult,
    RouteResult,
    SearchHit,
    SearchResult,
)

__all__ = [
    # 공개 함수
    "search",
    "rerank",
    "cite",
    "validate_citations",
    "decide_abstain",
    "aggregate",
    "route",
    "classify_intent",
    "parse_amount",
    "normalize",
    "extract_clause_ref",
    "redact",
    # GLM client
    "GlmClient",
    "RerankClient",
    "GLM_MODEL",
    # 상수
    "ABS_THRESHOLD",
    "ABSTAIN_MESSAGE_KO",
    # 반환형
    "SearchHit",
    "SearchResult",
    "RerankResult",
    "Citation",
    "CitationKind",
    "AbstainDecision",
    "AggregateRow",
    "AggregateResult",
    "QueryIntent",
    "RouteResult",
]
