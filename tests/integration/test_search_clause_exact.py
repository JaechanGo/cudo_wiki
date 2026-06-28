"""① 조항 직격 — canonical_clause_id 정확매칭 (plan §9.3①, minor-7)."""

from __future__ import annotations

import pytest

from app.search.search import search

from ._seed import CLAUSE_CANONICAL, seed_minimal

pytestmark = pytest.mark.integration


async def test_search_clause_exact(aconn):
    async with aconn.transaction(force_rollback=True):
        ids = await seed_minimal(aconn)

        res = await search(aconn, CLAUSE_CANONICAL)

        assert res.strategy == "exact_clause"
        assert res.hits, "조항 직격 히트가 없음"
        top = res.hits[0]
        assert top.chunk_id == ids.clause_chunk
        assert top.canonical_clause_id == CLAUSE_CANONICAL
        assert top.raw_score > 0                       # exact 신뢰도 상수 1.0
        scores = [h.score for h in res.hits]
        assert scores == sorted(scores, reverse=True)  # score 내림차순 정렬
