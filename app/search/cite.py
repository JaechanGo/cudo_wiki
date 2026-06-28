"""인용 결정론 추출 + 실존 validator (plan §6.1/§6.2).

★ LLM 미관여 — 인용은 hit 메타데이터(canonical_clause_id/canonical_authority_id)에서 결정론
추출(조번호 생성 금지). cite 는 순수 함수(authority 식별자는 §4.5 LEFT JOIN 으로 hit 에 이미
비정규화 보유). validate_citations 만 DB 로 실존 확인(인용정확도 NFR 1차 가드).
"""

from __future__ import annotations

from dataclasses import replace

from app.search.types import Citation, CitationKind, SearchHit


def cite(hits: list[SearchHit]) -> list[Citation]:
    """hits 에서 결정론 인용을 추출한다(canonical_id NULL 인 hit 만 제외, 순수)."""
    citations: list[Citation] = []
    for hit in hits:
        if hit.chunk_class == "clause":
            if hit.canonical_clause_id:
                citations.append(
                    Citation(
                        kind=CitationKind.CLAUSE,
                        canonical_id=hit.canonical_clause_id,
                        label=hit.clause_label,
                        chunk_id=hit.chunk_id,
                    )
                )
        elif hit.chunk_class == "authority_cell":
            if hit.canonical_authority_id:
                citations.append(
                    Citation(
                        kind=CitationKind.AUTHORITY,
                        canonical_id=hit.canonical_authority_id,
                        label=hit.clause_label,
                        chunk_id=hit.chunk_id,
                    )
                )
        else:  # notice_section / form / attachment_text / table → post 키
            if hit.source_post_id is not None:
                citations.append(
                    Citation(
                        kind=CitationKind.POST,
                        canonical_id=f"post#{hit.source_post_id}",
                        label=None,
                        chunk_id=hit.chunk_id,
                    )
                )
    return citations


async def validate_citations(conn, citations: list[Citation]) -> list[Citation]:
    """각 인용의 canonical_id 가 실제 현행 행에 존재하는지 SQL 로 확인해 validated 를 채운다."""
    validated: list[Citation] = []
    async with conn.cursor() as cur:
        for citation in citations:
            if citation.kind == CitationKind.CLAUSE:
                await cur.execute(
                    "SELECT 1 FROM clause WHERE canonical_clause_id = %s AND is_current",
                    (citation.canonical_id,),
                )
            elif citation.kind == CitationKind.AUTHORITY:
                await cur.execute(
                    "SELECT 1 FROM authority_matrix "
                    "WHERE canonical_authority_id = %s AND is_current",
                    (citation.canonical_id,),
                )
            else:  # POST — "post#<id>"
                post_id = int(citation.canonical_id.split("#", 1)[1])
                await cur.execute("SELECT 1 FROM post WHERE post_id = %s", (post_id,))
            row = await cur.fetchone()
            validated.append(replace(citation, validated=row is not None))
    return validated
