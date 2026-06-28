"""plan §10 (선택) — enum/CHECK 회귀: 잘못된 doc_type/action_type/depth → CHECK 위반.

loader 가 dataclass 값을 그대로 적재하므로, DB CHECK enum 이 잘못된 값을 막는지(=loader→DB
가드) 확인한다. 각 위반은 독립 트랜잭션(force_rollback)에서 검증.
"""

from __future__ import annotations

import psycopg
import pytest

from app.ingest.board_seed import BOARDS
from app.ingest.models import ParsedAuthority, ParsedClause, ParsedRegulation, RawPost

pytestmark = pytest.mark.integration

REG_BOARD_NO = 1401000286


@pytest.fixture
def conn(migrated_db):
    with psycopg.connect(migrated_db["libpq"]) as c:
        yield c


def test_bad_doc_type_rejected(conn) -> None:
    from app.ingest.loader import upsert_board_seed, upsert_post

    with conn.transaction(force_rollback=True):
        bid = upsert_board_seed(conn, BOARDS)[REG_BOARD_NO]
        with pytest.raises(psycopg.errors.CheckViolation):
            upsert_post(
                conn,
                RawPost(board_no=REG_BOARD_NO, art_no=1, title="x", doc_type="INVALID"),
                bid,
            )


def test_bad_depth_rejected(conn) -> None:
    from app.ingest.loader import (
        upsert_board_seed,
        upsert_clauses,
        upsert_post,
        upsert_regulation,
    )

    with conn.transaction(force_rollback=True):
        bid = upsert_board_seed(conn, BOARDS)[REG_BOARD_NO]
        pid = upsert_post(
            conn, RawPost(board_no=REG_BOARD_NO, art_no=2, title="규정", doc_type="regulation"), bid
        )
        rid = upsert_regulation(conn, ParsedRegulation(title="규정", reg_type="규정"), bid, pid)
        with pytest.raises(psycopg.errors.CheckViolation):
            upsert_clauses(conn, rid, [
                ParsedClause(canonical_clause_id=f"R{rid}#a1", clause_label="제1조", text="t",
                             depth="paragraphs", order_seq=0),  # 잘못된 depth
            ])


def test_bad_action_type_rejected(conn) -> None:
    from app.ingest.loader import (
        upsert_authority,
        upsert_board_seed,
        upsert_post,
        upsert_regulation,
    )

    with conn.transaction(force_rollback=True):
        bid = upsert_board_seed(conn, BOARDS)[REG_BOARD_NO]
        pid = upsert_post(
            conn, RawPost(board_no=REG_BOARD_NO, art_no=3, title="규정", doc_type="regulation"), bid
        )
        rid = upsert_regulation(conn, ParsedRegulation(title="규정", reg_type="규정"), bid, pid)
        with pytest.raises(psycopg.errors.CheckViolation):
            upsert_authority(conn, rid, [
                ParsedAuthority(canonical_authority_id=f"R{rid}#auth0", business_item="구매",
                                action_type="결재", order_seq=0),  # 잘못된 action_type
            ])
