"""검색 코어 반환형 — frozen dataclass / Enum (plan §3.1).

모든 공개 함수의 입출력 계약. 사용자 노출 텍스트는 한국어이나 코드 식별자/enum 값은 영문.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime  # search(as_of)/aggregate 시그니처는 date 를 별도 import
from enum import StrEnum


class QueryIntent(StrEnum):
    """질의 의도 분류 결과 (intent.classify_intent)."""

    SEARCH = "search"               # 일반 규정/공지 검색
    AUTHORITY_LOOKUP = "authority"  # 전결권자/결재라인 조회
    AGGREGATE = "aggregate"         # 카운트/비교 집계


class CitationKind(StrEnum):
    """인용 종류 (cite)."""

    CLAUSE = "clause"
    AUTHORITY = "authority"
    POST = "post"


@dataclass(frozen=True)
class SearchHit:
    """검색 후보 1건. chunk 행 + 비정규화 인용 식별자(major-1)."""

    chunk_id: int
    chunk_class: str  # clause/notice_section/authority_cell/table/attachment_text/form
    board_id: int
    body: str
    score: float                    # 합성 스코어(raw_score * recency 가중)
    raw_score: float                # pgroonga_score 원본(폴백/디버그용)
    canonical_clause_id: str | None
    # §4.5 LEFT JOIN authority_matrix 비정규화(비-authority hit 은 NULL, major-1).
    canonical_authority_id: str | None
    clause_label: str | None
    source_post_id: int | None
    clause_id: int | None
    source_attachment_id: int | None
    authority_id: int | None
    posted_at: datetime | None
    meta: dict | None


@dataclass(frozen=True)
class SearchResult:
    """search() 반환 — 후보 top-N + 검색 전략 메타."""

    query: str
    normalized_query: str
    strategy: str  # ngram | ngram+mecab | exact_clause | synonym_expanded (조합 "+")
    expanded_query: str             # 실제 &@~ 에 들어간 PGroonga 질의(query_expand 결과)
    hits: list[SearchHit]
    top_score: float                # hits 비면 0.0


@dataclass(frozen=True)
class RerankResult:
    """rerank() 반환 — 재정렬 결과 + 폴백 여부."""

    hits: list[SearchHit]           # 재정렬(또는 폴백 시 입력 순서 유지)
    reranked: bool                  # True=GLM 적용, False=BM25 폴백
    fallback_reason: str | None     # 폴백 사유(타임아웃/연결실패/non-200/파싱실패) — 없으면 None


@dataclass(frozen=True)
class Citation:
    """결정론 인용 1건 (cite). canonical_id 는 항상 채워진 str."""

    kind: CitationKind
    canonical_id: str               # canonical_clause_id 또는 canonical_authority_id
    label: str | None               # clause_label 등 표시용
    chunk_id: int | None
    validated: bool = False         # validate_citations 통과 여부


@dataclass(frozen=True)
class AbstainDecision:
    """거절 게이트 판정 (abstain.decide_abstain)."""

    abstained: bool
    reason: str                     # 코드용 영문 사유("below_abs_threshold"/"empty_hits"/...)
    message_ko: str                 # 사용자 노출 한국어("" if not abstained)


@dataclass(frozen=True)
class AggregateRow:
    """집계 결과 1행. extra 에 결정론 인용 식별자(major-2)."""

    label: str
    value: str | int | None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AggregateResult:
    """aggregate() 반환 — 구조화 SQL 집계."""

    kind: str                       # "approver"/"approval_line"/"board_count"/...
    rows: list[AggregateRow]
    count: int


@dataclass(frozen=True)
class RouteResult:
    """route() 반환 — intent 별 채워지는 통합 결과."""

    intent: QueryIntent
    search: SearchResult | None = None
    rerank: RerankResult | None = None
    citations: list[Citation] | None = None
    abstain: AbstainDecision | None = None
    aggregate: AggregateResult | None = None
