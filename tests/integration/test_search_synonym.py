"""② 동의어 — query_expand 확장 히트 (plan §9.3②, minor-7)."""

from __future__ import annotations

import pytest

from app.search.search import search

from ._seed import seed_minimal

pytestmark = pytest.mark.integration


async def test_search_synonym_expansion(aconn):
    async with aconn.transaction(force_rollback=True):
        ids = await seed_minimal(aconn)

        # "연차" → query_expand 로 "연차휴가" 본문(공지 chunk) 매칭.
        res = await search(aconn, "연차")

        assert res.strategy == "synonym_expanded"
        assert "연차휴가" in res.expanded_query
        chunk_ids = {h.chunk_id for h in res.hits}
        assert ids.notice_chunk in chunk_ids, "동의어 확장 히트 누락"
        assert all(h.raw_score > 0 for h in res.hits)  # FTS 점수 양수
        scores = [h.score for h in res.hits]
        assert scores == sorted(scores, reverse=True)
