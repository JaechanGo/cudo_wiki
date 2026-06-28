"""③ 거절 — 무근거 질의 → route abstain=True + 한국어 메시지 (plan §9.3③)."""

from __future__ import annotations

import pytest

from app.search.router import route
from app.search.types import QueryIntent

from ._seed import seed_minimal

pytestmark = pytest.mark.integration


async def test_abstain_on_no_evidence(aconn):
    async with aconn.transaction(force_rollback=True):
        await seed_minimal(aconn)

        # do_rerank=False → GLM 미접속(네트워크 0). 무근거 질의는 hits 비어 거절.
        res = await route(aconn, "존재하지않는규정XYZ", do_rerank=False)

        assert res.intent == QueryIntent.SEARCH
        assert res.abstain is not None
        assert res.abstain.abstained is True
        assert res.abstain.reason == "empty_hits"
        assert "찾지 못했습니다" in res.abstain.message_ko
        assert res.citations is None  # 거절 시 인용 생략
