"""acl.allowed_board_ids 통합테스트 (Task009 §4.3·§4.4·§8.2 — DB 필요, 없으면 skip).

신원 존재 → 포함 보드 전체. 신원부재 → 빈(fail-closed). v1 역할 게이팅 없음.
"""

from __future__ import annotations

import pytest

from app.mcp.acl import allowed_board_ids
from app.mcp.context import Identity
from tests.integration._seed import seed_minimal

pytestmark = pytest.mark.integration


def _ident(present: bool) -> Identity:
    if present:
        return Identity(role="staff", email="a@cudo.co.kr", user_id=None,
                        session_id=None, raw_present=True)
    return Identity(role=None, email=None, user_id=None, session_id=None, raw_present=False)


async def test_present_identity_gets_included_boards(aconn):
    async with aconn.transaction(force_rollback=True):
        ids = await seed_minimal(aconn)
        allowed = await allowed_board_ids(aconn, _ident(True))
        # 시드 3보드 모두 included=true(기본) → 허용집합에 포함.
        assert ids.reg_board in allowed
        assert ids.notice_board in allowed
        assert ids.auth_board in allowed


async def test_absent_identity_fail_closed(aconn):
    async with aconn.transaction(force_rollback=True):
        await seed_minimal(aconn)
        allowed = await allowed_board_ids(aconn, _ident(False))
        assert allowed == []


async def test_excluded_board_not_allowed(aconn):
    """included=false 보드는 허용집합에서 제외(민감보드 구조적 배제 패턴)."""
    async with aconn.transaction(force_rollback=True):
        ids = await seed_minimal(aconn)
        await aconn.execute(
            "INSERT INTO board (bizbox_board_no,name,slug,board_class,"
            "default_chunk_strategy,included) "
            "VALUES (8099,'민감','seed-sensitive','etc','whole',false)"
        )
        allowed = await allowed_board_ids(aconn, _ident(True))
        excluded = await aconn.execute(
            "SELECT board_id FROM board WHERE slug='seed-sensitive'"
        )
        sensitive_id = (await excluded.fetchone())[0]
        assert sensitive_id not in allowed
        assert ids.reg_board in allowed
