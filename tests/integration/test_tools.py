"""도구 7종 impl_* 통합테스트 (Task009 §3·§8.2 — DB 필요, 없으면 skip).

impl_* 는 (conn, identity, params) 시그니처 — MCP Context 없이 직접 호출. ACL·레닥션·거절·인용·
첨부 게이트(B-1)·집계를 검증한다. 신원·로깅 음성 케이스는 test_tools_negative.py.
"""

from __future__ import annotations

import pytest

from app.mcp.context import Identity
from app.mcp.tools import aggregate as agg_tool
from app.mcp.tools import attachment as att_tool
from app.mcp.tools import authority as auth_tool
from app.mcp.tools import board as board_tool
from app.mcp.tools import regulation as reg_tool
from app.mcp.tools import search as search_tool
from tests.integration._seed import seed_tools_corpus

pytestmark = pytest.mark.integration

STAFF = Identity(role="staff", email="u@cudo.co.kr", user_id="u1",
                 session_id="s1", raw_present=True)
ABSENT = Identity(role=None, email=None, user_id=None, session_id=None, raw_present=False)


# ── search_regulations(§3.1) ─────────────────────────────────────────────


async def test_search_returns_redacted_hits_with_source(aconn):
    async with aconn.transaction(force_rollback=True):
        await seed_tools_corpus(aconn)
        out = await search_tool.impl_search_regulations(
            aconn, STAFF, query="징계", board_ids=None, as_of=None,
            only_current=True, limit=8,
        )
        assert out.abstained is False
        assert out.hits, "검색 hit 가 있어야 함"
        # PII(계좌/이메일) 마스킹 — 비레닥션 노출 0건.
        for hit in out.hits:
            assert "110-123-456789" not in hit.snippet
            assert "hr@cudo.co.kr" not in hit.snippet
            assert hit.source.board_name == "인사규정"


async def test_search_absent_identity_fail_closed(aconn):
    async with aconn.transaction(force_rollback=True):
        await seed_tools_corpus(aconn)
        out = await search_tool.impl_search_regulations(
            aconn, ABSENT, query="징계", board_ids=None, as_of=None,
            only_current=True, limit=8,
        )
        assert out.abstained is True
        assert out.hits == []
        assert out.message_ko is not None


async def test_search_no_match_abstains(aconn):
    async with aconn.transaction(force_rollback=True):
        await seed_tools_corpus(aconn)
        out = await search_tool.impl_search_regulations(
            aconn, STAFF, query="존재하지않는규정ZZZ", board_ids=None, as_of=None,
            only_current=True, limit=8,
        )
        assert out.abstained is True
        assert out.message_ko is not None


# ── get_regulation(§3.2) ─────────────────────────────────────────────────


async def test_get_regulation_clauses_redacted(aconn):
    async with aconn.transaction(force_rollback=True):
        ids = await seed_tools_corpus(aconn)
        out = await reg_tool.impl_get_regulation(
            aconn, STAFF, regulation_id=ids.curated_reg, as_of=None,
        )
        assert out.message_ko is None
        assert out.title == "인사규정"
        labels = [c.clause_label for c in out.clauses]
        assert labels == ["제15조", "제16조"]  # order_seq 정렬
        joined = " ".join(c.text for c in out.clauses)
        assert "110-123-456789" not in joined  # 계좌 마스킹
        assert out.source is not None
        assert out.source.reg_code == "REG-인사-001"


async def test_get_regulation_board_not_allowed_denied(aconn):
    async with aconn.transaction(force_rollback=True):
        ids = await seed_tools_corpus(aconn)
        # reg_board 를 included=false 로 → 허용집합에서 빠짐.
        await aconn.execute(
            "UPDATE board SET included=false WHERE board_id=%s", (ids.reg_board,)
        )
        out = await reg_tool.impl_get_regulation(
            aconn, STAFF, regulation_id=ids.curated_reg, as_of=None,
        )
        assert out.message_ko is not None
        assert out.clauses == []


async def test_get_regulation_not_found(aconn):
    async with aconn.transaction(force_rollback=True):
        await seed_tools_corpus(aconn)
        out = await reg_tool.impl_get_regulation(
            aconn, STAFF, regulation_id=99999, as_of=None,
        )
        assert out.message_ko is not None


# ── get_attachment(§3.3, B-1) ────────────────────────────────────────────


async def test_get_attachment_text_redacted(aconn):
    async with aconn.transaction(force_rollback=True):
        ids = await seed_tools_corpus(aconn)
        out = await att_tool.impl_get_attachment(
            aconn, STAFF, attachment_id=ids.text_attachment, page_no=None,
        )
        assert out.mode == "text"
        assert out.download_url == "http://gw/file/101"
        assert out.text is not None
        assert "301-1234-5678-91" not in out.text  # 계좌 마스킹
        assert "hong@cudo.co.kr" not in out.text


async def test_get_attachment_image_noncurated_link_fallback(aconn):
    """B-1: 비큐레이션 image → base64 None + unverified + 링크폴백 + 경고."""
    async with aconn.transaction(force_rollback=True):
        ids = await seed_tools_corpus(aconn)
        out = await att_tool.impl_get_attachment(
            aconn, STAFF, attachment_id=ids.noncurated_image_attachment, page_no=None,
        )
        assert out.mode == "image"
        assert out.image_base64 is None
        assert out.unverified_image is True
        assert out.download_url == "http://gw/file/201"
        assert out.warning_ko is not None


async def test_get_attachment_image_curated_but_no_volume_link_fallback(aconn):
    """B-1: 큐레이션 통과여도 v1 볼륨 미마운트 → 링크 폴백."""
    async with aconn.transaction(force_rollback=True):
        ids = await seed_tools_corpus(aconn)
        out = await att_tool.impl_get_attachment(
            aconn, STAFF, attachment_id=ids.curated_image_attachment, page_no=1,
        )
        assert out.mode == "image"
        assert out.image_base64 is None  # 볼륨 미마운트 → 폴백
        assert out.unverified_image is True
        # OCR 텍스트는 레닥션.
        if out.ocr_text:
            assert "110-123-456789" not in out.ocr_text


# ── list_boards(§3.4) ────────────────────────────────────────────────────


async def test_list_boards_allowed_only(aconn):
    async with aconn.transaction(force_rollback=True):
        ids = await seed_tools_corpus(aconn)
        out = await board_tool.impl_list_boards(aconn, STAFF, board_class=None)
        board_ids = {b.board_id for b in out.boards}
        assert ids.reg_board in board_ids


async def test_list_boards_absent_identity_empty(aconn):
    async with aconn.transaction(force_rollback=True):
        await seed_tools_corpus(aconn)
        out = await board_tool.impl_list_boards(aconn, ABSENT, board_class=None)
        assert out.boards == []
        assert out.message_ko is not None


# ── get_approval_authority(§3.5, M-2) ────────────────────────────────────


async def test_authority_condition_note_boosted_and_redacted(aconn):
    async with aconn.transaction(force_rollback=True):
        await seed_tools_corpus(aconn)
        out = await auth_tool.impl_get_approval_authority(
            aconn, STAFF, query="비품 구매", amount=None, board_ids=None,
        )
        assert out.count >= 1
        row = next(r for r in out.rows if r.citation == "AUTH-구매-010")
        assert row.approver_role == "팀장"
        # M-2: condition_note 가 C 직접 SQL 로 부착 + 레닥션(계좌 마스킹).
        assert row.condition_note is not None
        assert "123456-78-901234" not in row.condition_note


# ── aggregate_compare(§3.6, m-4) ─────────────────────────────────────────


async def test_aggregate_compare_board_count_with_names(aconn):
    async with aconn.transaction(force_rollback=True):
        ids = await seed_tools_corpus(aconn)
        out = await agg_tool.impl_aggregate_compare(
            aconn, STAFF, query="규정 비교", board_ids=[ids.reg_board],
        )
        assert out.kind == "board_count"
        # label 이 board_id 가 아니라 보드명으로 치환.
        for row in out.rows:
            assert row.label == "인사규정"
            assert row.board_id == ids.reg_board
