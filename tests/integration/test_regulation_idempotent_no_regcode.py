"""★ plan §10 rev2 (major #2 회귀 안전망) — reg_code=NULL 규정 멱등 사슬.

reg_code 가 NULL 이면 partial-unique ``(reg_code) WHERE is_current`` 가 미발화 →
순진하게 INSERT 하면 재실행마다 regulation_id(IDENTITY)가 새로 발급되고 그 아래 clause/
authority 가 전부 중복 INSERT 된다(major #1). upsert_regulation 이 ``source_post_id`` 기준
SELECT-then-upsert 로 regulation_id 를 보존하는지(=하위 canonical 멱등 성립)를 2회 적재로 단언.
"""

from __future__ import annotations

import psycopg
import pytest

from app.ingest.board_seed import BOARDS
from app.ingest.models import (
    ParsedAuthority,
    ParsedClause,
    ParsedRegulation,
    RawAttachment,
    RawPost,
)

pytestmark = pytest.mark.integration

REG_BOARD_NO = 900000286  # 사내규정


@pytest.fixture
def conn(migrated_db):
    with psycopg.connect(migrated_db["libpq"]) as c:
        yield c


def _load_once(conn, board_id: int) -> tuple[int, int]:
    """post→regulation→clause/authority 한 사이클. (post_id, regulation_id) 반환."""
    from app.ingest.loader import (
        upsert_attachments,
        upsert_authority,
        upsert_clauses,
        upsert_post,
        upsert_regulation,
    )

    raw = RawPost(
        board_no=REG_BOARD_NO,
        art_no=5001,
        title="취업규칙",
        doc_type="regulation",
        body_text="제1조(목적) 이 규칙은 ...",
        content_hash="hash-v1",
        attachments=(
            RawAttachment(file_name="별표.hwp", kind="hwp", bizbox_file_seq=1, sha256="sha-a"),
        ),
    )
    pid = upsert_post(conn, raw, board_id)
    upsert_attachments(conn, pid, raw.attachments)

    reg = ParsedRegulation(title="취업규칙", reg_type="규정")  # reg_code=None (백필 컬럼)
    rid = upsert_regulation(conn, reg, board_id, pid)

    # canonical 은 보존된 regulation_id 기반 → 2회차도 동일해야 멱등.
    clauses = [
        ParsedClause(
            canonical_clause_id=f"R{rid}#a1", clause_label="제1조", text="목적",
            depth="article", order_seq=0, article_no=1,
        ),
        ParsedClause(
            canonical_clause_id=f"R{rid}#a1-p1", clause_label="제1조①", text="제1항",
            depth="paragraph", order_seq=1, article_no=1, paragraph_no=1,
            parent_canonical_id=f"R{rid}#a1",
        ),
    ]
    upsert_clauses(conn, rid, clauses)

    cells = [
        ParsedAuthority(
            canonical_authority_id=f"R{rid}#auth0", business_item="물품구매",
            action_type="전결", amount_min=None, amount_max=10_000_000, order_seq=0,
        ),
    ]
    upsert_authority(conn, rid, cells)
    return pid, rid


def test_regulation_chain_idempotent_without_regcode(conn) -> None:
    from app.ingest.loader import upsert_board_seed

    with conn.transaction(force_rollback=True):
        board_id = upsert_board_seed(conn, BOARDS)[REG_BOARD_NO]

        pid1, rid1 = _load_once(conn, board_id)
        assert conn.execute(
            "SELECT reg_code FROM regulation WHERE regulation_id=%s", (rid1,)
        ).fetchone()[0] is None, "1차 적재는 reg_code=NULL 경로여야 함"
        assert conn.execute(
            "SELECT curated FROM regulation WHERE regulation_id=%s", (rid1,)
        ).fetchone()[0] is False, "적재 규정은 curated=false (ADR-003)"

        n_reg = conn.execute("SELECT count(*) FROM regulation").fetchone()[0]
        n_cl = conn.execute("SELECT count(*) FROM clause").fetchone()[0]
        n_au = conn.execute("SELECT count(*) FROM authority_matrix").fetchone()[0]
        cl1 = sorted(
            r[0] for r in conn.execute(
                "SELECT canonical_clause_id FROM clause WHERE regulation_id=%s", (rid1,)
            )
        )
        au1 = sorted(
            r[0] for r in conn.execute(
                "SELECT canonical_authority_id FROM authority_matrix WHERE regulation_id=%s",
                (rid1,),
            )
        )

        # 2회차 — 동일 데이터.
        pid2, rid2 = _load_once(conn, board_id)

        assert pid2 == pid1, "post_id 가 재실행 간 보존되지 않음"
        assert rid2 == rid1, "★ regulation_id 가 재실행 간 보존되지 않음(멱등 사슬 ② 붕괴)"
        assert conn.execute("SELECT count(*) FROM regulation").fetchone()[0] == n_reg
        assert conn.execute("SELECT count(*) FROM clause").fetchone()[0] == n_cl
        assert conn.execute("SELECT count(*) FROM authority_matrix").fetchone()[0] == n_au

        cl2 = sorted(
            r[0] for r in conn.execute(
                "SELECT canonical_clause_id FROM clause WHERE regulation_id=%s", (rid2,)
            )
        )
        au2 = sorted(
            r[0] for r in conn.execute(
                "SELECT canonical_authority_id FROM authority_matrix WHERE regulation_id=%s",
                (rid2,),
            )
        )
        assert cl2 == cl1, "canonical_clause_id 동일성 붕괴"
        assert au2 == au1, "canonical_authority_id 동일성 붕괴"

        # clause 계층: 제1항의 parent 가 제1조로 해소됐는지.
        parent = conn.execute(
            "SELECT p.canonical_clause_id FROM clause c "
            "JOIN clause p ON c.parent_clause_id = p.clause_id "
            "WHERE c.canonical_clause_id = %s",
            (f"R{rid1}#a1-p1",),
        ).fetchone()
        assert parent is not None and parent[0] == f"R{rid1}#a1", "parent_clause_id 해소 실패"
