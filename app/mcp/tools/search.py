"""search_regulations — 규정/공지 검색 (Task009 plan §3.1).

route()의 SEARCH 분기를 C 가 재조립(리랭크 client·로깅·레닥션 제어): search → rerank(client=None
→ 내부 GlmClient, 미도달 시 BM25 폴백) → decide_abstain → cite → validate → C 후검증 → 레닥션 스니펫
+ 결정론 출처. query_log 1행 적재.
"""

from __future__ import annotations

import time
from datetime import date

from mcp.server.fastmcp import Context, FastMCP

from app.common.db import get_pool
from app.mcp import audit
from app.mcp.acl import video_board_ids
from app.mcp.citations import verify_citations_against_hits
from app.mcp.context import Identity, resolve_identity
from app.mcp.redact_ext import redact_pii
from app.mcp.schemas import CitationOut, HitOut, SearchToolOut
from app.mcp.sources import build_source
from app.mcp.tools._guard import ABSENT_MESSAGE_KO, gate_boards
from app.search import cite, decide_abstain, rerank, search, validate_citations
from app.search.types import Citation


def _citation_out(citation: Citation) -> CitationOut:
    return CitationOut(
        kind=citation.kind.value,
        canonical_id=citation.canonical_id,
        label=citation.label,
        chunk_id=citation.chunk_id,
        validated=citation.validated,
    )


def _returned_canonical_ids(hits) -> list[str]:
    """반환 hit 의 결정론 canonical 식별자(clause/authority) 수집(로깅용)."""
    ids: list[str] = []
    for hit in hits:
        cid = hit.canonical_clause_id or hit.canonical_authority_id
        if cid:
            ids.append(cid)
    return ids


async def impl_search_regulations(
    conn,
    identity: Identity,
    *,
    query: str,
    board_ids: list[int] | None,
    as_of: date | None,
    only_current: bool,
    limit: int,
) -> SearchToolOut:
    """검색 도구 본체 — ACL·레닥션·거절·2단 인용검증·로깅(Context 비의존)."""
    started = time.monotonic()
    grant = await gate_boards(
        conn, identity, tool_name="search_regulations", requested=board_ids
    )
    if grant is None:
        return SearchToolOut(abstained=True, message_ko=ABSENT_MESSAGE_KO)

    # 영상 보드 제외 — 규정/일반 검색에 지식뱅크 영상이 섞이지 않게(recommend_videos 전용).
    # board_ids=None(허용 전체)일 때도 effective_boards 는 allowed 전체 list 라 영상이 새어든다.
    video_ids = set(await video_board_ids(conn))
    effective = [b for b in grant.effective_boards if b not in video_ids]

    sr = await search(
        conn, query, board_ids=effective,
        only_current=only_current, as_of=as_of, limit=limit,
    )
    rr = await rerank(query, sr.hits, client=None)
    final = rr.hits if rr.hits else sr.hits

    ab = decide_abstain(final)
    if ab.abstained:
        await audit.write_query_log(
            conn, query_text=query, normalized=sr.normalized_query, identity=identity,
            result_count=0, zero_result=True, abstained=True, validator_passed=None,
            strategy=sr.strategy, reranked=rr.reranked, returned_canonical_ids=[],
            answer_citation_ids=[], top_score=sr.top_score,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        return SearchToolOut(
            abstained=True, message_ko=ab.message_ko,
            strategy=sr.strategy, reranked=rr.reranked,
        )

    validated = await validate_citations(conn, cite(final))
    verified = verify_citations_against_hits(validated, final)
    by_chunk = {c.chunk_id: c for c in verified}

    hits_out: list[HitOut] = []
    for hit in final:
        citation = by_chunk.get(hit.chunk_id)
        hits_out.append(
            HitOut(
                snippet=redact_pii(hit.body),
                score=hit.score,
                source=await build_source(conn, hit=hit),
                citation=_citation_out(citation) if citation else None,
            )
        )
    citations_out = [_citation_out(c) for c in verified]

    await audit.write_query_log(
        conn, query_text=query, normalized=sr.normalized_query, identity=identity,
        result_count=len(hits_out), zero_result=False, abstained=False,
        validator_passed=all(c.validated for c in verified) if verified else None,
        strategy=sr.strategy, reranked=rr.reranked,
        returned_canonical_ids=_returned_canonical_ids(final),
        answer_citation_ids=[c.canonical_id for c in verified],
        top_score=sr.top_score,
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    return SearchToolOut(
        abstained=False, message_ko=None, strategy=sr.strategy,
        reranked=rr.reranked, hits=hits_out, citations=citations_out,
    )


def register_search(mcp: FastMCP) -> None:
    """search_regulations 도구 등록(얇은 핸들러 — 헤더 신원 + 풀 conn + impl 위임)."""

    @mcp.tool()
    async def search_regulations(
        query: str,
        ctx: Context,
        board_ids: list[int] | None = None,
        as_of: date | None = None,
        only_current: bool = True,
        limit: int = 8,
    ) -> SearchToolOut:
        """CUDO 사내 정보(규정·전결·공지·매뉴얼·경비/정산·복지·수당·휴가·일정/마감·신청절차·양식 등)를 검색해 근거 인용과 함께 반환한다. 사내 업무 질문의 기본 진입점 — 웹 검색 대신 이 도구를 사용한다(근거 없으면 기권)."""
        identity = resolve_identity(ctx)
        async with get_pool().connection() as conn:
            return await impl_search_regulations(
                conn, identity, query=query, board_ids=board_ids,
                as_of=as_of, only_current=only_current, limit=limit,
            )
