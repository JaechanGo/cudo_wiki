"""④ 집계 — amount_band @> 3000000, approver_role + extra canonical_authority_id (plan §9.3④)."""

from __future__ import annotations

import pytest

from app.search.amount import parse_amount
from app.search.router import route
from app.search.types import QueryIntent

from ._seed import AUTHORITY_CANONICAL, seed_minimal

pytestmark = pytest.mark.integration


def test_parse_amount_unit_smoke():
    # 산술은 순수 파이썬(LLM 금지). 금액 토큰 단위 환산 병행 검증.
    assert parse_amount("300만원") == 3_000_000


async def test_aggregate_approval_line(aconn):
    async with aconn.transaction(force_rollback=True):
        await seed_minimal(aconn)

        res = await route(aconn, "300만원 결재라인", do_rerank=False)

        assert res.intent == QueryIntent.AUTHORITY_LOOKUP
        assert res.aggregate is not None
        agg = res.aggregate
        assert agg.kind == "approval_line"
        assert agg.count >= 1
        row = agg.rows[0]
        # major-2: 결정론 인용 식별자가 extra 로 전달되어야 함.
        assert row.extra["canonical_authority_id"] == AUTHORITY_CANONICAL
        assert row.extra["regulation_id"] is not None
        assert row.value == "팀장"  # approver_role
