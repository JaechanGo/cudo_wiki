"""보드 수집 워치독 (plan §8, must, RISK-004).

- ``update_heartbeat``: 보드 실행 중 heartbeat_at=now() + status 전이 + consecutive_failures
  누적(status='error')/리셋(그 외)을 기록한다. total_*/last_success_at 전진은
  ``loader.advance_ingest_state`` 책임(여기는 살아있음 신호·실패 카운터).
- ``detect_stalled``: last_success_at/heartbeat_at 의 최신 신호가 임계(no_signal_hours) 초과한
  보드를 stalled 로 감지(NFR 신선도 ≤24h 정합). 한 번도 실행 안 한(신호 NULL) 보드는 제외.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.ingest.models import BoardHealth

if TYPE_CHECKING:
    from psycopg import Connection


def update_heartbeat(
    conn: Connection, board_id: int, status: str, health: str
) -> None:
    """heartbeat 갱신 + status/health 전이 + 연속 실패 카운터.

    status='error' 면 consecutive_failures 를 +1, 그 외 상태면 0 으로 리셋한다.
    """
    conn.execute(
        """
        UPDATE ingest_state SET
          status = %s,
          health = %s,
          heartbeat_at = now(),
          last_run_at = now(),
          consecutive_failures = CASE WHEN %s = 'error'
                                      THEN consecutive_failures + 1 ELSE 0 END
        WHERE board_id = %s
        """,
        (status, health, status, board_id),
    )


def detect_stalled(conn: Connection, *, no_signal_hours: int = 24) -> list[BoardHealth]:
    """무신호 임계 초과 보드 → stalled BoardHealth 목록.

    신호 = COALESCE(last_success_at, heartbeat_at) 의 최신값. 둘 다 NULL(미실행)이면 제외.
    임계(now() - no_signal_hours) 보다 오래된 보드만 반환하며 health='stalled' 로 표시한다.
    """
    rows = conn.execute(
        """
        SELECT s.board_id, b.bizbox_board_no, b.name, s.status,
               s.heartbeat_at, s.last_run_at, s.last_success_at,
               s.consecutive_failures, s.total_posts, s.total_attachments, s.error_msg
        FROM ingest_state s
        JOIN board b ON b.board_id = s.board_id
        WHERE COALESCE(s.last_success_at, s.heartbeat_at) IS NOT NULL
          AND GREATEST(
                COALESCE(s.last_success_at, s.heartbeat_at),
                COALESCE(s.heartbeat_at, s.last_success_at)
              ) < now() - make_interval(hours => %s)
        ORDER BY s.board_id
        """,
        (no_signal_hours,),
    ).fetchall()
    return [
        BoardHealth(
            board_id=r[0],
            bizbox_board_no=r[1],
            name=r[2],
            status=r[3],
            health="stalled",
            heartbeat_at=r[4],
            last_run_at=r[5],
            last_success_at=r[6],
            consecutive_failures=r[7],
            total_posts=r[8],
            total_attachments=r[9],
            error_msg=r[10],
        )
        for r in rows
    ]
