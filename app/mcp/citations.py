"""인용 후검증 — C 레벨 2차 가드 (Task009 §3 공통, 태스크 요구 #3).

B ``validate_citations``(DB 실존)와 **별개**: 답변에 실릴 인용의 ``chunk_id`` 가 실제 반환된
hit 집합에 있고, ``canonical_id`` 가 그 hit 의 canonical 메타와 일치하는지 후검증한다. 불일치/위조
인용은 drop + 경고 로그 → "인용 조항이 근거 청크 메타와 일치" NFR(인용정확도 ≥98%) 2차 가드. 순수.
"""

from __future__ import annotations

from app.common.logging import get_logger
from app.search.types import Citation, CitationKind, SearchHit

_logger = get_logger("app.mcp.citations")


def _hit_matches(citation: Citation, hit: SearchHit) -> bool:
    """인용의 canonical_id 가 해당 hit 의 종류별 canonical 메타와 일치하는지."""
    if citation.kind == CitationKind.CLAUSE:
        return hit.canonical_clause_id == citation.canonical_id
    if citation.kind == CitationKind.AUTHORITY:
        return hit.canonical_authority_id == citation.canonical_id
    # POST — "post#<id>"
    if hit.source_post_id is None:
        return False
    return citation.canonical_id == f"post#{hit.source_post_id}"


def verify_citations_against_hits(
    citations: list[Citation], hits: list[SearchHit]
) -> list[Citation]:
    """chunk_id 가 hit 집합에 있고 canonical 이 일치하는 인용만 통과시킨다(나머지 drop)."""
    by_chunk = {h.chunk_id: h for h in hits}
    verified: list[Citation] = []
    for citation in citations:
        hit = by_chunk.get(citation.chunk_id) if citation.chunk_id is not None else None
        if hit is not None and _hit_matches(citation, hit):
            verified.append(citation)
        else:
            _logger.warning(
                "인용 후검증 drop: kind=%s canonical=%s chunk=%s (hit 메타 불일치)",
                citation.kind, citation.canonical_id, citation.chunk_id,
            )
    return verified
