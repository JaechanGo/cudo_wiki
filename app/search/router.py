"""intent → 검색|집계|전결조회 라우팅 — 전체 파이프라인 (plan §7.3).

★ 운영 진입점. rerank 는 redactor 를 노출하지 않고 내부 기본값(redaction.redact)으로만 호출
(minor-1) → 비레닥션 본문의 GLM 전송 우회 불가. abstain=True 면 인용/리랭크 생략.
"""

from __future__ import annotations

from app.search.abstain import decide_abstain
from app.search.aggregate import aggregate
from app.search.cite import cite, validate_citations
from app.search.intent import classify_intent
from app.search.normalize import normalize
from app.search.rerank import rerank
from app.search.search import search
from app.search.types import QueryIntent, RouteResult


async def route(
    conn,
    query: str,
    *,
    board_ids: list[int] | None = None,
    rerank_client=None,
    do_rerank: bool = True,
) -> RouteResult:
    """질의 의도를 분류해 검색/집계 경로로 라우팅하고 통합 결과를 반환한다."""
    intent = classify_intent(normalize(query))

    if intent in (QueryIntent.AUTHORITY_LOOKUP, QueryIntent.AGGREGATE):
        agg = await aggregate(conn, query, board_ids=board_ids)
        return RouteResult(intent=intent, aggregate=agg)

    # SEARCH 경로
    sr = await search(conn, query, board_ids=board_ids)
    rr = await rerank(query, sr.hits, client=rerank_client) if do_rerank else None
    final_hits = rr.hits if rr is not None else sr.hits

    ab = decide_abstain(final_hits)
    if ab.abstained:
        return RouteResult(intent=intent, search=sr, rerank=rr, abstain=ab)

    citations = await validate_citations(conn, cite(final_hits))
    return RouteResult(
        intent=intent, search=sr, rerank=rr, citations=citations, abstain=ab
    )
