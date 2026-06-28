"""★ Inspector minor #1 해소 — **커밋 경계를 넘는** reg_code=NULL 규정 멱등.

자매 테스트 ``test_regulation_idempotent_no_regcode`` 는 단일 트랜잭션 ``force_rollback``
안에서 ``_load_once`` 를 2회 호출한다 — 2회차의 SELECT-then-upsert 가 **같은 미커밋
스냅샷**을 보므로 "1배치를 COMMIT 한 뒤 새 트랜잭션이 그 규정을 SELECT 로 재발견하는가"
라는 진짜 커밋 경계 멱등은 검증하지 못한다.

본 테스트는 1배치 COMMIT → 2배치 COMMIT 로 **별도 트랜잭션(별도 커넥션) 2회 적재**하여,
``upsert_regulation`` 의 source_post_id 기준 보존이 커밋 경계를 넘어서도 성립함을 단언한다:
regulation_id·canonical_clause_id·canonical_authority_id·post_id 가 두 배치에서 동일하고,
행수가 1배치 후와 불변이며, 워터마크가 후퇴하지 않는다.

격리: ``migrated_db`` 는 session-scope 이고 본 테스트는 데이터를 COMMIT 하므로 다른 통합
테스트(절대 행수·공유 보드 워터마크 단언)에 누수되면 안 된다. → BOARDS 시드·다른 테스트와
겹치지 않는 **전용 bizbox_board_no** 를 쓰고, teardown 에서 자신이 넣은 모든 행(authority/
clause/regulation/attachment/post/ingest_state/board)을 삭제한다.
"""

from __future__ import annotations

import psycopg
import pytest

from app.ingest.models import (
    BoardSeed,
    IngestCounts,
    ParsedAuthority,
    ParsedClause,
    ParsedRegulation,
    RawAttachment,
    RawPost,
)

pytestmark = pytest.mark.integration

# BOARDS·다른 통합테스트와 겹치지 않는 전용 자연키(이 테스트 전용, teardown 으로 회수).
DEDICATED_BOARD = BoardSeed(
    bizbox_board_no=1409999007,
    name="멱등커밋테스트(task007)",
    slug="task007-committed-idem",
    board_class="regulation",
    default_chunk_strategy="article",
    use_mecab_parallel=True,
)
ART_NO = 7007  # 전용 보드 안의 글 번호(워터마크 단언용).


@pytest.fixture
def dedicated_board(migrated_db):
    """전용 보드를 COMMIT 시드한 뒤 board_id 를 내주고, 테스트 후 전 데이터 회수.

    별도 커넥션 2배치가 보려면 보드는 커밋돼 있어야 한다. teardown 은 FK 역순으로 삭제해
    session-scope DB 에 본 테스트 흔적을 남기지 않는다(자매 테스트의 절대 행수·워터마크 보호).
    """
    from app.ingest.loader import upsert_board_seed

    dsn = migrated_db["libpq"]
    with psycopg.connect(dsn) as c:
        board_id = upsert_board_seed(c, [DEDICATED_BOARD])[DEDICATED_BOARD.bizbox_board_no]
        c.commit()
    try:
        yield dsn, board_id
    finally:
        with psycopg.connect(dsn) as c:
            c.execute(
                "DELETE FROM authority_matrix WHERE regulation_id IN "
                "(SELECT regulation_id FROM regulation WHERE board_id = %s)",
                (board_id,),
            )
            c.execute(
                "DELETE FROM clause WHERE regulation_id IN "
                "(SELECT regulation_id FROM regulation WHERE board_id = %s)",
                (board_id,),
            )
            c.execute("DELETE FROM regulation WHERE board_id = %s", (board_id,))
            c.execute(
                "DELETE FROM attachment WHERE post_id IN "
                "(SELECT post_id FROM post WHERE board_id = %s)",
                (board_id,),
            )
            c.execute("DELETE FROM post WHERE board_id = %s", (board_id,))
            c.execute("DELETE FROM ingest_state WHERE board_id = %s", (board_id,))
            c.execute("DELETE FROM board WHERE board_id = %s", (board_id,))
            c.commit()


def _load_once(conn: psycopg.Connection, board_id: int) -> tuple[int, int]:
    """post→regulation→clause/authority + 워터마크 1사이클. (post_id, regulation_id) 반환.

    자매 테스트와 동일한 reg_code=NULL 경로. canonical id 는 보존된 regulation_id 기반이라
    2회차도 동일해야 멱등(=ON CONFLICT no-op).
    """
    from app.ingest.loader import (
        advance_ingest_state,
        upsert_attachments,
        upsert_authority,
        upsert_clauses,
        upsert_post,
        upsert_regulation,
    )

    raw = RawPost(
        board_no=DEDICATED_BOARD.bizbox_board_no,
        art_no=ART_NO,
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

    reg = ParsedRegulation(title="취업규칙", reg_type="규정")  # reg_code=None
    rid = upsert_regulation(conn, reg, board_id, pid)

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

    advance_ingest_state(
        conn, board_id, last_art_no=ART_NO, last_posted_at=None,
        counts=IngestCounts(posts=1, attachments=1, failures=0),
    )
    return pid, rid


def _load_committed(dsn: str, board_id: int) -> tuple[int, int]:
    """별도 커넥션에서 1사이클 적재 후 **실제 COMMIT**(커밋 경계 시뮬레이션)."""
    with psycopg.connect(dsn) as c:
        pid, rid = _load_once(c, board_id)
        c.commit()
    return pid, rid


def _counts(dsn: str, board_id: int, rid: int) -> dict[str, int]:
    with psycopg.connect(dsn) as c:
        return {
            "post": c.execute(
                "SELECT count(*) FROM post WHERE board_id = %s", (board_id,)
            ).fetchone()[0],
            "regulation": c.execute(
                "SELECT count(*) FROM regulation WHERE board_id = %s", (board_id,)
            ).fetchone()[0],
            "clause": c.execute(
                "SELECT count(*) FROM clause WHERE regulation_id = %s", (rid,)
            ).fetchone()[0],
            "authority": c.execute(
                "SELECT count(*) FROM authority_matrix WHERE regulation_id = %s", (rid,)
            ).fetchone()[0],
        }


def _canon_sets(dsn: str, rid: int) -> tuple[list[str], list[str]]:
    with psycopg.connect(dsn) as c:
        cl = sorted(
            r[0] for r in c.execute(
                "SELECT canonical_clause_id FROM clause WHERE regulation_id = %s", (rid,)
            )
        )
        au = sorted(
            r[0] for r in c.execute(
                "SELECT canonical_authority_id FROM authority_matrix WHERE regulation_id = %s",
                (rid,),
            )
        )
    return cl, au


def _watermark(dsn: str, board_id: int) -> int:
    with psycopg.connect(dsn) as c:
        return c.execute(
            "SELECT last_art_no FROM ingest_state WHERE board_id = %s", (board_id,)
        ).fetchone()[0]


def test_regulation_chain_idempotent_across_commit_boundary(dedicated_board) -> None:
    dsn, board_id = dedicated_board

    # ── 1배치: 적재 + COMMIT ─────────────────────────────────────────────
    pid1, rid1 = _load_committed(dsn, board_id)

    with psycopg.connect(dsn) as c:
        assert c.execute(
            "SELECT reg_code FROM regulation WHERE regulation_id = %s", (rid1,)
        ).fetchone()[0] is None, "1차 적재는 reg_code=NULL 경로여야 함"
        assert c.execute(
            "SELECT curated FROM regulation WHERE regulation_id = %s", (rid1,)
        ).fetchone()[0] is False, "적재 규정은 curated=false (ADR-003)"

    counts1 = _counts(dsn, board_id, rid1)
    cl1, au1 = _canon_sets(dsn, rid1)
    wm1 = _watermark(dsn, board_id)
    assert wm1 == ART_NO

    # ── 2배치: 동일 데이터 별도 트랜잭션 적재 + COMMIT ───────────────────
    pid2, rid2 = _load_committed(dsn, board_id)

    # 커밋 경계를 넘어 id 가 보존돼야 멱등(자매 테스트가 못 잡는 지점).
    assert pid2 == pid1, "post_id 가 커밋 경계 재실행 간 보존되지 않음"
    assert rid2 == rid1, "★ regulation_id 가 커밋 경계 재실행 간 보존되지 않음(멱등 사슬 ② 붕괴)"

    counts2 = _counts(dsn, board_id, rid1)
    assert counts2 == counts1, f"행수 불변 위배: {counts1} → {counts2}"

    cl2, au2 = _canon_sets(dsn, rid1)
    assert cl2 == cl1, "canonical_clause_id 동일성 붕괴"
    assert au2 == au1, "canonical_authority_id 동일성 붕괴"

    # 워터마크 후퇴 없음(GREATEST 가드).
    wm2 = _watermark(dsn, board_id)
    assert wm2 == wm1 == ART_NO, "워터마크 후퇴/변동"

    # clause 계층: 제1항 parent 가 제1조로 해소(커밋 후에도).
    with psycopg.connect(dsn) as c:
        parent = c.execute(
            "SELECT p.canonical_clause_id FROM clause c "
            "JOIN clause p ON c.parent_clause_id = p.clause_id "
            "WHERE c.canonical_clause_id = %s",
            (f"R{rid1}#a1-p1",),
        ).fetchone()
    assert parent is not None and parent[0] == f"R{rid1}#a1", "parent_clause_id 해소 실패"
