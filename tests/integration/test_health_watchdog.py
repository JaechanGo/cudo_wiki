"""plan §8 — 보드 수집 워치독(RISK-004).

``update_heartbeat`` 의 heartbeat_at/status/health 전이·consecutive_failures 누적/리셋과,
``detect_stalled`` 의 무신호 임계(NFR 신선도 ≤24h) 초과 감지를 검증한다.
"""

from __future__ import annotations

import psycopg
import pytest

from app.ingest.board_seed import BOARDS
from app.ingest.health import detect_stalled, update_heartbeat

pytestmark = pytest.mark.integration

NOTICE_BOARD_NO = 501000074
REG_BOARD_NO = 1401000286


@pytest.fixture
def conn(migrated_db):
    with psycopg.connect(migrated_db["libpq"]) as c:
        yield c


def test_update_heartbeat_transitions_and_failure_counter(conn) -> None:
    from app.ingest.loader import upsert_board_seed

    with conn.transaction(force_rollback=True):
        bid = upsert_board_seed(conn, BOARDS)[NOTICE_BOARD_NO]

        update_heartbeat(conn, bid, status="running", health="healthy")
        row = conn.execute(
            "SELECT status, health, heartbeat_at, consecutive_failures "
            "FROM ingest_state WHERE board_id = %s",
            (bid,),
        ).fetchone()
        assert row[0] == "running"
        assert row[1] == "healthy"
        assert row[2] is not None
        assert row[3] == 0

        # 연속 실패 누적.
        update_heartbeat(conn, bid, status="error", health="error")
        update_heartbeat(conn, bid, status="error", health="error")
        cf = conn.execute(
            "SELECT consecutive_failures FROM ingest_state WHERE board_id = %s", (bid,)
        ).fetchone()[0]
        assert cf == 2

        # 정상 복귀 시 리셋.
        update_heartbeat(conn, bid, status="idle", health="healthy")
        cf = conn.execute(
            "SELECT consecutive_failures FROM ingest_state WHERE board_id = %s", (bid,)
        ).fetchone()[0]
        assert cf == 0


def test_detect_stalled_flags_old_signal(conn) -> None:
    from app.ingest.loader import upsert_board_seed

    with conn.transaction(force_rollback=True):
        board_map = upsert_board_seed(conn, BOARDS)
        bid_fresh = board_map[NOTICE_BOARD_NO]
        bid_stale = board_map[REG_BOARD_NO]

        # 신선: 방금 성공.
        conn.execute(
            "UPDATE ingest_state SET last_success_at = now(), heartbeat_at = now() "
            "WHERE board_id = %s",
            (bid_fresh,),
        )
        # 무신호: 30시간 전(임계 24h 초과).
        conn.execute(
            "UPDATE ingest_state SET last_success_at = now() - interval '30 hours', "
            "heartbeat_at = now() - interval '30 hours' WHERE board_id = %s",
            (bid_stale,),
        )

        stalled = detect_stalled(conn, no_signal_hours=24)
        ids = {b.board_id for b in stalled}
        assert bid_stale in ids
        assert bid_fresh not in ids

        bh = next(b for b in stalled if b.board_id == bid_stale)
        assert bh.health == "stalled"
        assert bh.bizbox_board_no == REG_BOARD_NO
        assert bh.name == "사내규정"


def test_detect_stalled_excludes_never_run_boards(conn) -> None:
    """막 시드된(신호 NULL) 보드는 아직 stalled 아님(최초 실행 전)."""
    from app.ingest.loader import upsert_board_seed

    with conn.transaction(force_rollback=True):
        upsert_board_seed(conn, BOARDS)
        stalled = detect_stalled(conn, no_signal_hours=24)
        assert stalled == []
