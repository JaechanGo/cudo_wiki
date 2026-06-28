"""verify_citations_against_hits 단위테스트 (Task009 §3 공통·태스크 요구 #3·§8.1).

B validate_citations(DB 실존)와 별개의 C 레벨 2차 가드: 인용의 chunk_id 가 실제 반환된 hit 집합에
있고 canonical_id 가 그 hit 의 canonical 과 일치하는 것만 통과. 위조/불일치 인용은 drop.
"""

from __future__ import annotations

from app.mcp.citations import verify_citations_against_hits
from app.search.types import Citation, CitationKind, SearchHit


def _hit(chunk_id, *, chunk_class="clause", canonical_clause_id=None,
         canonical_authority_id=None, source_post_id=None, clause_label=None):
    return SearchHit(
        chunk_id=chunk_id, chunk_class=chunk_class, board_id=1, body="본문",
        score=1.0, raw_score=1.0, canonical_clause_id=canonical_clause_id,
        canonical_authority_id=canonical_authority_id, clause_label=clause_label,
        source_post_id=source_post_id, clause_id=None, source_attachment_id=None,
        authority_id=None, posted_at=None, meta=None,
    )


def test_keeps_matching_clause_citation():
    hits = [_hit(10, canonical_clause_id="REG-인사-제15조", clause_label="제15조")]
    cites = [Citation(CitationKind.CLAUSE, "REG-인사-제15조", "제15조", 10)]
    out = verify_citations_against_hits(cites, hits)
    assert out == cites


def test_drops_citation_with_chunk_not_in_hits():
    hits = [_hit(10, canonical_clause_id="REG-인사-제15조")]
    cites = [Citation(CitationKind.CLAUSE, "REG-인사-제15조", "제15조", 99)]  # chunk 99 미반환
    out = verify_citations_against_hits(cites, hits)
    assert out == []


def test_drops_citation_with_mismatched_canonical():
    """chunk 는 맞지만 canonical 이 hit 메타와 불일치 → 위조 인용 drop."""
    hits = [_hit(10, canonical_clause_id="REG-인사-제15조")]
    cites = [Citation(CitationKind.CLAUSE, "REG-위조-제99조", "제99조", 10)]
    out = verify_citations_against_hits(cites, hits)
    assert out == []


def test_authority_citation_matches_authority_canonical():
    hits = [_hit(20, chunk_class="authority_cell", canonical_authority_id="AUTH-구매-001")]
    cites = [Citation(CitationKind.AUTHORITY, "AUTH-구매-001", None, 20)]
    out = verify_citations_against_hits(cites, hits)
    assert out == cites


def test_post_citation_matches_source_post():
    hits = [_hit(30, chunk_class="notice_section", source_post_id=7)]
    cites = [Citation(CitationKind.POST, "post#7", None, 30)]
    out = verify_citations_against_hits(cites, hits)
    assert out == cites


def test_post_citation_mismatch_dropped():
    hits = [_hit(30, chunk_class="notice_section", source_post_id=7)]
    cites = [Citation(CitationKind.POST, "post#999", None, 30)]
    out = verify_citations_against_hits(cites, hits)
    assert out == []


def test_citation_without_chunk_id_dropped():
    hits = [_hit(10, canonical_clause_id="X")]
    cites = [Citation(CitationKind.CLAUSE, "X", None, None)]
    out = verify_citations_against_hits(cites, hits)
    assert out == []


def test_mixed_keeps_only_valid():
    hits = [
        _hit(10, canonical_clause_id="C1"),
        _hit(20, chunk_class="authority_cell", canonical_authority_id="A1"),
    ]
    valid = Citation(CitationKind.CLAUSE, "C1", None, 10)
    forged = Citation(CitationKind.AUTHORITY, "FORGED", None, 20)
    out = verify_citations_against_hits([valid, forged], hits)
    assert out == [valid]


def test_empty_inputs():
    assert verify_citations_against_hits([], []) == []
