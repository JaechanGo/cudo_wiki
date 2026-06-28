"""plan §10 — 동일 데이터 2회 적재 멱등 (post/attachment 행수 불변, content_hash no-op,
워터마크 단조 전진).
"""

from __future__ import annotations

from datetime import UTC, datetime

import psycopg
import pytest

from app.ingest.board_seed import BOARDS
from app.ingest.models import IngestCounts, RawAttachment, RawPost

pytestmark = pytest.mark.integration

NOTICE_BOARD_NO = 501000074  # 공지사항


@pytest.fixture
def conn(migrated_db):
    with psycopg.connect(migrated_db["libpq"]) as c:
        yield c


def _raw(content_hash: str) -> RawPost:
    return RawPost(
        board_no=NOTICE_BOARD_NO,
        art_no=777,
        title="연차 사용 안내",
        doc_type="notice",
        body_text="연차는 연 15일 부여된다.",
        content_hash=content_hash,
        attachments=(
            RawAttachment(file_name="guide.pdf", kind="pdf", bizbox_file_seq=1, sha256="p1"),
            RawAttachment(file_name="form.xlsx", kind="excel", bizbox_file_seq=2, sha256="x1"),
        ),
    )


def test_post_attachment_rowcount_invariant(conn) -> None:
    from app.ingest.loader import upsert_attachments, upsert_board_seed, upsert_post

    with conn.transaction(force_rollback=True):
        bid = upsert_board_seed(conn, BOARDS)[NOTICE_BOARD_NO]

        pid1 = upsert_post(conn, _raw("h1"), bid)
        ids1 = upsert_attachments(conn, pid1, _raw("h1").attachments)
        assert len(ids1) == 2
        n_post = conn.execute("SELECT count(*) FROM post").fetchone()[0]
        n_att = conn.execute("SELECT count(*) FROM attachment").fetchone()[0]

        # 2회차 동일 데이터.
        pid2 = upsert_post(conn, _raw("h1"), bid)
        ids2 = upsert_attachments(conn, pid2, _raw("h1").attachments)

        assert pid2 == pid1
        assert ids2 == ids1, "첨부 dedup 실패(같은 (post_id,file_seq) 재INSERT)"
        assert conn.execute("SELECT count(*) FROM post").fetchone()[0] == n_post
        assert conn.execute("SELECT count(*) FROM attachment").fetchone()[0] == n_att


def test_content_hash_noop_vs_update(conn) -> None:
    """동일 content_hash 면 UPDATE 미발화(no-op) → 행 물리위치(ctid) 불변. 다른 hash 면 갱신.

    단일 트랜잭션 내 INSERT→UPDATE 는 같은 xid 라 xmin 으론 구분 못 함 → ctid 로 검출
    (UPDATE 는 새 튜플 버전 생성 → ctid 변동, no-op 은 불변).
    """
    from app.ingest.loader import upsert_board_seed, upsert_post

    with conn.transaction(force_rollback=True):
        bid = upsert_board_seed(conn, BOARDS)[NOTICE_BOARD_NO]

        pid = upsert_post(conn, _raw("h1"), bid)
        ctid1 = conn.execute(
            "SELECT ctid FROM post WHERE post_id = %s", (pid,)
        ).fetchone()[0]

        # 동일 hash → no-op → ctid 불변.
        upsert_post(conn, _raw("h1"), bid)
        ctid2 = conn.execute(
            "SELECT ctid FROM post WHERE post_id = %s", (pid,)
        ).fetchone()[0]
        assert ctid2 == ctid1, "동일 content_hash 인데 행이 갱신됨(no-op 위반)"

        # 다른 hash → 실제 UPDATE → ctid 변동.
        upsert_post(conn, _raw("h2"), bid)
        ctid3 = conn.execute(
            "SELECT ctid FROM post WHERE post_id = %s", (pid,)
        ).fetchone()[0]
        assert ctid3 != ctid1, "content_hash 변경 시 갱신이 일어나야 함"
        assert conn.execute(
            "SELECT content_hash FROM post WHERE post_id = %s", (pid,)
        ).fetchone()[0] == "h2"


def test_watermark_monotonic_advance(conn) -> None:
    """advance_ingest_state — GREATEST 가드로 워터마크 후퇴 방지, total 누적."""
    from app.ingest.loader import advance_ingest_state, upsert_board_seed

    with conn.transaction(force_rollback=True):
        bid = upsert_board_seed(conn, BOARDS)[NOTICE_BOARD_NO]
        t1 = datetime(2026, 1, 1, tzinfo=UTC)
        t2 = datetime(2026, 2, 1, tzinfo=UTC)

        advance_ingest_state(conn, bid, 100, t1, IngestCounts(posts=2, attachments=1))
        row = conn.execute(
            "SELECT last_art_no, total_posts, total_attachments FROM ingest_state "
            "WHERE board_id = %s", (bid,)
        ).fetchone()
        assert row == (100, 2, 1)

        # 더 낮은 art_no → GREATEST 로 후퇴 안 함(100 유지).
        advance_ingest_state(conn, bid, 50, t1, IngestCounts(posts=1, attachments=0))
        last = conn.execute(
            "SELECT last_art_no FROM ingest_state WHERE board_id = %s", (bid,)
        ).fetchone()[0]
        assert last == 100, "워터마크가 후퇴함(GREATEST 가드 실패)"

        # 더 높은 art_no → 전진.
        advance_ingest_state(conn, bid, 200, t2, IngestCounts(posts=3, attachments=2))
        row = conn.execute(
            "SELECT last_art_no, last_posted_at, total_posts FROM ingest_state "
            "WHERE board_id = %s", (bid,)
        ).fetchone()
        assert row[0] == 200
        assert row[1] == t2
        assert row[2] == 2 + 1 + 3, "total_posts 누적 오류"
