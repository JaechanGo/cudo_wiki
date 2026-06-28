"""평가 하네스 — 시드 골든셋 recall/citation/abstain + 빈 골든셋 graceful (plan §9.3⑤)."""

from __future__ import annotations

import pytest

from app.search.eval import run_eval

from ._seed import seed_golden_set, seed_minimal

pytestmark = pytest.mark.integration


async def test_run_eval_on_seed_goldenset(aconn):
    async with aconn.transaction(force_rollback=True):
        ids = await seed_minimal(aconn)
        await seed_golden_set(aconn, ids)

        report = await run_eval(aconn, eval_set="seed")

        assert report.total == 3
        assert report.abstain_recall == 1.0        # 거절 대상 1건 모두 재현
        assert report.recall_at_10 is not None
        assert report.recall_at_10 > 0
        assert report.citation_accuracy is not None
        assert report.over_abstain == 0
        assert "clause" in report.per_type
        assert "authority" in report.per_type


async def test_run_eval_empty_goldenset_graceful(aconn):
    # 존재하지 않는 eval_set → 0건 graceful(지표 N/A, 예외 없음).
    report = await run_eval(aconn, eval_set="__nonexistent__")
    assert report.total == 0
    assert report.recall_at_10 is None
    assert report.abstain_recall is None
