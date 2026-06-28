"""배치 전용 동기 psycopg3 커넥션 (인제스트 파이프라인).

런타임 MCP 서버는 ``app/common/db.py`` 의 AsyncConnectionPool 을 쓰고, 인제스트 배치는
이 모듈의 **동기 단발 커넥션**을 쓴다 — 배치/런타임 격리(plan §0·§1·§19).

DSN 은 ``Settings.dsn`` (libpq ``postgresql://``) 재사용. 풀을 쓰지 않는 이유:
배치는 단일 프로세스·순차 보드 순회라 커넥션 1개로 충분하고, 풀 수명주기(open/close)
관리가 불필요하다. 트랜잭션 경계는 "1글=1커밋"(loader, 파트2)이 직접 잡는다.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

import psycopg

from app.common.config import get_settings

if TYPE_CHECKING:
    from psycopg import Connection


@contextmanager
def batch_connection(*, autocommit: bool = False) -> Iterator[Connection]:
    """배치 작업용 동기 psycopg3 커넥션 컨텍스트매니저.

    정상 종료 시 commit, 예외 시 rollback 후 재던짐, 어느 경우든 close.
    ``autocommit=True`` 면 커밋/롤백을 호출부에 위임(DDL·진단용).

    Args:
        autocommit: True 면 자동커밋 모드(컨텍스트 매니저가 commit/rollback 안 함).

    Yields:
        열린 psycopg3 동기 커넥션.
    """
    conn = psycopg.connect(get_settings().dsn, autocommit=autocommit)
    try:
        yield conn
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            conn.rollback()
        raise
    finally:
        conn.close()
