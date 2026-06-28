"""decide_abstain 단위테스트 — 임계 판정 + 한국어 메시지 (plan §6.3)."""

from __future__ import annotations

from app.search.abstain import ABSTAIN_MESSAGE_KO, decide_abstain
from app.search.types import SearchHit


def _hit(score: float) -> SearchHit:
    return SearchHit(
        chunk_id=1, chunk_class="clause", board_id=1, body="본문",
        score=score, raw_score=score, canonical_clause_id="C#1",
        canonical_authority_id=None, clause_label="제1조", source_post_id=None,
        clause_id=1, source_attachment_id=None, authority_id=None,
        posted_at=None, meta=None,
    )


def test_empty_hits_abstains():
    d = decide_abstain([])
    assert d.abstained is True
    assert d.reason == "empty_hits"
    assert d.message_ko == ABSTAIN_MESSAGE_KO
    assert "찾지 못했습니다" in d.message_ko


def test_below_threshold_abstains():
    d = decide_abstain([_hit(0.1)], abs_threshold=0.5)
    assert d.abstained is True
    assert d.reason == "below_abs_threshold"
    assert d.message_ko == ABSTAIN_MESSAGE_KO


def test_above_threshold_passes():
    d = decide_abstain([_hit(2.0)], abs_threshold=0.5)
    assert d.abstained is False
    assert d.reason == ""
    assert d.message_ko == ""


def test_uses_top_score_of_unsorted():
    # 정렬 안 된 입력이어도 최고 score 기준.
    d = decide_abstain([_hit(0.1), _hit(3.0)], abs_threshold=1.0)
    assert d.abstained is False
