"""도구 음성/엣지 + 로깅 결선 통합테스트 (Task009 §8.3 m-5 — DB 필요, 없으면 skip).

(a) 이미지 PII 경로(큐레이션+볼륨 충족 → base64 / 미충족 → 폴백) · (b) diff 직전판 부재·정상 ·
(c) base64 크기상한 폴백 · (d) GLM 다운 rerank 폴백 · (e) 로깅(query_log/acl_audit 결선).
"""

from __future__ import annotations

import pytest

from app.mcp import attachments
from app.mcp.context import Identity
from app.mcp.tools import attachment as att_tool
from app.mcp.tools import authority as auth_tool
from app.mcp.tools import diff_tool
from app.mcp.tools import regulation as reg_tool
from app.mcp.tools import search as search_tool
from tests.integration._seed import seed_tools_corpus

pytestmark = pytest.mark.integration

STAFF = Identity(role="staff", email="u@cudo.co.kr", user_id="u1",
                 session_id="s1", raw_present=True)
ABSENT = Identity(role=None, email=None, user_id=None, session_id=None, raw_present=False)


async def _scalar(conn, sql, params=()):
    cur = await conn.execute(sql, params)
    return (await cur.fetchone())[0]


# ── (a) 이미지 PII 경로 — 큐레이션 통과 + 볼륨 가용(임시파일) → base64 ────────


async def test_image_curated_volume_available_returns_base64(aconn, tmp_path):
    async with aconn.transaction(force_rollback=True):
        ids = await seed_tools_corpus(aconn)
        img = tmp_path / "page1.png"
        img.write_bytes(b"\x89PNG\r\n REAL IMAGE BYTES")
        # 큐레이션 post(curated_post) 에 image 첨부 + 실파일 image_path.
        att_id = await _scalar(
            aconn,
            "INSERT INTO attachment (post_id,file_name,mime_type,kind,storage_path,"
            "download_url,ocr_status,byte_size) "
            "VALUES (%s,'p.png','image/png','image',%s,'http://gw/file/9','done',100) "
            "RETURNING attachment_id",
            (ids.curated_post, str(img)),
        )
        await aconn.execute(
            "INSERT INTO attachment_page (attachment_id,page_no,image_path,ocr_text) "
            "VALUES (%s,1,%s,'OCR')",
            (att_id, str(img)),
        )
        out = await att_tool.impl_get_attachment(
            aconn, STAFF, attachment_id=att_id, page_no=1
        )
        assert out.mode == "image"
        assert out.image_base64 is not None  # 게이트 충족 → base64
        assert out.unverified_image is False


async def test_image_curated_volume_size_exceeded_fallback(aconn, tmp_path, monkeypatch):
    """(c) 큐레이션+볼륨이어도 크기상한 초과 → 링크 폴백."""
    async with aconn.transaction(force_rollback=True):
        ids = await seed_tools_corpus(aconn)
        img = tmp_path / "big.png"
        img.write_bytes(b"x" * 5000)
        monkeypatch.setattr(attachments, "MAX_IMAGE_BYTES", 10)
        att_id = await _scalar(
            aconn,
            "INSERT INTO attachment (post_id,file_name,mime_type,kind,storage_path,"
            "download_url,ocr_status,byte_size) "
            "VALUES (%s,'big.png','image/png','image',%s,'http://gw/file/8','done',5000) "
            "RETURNING attachment_id",
            (ids.curated_post, str(img)),
        )
        await aconn.execute(
            "INSERT INTO attachment_page (attachment_id,page_no,image_path) "
            "VALUES (%s,1,%s)",
            (att_id, str(img)),
        )
        out = await att_tool.impl_get_attachment(
            aconn, STAFF, attachment_id=att_id, page_no=1
        )
        assert out.image_base64 is None
        assert out.unverified_image is True
        assert out.download_url == "http://gw/file/8"


# ── (b) diff — 정상(added/removed/changed) + 직전판 부재(initial) ──────────


async def _seed_diff_pair(conn, board_id):
    """R0(직전) ⊃ {C1 old, C3}, R1(현행) ⊃ {C1 new(changed), C2(added)}. C3 removed."""
    r0 = await _scalar(
        conn,
        "INSERT INTO regulation (board_id,title,reg_type,is_current) "
        "VALUES (%s,'규정 v0','규정',false) RETURNING regulation_id",
        (board_id,),
    )
    r1 = await _scalar(
        conn,
        "INSERT INTO regulation (board_id,title,reg_type,supersedes_regulation_id) "
        "VALUES (%s,'규정 v1','규정',%s) RETURNING regulation_id",
        (board_id, r0),
    )
    # R0 clauses (is_current=false 로 canonical 충돌 회피).
    await conn.execute(
        "INSERT INTO clause (regulation_id,canonical_clause_id,clause_label,text,"
        "depth,order_seq,is_current) VALUES "
        "(%s,'D-제1조','제1조','옛 본문','article',1,false),"
        "(%s,'D-제3조','제3조','삭제될 조항','article',2,false)",
        (r0, r0),
    )
    # R1 clauses (is_current=true).
    await conn.execute(
        "INSERT INTO clause (regulation_id,canonical_clause_id,clause_label,text,"
        "depth,order_seq,is_current) VALUES "
        "(%s,'D-제1조','제1조','새 본문','article',1,true),"
        "(%s,'D-제2조','제2조','신규 조항','article',2,true)",
        (r1, r1),
    )
    return r0, r1


async def test_diff_normal_added_removed_changed(aconn):
    async with aconn.transaction(force_rollback=True):
        ids = await seed_tools_corpus(aconn)
        r0, r1 = await _seed_diff_pair(aconn, ids.reg_board)
        out = await diff_tool.impl_get_regulation_diff(
            aconn, STAFF, regulation_id=r1,
        )
        assert out.is_initial is False
        assert out.from_regulation_id == r0
        assert {a.canonical_clause_id for a in out.added} == {"D-제2조"}
        assert {r.canonical_clause_id for r in out.removed} == {"D-제3조"}
        assert {c.canonical_clause_id for c in out.changed} == {"D-제1조"}


async def test_diff_initial_when_no_predecessor(aconn):
    async with aconn.transaction(force_rollback=True):
        ids = await seed_tools_corpus(aconn)
        # curated_reg 는 supersedes_regulation_id NULL(최초판).
        out = await diff_tool.impl_get_regulation_diff(
            aconn, STAFF, regulation_id=ids.curated_reg,
        )
        assert out.is_initial is True
        assert out.from_regulation_id is None
        assert out.removed == []
        assert out.changed == []
        assert {a.canonical_clause_id for a in out.added} == {"REG-인사-제15조", "REG-인사-제16조"}


async def test_diff_absent_identity(aconn):
    async with aconn.transaction(force_rollback=True):
        ids = await seed_tools_corpus(aconn)
        out = await diff_tool.impl_get_regulation_diff(
            aconn, ABSENT, regulation_id=ids.curated_reg,
        )
        assert out.message_ko is not None
        assert out.added == []


# ── (d) GLM 다운 rerank 폴백 — hits 정상 + 레닥션 + reranked=false ──────────


async def test_search_rerank_fallback_keeps_hits(aconn):
    """GLM 미도달(테스트 환경) → BM25 폴백, hits 정상·스니펫 레닥션·reranked=false."""
    async with aconn.transaction(force_rollback=True):
        await seed_tools_corpus(aconn)
        out = await search_tool.impl_search_regulations(
            aconn, STAFF, query="징계", board_ids=None, as_of=None,
            only_current=True, limit=8,
        )
        assert out.abstained is False
        assert out.hits
        assert out.reranked is False  # GLM 미주입 → 폴백
        for hit in out.hits:
            assert "110-123-456789" not in hit.snippet


# ── (e) 로깅 결선 — query_log / acl_audit ────────────────────────────────


async def test_search_writes_query_log(aconn):
    async with aconn.transaction(force_rollback=True):
        await seed_tools_corpus(aconn)
        await search_tool.impl_search_regulations(
            aconn, STAFF, query="징계", board_ids=None, as_of=None,
            only_current=True, limit=8,
        )
        row = await (await aconn.execute(
            "SELECT query_text, user_email_hash, retrieval_strategy, result_count "
            "FROM query_log ORDER BY query_log_id DESC LIMIT 1"
        )).fetchone()
        assert row[0] == "징계"
        assert row[1] is not None and "@" not in row[1]  # email 해시
        assert row[2] is not None  # strategy


async def test_identity_absent_writes_acl_audit(aconn):
    async with aconn.transaction(force_rollback=True):
        await seed_tools_corpus(aconn)
        await search_tool.impl_search_regulations(
            aconn, ABSENT, query="징계", board_ids=None, as_of=None,
            only_current=True, limit=8,
        )
        row = await (await aconn.execute(
            "SELECT decision, identity_present FROM acl_audit "
            "ORDER BY acl_audit_id DESC LIMIT 1"
        )).fetchone()
        assert row[0] == "identity_absent"
        assert row[1] is False


async def test_authority_denied_board_fail_closed(aconn):
    """요청 보드가 허용집합 밖이면 집계가 전체 보드로 새지 않고 fail-closed(빈 결과)."""
    async with aconn.transaction(force_rollback=True):
        ids = await seed_tools_corpus(aconn)
        denied_board = ids.reg_board + 9999  # 존재하지 않는 보드 요청
        out = await auth_tool.impl_get_approval_authority(
            aconn, STAFF, query="비품 구매", amount=None, board_ids=[denied_board],
        )
        assert out.count == 0  # 거부 보드 → 전체 조회로 새지 않음


async def test_board_deny_writes_acl_audit(aconn):
    async with aconn.transaction(force_rollback=True):
        ids = await seed_tools_corpus(aconn)
        await aconn.execute(
            "UPDATE board SET included=false WHERE board_id=%s", (ids.reg_board,)
        )
        await reg_tool.impl_get_regulation(
            aconn, STAFF, regulation_id=ids.curated_reg, as_of=None,
        )
        row = await (await aconn.execute(
            "SELECT decision, denied_board_ids FROM acl_audit "
            "ORDER BY acl_audit_id DESC LIMIT 1"
        )).fetchone()
        assert row[0] == "deny"
        assert ids.reg_board in (row[1] or [])
