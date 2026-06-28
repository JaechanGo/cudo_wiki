"""audit.write_acl_audit / write_query_log 통합테스트 (Task009 §5.2·§5.3·§7.3 — DB 필요).

명시 commit 경계(m-3)·email 해시 적재·best-effort(실패가 본기능 비차단) 검증.
"""

from __future__ import annotations

import pytest

from app.mcp import audit
from app.mcp.context import Identity

pytestmark = pytest.mark.integration


def _ident():
    return Identity(role="staff", email="A@Cudo.co.kr", user_id="u1",
                    session_id="sess-1", raw_present=True)


async def test_write_acl_audit_deny_row(aconn):
    async with aconn.transaction(force_rollback=True):
        await audit.write_acl_audit(
            aconn, tool_name="search_regulations", identity=_ident(),
            decision="filtered", requested=[1, 99], allowed=[1, 2], denied=[99],
            reason="unknown_board",
        )
        row = await (await aconn.execute(
            "SELECT tool_name, user_role, user_email_hash, identity_present, decision, "
            "requested_board_ids, denied_board_ids, reason, session_id "
            "FROM acl_audit ORDER BY acl_audit_id DESC LIMIT 1"
        )).fetchone()
        assert row[0] == "search_regulations"
        assert row[1] == "staff"
        assert row[2] == audit.hash_email("A@Cudo.co.kr")  # 원문 아님
        assert "@" not in (row[2] or "")
        assert row[3] is True
        assert row[4] == "filtered"
        assert row[5] == [1, 99]
        assert row[6] == [99]
        assert row[7] == "unknown_board"
        assert row[8] == "sess-1"


async def test_write_acl_audit_identity_absent(aconn):
    absent = Identity(role=None, email=None, user_id=None, session_id=None, raw_present=False)
    async with aconn.transaction(force_rollback=True):
        await audit.write_acl_audit(
            aconn, tool_name="list_boards", identity=absent,
            decision="identity_absent", reason="no_identity",
        )
        row = await (await aconn.execute(
            "SELECT identity_present, decision, user_email_hash FROM acl_audit "
            "ORDER BY acl_audit_id DESC LIMIT 1"
        )).fetchone()
        assert row[0] is False
        assert row[1] == "identity_absent"
        assert row[2] is None  # email 없음 → 해시 None


async def test_write_query_log_row(aconn):
    async with aconn.transaction(force_rollback=True):
        await audit.write_query_log(
            aconn, query_text="연차 규정", normalized="연차 규정", identity=_ident(),
            result_count=3, zero_result=False, abstained=False, validator_passed=True,
            strategy="synonym_expanded", reranked=True,
            returned_canonical_ids=["REG-인사-제15조"], answer_citation_ids=["REG-인사-제15조"],
            top_score=0.42, latency_ms=12,
        )
        row = await (await aconn.execute(
            "SELECT query_text, user_email_hash, result_count, abstained, validator_passed, "
            "retrieval_strategy, reranked, returned_canonical_ids, answer_citation_ids, "
            "top_score, session_id FROM query_log ORDER BY query_log_id DESC LIMIT 1"
        )).fetchone()
        assert row[0] == "연차 규정"
        assert row[1] == audit.hash_email("A@Cudo.co.kr")
        assert row[2] == 3
        assert row[3] is False
        assert row[4] is True
        assert row[5] == "synonym_expanded"
        assert row[6] is True
        assert row[7] == ["REG-인사-제15조"]
        assert row[8] == ["REG-인사-제15조"]
        assert row[10] == "sess-1"


async def test_audit_write_best_effort_does_not_raise(aconn):
    """잘못된 decision(CHECK 위반)이라도 best-effort → 예외 전파 안 함(본기능 비차단)."""
    async with aconn.transaction(force_rollback=True):
        # 예외가 새어나오면 테스트 실패. best-effort 면 조용히 로그 강등.
        await audit.write_acl_audit(
            aconn, tool_name="x", identity=_ident(), decision="BOGUS_NOT_IN_ENUM",
        )
        # 후속 쿼리가 정상 동작(트랜잭션 abort 되지 않음 — savepoint 격리).
        ok = await (await aconn.execute("SELECT 1")).fetchone()
        assert ok[0] == 1
