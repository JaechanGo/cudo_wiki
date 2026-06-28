"""plan §10 (major #3) — partial-unique upsert vs 개정 버전교체(supersede) 경로 분리.

- 일반 upsert: 같은 canonical 재적재 → **제자리 갱신**(현행 1행, 버전 미증가).
- supersede_*: 구행 ``is_current=false`` down → 신행 **순수 INSERT**(ON CONFLICT 없음) +
  supersedes_*_id 연결 → 현행 1행 유지하되 비현행 이력 1행이 남는다.
  (authority_matrix 는 supersedes 링크 컬럼이 스키마에 없어 is_current 토글만 검증.)
"""

from __future__ import annotations

import psycopg
import pytest

from app.ingest.board_seed import BOARDS
from app.ingest.models import (
    ParsedAuthority,
    ParsedClause,
    ParsedRegulation,
    RawPost,
)

pytestmark = pytest.mark.integration

REG_BOARD_NO = 900000286


@pytest.fixture
def conn(migrated_db):
    with psycopg.connect(migrated_db["libpq"]) as c:
        yield c


def _bootstrap(conn) -> tuple[int, int, int, int]:
    """초기 1글=1규정+1조+1셀 적재. (board_id, regulation_id, clause_id, authority_id)."""
    from app.ingest.loader import (
        upsert_authority,
        upsert_board_seed,
        upsert_clauses,
        upsert_post,
        upsert_regulation,
    )

    bid = upsert_board_seed(conn, BOARDS)[REG_BOARD_NO]
    pid = upsert_post(
        conn,
        RawPost(board_no=REG_BOARD_NO, art_no=9100, title="복무규정",
                doc_type="regulation", content_hash="v1"),
        bid,
    )
    rid = upsert_regulation(conn, ParsedRegulation(title="복무규정", reg_type="규정"), bid, pid)
    upsert_clauses(conn, rid, [
        ParsedClause(canonical_clause_id=f"R{rid}#a1", clause_label="제1조", text="원본",
                     depth="article", order_seq=0, article_no=1),
    ])
    cid = conn.execute(
        "SELECT clause_id FROM clause WHERE canonical_clause_id=%s AND is_current",
        (f"R{rid}#a1",),
    ).fetchone()[0]
    upsert_authority(conn, rid, [
        ParsedAuthority(canonical_authority_id=f"R{rid}#auth0", business_item="구매",
                        action_type="전결", amount_max=10_000_000, order_seq=0),
    ])
    aid = conn.execute(
        "SELECT authority_id FROM authority_matrix WHERE canonical_authority_id=%s AND is_current",
        (f"R{rid}#auth0",),
    ).fetchone()[0]
    return bid, rid, cid, aid


def test_clause_upsert_is_inplace_not_versioned(conn) -> None:
    """같은 canonical 재upsert(텍스트 변경)는 제자리 갱신 — 현행 1행, 이력행 미생성."""
    from app.ingest.loader import upsert_clauses

    with conn.transaction(force_rollback=True):
        _, rid, cid, _ = _bootstrap(conn)
        upsert_clauses(conn, rid, [
            ParsedClause(canonical_clause_id=f"R{rid}#a1", clause_label="제1조", text="수정본",
                         depth="article", order_seq=0, article_no=1),
        ])
        rows = conn.execute(
            "SELECT clause_id, text, is_current FROM clause WHERE canonical_clause_id=%s",
            (f"R{rid}#a1",),
        ).fetchall()
        assert len(rows) == 1, "일반 upsert 가 새 버전행을 만들면 안 됨"
        assert rows[0][0] == cid and rows[0][1] == "수정본" and rows[0][2] is True


def test_supersede_regulation_versions(conn) -> None:
    from app.ingest.loader import supersede_regulation

    with conn.transaction(force_rollback=True):
        bid, rid_old, _, _ = _bootstrap(conn)
        rid_new = supersede_regulation(
            conn,
            old_regulation_id=rid_old,
            new_reg=ParsedRegulation(title="복무규정(개정)", reg_type="규정", revision_no=2),
            board_id=bid,
            source_post_id=conn.execute(
                "SELECT source_post_id FROM regulation WHERE regulation_id=%s", (rid_old,)
            ).fetchone()[0],
        )
        assert rid_new != rid_old
        old = conn.execute(
            "SELECT is_current FROM regulation WHERE regulation_id=%s", (rid_old,)
        ).fetchone()[0]
        new = conn.execute(
            "SELECT is_current, supersedes_regulation_id FROM regulation WHERE regulation_id=%s",
            (rid_new,),
        ).fetchone()
        assert old is False, "구 규정이 down(is_current=false) 되지 않음"
        assert new[0] is True, "신 규정이 현행이 아님"
        assert new[1] == rid_old, "supersedes_regulation_id 연결 누락"


def test_supersede_clause_partial_unique(conn) -> None:
    """개정 조항: down→순수 INSERT. 현행 1행 + 이력 1행, partial-unique 위반 없음."""
    from app.ingest.loader import supersede_clause

    with conn.transaction(force_rollback=True):
        _, rid, cid_old, _ = _bootstrap(conn)
        cid_new = supersede_clause(
            conn,
            old_clause_id=cid_old,
            new_clause=ParsedClause(
                canonical_clause_id=f"R{rid}#a1", clause_label="제1조", text="개정 조문",
                depth="article", order_seq=0, article_no=1,
            ),
            regulation_id=rid,
        )
        assert cid_new != cid_old
        all_rows = conn.execute(
            "SELECT clause_id, is_current, supersedes_clause_id FROM clause "
            "WHERE canonical_clause_id=%s ORDER BY clause_id", (f"R{rid}#a1",),
        ).fetchall()
        assert len(all_rows) == 2, "supersede 는 이력행을 남겨야 함(down+INSERT)"
        current = [r for r in all_rows if r[1]]
        assert len(current) == 1, "현행 clause 가 정확히 1행이어야(partial-unique)"
        assert current[0][0] == cid_new, "현행 clause 가 신행이 아님"
        assert current[0][2] == cid_old, "supersedes_clause_id 연결 누락"
        assert conn.execute(
            "SELECT is_current FROM clause WHERE clause_id=%s", (cid_old,)
        ).fetchone()[0] is False


def test_supersede_authority_toggle(conn) -> None:
    """authority 는 supersedes 링크 컬럼 부재 → is_current 토글 + 이력행만 검증."""
    from app.ingest.loader import supersede_authority

    with conn.transaction(force_rollback=True):
        _, rid, _, aid_old = _bootstrap(conn)
        aid_new = supersede_authority(
            conn,
            old_authority_id=aid_old,
            new_cell=ParsedAuthority(
                canonical_authority_id=f"R{rid}#auth0", business_item="구매",
                action_type="전결", amount_max=20_000_000, order_seq=0,
            ),
            regulation_id=rid,
        )
        assert aid_new != aid_old
        rows = conn.execute(
            "SELECT authority_id, is_current FROM authority_matrix "
            "WHERE canonical_authority_id=%s ORDER BY authority_id", (f"R{rid}#auth0",),
        ).fetchall()
        assert len(rows) == 2
        current = [r for r in rows if r[1]]
        assert len(current) == 1 and current[0][0] == aid_new
        assert conn.execute(
            "SELECT is_current FROM authority_matrix WHERE authority_id=%s", (aid_old,)
        ).fetchone()[0] is False
